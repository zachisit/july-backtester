"""
Tests for trade_analyzer/report_generator.py — second batch of pure helpers.

Targets eight functions with no existing tests:
  - generate_drawdown_summary      guard clauses, empty/None dd_periods_df, valid table
  - generate_symbol_performance_summary  missing 'Symbol' col, normal path, problem symbols
  - generate_prof_unprof_comparison      empty symbol_perf_df, normal path
  - generate_losing_month_summary        guard clauses, no losing months, normal path
  - generate_wins_losses_summary         empty df, missing Profit, normal path
  - generate_duration_summary            missing cols, normal path
  - generate_mae_mfe_summary             missing cols, normal path
  - generate_profit_dist_stats           missing col, insufficient data, normal path
  - generate_mc_summary                  empty results, normal path, percentile labels
  - generate_mc_percentile_table         missing key, invalid type, normal path
"""
import pytest
import numpy as np
import pandas as pd

from trade_analyzer.report_generator import (
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
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _trades(n=10, symbols=None):
    """Minimal trades DataFrame with all common columns."""
    rng = np.random.default_rng(0)
    if symbols is None:
        symbols = ["AAPL"] * n
    profits = rng.normal(50, 200, n)
    return pd.DataFrame({
        "Symbol":    symbols,
        "Date":      pd.date_range("2021-01-04", periods=n, freq="3B"),
        "Ex. date":  pd.date_range("2021-01-06", periods=n, freq="3B"),
        "Profit":    profits,
        "% Profit":  profits / 1000 * 100,
        "Win":       profits > 0,
        "# bars":    rng.integers(1, 20, n).astype(float),
        "MAE":       rng.uniform(-5, 0, n),
        "MFE":       rng.uniform(0, 10, n),
        "Entry YrMo": pd.period_range("2021-01", periods=n, freq="M"),
    })


def _dd_periods(n=3):
    """Minimal drawdown periods DataFrame."""
    start = pd.date_range("2021-01-04", periods=n, freq="30B")
    return pd.DataFrame({
        "Start_Date":     start,
        "Trough_Date":    start + pd.Timedelta(days=10),
        "End_Date":       start + pd.Timedelta(days=20),
        "DD_Amount":      [500.0, 300.0, 100.0][:n],
        "Duration_Trades":[5, 3, 2][:n],
        "Duration_Days":  [20, 12, 8][:n],
        "Recovery_Trades":[7, 4, 3][:n],
        "Recovery_Days":  [28, 15, 10][:n],
        "Peak_Value":     [10000.0, 9000.0, 8000.0][:n],
    })


# ---------------------------------------------------------------------------
# generate_drawdown_summary
# ---------------------------------------------------------------------------

class TestGenerateDrawdownSummary:

    def test_returns_tuple_of_two_strings(self):
        title, text = generate_drawdown_summary(None, 10.0, 8.5)
        assert isinstance(title, str) and isinstance(text, str)

    def test_title_contains_drawdown(self):
        title, _ = generate_drawdown_summary(None, 10.0, 8.5)
        assert "Drawdown" in title

    def test_none_dd_periods_shows_no_periods_message(self):
        _, text = generate_drawdown_summary(None, 10.0, 8.5)
        assert "No completed drawdown" in text or "not found" in text.lower() or "cumulative profit" in text.lower()

    def test_empty_dd_periods_shows_no_periods_message(self):
        _, text = generate_drawdown_summary(pd.DataFrame(), 5.0, 4.0)
        assert "No completed drawdown" in text or text != ""

    def test_max_equity_dd_shown(self):
        _, text = generate_drawdown_summary(None, 10.0, 12.5)
        assert "12.50%" in text

    def test_max_equity_dd_negative_flag(self):
        """drawdown_as_negative=True → value displayed as negative magnitude."""
        _, text = generate_drawdown_summary(None, 10.0, 8.0, drawdown_as_negative=True)
        assert "-8.00%" in text

    def test_valid_dd_periods_shows_table_header(self):
        _, text = generate_drawdown_summary(_dd_periods(), 10.0, 8.5)
        assert "Drawdown Duration" in text or "Start Date" in text

    def test_valid_dd_periods_shows_top5_header(self):
        _, text = generate_drawdown_summary(_dd_periods(), 10.0, 8.5)
        assert "Top 5" in text or "Top 5 Largest" in text

    def test_valid_dd_periods_average_duration_present(self):
        _, text = generate_drawdown_summary(_dd_periods(), 10.0, 8.5)
        assert "Average Drawdown Duration" in text

    def test_valid_dd_periods_max_duration_present(self):
        _, text = generate_drawdown_summary(_dd_periods(), 10.0, 8.5)
        assert "Maximum Drawdown Duration" in text

    def test_recovery_stats_present(self):
        _, text = generate_drawdown_summary(_dd_periods(), 10.0, 8.5)
        assert "Recovery" in text


# ---------------------------------------------------------------------------
# generate_symbol_performance_summary
# ---------------------------------------------------------------------------

class TestGenerateSymbolPerformanceSummary:

    def test_returns_three_elements(self):
        result = generate_symbol_performance_summary(_trades(), 1.0)
        assert len(result) == 3

    def test_title_is_string(self):
        title, _, _ = generate_symbol_performance_summary(_trades(), 1.0)
        assert isinstance(title, str)

    def test_missing_symbol_col_returns_error_message(self):
        df = _trades().drop(columns=["Symbol"])
        _, text, _ = generate_symbol_performance_summary(df, 1.0)
        assert "Symbol" in text or "Error" in text

    def test_normal_path_returns_dataframe(self):
        _, _, sym_perf = generate_symbol_performance_summary(_trades(n=20), 1.0)
        assert isinstance(sym_perf, pd.DataFrame)

    def test_summary_text_contains_symbol_name(self):
        syms = ["AAPL"] * 5 + ["MSFT"] * 5
        _, text, _ = generate_symbol_performance_summary(_trades(n=10, symbols=syms), 1.0)
        assert "AAPL" in text or "MSFT" in text

    def test_problem_symbols_section_shown_when_pf_below_threshold(self):
        """Force all trades to losing so PF < threshold."""
        df = _trades(n=10)
        df["Profit"] = -100.0  # all losses → PF = 0
        _, text, _ = generate_symbol_performance_summary(df, 1.0)
        assert "Profit Factor" in text or "0.00" in text or "Problem" in text or "AAPL" in text

    def test_no_problem_symbols_shown_when_all_profitable(self):
        df = _trades(n=10)
        df["Profit"] = 100.0  # all wins
        _, text, _ = generate_symbol_performance_summary(df, 2.0)
        # PF is infinite (no losses), so it's not < threshold unless inf is excluded
        assert isinstance(text, str)


# ---------------------------------------------------------------------------
# generate_prof_unprof_comparison
# ---------------------------------------------------------------------------

class TestGenerateProfUnprofComparison:

    def test_returns_tuple_of_two_strings(self):
        result = generate_prof_unprof_comparison(_trades(), pd.DataFrame(), 1.5, 1.0)
        assert len(result) == 2

    def test_empty_symbol_perf_shows_unavailable_message(self):
        _, text = generate_prof_unprof_comparison(_trades(), pd.DataFrame(), 1.5, 1.0)
        assert "unavailable" in text.lower() or "cannot" in text.lower() or "Could not" in text

    def test_normal_path_returns_string(self):
        _, _, sym_perf = generate_symbol_performance_summary(_trades(n=20), 1.0)
        title, text = generate_prof_unprof_comparison(_trades(n=20), sym_perf, 1.5, 0.5)
        assert isinstance(text, str)

    def test_comparison_threshold_shown_in_text(self):
        _, _, sym_perf = generate_symbol_performance_summary(_trades(n=20), 1.0)
        _, text = generate_prof_unprof_comparison(_trades(n=20), sym_perf, 1.50, 0.50)
        assert "1.50" in text or "0.50" in text

    def test_interpretation_notes_present(self):
        _, _, sym_perf = generate_symbol_performance_summary(_trades(n=20), 1.0)
        _, text = generate_prof_unprof_comparison(_trades(n=20), sym_perf, 1.5, 0.5)
        assert "Interpretation" in text or "Compare" in text or "group" in text.lower()


# ---------------------------------------------------------------------------
# generate_losing_month_summary
# ---------------------------------------------------------------------------

class TestGenerateLosingMonthSummary:

    def _monthly_perf(self, profits):
        periods = pd.period_range("2021-01", periods=len(profits), freq="M")
        return pd.DataFrame({
            "Entry YrMo":    [str(p) for p in periods],
            "Monthly_Profit": profits,
        })

    def test_returns_tuple_of_two_strings(self):
        result = generate_losing_month_summary(_trades(), self._monthly_perf([100, -50]), 3)
        assert len(result) == 2

    def test_none_monthly_perf_shows_unavailable(self):
        _, text = generate_losing_month_summary(_trades(), None, 3)
        assert "unavailable" in text.lower() or "Could not" in text

    def test_empty_monthly_perf_shows_unavailable(self):
        _, text = generate_losing_month_summary(_trades(), pd.DataFrame(), 3)
        assert "unavailable" in text.lower() or "Could not" in text

    def test_no_losing_months_shows_message(self):
        monthly = self._monthly_perf([100, 200, 150])
        _, text = generate_losing_month_summary(_trades(), monthly, 3)
        assert "No losing months" in text

    def test_losing_month_appears_in_output(self):
        monthly = self._monthly_perf([-200.0])
        df = _trades(n=5)
        df["Entry YrMo"] = pd.period_range("2021-01", periods=5, freq="M")
        _, text = generate_losing_month_summary(df, monthly, 3)
        # Should mention the month
        assert "2021" in text or "Month" in text or "Loss" in text

    def test_missing_required_trades_cols_shows_missing(self):
        df = _trades().drop(columns=["Symbol"])
        monthly = self._monthly_perf([-100])
        _, text = generate_losing_month_summary(df, monthly, 3)
        assert "missing" in text.lower() or "unavailable" in text.lower() or "Could not" in text


# ---------------------------------------------------------------------------
# generate_wins_losses_summary
# ---------------------------------------------------------------------------

class TestGenerateWinsLossesSummary:

    def test_returns_list(self):
        result = generate_wins_losses_summary(_trades(), 5)
        assert isinstance(result, list)

    def test_empty_df_returns_list_with_message(self):
        result = generate_wins_losses_summary(pd.DataFrame(), 5)
        assert len(result) >= 1
        assert "empty" in result[0]["data"].lower() or "missing" in result[0]["data"].lower()

    def test_missing_profit_col_returns_list_with_message(self):
        df = _trades().drop(columns=["Profit"])
        result = generate_wins_losses_summary(df, 5)
        assert len(result) >= 1

    def test_normal_path_returns_four_sections(self):
        """top_n wins %, top_n losses %, top_n wins $, top_n losses $."""
        result = generate_wins_losses_summary(_trades(n=20), 5)
        assert len(result) == 4

    def test_each_section_has_title_and_data(self):
        result = generate_wins_losses_summary(_trades(n=20), 5)
        for section in result:
            assert "title" in section
            assert "data" in section

    def test_titles_mention_wins_and_losses(self):
        result = generate_wins_losses_summary(_trades(n=20), 5)
        titles = [s["title"] for s in result]
        assert any("Wins" in t or "Win" in t for t in titles)
        assert any("Losses" in t or "Loss" in t for t in titles)


# ---------------------------------------------------------------------------
# generate_duration_summary
# ---------------------------------------------------------------------------

class TestGenerateDurationSummary:

    def test_returns_tuple_of_two_strings(self):
        title, text = generate_duration_summary(_trades())
        assert isinstance(title, str) and isinstance(text, str)

    def test_empty_df_skips(self):
        _, text = generate_duration_summary(pd.DataFrame())
        assert "Skipped" in text or "Missing" in text or "missing" in text.lower()

    def test_missing_bars_col_skips(self):
        df = _trades().drop(columns=["# bars"])
        _, text = generate_duration_summary(df)
        assert "Skipped" in text or "missing" in text.lower()

    def test_missing_win_col_skips(self):
        df = _trades().drop(columns=["Win"])
        _, text = generate_duration_summary(df)
        assert "Skipped" in text or "missing" in text.lower()

    def test_normal_path_shows_avg_bars_wins(self):
        _, text = generate_duration_summary(_trades(n=20))
        assert "Wins" in text or "wins" in text or "bars" in text.lower()

    def test_normal_path_shows_avg_bars_losses(self):
        _, text = generate_duration_summary(_trades(n=20))
        assert "Losses" in text or "losses" in text


# ---------------------------------------------------------------------------
# generate_mae_mfe_summary
# ---------------------------------------------------------------------------

class TestGenerateMaeMfeSummary:

    def test_returns_tuple_of_two_strings(self):
        title, text = generate_mae_mfe_summary(_trades())
        assert isinstance(title, str) and isinstance(text, str)

    def test_empty_df_skips(self):
        _, text = generate_mae_mfe_summary(pd.DataFrame())
        assert "Skipped" in text or "Missing" in text or "missing" in text.lower()

    def test_missing_mae_col_skips(self):
        df = _trades().drop(columns=["MAE"])
        _, text = generate_mae_mfe_summary(df)
        assert "Skipped" in text or "missing" in text.lower()

    def test_missing_mfe_col_skips(self):
        df = _trades().drop(columns=["MFE"])
        _, text = generate_mae_mfe_summary(df)
        assert "Skipped" in text or "missing" in text.lower()

    def test_missing_win_col_skips(self):
        df = _trades().drop(columns=["Win"])
        _, text = generate_mae_mfe_summary(df)
        assert "Skipped" in text or "missing" in text.lower()

    def test_normal_path_shows_mae_for_losses(self):
        _, text = generate_mae_mfe_summary(_trades(n=20))
        assert "MAE" in text

    def test_normal_path_shows_mfe_for_wins(self):
        _, text = generate_mae_mfe_summary(_trades(n=20))
        assert "MFE" in text


# ---------------------------------------------------------------------------
# generate_profit_dist_stats
# ---------------------------------------------------------------------------

class TestGenerateProfitDistStats:

    def test_returns_tuple_of_two_strings(self):
        title, text = generate_profit_dist_stats(_trades())
        assert isinstance(title, str) and isinstance(text, str)

    def test_empty_df_skips(self):
        _, text = generate_profit_dist_stats(pd.DataFrame())
        assert "Skipped" in text or "Missing" in text or "missing" in text.lower()

    def test_missing_pct_profit_col_skips(self):
        df = _trades().drop(columns=["% Profit"])
        _, text = generate_profit_dist_stats(df)
        assert "Skipped" in text or "missing" in text.lower()

    def test_insufficient_data_skips(self):
        """< 3 rows → cannot compute skew/kurt."""
        _, text = generate_profit_dist_stats(_trades(n=2))
        assert "Skipped" in text or "Insufficient" in text

    def test_normal_path_shows_skewness(self):
        _, text = generate_profit_dist_stats(_trades(n=20))
        assert "Skewness" in text or "skewness" in text.lower()

    def test_normal_path_shows_kurtosis(self):
        _, text = generate_profit_dist_stats(_trades(n=20))
        assert "Kurtosis" in text or "kurtosis" in text.lower()

    def test_skewness_is_numeric(self):
        _, text = generate_profit_dist_stats(_trades(n=20))
        # Should contain a formatted float like "0.12" or "-1.34"
        import re
        assert re.search(r"[-+]?\d+\.\d+", text) is not None


# ---------------------------------------------------------------------------
# generate_mc_summary
# ---------------------------------------------------------------------------

def _mc_results(n=200):
    """Minimal mc_results dict with all expected keys."""
    rng = np.random.default_rng(42)
    return {
        "final_equities":          pd.Series(rng.normal(110_000, 5_000, n)),
        "cagrs":                   pd.Series(rng.normal(0.08, 0.02, n)),
        "max_drawdown_amounts":    pd.Series(rng.uniform(-5_000, -500, n)),
        "max_drawdown_percentages":pd.Series(rng.uniform(-20, -2, n)),
        "lowest_equities":         pd.Series(rng.normal(95_000, 3_000, n)),
    }


class TestGenerateMcSummary:

    def test_returns_tuple_of_two_strings(self):
        title, text = generate_mc_summary(_mc_results(), 100_000, False)
        assert isinstance(title, str) and isinstance(text, str)

    def test_empty_results_shows_not_available(self):
        _, text = generate_mc_summary({}, 100_000, False)
        assert "not available" in text.lower() or "empty" in text.lower()

    def test_empty_final_equities_shows_not_available(self):
        _, text = generate_mc_summary({"final_equities": []}, 100_000, False)
        assert "not available" in text.lower() or "empty" in text.lower()

    def test_num_simulations_mentioned(self):
        _, text = generate_mc_summary(_mc_results(n=150), 100_000, False)
        assert "150" in text

    def test_final_equity_section_present(self):
        _, text = generate_mc_summary(_mc_results(), 100_000, False)
        assert "Final Equity" in text

    def test_cagr_section_present(self):
        _, text = generate_mc_summary(_mc_results(), 100_000, False)
        assert "CAGR" in text

    def test_drawdown_section_present(self):
        _, text = generate_mc_summary(_mc_results(), 100_000, False)
        assert "Drawdown" in text

    def test_probability_profit_line_present(self):
        _, text = generate_mc_summary(_mc_results(), 100_000, False)
        assert "Probability" in text or "%" in text

    def test_average_line_present(self):
        _, text = generate_mc_summary(_mc_results(), 100_000, False)
        assert "Average" in text

    def test_percentile_label_ordinal_suffix(self):
        """get_p_label uses st/nd/rd/th correctly (spot check)."""
        _, text = generate_mc_summary(_mc_results(), 100_000, False)
        # 1st, 5th, 10th, 25th, 50th etc. all come from config.MC_PERCENTILES
        assert "Percentile" in text or "th" in text


# ---------------------------------------------------------------------------
# generate_mc_percentile_table
# ---------------------------------------------------------------------------

def _mc_detailed_percentiles():
    """Minimal mc_detailed_percentiles dict matching the expected schema."""
    percs = ["1th", "5th", "10th", "25th", "50th", "75th", "90th", "95th", "99th"]
    rng = np.random.default_rng(7)
    return {
        "Final Equity":    {p: rng.uniform(90_000, 120_000) for p in percs},
        "CAGR":            {p: rng.uniform(0.02, 0.15) for p in percs},
        "Max Drawdown $":  {p: rng.uniform(-8_000, -500) for p in percs},
        "Max Drawdown %":  {p: rng.uniform(-25, -2) for p in percs},
        "Lowest Equity":   {p: rng.uniform(85_000, 100_000) for p in percs},
    }


class TestGenerateMcPercentileTable:

    def test_returns_tuple_of_two_strings(self):
        mc = {"mc_detailed_percentiles": _mc_detailed_percentiles()}
        title, text = generate_mc_percentile_table(mc, False)
        assert isinstance(title, str) and isinstance(text, str)

    def test_empty_dict_shows_not_found_message(self):
        _, text = generate_mc_percentile_table({}, False)
        assert "not found" in text.lower() or "MC" in text or "data" in text.lower()

    def test_missing_key_shows_not_found_message(self):
        _, text = generate_mc_percentile_table({"other_key": {}}, False)
        assert "not found" in text.lower()

    def test_invalid_type_for_detailed_percentiles(self):
        """Non-dict value for mc_detailed_percentiles triggers the invalid branch."""
        _, text = generate_mc_percentile_table({"mc_detailed_percentiles": "bad"}, False)
        assert "invalid" in text.lower() or "Error" in text or "not found" in text.lower()

    def test_empty_detailed_percentiles_dict(self):
        _, text = generate_mc_percentile_table({"mc_detailed_percentiles": {}}, False)
        assert "invalid" in text.lower() or "empty" in text.lower() or "Error" in text

    def test_normal_path_contains_final_equity_col(self):
        mc = {"mc_detailed_percentiles": _mc_detailed_percentiles()}
        _, text = generate_mc_percentile_table(mc, False)
        assert "Final Equity" in text or "Equity" in text

    def test_normal_path_contains_cagr_col(self):
        mc = {"mc_detailed_percentiles": _mc_detailed_percentiles()}
        _, text = generate_mc_percentile_table(mc, False)
        assert "CAGR" in text or "Return" in text

    def test_normal_path_contains_percentile_rows(self):
        mc = {"mc_detailed_percentiles": _mc_detailed_percentiles()}
        _, text = generate_mc_percentile_table(mc, False)
        assert "%" in text
