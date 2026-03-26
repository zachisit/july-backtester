"""
tests/test_analyzer_branches.py

Branch coverage for trade_analyzer/analyzer.py lines not hit by test_analyzer.py.

Focuses on the report-section generation loop inside _run_analysis:
  - Monthly performance section (Entry YrMo present / absent)
  - Duration histogram section (# bars present / absent)
  - MAE/MFE section (MAE/MFE/Win present / absent)
  - % Profit distribution section (% Profit present / absent)
  - R-multiple histogram section (RMultiple present / absent, < 2 values)
  - MC simulation result processing (mc_results non-empty)
  - Benchmark available branch (benchmark_df non-None with Benchmark_Price)
  - Equity for DD calc branches (Equity col present vs daily_equity path)
"""
import contextlib
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

from trade_analyzer import analyzer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trades_df(n=10, extra_cols=None):
    """Minimal trades DataFrame accepted by clean_trades_data."""
    dates_entry = pd.date_range("2021-01-04", periods=n, freq="3B")
    dates_exit  = pd.date_range("2021-01-08", periods=n, freq="3B")
    profits = [100.0, -50.0, 200.0, -30.0, 150.0,
               80.0,  -20.0, 120.0, -10.0, 90.0][:n]
    pct     = [2.0, -1.0, 4.0, -0.5, 3.0,
               1.6,  -0.4, 2.4,  -0.2, 1.8][:n]
    df = pd.DataFrame({
        "Date":      dates_entry,
        "Ex. date":  dates_exit,
        "Profit":    profits,
        "% Profit":  pct,
    })
    if extra_cols:
        for col, val in extra_cols.items():
            df[col] = val
    return df


@contextlib.contextmanager
def _stub_downstream(**extra_returns):
    """Stub all heavy downstream calls; allow extras to override."""
    defaults = {
        "trade_analyzer.analyzer.data_handler.calculate_daily_returns": (
            pd.Series([100_000.0, 101_000.0], index=pd.date_range("2021-01-04", periods=2)),
            pd.Series([0.0, 0.01], index=pd.date_range("2021-01-04", periods=2)),
        ),
        "trade_analyzer.analyzer.data_handler.download_benchmark_data": None,
        "trade_analyzer.analyzer.report_generator.generate_overall_metrics_summary": ("Metrics", "text"),
        "trade_analyzer.analyzer.report_generator.generate_wfa_summary": ("WFA", "text"),
        "trade_analyzer.analyzer.report_generator.generate_markdown_report": None,
        "trade_analyzer.analyzer.report_generator.generate_pdf_report": None,
        "trade_analyzer.analyzer.report_generator.extract_key_metrics_for_console": {},
        "trade_analyzer.analyzer.calculations.calculate_core_metrics": {},
        "trade_analyzer.analyzer.calculations.calculate_rolling_metrics": pd.DataFrame(),
        "trade_analyzer.analyzer.calculations.run_monte_carlo_simulation": {},
    }
    defaults.update(extra_returns)

    patches = []
    try:
        for target, rv in defaults.items():
            if rv is None:
                p = patch(target)
            else:
                p = patch(target, return_value=rv)
            patches.append(p)
        # Suppress plt entirely
        patches.append(patch("trade_analyzer.analyzer.plt"))

        [p.start() for p in patches]
        yield
    finally:
        for p in patches:
            try:
                p.stop()
            except RuntimeError:
                pass


# ---------------------------------------------------------------------------
# Monthly performance section (lines 244-261)
# ---------------------------------------------------------------------------

class TestMonthlyPerfSection:

    def test_entry_yrmo_present_no_crash(self, tmp_path):
        """'Entry YrMo' column in trades_df → monthly section executes."""
        df = _make_trades_df()
        # Simulate what clean_trades_data produces — Entry YrMo as period strings
        df["Entry YrMo"] = pd.PeriodIndex(df["Date"], freq="M")
        with _stub_downstream():
            analyzer._run_analysis(df, str(tmp_path), "monthly_run", {})

    def test_entry_yrmo_absent_section_skipped(self, tmp_path):
        """No 'Entry YrMo' column → monthly section skipped with message."""
        df = _make_trades_df()
        with _stub_downstream():
            analyzer._run_analysis(df, str(tmp_path), "no_monthly", {})

    def test_monthly_plot_exception_caught(self, tmp_path):
        """Exception inside monthly plot block is caught, not propagated."""
        df = _make_trades_df()
        df["Entry YrMo"] = pd.PeriodIndex(df["Date"], freq="M")
        with _stub_downstream(), \
             patch("trade_analyzer.analyzer.plotting.plot_monthly_performance",
                   side_effect=RuntimeError("plot exploded")):
            analyzer._run_analysis(df, str(tmp_path), "monthly_exc", {})


# ---------------------------------------------------------------------------
# Duration histogram section (lines 269-277)
# ---------------------------------------------------------------------------

class TestDurationSection:

    def test_bars_column_present_no_crash(self, tmp_path):
        """'# bars' numeric column → duration section executes."""
        df = _make_trades_df()
        df["# bars"] = 5
        with _stub_downstream():
            analyzer._run_analysis(df, str(tmp_path), "duration_run", {})

    def test_bars_column_absent_section_skipped(self, tmp_path):
        """No '# bars' column → duration section skipped."""
        df = _make_trades_df()
        with _stub_downstream():
            analyzer._run_analysis(df, str(tmp_path), "no_duration", {})

    def test_bars_column_non_numeric_skipped(self, tmp_path):
        """'# bars' with string values → not numeric → section skipped."""
        df = _make_trades_df()
        df["# bars"] = "five"
        with _stub_downstream():
            analyzer._run_analysis(df, str(tmp_path), "bad_bars", {})


# ---------------------------------------------------------------------------
# MAE/MFE section (lines 279-289)
# ---------------------------------------------------------------------------

class TestMaeMfeSection:

    def test_mae_mfe_columns_present_no_crash(self, tmp_path):
        """MAE, MFE, % Profit, Win all present → MAE/MFE section executes."""
        df = _make_trades_df()
        df["MAE"] = -0.02
        df["MFE"] = 0.04
        df["Win"] = (df["Profit"] > 0).astype(int)
        with _stub_downstream():
            analyzer._run_analysis(df, str(tmp_path), "mae_mfe_run", {})

    def test_mae_absent_section_skipped(self, tmp_path):
        """MAE column missing → section skipped."""
        df = _make_trades_df()
        df["MFE"] = 0.04
        df["Win"] = 1
        with _stub_downstream():
            analyzer._run_analysis(df, str(tmp_path), "no_mae", {})


# ---------------------------------------------------------------------------
# % Profit distribution section (lines 291-297)
# ---------------------------------------------------------------------------

class TestProfitDistSection:

    def test_pct_profit_present_no_crash(self, tmp_path):
        """'% Profit' numeric column present → dist section executes."""
        df = _make_trades_df()
        # % Profit is already in _make_trades_df
        with _stub_downstream():
            analyzer._run_analysis(df, str(tmp_path), "pct_run", {})

    def test_pct_profit_non_numeric_skipped(self, tmp_path):
        """'% Profit' string column → not numeric → section skipped."""
        df = _make_trades_df()
        df["% Profit"] = "bad"
        with _stub_downstream():
            analyzer._run_analysis(df, str(tmp_path), "bad_pct", {})


# ---------------------------------------------------------------------------
# R-multiple histogram section (lines 299-324)
# ---------------------------------------------------------------------------

class TestRMultipleSection:

    def test_rmultiple_present_enough_values(self, tmp_path):
        """'RMultiple' numeric with >= 2 values → histogram section executes."""
        df = _make_trades_df()
        df["RMultiple"] = [1.5, -0.5, 2.0, -1.0, 0.8,
                           1.2,  0.3, -0.8,  1.1, 0.6]
        with _stub_downstream():
            analyzer._run_analysis(df, str(tmp_path), "rmult_run", {})

    def test_rmultiple_fewer_than_2_values_skipped(self, tmp_path):
        """'RMultiple' with only 1 non-NaN value → skipped."""
        df = _make_trades_df()
        df["RMultiple"] = [1.0] + [np.nan] * (len(df) - 1)
        with _stub_downstream():
            analyzer._run_analysis(df, str(tmp_path), "rmult_1val", {})

    def test_rmultiple_absent_skipped(self, tmp_path):
        """No 'RMultiple' column → section skipped with message."""
        df = _make_trades_df()
        with _stub_downstream():
            analyzer._run_analysis(df, str(tmp_path), "no_rmult", {})

    def test_rmultiple_plot_exception_caught(self, tmp_path):
        """Exception in the R-multiple plot block is caught, not propagated."""
        df = _make_trades_df()
        df["RMultiple"] = [1.0, -0.5, 2.0, -1.0, 0.8,
                           1.1,  0.2, -0.6,  0.9, 0.4]
        with _stub_downstream(), \
             patch("trade_analyzer.analyzer.plt") as mock_plt:
            mock_plt.subplots.side_effect = RuntimeError("hist exploded")
            analyzer._run_analysis(df, str(tmp_path), "rmult_exc", {})


# ---------------------------------------------------------------------------
# Monte Carlo result processing (lines 377-412)
# ---------------------------------------------------------------------------

class TestMcResultProcessing:

    def _mc_results(self):
        """Minimal mc_results dict that exercises the full MC section."""
        n = 20
        return {
            "simulated_equity_paths": pd.DataFrame(
                np.random.rand(n, 10) * 100_000,
                columns=[f"s{i}" for i in range(10)]
            ),
            "max_drawdown_percentages": pd.Series(np.random.rand(n) * 0.3),
            "lowest_equities": pd.Series(np.random.rand(n) * 100_000),
            "final_equities": pd.Series(np.random.rand(n) * 110_000),
            "cagrs": pd.Series(np.random.rand(n) * 0.2),
            "percentile_5": 0.05,
            "percentile_50": 0.10,
            "percentile_95": 0.20,
        }

    def test_mc_results_nonempty_executes_section(self, tmp_path):
        """Non-empty mc_results dict → MC summary sections appended."""
        df = _make_trades_df()
        mc = self._mc_results()
        with _stub_downstream(
            **{
                "trade_analyzer.analyzer.calculations.run_monte_carlo_simulation": mc,
                "trade_analyzer.analyzer.report_generator.generate_mc_percentile_table": ("MC Pct", "mc text"),
                "trade_analyzer.analyzer.report_generator.generate_mc_summary": ("MC Sum", "mc sum text"),
            }
        ):
            analyzer._run_analysis(df, str(tmp_path), "mc_run", {})

    def test_mc_results_empty_dict_section_skipped(self, tmp_path):
        """mc_results = {} → MC section appended as 'Skipped'."""
        df = _make_trades_df()
        with _stub_downstream(
            **{"trade_analyzer.analyzer.calculations.run_monte_carlo_simulation": {}}
        ):
            analyzer._run_analysis(df, str(tmp_path), "mc_empty", {})

    def test_mc_exception_section_handled(self, tmp_path):
        """Exception inside MC block → error section appended, no propagation."""
        df = _make_trades_df()
        with _stub_downstream(
            **{
                "trade_analyzer.analyzer.calculations.run_monte_carlo_simulation":
                    RuntimeError("mc boom"),
            }
        ):
            # Use side_effect instead of return_value for the exception
            with patch(
                "trade_analyzer.analyzer.calculations.run_monte_carlo_simulation",
                side_effect=RuntimeError("mc boom"),
            ):
                analyzer._run_analysis(df, str(tmp_path), "mc_exc", {})


# ---------------------------------------------------------------------------
# Benchmark available branch (line 156-165)
# ---------------------------------------------------------------------------

class TestBenchmarkAvailableBranch:

    def test_benchmark_df_present_with_benchmark_price(self, tmp_path):
        """benchmark_df non-None with 'Benchmark_Price' → returns reindex into daily_returns."""
        df = _make_trades_df()
        idx = pd.date_range("2021-01-04", periods=5)
        bench_df = pd.DataFrame(
            {"Benchmark_Price": np.linspace(300.0, 320.0, 5)},
            index=idx,
        )
        daily_returns_idx = pd.date_range("2021-01-04", periods=5)
        daily_eq = pd.Series(
            [100_000, 100_500, 101_000, 101_500, 102_000],
            index=daily_returns_idx,
        )
        daily_ret = pd.Series(
            [0.0, 0.005, 0.005, 0.005, 0.005],
            index=daily_returns_idx,
        )
        with _stub_downstream(
            **{
                "trade_analyzer.analyzer.data_handler.download_benchmark_data": bench_df,
                "trade_analyzer.analyzer.data_handler.calculate_daily_returns": (daily_eq, daily_ret),
            }
        ):
            analyzer._run_analysis(df, str(tmp_path), "bench_run", {})

    def test_empty_benchmark_df_falls_through(self, tmp_path):
        """Empty benchmark_df → benchmark_returns stays empty Series."""
        df = _make_trades_df()
        empty_bench = pd.DataFrame()
        with _stub_downstream(
            **{"trade_analyzer.analyzer.data_handler.download_benchmark_data": empty_bench}
        ):
            analyzer._run_analysis(df, str(tmp_path), "empty_bench", {})


# ---------------------------------------------------------------------------
# Equity for DD calc branches (lines 216-223)
# ---------------------------------------------------------------------------

class TestEquityDdCalcBranch:

    def test_equity_column_present_uses_it(self, tmp_path):
        """'Equity' column in trades_df → equity_for_dd_calc uses trade equity."""
        df = _make_trades_df()
        # Simulate Equity column that clean_trades_data might produce
        df["Equity"] = 100_000.0 + np.cumsum(df["Profit"])
        daily_eq = pd.Series(
            np.linspace(100_000, 102_000, 5),
            index=pd.date_range("2021-01-04", periods=5),
        )
        daily_ret = pd.Series(
            [0.0] * 5, index=pd.date_range("2021-01-04", periods=5)
        )
        with _stub_downstream(
            **{"trade_analyzer.analyzer.data_handler.calculate_daily_returns": (daily_eq, daily_ret)}
        ):
            analyzer._run_analysis(df, str(tmp_path), "equity_col_run", {})
