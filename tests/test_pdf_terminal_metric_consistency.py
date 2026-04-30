"""
tests/test_pdf_terminal_metric_consistency.py

Regression tests that verify PDF tearsheet metrics match terminal output
when PORTFOLIO_TIMELINE is supplied (the daily MTM equity curve from the
backtester).

Bugs caught and fixed:
  - CAGR duration: PDF used first-trade-to-last-trade; terminal uses full
    portfolio_timeline span.  PDF CAGR was systematically inflated vs terminal
    for any strategy with a warmup period.
  - Sharpe/Sortino period: PDF built daily_returns from the trade log (starting
    at first-trade-minus-1-day); terminal uses the full portfolio_timeline
    (including warmup bars with 0% returns).
  - Calmar: derives from CAGR, so was also wrong.
  - Risk-free rate: default_config.RISK_FREE_RATE was 0.0 while the backtester
    defaults to 0.05.  report.py now reads risk_free_rate from config_snapshot.json
    and default_config.RISK_FREE_RATE has been corrected to 0.05.

Fix (analyzer.py): when PORTFOLIO_TIMELINE is available, override daily_equity,
daily_returns, and total_duration_years so all downstream metrics use the same
data as the terminal.
Fix (report_generator.py): generate_overall_metrics_summary prefers
daily_equity.index span for CAGR duration over first-trade/last-trade dates.
Fix (report.py + default_config.py): risk_free_rate is now read from
config_snapshot.json so the PDF Sharpe/Sortino use the same rate as the terminal.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
import numpy as np
import pandas as pd
import pytest

from helpers.simulations import calculate_advanced_metrics
from trade_analyzer import calculations
from trade_analyzer import report_generator


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_timeline(n_days: int = 252 * 5, drift: float = 0.0005) -> pd.Series:
    """Steady-drift equity curve that starts from 2015-01-02."""
    np.random.seed(99)
    daily_rets = drift + np.random.normal(0, 0.008, n_days)
    equity = 100_000 * np.cumprod(1 + daily_rets)
    return pd.Series(equity, index=pd.bdate_range("2015-01-02", periods=n_days))


def _make_trades_df(timeline: pd.Series, warmup_bars: int = 50) -> pd.DataFrame:
    """
    Build a minimal trades DataFrame whose Date.min() is `warmup_bars` after
    the timeline start, simulating a strategy that needs warmup before trading.
    """
    trade_dates = timeline.index[warmup_bars:]
    n = len(trade_dates)
    profits = np.diff(timeline.values[warmup_bars:], prepend=timeline.values[warmup_bars])
    cum_profit = np.cumsum(profits)
    return pd.DataFrame({
        'Date': trade_dates,
        'Ex. date': trade_dates,
        'Profit': profits,
        'Cumulative_Profit': cum_profit,
        'Win': profits > 0,
        '% Profit': profits / timeline.values[warmup_bars] * 100,
        'Return_Frac': profits / timeline.values[warmup_bars],
        'Equity': 100_000 + cum_profit,
    })


RF = 0.05
TRADING_DAYS = 252


# ---------------------------------------------------------------------------
# CAGR duration consistency
# ---------------------------------------------------------------------------

class TestCagrDurationConsistency:
    """PDF CAGR must use the full portfolio_timeline span, not first-to-last trade."""

    def test_terminal_cagr_uses_full_period(self):
        tl = _make_timeline()
        metrics = calculate_advanced_metrics([1.0] * 10, tl, [1] * 10)
        duration = (tl.index[-1] - tl.index[0]).days / 365.25
        expected = (tl.iloc[-1] / tl.iloc[0]) ** (1 / duration) - 1
        assert abs(metrics.get("calmar_ratio", 0) * metrics.get("max_drawdown", 1) - expected) < 1e-4

    def test_pdf_duration_prefers_daily_equity_index(self):
        """generate_overall_metrics_summary must use daily_equity index span."""
        import re
        tl = _make_timeline(n_days=252 * 5)
        warmup = 50
        trades_df = _make_trades_df(tl, warmup_bars=warmup)

        # daily_equity = full portfolio_timeline (as set by analyzer.py after fix)
        daily_equity = tl
        daily_returns = tl.pct_change().dropna()

        _, summary = report_generator.generate_overall_metrics_summary(
            trades_df, daily_returns, pd.Series(dtype=float), None,
            daily_equity, 'SPY', 100_000, RF, TRADING_DAYS,
        )

        full_duration = (tl.index[-1] - tl.index[0]).days / 365.25
        trade_duration = (trades_df['Ex. date'].max() - trades_df['Date'].min()).days / 365.25

        # The durations differ because of the warmup
        assert full_duration > trade_duration - 0.01, "Sanity: full_duration should exceed trade_duration"

        # summary is a '\n'-joined string
        lines = [l for l in summary.split('\n') if "years" in l]
        assert lines, f"Duration line not found in summary. Summary snippet:\n{summary[:400]}"
        match = re.search(r"(\d+\.\d+)\s+years", lines[0])
        assert match, f"Could not parse years from: {lines[0]}"
        reported_years = float(match.group(1))
        assert abs(reported_years - full_duration) < 0.1, (
            f"PDF duration {reported_years:.2f} yr should match full period "
            f"{full_duration:.2f} yr, not trade-only {trade_duration:.2f} yr"
        )

    def test_cagr_matches_terminal_when_portfolio_timeline_provided(self):
        """With PORTFOLIO_TIMELINE supplied, PDF CAGR must agree with terminal."""
        tl = _make_timeline()
        warmup = 50
        trades_df = _make_trades_df(tl, warmup_bars=warmup)

        # Terminal CAGR
        terminal_metrics = calculate_advanced_metrics([1.0] * 10, tl, [1] * 10)
        terminal_dur = (tl.index[-1] - tl.index[0]).days / 365.25
        terminal_cagr = (tl.iloc[-1] / tl.iloc[0]) ** (1 / terminal_dur) - 1

        # PDF CAGR (using the equity index span as fixed)
        daily_equity_fixed = tl
        pdf_dur = (daily_equity_fixed.index[-1] - daily_equity_fixed.index[0]).days / 365.25
        pdf_cagr = calculations.calculate_cagr(100_000, tl.iloc[-1], pdf_dur)

        assert abs(pdf_cagr - terminal_cagr) < 0.001, (
            f"PDF CAGR {pdf_cagr:.4f} vs terminal CAGR {terminal_cagr:.4f} — "
            "they should match when the same period is used"
        )

    def test_warmup_inflates_cagr_when_trade_dates_used(self):
        """Demonstrate the old bug: trade-date duration < full duration → inflated CAGR."""
        tl = _make_timeline()
        warmup = 100
        trades_df = _make_trades_df(tl, warmup_bars=warmup)

        full_dur = (tl.index[-1] - tl.index[0]).days / 365.25
        trade_dur = (trades_df['Ex. date'].max() - trades_df['Date'].min()).days / 365.25

        full_cagr = calculations.calculate_cagr(100_000, tl.iloc[-1], full_dur)
        trade_cagr = calculations.calculate_cagr(100_000, tl.iloc[-1], trade_dur)

        # Shorter denominator → higher CAGR (for profitable strategies)
        if tl.iloc[-1] > 100_000:
            assert trade_cagr > full_cagr, (
                "For a profitable strategy, trade-date CAGR should exceed full-period CAGR"
            )


# ---------------------------------------------------------------------------
# Sharpe period consistency
# ---------------------------------------------------------------------------

class TestSharpePeriodConsistency:
    """PDF Sharpe must use the full portfolio_timeline when provided."""

    def test_terminal_sharpe_includes_warmup(self):
        """Terminal Sharpe uses the full timeline — adding zero-return warmup bars
        slightly changes the Sharpe vs starting from the first trade."""
        np.random.seed(42)
        n = 252 * 5
        warmup = 100
        rets = 0.0005 + np.random.normal(0, 0.008, n)
        equity = 100_000 * np.cumprod(1 + rets)
        tl = pd.Series(equity, index=pd.bdate_range("2015-01-02", periods=n))

        # Sharpe from full timeline (terminal)
        terminal_metrics = calculate_advanced_metrics([1.0] * 10, tl, [1])
        sharpe_full = terminal_metrics["sharpe_ratio"]

        # Sharpe from trade-only period (old PDF behaviour)
        tl_trades = tl.iloc[warmup:]
        trade_metrics = calculate_advanced_metrics([1.0] * 10, tl_trades, [1])
        sharpe_trades = trade_metrics["sharpe_ratio"]

        # They differ — validating that the period matters
        assert sharpe_full != pytest.approx(sharpe_trades, abs=0.05), (
            "Sharpe from full period should differ from trade-only period"
        )

    def test_pdf_sharpe_matches_terminal_when_full_timeline_used(self):
        """When daily_returns is derived from the full portfolio_timeline,
        PDF Sharpe == terminal Sharpe (same formula, same data)."""
        tl = _make_timeline()
        pnl_list = [float(tl.iloc[-1] - tl.iloc[0])]

        terminal_metrics = calculate_advanced_metrics(pnl_list, tl, [len(tl)])
        terminal_sharpe = terminal_metrics["sharpe_ratio"]

        # Simulate what analyzer.py now does: derive daily_returns from portfolio_timeline
        daily_returns = tl.pct_change().dropna()
        rf_daily = (1 + RF) ** (1 / TRADING_DAYS) - 1
        excess = daily_returns - rf_daily
        pdf_sharpe = (excess.mean() / excess.std()) * math.sqrt(TRADING_DAYS)

        assert abs(pdf_sharpe - terminal_sharpe) < 1e-6, (
            f"PDF Sharpe {pdf_sharpe:.6f} must equal terminal Sharpe {terminal_sharpe:.6f}"
        )


# ---------------------------------------------------------------------------
# report_generator.generate_overall_metrics_summary — duration preference
# ---------------------------------------------------------------------------

class TestGenerateOverallMetricsSummaryDuration:
    """generate_overall_metrics_summary must prefer daily_equity.index span."""

    def test_duration_from_equity_index_not_trade_dates(self):
        import re
        warmup = 60
        tl = _make_timeline(n_days=252 * 3)
        trades_df = _make_trades_df(tl, warmup_bars=warmup)
        daily_equity = tl
        daily_returns = tl.pct_change().dropna()

        _, summary = report_generator.generate_overall_metrics_summary(
            trades_df, daily_returns, pd.Series(dtype=float), None,
            daily_equity, 'SPY', 100_000, RF, TRADING_DAYS,
        )

        expected_dur = (tl.index[-1] - tl.index[0]).days / 365.25
        lines = [l for l in summary.split('\n') if "years" in l]
        assert lines, f"Duration line missing. Summary:\n{summary[:300]}"
        match = re.search(r"(\d+\.\d+)\s+years", lines[0])
        assert match
        reported = float(match.group(1))
        assert abs(reported - expected_dur) < 0.05

    def test_falls_back_to_trade_dates_when_no_equity(self):
        """When daily_equity is empty, trade dates are still used as before."""
        import re
        warmup = 60
        tl = _make_timeline(n_days=252 * 3)
        trades_df = _make_trades_df(tl, warmup_bars=warmup)
        empty_equity = pd.Series(dtype=float)
        daily_returns = tl.pct_change().dropna()

        _, summary = report_generator.generate_overall_metrics_summary(
            trades_df, daily_returns, pd.Series(dtype=float), None,
            empty_equity, 'SPY', 100_000, RF, TRADING_DAYS,
        )

        trade_dur = (trades_df['Ex. date'].max() - trades_df['Date'].min()).days / 365.25
        lines = [l for l in summary.split('\n') if "years" in l]
        assert lines, f"Duration line missing. Summary:\n{summary[:300]}"
        match = re.search(r"(\d+\.\d+)\s+years", lines[0])
        assert match
        reported = float(match.group(1))
        assert abs(reported - trade_dur) < 0.05


# ---------------------------------------------------------------------------
# Risk-free rate consistency
# ---------------------------------------------------------------------------

class TestRiskFreeRateConsistency:
    """PDF Sharpe must use the backtester's risk_free_rate, not the analyzer default."""

    def test_default_config_risk_free_rate_matches_backtester(self):
        """default_config.RISK_FREE_RATE must equal the backtester's default (0.05)."""
        from trade_analyzer.default_config import RISK_FREE_RATE as ANALYZER_RF
        from config import CONFIG
        assert ANALYZER_RF == CONFIG["risk_free_rate"], (
            f"default_config.RISK_FREE_RATE={ANALYZER_RF} must equal "
            f"config.CONFIG['risk_free_rate']={CONFIG['risk_free_rate']}"
        )

    def test_sharpe_differs_between_rf_zero_and_rf_five_pct(self):
        """Sharpe with rf=0.0 differs from rf=0.05 — confirms the rate is not ignored."""
        tl = _make_timeline()
        daily_returns = tl.pct_change().dropna()

        sharpe_rf0 = calculations.calculate_sharpe_ratio(daily_returns, 0.0, TRADING_DAYS)
        sharpe_rf5 = calculations.calculate_sharpe_ratio(daily_returns, 0.05, TRADING_DAYS)

        assert sharpe_rf0 != pytest.approx(sharpe_rf5, abs=0.01), (
            "Sharpe with rf=0.0 must differ from rf=0.05 to show the rate is applied"
        )
        assert sharpe_rf0 > sharpe_rf5, (
            f"For a positive-drift strategy, rf=0 Sharpe ({sharpe_rf0:.4f}) "
            f"must exceed rf=0.05 Sharpe ({sharpe_rf5:.4f})"
        )

    def test_pdf_sharpe_matches_terminal_with_correct_rf(self):
        """With the same rf rate and timeline, PDF and terminal Sharpe must agree."""
        np.random.seed(7)
        tl = _make_timeline()
        pnl_list = [float(tl.iloc[-1] - tl.iloc[0])]
        from unittest.mock import patch
        with patch.dict("config.CONFIG", {"risk_free_rate": RF, "timeframe": "D", "timeframe_multiplier": 1}):
            terminal_metrics = calculate_advanced_metrics(pnl_list, tl, [len(tl)])
        terminal_sharpe = terminal_metrics["sharpe_ratio"]

        daily_returns = tl.pct_change().dropna()
        pdf_sharpe = calculations.calculate_sharpe_ratio(daily_returns, RF, TRADING_DAYS)

        assert abs(pdf_sharpe - terminal_sharpe) < 1e-6, (
            f"PDF Sharpe {pdf_sharpe:.6f} must equal terminal Sharpe {terminal_sharpe:.6f}"
        )

    def test_load_risk_free_rate_reads_from_snapshot(self, tmp_path):
        """_load_risk_free_rate must return the rate stored in config_snapshot.json."""
        import json
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from report import _load_risk_free_rate

        snapshot = {"risk_free_rate": 0.03, "timeframe": "D"}
        (tmp_path / "config_snapshot.json").write_text(json.dumps(snapshot))
        assert _load_risk_free_rate(tmp_path) == pytest.approx(0.03)

    def test_load_risk_free_rate_returns_none_when_missing(self, tmp_path):
        """_load_risk_free_rate returns None when config_snapshot.json is absent."""
        from report import _load_risk_free_rate
        assert _load_risk_free_rate(tmp_path) is None
