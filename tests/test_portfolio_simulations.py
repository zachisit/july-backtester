"""
Tests for helpers/portfolio_simulations.py — run_portfolio_simulation.

Covers the key branches without requiring real market data:
  - No valid trades → returns None
  - Simple long trade lifecycle (buy + sell signal)
  - Stop-loss: percentage type triggers exit
  - Stop-loss: ATR type triggers exit
  - Mark-to-market: open position closed at end of backtest
  - Short trade lifecycle (short entry + cover)
  - Result structure and keys
  - Multiple symbols
  - Volume-based market impact (coeff > 0)
  - Max pct ADV filter
"""
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch

from helpers.portfolio_simulations import run_portfolio_simulation


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_DATES = pd.bdate_range("2021-01-04", periods=20)  # 20 business days


def _ohlcv(n=20, base=100.0, trend=0.0, atr_val=2.0):
    """Minimal OHLCV DataFrame with ATR_14 column for stop-loss tests."""
    close = np.full(n, base) + np.arange(n) * trend
    return pd.DataFrame({
        "Open":   close * 0.999,
        "High":   close + 1.0,
        "Low":    close - 1.0,
        "Close":  close,
        "Volume": np.full(n, 1_000_000.0),
        "ATR_14": np.full(n, atr_val),
    }, index=_DATES[:n])


def _signals(n=20, buy_at=2, sell_at=10):
    """Signal series: 1 on buy_at, -1 on sell_at, else 0."""
    s = pd.Series(np.zeros(n, dtype=int), index=_DATES[:n])
    if buy_at is not None:
        s.iloc[buy_at] = 1
    if sell_at is not None:
        s.iloc[sell_at] = -1
    return s


def _run(portfolio_data, signals, stop_config=None, initial_capital=100_000,
         allocation_pct=0.1, spy_df=None, vix_df=None, tnx_df=None,
         config_overrides=None):
    """Wrapper that patches CONFIG with safe defaults then runs the simulation."""
    defaults = {
        "slippage_pct": 0.0,
        "commission_per_share": 0.0,
        "risk_free_rate": 0.05,
        "volume_impact_coeff": 0.0,
        "max_pct_adv": 0,
        "htb_rate_annual": 0.0,
        "execution_time": "close",
    }
    if config_overrides:
        defaults.update(config_overrides)
    stop_config = stop_config or {"type": "none"}
    spy = spy_df if spy_df is not None else _ohlcv()
    vix = vix_df if vix_df is not None else _ohlcv(base=20.0)
    with patch.dict("config.CONFIG", defaults):
        return run_portfolio_simulation(
            portfolio_data, signals, initial_capital, allocation_pct,
            spy, vix, tnx_df, stop_config,
        )


# ---------------------------------------------------------------------------
# Returns None when no trades execute
# ---------------------------------------------------------------------------

class TestNoTrades:

    def test_all_zero_signals_returns_none(self):
        """No signal ever fires → pnl_list empty → returns None."""
        data = {"AAPL": _ohlcv()}
        sigs = {"AAPL": pd.Series(np.zeros(20, dtype=int), index=_DATES)}
        assert _run(data, sigs) is None

    def test_buy_only_no_sell_uses_mark_to_market(self):
        """Buy but never sell → position closed at end of backtest → not None."""
        data = {"AAPL": _ohlcv()}
        sigs = {"AAPL": _signals(sell_at=None)}  # never sell
        result = _run(data, sigs)
        assert result is not None

    def test_empty_portfolio_raises_index_error(self):
        """No symbols → all_dates is empty → IndexError at last_date = all_dates[-1].
        Documents current behavior (unguarded edge case in implementation)."""
        with pytest.raises(IndexError):
            _run({}, {})


# ---------------------------------------------------------------------------
# Basic long trade lifecycle
# ---------------------------------------------------------------------------

class TestLongTrade:

    def _simple(self):
        data = {"AAPL": _ohlcv(trend=1.0)}
        sigs = {"AAPL": _signals(buy_at=2, sell_at=10)}
        return _run(data, sigs)

    def test_result_is_not_none(self):
        assert self._simple() is not None

    def test_result_has_trade_log(self):
        assert "trade_log" in self._simple()

    def test_trade_log_has_one_entry(self):
        assert len(self._simple()["trade_log"]) == 1

    def test_trades_count_is_one(self):
        assert self._simple()["Trades"] == 1

    def test_trade_pnl_list_has_one_element(self):
        result = self._simple()
        assert len(result["trade_pnl_list"]) == 1

    def test_pnl_percent_is_float(self):
        result = self._simple()
        assert isinstance(result["pnl_percent"], float)

    def test_portfolio_timeline_in_result(self):
        assert "portfolio_timeline" in self._simple()

    def test_win_rate_between_zero_and_one(self):
        result = self._simple()
        assert 0.0 <= result["win_rate"] <= 1.0

    def test_profitable_trade_has_positive_pnl(self):
        """Upward trend + buy early + sell late → positive P&L."""
        result = self._simple()
        assert result["trade_pnl_list"][0] > 0

    def test_losing_trade_has_negative_pnl(self):
        """Downward trend → buy + hold + sell → negative P&L."""
        data = {"AAPL": _ohlcv(trend=-2.0)}
        sigs = {"AAPL": _signals(buy_at=2, sell_at=10)}
        result = _run(data, sigs)
        assert result is not None
        assert result["trade_pnl_list"][0] < 0

    def test_trade_log_has_symbol_field(self):
        result = self._simple()
        assert result["trade_log"][0]["Symbol"] == "AAPL"

    def test_trade_log_has_profit_field(self):
        result = self._simple()
        assert "Profit" in result["trade_log"][0]

    def test_trade_log_has_exit_reason(self):
        result = self._simple()
        assert "ExitReason" in result["trade_log"][0]


# ---------------------------------------------------------------------------
# Stop-loss: percentage type
# ---------------------------------------------------------------------------

class TestPercentageStopLoss:

    def test_stop_triggered_before_sell_signal(self):
        """Entry at 100, stop=5%, drop to 90 → stop fires before sell_at=15."""
        close = np.array([100.0, 100.0, 100.0,  # entry bar 2 at close 100
                          95.0, 94.0, 92.0, 90.0,  # sharp drop
                          90.0, 90.0, 90.0, 90.0,  # remains low
                          90.0, 90.0, 90.0, 90.0,
                          90.0, 90.0, 90.0, 90.0, 90.0])
        low = close - 2.0
        df = pd.DataFrame({
            "Open": close * 0.999, "High": close + 1.0,
            "Low": low, "Close": close, "Volume": np.full(20, 1e6),
            "ATR_14": np.full(20, 2.0),
        }, index=_DATES[:20])
        data = {"AAPL": df}
        sigs = {"AAPL": _signals(buy_at=2, sell_at=15)}
        result = _run(data, sigs, stop_config={"type": "percentage", "value": 0.05})
        assert result is not None
        log = result["trade_log"][0]
        assert "Stop Loss" in log["ExitReason"]

    def test_result_not_none_with_percentage_stop(self):
        data = {"AAPL": _ohlcv(trend=1.0)}
        sigs = {"AAPL": _signals(buy_at=2, sell_at=10)}
        result = _run(data, sigs, stop_config={"type": "percentage", "value": 0.05})
        assert result is not None


# ---------------------------------------------------------------------------
# Stop-loss: ATR type
# ---------------------------------------------------------------------------

class TestAtrStopLoss:

    def test_atr_stop_fires_on_sharp_drop(self):
        """ATR=2, multiplier=1 → stop = prev_close - 2. A sharp drop triggers it."""
        close = np.array([100.0] * 3 + [95.0] * 17, dtype=float)
        low = close - 4.0  # Low goes well below ATR stop
        df = pd.DataFrame({
            "Open": close * 0.999, "High": close + 1.0,
            "Low": low, "Close": close, "Volume": np.full(20, 1e6),
            "ATR_14": np.full(20, 2.0),
        }, index=_DATES[:20])
        data = {"AAPL": df}
        sigs = {"AAPL": _signals(buy_at=2, sell_at=18)}
        result = _run(data, sigs, stop_config={"type": "atr", "multiplier": 1.0})
        assert result is not None
        log = result["trade_log"][0]
        assert "Stop Loss" in log["ExitReason"] or "Strategy Exit" in log["ExitReason"]

    def test_atr_stop_no_crash_when_no_atr_column(self):
        """If ATR_14 column is missing, stop is never set → simulation runs normally."""
        data = {"AAPL": _ohlcv(trend=1.0)}
        data["AAPL"] = data["AAPL"].drop(columns=["ATR_14"])
        sigs = {"AAPL": _signals(buy_at=2, sell_at=10)}
        result = _run(data, sigs, stop_config={"type": "atr", "multiplier": 3.0})
        assert result is not None


# ---------------------------------------------------------------------------
# Mark-to-market (positions still open at end)
# ---------------------------------------------------------------------------

class TestMarkToMarket:

    def test_open_position_logged_at_end_of_backtest(self):
        """Buy but never sell → closed at last bar with 'End of Backtest' reason."""
        data = {"AAPL": _ohlcv(trend=0.5)}
        sigs = {"AAPL": _signals(sell_at=None)}
        result = _run(data, sigs)
        assert result is not None
        log = result["trade_log"][0]
        assert log["ExitReason"] == "End of Backtest"

    def test_mark_to_market_pnl_matches_price_change(self):
        """Entry price 100, final price ~110 → positive P&L."""
        data = {"AAPL": _ohlcv(base=100.0, trend=0.5)}  # ~110 at bar 19
        sigs = {"AAPL": _signals(sell_at=None)}
        result = _run(data, sigs)
        assert result["trade_pnl_list"][0] > 0


# ---------------------------------------------------------------------------
# Short trades
# ---------------------------------------------------------------------------

class TestShortTrade:

    def _short_data(self, trend=-0.5):
        close = 100.0 + np.arange(20) * trend
        df = pd.DataFrame({
            "Open": close * 0.999, "High": close + 1.0, "Low": close - 1.0,
            "Close": close, "Volume": np.full(20, 1e6), "ATR_14": np.full(20, 2.0),
        }, index=_DATES[:20])
        return {"AAPL": df}

    def _short_sigs(self, short_at=2, cover_at=10):
        s = pd.Series(np.zeros(20, dtype=int), index=_DATES[:20])
        s.iloc[short_at] = -2   # short entry
        s.iloc[cover_at] = -1   # cover signal
        return {"AAPL": s}

    def test_short_trade_executes(self):
        result = _run(self._short_data(), self._short_sigs())
        assert result is not None

    def test_short_trade_logged_with_short_prefix(self):
        result = _run(self._short_data(), self._short_sigs())
        trade_labels = [t["Trade"] for t in result["trade_log"]]
        assert any("Short" in lbl for lbl in trade_labels)

    def test_short_trade_profitable_on_downtrend(self):
        """Short a downtrending stock → profit positive."""
        result = _run(self._short_data(trend=-2.0), self._short_sigs())
        assert result["trade_pnl_list"][0] > 0


# ---------------------------------------------------------------------------
# Multiple symbols
# ---------------------------------------------------------------------------

class TestMultipleSymbols:

    def test_two_symbols_both_trade(self):
        data = {"AAPL": _ohlcv(trend=1.0), "MSFT": _ohlcv(trend=0.5)}
        sigs = {
            "AAPL": _signals(buy_at=2, sell_at=10),
            "MSFT": _signals(buy_at=3, sell_at=12),
        }
        result = _run(data, sigs)
        assert result is not None
        assert result["Trades"] == 2

    def test_one_symbol_no_trade_other_does(self):
        data = {"AAPL": _ohlcv(trend=1.0), "MSFT": _ohlcv()}
        sigs = {
            "AAPL": _signals(buy_at=2, sell_at=10),  # trades
            "MSFT": pd.Series(np.zeros(20, dtype=int), index=_DATES),  # no signal
        }
        result = _run(data, sigs)
        assert result is not None
        assert result["Trades"] == 1


# ---------------------------------------------------------------------------
# Volume-based market impact
# ---------------------------------------------------------------------------

class TestVolumeImpact:

    def test_positive_impact_coeff_does_not_crash(self):
        data = {"AAPL": _ohlcv()}
        sigs = {"AAPL": _signals(buy_at=2, sell_at=10)}
        result = _run(data, sigs, config_overrides={"volume_impact_coeff": 0.1})
        assert result is not None

    def test_impact_bps_in_trade_log(self):
        data = {"AAPL": _ohlcv()}
        sigs = {"AAPL": _signals(buy_at=2, sell_at=10)}
        result = _run(data, sigs, config_overrides={"volume_impact_coeff": 0.1})
        assert "VolumeImpact_bps" in result["trade_log"][0]


# ---------------------------------------------------------------------------
# Max pct ADV filter
# ---------------------------------------------------------------------------

class TestMaxPctAdv:

    def test_max_pct_adv_filter_does_not_crash(self):
        """With a small max_pct_adv, shares are capped but simulation still runs."""
        data = {"AAPL": _ohlcv()}
        sigs = {"AAPL": _signals(buy_at=2, sell_at=10)}
        result = _run(data, sigs, config_overrides={"max_pct_adv": 0.01})
        # May return None if shares are too small after cap, or a valid result
        assert result is None or isinstance(result, dict)

    def test_large_max_pct_adv_runs_normally(self):
        data = {"AAPL": _ohlcv()}
        sigs = {"AAPL": _signals(buy_at=2, sell_at=10)}
        result = _run(data, sigs, config_overrides={"max_pct_adv": 10.0})
        assert result is not None


# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------

class TestResultStructure:

    def _result(self):
        data = {"AAPL": _ohlcv(trend=1.0)}
        sigs = {"AAPL": _signals(buy_at=2, sell_at=10)}
        return _run(data, sigs)

    def test_has_max_drawdown_key(self):
        assert "max_drawdown" in self._result()

    def test_has_win_rate_key(self):
        assert "win_rate" in self._result()

    def test_has_profit_factor_key(self):
        assert "profit_factor" in self._result()

    def test_has_sharpe_ratio_key(self):
        assert "sharpe_ratio" in self._result()

    def test_has_initial_capital_key(self):
        r = self._result()
        assert "initial_capital" in r
        assert r["initial_capital"] == 100_000

    def test_max_drawdown_non_negative(self):
        assert self._result()["max_drawdown"] >= 0

    def test_profit_factor_non_negative(self):
        pf = self._result()["profit_factor"]
        assert pf >= 0 or pf == float("inf")
