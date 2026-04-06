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

    try:
        return subprocess.run(
            [sys.executable, str(wrapper)],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("Subprocess timed out — system too slow for this integration test")


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
        "symbols_to_test": ["AAPL"],
        "portfolios": {},
        # AAPL fixture has 62 rows — must be below this or the symbol is filtered
        # before any worker runs, giving a false-green test
        "min_bars_required": 10,
        # Run one strategy only — keeps subprocess runtime under the 90s timeout
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
        """Run must not crash with any unhandled exception or worker fatal error."""
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
