# custom_strategies/round35_strategies.py
"""
Round 35 Research Strategies — Mean Reversion Weekly (Counter-Trend Test)

ALL prior champions are trend-following: they buy when price is strong and rising.
This round tests the OPPOSITE hypothesis: buy on weakness in an uptrend.

Mean reversion on weekly bars:
- Daily mean reversion is proven to be noisy (too many false oversold readings)
- On weekly bars, RSI < 30 requires sustained multi-week selling pressure
  → Only fires during genuine corrections, not single bad days
- The SMA(40w) filter ensures we only buy pullbacks WITHIN an uptrend, not crashes

Two counter-trend signals:

  1. RSI Mean Reversion Weekly (RSI < 30 bounce in uptrend)
     Entry: RSI(14w) crosses above 30 (recovering from oversold) AND price > SMA(40w)
     Exit:  RSI > 60 (recovered to bullish territory) OR price < SMA(40w)
     This is the complement of RSI Weekly Trend (55-cross): buys BEFORE it enters,
     catching the "spring" phase of a correction within an uptrend.

  2. Bollinger Band Mean Reversion Weekly (close < lower BB in uptrend)
     Entry: Close < Lower BB (-2-std, 20w) AND price > SMA(40w)
     Exit:  Close > Middle BB (SMA 20w) OR price < SMA(40w)
     Note: "Close < Lower BB AND price > SMA(40w)" seems contradictory but is possible:
     SMA(40w) measures the 10-month uptrend; BB(20w) measures 5-month deviation.
     A 10%+ pullback in a multi-year uptrend can push close below the 5-month BB band
     while still above the 10-month trend line.

Key research question: Are mean reversion returns UNCORRELATED with momentum returns?
If RS(min) and exit-day correlation of these strategies is low vs existing champions,
they could be the portfolio's only true diversifiers.
"""

import numpy as np
import pandas as pd
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import calculate_sma, calculate_rsi
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ===========================================================================
# STRATEGY 1 — RSI Mean Reversion Weekly (RSI < 30 bounce) + SMA200 Gate
# Counter-trend: buy oversold pullbacks in established uptrends
# ===========================================================================

@register_strategy(
    name="RSI MeanRev Weekly (30-bounce) + SMA200",
    dependencies=[],
    params={
        "rsi_period":   14,                                        # 14-week RSI
        "rsi_entry":    30.0,                                      # oversold level
        "rsi_exit":     60.0,                                      # recovered to bullish
        "sma_slow":     get_bars_for_period("200d", _TF, _MUL),   # 40w uptrend gate
    },
)
def rsi_meanrev_weekly_sma200(df, **kwargs):
    """RSI mean reversion on weekly bars — buy oversold pullbacks in uptrends.

    On daily bars, RSI < 30 fires frequently (50+ times/year in trending stocks),
    generating too many whipsaws. On weekly bars, RSI(14w) < 30 requires
    consistent selling for 3-6 consecutive weeks — a genuine correction.

    The SMA(40w) gate ensures entries only during confirmed long-term uptrends.
    A stock can pull back to RSI(30) weekly while remaining above its 40-week
    moving average: this represents the "spring-loading" phase before the next
    leg higher.

    Signal logic:
    - Entry: RSI(14w) crosses above 30 (recovering from oversold) AND Close > SMA(40w)
    - Exit:  RSI(14w) > 60 (fully recovered to bullish momentum) OR Close < SMA(40w)

    Expected behavior: fewer trades than trend strategies, but potentially higher
    win rate and lower correlation with trend-following champions.
    """
    rsi_period = kwargs["rsi_period"]
    rsi_entry  = kwargs["rsi_entry"]
    rsi_exit   = kwargs["rsi_exit"]
    sma_slow   = kwargs["sma_slow"]

    # Compute RSI
    df = calculate_rsi(df, rsi_period)
    rsi_col = f"RSI_{rsi_period}"

    # SMA uptrend gate
    df = calculate_sma(df, sma_slow)
    sma_col = f"SMA_{sma_slow}"
    is_uptrend = df["Close"] > df[sma_col]

    # RSI oversold bounce crossover
    rsi_above_entry = df[rsi_col] > rsi_entry
    rsi_cross_up    = rsi_above_entry & ~rsi_above_entry.shift(1).fillna(False)

    is_entry = rsi_cross_up & is_uptrend
    is_exit  = (df[rsi_col] > rsi_exit) | ~is_uptrend

    # Stateful signal construction
    signals = []
    in_position = False

    for i in range(len(df)):
        rsi_val = df[rsi_col].iloc[i]
        sma_val = df[sma_col].iloc[i]

        if pd.isna(rsi_val) or pd.isna(sma_val):
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
    df.drop(columns=[rsi_col, sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 2 — Bollinger Band Mean Reversion Weekly (close < lower BB) + SMA200
# Counter-trend: buy at statistical lower extreme in established uptrends
# ===========================================================================

@register_strategy(
    name="BB MeanRev Weekly (lower-band) + SMA200",
    dependencies=[],
    params={
        "bb_length":  get_bars_for_period("100d", _TF, _MUL),  # 20w Bollinger Band
        "bb_std":     2.0,
        "sma_slow":   get_bars_for_period("200d", _TF, _MUL),  # 40w uptrend gate
    },
)
def bb_meanrev_weekly_sma200(df, **kwargs):
    """Bollinger Band mean reversion on weekly bars with SMA200 uptrend filter.

    Complements the BB Weekly Breakout strategy (Round 34) by capturing the
    OPPOSITE scenario: when price falls to the statistical lower extreme
    (-2 standard deviations below the 20-week mean) in an uptrend, it
    represents an unusually deep pullback likely to revert toward the mean.

    Key design: the SMA(40w) uptrend gate is CRITICAL here. Without it,
    this would fire on stocks in genuine downtrends — the gate ensures we
    only buy statistical extremes in stocks with intact long-term uptrends.

    Signal logic:
    - Lower Band = SMA(20w) - 2 × StdDev(20w)
    - Middle Band = SMA(20w)
    - Entry: Close < Lower Band AND Close > SMA(40w) (extreme pullback in uptrend)
    - Exit:  Close > Middle Band (reverted to mean) OR Close < SMA(40w)
    """
    bb_length = kwargs["bb_length"]
    bb_std    = kwargs["bb_std"]
    sma_slow  = kwargs["sma_slow"]

    # Bollinger Bands
    sma_bb     = df["Close"].rolling(bb_length).mean()
    std_bb     = df["Close"].rolling(bb_length).std()
    lower_band = sma_bb - bb_std * std_bb

    # SMA uptrend gate
    df = calculate_sma(df, sma_slow)
    sma_col   = f"SMA_{sma_slow}"
    is_uptrend = df["Close"] > df[sma_col]

    # Entry: below lower band AND in uptrend
    below_lower = df["Close"] < lower_band
    above_mid   = df["Close"] > sma_bb

    entry_condition = below_lower & is_uptrend
    exit_condition  = above_mid | ~is_uptrend

    # Stateful signal construction
    signals = []
    in_position = False

    for i in range(len(df)):
        if pd.isna(sma_bb.iloc[i]) or pd.isna(df[sma_col].iloc[i]):
            signals.append(-1)
            continue

        if not in_position:
            if entry_condition.iloc[i]:
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
