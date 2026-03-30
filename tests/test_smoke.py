# tests/test_smoke.py
"""
Integration smoke test — end-to-end portfolio simulation with synthetic data.

Runs run_portfolio_simulation with a 2-symbol mini portfolio, 30 bars of
synthetic OHLCV data, and SMA crossover signals. Asserts:
  - result dict has all expected keys
  - portfolio_timeline has correct length
  - trade_log is a list
  - P&L is a finite number
  - no exceptions are raised during the full simulation path

No file I/O, no network — pure in-memory. This catches wiring regressions
that unit tests miss.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from unittest.mock import patch
from helpers.portfolio_simulations import run_portfolio_simulation
from helpers.indicators import sma_crossover_logic


# ---------------------------------------------------------------------------
# Helpers — synthetic data builders
# ---------------------------------------------------------------------------

def _make_ohlcv(n=30, start_price=100.0, trend=0.002, start="2023-01-02"):
    """
    Build a synthetic OHLCV DataFrame with n business days.
    Prices follow a gentle uptrend so SMA crossovers will fire.
    """
    dates = pd.bdate_range(start=start, periods=n, freq="B")
    closes = [start_price * (1 + trend) ** i for i in range(n)]
    df = pd.DataFrame({
        "Open":   [c * 0.999 for c in closes],
        "High":   [c * 1.01 for c in closes],
        "Low":    [c * 0.99 for c in closes],
        "Close":  closes,
        "Volume": [1_000_000 + i * 10_000 for i in range(n)],
    }, index=dates)
    df.index.name = "Datetime"
    return df


def _make_spy_df(n=30, start="2023-01-02"):
    """Build a synthetic SPY DataFrame aligned to the same dates."""
    return _make_ohlcv(n=n, start_price=400.0, trend=0.001, start=start)


def _make_vix_df(n=30, start="2023-01-02"):
    """Build a synthetic VIX DataFrame with low volatility."""
    dates = pd.bdate_range(start=start, periods=n, freq="B")
    df = pd.DataFrame({
        "Open": [18.0] * n, "High": [19.0] * n,
        "Low": [17.0] * n, "Close": [18.0] * n,
        "Volume": [0] * n,
    }, index=dates)
    df.index.name = "Datetime"
    return df


def _generate_signals(df, fast=5, slow=10):
    """
    Run SMA crossover on a DataFrame and return the Signal series.
    Uses short lookbacks so signals fire within 30 bars.
    """
    df_copy = df.copy()
    df_copy = sma_crossover_logic(df_copy, fast=fast, slow=slow)
    return df_copy["Signal"]


# ---------------------------------------------------------------------------
# Config override — minimal trading costs for predictable results
# ---------------------------------------------------------------------------

_TEST_CONFIG = {
    "slippage_pct": 0.0,
    "commission_per_share": 0.0,
    "execution_time": "open",
    "max_pct_adv": 0,
    "volume_impact_coeff": 0.0,
    "risk_free_rate": 0.05,
    "htb_rate_annual": 0.0,
}


# ---------------------------------------------------------------------------
# TestSmokeEndToEnd
# ---------------------------------------------------------------------------

class TestSmokeEndToEnd:
    """End-to-end integration test using run_portfolio_simulation."""

    @pytest.fixture
    def sim_result(self):
        """Run a full simulation and return the result dict."""
        n = 60  # enough bars for SMA(5/10) to warm up and generate trades

        sym_a = _make_ohlcv(n=n, start_price=100.0, trend=0.003)
        sym_b = _make_ohlcv(n=n, start_price=50.0, trend=0.002)
        spy_df = _make_spy_df(n=n)
        vix_df = _make_vix_df(n=n)

        portfolio_data = {"TESTA": sym_a, "TESTB": sym_b}
        signals = {
            "TESTA": _generate_signals(sym_a),
            "TESTB": _generate_signals(sym_b),
        }

        with patch.dict("config.CONFIG", _TEST_CONFIG):
            result = run_portfolio_simulation(
                portfolio_data=portfolio_data,
                signals=signals,
                initial_capital=100_000.0,
                allocation_pct=0.10,
                spy_df=spy_df,
                vix_df=vix_df,
                tnx_df=None,
                stop_config={"type": "none"},
            )
        return result

    def test_result_is_not_none(self, sim_result):
        """Simulation must return a result dict, not None."""
        assert sim_result is not None, "Simulation returned None — no trades were generated"

    def test_result_has_expected_keys(self, sim_result):
        """Result dict must contain all core metric keys."""
        expected_keys = [
            "pnl_percent", "Trades", "trade_log", "trade_pnl_list",
            "portfolio_timeline", "initial_capital",
            "max_drawdown", "sharpe_ratio", "win_rate", "profit_factor",
            "calmar_ratio",
        ]
        for key in expected_keys:
            assert key in sim_result, f"Missing key: {key}"

    def test_portfolio_timeline_is_series(self, sim_result):
        """portfolio_timeline must be a pandas Series."""
        assert isinstance(sim_result["portfolio_timeline"], pd.Series)

    def test_portfolio_timeline_not_empty(self, sim_result):
        """portfolio_timeline must have entries."""
        assert len(sim_result["portfolio_timeline"]) > 0

    def test_portfolio_timeline_starts_near_initial_capital(self, sim_result):
        """First equity value should be close to initial capital (no trades on day 1)."""
        first_val = sim_result["portfolio_timeline"].iloc[0]
        assert abs(first_val - 100_000.0) < 1_000, f"First equity {first_val} too far from 100k"

    def test_trade_log_is_list(self, sim_result):
        """trade_log must be a list."""
        assert isinstance(sim_result["trade_log"], list)

    def test_trade_log_has_trades(self, sim_result):
        """At least one trade should have been generated."""
        assert len(sim_result["trade_log"]) > 0

    def test_trade_log_entries_have_required_fields(self, sim_result):
        """Each trade log entry must have the core fields."""
        required_fields = [
            "Symbol", "Trade", "EntryDate", "ExitDate",
            "EntryPrice", "ExitPrice", "Profit", "Shares",
            "is_win", "HoldDuration", "ExitReason",
            "InitialRisk", "RMultiple",
        ]
        for trade in sim_result["trade_log"]:
            for field in required_fields:
                assert field in trade, f"Trade missing field: {field}"

    def test_pnl_is_finite(self, sim_result):
        """P&L percent must be a finite number."""
        assert np.isfinite(sim_result["pnl_percent"]), f"P&L is not finite: {sim_result['pnl_percent']}"

    def test_trades_count_matches_log(self, sim_result):
        """Trades count must match the length of trade_log."""
        assert sim_result["Trades"] == len(sim_result["trade_log"])

    def test_max_drawdown_non_negative(self, sim_result):
        """Max drawdown must be >= 0."""
        assert sim_result["max_drawdown"] >= 0

    def test_win_rate_between_zero_and_one(self, sim_result):
        """Win rate must be between 0 and 1."""
        assert 0 <= sim_result["win_rate"] <= 1

    def test_trade_symbols_are_from_portfolio(self, sim_result):
        """All traded symbols must come from the portfolio."""
        valid_symbols = {"TESTA", "TESTB"}
        for trade in sim_result["trade_log"]:
            assert trade["Symbol"] in valid_symbols, f"Unknown symbol: {trade['Symbol']}"


# ---------------------------------------------------------------------------
# TestSmokeWithStopLoss
# ---------------------------------------------------------------------------

class TestSmokeWithStopLoss:
    """Smoke test with a percentage stop loss enabled."""

    def test_percentage_stop_does_not_crash(self):
        """Running with a percentage stop should complete without errors."""
        n = 60
        sym = _make_ohlcv(n=n, start_price=100.0, trend=0.001)
        spy_df = _make_spy_df(n=n)
        vix_df = _make_vix_df(n=n)

        portfolio_data = {"TEST": sym}
        signals = {"TEST": _generate_signals(sym)}

        with patch.dict("config.CONFIG", _TEST_CONFIG):
            result = run_portfolio_simulation(
                portfolio_data=portfolio_data,
                signals=signals,
                initial_capital=100_000.0,
                allocation_pct=0.10,
                spy_df=spy_df,
                vix_df=vix_df,
                tnx_df=None,
                stop_config={"type": "percentage", "value": 0.05},
            )
        # Result may be None if the stop prevented all trades from completing,
        # but the simulation must not crash.
        assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# TestSmokeEmptyPortfolio
# ---------------------------------------------------------------------------

class TestSmokeEmptyPortfolio:
    """Edge case: simulation with no matching signals."""

    def test_no_trades_returns_none(self):
        """If no trades are generated, result should be None."""
        n = 30
        sym = _make_ohlcv(n=n, start_price=100.0, trend=0.0)  # flat price
        spy_df = _make_spy_df(n=n)
        vix_df = _make_vix_df(n=n)

        # All signals are -1 (never enter)
        signals = {"TEST": pd.Series(-1, index=sym.index)}
        portfolio_data = {"TEST": sym}

        with patch.dict("config.CONFIG", _TEST_CONFIG):
            result = run_portfolio_simulation(
                portfolio_data=portfolio_data,
                signals=signals,
                initial_capital=100_000.0,
                allocation_pct=0.10,
                spy_df=spy_df,
                vix_df=vix_df,
                tnx_df=None,
                stop_config={"type": "none"},
            )
        assert result is None, "Expected None when no trades are generated"
