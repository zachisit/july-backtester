"""
tests/test_startup_validation.py

Subprocess-based integration tests for the S1 (API key) and S2 (config
validation) startup guards in main.py.

Design constraints
------------------
main.py does `from config import CONFIG` at module level, so patching
CONFIG inside the test process has no effect on a live subprocess.

Solution — thin wrapper script strategy:
  For each test that needs a custom CONFIG value we generate a small
  wrapper .py into tmp_path that:
    1. Inserts PROJECT_ROOT at the front of sys.path
    2. Imports `config` (cached into sys.modules)
    3. Mutates config.CONFIG[key] = value   ← same dict object main.py holds
    4. Sets sys.argv to include --dry-run    ← prevents data fetching on pass
    5. Imports and calls main.main()

  Because `from config import CONFIG` in main.py gets a reference to the
  same dict object, mutations made in step 3 are visible to main() without
  any monkey-patching library.

  For pure S1 tests (where CONFIG stays unmodified) we reuse the simpler
  direct `_run_main()` helper identical to test_main_cli.py.

Stream conventions (main.py):
  - print()       -> stdout   (S1/S2 error messages)
  - logger.*()    -> stderr   (logging.StreamHandler)
"""

import os
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIN = os.path.join(PROJECT_ROOT, "main.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_main(*args, extra_env=None):
    """
    Run main.py directly (no CONFIG patches). Used for S1 tests where the
    real config.py is fine but the env var is controlled.
    """
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, MAIN, *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=PROJECT_ROOT,
    )


def _run_with_config_patch(tmp_path, patches: dict, cli_args=("--dry-run",), extra_env=None):
    """
    Generate a wrapper script in tmp_path that mutates specific CONFIG keys
    then calls main.main(). Passes --dry-run by default so tests that survive
    S1+S2 exit cleanly at the dry-run gate rather than attempting data fetches.

    Parameters
    ----------
    patches   : dict of {config_key: value} to inject via config.CONFIG[key]=value
    cli_args  : CLI arguments forwarded to main() via sys.argv (default: --dry-run)
    extra_env : extra env var overrides (POLYGON_API_KEY pre-set to "test-key")
    """
    # Build the wrapper as a flat list of un-indented lines to avoid
    # IndentationError when patch_lines spans multiple lines inside an f-string.
    lines = [
        "import sys",
        f"sys.path.insert(0, {repr(PROJECT_ROOT)})",
        "import config",
    ]
    for k, v in patches.items():
        lines.append(f"config.CONFIG[{repr(k)}] = {repr(v)}")
    lines.append(f"sys.argv = {repr(['main.py'] + list(cli_args))}")
    lines.append("import main")
    lines.append("main.main()")

    wrapper = tmp_path / "run_patched.py"
    wrapper.write_text("\n".join(lines), encoding="utf-8")

    env = os.environ.copy()
    env["POLYGON_API_KEY"] = "test-key"   # satisfy S1 by default
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [sys.executable, str(wrapper)],
        capture_output=True,
        text=True,
        env=env,
        cwd=PROJECT_ROOT,
    )


# ---------------------------------------------------------------------------
# S1 — API Key Validation
# ---------------------------------------------------------------------------

class TestS1ApiKeyCheck:
    """S1 guard: POLYGON_API_KEY must be set when data_provider == 'polygon'."""

    # --- Failure cases ---
    # These tests explicitly force data_provider='polygon' so S1 fires regardless
    # of whatever data_provider is set in config.py at the time of the run.

    def test_empty_key_exits_one(self, tmp_path):
        result = _run_with_config_patch(
            tmp_path,
            patches={"data_provider": "polygon"},
            extra_env={"POLYGON_API_KEY": ""},
        )
        assert result.returncode == 1

    def test_empty_key_prints_error_message(self, tmp_path):
        result = _run_with_config_patch(
            tmp_path,
            patches={"data_provider": "polygon"},
            extra_env={"POLYGON_API_KEY": ""},
        )
        assert "POLYGON_API_KEY is not set" in result.stdout

    def test_error_goes_to_stdout_not_stderr(self, tmp_path):
        """S1 uses print() which writes to stdout."""
        result = _run_with_config_patch(
            tmp_path,
            patches={"data_provider": "polygon"},
            extra_env={"POLYGON_API_KEY": ""},
        )
        assert "POLYGON_API_KEY" in result.stdout
        assert "POLYGON_API_KEY" not in result.stderr

    def test_s1_fires_before_run_summary(self, tmp_path):
        """S1 must abort before the U1 RUN SUMMARY block."""
        result = _run_with_config_patch(
            tmp_path,
            patches={"data_provider": "polygon"},
            extra_env={"POLYGON_API_KEY": ""},
        )
        combined = result.stdout + result.stderr
        assert "RUN SUMMARY" not in combined

    def test_s1_fires_before_dry_run_gate(self, tmp_path):
        """[DRY RUN] is logged after the summary — must not appear when S1 fires."""
        result = _run_with_config_patch(
            tmp_path,
            patches={"data_provider": "polygon"},
            extra_env={"POLYGON_API_KEY": ""},
        )
        combined = result.stdout + result.stderr
        assert "[DRY RUN]" not in combined

    # --- Pass case ---

    def test_valid_key_does_not_exit_one(self, tmp_path):
        result = _run_with_config_patch(
            tmp_path,
            patches={"data_provider": "polygon"},
            extra_env={"POLYGON_API_KEY": "test-key"},
        )
        assert result.returncode != 1

    # --- Non-polygon provider skips S1 ---

    def test_norgate_provider_skips_api_key_check(self, tmp_path):
        """
        When data_provider is not 'polygon', S1 must not fire even with no key.
        We patch data_provider to 'norgate' and expect the script to continue
        past S1 (it will still exit due to S2 or dry-run gate).
        """
        result = _run_with_config_patch(
            tmp_path,
            patches={"data_provider": "norgate"},
            extra_env={"POLYGON_API_KEY": ""},
        )
        # S1 error message must NOT appear
        assert "POLYGON_API_KEY is not set" not in result.stdout
        # Returncode must NOT be due to S1 (may be 0 for dry-run or non-zero for other reason)
        # The definitive signal is the absence of the S1 error string.


# ---------------------------------------------------------------------------
# S2 — Date Validation
# ---------------------------------------------------------------------------

class TestS2DateValidation:
    """S2 guard: start_date must be a valid date string that precedes end_date."""

    def test_start_after_end_exits_one(self, tmp_path):
        result = _run_with_config_patch(
            tmp_path,
            patches={"start_date": "2025-01-01", "end_date": "2020-01-01"},
        )
        assert result.returncode == 1

    def test_start_after_end_prints_error_header(self, tmp_path):
        result = _run_with_config_patch(
            tmp_path,
            patches={"start_date": "2025-01-01", "end_date": "2020-01-01"},
        )
        assert "[ERROR] Invalid configuration in config.py:" in result.stdout

    def test_start_after_end_error_mentions_start_date(self, tmp_path):
        result = _run_with_config_patch(
            tmp_path,
            patches={"start_date": "2025-01-01", "end_date": "2020-01-01"},
        )
        assert "start_date" in result.stdout

    def test_start_equals_end_exits_one(self, tmp_path):
        """Boundary: start_date == end_date must also fail (condition is start >= end)."""
        result = _run_with_config_patch(
            tmp_path,
            patches={"start_date": "2022-06-01", "end_date": "2022-06-01"},
        )
        assert result.returncode == 1

    def test_invalid_date_format_exits_one(self, tmp_path):
        result = _run_with_config_patch(
            tmp_path,
            patches={"start_date": "01/01/2020"},  # wrong format (not %Y-%m-%d)
        )
        assert result.returncode == 1

    def test_invalid_date_format_mentions_invalid_date(self, tmp_path):
        result = _run_with_config_patch(
            tmp_path,
            patches={"start_date": "not-a-date"},
        )
        assert "Invalid date format" in result.stdout or "invalid" in result.stdout.lower()

    def test_valid_dates_pass_s2_date_check(self, tmp_path):
        """Well-formed dates in correct order must not trigger the date error."""
        result = _run_with_config_patch(
            tmp_path,
            patches={"start_date": "2020-01-01", "end_date": "2024-01-01"},
        )
        # If exit is 1 it must NOT be because of a date error
        if result.returncode == 1:
            assert "start_date" not in result.stdout


# ---------------------------------------------------------------------------
# S2 — Allocation Validation
# ---------------------------------------------------------------------------

class TestS2AllocationValidation:
    """S2 guard: allocation_per_trade must be in (0, 1.0]."""

    def test_zero_allocation_exits_one(self, tmp_path):
        result = _run_with_config_patch(tmp_path, patches={"allocation_per_trade": 0})
        assert result.returncode == 1

    def test_zero_allocation_error_mentions_field(self, tmp_path):
        result = _run_with_config_patch(tmp_path, patches={"allocation_per_trade": 0})
        assert "allocation_per_trade" in result.stdout

    def test_negative_allocation_exits_one(self, tmp_path):
        result = _run_with_config_patch(tmp_path, patches={"allocation_per_trade": -0.5})
        assert result.returncode == 1

    def test_over_one_allocation_exits_one(self, tmp_path):
        result = _run_with_config_patch(tmp_path, patches={"allocation_per_trade": 1.1})
        assert result.returncode == 1

    def test_allocation_exactly_one_passes_s2(self, tmp_path):
        """Upper boundary: 1.0 is inclusive and must NOT trigger S2."""
        result = _run_with_config_patch(tmp_path, patches={"allocation_per_trade": 1.0})
        if result.returncode == 1:
            assert "allocation_per_trade" not in result.stdout

    def test_typical_allocation_passes_s2(self, tmp_path):
        """0.05 (5% per trade) is a standard value and must pass."""
        result = _run_with_config_patch(tmp_path, patches={"allocation_per_trade": 0.05})
        if result.returncode == 1:
            assert "allocation_per_trade" not in result.stdout


# ---------------------------------------------------------------------------
# S2 — Portfolio Validation
# ---------------------------------------------------------------------------

class TestS2PortfolioValidation:
    """S2 guard: portfolios dict must be non-empty."""

    def test_empty_portfolios_exits_one(self, tmp_path):
        result = _run_with_config_patch(tmp_path, patches={"portfolios": {}})
        assert result.returncode == 1

    def test_empty_portfolios_prints_error_header(self, tmp_path):
        result = _run_with_config_patch(tmp_path, patches={"portfolios": {}})
        assert "[ERROR] Invalid configuration in config.py:" in result.stdout

    def test_empty_portfolios_error_mentions_portfolios(self, tmp_path):
        result = _run_with_config_patch(tmp_path, patches={"portfolios": {}})
        assert "portfolios" in result.stdout.lower()

    def test_none_portfolios_exits_one(self, tmp_path):
        """None is also falsy and should trigger the same guard."""
        result = _run_with_config_patch(tmp_path, patches={"portfolios": None})
        assert result.returncode == 1


# ---------------------------------------------------------------------------
# S2 — Combined / Error Reporting
# ---------------------------------------------------------------------------

class TestS2ErrorReporting:
    """S2 collects all errors and reports them in a single exit."""

    def test_multiple_errors_all_reported_before_exit(self, tmp_path):
        """
        Two independent failures (bad date + bad allocation) must both appear
        in the same error output — S2 must not short-circuit on the first failure.
        """
        result = _run_with_config_patch(
            tmp_path,
            patches={
                "start_date": "2025-01-01",
                "end_date": "2020-01-01",
                "allocation_per_trade": 0,
            },
        )
        assert result.returncode == 1
        assert "start_date" in result.stdout
        assert "allocation_per_trade" in result.stdout

    def test_s2_error_uses_stdout_not_stderr(self, tmp_path):
        """S2 uses print() — errors must appear on stdout."""
        result = _run_with_config_patch(tmp_path, patches={"portfolios": {}})
        assert "portfolios" in result.stdout.lower()
        assert "portfolios" not in result.stderr.lower()

    def test_s2_fires_before_run_summary(self, tmp_path):
        """S2 exits before the U1 RUN SUMMARY block is reached."""
        result = _run_with_config_patch(tmp_path, patches={"portfolios": {}})
        combined = result.stdout + result.stderr
        assert "RUN SUMMARY" not in combined

    def test_s2_fires_before_dry_run_gate(self, tmp_path):
        result = _run_with_config_patch(tmp_path, patches={"portfolios": {}})
        combined = result.stdout + result.stderr
        assert "[DRY RUN]" not in combined
