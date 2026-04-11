# custom_strategies/round36_strategies.py
"""
Round 36 Research Strategies — Genuinely New Ecosystems

After testing momentum oscillators (Round 34) and mean reversion (Round 35),
this round explores two fundamentally different signal archetypes:

  1. Relative Momentum vs SPY (cross-sectional / relative strength)
     Signal: Stock 13-week return / SPY 13-week return > 1.15 (outperforming by 15%+)
     AND price > SMA(40w) uptrend gate
     This is structurally different from ALL existing champions:
     - Price Momentum (6m ROC): absolute momentum (stock rising by 15%+)
     - RSI/Stochastic/Williams R: oscillator threshold signals
     - Relative Momentum: measures RELATIVE performance (stock vs index)
     Hypothesis: Stocks outperforming the index by 15%+ over 13w are in genuine
     relative strength phases → tend to continue outperforming.

  2. Bollinger Band Squeeze Breakout Weekly
     Signal: Price breaks above upper BB AFTER a period of extreme low volatility
     (bandwidth at 40-bar minimum) AND price > SMA(40w)
     This captures the "coiled spring" dynamic: periods of abnormally low volatility
     on weekly bars precede major breakouts. Filters out breakouts that occur during
     normal volatility — only triggers on genuine compression-expansion cycles.
     Different from plain BB Breakout (Round 34) because it requires PRIOR squeeze.
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
# STRATEGY 1 — Relative Momentum vs SPY Weekly (13w outperformance) + SMA200
# Entry: Stock 13w return > SPY 13w return × 1.15 AND price > SMA(40w)
# ===========================================================================

@register_strategy(
    name="Relative Momentum (13w vs SPY) Weekly + SMA200",
    dependencies=["spy"],
    params={
        "roc_bars":   get_bars_for_period("65d", _TF, _MUL),    # 13w lookback
        "rel_thresh": 1.15,                                       # outperform SPY by 15%+
        "sma_slow":   get_bars_for_period("200d", _TF, _MUL),   # 40w uptrend gate
    },
)
def relative_momentum_weekly_sma200(df, spy_df, **kwargs):
    """Relative momentum strategy: buy stocks outperforming SPY by 15%+ over 13w.

    This is the only strategy in the research that uses RELATIVE performance
    rather than absolute price levels or oscillator thresholds. It answers:
    "Is this stock winning more than the market itself?"

    Key distinction from Price Momentum (6m ROC > 15%):
    - Price Momentum: buy any stock up 15%+ in 6 months (absolute threshold)
    - Relative Momentum: buy stocks whose 13w return > SPY's 13w return × 1.15
    During a strong bull market, Price Momentum fires on nearly all rising stocks.
    Relative Momentum is more selective — requires the stock to BEAT the index
    meaningfully. In a flat/down market, it correctly stays flat.

    Signal logic:
    - stock_roc = Close / Close.shift(13w) - 1
    - spy_roc   = SPY_Close / SPY_Close.shift(13w) - 1
    - relative  = (1 + stock_roc) / (1 + spy_roc)   [> 1 means stock is outperforming]
    - Entry: relative > rel_thresh AND Close > SMA(40w)
    - Exit:  relative <= 1.0 (stock now underperforming SPY) OR Close < SMA(40w)
    """
    roc_bars  = kwargs["roc_bars"]
    rel_thresh = kwargs["rel_thresh"]
    sma_slow  = kwargs["sma_slow"]

    # Align SPY to df index
    spy_close = spy_df["Close"].reindex(df.index, method="ffill")

    # 13-week rate of change
    stock_roc = df["Close"] / df["Close"].shift(roc_bars) - 1
    spy_roc   = spy_close / spy_close.shift(roc_bars) - 1

    # Relative strength ratio: > 1 means stock outperforming SPY
    relative = (1 + stock_roc) / (1 + spy_roc.replace(0, np.nan))

    # SMA uptrend gate
    df = calculate_sma(df, sma_slow)
    sma_col   = f"SMA_{sma_slow}"
    is_uptrend = df["Close"] > df[sma_col]

    # Entry: outperforming by rel_thresh AND in uptrend
    is_outperforming = relative > rel_thresh
    was_outperforming = is_outperforming.shift(1).fillna(False)
    cross_up = is_outperforming & ~was_outperforming

    is_entry = cross_up & is_uptrend
    is_exit  = (relative <= 1.0) | ~is_uptrend

    # Stateful signal construction
    signals = []
    in_position = False

    for i in range(len(df)):
        rel_val = relative.iloc[i]
        sma_val = df[sma_col].iloc[i]

        if pd.isna(rel_val) or pd.isna(sma_val):
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
# STRATEGY 2 — BB Squeeze Breakout Weekly + SMA200
# Entry: Close > Upper BB AFTER bandwidth at 40-bar minimum AND price > SMA(40w)
# ===========================================================================

@register_strategy(
    name="BB Squeeze Breakout Weekly + SMA200",
    dependencies=[],
    params={
        "bb_length":       get_bars_for_period("100d", _TF, _MUL),  # 20w Bollinger Band
        "bb_std":          2.0,
        "squeeze_length":  get_bars_for_period("200d", _TF, _MUL),  # 40w squeeze lookback
        "sma_slow":        get_bars_for_period("200d", _TF, _MUL),  # 40w uptrend gate
    },
)
def bb_squeeze_breakout_weekly_sma200(df, **kwargs):
    """Bollinger Band squeeze breakout on weekly bars with SMA200 uptrend gate.

    The "squeeze" condition requires bandwidth at a 40-bar (40-week ≈ 10-month)
    minimum. This means the stock's weekly price range has been abnormally narrow
    for nearly a year before the breakout fires. This is much rarer than the plain
    BB Breakout (Round 34, which requires only current upper band penetration).

    Coiled spring mechanics:
    - Long periods of narrow volatility = market indecision / accumulation
    - When a strong trend begins after a squeeze, initial moves are sustained
    - SMA200 ensures the "spring" releases upward, not downward

    Signal logic:
    - Bandwidth = (Upper BB - Lower BB) / SMA(20w)
    - Squeeze = current bandwidth = 40-bar minimum bandwidth
    - Entry: Close > Upper BB AND squeeze was active last bar AND Close > SMA(40w)
    - Exit:  Close < Middle BB OR Close < SMA(40w)
    """
    bb_length      = kwargs["bb_length"]
    bb_std         = kwargs["bb_std"]
    squeeze_length = kwargs["squeeze_length"]
    sma_slow       = kwargs["sma_slow"]

    # Bollinger Bands
    sma_bb     = df["Close"].rolling(bb_length).mean()
    std_bb     = df["Close"].rolling(bb_length).std()
    upper_band = sma_bb + bb_std * std_bb

    # Bandwidth and squeeze detection
    bandwidth     = (2 * bb_std * std_bb) / sma_bb.replace(0, np.nan)
    min_bandwidth = bandwidth.rolling(squeeze_length).min()
    squeeze_on    = bandwidth <= min_bandwidth  # at/near minimum bandwidth

    # SMA uptrend gate
    df = calculate_sma(df, sma_slow)
    sma_col   = f"SMA_{sma_slow}"
    is_uptrend = df["Close"] > df[sma_col]

    # Entry: close > upper band AND prior bar had squeeze AND uptrend
    above_upper     = df["Close"] > upper_band
    above_middle    = df["Close"] > sma_bb
    prior_squeeze   = squeeze_on.shift(1).fillna(False)

    is_entry = above_upper & prior_squeeze & is_uptrend
    is_exit  = ~above_middle | ~is_uptrend

    # Stateful signal construction
    signals = []
    in_position = False

    for i in range(len(df)):
        if pd.isna(sma_bb.iloc[i]) or pd.isna(min_bandwidth.iloc[i]) or pd.isna(df[sma_col].iloc[i]):
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
