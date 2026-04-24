# tests/test_exclude_open_positions.py
"""
Unit tests for realized-only reporting mode (SECTION 22).

When exclude_open_positions=True, positions still open at the final bar are
excluded from the trade log. The headline P&L (%) is the sum of closed-trade
profits divided by initial_capital instead of reading from the last bar of the
portfolio_timeline (which includes unrealized MTM).

Covers:
  TestConfigDefaults            — key presence and default value
  TestEobIncludedByDefault      — default mode includes EoB trades (no regression)
  TestExcludeDropsEobTrades     — flag=True removes EoB trades from trade log
  TestRealizedPnlFormula        — pnl_percent equals sum(realized) / initial_capital
  TestNoOpenPositionsRegression — no open positions → both modes give identical counts
"""

import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import CONFIG
from helpers.portfolio_simulations import run_portfolio_simulation


# ---------------------------------------------------------------------------
# Shared config patch — zero costs, open execution
# ---------------------------------------------------------------------------

_BASE_CONFIG = {
    "slippage_pct": 0.0,
    "commission_per_share": 0.0,
    "execution_time": "open",
    "max_pct_adv": 0,
    "volume_impact_coeff": 0.0,
    "risk_free_rate": 0.05,
    "htb_rate_annual": 0.0,
}


# ---------------------------------------------------------------------------
# Synthetic data builders
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 60, start_price: float = 100.0, trend: float = 0.002) -> pd.DataFrame:
    dates = pd.bdate_range(start="2020-01-02", periods=n)
    closes = np.array([start_price * (1 + trend) ** i for i in range(n)])
    df = pd.DataFrame({
        "Open":   closes * 0.999,
        "High":   closes * 1.01,
        "Low":    closes * 0.99,
        "Close":  closes,
        "Volume": np.full(n, 1_000_000.0),
    }, index=dates)
    df.index.name = "Datetime"
    return df


def _make_signals(index: pd.DatetimeIndex, entry_idx: int, exit_idx: int | None) -> pd.Series:
    """
    Build a Signal series on `index`.

    entry_idx  — position whose value is set to 1 (fires entry at index[entry_idx+1])
    exit_idx   — position whose value is set to -1 (fires exit at index[exit_idx+1]);
                 pass None to leave position open until end-of-backtest
    """
    signals = pd.Series(0, index=index, dtype=int)
    signals.iloc[entry_idx] = 1
    if exit_idx is not None:
        signals.iloc[exit_idx] = -1
    return signals


# ---------------------------------------------------------------------------
# Fixtures that guarantee at least one closed trade AND one open position
# ---------------------------------------------------------------------------

def _run_sim_with_open_position(exclude: bool):
    """
    Two-symbol simulation:
      SYM_A — enters at bar 5, exits at bar 15 (one closed trade)
      SYM_B — enters at bar 30, never exits (one EoB open position)

    Returns the result dict from run_portfolio_simulation.
    """
    n = 60
    df_a = _make_ohlcv(n=n, start_price=100.0, trend=0.003)
    df_b = _make_ohlcv(n=n, start_price=50.0,  trend=0.002)

    # Signal on bar i fires entry/exit at bar i+1 (open execution)
    sig_a = _make_signals(df_a.index, entry_idx=4, exit_idx=14)   # closed trade
    sig_b = _make_signals(df_b.index, entry_idx=29, exit_idx=None) # open at end

    config_patch = {**_BASE_CONFIG, "exclude_open_positions": exclude}
    with patch.dict("config.CONFIG", config_patch):
        return run_portfolio_simulation(
            portfolio_data={"SYM_A": df_a, "SYM_B": df_b},
            signals={"SYM_A": sig_a, "SYM_B": sig_b},
            initial_capital=100_000.0,
            allocation_pct=0.10,
            spy_df=None,
            vix_df=None,
            tnx_df=None,
            stop_config={"type": "none"},
        )


def _run_sim_no_open_position(exclude: bool):
    """
    Single-symbol simulation where the strategy always exits before the last bar.
    Used for the no-regression test.
    """
    n = 60
    df_a = _make_ohlcv(n=n, start_price=100.0, trend=0.003)
    sig_a = _make_signals(df_a.index, entry_idx=4, exit_idx=14)  # closed, never open at end

    config_patch = {**_BASE_CONFIG, "exclude_open_positions": exclude}
    with patch.dict("config.CONFIG", config_patch):
        return run_portfolio_simulation(
            portfolio_data={"SYM_A": df_a},
            signals={"SYM_A": sig_a},
            initial_capital=100_000.0,
            allocation_pct=0.10,
            spy_df=None,
            vix_df=None,
            tnx_df=None,
            stop_config={"type": "none"},
        )


# ---------------------------------------------------------------------------
# TestConfigDefaults
# ---------------------------------------------------------------------------

class TestConfigDefaults:

    def test_exclude_open_positions_key_present(self):
        assert "exclude_open_positions" in CONFIG

    def test_exclude_open_positions_default_is_false(self):
        """Default must be False so existing runs are unaffected."""
        assert CONFIG["exclude_open_positions"] is False


# ---------------------------------------------------------------------------
# TestEobIncludedByDefault
# ---------------------------------------------------------------------------

class TestEobIncludedByDefault:
    """With exclude_open_positions=False the EoB trade must appear in trade_log."""

    @pytest.fixture(scope="class")
    def result(self):
        return _run_sim_with_open_position(exclude=False)

    def test_result_is_not_none(self, result):
        assert result is not None

    def test_eob_trade_present(self, result):
        eob_trades = [t for t in result["trade_log"] if t["ExitReason"] == "End of Backtest"]
        assert len(eob_trades) >= 1, "Expected at least one End-of-Backtest trade in default mode"

    def test_trade_count_includes_eob(self, result):
        eob = sum(1 for t in result["trade_log"] if t["ExitReason"] == "End of Backtest")
        closed = sum(1 for t in result["trade_log"] if t["ExitReason"] != "End of Backtest")
        assert result["Trades"] == eob + closed


# ---------------------------------------------------------------------------
# TestExcludeDropsEobTrades
# ---------------------------------------------------------------------------

class TestExcludeDropsEobTrades:
    """With exclude_open_positions=True the EoB trades must be absent."""

    @pytest.fixture(scope="class")
    def result(self):
        return _run_sim_with_open_position(exclude=True)

    def test_result_is_not_none(self, result):
        assert result is not None, (
            "Simulation returned None — the closed trade should keep the trade log non-empty"
        )

    def test_no_eob_trades_in_log(self, result):
        eob_trades = [t for t in result["trade_log"] if t["ExitReason"] == "End of Backtest"]
        assert eob_trades == [], f"Expected no EoB trades; got {eob_trades}"

    def test_trade_count_is_closed_only(self, result):
        """Trades should equal only the strategies that fully closed."""
        assert result["Trades"] == len(result["trade_log"])
        assert all(t["ExitReason"] != "End of Backtest" for t in result["trade_log"])

    def test_fewer_trades_than_default_mode(self):
        result_default = _run_sim_with_open_position(exclude=False)
        result_realized = _run_sim_with_open_position(exclude=True)
        assert result_realized["Trades"] < result_default["Trades"], (
            "Realized-only mode should have fewer trades than default (EoB dropped)"
        )


# ---------------------------------------------------------------------------
# TestRealizedPnlFormula
# ---------------------------------------------------------------------------

class TestRealizedPnlFormula:
    """pnl_percent must equal sum(closed profits) / initial_capital when flag is True."""

    @pytest.fixture(scope="class")
    def result(self):
        return _run_sim_with_open_position(exclude=True)

    def test_pnl_percent_matches_realized_sum(self, result):
        closed_profits = [t["Profit"] for t in result["trade_log"]]
        expected = sum(closed_profits) / 100_000.0
        assert abs(result["pnl_percent"] - expected) < 1e-9, (
            f"pnl_percent {result['pnl_percent']:.6f} != realized sum / capital {expected:.6f}"
        )

    def test_pnl_percent_differs_from_timeline_tail(self, result):
        """Realized P&L must differ from the last portfolio_timeline bar,
        which still includes the open position's unrealized MTM."""
        timeline_pnl = (result["portfolio_timeline"].iloc[-1] / 100_000.0) - 1
        # They will differ because the timeline includes the unrealized open position
        assert abs(result["pnl_percent"] - timeline_pnl) > 1e-6, (
            "pnl_percent should not equal the timeline-based figure when open positions exist"
        )


# ---------------------------------------------------------------------------
# TestNoOpenPositionsRegression
# ---------------------------------------------------------------------------

class TestNoOpenPositionsRegression:
    """When no positions are open at end, both modes produce the same trade count."""

    def test_trade_count_identical_when_no_open_positions(self):
        result_default  = _run_sim_no_open_position(exclude=False)
        result_realized = _run_sim_no_open_position(exclude=True)

        assert result_default  is not None
        assert result_realized is not None

        assert result_default["Trades"] == result_realized["Trades"], (
            "Trade count must be identical when no positions are open at backtest end"
        )

    def test_no_eob_trades_in_either_mode(self):
        result_default  = _run_sim_no_open_position(exclude=False)
        result_realized = _run_sim_no_open_position(exclude=True)

        for result, label in [(result_default, "default"), (result_realized, "realized")]:
            eob = [t for t in result["trade_log"] if t["ExitReason"] == "End of Backtest"]
            assert eob == [], f"Unexpected EoB trade in {label} mode: {eob}"
