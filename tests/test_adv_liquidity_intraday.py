# tests/test_adv_liquidity_intraday.py
"""
Regression tests for issue #264: the `max_pct_adv` liquidity cap (and the
volume-impact market-impact model) in helpers/portfolio_simulations.py
computed its "20-day average volume" as a rolling mean over the last 20 raw
*bars*, regardless of timeframe.

On daily bars that's correct (20 bars == 20 trading days). On intraday bars
(MIN/H) it's wrong by orders of magnitude -- a `window=20` on 5-minute bars
covers ~100 minutes, not 20 trading days -- so the liquidity cap silently
clamps position sizes on intraday backtests to whatever the last few minutes
of volume happened to be. Because bigger `initial_capital` asks for bigger
share counts, this mis-scaled cap bites harder (and non-linearly) as capital
grows, and behaves completely differently between an intraday run and a
daily run of the same strategy/config -- matching the reported symptom
("intraday capital differs from daily ... as I added more starting capital
the results changed").

The fix converts the rolling window to `get_bars_for_period("20d", timeframe,
multiplier)` bars instead of a hardcoded 20, so the window always spans ~20
trading days regardless of bar granularity.
"""

import os
import sys
from unittest.mock import patch

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.portfolio_simulations import run_portfolio_simulation


def _make_intraday_ohlcv(n_days, bars_per_day, low_volume_day, low_vol_bars,
                          high_vol=20_000, low_vol=10, price=100.0):
    """25 trading days of 5-minute-equivalent bars, flat price.

    Every bar has Volume=high_vol EXCEPT the bars in `low_vol_bars` (0-indexed
    bar offsets within `low_volume_day`, itself 1-indexed), which get
    Volume=low_vol. This simulates a brief intraday liquidity lull immediately
    before entry while the stock has been genuinely liquid for the prior
    ~24 trading days.
    """
    rows = []
    idx = []
    for day in range(1, n_days + 1):
        day_start = pd.Timestamp("2024-01-02") + pd.tseries.offsets.BDay(day - 1)
        for bar in range(bars_per_day):
            ts = day_start + pd.Timedelta(minutes=5 * bar)
            vol = low_vol if (day == low_volume_day and bar in low_vol_bars) else high_vol
            idx.append(ts)
            rows.append({"Open": price, "High": price, "Low": price, "Close": price, "Volume": vol})
    df = pd.DataFrame(rows, index=pd.DatetimeIndex(idx))
    df.index.name = "Datetime"
    return df


def _run_intraday_sim(max_pct_adv, entry_day=25, entry_bar=30, bars_per_day=78, n_days=25):
    """Enter a single long at a specific intraday bar and hold to end of backtest."""
    low_vol_bars = set(range(10, 40))  # bars 10-39 of the entry day are illiquid
    df = _make_intraday_ohlcv(n_days, bars_per_day, low_volume_day=entry_day, low_vol_bars=low_vol_bars)

    entry_idx = (entry_day - 1) * bars_per_day + entry_bar
    entry_ts = df.index[entry_idx]

    signal = pd.Series(0, index=df.index)
    signal.loc[entry_ts] = 1  # enter here; never exit -> closed via end-of-backtest MTM

    test_config = {
        "timeframe": "MIN",
        "timeframe_multiplier": 5,
        "execution_time": "close",
        "slippage_pct": 0.0,
        "commission_per_share": 0.0,
        "max_pct_adv": max_pct_adv,
        "volume_impact_coeff": 0.0,
        "risk_free_rate": 0.05,
        "htb_rate_annual": 0.0,
        "position_sizing_method": "fixed",
    }

    with patch.dict("config.CONFIG", test_config):
        result = run_portfolio_simulation(
            portfolio_data={"TEST": df},
            signals={"TEST": signal},
            initial_capital=100_000.0,
            allocation_pct=0.10,
            spy_df=None,
            vix_df=None,
            tnx_df=None,
            stop_config={"type": "none"},
        )
    return result, entry_ts


class TestAdvLiquidityCapIntraday:

    def test_cap_disabled_gets_full_allocation(self):
        """Sanity check: with max_pct_adv=0 (disabled), the desired 10% allocation
        (100_000 * 0.10 / 100.0 = 100 shares) is filled in full."""
        result, _ = _run_intraday_sim(max_pct_adv=0.0)
        assert result is not None
        trade = result["trade_log"][0]
        assert trade["Shares"] == pytest.approx(100.0, rel=1e-6)

    def test_cap_uses_20_trading_day_window_not_20_bars(self):
        """The stock has been highly liquid for ~24 trading days; only the last
        30-ish 5-minute bars (a few minutes) before entry are illiquid. A correct
        20-*trading-day* ADV window is dominated by the liquid history and should
        NOT clamp the position down anywhere near the degenerate ~0.5-share cap
        that a literal 20-*bar* window would produce (adv_20=10 * 0.05 = 0.5).
        """
        result, _ = _run_intraday_sim(max_pct_adv=0.05)
        assert result is not None
        trade = result["trade_log"][0]
        # Full allocation (100 shares) should be unaffected by the transient
        # end-of-window volume lull once the window spans real trading days.
        assert trade["Shares"] == pytest.approx(100.0, rel=1e-6), (
            f"ADV cap over-clamped an intraday order despite ~24 days of ample "
            f"liquidity: got {trade['Shares']} shares (bug clamps to ~0.5)"
        )

    def test_cap_still_binds_when_truly_illiquid_for_full_window(self):
        """Control case: if the ENTIRE 20-trading-day window is illiquid (not
        just a few end-of-window bars), the cap must still correctly bind --
        this isn't a test that disables the liquidity filter, only that its
        window is sized correctly.
        """
        bars_per_day = 78
        n_days = 25
        # Day 1 is left liquid (irrelevant -- outside the trailing 20-day
        # window at entry); days 2-25 (24 trading days, comfortably >= the
        # 20-day window) are entirely illiquid.
        df = _make_intraday_ohlcv(n_days, bars_per_day, low_volume_day=1, low_vol_bars=set())
        illiquid_start = 1 * bars_per_day
        df.iloc[illiquid_start:, df.columns.get_loc("Volume")] = 10

        entry_idx = (25 - 1) * bars_per_day + 30
        entry_ts = df.index[entry_idx]
        signal = pd.Series(0, index=df.index)
        signal.loc[entry_ts] = 1

        test_config = {
            "timeframe": "MIN", "timeframe_multiplier": 5, "execution_time": "close",
            "slippage_pct": 0.0, "commission_per_share": 0.0,
            "max_pct_adv": 0.05, "volume_impact_coeff": 0.0,
            "risk_free_rate": 0.05, "htb_rate_annual": 0.0,
            "position_sizing_method": "fixed",
        }
        with patch.dict("config.CONFIG", test_config):
            result = run_portfolio_simulation(
                portfolio_data={"TEST": df}, signals={"TEST": signal},
                initial_capital=100_000.0, allocation_pct=0.10,
                spy_df=None, vix_df=None, tnx_df=None,
                stop_config={"type": "none"},
            )
        assert result is not None
        trade = result["trade_log"][0]
        assert trade["Shares"] < 100.0, (
            "Cap should still bind when the full 20-day window is genuinely illiquid"
        )

    def test_daily_timeframe_window_unchanged(self):
        """Daily timeframe: 20 bars == 20 trading days already -- the fix must
        be a no-op here (golden-master / byte-for-byte protection)."""
        n = 40
        dates = pd.bdate_range("2024-01-02", periods=n, freq="B")
        df = pd.DataFrame({
            "Open": [100.0] * n, "High": [100.0] * n, "Low": [100.0] * n, "Close": [100.0] * n,
            "Volume": [10] * 20 + [20_000] * 20,  # illiquid first 20 days, liquid last 20
        }, index=dates)
        df.index.name = "Datetime"

        entry_ts = dates[25]  # inside the liquid stretch; only last 20 bars matter for D
        signal = pd.Series(0, index=df.index)
        signal.loc[entry_ts] = 1

        test_config = {
            "timeframe": "D", "timeframe_multiplier": 1, "execution_time": "close",
            "slippage_pct": 0.0, "commission_per_share": 0.0,
            "max_pct_adv": 0.05, "volume_impact_coeff": 0.0,
            "risk_free_rate": 0.05, "htb_rate_annual": 0.0,
            "position_sizing_method": "fixed",
        }
        with patch.dict("config.CONFIG", test_config):
            result = run_portfolio_simulation(
                portfolio_data={"TEST": df}, signals={"TEST": signal},
                initial_capital=100_000.0, allocation_pct=0.10,
                spy_df=None, vix_df=None, tnx_df=None,
                stop_config={"type": "none"},
            )
        assert result is not None
        trade = result["trade_log"][0]
        # adv_20 at entry (last 20 daily bars, all liquid) = 20_000 -> cap = 1000 shares,
        # well above the 100-share target allocation -> uncapped.
        assert trade["Shares"] == pytest.approx(100.0, rel=1e-6)
