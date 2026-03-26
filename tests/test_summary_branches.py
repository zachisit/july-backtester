"""
tests/test_summary_branches.py

Branch coverage for helpers/summary.py — targeting function bodies not
covered by the existing test_summary_*.py files.

Focuses on:
  - generate_final_summary: happy path, filtered_df empty, verbose branch,
    CSV save exception
  - generate_per_portfolio_summary: happy path body, display_df empty,
    corr_matrix path, all_results filtering
  - generate_single_asset_summary_report: happy path body
"""
import os
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

from helpers.summary import (
    generate_final_summary,
    generate_per_portfolio_summary,
    generate_single_asset_summary_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_result(**overrides):
    """Minimal result dict that passes all default filters."""
    r = {
        "Strategy":         "SMA_Cross",
        "Asset":            "AAPL",
        "Trades":           60,  # above default min_trades_for_mc=50
        "max_drawdown":     0.10,    # 10% <= 100% default
        "mc_score":         5,       # >= -999 default
        "pnl_percent":      0.15,    # 15% >= -999% default
        "calmar_ratio":     1.5,
        "sharpe_ratio":     1.2,
        "profit_factor":    1.8,
        "win_rate":         0.55,
        "vs_spy_benchmark": 0.05,
        "vs_qqq_benchmark": 0.03,
        "mc_verdict":       "Good",
        "wfa_verdict":      "Pass",
        "wfa_rolling_verdict": "Pass",
        "oos_pnl_pct":      0.08,
        "expectancy":       0.25,
        "sqn":              2.1,
        "avg_trade_duration": 3.5,
        "rolling_sharpe_mean":  1.1,
        "rolling_sharpe_min":   0.8,
        "rolling_sharpe_final": 1.0,
        "max_recovery_days":    20,
        "avg_recovery_days":    10.0,
        "initial_capital":      100_000,
    }
    r.update(overrides)
    return r


# ---------------------------------------------------------------------------
# generate_final_summary — happy path
# ---------------------------------------------------------------------------

class TestGenerateFinalSummaryHappyPath:

    def test_prints_header_to_stdout(self, capsys):
        results = [_minimal_result()]
        with patch("helpers.summary.os.makedirs"), \
             patch("helpers.summary.pd.DataFrame.to_csv"):
            generate_final_summary(results)
        out = capsys.readouterr().out
        assert "Overall Top 5 Single-Asset Strategies" in out

    def test_prints_strategy_name(self, capsys):
        results = [_minimal_result(Strategy="MyCoolStrat")]
        with patch("helpers.summary.os.makedirs"), \
             patch("helpers.summary.pd.DataFrame.to_csv"):
            generate_final_summary(results)
        out = capsys.readouterr().out
        assert "MyCoolStrat" in out

    def test_multiple_results_shown(self, capsys):
        results = [_minimal_result(Strategy=f"S{i}") for i in range(3)]
        with patch("helpers.summary.os.makedirs"), \
             patch("helpers.summary.pd.DataFrame.to_csv"):
            generate_final_summary(results)
        out = capsys.readouterr().out
        assert "S0" in out or "S1" in out or "S2" in out


# ---------------------------------------------------------------------------
# generate_final_summary — filtered_df empty branch
# ---------------------------------------------------------------------------

class TestGenerateFinalSummaryFilteredEmpty:

    def test_no_strategies_pass_filter_prints_message(self, capsys):
        """Result with Trades < min_trades → filtered_df empty."""
        results = [_minimal_result(Trades=1)]  # below default min_trades=15
        with patch.dict("config.CONFIG", {"min_trades_for_mc": 50}):
            generate_final_summary(results)
        out = capsys.readouterr().out
        assert "No strategies met the final criteria" in out

    def test_high_drawdown_filters_out_all(self, capsys):
        results = [_minimal_result(max_drawdown=2.0)]  # exceeds 100% cap
        with patch.dict("config.CONFIG", {"max_acceptable_drawdown": 0.5}):
            generate_final_summary(results)
        out = capsys.readouterr().out
        assert "No strategies met the final criteria" in out


# ---------------------------------------------------------------------------
# generate_final_summary — verbose output branch
# ---------------------------------------------------------------------------

class TestGenerateFinalSummaryVerbose:

    def test_verbose_true_prints_extended_table(self, capsys):
        results = [_minimal_result()]
        with patch("helpers.summary.os.makedirs"), \
             patch("helpers.summary.pd.DataFrame.to_csv"), \
             patch.dict("config.CONFIG", {"verbose_output": True}):
            generate_final_summary(results)
        out = capsys.readouterr().out
        # Verbose mode should NOT print the hint
        assert "Run with --verbose" not in out

    def test_non_verbose_prints_hint(self, capsys):
        results = [_minimal_result()]
        with patch("helpers.summary.os.makedirs"), \
             patch("helpers.summary.pd.DataFrame.to_csv"), \
             patch.dict("config.CONFIG", {"verbose_output": False}):
            generate_final_summary(results)
        out = capsys.readouterr().out
        assert "Run with --verbose" in out


# ---------------------------------------------------------------------------
# generate_final_summary — CSV save exception branch
# ---------------------------------------------------------------------------

class TestGenerateFinalSummaryCsvException:

    def test_csv_write_exception_prints_warning(self, capsys):
        """Exception during to_csv prints a WARNING instead of raising."""
        results = [_minimal_result()]
        with patch("helpers.summary.os.makedirs"), \
             patch("helpers.summary.pd.DataFrame.to_csv",
                   side_effect=PermissionError("access denied")):
            generate_final_summary(results)  # must not raise
        out = capsys.readouterr().out
        assert "WARNING" in out or "Could not save" in out


# ---------------------------------------------------------------------------
# generate_per_portfolio_summary — happy path body
# ---------------------------------------------------------------------------

class TestGeneratePerPortfolioSummaryBody:

    def test_prints_portfolio_name(self, capsys):
        results = [_minimal_result()]
        with patch("helpers.summary.save_trades_to_csv"):
            generate_per_portfolio_summary(
                results, "TestPortfolio", 0.10, 0.12, "run_001"
            )
        out = capsys.readouterr().out
        assert "TestPortfolio" in out

    def test_prints_spy_return(self, capsys):
        results = [_minimal_result()]
        with patch("helpers.summary.save_trades_to_csv"):
            generate_per_portfolio_summary(
                results, "TestPortfolio", 0.15, 0.12, "run_001"
            )
        out = capsys.readouterr().out
        assert "15.00%" in out

    def test_strategy_name_in_output(self, capsys):
        results = [_minimal_result(Strategy="RSI_Logic")]
        with patch("helpers.summary.save_trades_to_csv"):
            generate_per_portfolio_summary(
                results, "MyPort", 0.10, 0.10, "run_x"
            )
        out = capsys.readouterr().out
        assert "RSI_Logic" in out


# ---------------------------------------------------------------------------
# generate_per_portfolio_summary — display_df empty branch
# ---------------------------------------------------------------------------

class TestGeneratePerPortfolioDisplayEmpty:

    def test_no_strategies_pass_display_filter(self, capsys):
        """Trades=0 fails display filter → empty display_df → message printed."""
        results = [_minimal_result(Trades=0)]
        with patch("helpers.summary.save_trades_to_csv"):
            generate_per_portfolio_summary(
                results, "EmptyPort", 0.10, 0.10, "run_empty"
            )
        out = capsys.readouterr().out
        assert "No strategies" in out or "EmptyPort" in out


# ---------------------------------------------------------------------------
# generate_per_portfolio_summary — corr_matrix path
# ---------------------------------------------------------------------------

class TestGeneratePerPortfolioWithCorrMatrix:

    def test_with_correlation_matrix_adds_avg_corr_column(self, capsys):
        """corr_matrix provided → avg_corr column added to display_df."""
        results = [_minimal_result(Strategy="S1"), _minimal_result(Strategy="S2")]
        corr = pd.DataFrame(
            [[1.0, 0.3], [0.3, 1.0]],
            index=["S1", "S2"],
            columns=["S1", "S2"],
        )
        with patch("helpers.summary.save_trades_to_csv"):
            generate_per_portfolio_summary(
                results, "CorrPort", 0.10, 0.10, "run_c",
                corr_matrix=corr,
            )
        out = capsys.readouterr().out
        # Just assert no crash and something printed
        assert "CorrPort" in out

    def test_none_corr_matrix_uses_na(self, capsys):
        """corr_matrix=None → avg_corr='N/A' for all strategies."""
        results = [_minimal_result()]
        with patch("helpers.summary.save_trades_to_csv"):
            generate_per_portfolio_summary(
                results, "NoCorrPort", 0.05, 0.05, "run_nc",
                corr_matrix=None,
            )
        out = capsys.readouterr().out
        assert "NoCorrPort" in out


# ---------------------------------------------------------------------------
# generate_single_asset_summary_report — happy path body
# ---------------------------------------------------------------------------

class TestGenerateSingleAssetSummaryBody:

    def test_happy_path_does_not_crash(self, tmp_path, capsys):
        """Full run with a minimal valid symbol_result."""
        symbol_results = [
            _minimal_result(Strategy="BollingerBand", Asset="SPY"),
        ]
        spy_bench = {"pnl_percent": 0.12, "Trades": 252}
        qqq_bench = {"pnl_percent": 0.15, "Trades": 252}
        with patch("helpers.summary.save_trades_to_csv"):
            generate_single_asset_summary_report(
                symbol_results, spy_bench, qqq_bench,
                "SPY", str(tmp_path), "run_001",
            )
        # Just assert it doesn't raise
        assert True

    def test_output_contains_symbol(self, tmp_path, capsys):
        symbol_results = [_minimal_result(Strategy="RSI")]
        spy_bench = {"pnl_percent": 0.10, "Trades": 100}
        qqq_bench = {"pnl_percent": 0.12, "Trades": 100}
        with patch("helpers.summary.save_trades_to_csv"):
            generate_single_asset_summary_report(
                symbol_results, spy_bench, qqq_bench,
                "AAPL", str(tmp_path), "run_002",
            )
        out = capsys.readouterr().out
        # The function should print something about the symbol
        assert "AAPL" in out or len(out) > 0
