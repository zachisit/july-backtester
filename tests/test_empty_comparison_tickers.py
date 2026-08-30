"""
tests/test_empty_comparison_tickers.py

Regression tests for the empty comparison_tickers code path.

Background
----------
PR #91 removed the silent 4-ticker fallback from parse_comparison_tickers().
PR #92/93 allowed comparison_tickers=[] to run without raising, deriving the
data period from config start_date/end_date instead of fetching SPY.

Bug caught in manual QA (issue #92):
    When comparison_tickers=[] the engine raised:
        NameError: name 'spy_df' is not defined
    at the WFA split-date calculation because the else-branch that handles
    the empty case set _spy_actual_start/_spy_actual_end but never assigned
    spy_df, which is referenced on the next line:
        wfa_split_date = _get_split_date(..., df=spy_df, ...)

These tests exercise:
    1. parse_comparison_tickers([]) returns a valid empty structure
       (unit — no subprocess needed)
    2. main() with comparison_tickers=[] + parquet provider + AAPL fixture
       completes without NameError (subprocess — exercises the real fetch block)
    3. The "Data Period (config)" log line appears when no comparison tickers
       are configured
    4. No B&H log lines appear when benchmarks list is empty
    5. main() with comparison_tickers=[] still honours wfa_split_ratio
       (the spy_df=None path must reach _get_split_date without crashing)
    6. A missing comparison_tickers key (None / absent) still raises ValueError
       to prevent silent misconfiguration
"""

import os
import subprocess
import sys
import types

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_FIXTURE_DIR = os.path.join(PROJECT_ROOT, "tests", "fixtures", "parquet_data")
_FIXTURE_AVAILABLE = os.path.isdir(_FIXTURE_DIR) and any(
    f.endswith(".parquet") for f in os.listdir(_FIXTURE_DIR) if os.path.isfile(os.path.join(_FIXTURE_DIR, f))
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wrapper_source(patches: dict, cli_args=()) -> str:
    """
    Build the wrapper script that applies CONFIG patches then calls main.main().

    The `main.main()` call MUST sit under an `if __name__ == "__main__"` guard
    (#362). `main.py` builds a multiprocessing Pool, and under the spawn start
    method — macOS and Windows — every worker re-imports the parent's __main__,
    which is this wrapper. Without the guard each child re-entered main.main()
    during bootstrap, died on `RuntimeError: An attempt has been made to start
    a new process before the current process has finished its bootstrapping
    phase`, and the parent then waited on them forever. All 7 tests below hit
    the 120s timeout and self-skipped, so the whole `slow` marker reported
    "7 skipped" in 14 minutes while testing nothing. Guarded, the same run
    finishes in ~3s on macOS, ~6-9s on Windows (idle box).

    The CONFIG patches stay at module scope deliberately: spawn children
    re-import this module, so they must re-apply there to reach the workers.
    """
    lines = [
        "import sys",
        f"sys.path.insert(0, {repr(PROJECT_ROOT)})",
        "import config",
    ]
    for k, v in patches.items():
        lines.append(f"config.CONFIG[{repr(k)}] = {repr(v)}")
    lines.append("import main")
    lines.append('if __name__ == "__main__":')
    lines.append(f"    sys.argv = {repr(['main.py'] + list(cli_args))}")
    lines.append("    main.main()")
    return "\n".join(lines) + "\n"


def _run_patched(tmp_path, patches: dict, cli_args=()) -> subprocess.CompletedProcess:
    """Run the wrapper from :func:`_wrapper_source` as a subprocess.

    Asserts the run did real work, because six of the seven tests below assert
    only the ABSENCE of a string in stderr — which holds trivially if main()
    produced no output at all. Verified: with a nonexistent symbol, or with
    `min_bars_required` above the fixture's 62 rows, main() logs "Could not
    fetch data for any symbols" / "No simulation tasks were generated", exits 0,
    never starts a worker, and ALL SEVEN assertions still pass. The
    _BASE_PATCHES comment names that risk; nothing enforced it.
    """
    wrapper = tmp_path / "run_patched.py"
    wrapper.write_text(_wrapper_source(patches, cli_args), encoding="utf-8")

    try:
        result = subprocess.run(
            [sys.executable, str(wrapper)],
            capture_output=True,
            text=True,
            # main.py:27-28 reconfigures its own streams to UTF-8. Reading them
            # back with text=True and no encoding uses the locale default —
            # cp1252 on Windows — which cannot decode the U+2501 rule in
            # main.py's own banner. subprocess raises inside _readerthread, so
            # it does not propagate: it surfaces as an unhandled-thread warning
            # and `result.stderr` comes back None, turning every assertion in
            # this file into `TypeError: argument of type 'NoneType' is not
            # iterable`. Invisible until #362 was fixed, because the deadlock
            # timed out first and nothing ever decoded anything.
            encoding="utf-8",
            errors="replace",
            cwd=PROJECT_ROOT,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"exit {result.returncode}\n{result.stderr[-2000:]}")
        assert "All portfolio simulations complete" in result.stderr, (
            "the run produced no simulation — every absence-assertion in "
            "this file would pass vacuously\n" + result.stderr[-2000:])
        assert "Could not fetch data for any symbols" not in result.stderr, (
            "the fixture symbol was filtered out before any worker ran\n"
            + result.stderr[-2000:])
        return result
    except subprocess.TimeoutExpired:
        # NOT a skip. This run takes ~3s on macOS and ~6-9s on Windows idle, so 120s
        # means a deadlock, and #362 is what happens when a deadlock is
        # reported as "your machine is slow": 7 skipped and 7 passed read
        # identically in a summary line, and these were the only tests
        # exercising main() end-to-end through a real Pool.
        pytest.fail(
            "Wrapper subprocess did not finish in 120s. It normally takes ~3s on "
            "macOS and ~6-9s on Windows on an idle box, so 120s is a ~13x "
            "margin and a timeout here is PROBABLY the #362 multiprocessing "
            "bootstrap deadlock this guard used to hide. Rule out a loaded "
            "machine first — CPU contention was measured inflating these same "
            "seven tests 4x, to ~38s.")


# ---------------------------------------------------------------------------
# Unit tests — no subprocess
# ---------------------------------------------------------------------------

class TestParseEmptyList:
    """parse_comparison_tickers([]) must return a valid empty structure."""

    def test_empty_list_returns_empty_benchmarks(self):
        from helpers.comparison_tickers import parse_comparison_tickers
        result = parse_comparison_tickers({"comparison_tickers": []})
        assert result["benchmarks"] == []

    def test_empty_list_returns_empty_dependencies(self):
        from helpers.comparison_tickers import parse_comparison_tickers
        result = parse_comparison_tickers({"comparison_tickers": []})
        assert result["dependencies"] == {}

    def test_empty_list_returns_empty_all_symbols(self):
        from helpers.comparison_tickers import parse_comparison_tickers
        result = parse_comparison_tickers({"comparison_tickers": []})
        assert result["all_symbols"] == []

    def test_missing_key_still_raises(self):
        from helpers.comparison_tickers import parse_comparison_tickers
        with pytest.raises(ValueError, match="comparison_tickers"):
            parse_comparison_tickers({})

    def test_none_value_still_raises(self):
        from helpers.comparison_tickers import parse_comparison_tickers
        with pytest.raises(ValueError, match="comparison_tickers"):
            parse_comparison_tickers({"comparison_tickers": None})


# ---------------------------------------------------------------------------
# Unit tests — run_portfolio_simulation with spy_df=None / vix_df=None
# ---------------------------------------------------------------------------

_SKIP_NO_FIXTURE = pytest.mark.skipif(
    not _FIXTURE_AVAILABLE,
    reason="Parquet fixture directory not present — run from project root.",
)


@_SKIP_NO_FIXTURE
class TestSimulationWithNoneComparisons:
    """
    Direct unit tests for portfolio_simulations.py when spy_df / vix_df are None.

    This is the root-cause fix for the AttributeError:
        'NoneType' object has no attribute 'loc'
    raised inside run_portfolio_simulation when comparison_tickers=[].

    These tests are fast (no subprocess, no multiprocessing) and target the
    exact lines that needed the None-guard.
    """

    _SIM_CONFIG = {
        "slippage_pct": 0.0,
        "commission_per_share": 0.0,
        "execution_time": "open",
        "max_pct_adv": 0,
        "volume_impact_coeff": 0.0,
        "risk_free_rate": 0.05,
        "htb_rate_annual": 0.0,
        "timeframe": "D",
        "timeframe_multiplier": 1,
    }

    @pytest.fixture(scope="class")
    def aapl_df(self):
        from services.parquet_service import get_price_data
        df = get_price_data("AAPL", "2023-01-01", "2023-12-31", {"parquet_data_dir": _FIXTURE_DIR})
        assert df is not None
        df.index = df.index.tz_localize(None)
        return df

    def test_spy_none_does_not_raise(self, aapl_df):
        """Regression: spy_df=None must not raise AttributeError on .loc access."""
        from unittest.mock import patch
        from helpers.portfolio_simulations import run_portfolio_simulation
        from helpers.indicators import sma_crossover_logic

        sig_df = sma_crossover_logic(aapl_df.copy(), fast=5, slow=10)
        signals = {"AAPL": sig_df["Signal"]}

        with patch.dict("config.CONFIG", self._SIM_CONFIG):
            result = run_portfolio_simulation(
                portfolio_data={"AAPL": aapl_df},
                signals=signals,
                initial_capital=100_000,
                allocation_pct=0.10,
                spy_df=None,
                vix_df=None,
                tnx_df=None,
                stop_config={"type": "none"},
            )
        assert result is not None

    def test_vix_none_does_not_raise(self, aapl_df):
        """vix_df=None must not raise AttributeError on .loc access."""
        from unittest.mock import patch
        from helpers.portfolio_simulations import run_portfolio_simulation
        from helpers.indicators import sma_crossover_logic

        sig_df = sma_crossover_logic(aapl_df.copy(), fast=5, slow=10)
        signals = {"AAPL": sig_df["Signal"]}

        with patch.dict("config.CONFIG", self._SIM_CONFIG):
            result = run_portfolio_simulation(
                portfolio_data={"AAPL": aapl_df},
                signals=signals,
                initial_capital=100_000,
                allocation_pct=0.10,
                spy_df=None,
                vix_df=None,
                tnx_df=None,
                stop_config={"type": "none"},
            )
        assert result is not None

    def test_entry_spy_features_absent_when_spy_none(self, aapl_df):
        """When spy_df=None, entry_SPY_* columns must not appear in trade log."""
        from unittest.mock import patch
        from helpers.portfolio_simulations import run_portfolio_simulation
        from helpers.indicators import sma_crossover_logic

        sig_df = sma_crossover_logic(aapl_df.copy(), fast=5, slow=10)
        signals = {"AAPL": sig_df["Signal"]}

        with patch.dict("config.CONFIG", self._SIM_CONFIG):
            result = run_portfolio_simulation(
                portfolio_data={"AAPL": aapl_df},
                signals=signals,
                initial_capital=100_000,
                allocation_pct=0.10,
                spy_df=None,
                vix_df=None,
                tnx_df=None,
                stop_config={"type": "none"},
            )

        trade_log = result.get("trade_log", [])
        for trade in trade_log:
            assert "entry_SPY_RSI_14" not in trade
            assert "entry_SPY_SMA200_dist_pct" not in trade
            assert "entry_VIX_Close" not in trade

    def test_result_has_expected_keys(self, aapl_df):
        """Result dict must have the standard keys regardless of None comparisons."""
        from unittest.mock import patch
        from helpers.portfolio_simulations import run_portfolio_simulation
        from helpers.indicators import sma_crossover_logic

        sig_df = sma_crossover_logic(aapl_df.copy(), fast=5, slow=10)
        signals = {"AAPL": sig_df["Signal"]}

        with patch.dict("config.CONFIG", self._SIM_CONFIG):
            result = run_portfolio_simulation(
                portfolio_data={"AAPL": aapl_df},
                signals=signals,
                initial_capital=100_000,
                allocation_pct=0.10,
                spy_df=None,
                vix_df=None,
                tnx_df=None,
                stop_config={"type": "none"},
            )

        for key in ("Trades", "trade_log", "portfolio_timeline"):
            assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Subprocess integration tests — require parquet fixtures
# ---------------------------------------------------------------------------


@_SKIP_NO_FIXTURE
@pytest.mark.slow
class TestEmptyComparisonTickersRun:
    """
    Full main() subprocess runs using parquet fixtures + comparison_tickers=[].

    Marked @slow — excluded from the default test run to avoid CPU saturation
    from multiprocessing worker startup. Run explicitly with:
        pytest -m slow tests/test_empty_comparison_tickers.py

    The core regression (AttributeError in workers) is covered without
    subprocess overhead by TestSimulationWithNoneComparisons above.
    """

    _BASE_PATCHES = {
        "data_provider": "parquet",
        "comparison_tickers": [],
        "portfolios": {"My Symbols": ["AAPL"]},
        # AAPL fixture has 62 rows — must be below this or the symbol is filtered
        # before any worker runs, giving a false-green test
        "min_bars_required": 10,
        # Run one strategy only — keeps subprocess runtime well under the 120s
        # timeout in _run_patched (the whole run takes ~3s on macOS, ~6-9s on
        # Windows)
        "strategies": ["SMA Crossover (20d/50d)"],
        "wfa_split_ratio": None,
        "wfa_folds": None,
        "export_ml_features": False,
        "save_individual_trades": False,
        "sensitivity_sweep_enabled": False,
    }

    def _patches_with(self, **overrides):
        patches = dict(self._BASE_PATCHES)
        patches["parquet_data_dir"] = _FIXTURE_DIR
        patches.update(overrides)
        return patches

    def test_no_name_error(self, tmp_path):
        """Regression: spy_df NameError must not occur with empty comparison_tickers."""
        result = _run_patched(tmp_path, self._patches_with(), cli_args=[])
        assert "NameError" not in result.stderr, result.stderr

    def test_no_attribute_error_on_none_spy_df(self, tmp_path):
        """
        Regression: with comparison_tickers=[], spy_df_local=None inside workers.
        portfolio_simulations.py must guard spy_df/vix_df before .loc[] access.
        Previously crashed: AttributeError: 'NoneType' object has no attribute 'loc'
        """
        result = _run_patched(tmp_path, self._patches_with(), cli_args=[])
        assert "AttributeError" not in result.stderr, result.stderr
        assert "FATAL ERROR IN WORKER" not in result.stderr, result.stderr

    def test_exits_zero_or_clean_failure(self, tmp_path):
        """Run must not crash with any unhandled exception or worker fatal error.

        The name promised an exit-code check that the body never made, so
        `sys.exit(1)` with a clean log passed. The check now lives in
        `_run_patched` and covers all seven call sites, not just this one — so
        it is deliberately NOT repeated here: a duplicate assert after the
        helper has already asserted can never be the one that fails, and a
        hollow assertion in a PR about hollow assertions is worse than none.
        """
        result = _run_patched(tmp_path, self._patches_with(), cli_args=[])
        combined = result.stdout + result.stderr
        assert "Traceback" not in combined, combined
        assert "FATAL ERROR IN WORKER" not in combined, combined

    def test_config_period_log_line_appears(self, tmp_path):
        """When comparison_dfs is empty the 'Data Period (config)' line must appear."""
        result = _run_patched(tmp_path, self._patches_with(), cli_args=[])
        assert "Data Period (config)" in result.stderr, result.stderr

    def test_no_bnh_log_lines(self, tmp_path):
        """No B&H return lines should be logged when benchmarks list is empty."""
        result = _run_patched(tmp_path, self._patches_with(), cli_args=[])
        assert "B&H:" not in result.stderr, result.stderr

    def test_wfa_enabled_does_not_crash(self, tmp_path):
        """
        With wfa_split_ratio set, _get_split_date is called with spy_df=None.
        This must not raise — wfa.get_split_date handles df=None via calendar
        day splitting.
        """
        result = _run_patched(
            tmp_path,
            self._patches_with(wfa_split_ratio=0.8),
            cli_args=[],
        )
        combined = result.stdout + result.stderr
        assert "NameError" not in combined, combined
        assert "Traceback" not in combined, combined
        assert "FATAL ERROR IN WORKER" not in combined, combined

    def test_actual_data_period_line_not_present(self, tmp_path):
        """'Actual Data Period' line should NOT appear — only 'Data Period (config)'."""
        result = _run_patched(tmp_path, self._patches_with(), cli_args=[])
        assert "Actual Data Period" not in result.stderr, result.stderr


class TestWrapperSource:
    """Pins the generated wrapper directly (#362).

    Fast, no subprocess — so the harness contract is checked even when the
    `slow` marker is deselected, which is the default. That matters here: the
    bug it guards made every slow test report "skipped", and a deselected suite
    reports nothing at all, so nothing in a default run could have caught it.
    """

    @staticmethod
    def _exec_as(src, module_name):
        """Execute the wrapper under a chosen __name__, with `main` and
        `config` stubbed. Returns (main_was_called, captured_config).

        This executes the real spawn-child contract rather than grepping the
        source. A purely textual pin does not hold: emitting the guard with a
        `pass` body and leaving `main.main()` at module scope satisfies every
        string assertion while fully reintroducing the #362 deadlock.
        """
        calls = []
        stub_main = types.ModuleType("main")
        stub_main.main = lambda: calls.append(1)
        stub_config = types.ModuleType("config")
        stub_config.CONFIG = {}

        saved = {k: sys.modules.get(k) for k in ("main", "config")}
        saved_argv = list(sys.argv)
        sys.modules["main"] = stub_main
        sys.modules["config"] = stub_config
        try:
            exec(compile(src, "<wrapper>", "exec"), {"__name__": module_name})
        finally:
            sys.argv = saved_argv
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v
        return bool(calls), stub_config.CONFIG

    def test_a_spawn_child_import_does_not_call_main(self):
        """THE contract. A spawn worker re-imports the parent's __main__ under
        the name "__mp_main__"; if that import calls main.main() it builds a
        second Pool during bootstrap, dies, and hangs the parent — #362."""
        called, _ = self._exec_as(_wrapper_source({"data_provider": "parquet"}),
                                  "__mp_main__")
        assert not called, (
            "a spawn child re-importing this wrapper called main.main() — "
            "that is the #362 deadlock")

    def test_running_it_directly_does_call_main(self):
        """The other half: the guard must not make the wrapper inert."""
        called, _ = self._exec_as(_wrapper_source({"data_provider": "parquet"}),
                                  "__main__")
        assert called, "the wrapper never called main.main() at all"

    def test_a_spawn_child_still_applies_the_config_patches(self):
        """Same contract, other direction: the patches must reach the child,
        so they cannot be moved under the guard to fix the above."""
        _, cfg = self._exec_as(
            _wrapper_source({"data_provider": "parquet", "wfa_folds": None}),
            "__mp_main__")
        assert cfg.get("data_provider") == "parquet", cfg
        assert "wfa_folds" in cfg, cfg

    def test_config_patches_stay_at_module_scope(self):
        """Spawn children re-import the wrapper, so the patches must apply
        there too — moving them under the guard would leave workers on the
        unpatched CONFIG."""
        src = _wrapper_source({"data_provider": "parquet", "wfa_folds": None})
        head = src.split('if __name__ == "__main__":', 1)[0]
        assert "config.CONFIG['data_provider'] = 'parquet'" in head, head
        assert "config.CONFIG['wfa_folds'] = None" in head, head

    def test_cli_args_reach_sys_argv(self):
        src = _wrapper_source({}, cli_args=["--verbose"])
        assert "['main.py', '--verbose']" in src, src

    def test_the_wrapper_is_syntactically_valid(self):
        compile(_wrapper_source({"a": 1}, cli_args=["--dry-run"]),
                "<wrapper>", "exec")


class TestSubprocessCallSiteHygiene:
    """Every `subprocess.run` in the four wrapper modules must pass
    `encoding`/`errors` and a `timeout` (#362, #366).

    Both invariants have already bitten, and both were fixed by hand across
    four hand-copied helpers — which is how one of seven call sites got missed
    in the same file as one that was fixed. Nothing could catch that, because
    `TestWrapperSource` pins one of four implementations.

    This is the stopgap until #366 replaces the copies with a shared harness:
    it cannot stop them drifting, but it can stop them drifting SILENTLY.

    Walked with `ast`, not grep — a grep for "encoding" matches the comment
    that explains `encoding`, which on this particular defect is the wrong
    instrument.
    """

    _MODULES = (
        "test_empty_comparison_tickers.py",
        "test_main_cli.py",
        "test_startup_validation.py",
        "test_ui_output.py",
    )

    @staticmethod
    def _call_sites(module_name):
        import ast
        path = os.path.join(PROJECT_ROOT, "tests", module_name)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if (isinstance(fn, ast.Attribute) and fn.attr == "run"
                    and isinstance(fn.value, ast.Name)
                    and fn.value.id == "subprocess"):
                yield node.lineno, {k.arg for k in node.keywords}

    def test_every_call_site_decodes_as_utf8(self):
        bare = [f"{m}:{ln}" for m in self._MODULES
                for ln, kw in self._call_sites(m)
                if not {"encoding", "errors"} <= kw]
        assert not bare, (
            f"subprocess.run without encoding/errors: {bare} — main.py writes "
            f"UTF-8, the locale default is cp1252 on Windows, and the decode "
            f"failure surfaces as stderr=None, not as an exception (#362)")

    def test_every_call_site_has_a_timeout(self):
        bare = [f"{m}:{ln}" for m in self._MODULES
                for ln, kw in self._call_sites(m) if "timeout" not in kw]
        assert not bare, (
            f"subprocess.run without timeout: {bare} — a wrapper that hangs "
            f"with no ceiling hangs the default suite forever")

    def test_the_walk_actually_finds_the_call_sites(self):
        """Guards the guard: if the AST walk silently matched nothing, both
        tests above would pass against any amount of breakage."""
        total = sum(1 for m in self._MODULES for _ in self._call_sites(m))
        assert total >= 7, f"found only {total} subprocess.run call sites"
