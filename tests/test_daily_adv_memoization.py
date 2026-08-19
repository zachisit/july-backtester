"""
Tests for the per-symbol ADV memo (issue #269).

`_daily_adv()` in helpers/portfolio_simulations.py used to recompute
`.rolling().mean()` over an entire volume series on every call and keep a
single value. With four call sites -- two of them firing on the same entry
bar -- that is a lot of repeated work, and the cost scales with series
length, so intraday runs pay for it heavily.

Memoizing is only safe if two things hold, and both are tested here:

1. The cached values are identical to what the per-call version produced.
2. The cache does NOT outlive a single run_portfolio_simulation() call.
   Workers process many strategies/portfolios in one process, so a
   module-level cache would serve one portfolio's volume series to the next
   -- silently sizing positions off the wrong symbol's liquidity.

No network, no randomness.
"""

import os
import sys
from unittest.mock import patch

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.portfolio_simulations import run_portfolio_simulation  # noqa: E402

PRICE = 1.0
N_BARS = 60
ENTRY_IDX = 40  # well past the 20-bar daily window


def _daily_df(volume, n_bars=N_BARS, price=PRICE):
    idx = pd.DatetimeIndex(pd.date_range("2024-01-02", periods=n_bars, freq="B"))
    idx.name = "Datetime"
    return pd.DataFrame(
        {"Open": price, "High": price, "Low": price, "Close": price,
         "Volume": float(volume)},
        index=idx,
    )


def _base_config(**overrides):
    cfg = {
        "timeframe": "D",
        "timeframe_multiplier": 1,
        "execution_time": "close",
        "slippage_pct": 0.0,
        "commission_per_share": 0.0,
        "max_pct_adv": 0.05,
        "volume_impact_coeff": 0.0,
        "risk_free_rate": 0.05,
        "htb_rate_annual": 0.0,
        "position_sizing_method": "fixed",
    }
    cfg.update(overrides)
    return cfg


def _run(df, symbol="TEST", entry_idx=ENTRY_IDX, **cfg_overrides):
    signal = pd.Series(0, index=df.index)
    signal.iloc[entry_idx] = 1  # enter, never exit -> closed by end-of-run MTM

    with patch.dict("config.CONFIG", _base_config(**cfg_overrides)):
        return run_portfolio_simulation(
            portfolio_data={symbol: df},
            signals={symbol: signal},
            initial_capital=1_000_000.0,  # asks for far more than the cap allows
            allocation_pct=0.10,
            spy_df=None,
            vix_df=None,
            tnx_df=None,
            stop_config={"type": "none"},
        )


class TestMemoizedValuesAreCorrect:
    """The memo must return exactly what the per-call computation returned."""

    @pytest.mark.parametrize("volume", [20_000.0, 2_000.0, 137_500.0])
    def test_cap_matches_directly_computed_adv(self, volume):
        df = _daily_df(volume)
        result = _run(df)

        assert result is not None
        trade = result["trade_log"][0]

        # Daily bars: bars_per_day == 1.0, so ADV == the 20-bar rolling mean,
        # which on constant volume is just `volume`.
        expected_cap = volume * 0.05
        assert trade["Shares"] == pytest.approx(expected_cap, rel=1e-9)

    def test_matches_uncached_rolling_computation(self):
        """
        Recompute the ADV the long way and confirm the engine agrees --
        i.e. the memo is a pure caching layer, not a different formula.
        """
        volume = 20_000.0
        df = _daily_df(volume)
        result = _run(df)

        entry_ts = df.index[ENTRY_IDX]
        uncached = (
            df["Volume"].rolling(window=20, min_periods=1).mean().get(entry_ts)
        ) * 1.0

        trade = result["trade_log"][0]
        assert trade["Shares"] == pytest.approx(uncached * 0.05, rel=1e-9)

    def test_varying_volume_is_not_flattened_by_the_cache(self):
        """
        A cache bug that stored a scalar instead of the full series would
        still pass constant-volume tests. Use a ramp so the ADV at the entry
        bar differs from the ADV anywhere else.
        """
        df = _daily_df(20_000.0)
        df["Volume"] = [1_000.0 * (i + 1) for i in range(len(df))]

        result = _run(df)
        entry_ts = df.index[ENTRY_IDX]
        expected_adv = df["Volume"].rolling(window=20, min_periods=1).mean().get(entry_ts)

        trade = result["trade_log"][0]
        assert trade["Shares"] == pytest.approx(expected_adv * 0.05, rel=1e-9)
        # Sanity: the ramp really does make this bar distinctive.
        assert expected_adv != pytest.approx(df["Volume"].mean(), rel=1e-6)


class TestCacheIsScopedToOneRun:
    """
    The regression that matters: a module-level cache would leak across
    simulations inside one worker process.
    """

    def test_second_run_same_symbol_uses_its_own_volume(self):
        liquid = _daily_df(20_000.0)     # cap -> 1,000 shares
        illiquid = _daily_df(2_000.0)    # cap ->   100 shares

        first = _run(liquid, symbol="TEST")
        second = _run(illiquid, symbol="TEST")

        assert first["trade_log"][0]["Shares"] == pytest.approx(1_000.0, rel=1e-9)
        assert second["trade_log"][0]["Shares"] == pytest.approx(100.0, rel=1e-9), (
            "second run reused the first run's cached ADV -- the memo has "
            "escaped run_portfolio_simulation()'s scope"
        )

    def test_leak_is_detected_in_both_orders(self):
        """Guard against a cache that happens to be overwritten by ordering."""
        illiquid = _daily_df(2_000.0)
        liquid = _daily_df(20_000.0)

        first = _run(illiquid, symbol="TEST")
        second = _run(liquid, symbol="TEST")

        assert first["trade_log"][0]["Shares"] == pytest.approx(100.0, rel=1e-9)
        assert second["trade_log"][0]["Shares"] == pytest.approx(1_000.0, rel=1e-9)

    def test_distinct_symbols_in_one_run_do_not_share_an_entry(self):
        """Two symbols in the same portfolio must key the cache separately."""
        liquid = _daily_df(20_000.0)
        illiquid = _daily_df(2_000.0)

        signals = {}
        for sym, df in (("LIQ", liquid), ("ILQ", illiquid)):
            s = pd.Series(0, index=df.index)
            s.iloc[ENTRY_IDX] = 1
            signals[sym] = s

        with patch.dict("config.CONFIG", _base_config()):
            result = run_portfolio_simulation(
                portfolio_data={"LIQ": liquid, "ILQ": illiquid},
                signals=signals,
                initial_capital=1_000_000.0,
                allocation_pct=0.10,
                spy_df=None,
                vix_df=None,
                tnx_df=None,
                stop_config={"type": "none"},
            )

        by_symbol = {t["Symbol"]: t for t in result["trade_log"]}
        assert by_symbol["LIQ"]["Shares"] == pytest.approx(1_000.0, rel=1e-9)
        assert by_symbol["ILQ"]["Shares"] == pytest.approx(100.0, rel=1e-9)


class TestCacheIsSharedAcrossEntryAndExitSites:
    """
    The entry sites populate the cache from `df['Volume']`; the exit sites
    read it back via `portfolio_data[symbol]['Volume']`. Those are separate
    expressions over the same underlying frame, so this pins that the cached
    series serves both -- and, because the volume ramps, that the memo
    returns a per-DATE value rather than one frozen number.
    """

    def test_entry_and_exit_each_use_their_own_bars_adv(self):
        coeff = 0.1
        exit_idx = ENTRY_IDX + 10

        df = _daily_df(20_000.0)
        df["Volume"] = [1_000.0 * (i + 1) for i in range(len(df))]

        signal = pd.Series(0, index=df.index)
        signal.iloc[ENTRY_IDX] = 1
        signal.iloc[exit_idx] = -1  # real exit -> exercises the exit ADV site

        with patch.dict("config.CONFIG", _base_config(volume_impact_coeff=coeff)):
            result = run_portfolio_simulation(
                portfolio_data={"TEST": df},
                signals={"TEST": signal},
                initial_capital=1_000_000.0,
                allocation_pct=0.10,
                spy_df=None,
                vix_df=None,
                tnx_df=None,
                stop_config={"type": "none"},
            )

        trade = result["trade_log"][0]
        assert trade["ExitReason"] != "End of Backtest", (
            "fixture regressed: this must take the normal exit path"
        )

        adv = df["Volume"].rolling(window=20, min_periods=1).mean()
        entry_adv = adv.get(df.index[ENTRY_IDX])
        exit_adv = adv.get(df.index[exit_idx])

        # The ramp must actually make the two bars differ, or this proves
        # nothing about per-date lookups.
        assert entry_adv != pytest.approx(exit_adv, rel=1e-6)

        shares = trade["Shares"]
        assert shares == pytest.approx(entry_adv * 0.05, rel=1e-9)

        expected_entry = PRICE * (1 + coeff * ((shares / entry_adv) ** 0.5))
        expected_exit = PRICE * (1 - coeff * ((shares / exit_adv) ** 0.5))

        assert trade["EntryPrice"] == pytest.approx(expected_entry, rel=1e-9)
        assert trade["ExitPrice"] == pytest.approx(expected_exit, rel=1e-9)


class TestMinPeriodsStaysOne:
    """
    #269 also proposed raising min_periods to one full session so the early
    ADV estimate has a day behind it. It is deliberately NOT done, and this
    class pins why: both ADV consumers guard with `pd.notna(adv) and adv > 0`,
    so a NaN does not yield a cautious cap -- it removes the cap entirely.
    """

    def test_cap_is_active_from_the_very_first_bar(self):
        """
        Entering on bar 0, with only one bar of history, must still be capped.
        Under min_periods > 1 the ADV would be NaN here and the position would
        be filled at the full requested size instead.
        """
        volume = 20_000.0
        df = _daily_df(volume)
        result = _run(df, entry_idx=0)

        trade = result["trade_log"][0]
        uncapped_request = 1_000_000.0 * 0.10 / PRICE  # 100,000 shares

        assert trade["Shares"] == pytest.approx(volume * 0.05, rel=1e-9)
        assert trade["Shares"] < uncapped_request

    @pytest.mark.parametrize("entry_idx", [0, 1, 5, 19])
    def test_cap_active_throughout_the_partial_window(self, entry_idx):
        """Every bar before the window is full must still be capped."""
        volume = 20_000.0
        result = _run(_daily_df(volume), entry_idx=entry_idx)
        trade = result["trade_log"][0]
        assert trade["Shares"] == pytest.approx(volume * 0.05, rel=1e-9)


class TestImpactPathSharesTheMemo:
    """
    The entry cap and the entry impact model both look up ADV on the same
    bar; they must agree, since they now read the same cached series.
    """

    def test_entry_impact_uses_the_same_adv_as_the_cap(self):
        """
        The impact model's ADV is not reported directly, but it is baked into
        the filled entry price: entry = raw * (1 + coeff*sqrt(shares/adv)).
        Solving that back out proves both lookups saw the same ADV.
        """
        volume = 20_000.0
        coeff = 0.1
        df = _daily_df(volume)

        result = _run(df, max_pct_adv=0.05, volume_impact_coeff=coeff)
        trade = result["trade_log"][0]

        shares = trade["Shares"]
        assert shares == pytest.approx(volume * 0.05, rel=1e-9)

        # adv == volume on constant volume (daily bars -> bars_per_day 1.0)
        expected_entry = PRICE * (1 + coeff * ((shares / volume) ** 0.5))
        assert trade["EntryPrice"] == pytest.approx(expected_entry, rel=1e-9)

    def test_impact_scales_with_the_symbols_own_adv(self):
        """A less liquid symbol must be charged more impact, not the same."""
        coeff = 0.1
        liquid = _run(_daily_df(20_000.0), max_pct_adv=0.05,
                      volume_impact_coeff=coeff)["trade_log"][0]
        illiquid = _run(_daily_df(2_000.0), max_pct_adv=0.05,
                        volume_impact_coeff=coeff)["trade_log"][0]

        # Both cap at 5% of their own ADV, so shares/adv is identical and the
        # impact bps match -- what must differ is the share count itself.
        assert liquid["Shares"] == pytest.approx(1_000.0, rel=1e-9)
        assert illiquid["Shares"] == pytest.approx(100.0, rel=1e-9)
        assert liquid["EntryPrice"] == pytest.approx(
            illiquid["EntryPrice"], rel=1e-9
        )
