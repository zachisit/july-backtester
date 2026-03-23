# custom_strategies/mean_reversion.py
"""Mean reversion, channel breakout, volume, and market-regime strategy plugins.

Covers the remaining configurations from the legacy _STATIC_STRATEGIES dict:

  Bollinger Band family
    - Bollinger Band Fade (20d/2.0 and 20d/2.5)
    - Bollinger Band Breakout (20d)
    - Bollinger Band Squeeze (20d/40d)
    - Bollinger Band Fade w/ SPY Trend Filter (20d/2.0)
    - 1m BB Squeeze (10/20) and (20/50)  — sub-daily variants

  Oscillator / momentum
    - Stochastic Oscillator (14d)
    - Chaikin Money Flow (10d and 20d)

  Volume / flow
    - OBV Trend (20d MA)

  Moving Average confluence and trend
    - MA Bounce (20d)
    - SMA 200 Trend Filter (200d)
    - MA Confluence (Full Stack, Fast Entry & Exit, Fast MA Exit, Fast Entry, Medium MA Exit)
    - MA Confluence (Full Stack) w/ Regime Filter

  Channel / volatility breakout
    - Donchian Channel Breakout (20d/10d)
    - Keltner Channel Breakout (20d)
    - ATR Trailing Stop (14/3)
    - ATR Trailing Stop w/ Trend Filter (20d entry / 14d ATR / 200d SMA)

  Calendar / overnight hold
    - Hold The Week (Tue–Fri)
    - Weekend Hold (Fri–Mon)
    - Daily Overnight Hold (weekdays only) w/ VIX Filter

All strategies are registered automatically when this module is imported
via ``load_strategies("custom_strategies")``.  No edits to any core file
are required to add, remove, or rename them.
"""

from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import (
    volume_weighted_rsi_logic,
    bollinger_band_logic,
    bollinger_breakout_logic,
    bollinger_band_squeeze_logic,
    bollinger_fade_with_regime_filter_logic,
    stochastic_logic,
    chaikin_money_flow_logic,
    obv_logic,
    ma_bounce_logic,
    sma_trend_filter_logic,
    ma_confluence_logic,
    ma_confluence_with_regime_filter_logic,
    donchian_channel_breakout_logic,
    keltner_channel_breakout_logic,
    atr_trailing_stop_logic,
    atr_trailing_stop_with_trend_filter_logic,
    hold_the_week_logic,
    weekend_hold_logic,
    weekday_overnight_with_vix_filter_logic,
)
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ===========================================================================
# BOLLINGER BAND FAMILY
# ===========================================================================

@register_strategy(
    name="Bollinger Band Fade (20d/2.0)",
    dependencies=[],
    params={
        "length":  get_bars_for_period("20d", _TF, _MUL),
        "std_dev": 2.0,
    },
)
def bb_fade_20_2(df, **kwargs):
    """Bollinger Band fade: buy below lower band, exit above middle SMA.

    Standard 20-bar / 2.0 std-dev configuration.  Best in mean-reverting,
    range-bound markets; loses money in strong trending environments.
    """
    return bollinger_band_logic(df, length=kwargs["length"], std_dev=kwargs["std_dev"])


@register_strategy(
    name="Bollinger Band Fade (20d/2.5)",
    dependencies=[],
    params={
        "length":  get_bars_for_period("20d", _TF, _MUL),
        "std_dev": 2.5,
    },
)
def bb_fade_20_2_5(df, **kwargs):
    """Bollinger Band fade with wider 2.5 std-dev bands.

    Wider bands mean fewer but potentially more extreme oversold entries
    compared to the 2.0 variant.
    """
    return bollinger_band_logic(df, length=kwargs["length"], std_dev=kwargs["std_dev"])


@register_strategy(
    name="Bollinger Band Breakout (20d)",
    dependencies=[],
    params={
        "length":  get_bars_for_period("20d", _TF, _MUL),
        "std_dev": 2,
    },
)
def bb_breakout_20(df, **kwargs):
    """Bollinger Band momentum breakout: buy above upper band, exit below SMA.

    The opposite of the fade — trades in the direction of the breakout.
    Suited to trending markets.
    """
    return bollinger_breakout_logic(df, length=kwargs["length"], std_dev=kwargs["std_dev"])


@register_strategy(
    name="Bollinger Band Squeeze (20d/40d)",
    dependencies=[],
    params={
        "length":         get_bars_for_period("20d", _TF, _MUL),
        "std_dev":        2.0,
        "squeeze_length": get_bars_for_period("40d", _TF, _MUL),
    },
)
def bb_squeeze_20_40(df, **kwargs):
    """Bollinger Band squeeze breakout: enters after a low-volatility compression period.

    Waits for the 20-bar bandwidth to reach its 40-bar minimum (the "squeeze"),
    then buys the first close above the upper band.  Designed to catch explosive
    post-consolidation moves.
    """
    return bollinger_band_squeeze_logic(
        df,
        length=kwargs["length"],
        std_dev=kwargs["std_dev"],
        squeeze_length=kwargs["squeeze_length"],
    )


@register_strategy(
    name="Bollinger Band Fade w/ SPY Trend Filter (20d/2.0)",
    dependencies=["spy"],
    params={
        "length":  get_bars_for_period("20d", _TF, _MUL),
        "std_dev": 2.0,
    },
)
def bb_fade_spy_filter(df, **kwargs):
    """Bollinger Band fade, buy signals gated by SPY being above its 200-bar SMA.

    Applies the standard BB fade logic but only enters when the broad market
    is in a long-term uptrend.  Exits are unfiltered.
    ``spy_df`` is injected automatically by the engine (declared in dependencies).
    """
    return bollinger_fade_with_regime_filter_logic(
        df,
        spy_df=kwargs["spy_df"],
        length=kwargs["length"],
        std_dev=kwargs["std_dev"],
    )


# Sub-daily Bollinger Band Squeeze variants  (only registered when timeframe is MIN)
if _TF == "MIN":
    @register_strategy(
        name="1m BB Squeeze (10/2.0) / 20-period squeeze",
        dependencies=[],
        params={
            "length":         get_bars_for_period("10min", _TF, _MUL),
            "std_dev":        2.0,
            "squeeze_length": get_bars_for_period("20min", _TF, _MUL),
        },
    )
    def bb_squeeze_1m_10_20(df, **kwargs):
        """Sub-daily BB squeeze breakout with a 10-bar window and 20-bar squeeze lookback.

        Designed for minute-level bars (``timeframe = "MIN"`` in config).
        """
        return bollinger_band_squeeze_logic(
            df,
            length=kwargs["length"],
            std_dev=kwargs["std_dev"],
            squeeze_length=kwargs["squeeze_length"],
        )

    @register_strategy(
        name="1m BB Squeeze (20/2.0) / 50-period squeeze",
        dependencies=[],
        params={
            "length":         get_bars_for_period("20min", _TF, _MUL),
            "std_dev":        2.0,
            "squeeze_length": get_bars_for_period("50min", _TF, _MUL),
        },
    )
    def bb_squeeze_1m_20_50(df, **kwargs):
        """Sub-daily BB squeeze breakout with a 20-bar window and 50-bar squeeze lookback.

        Designed for minute-level bars (``timeframe = "MIN"`` in config).
        Longer lookback than the 10/20 variant — fewer but potentially more
        significant squeeze signals.
        """
        return bollinger_band_squeeze_logic(
            df,
            length=kwargs["length"],
            std_dev=kwargs["std_dev"],
            squeeze_length=kwargs["squeeze_length"],
        )


# ===========================================================================
# OSCILLATOR / MOMENTUM
# ===========================================================================

@register_strategy(
    name="Stochastic Oscillator (14d)",
    dependencies=[],
    params={
        "length":     get_bars_for_period("14d", _TF, _MUL),
        "k_smooth":   3,
        "oversold":   20,
        "exit_level": 50,
    },
)
def stochastic_14(df, **kwargs):
    """Stochastic oscillator mean reversion: buy when %K crosses above 20, exit above 50.

    Uses a 3-bar smoothing on %K.  The oversold crossover entry mirrors the
    RSI Mean Reversion logic but uses %K instead of RSI.
    """
    return stochastic_logic(
        df,
        length=kwargs["length"],
        k_smooth=kwargs["k_smooth"],
        oversold=kwargs["oversold"],
        exit_level=kwargs["exit_level"],
    )


# ===========================================================================
# CHAIKIN MONEY FLOW
# ===========================================================================

@register_strategy(
    name="Chaikin Money Flow (10d)",
    dependencies=[],
    params={
        "length":          get_bars_for_period("10d", _TF, _MUL),
        "buy_threshold":   0.00,
        "sell_threshold": -0.05,
    },
)
def cmf_10(df, **kwargs):
    """Chaikin Money Flow (10-bar): enter when CMF crosses above 0, exit below -0.05.

    Shorter lookback makes this more responsive than the 20-bar variant.
    """
    return chaikin_money_flow_logic(
        df,
        length=kwargs["length"],
        buy_threshold=kwargs["buy_threshold"],
        sell_threshold=kwargs["sell_threshold"],
    )


@register_strategy(
    name="Chaikin Money Flow (20d/0.05/0.05)",
    dependencies=[],
    params={
        "length":          get_bars_for_period("20d", _TF, _MUL),
        "buy_threshold":   0.05,
        "sell_threshold": -0.05,
    },
)
def cmf_20(df, **kwargs):
    """Chaikin Money Flow (20-bar): enter on sustained buying flow (CMF > 0.05), exit on sustained selling (CMF < -0.05).

    Symmetric thresholds and a longer lookback reduce noise relative to the 10-bar variant.
    """
    return chaikin_money_flow_logic(
        df,
        length=kwargs["length"],
        buy_threshold=kwargs["buy_threshold"],
        sell_threshold=kwargs["sell_threshold"],
    )


# ===========================================================================
# VOLUME / FLOW
# ===========================================================================

@register_strategy(
    name="OBV Trend (20d MA)",
    dependencies=[],
    params={
        "ma_length": get_bars_for_period("20d", _TF, _MUL),
    },
)
def obv_trend_20(df, **kwargs):
    """On-Balance Volume trend following: long when OBV is above its 20-bar moving average.

    Uses raw OBV crossover of its SMA as a proxy for institutional buying/selling pressure.
    Exits when OBV drops below its SMA.
    """
    return obv_logic(df, ma_length=kwargs["ma_length"])


# ===========================================================================
# MOVING AVERAGE CONFLUENCE AND TREND
# ===========================================================================

@register_strategy(
    name="MA Bounce (20d)",
    dependencies=[],
    params={
        "ma_length":   get_bars_for_period("20d", _TF, _MUL),
        "filter_bars": 2,
    },
)
def ma_bounce_20(df, **kwargs):
    """Moving average bounce: buy when price touches the 20-bar MA from above and recovers.

    ``filter_bars=2`` requires at least 2 consecutive bars below the MA to confirm
    a real test (filters out brief wicks).  Exits on 2 consecutive closes below the MA.
    """
    return ma_bounce_logic(
        df,
        ma_length=kwargs["ma_length"],
        filter_bars=kwargs["filter_bars"],
    )


@register_strategy(
    name="SMA 200 Trend Filter (200d)",
    dependencies=[],
    params={
        "ma_length": get_bars_for_period("200d", _TF, _MUL),
    },
)
def sma_200_trend(df, **kwargs):
    """Simple SMA-200 trend filter: long when Close > 200-bar SMA, flat otherwise.

    Acts as a pure trend filter rather than a crossover system — always in the
    market as long as the long-term trend is up.  Useful as a baseline to compare
    against more complex strategies.
    """
    return sma_trend_filter_logic(df, ma_length=kwargs["ma_length"])


@register_strategy(
    name="MA Confluence (Full Stack)",
    dependencies=[],
    params={
        "ma_fast":   get_bars_for_period("10d", _TF, _MUL),
        "ma_medium": get_bars_for_period("20d", _TF, _MUL),
        "ma_slow":   get_bars_for_period("50d", _TF, _MUL),
    },
)
def ma_confluence_full_stack(df, **kwargs):
    """MA Confluence: enter when Close, fast MA, and medium MA are all above the slow MA.

    Conservative entry (all three must stack bullishly) and conservative exit
    (all three must stack bearishly).  The baseline/original configuration.
    """
    return ma_confluence_logic(
        df,
        ma_fast=kwargs["ma_fast"],
        ma_medium=kwargs["ma_medium"],
        ma_slow=kwargs["ma_slow"],
    )


@register_strategy(
    name="MA Confluence (Fast Entry & Exit)",
    dependencies=[],
    params={
        "ma_fast":     get_bars_for_period("10d", _TF, _MUL),
        "ma_medium":   get_bars_for_period("20d", _TF, _MUL),
        "ma_slow":     get_bars_for_period("50d", _TF, _MUL),
        "entry_rule":  "fast_only",
        "exit_rule":   "fast_cross",
    },
)
def ma_confluence_fast_entry_exit(df, **kwargs):
    """Most aggressive MA Confluence variant: fast entry AND fast exit.

    Entry requires only Close and fast MA above slow MA (no medium MA confirmation).
    Exit fires as soon as the fast MA crosses below the slow MA.
    Produces the most trades; most sensitive to noise.
    """
    return ma_confluence_logic(
        df,
        ma_fast=kwargs["ma_fast"],
        ma_medium=kwargs["ma_medium"],
        ma_slow=kwargs["ma_slow"],
        entry_rule=kwargs["entry_rule"],
        exit_rule=kwargs["exit_rule"],
    )


@register_strategy(
    name="MA Confluence (Fast MA Exit)",
    dependencies=[],
    params={
        "ma_fast":   get_bars_for_period("10d", _TF, _MUL),
        "ma_medium": get_bars_for_period("20d", _TF, _MUL),
        "ma_slow":   get_bars_for_period("50d", _TF, _MUL),
        "exit_rule": "fast_cross",
    },
)
def ma_confluence_fast_exit(df, **kwargs):
    """MA Confluence with conservative entry and fast exit.

    Enters on the full bullish stack but exits aggressively on the fast MA cross.
    Preserves gains quickly at the cost of being whipsawed on minor pullbacks.
    """
    return ma_confluence_logic(
        df,
        ma_fast=kwargs["ma_fast"],
        ma_medium=kwargs["ma_medium"],
        ma_slow=kwargs["ma_slow"],
        exit_rule=kwargs["exit_rule"],
    )


@register_strategy(
    name="MA Confluence (Fast Entry)",
    dependencies=[],
    params={
        "ma_fast":    get_bars_for_period("10d", _TF, _MUL),
        "ma_medium":  get_bars_for_period("20d", _TF, _MUL),
        "ma_slow":    get_bars_for_period("50d", _TF, _MUL),
        "entry_rule": "fast_only",
    },
)
def ma_confluence_fast_entry(df, **kwargs):
    """MA Confluence with aggressive entry and conservative exit.

    Enters early (only fast MA + Close must be above slow MA) but exits only
    on the full bearish stack.  Captures more of the move but at a higher
    false-positive entry rate.
    """
    return ma_confluence_logic(
        df,
        ma_fast=kwargs["ma_fast"],
        ma_medium=kwargs["ma_medium"],
        ma_slow=kwargs["ma_slow"],
        entry_rule=kwargs["entry_rule"],
    )


@register_strategy(
    name="MA Confluence (Medium MA Exit)",
    dependencies=[],
    params={
        "ma_fast":   get_bars_for_period("10d", _TF, _MUL),
        "ma_medium": get_bars_for_period("20d", _TF, _MUL),
        "ma_slow":   get_bars_for_period("50d", _TF, _MUL),
        "exit_rule": "medium_cross",
    },
)
def ma_confluence_medium_exit(df, **kwargs):
    """MA Confluence with conservative entry and medium-MA-based exit.

    Exits when Close drops below the medium (20-bar) MA — tighter than the
    full bearish stack but looser than the fast cross exit.
    """
    return ma_confluence_logic(
        df,
        ma_fast=kwargs["ma_fast"],
        ma_medium=kwargs["ma_medium"],
        ma_slow=kwargs["ma_slow"],
        exit_rule=kwargs["exit_rule"],
    )


@register_strategy(
    name="MA Confluence (Full Stack) w/ Regime Filter",
    dependencies=["spy", "vix"],
    params={
        "ma_fast":   get_bars_for_period("10d", _TF, _MUL),
        "ma_medium": get_bars_for_period("20d", _TF, _MUL),
        "ma_slow":   get_bars_for_period("50d", _TF, _MUL),
    },
)
def ma_confluence_regime(df, **kwargs):
    """MA Confluence gated by the full "Bull-Quiet" regime: SPY > 200-SMA AND VIX < 30.

    Entry requires both the full bullish MA stack AND favourable macro conditions.
    Exit is triggered by the individual stock's own trend breaking — never filtered.
    ``spy_df`` and ``vix_df`` are injected automatically by the engine.
    """
    return ma_confluence_with_regime_filter_logic(
        df,
        spy_df=kwargs["spy_df"],
        vix_df=kwargs["vix_df"],
        ma_fast=kwargs["ma_fast"],
        ma_medium=kwargs["ma_medium"],
        ma_slow=kwargs["ma_slow"],
    )


# ===========================================================================
# CHANNEL / VOLATILITY BREAKOUT
# ===========================================================================

@register_strategy(
    name="Donchian Breakout (20d/10d)",
    dependencies=[],
    params={
        "entry_period": get_bars_for_period("20d", _TF, _MUL),
        "exit_period":  get_bars_for_period("10d", _TF, _MUL),
    },
)
def donchian_breakout_20_10(df, **kwargs):
    """Donchian channel breakout: buy on new 20-bar high, exit on new 10-bar low.

    Classic trend-following breakout system inspired by the Turtle Trading rules.
    The asymmetric window (entry > exit) lets winners run while cutting losers quickly.
    """
    return donchian_channel_breakout_logic(
        df,
        entry_period=kwargs["entry_period"],
        exit_period=kwargs["exit_period"],
    )


@register_strategy(
    name="Keltner Channel Breakout (20d)",
    dependencies=[],
    params={
        "ema_length":     get_bars_for_period("20d", _TF, _MUL),
        "atr_length":     get_bars_for_period("20d", _TF, _MUL),
        "atr_multiplier": 2.0,
    },
)
def keltner_breakout_20(df, **kwargs):
    """Keltner Channel breakout: buy when price closes above the upper channel.

    Uses EMA as the middle line and ATR-scaled bands.  Exit when price closes
    below the middle EMA.  Compared to Bollinger Bands, Keltner Channels use
    ATR (smoother) rather than std-dev (more reactive to spikes).
    """
    return keltner_channel_breakout_logic(
        df,
        ema_length=kwargs["ema_length"],
        atr_length=kwargs["atr_length"],
        atr_multiplier=kwargs["atr_multiplier"],
    )


@register_strategy(
    name="ATR Trailing Stop (14/3)",
    dependencies=[],
    params={
        "atr_period":     get_bars_for_period("14d", _TF, _MUL),
        "atr_multiplier": 3.0,
    },
)
def atr_trailing_stop_14_3(df, **kwargs):
    """ATR trailing stop: enter on SMA-200 breakout, exit when price closes below 3x ATR trailing stop.

    The trailing stop rises with the price and never moves down, locking in gains
    while providing a volatility-adjusted exit cushion.
    """
    return atr_trailing_stop_logic(
        df,
        atr_period=kwargs["atr_period"],
        atr_multiplier=kwargs["atr_multiplier"],
    )


@register_strategy(
    name="ATR Trailing Stop w/ Trend Filter",
    dependencies=[],
    params={
        "entry_period":   get_bars_for_period("20d", _TF, _MUL),
        "atr_period":     get_bars_for_period("14d", _TF, _MUL),
        "atr_multiplier": 3.0,
        "ma_length":      get_bars_for_period("200d", _TF, _MUL),
    },
)
def atr_trailing_stop_trend_filter(df, **kwargs):
    """ATR trailing stop with Donchian breakout entry, gated by a 200-bar SMA trend filter.

    Enters on a 20-bar high breakout only when price is above the 200-bar SMA.
    Exits when the ATR trailing stop is hit OR price closes below the SMA.
    Combines breakout entry precision with long-term trend awareness.

    Note: uses intrabar fill assumption on daily data (entry detected on current
    bar's High, filled at same bar's Close).  See indicators.py docstring for details.
    """
    return atr_trailing_stop_with_trend_filter_logic(
        df,
        entry_period=kwargs["entry_period"],
        atr_period=kwargs["atr_period"],
        atr_multiplier=kwargs["atr_multiplier"],
        ma_length=kwargs["ma_length"],
    )


# ===========================================================================
# CALENDAR / OVERNIGHT HOLD
# ===========================================================================

@register_strategy(
    name="Hold The Week (Tue-Fri)",
    dependencies=[],
    params={},
)
def hold_the_week(df, **kwargs):
    """Calendar-based: buy at Monday's close (fill Tuesday open), sell at Thursday's close (fill Friday open).

    Attempts to capture intra-week drift.  Not affected by indicator lookback
    periods — signals are determined purely by the day of the week.
    """
    return hold_the_week_logic(df)


@register_strategy(
    name="Weekend Hold (Fri-Mon)",
    dependencies=[],
    params={},
)
def weekend_hold(df, **kwargs):
    """Calendar-based: buy at Thursday's close (fill Friday open), sell at Friday's close (fill Monday open).

    Captures the weekend gap effect.  Best run on daily bars where Friday and
    Monday are adjacent rows in the DataFrame.
    """
    return weekend_hold_logic(df)


@register_strategy(
    name="Daily Overnight Hold (weekdays) w/ VIX Filter",
    dependencies=["vix"],
    params={},
)
def overnight_hold_vix(df, **kwargs):
    """Weekday overnight hold, gated by VIX below 20.

    Goes long Monday–Thursday nights only when VIX is below the threshold.
    Avoids overnight exposure during high-volatility regimes.
    ``vix_df`` is injected automatically by the engine (declared in dependencies).
    """
    return weekday_overnight_with_vix_filter_logic(df, vix_df=kwargs["vix_df"])


@register_strategy(
    name="Volume-Weighted RSI (14/30)",
    dependencies=[],
    params={
        "length": get_bars_for_period("14d", _TF, _MUL),
        "oversold": 30,
        "exit_level": 50,
    },
)
def volume_weighted_rsi(df, **kwargs):
    """Volume-Weighted RSI mean-reversion strategy.

    RSI calculated on volume-weighted returns rather than raw close-to-close
    returns. Produces a distinct signal from standard RSI — tends to fire
    earlier on institutional accumulation days where heavy volume accompanies
    price moves.

    Entry: VWRSI crosses back up above 30 (oversold bounce).
    Exit: VWRSI crosses up above 50 (return to mean).
    """
    return volume_weighted_rsi_logic(
        df,
        length=kwargs["length"],
        oversold=kwargs["oversold"],
        exit_level=kwargs["exit_level"],
    )
