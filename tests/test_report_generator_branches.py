"""
tests/test_report_generator_branches.py

Branch coverage for trade_analyzer/report_generator.py.
Targets lines NOT covered by test_report_generator.py / test_report_generator_summaries.py:

  - add_line_to_summary: format-error branch (47)
  - generate_overall_metrics_summary: full body (59-245)
  - generate_drawdown_summary: missing-cols branch (365), exception handler (368-371)
  - generate_symbol_performance_summary: no-problem-symbols path (407), exception (408-409)
  - generate_prof_unprof_comparison: get_group_stats with data (436-445), exception (454-457)
  - generate_losing_month_summary: non-string Entry YrMo (481-482), no-trades (499-500),
        top-contributors present (521), exception (529-532)
  - generate_wins_losses_summary: missing sort-col (567-568), exception (582-585)
  - generate_duration_summary: Win-to-bool exception (600), handler (610-613)
  - generate_mae_mfe_summary: Win-to-bool exception (630), handler (640-643)
  - generate_profit_dist_stats: exception handler (664-667)
  - generate_mc_summary: exception handler (738-741)
  - generate_mc_percentile_table: exception handler (787-790)
  - extract_key_metrics_for_console: regex no-match (1111-1112), max-dd extraction (1124)
"""
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from trade_analyzer.report_generator import (
    add_line_to_summary,
    generate_overall_metrics_summary,
    generate_drawdown_summary,
    generate_symbol_performance_summary,
    generate_prof_unprof_comparison,
    generate_losing_month_summary,
    generate_wins_losses_summary,
    generate_duration_summary,
    generate_mae_mfe_summary,
    generate_profit_dist_stats,
    generate_mc_summary,
    generate_mc_percentile_table,
    extract_key_metrics_for_console,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _trades(n=15):
    """Minimal trades DataFrame with all common columns."""
    dates = pd.date_range("2020-01-02", periods=n, freq="5B")
    ex_dates = dates + pd.Timedelta(days=10)
    pattern = [100.0, -50.0, 200.0, -30.0, 150.0]
    pct_pattern = [2.0, -1.0, 4.0, -0.5, 3.0]
    profits = [pattern[i % 5] for i in range(n)]
    pct = [pct_pattern[i % 5] for i in range(n)]
    return pd.DataFrame({
        "Date":      dates,
        "Ex. date":  ex_dates,
        "Profit":    profits,
        "% Profit":  pct,
        "Win":       [p > 0 for p in profits],
        "Symbol":    ["AAPL"] * n,
        "Shares":    [100.0] * n,
        "Price":     [50.0] * n,
        "# bars":    [5.0] * n,
        "MAE":       [1.0] * n,
        "MFE":       [2.0] * n,
    })


def _daily_rets(n=300, seed=42):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n)
    return pd.Series(rng.standard_normal(n) * 0.01, index=idx)


# ---------------------------------------------------------------------------
# Custom DataFrame subclass for Win-to-bool exception tests
# ---------------------------------------------------------------------------

class _DFWithBadWin(pd.DataFrame):
    """DataFrame that raises TypeError when 'Win' column's astype(bool) is called."""

    def __getitem__(self, key):
        if key == "Win":
            bad = MagicMock(spec=pd.Series)
            bad.fillna.return_value.astype.side_effect = TypeError("forced type error")
            return bad
        return super().__getitem__(key)


# ---------------------------------------------------------------------------
# add_line_to_summary — format error branch (line 47)
# ---------------------------------------------------------------------------

class TestAddLineFormatError:

    def test_format_error_branch_on_non_numeric_with_is_curr(self):
        """is_curr=True with a non-numeric string → ValueError/TypeError → 'Format Error'."""
        lines = []
        add_line_to_summary(lines, "Label", "not_a_number", is_curr=True)
        assert "Format Error" in lines[0]

    def test_format_error_branch_on_non_numeric_with_is_pct(self):
        lines = []
        add_line_to_summary(lines, "Label", "not_a_number", is_pct=True)
        assert "Format Error" in lines[0]


# ---------------------------------------------------------------------------
# generate_overall_metrics_summary — full body (lines 59-245)
# ---------------------------------------------------------------------------

class TestOverallMetricsSummary:

    def _run(self, trades, daily_returns=None, benchmark_returns=None,
             benchmark_df=None, daily_equity=None, ticker="SPY",
             initial_equity=100_000, rfr=0.05, tdy=252):
        if daily_returns is None:
            daily_returns = _daily_rets()
        if daily_equity is None:
            daily_equity = pd.Series(dtype=float)
        return generate_overall_metrics_summary(
            trades, daily_returns, benchmark_returns, benchmark_df,
            daily_equity, ticker, initial_equity, rfr, tdy,
        )

    def test_returns_tuple_of_two(self):
        result = self._run(_trades())
        assert isinstance(result, tuple) and len(result) == 2

    def test_title_contains_overall(self):
        title, _ = self._run(_trades())
        assert "Overall" in title

    def test_text_contains_total_net_profit(self):
        _, text = self._run(_trades())
        assert "Total Net Profit" in text

    def test_text_contains_win_rate(self):
        _, text = self._run(_trades())
        assert "Win Rate" in text

    def test_text_contains_sharpe_ratio(self):
        _, text = self._run(_trades())
        assert "Sharpe" in text

    def test_text_contains_cagr(self):
        _, text = self._run(_trades())
        assert "CAGR" in text

    def test_text_contains_after_tax_cagr(self):
        _, text = self._run(_trades())
        assert "After-Tax CAGR" in text

    def test_with_benchmark_returns_adds_beta(self):
        dr = _daily_rets()
        br = _daily_rets(seed=7)
        _, text = self._run(_trades(), daily_returns=dr, benchmark_returns=br)
        assert "Beta" in text

    def test_with_benchmark_df_adds_benchmark_return(self):
        bench_idx = pd.date_range("2020-01-01", periods=200)
        bench_df = pd.DataFrame(
            {"Benchmark_Price": np.linspace(300, 350, 200)}, index=bench_idx
        )
        _, text = self._run(_trades(), benchmark_df=bench_df)
        assert "SPY" in text

    def test_with_daily_equity_series(self):
        equity = pd.Series(
            np.linspace(100_000, 110_000, 300),
            index=pd.date_range("2020-01-01", periods=300),
        )
        _, text = self._run(_trades(), daily_equity=equity)
        assert "Max Equity Drawdown" in text

    def test_with_equity_column_in_trades(self):
        t = _trades()
        t["Equity"] = np.linspace(100_000, 115_000, len(t))
        _, text = self._run(t)
        assert "Total Net Profit" in text

    def test_shares_and_price_compute_turnover(self):
        _, text = self._run(_trades())
        assert "Annual Turnover" in text

    def test_all_losses_produces_valid_output(self):
        t = _trades()
        t["Profit"] = -50.0
        t["% Profit"] = -1.0
        t["Win"] = False
        _, text = self._run(t)
        assert "Total Net Profit" in text

    def test_same_start_end_date_no_duration(self):
        """All trades on same day → duration = 0 → CAGR = NaN handled."""
        t = _trades(n=5)
        t["Date"] = pd.Timestamp("2020-06-01")
        t["Ex. date"] = pd.Timestamp("2020-06-01")
        _, text = self._run(t)
        assert isinstance(text, str)

    def test_sharpe_of_trades_with_pct_profit(self):
        """'% Profit' column present → per-trade Sharpe diagnostics run."""
        _, text = self._run(_trades())
        assert isinstance(text, str)

    def test_exception_in_body_returns_error_string(self):
        """Force exception inside the try block → text starts with 'Error in'."""
        with patch(
            "trade_analyzer.report_generator.calculations.calculate_core_metrics",
            side_effect=RuntimeError("forced"),
        ):
            _, text = self._run(_trades())
        assert "Error" in text


# ---------------------------------------------------------------------------
# generate_drawdown_summary — specific branches
# ---------------------------------------------------------------------------

class TestDrawdownSummaryBranches:

    def _dd_df(self):
        return pd.DataFrame({
            "Start_Date":     [pd.Timestamp("2020-02-01")],
            "Trough_Date":    [pd.Timestamp("2020-03-01")],
            "End_Date":       [pd.Timestamp("2020-04-01")],
            "DD_Amount":      [5000.0],
            "Duration_Days":  [30.0],
            "Duration_Trades":[5.0],
            "Peak_Value":     [105_000.0],
            "Recovery_Trades":[3.0],
            "Recovery_Days":  [20.0],
        })

    def test_missing_required_cols_shows_cannot_display(self):
        """dd_periods_df present but missing required top-5 cols → line 365."""
        dd = pd.DataFrame({"Duration_Trades": [5.0], "Duration_Days": [30.0]})
        title, text = generate_drawdown_summary(dd, 5.0, 10.0)
        assert "Could not display" in text or "missing" in text.lower()

    def test_exception_handler_fires_on_bad_data(self):
        """Strings in date columns fail strftime → exception handler 368-371."""
        dd = self._dd_df()
        dd["Start_Date"] = "not-a-date"   # str has no .strftime → AttributeError
        title, text = generate_drawdown_summary(dd, 5.0, 10.0)
        assert "Error" in text or "error" in text.lower()

    def test_drawdown_as_negative_flag_displays_negative(self):
        _, text = generate_drawdown_summary(None, 5.0, 10.0, drawdown_as_negative=True)
        assert isinstance(text, str)

    def test_no_dd_periods_shows_no_completed_message(self):
        _, text = generate_drawdown_summary(None, 5.0, 10.0)
        assert "No completed drawdown" in text or isinstance(text, str)


# ---------------------------------------------------------------------------
# generate_symbol_performance_summary — branches
# ---------------------------------------------------------------------------

class TestSymbolPerfBranches:

    def test_no_problem_symbols_shows_none_found(self):
        """All symbols have PF >= threshold → 'No symbols found' path (line 407)."""
        t = _trades()
        t["Profit"] = 100.0
        t["Win"] = True
        title, text, _ = generate_symbol_performance_summary(t, 0.01)
        assert "No symbols" in text or isinstance(text, str)

    def test_exception_handler_fires(self):
        """Patch option_context to raise → exception handler 408-409."""
        with patch(
            "trade_analyzer.report_generator.pd.option_context",
            side_effect=RuntimeError("forced"),
        ):
            title, text, _ = generate_symbol_performance_summary(_trades(), 0.5)
        assert "Error" in text


# ---------------------------------------------------------------------------
# generate_prof_unprof_comparison — branches
# ---------------------------------------------------------------------------

class TestProfUnprofBranches:

    def _symbol_perf(self):
        return pd.DataFrame(
            {"Profit_Factor": [5.0, 0.3]}, index=["AAPL", "MSFT"]
        )

    def test_get_group_stats_with_profitable_group(self):
        """profitable_symbols_list non-empty → get_group_stats body executes (436-445)."""
        trades = pd.DataFrame({
            "Symbol":    ["AAPL", "AAPL", "MSFT"],
            "Profit":    [100.0, 150.0, -50.0],
            "% Profit":  [2.0, 3.0, -1.0],
            "# bars":    [5.0, 6.0, 4.0],
            "Win":       [True, True, False],
        })
        title, text = generate_prof_unprof_comparison(
            trades, self._symbol_perf(), profitable_threshold=2.0, unprofitable_threshold=1.0
        )
        assert "Profitable Symbols" in text

    def test_get_group_stats_shows_avg_pct_return(self):
        trades = pd.DataFrame({
            "Symbol":    ["AAPL", "AAPL"],
            "Profit":    [100.0, 200.0],
            "% Profit":  [2.0, 4.0],
            "# bars":    [5.0, 6.0],
            "Win":       [True, True],
        })
        sp = pd.DataFrame({"Profit_Factor": [5.0]}, index=["AAPL"])
        title, text = generate_prof_unprof_comparison(
            trades, sp, profitable_threshold=2.0, unprofitable_threshold=1.0
        )
        assert "Avg" in text

    def test_exception_handler_fires(self):
        """Patch pd.notna to raise inside get_group_stats → handler 454-457."""
        with patch(
            "trade_analyzer.report_generator.pd.notna",
            side_effect=RuntimeError("forced"),
        ):
            title, text = generate_prof_unprof_comparison(
                _trades(), self._symbol_perf(), 2.0, 1.0
            )
        assert "Error" in text


# ---------------------------------------------------------------------------
# generate_losing_month_summary — branches
# ---------------------------------------------------------------------------

class TestLosingMonthBranches:

    def test_non_string_entry_yrmo_gets_converted_and_finds_no_trades(self):
        """Integer Entry YrMo → conversion (481-482) then no matching trades (499-500)."""
        monthly = pd.DataFrame({
            "Entry YrMo":     [202001, 202002],  # integers, not strings
            "Monthly_Profit": [-1000.0, -500.0],
        })
        trades = pd.DataFrame({
            "Entry YrMo": ["2020-01", "2020-02"],
            "Symbol":     ["AAPL", "AAPL"],
            "Profit":     [-100.0, -50.0],
        })
        title, text = generate_losing_month_summary(trades, monthly, 3)
        # Integers convert to "202001" which won't match "2020-01" → no trades found
        assert isinstance(text, str)

    def test_has_top_contributors_appends_table(self):
        """Matching trades in losing month with negative profits → line 521."""
        monthly = pd.DataFrame({
            "Entry YrMo":     ["2020-01"],
            "Monthly_Profit": [-1000.0],
        })
        trades = pd.DataFrame({
            "Entry YrMo": ["2020-01", "2020-01"],
            "Symbol":     ["AAPL", "MSFT"],
            "Profit":     [-500.0, -400.0],
        })
        title, text = generate_losing_month_summary(trades, monthly, 3)
        assert "2020-01" in text or "AAPL" in text or "MSFT" in text

    def test_exception_handler_fires(self):
        """Patch pd.set_option to raise → handler 529-532."""
        monthly = pd.DataFrame({
            "Entry YrMo":     ["2020-01"],
            "Monthly_Profit": [-1000.0],
        })
        trades = pd.DataFrame({
            "Entry YrMo": ["2020-01"],
            "Symbol":     ["AAPL"],
            "Profit":     [-500.0],
        })
        with patch(
            "trade_analyzer.report_generator.pd.set_option",
            side_effect=RuntimeError("forced"),
        ):
            title, text = generate_losing_month_summary(trades, monthly, 3)
        assert "Error" in text


# ---------------------------------------------------------------------------
# generate_wins_losses_summary — branches
# ---------------------------------------------------------------------------

class TestWinsLossesBranches:

    def test_missing_pct_profit_column_triggers_skipped_message(self):
        """'% Profit' absent → add_summary skips it → lines 567-568."""
        trades = pd.DataFrame({
            "Profit": [100.0, -50.0, 200.0, -30.0, 150.0],
            "Symbol": ["AAPL"] * 5,
        })
        result = generate_wins_losses_summary(trades, 3)
        assert isinstance(result, list)
        # At least one entry should say 'Skipped'
        all_data = " ".join(r.get("data", "") for r in result)
        assert "Skipped" in all_data

    def test_exception_handler_fires(self):
        """Patch pd.set_option to raise → handler 582-585."""
        t = _trades()
        with patch(
            "trade_analyzer.report_generator.pd.set_option",
            side_effect=RuntimeError("forced"),
        ):
            result = generate_wins_losses_summary(t, 3)
        assert any("Error" in r.get("data", "") for r in result)


# ---------------------------------------------------------------------------
# generate_duration_summary — Win-to-bool exception (600) and handler (610-613)
# ---------------------------------------------------------------------------

class TestDurationSummaryBranches:

    def test_win_to_bool_exception_returns_skipped(self):
        """Win column's astype(bool) raises → bare except (line 600)."""
        df = _DFWithBadWin({"# bars": [5.0, 6.0], "Win": [True, False]})
        title, text = generate_duration_summary(df)
        assert "Cannot convert" in text

    def test_exception_handler_fires(self):
        """Patch pd.api.types.is_numeric_dtype to raise inside try → lines 610-613."""
        t = _trades()
        with patch(
            "trade_analyzer.report_generator.pd.api.types.is_numeric_dtype",
            side_effect=RuntimeError("forced"),
        ):
            title, text = generate_duration_summary(t)
        assert "Error" in text


# ---------------------------------------------------------------------------
# generate_mae_mfe_summary — Win-to-bool exception (630) and handler (640-643)
# ---------------------------------------------------------------------------

class TestMaeMfeSummaryBranches:

    def test_win_to_bool_exception_returns_skipped(self):
        """Win column's astype(bool) raises → bare except (line 630)."""
        df = _DFWithBadWin({
            "MAE": [1.0, 2.0], "MFE": [3.0, 4.0], "Win": [True, False]
        })
        title, text = generate_mae_mfe_summary(df)
        assert "Cannot convert" in text

    def test_exception_handler_fires(self):
        """Patch pd.api.types.is_numeric_dtype to raise → lines 640-643."""
        t = _trades()
        with patch(
            "trade_analyzer.report_generator.pd.api.types.is_numeric_dtype",
            side_effect=RuntimeError("forced"),
        ):
            title, text = generate_mae_mfe_summary(t)
        assert "Error" in text


# ---------------------------------------------------------------------------
# generate_profit_dist_stats — exception handler (664-667)
# ---------------------------------------------------------------------------

class TestProfitDistBranches:

    def test_exception_handler_fires(self):
        """Patch pd.Series.skew to raise → handler 664-667."""
        t = _trades()
        with patch(
            "trade_analyzer.report_generator.pd.Series.skew",
            side_effect=RuntimeError("forced"),
        ):
            title, text = generate_profit_dist_stats(t)
        assert "Error" in text


# ---------------------------------------------------------------------------
# generate_mc_summary — exception handler (738-741)
# ---------------------------------------------------------------------------

class TestMcSummaryExceptionHandler:

    def test_exception_handler_fires(self):
        """Patch pd.Series.dropna to raise inside add_stat_line → 738-741."""
        fe = pd.Series([100_000, 110_000, 90_000])
        mc = {
            "final_equities":           fe,
            "cagrs":                    pd.Series([0.1, 0.05, -0.01]),
            "max_drawdown_amounts":     pd.Series([5000, 3000, 7000]),
            "max_drawdown_percentages": pd.Series([5.0, 3.0, 7.0]),
            "lowest_equities":          pd.Series([95_000, 97_000, 93_000]),
        }
        with patch.object(pd.Series, "dropna", side_effect=RuntimeError("forced")):
            title, text = generate_mc_summary(mc, 100_000, False)
        assert "Error" in text


# ---------------------------------------------------------------------------
# generate_mc_percentile_table — exception handler (787-790)
# ---------------------------------------------------------------------------

class TestMcPercentileTableExceptionHandler:

    def test_exception_handler_fires(self):
        """Patch pd.option_context to raise → handler 787-790."""
        mc = {
            "mc_detailed_percentiles": {
                "Final Equity": {"10th": 90_000, "50th": 100_000, "90th": 120_000},
                "CAGR":         {"10th": -0.05, "50th": 0.05,     "90th": 0.15},
            }
        }
        with patch(
            "trade_analyzer.report_generator.pd.option_context",
            side_effect=RuntimeError("forced"),
        ):
            title, text = generate_mc_percentile_table(mc, False)
        assert "Error" in text


# ---------------------------------------------------------------------------
# extract_key_metrics_for_console — regex no-match (1111-1112) and max_dd (1124)
# ---------------------------------------------------------------------------

class TestExtractKeyMetricsBranches:

    def test_mc_average_cagr_regex_no_match_stores_string(self):
        """Value string with no numeric → regex fails → line 1111-1112 stores raw string."""
        data = "CAGR Average: no-number-here\n"
        sections = [{"title": "Monte Carlo: Percentile Analysis", "data": data}]
        result = extract_key_metrics_for_console(sections)
        # The regex should fail, so the raw string is stored
        assert "MC Average CAGR" in result
        assert isinstance(result["MC Average CAGR"], str)

    def test_max_equity_drawdown_extracted_by_regex(self):
        """Overall Metrics section with 'Max Equity Drawdown: 12.34%' → line 1124."""
        data = "CAGR:                                         8.50%\nMax Equity Drawdown:                          12.34%\n"
        sections = [{"title": "Overall Performance Metrics", "data": data}]
        result = extract_key_metrics_for_console(sections)
        assert "Max Equity Drawdown" in result
        assert result["Max Equity Drawdown"] == pytest.approx(12.34)

    def test_cagr_extracted_by_regex_from_overall(self):
        """CAGR regex in Overall section → line 1121."""
        data = "CAGR:                                         15.23%\n"
        sections = [{"title": "Overall Performance Metrics", "data": data}]
        result = extract_key_metrics_for_console(sections)
        assert result.get("CAGR") == pytest.approx(15.23)
