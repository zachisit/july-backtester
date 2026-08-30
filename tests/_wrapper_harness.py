"""Shared harness for the four test modules that drive `main.py` as a subprocess.

Issue #366. Four modules — `test_empty_comparison_tickers`, `test_main_cli`,
`test_startup_validation`, `test_ui_output` — each hand-rolled the same thing:
write a wrapper script that patches `config.CONFIG`, imports `main`, calls
`main.main()`, and run it as a subprocess.

WHY THIS FILE EXISTS RATHER THAN FOUR COPIES
---------------------------------------------
Both invariants the copies must hold have already been violated in production,
and each was then fixed FOUR TIMES BY HAND:

  #362  the `if __name__ == "__main__"` guard. Missing from all four. Under the
        spawn start method every Pool worker re-imports the parent's __main__ —
        the wrapper — re-enters main.main() during bootstrap and deadlocks the
        parent. Cost: `pytest -m slow` reported "7 skipped" in 842s while
        testing nothing, for as long as it had been broken.

  #362  `encoding="utf-8"`. Missing from all four. main.py reconfigures its own
        streams to UTF-8; reading them back with `text=True` and no encoding
        uses the locale default — cp1252 on Windows — which cannot decode the
        U+2501 in main.py's own banner. subprocess raises inside _readerthread,
        so it does not propagate: `result.stderr` comes back None and every
        assertion becomes `TypeError: argument of type 'NoneType' is not
        iterable`.

The second fix reached six of seven call sites on the first attempt. The
seventh sat in the SAME FILE as one that was fixed, and was found by an AST
walk rather than by reading. That is the argument for one implementation: a
copy that drifts is indistinguishable from one that does not until someone
audits all four.

A source-text guard was tried and is not sufficient — it has now been
structurally blind three times (keyed on a name one path never used, then on a
node type the code stopped using, then on a line window that excluded the line
under judgement). The durable fix is to have one thing to get right.
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

#: A wrapper run against the parquet fixture takes ~3s on macOS and ~6-9s on an
#: idle Windows box. 120s is therefore a ~13x margin. Contention is real
#: though — CPU load was measured inflating the same seven tests 4x, to ~38s —
#: so a timeout is *probably* a hang rather than certainly one.
DEFAULT_TIMEOUT = 120


def wrapper_source(patches: dict, cli_args=(), project_root: str = PROJECT_ROOT) -> str:
    """Build the wrapper script.

    `main.main()` sits under an `if __name__ == "__main__"` guard, and the
    `config.CONFIG` patches deliberately do NOT: spawn children re-import this
    module, so the patches must apply there to reach the workers, while
    main.main() must not run again during bootstrap.

    Both halves are load-bearing and both are pinned by
    tests/test_empty_comparison_tickers.py::TestWrapperSource, which executes
    the source under `__name__ = "__mp_main__"` rather than grepping it.
    """
    lines = [
        "import sys",
        f"sys.path.insert(0, {repr(project_root)})",
        "import config",
    ]
    for key, value in patches.items():
        lines.append(f"config.CONFIG[{repr(key)}] = {repr(value)}")
    lines.append("import main")
    lines.append('if __name__ == "__main__":')
    lines.append(f"    sys.argv = {repr(['main.py'] + list(cli_args))}")
    lines.append("    main.main()")
    return "\n".join(lines) + "\n"


def run_wrapper(tmp_path, patches: dict, cli_args=(), *, env: dict | None = None,
                timeout: int = DEFAULT_TIMEOUT,
                expect_simulation: bool = False) -> subprocess.CompletedProcess:
    """Write the wrapper and run it.

    `expect_simulation` asserts the run did real work. It defaults to False
    because most callers pass `--dry-run` and exit before any simulation; the
    modules that DO expect one opt in, because their assertions are mostly of
    the form `"..." not in result.stderr`, which holds trivially when main()
    produced no output at all.
    """
    wrapper = tmp_path / "run_patched.py"
    wrapper.write_text(wrapper_source(patches, cli_args), encoding="utf-8")

    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    try:
        result = subprocess.run(
            [sys.executable, str(wrapper)],
            capture_output=True,
            text=True,
            encoding="utf-8",      # see the module docstring; NOT the locale default
            errors="replace",
            env=run_env,
            cwd=PROJECT_ROOT,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        # NOT a skip. #362 is what happens when a deadlock is reported as a slow
        # machine: "7 skipped" and "7 passed" read identically in a summary line
        # and the reason blames your hardware, so nobody looks.
        pytest.fail(
            f"Wrapper subprocess did not finish in {timeout}s. It normally takes "
            f"~3s on macOS and ~6-9s on Windows on an idle box, so a timeout is "
            f"PROBABLY the #362 multiprocessing bootstrap deadlock this guard "
            f"exists to prevent. Rule out a loaded machine first — CPU "
            f"contention was measured inflating these same runs 4x.")

    if expect_simulation:
        assert result.returncode == 0, (
            f"exit {result.returncode}\n{result.stderr[-2000:]}")
        assert "All portfolio simulations complete" in result.stderr, (
            "the run produced no simulation — every absence-assertion in the "
            "caller would pass vacuously\n" + result.stderr[-2000:])
        assert "Could not fetch data for any symbols" not in result.stderr, (
            "the fixture symbol was filtered out before any worker ran\n"
            + result.stderr[-2000:])
    return result
