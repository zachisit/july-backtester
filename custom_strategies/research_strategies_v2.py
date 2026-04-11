# custom_strategies/research_strategies_v2.py
"""
Round 2 Research Strategies — multi-agent design based on Round 1 results.

9 strategies across 3 families, designed to fix Round 1 weaknesses:
  - Momentum: SMA200 filter, RSI confirmation gate, EMA+ROC dual-signal
  - Breakout: Longer Donchian window, tighter Keltner multiplier, Bollinger breakout
  - Mean Reversion: Trend-filtered RSI, relaxed VW RSI, OBV volume-flow

Target ecosystem: tech_giants.json (AAPL, MSFT, GOOG, AMZN, NVDA, META)
"""

import numpy as np
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import (
    roc_logic,
    rsi_logic,
    rsi_with_trend_filter_logic,
    volume_weighted_rsi_logic,
    ema_crossover_unfiltered_logic,
    calculate_sma,
    donchian_channel_breakout_logic,
    keltner_channel_breakout_logic,
    bollinger_breakout_logic,
    obv_price_confirmation_logic,
)
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ===========================================================================
# MOMENTUM FAMILY (3 strategies)
# ===========================================================================

@register_strategy(
    name="ROC + SMA200 Trend Filter (20d)",
    dependencies=[],
    params={
        "length":    get_bars_for_period("20d", _TF, _MUL),
        "threshold": 0,
        "ma_length": get_bars_for_period("200d", _TF, _MUL),
    },
)
def roc_sma200_filter_20d(df, **kwargs):
    """ROC Momentum gated by the 200-bar SMA trend filter.

    Round 1 problem: ROC Momentum (20d) had negative Sharpe on single symbols.
    Fix: Only hold longs when price is above its 200-bar SMA (uptrend confirmed).
    Exits are unconditional — never held through confirmed downtrends.
    Expected: fewer whipsaws, lower MaxDD, improved Sharpe vs raw ROC.
    """
    df = roc_logic(df, length=kwargs["length"], threshold=kwargs["threshold"])
    roc_signal = df["Signal"].copy()

    df = calculate_sma(df, length=kwargs["ma_length"])
    sma_col = f'SMA_{kwargs["ma_length"]}'
    is_uptrend = df["Close"] > df[sma_col]

    df["Signal"] = np.where(roc_signal == 1, np.where(is_uptrend, 1, -1), -1)
    return df


@register_strategy(
    name="ROC + RSI Confirmation (20d/14d)",
    dependencies=[],
    params={
        "roc_length":    get_bars_for_period("20d", _TF, _MUL),
        "roc_threshold": 0,
        "rsi_length":    get_bars_for_period("14d", _TF, _MUL),
        "oversold":      40,
        "exit_level":    65,
    },
)
def roc_rsi_confirmation_20d(df, **kwargs):
    """RSI mean-reversion entries gated by a positive 20-bar ROC.

    Round 1 problem: RSI alone had low Calmar; ROC alone had low win rate.
    Fix: RSI drives timing (buy at oversold bounce), ROC filters direction
    (only enter when momentum is also positive). Exits follow RSI exit_level.
    Expected: higher conviction entries, win rate ~55-65%, fewer total trades.
    """
    df = roc_logic(df, length=kwargs["roc_length"], threshold=kwargs["roc_threshold"])
    roc_signal = df["Signal"].copy()

    df = rsi_logic(
        df,
        length=kwargs["rsi_length"],
        oversold=kwargs["oversold"],
        exit_level=kwargs["exit_level"],
    )
    rsi_signal = df["Signal"].copy()

    # Gate RSI long entries on positive ROC; exits always fire unconditionally
    df["Signal"] = np.where(
        rsi_signal == 1,
        np.where(roc_signal == 1, 1, -1),
        rsi_signal,
    )
    return df


@register_strategy(
    name="EMA Crossover + ROC Gate (12/26/20d)",
    dependencies=[],
    params={
        "fast_ema":      get_bars_for_period("12d", _TF, _MUL),
        "slow_ema":      get_bars_for_period("26d", _TF, _MUL),
        "roc_length":    get_bars_for_period("20d", _TF, _MUL),
        "roc_threshold": 0,
    },
)
def ema_crossover_roc_gate_12_26(df, **kwargs):
    """EMA crossover (12/26) with 20-bar ROC as momentum confirmation gate.

    Round 1 problem: Raw ROC had 43% win rate; too many contra-trend entries.
    Fix: EMA crossover provides structural trend signal (fewer, cleaner events);
    ROC gate filters entries that occur during consolidation/drift.
    Expected: 50-80 trades over 22 years per symbol, win rate ~58-65%, positive Sharpe.
    """
    df = ema_crossover_unfiltered_logic(
        df, fast_ema=kwargs["fast_ema"], slow_ema=kwargs["slow_ema"]
    )
    ema_signal = df["Signal"].copy()

    df = roc_logic(df, length=kwargs["roc_length"], threshold=kwargs["roc_threshold"])
    roc_signal = df["Signal"].copy()

    # EMA long positions only when ROC also positive; EMA exits unconditional
    df["Signal"] = np.where(
        ema_signal == 1,
        np.where(roc_signal == 1, 1, -1),
        -1,
    )
    return df


# ===========================================================================
# BREAKOUT FAMILY (3 strategies)
# ===========================================================================

@register_strategy(
    name="Donchian Breakout (40/20)",
    dependencies=[],
    params={
        "entry_period": get_bars_for_period("40d", _TF, _MUL),
        "exit_period":  get_bars_for_period("20d", _TF, _MUL),
    },
)
def donchian_40_20(df, **kwargs):
    """Donchian channel breakout — 40-bar entry, 20-bar exit (longer window).

    Round 1 winner: Donchian (20/10) had best Calmar (0.73) and PF (4.37).
    Hypothesis: Raising entry window to 40 bars increases conviction per trade
    (must break a longer-term high). Fewer trades but higher Expectancy(R).
    Ideal for multi-symbol portfolio where trade count is restored by breadth.
    """
    return donchian_channel_breakout_logic(
        df,
        entry_period=kwargs["entry_period"],
        exit_period=kwargs["exit_period"],
    )


@register_strategy(
    name="Keltner Breakout (20d/1.5x)",
    dependencies=[],
    params={
        "ema_length":     get_bars_for_period("20d", _TF, _MUL),
        "atr_length":     get_bars_for_period("14d", _TF, _MUL),
        "atr_multiplier": 1.5,
    },
)
def keltner_breakout_1_5x(df, **kwargs):
    """Keltner channel breakout with tighter 1.5x ATR multiplier.

    Round 1 issue: Keltner (2x) scored MC=3 (DD Understated). Narrower band
    generates more trade opportunities, improving MC sample size. The tighter
    channel means the strategy fires more often — fixes the under-trade problem.
    Expected: trade count 120-180, MC score improves, Sharpe stays positive.
    """
    return keltner_channel_breakout_logic(
        df,
        ema_length=kwargs["ema_length"],
        atr_length=kwargs["atr_length"],
        atr_multiplier=kwargs["atr_multiplier"],
    )


@register_strategy(
    name="Bollinger Breakout (20d/2.0x)",
    dependencies=[],
    params={
        "length":  get_bars_for_period("20d", _TF, _MUL),
        "std_dev": 2.0,
    },
)
def bb_breakout_20_2(df, **kwargs):
    """Bollinger Band breakout — enter on close above upper band.

    Different from the BB Squeeze (Round 1): this enters on ANY upper band
    breach, not just after a squeeze. Bollinger breakouts on tech stocks
    often signal the start of momentum runs.
    Expected: more trades than BB Squeeze (no pre-squeeze requirement),
    similar high PF characteristic.
    """
    return bollinger_breakout_logic(
        df,
        length=kwargs["length"],
        std_dev=kwargs["std_dev"],
    )


# ===========================================================================
# MEAN REVERSION FAMILY (3 strategies)
# ===========================================================================

@register_strategy(
    name="RSI + SMA200 Trend Filter (14/25/55)",
    dependencies=[],
    params={
        "rsi_length":  get_bars_for_period("14d", _TF, _MUL),
        "oversold":    25,
        "exit_level":  55,
        "ma_length":   get_bars_for_period("200d", _TF, _MUL),
    },
)
def rsi_sma200_filter_14_25_55(df, **kwargs):
    """RSI mean reversion with SMA-200 trend filter and tighter thresholds.

    Round 1 problem: Williams %R / Stochastic (identical signals) had 5070-day
    MaxRecovery — buying into bear markets was catastrophic.
    Fix: rsi_with_trend_filter_logic only enters when price > SMA200.
    Tighter oversold=25 (vs 30) reduces false signals; exit=55 captures fuller bounces.
    Expected: MaxRecovery drops dramatically; Calmar improves significantly.
    """
    return rsi_with_trend_filter_logic(
        df,
        rsi_length=kwargs["rsi_length"],
        oversold=kwargs["oversold"],
        exit_level=kwargs["exit_level"],
        ma_length=kwargs["ma_length"],
    )


@register_strategy(
    name="VW RSI Relaxed Entry (14/40/50)",
    dependencies=[],
    params={
        "length":      get_bars_for_period("14d", _TF, _MUL),
        "oversold":    40,
        "exit_level":  50,
    },
)
def vw_rsi_relaxed_40_50(df, **kwargs):
    """Volume-weighted RSI with relaxed oversold threshold to increase trade count.

    Round 1 problem: VW RSI had only 37 trades (MC Score = -999, too few).
    Fix: Raise oversold from 30 → 40. More entries qualify; trade count
    should reach 80-120, crossing the Monte Carlo minimum of 50.
    Lower exit (50 vs 55) from Round 1 for faster turnover.
    """
    return volume_weighted_rsi_logic(
        df,
        length=kwargs["length"],
        oversold=kwargs["oversold"],
        exit_level=kwargs["exit_level"],
    )


@register_strategy(
    name="OBV + Price EMA Dual Confirm (20/20)",
    dependencies=[],
    params={
        "obv_ma_length":   get_bars_for_period("20d", _TF, _MUL),
        "price_ma_length": get_bars_for_period("20d", _TF, _MUL),
    },
)
def obv_price_dual_confirm(df, **kwargs):
    """OBV trend entry with dual-confirmation exit.

    Entry: OBV crosses above its 20-bar SMA (institutional buying pressure
           turns net positive).
    Exit:  OBV crosses below SMA AND price closes below 20-bar EMA (both
           volume flow AND price must confirm weakness — reduces premature exits).

    Structural advantage: OBV-based signals are uncorrelated with Williams %R /
    Stochastic (which are pure price-oscillator signals). During bear markets,
    declining prices produce negative OBV cumulation, giving implicit trend
    filtering without an explicit SMA200 gate.
    """
    return obv_price_confirmation_logic(
        df,
        obv_ma_length=kwargs["obv_ma_length"],
        price_ma_length=kwargs["price_ma_length"],
    )
