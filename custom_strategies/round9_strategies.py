# custom_strategies/round9_strategies.py
"""
Round 9 Research Strategies — Two new signal families from Queue Item 5 list.

Round 8 findings:
  - ATR trailing stop on 44 tech stocks: MC Score -1 persists (structural)
  - SP500 universality CONFIRMED: all 3 primary champions pass WFA+RollWFA 3/3
  - SP500 combined portfolio at 3%: Bounce MC Score = 1 (first positive on 500 stocks!)
  - MA Bounce on WEEKLY BARS: P&L 140,028%, Sharpe 1.92, RS(min) -2.32 — extraordinary

Two new strategy families from the original Queue Item 5 list never yet tested:

  1. Price Momentum (6-month ROC > 15%) + SMA200
     Entry: Close > SMA200 AND ROC(126) > 15% (6-month return exceeds 15%)
     Exit: ROC(126) < 0% OR Close < SMA200
     Hypothesis: simple relative-strength — buy stocks that are already working.
     6-month return > 15% filters for strong intermediate-term momentum, not just
     short-term noise. The SMA200 ensures we're in an uptrend context.
     This is different from the ROC (20d) champion — 126 bars is 6× longer
     and captures multi-month price momentum rather than short-term rate of change.

  2. NR7 Volatility Contraction + Breakout
     Entry: Today's daily range is the narrowest of last 7 bars (NR7 pattern)
            AND Close > previous bar's High (micro-breakout bar)
            AND SMA200[today] > SMA200[20 bars ago] (uptrend check)
     Exit: Close < SMA50
     Hypothesis: volatility contraction before breakout is a classic institutional
     accumulation signal. When range contracts to 7-bar minimum, big money is
     "coiling the spring" before expansion. The micro-breakout confirms the move.
     Exit at SMA50 loss gives trades room to breathe in normal corrections.

These are genuinely different from all previously tested strategies:
  - Price Momentum uses a much longer ROC window (126d vs 20d in our champion)
  - NR7 uses a range-based volatility filter — no similar signal has been tested
"""

import numpy as np
import pandas as pd
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import calculate_sma
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ===========================================================================
# STRATEGY 1 — Price Momentum (6-month ROC > 15%) + SMA200
# Hypothesis: sustained multi-month momentum with uptrend context
# ===========================================================================

@register_strategy(
    name="Price Momentum (6m ROC, 15pct) + SMA200",
    dependencies=[],
    params={
        "roc_period":     get_bars_for_period("126d", _TF, _MUL),  # ~6 months
        "roc_threshold":  15.0,   # 15% 6-month return minimum
        "sma_slow":       get_bars_for_period("200d", _TF, _MUL),
    },
)
def price_momentum_6m_roc_sma200(df, **kwargs):
    """6-month Price Momentum + SMA200 uptrend gate.

    Buys stocks that have returned > 15% over the past 6 months while
    trading above their 200-day SMA. This is pure relative-strength
    trend following on a multi-month horizon.

    Key differences from ROC (20d) + MA Full Stack champion (rank 7):
    - 126-bar ROC vs 20-bar ROC: captures sustained institutional momentum
      rather than short-term price velocity
    - Simple SMA200 gate only — no triple MA stack required
    - Exit on ROC turning negative (momentum reversal) OR SMA200 loss
      (structural uptrend ends)

    Why 15% threshold:
    - S&P 500 historical 6-month return ≈ 4-6% in bull markets
    - Requiring 15% (2.5-3.5× market average) selects for stocks with
      genuine outperformance relative to the market
    - Too high (20%+) would be too selective; too low (5%) overlaps with
      random noise
    """
    roc_period    = kwargs["roc_period"]
    roc_threshold = kwargs["roc_threshold"]
    sma_slow      = kwargs["sma_slow"]

    # ROC(126): percentage change over the past 126 bars
    # pct_change gives decimal; multiply by 100 for percentage points
    df["_roc"] = df["Close"].pct_change(periods=roc_period) * 100.0

    # SMA200 uptrend gate
    df = calculate_sma(df, sma_slow)
    sma_col = f"SMA_{sma_slow}"
    is_uptrend = df["Close"] > df[sma_col]

    # Entry: both conditions
    is_entry = (df["_roc"] > roc_threshold) & is_uptrend

    # Exit: momentum reversal OR structural uptrend failure
    is_exit = (df["_roc"] < 0.0) | (~is_uptrend)

    # Stateless forward-fill signal construction
    signals = []
    in_position = False

    for i in range(len(df)):
        roc_val = df["_roc"].iloc[i]
        sma_val = df[sma_col].iloc[i]

        if pd.isna(roc_val) or pd.isna(sma_val):
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
    df.drop(columns=["_roc", sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 2 — NR7 Volatility Contraction + Breakout
# Hypothesis: range compression before expansion = institutional accumulation
# ===========================================================================

@register_strategy(
    name="NR7 Volatility Contraction + Breakout",
    dependencies=[],
    params={
        "nr_window":      7,      # Narrowest Range of last N bars
        "sma_fast":       get_bars_for_period("50d",  _TF, _MUL),   # exit MA
        "sma_slow":       get_bars_for_period("200d", _TF, _MUL),   # trend gate
        "trend_lookback": get_bars_for_period("20d",  _TF, _MUL),   # SMA200 slope check
    },
)
def nr7_volatility_contraction_breakout(df, **kwargs):
    """NR7 Volatility Contraction + Breakout with SMA200 trend gate.

    NR7 (Narrowest Range 7) is a classic pattern popularised by Toby Crabel.
    When the current day's range (High - Low) is the smallest of the past 7
    bars, the market is in a state of maximum compression — typically preceding
    a directional expansion.

    Signal logic:
    1. NR7: today's range < all of the past 6 bars' ranges (7-bar minimum)
    2. Micro-breakout: today's Close > yesterday's High (bullish bias confirmed)
    3. Uptrend: SMA200 today > SMA200 [20 bars ago] (rising 200-day MA slope)
    4. Exit: Close < SMA50 (hold while price is above 50-day MA)

    Why this is different from other breakout strategies:
    - Donchian breakout requires a 40-bar NEW HIGH (absolute price level)
    - NR7 is relative volatility — it fires after ANY compression period,
      not just near multi-month highs
    - NR7 can fire in the middle of an uptrend or early in a new trend,
      whereas Donchian requires the price to be at a multi-month extreme
    - Expected: more frequent entries (many small compressions vs rare 40-bar highs)
      but with shorter average hold duration (SMA50 exit vs 20-bar new-low exit)

    This catches institutional "coiling" before earnings reports, sector rotations,
    and other catalysts where range narrows before a defined move.
    """
    nr_window      = kwargs["nr_window"]
    sma_fast       = kwargs["sma_fast"]
    sma_slow       = kwargs["sma_slow"]
    trend_lookback = kwargs["trend_lookback"]

    # Daily range
    df["_range"] = df["High"] - df["Low"]

    # NR7: today's range is the narrowest of the past nr_window bars
    # rolling(nr_window).min() gives the minimum INCLUDING today
    # We want today's range < minimum of PREVIOUS (nr_window-1) bars
    df["_range_min_prev"] = df["_range"].shift(1).rolling(window=nr_window - 1).min()
    is_nr7 = df["_range"] < df["_range_min_prev"]

    # Micro-breakout: close above previous bar's high
    is_breakout = df["Close"] > df["High"].shift(1)

    # SMA200 slope gate: SMA200 today > SMA200 [trend_lookback bars ago]
    df = calculate_sma(df, sma_slow)
    sma_slow_col = f"SMA_{sma_slow}"
    is_uptrend = df[sma_slow_col] > df[sma_slow_col].shift(trend_lookback)

    # SMA50 exit
    df = calculate_sma(df, sma_fast)
    sma_fast_col = f"SMA_{sma_fast}"

    # Entry: all three conditions on same bar
    is_entry = is_nr7 & is_breakout & is_uptrend

    # Exit: close below SMA50
    is_exit = df["Close"] < df[sma_fast_col]

    # Stateless signal construction
    signals = []
    in_position = False

    for i in range(len(df)):
        if pd.isna(df[sma_slow_col].iloc[i]) or pd.isna(df[sma_fast_col].iloc[i]):
            signals.append(-1)
            continue
        if pd.isna(df["_range_min_prev"].iloc[i]):
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
    df.drop(columns=["_range", "_range_min_prev", sma_slow_col, sma_fast_col],
            errors="ignore", inplace=True)
    return df
