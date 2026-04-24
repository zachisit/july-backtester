# custom_strategies/round34_strategies.py
"""
Round 34 Research Strategies — Unexplored Oscillator Families on Weekly Bars

All previous champions (MA Bounce, MAC, Donchian, Price Momentum, RSI) have been
momentum/trend-following strategies. This round explores three untested signal families:

  1. Bollinger Band Weekly Breakout (volatility expansion momentum)
     Entry: Close > Upper BB (2-std, 20w) AND price > SMA(40w)
     Hypothesis: Breaking the 2-std upper band on weekly bars = genuine institutional breakout

  2. Stochastic Weekly Momentum (overbought continuation)
     Entry: %K(14w) crosses above 80 AND price > SMA(40w)
     NOTE: This is the INVERSE of the classic stochastic (oversold bounce).
     On weekly bars, %K > 80 = strong sustained buying, not an overextension to fade.
     Hypothesis: The same "weekly timeframe improvement" (165-215% Sharpe on daily→weekly)
     applies to oscillator-based signals.

  3. Williams %R Weekly Trend (overbought momentum continuation)
     Entry: Williams%R(14w) crosses above -20 AND price > SMA(40w)
     Same insight as Stochastic: on weekly bars, near high of 14-week range = strong trend.

  4. Volume-Weighted RSI Weekly Trend (>55 with volume confirmation)
     Entry: VWRSI(14w) crosses above 55 AND price > SMA(40w)
     VWRSI weights RSI by relative volume — fires earlier on institutional accumulation.
     Different from standard RSI Weekly (rank 3 champion) because volume-weighting
     can detect institutional buying before price fully breaks out.
"""

import numpy as np
import pandas as pd
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import calculate_sma, calculate_williams_r, calculate_volume_weighted_rsi
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ===========================================================================
# STRATEGY 1 — Bollinger Band Weekly Breakout + SMA200
# Entry: Close > Upper BB(20w, 2-std) AND price > SMA(40w)
# ===========================================================================

@register_strategy(
    name="BB Weekly Breakout (20w/2std) + SMA200",
    dependencies=[],
    params={
        "bb_length":  get_bars_for_period("100d", _TF, _MUL),  # 20w lookback
        "bb_std":     2.0,
        "sma_slow":   get_bars_for_period("200d", _TF, _MUL),  # 40w uptrend gate
    },
)
def bb_weekly_breakout_sma200(df, **kwargs):
    """Bollinger Band breakout on weekly bars with SMA200 uptrend gate.

    On daily bars, BB breakouts are noisy — price breaks the upper band
    frequently in volatile markets. On weekly bars, each bar represents
    5 days of price action; breaking the 2-std upper band requires a
    sustained multi-week move, not a single volatile session.

    Signal logic:
    - Upper Band = SMA(20w) + 2 × StdDev(20w)
    - Middle Band = SMA(20w)
    - Uptrend gate = price > SMA(40w) = SMA(200d)
    - Entry: Close > Upper Band (breakout) AND Close > SMA(40w)
    - Exit:  Close < Middle Band (momentum fading) OR Close < SMA(40w)
    """
    bb_length = kwargs["bb_length"]
    bb_std    = kwargs["bb_std"]
    sma_slow  = kwargs["sma_slow"]

    # Bollinger Band calculation
    sma_bb    = df["Close"].rolling(bb_length).mean()
    std_bb    = df["Close"].rolling(bb_length).std()
    upper_band = sma_bb + bb_std * std_bb

    # SMA uptrend gate
    df = calculate_sma(df, sma_slow)
    sma_col   = f"SMA_{sma_slow}"
    is_uptrend = df["Close"] > df[sma_col]

    # Crossover signals
    above_upper  = df["Close"] > upper_band
    above_middle = df["Close"] > sma_bb

    breakout_entry = above_upper & is_uptrend
    exit_condition = ~above_middle | ~is_uptrend

    # Stateful signal construction
    signals = []
    in_position = False

    for i in range(len(df)):
        if pd.isna(sma_bb.iloc[i]) or pd.isna(df[sma_col].iloc[i]):
            signals.append(-1)
            continue

        if not in_position:
            if breakout_entry.iloc[i]:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if exit_condition.iloc[i]:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 2 — Stochastic Weekly Momentum (K > 80 breakout) + SMA200
# Entry: %K(14w) crosses above 80 AND price > SMA(40w)
# ===========================================================================

@register_strategy(
    name="Stochastic Weekly Trend (K80) + SMA200",
    dependencies=[],
    params={
        "stoch_length": get_bars_for_period("70d", _TF, _MUL),   # 14w lookback
        "k_smooth":     3,                                          # smooth %K
        "entry_level":  80.0,                                       # overbought breakout
        "exit_level":   20.0,                                       # momentum collapses
        "sma_slow":     get_bars_for_period("200d", _TF, _MUL),   # 40w uptrend gate
    },
)
def stochastic_weekly_trend_sma200(df, **kwargs):
    """Stochastic momentum continuation on weekly bars.

    Classical stochastic logic buys oversold conditions (mean reversion).
    This strategy INVERTS the logic: %K > 80 on weekly bars = overbought
    momentum breakout = trend continuation signal.

    Why this works differently on weekly bars:
    - Daily %K > 80: very common in any rally, noise-heavy (50+ triggers/year)
    - Weekly %K > 80: rare event requiring 14 consecutive weeks near highs,
      indicates sustained institutional accumulation over 3-4 months

    Signal logic:
    - %K = 100 × (Close - Lowest Low(14w)) / (Highest High(14w) - Lowest Low(14w))
    - Entry: smoothed %K crosses above 80 AND price > SMA(40w)
    - Exit:  smoothed %K drops below 20 (momentum collapsed) OR price < SMA(40w)
    """
    stoch_length = kwargs["stoch_length"]
    k_smooth     = kwargs["k_smooth"]
    entry_level  = kwargs["entry_level"]
    exit_level   = kwargs["exit_level"]
    sma_slow     = kwargs["sma_slow"]

    # Stochastic %K calculation
    lowest_low   = df["Low"].rolling(stoch_length).min()
    highest_high = df["High"].rolling(stoch_length).max()
    raw_k        = 100 * (df["Close"] - lowest_low) / (highest_high - lowest_low).replace(0, np.nan)
    pct_k        = raw_k.rolling(k_smooth).mean()  # smoothed %K

    # SMA uptrend gate
    df = calculate_sma(df, sma_slow)
    sma_col   = f"SMA_{sma_slow}"
    is_uptrend = df["Close"] > df[sma_col]

    # Crossover detection
    above_entry = pct_k > entry_level
    k_cross_up   = above_entry & ~above_entry.shift(1).fillna(False)
    k_below_exit = pct_k < exit_level

    is_entry = k_cross_up & is_uptrend
    is_exit  = k_below_exit | ~is_uptrend

    # Stateful signal construction
    signals = []
    in_position = False

    for i in range(len(df)):
        k_val   = pct_k.iloc[i]
        sma_val = df[sma_col].iloc[i]

        if pd.isna(k_val) or pd.isna(sma_val):
            signals.append(-1)
            continue

        if not in_position:
            if is_entry.iloc[i]:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if is_exit.iloc[i]:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 3 — Williams %R Weekly Trend (>-20 breakout) + SMA200
# Entry: %R(14w) crosses above -20 AND price > SMA(40w)
# ===========================================================================

@register_strategy(
    name="Williams R Weekly Trend (above-20) + SMA200",
    dependencies=[],
    params={
        "wr_length":  get_bars_for_period("70d", _TF, _MUL),   # 14w lookback
        "entry_level": -20.0,                                    # near 14w high
        "exit_level":  -80.0,                                    # near 14w low
        "sma_slow":   get_bars_for_period("200d", _TF, _MUL),   # 40w uptrend gate
    },
)
def williams_r_weekly_trend_sma200(df, **kwargs):
    """Williams %R trend continuation on weekly bars.

    Williams %R ranges from 0 (at 14w high, overbought) to -100 (at 14w low, oversold).
    Classical mean-reversion logic: buy when %R oversold (< -80), sell when it reverts.
    This strategy INVERTS: crossing above -20 = close near the 14-week high = momentum.

    Key insight: on weekly bars, Williams %R > -20 means the closing price is within
    the top 20% of the 14-week range. For this to occur over multiple weeks requires
    genuine sustained trend, not a one-day spike.

    Signal logic:
    - %R = (Highest High(14w) - Close) / (Highest High(14w) - Lowest Low(14w)) × -100
    - Entry: %R crosses above -20 (near 14w high) AND price > SMA(40w)
    - Exit:  %R drops below -80 (near 14w low, trend broken) OR price < SMA(40w)
    """
    wr_length    = kwargs["wr_length"]
    entry_level  = kwargs["entry_level"]
    exit_level   = kwargs["exit_level"]
    sma_slow     = kwargs["sma_slow"]

    # Williams %R calculation
    df = calculate_williams_r(df, wr_length)
    wr_col = f"WilliamsR_{wr_length}"

    # SMA uptrend gate
    df = calculate_sma(df, sma_slow)
    sma_col   = f"SMA_{sma_slow}"
    is_uptrend = df["Close"] > df[sma_col]

    # Crossover detection
    above_entry  = df[wr_col] > entry_level
    wr_cross_up  = above_entry & ~above_entry.shift(1).fillna(False)
    wr_below_exit = df[wr_col] < exit_level

    is_entry = wr_cross_up & is_uptrend
    is_exit  = wr_below_exit | ~is_uptrend

    # Stateful signal construction
    signals = []
    in_position = False

    for i in range(len(df)):
        wr_val  = df[wr_col].iloc[i]
        sma_val = df[sma_col].iloc[i]

        if pd.isna(wr_val) or pd.isna(sma_val):
            signals.append(-1)
            continue

        if not in_position:
            if is_entry.iloc[i]:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if is_exit.iloc[i]:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[wr_col, sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 3b — Williams R Weekly Trend + SMA100 gate (faster re-entry variant)
# Created in EC-R52 (2026-04-23) to target EC R3 requirement (<365d recovery)
# ===========================================================================

@register_strategy(
    name="Williams R Weekly Trend (above-20) + SMA100",
    dependencies=[],
    params={
        "wr_length":   get_bars_for_period("70d", _TF, _MUL),   # 14w lookback
        "entry_level": -20.0,
        "exit_level":  -80.0,
        "sma_slow":    get_bars_for_period("100d", _TF, _MUL),  # 20w gate (faster)
    },
)
def williams_r_weekly_trend_sma100(df, **kwargs):
    """Same Williams %R weekly trend logic as Strategy 3, but with SMA100 (20-week)
    uptrend gate instead of SMA200 (40-week). Re-enters bull regimes 3-8 weeks
    earlier after bear markets, compressing equity-curve recovery duration."""
    wr_length    = kwargs["wr_length"]
    entry_level  = kwargs["entry_level"]
    exit_level   = kwargs["exit_level"]
    sma_slow     = kwargs["sma_slow"]

    df = calculate_williams_r(df, wr_length)
    wr_col = f"WilliamsR_{wr_length}"

    df = calculate_sma(df, sma_slow)
    sma_col   = f"SMA_{sma_slow}"
    is_uptrend = df["Close"] > df[sma_col]

    above_entry  = df[wr_col] > entry_level
    wr_cross_up  = above_entry & ~above_entry.shift(1).fillna(False)
    wr_below_exit = df[wr_col] < exit_level

    is_entry = wr_cross_up & is_uptrend
    is_exit  = wr_below_exit | ~is_uptrend

    signals = []
    in_position = False
    for i in range(len(df)):
        wr_val  = df[wr_col].iloc[i]
        sma_val = df[sma_col].iloc[i]
        if pd.isna(wr_val) or pd.isna(sma_val):
            signals.append(-1)
            continue
        if not in_position:
            if is_entry.iloc[i]:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if is_exit.iloc[i]:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[wr_col, sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 4 — Volume-Weighted RSI (VWRSI) Weekly Trend (>55) + SMA200
# Entry: VWRSI(14w) crosses above 55 AND price > SMA(40w)
# ===========================================================================

@register_strategy(
    name="VWRSI Weekly Trend (55-cross) + SMA200",
    dependencies=[],
    params={
        "vwrsi_period": 14,                                        # 14-week period
        "entry_level":  55.0,                                      # momentum threshold
        "exit_level":   45.0,                                      # momentum faded
        "sma_slow":     get_bars_for_period("200d", _TF, _MUL),   # 40w uptrend gate
    },
)
def vwrsi_weekly_trend_sma200(df, **kwargs):
    """Volume-Weighted RSI trend continuation on weekly bars.

    VWRSI is identical to RSI except it weights each bar's return by relative
    volume (volume / avg_volume_14w). On an institutional accumulation week, where
    price rises 3% on 2× average volume, the signal fires earlier than standard RSI.

    Hypothesis: VWRSI should perform similar to or better than RSI Weekly (rank 3
    champion, Sharpe 1.85) because:
    1. Volume confirmation reduces false signals from low-volume price moves
    2. High-volume weeks carry more weight → earlier trend detection
    3. Same entry/exit thresholds as RSI Weekly for direct comparison

    Signal logic:
    - VWRSI: RSI calculation on volume-weighted close-to-close returns
    - Entry: VWRSI(14w) crosses above 55 AND price > SMA(40w)
    - Exit:  VWRSI(14w) drops below 45 OR price < SMA(40w)
    """
    vwrsi_period = kwargs["vwrsi_period"]
    entry_level  = kwargs["entry_level"]
    exit_level   = kwargs["exit_level"]
    sma_slow     = kwargs["sma_slow"]

    # Compute VWRSI
    df = calculate_volume_weighted_rsi(df, vwrsi_period)
    vwrsi_col = f"VWRSI_{vwrsi_period}"

    # SMA uptrend gate
    df = calculate_sma(df, sma_slow)
    sma_col   = f"SMA_{sma_slow}"
    is_uptrend = df["Close"] > df[sma_col]

    # Crossover detection
    above_entry  = df[vwrsi_col] > entry_level
    vwrsi_cross_up = above_entry & ~above_entry.shift(1).fillna(False)

    is_entry = vwrsi_cross_up & is_uptrend
    is_exit  = (df[vwrsi_col] < exit_level) | ~is_uptrend

    # Stateful signal construction
    signals = []
    in_position = False

    for i in range(len(df)):
        vwrsi_val = df[vwrsi_col].iloc[i]
        sma_val   = df[sma_col].iloc[i]

        if pd.isna(vwrsi_val) or pd.isna(sma_val):
            signals.append(-1)
            continue

        if not in_position:
            if is_entry.iloc[i]:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if is_exit.iloc[i]:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[vwrsi_col, sma_col], errors="ignore", inplace=True)
    return df
