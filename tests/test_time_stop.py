"""
tests/test_time_stop.py

Unit tests for the asymmetric time stop feature (Section 23 of config.py).

Rule:
  After `time_stop_days` calendar days, exit a position at the current
  Close if it is currently at a loss (close < entry price).
  When `time_stop_losers_only=True` (default), profitable positions are
  never cut — they run until the strategy exits them.
"""
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from helpers.portfolio_simulations import run_portfolio_simulation

# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

_BASE_CONFIG = {
    "slippage_pct": 0.0,
    "commission_per_share": 0.0,
    "execution_time": "close",   # signal on day D → entry/exit at D's close
    "max_pct_adv": 0,
    "volume_impact_coeff": 0.0,
    "risk_free_rate": 0.05,
    "htb_rate_annual": 0.0,
    "timeframe": "D",
    "timeframe_multiplier": 1,
    "time_stop_days": None,      # default: disabled
    "time_stop_losers_only": True,
}


def _make_data(prices: list[float], *, entry_bar: int = 1) -> tuple[dict, dict]:
    """
    Build portfolio_data and signals for a single symbol "SYM".

    Signal = 1 on `entry_bar`, 0 on all other bars (hold until externally cut).
    Prices are used as Open / High / Low / Close on every bar.
    """
    n = len(prices)
    dates = pd.bdate_range("2020-01-02", periods=n)
    arr = np.array(prices, dtype=float)
    df = pd.DataFrame({
        "Open":            arr,
        "High":            arr + 1.0,
        "Low":             arr - 1.0,
        "Close":           arr,
        "Volume":          np.full(n, 1_000_000.0),
        "ATR_14":          np.full(n, 2.0),
        "RSI_14":          np.full(n, 50.0),
        "ATR_14_pct":      np.full(n, 0.02),
        "SMA200_dist_pct": np.full(n, 0.05),
        "Volume_Spike":    np.full(n, 1.0),
    }, index=dates)
    portfolio_data = {"SYM": df}

    sig = pd.Series(0, index=dates)
    sig.iloc[entry_bar] = 1
    signals = {"SYM": sig}
    return portfolio_data, signals


def _run(portfolio_data, signals, extra_config=None):
    cfg = {**_BASE_CONFIG, **(extra_config or {})}
    with patch.dict("config.CONFIG", cfg):
        return run_portfolio_simulation(
            portfolio_data=portfolio_data,
            signals=signals,
            initial_capital=100_000.0,
            allocation_pct=0.10,
            spy_df=None,
            vix_df=None,
            tnx_df=None,
            stop_config={"type": "none"},
        )


def _exit_reason(result) -> str:
    log = result["trade_log"]
    assert len(log) == 1, f"Expected 1 trade, got {len(log)}"
    return log[0]["ExitReason"]


def _hold_days(result) -> int:
    log = result["trade_log"]
    assert len(log) == 1
    return log[0]["HoldDuration"]


# ------------------------------------------------------------------
# TestTimeStopDisabledByDefault
# ------------------------------------------------------------------

class TestTimeStopDisabledByDefault:
    """time_stop_days=None must never fire."""

    def test_loser_not_cut_when_disabled(self):
        """A losing position runs to end-of-backtest when no time stop is set."""
        # Entry at 100, price drops to 80 and stays there (25 bars ≈ 34 calendar days)
        prices = [100.0] + [100.0] + [80.0] * 23
        portfolio_data, signals = _make_data(prices)
        result = _run(portfolio_data, signals, {"time_stop_days": None})
        assert _exit_reason(result) == "End of Backtest"

    def test_config_key_absent_no_crash(self):
        """Missing time_stop_days key in config must not raise."""
        prices = [100.0] + [100.0] + [80.0] * 23
        portfolio_data, signals = _make_data(prices)
        cfg = {k: v for k, v in _BASE_CONFIG.items()
               if k not in ("time_stop_days", "time_stop_losers_only")}
        with patch.dict("config.CONFIG", cfg):
            result = run_portfolio_simulation(
                portfolio_data=portfolio_data,
                signals=signals,
                initial_capital=100_000.0,
                allocation_pct=0.10,
                spy_df=None,
                vix_df=None,
                tnx_df=None,
                stop_config={"type": "none"},
            )
        assert result is not None


# ------------------------------------------------------------------
# TestAsymmetricTimeStopLosers
# ------------------------------------------------------------------

class TestAsymmetricTimeStopLosers:
    """time_stop_losers_only=True (default): cuts losers, protects winners."""

    def test_loser_cut_at_n_days(self):
        """A position at a loss after N calendar days fires 'Time Stop'."""
        # Entry bar 1 = Jan 3 2020 (price 100); price drops to 80 on bar 2.
        # 10-day stop: Jan 3 + 10 calendar days = Jan 13.
        # bdate_range: bar 1=Jan3, bar 2=Jan6(Mon), ..., bar 8=Jan14 = 11 days from entry → fires.
        prices = [100.0, 100.0, 80.0] + [80.0] * 22
        portfolio_data, signals = _make_data(prices)
        result = _run(portfolio_data, signals, {"time_stop_days": 10, "time_stop_losers_only": True})
        assert _exit_reason(result) == "Time Stop"

    def test_loser_not_cut_before_n_days(self):
        """A loser that hasn't hit N days yet is NOT cut."""
        # Only 5 bars after entry → at most ~5 calendar days → not hit 10-day stop
        prices = [100.0, 100.0, 80.0, 80.0, 80.0, 80.0]
        portfolio_data, signals = _make_data(prices)
        result = _run(portfolio_data, signals, {"time_stop_days": 10, "time_stop_losers_only": True})
        assert _exit_reason(result) == "End of Backtest"

    def test_winner_not_cut_by_time_stop(self):
        """A profitable position is never cut by the time stop."""
        # Entry at 100, rises to 120 and holds.  20-day stop passes, still no cut.
        prices = [100.0, 100.0, 120.0] + [120.0] * 27
        portfolio_data, signals = _make_data(prices)
        result = _run(portfolio_data, signals, {"time_stop_days": 10, "time_stop_losers_only": True})
        assert _exit_reason(result) == "End of Backtest"

    def test_winner_then_loser_cut_after_turn(self):
        """Position profitable early but turns into a loss → gets cut by time stop."""
        # Entry bar 1 at 100.  Rises to 110 for 3 bars, then drops to 90 and holds.
        # After the drop it's a loser → time stop should fire.
        prices = [100.0, 100.0, 110.0, 110.0, 110.0] + [90.0] * 25
        portfolio_data, signals = _make_data(prices)
        result = _run(portfolio_data, signals, {"time_stop_days": 10, "time_stop_losers_only": True})
        assert _exit_reason(result) == "Time Stop"

    def test_time_stop_exit_reason_label(self):
        """ExitReason must be exactly 'Time Stop'."""
        prices = [100.0, 100.0, 80.0] + [80.0] * 22
        portfolio_data, signals = _make_data(prices)
        result = _run(portfolio_data, signals, {"time_stop_days": 5})
        assert _exit_reason(result) == "Time Stop"


# ------------------------------------------------------------------
# TestSymmetricTimeStop
# ------------------------------------------------------------------

class TestSymmetricTimeStop:
    """time_stop_losers_only=False: cuts ALL positions after N days."""

    def test_winner_cut_when_losers_only_false(self):
        """A profitable position is cut after N days when losers_only=False."""
        prices = [100.0, 100.0, 120.0] + [120.0] * 27
        portfolio_data, signals = _make_data(prices)
        result = _run(portfolio_data, signals, {"time_stop_days": 10, "time_stop_losers_only": False})
        assert _exit_reason(result) == "Time Stop"

    def test_loser_also_cut(self):
        """A losing position is also cut (same behaviour as asymmetric)."""
        prices = [100.0, 100.0, 80.0] + [80.0] * 27
        portfolio_data, signals = _make_data(prices)
        result = _run(portfolio_data, signals, {"time_stop_days": 10, "time_stop_losers_only": False})
        assert _exit_reason(result) == "Time Stop"


# ------------------------------------------------------------------
# TestTimeStopPriority
# ------------------------------------------------------------------

class TestTimeStopPriority:
    """Time stop fires AFTER stop-loss but BEFORE strategy signal."""

    def test_strategy_exit_still_fires_before_time_stop(self):
        """If the strategy sends -1 before N days, strategy exit wins."""
        prices = [100.0, 100.0, 80.0, 80.0, 80.0, 80.0]
        portfolio_data, signals = _make_data(prices)
        # Override: add a strategy exit signal on bar 3
        sym_df = portfolio_data["SYM"]
        sig = pd.Series(0, index=sym_df.index)
        sig.iloc[1] = 1   # entry
        sig.iloc[3] = -1  # strategy exit before 100-day time stop
        signals = {"SYM": sig}
        result = _run(portfolio_data, signals, {"time_stop_days": 100})
        assert _exit_reason(result) == "Strategy Exit"
        assert _hold_days(result) < 100
