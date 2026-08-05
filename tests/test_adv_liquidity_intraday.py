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


class TestAdvIsDailyVolumeNotPerBarVolume:
    """Round-2 review (Shardul, PR #265): the first fix widened the rolling
    window's lookback horizon but still computed the mean of ONE BAR's
    volume, not one DAY's -- e.g. 78 bars/day at 20,000 volume/bar means a
    true daily volume of 1,560,000, but `rolling(1560).mean()` returns
    20,000 (the per-bar average), an understatement of the correct 5% ADV
    cap by a factor of 78 (1,000 shares instead of 78,000).

    This directly reproduces Shardul's repro with a target order size
    (10,000 shares) chosen specifically to fall BETWEEN the two thresholds:
    the bugged per-bar-mean cap (1,000) would clip it; the correct
    daily-volume cap (78,000) must not.
    """

    @staticmethod
    def _run(max_pct_adv, price=1.0, allocation_pct=0.10, initial_capital=100_000.0):
        bars_per_day = 78
        n_days = 25
        df = _make_intraday_ohlcv(n_days, bars_per_day, low_volume_day=1, low_vol_bars=set(), price=price)
        # Constant volume everywhere -- no lull, isolates the pure magnitude bug.
        entry_idx = (n_days - 1) * bars_per_day + 30
        entry_ts = df.index[entry_idx]
        signal = pd.Series(0, index=df.index)
        signal.loc[entry_ts] = 1

        test_config = {
            "timeframe": "MIN", "timeframe_multiplier": 5, "execution_time": "close",
            "slippage_pct": 0.0, "commission_per_share": 0.0,
            "max_pct_adv": max_pct_adv, "volume_impact_coeff": 0.0,
            "risk_free_rate": 0.05, "htb_rate_annual": 0.0,
            "position_sizing_method": "fixed",
        }
        with patch.dict("config.CONFIG", test_config):
            result = run_portfolio_simulation(
                portfolio_data={"TEST": df}, signals={"TEST": signal},
                initial_capital=initial_capital, allocation_pct=allocation_pct,
                spy_df=None, vix_df=None, tnx_df=None,
                stop_config={"type": "none"},
            )
        return result

    def test_cap_reflects_true_daily_volume_not_per_bar_mean(self):
        """20,000 shares/bar * 78 bars/day = 1,560,000 true daily volume.
        5% cap = 78,000 shares. Target order = 10,000 shares
        (100_000 * 0.10 / price=$1.00), which sits well below the correct
        cap but well above the bugged per-bar-mean cap of 1,000 -- so this
        assertion only passes once ADV is measured per DAY, not per bar.
        """
        result = self._run(max_pct_adv=0.05)
        assert result is not None
        trade = result["trade_log"][0]
        assert trade["Shares"] == pytest.approx(10_000.0, rel=1e-6), (
            f"Expected the full 10,000-share allocation (well under the correct "
            f"78,000-share daily-ADV cap); got {trade['Shares']} -- looks like ADV "
            f"is still being measured as per-bar volume, not per-day volume "
            f"(bugged cap would be ~1,000 shares)"
        )

    def test_cap_binds_at_the_correct_daily_threshold(self):
        """Push the desired order (via more capital) past the correct 78,000-share
        daily cap and confirm it clips there -- not at the bugged 1,000 mark."""
        # 100% allocation of $10,000,000 at $1/share = 10,000,000 desired shares,
        # far past the true daily cap of 78,000.
        result = self._run(max_pct_adv=0.05, allocation_pct=1.0, initial_capital=10_000_000.0)
        assert result is not None
        trade = result["trade_log"][0]
        assert trade["Shares"] == pytest.approx(78_000.0, rel=1e-6)


class TestVolumeImpactExitPathUsesCorrectedAdv:
    """Round-2 review (Shardul, PR #265): the normal multi-bar EXIT path
    (helpers/portfolio_simulations.py, the '--- VOLUME-BASED MARKET IMPACT
    (exit) ---' block) had its own separate rolling(window=20) computation
    that the first fix missed entirely -- entry used one (wrong) ADV
    definition, exit used a different, still-unfixed one. Both must now go
    through the same `_daily_adv` helper.
    """

    @staticmethod
    def _run(volume_impact_coeff):
        bars_per_day = 78
        n_days = 25
        df = _make_intraday_ohlcv(n_days, bars_per_day, low_volume_day=1, low_vol_bars=set(),
                                   high_vol=20_000, price=1.0)

        entry_idx = (n_days - 1) * bars_per_day + 10
        exit_idx = (n_days - 1) * bars_per_day + 40
        entry_ts, exit_ts = df.index[entry_idx], df.index[exit_idx]

        signal = pd.Series(0, index=df.index)
        signal.loc[entry_ts] = 1
        signal.loc[exit_ts] = -1

        test_config = {
            "timeframe": "MIN", "timeframe_multiplier": 5, "execution_time": "close",
            "slippage_pct": 0.0, "commission_per_share": 0.0,
            "max_pct_adv": 0.0, "volume_impact_coeff": volume_impact_coeff,
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
        return result

    def test_exit_impact_uses_daily_not_per_bar_adv(self):
        """shares=10,000, true daily ADV = 20,000/bar * 78 bars/day = 1,560,000.
        order_pct_of_adv = 10,000/1,560,000 = 0.64103% -> impact (one side) =
        0.1*sqrt(0.0064103) = 0.80064% = 80.06 bps; combined entry+exit ~= 160 bps.

        The bugged per-bar-mean ADV (constant volume -> mean is just 20,000
        regardless of window) instead computes order_pct_of_adv =
        10,000/20,000 = 50% -> impact (one side) = 0.1*sqrt(0.5) = 7.07% =
        707 bps; combined entry+exit ~= 1414 bps -- ~9x larger. The two
        regimes are far enough apart that a coarse bound cleanly separates them.
        """
        result = self._run(volume_impact_coeff=0.1)
        assert result is not None
        exits = [t for t in result["trade_log"] if t["ExitReason"] != "End of Backtest"]
        assert exits, "Expected a normal (non end-of-backtest) exit"
        trade = exits[0]
        assert "VolumeImpact_bps" in trade
        assert trade["VolumeImpact_bps"] == pytest.approx(160.1, abs=2.0), (
            f"Expected ~160 bps (true daily ADV); got {trade['VolumeImpact_bps']} "
            f"-- ~1414 bps would indicate the exit path is still using the bugged "
            f"per-bar-mean ADV"
        )

    def test_zero_coeff_exit_impact_is_zero(self):
        result = self._run(volume_impact_coeff=0.0)
        assert result is not None
        exits = [t for t in result["trade_log"] if t["ExitReason"] != "End of Backtest"]
        assert exits
        assert exits[0].get("VolumeImpact_bps", 0) == 0
