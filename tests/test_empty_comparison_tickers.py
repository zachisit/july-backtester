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

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_FIXTURE_DIR = os.path.join(PROJECT_ROOT, "tests", "fixtures", "parquet_data")
_FIXTURE_AVAILABLE = os.path.isdir(_FIXTURE_DIR) and any(
    f.endswith(".parquet") for f in os.listdir(_FIXTURE_DIR) if os.path.isfile(os.path.join(_FIXTURE_DIR, f))
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_patched(tmp_path, patches: dict, cli_args=()) -> subprocess.CompletedProcess:
    """
    Write a wrapper script that applies CONFIG patches then calls main.main().
    Uses the same pattern as test_main_cli.py.
    """
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

    return subprocess.run(
        [sys.executable, str(wrapper)],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )


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
# Integration tests — subprocess, require parquet fixtures
# ---------------------------------------------------------------------------

_SKIP_NO_FIXTURE = pytest.mark.skipif(
    not _FIXTURE_AVAILABLE,
    reason="Parquet fixture directory not present — run from project root.",
)


@_SKIP_NO_FIXTURE
class TestEmptyComparisonTickersRun:
    """
    Full main() runs using parquet fixtures + comparison_tickers=[].

    These tests caught the NameError bug: spy_df not defined when
    comparison_dfs is empty.
    """

    _BASE_PATCHES = {
        "data_provider": "parquet",
        "comparison_tickers": [],
        "symbols_to_test": ["AAPL"],
        "portfolios": {},
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

    def test_exits_zero_or_clean_failure(self, tmp_path):
        """Run must not crash with an unhandled exception."""
        result = _run_patched(tmp_path, self._patches_with(), cli_args=[])
        combined = result.stdout + result.stderr
        assert "Traceback" not in combined, combined

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

    def test_actual_data_period_line_not_present(self, tmp_path):
        """'Actual Data Period' line should NOT appear — only 'Data Period (config)'."""
        result = _run_patched(tmp_path, self._patches_with(), cli_args=[])
        assert "Actual Data Period" not in result.stderr, result.stderr
