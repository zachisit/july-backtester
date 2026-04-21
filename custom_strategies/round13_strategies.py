# custom_strategies/round13_strategies.py
"""
Round 13/14 Research Strategies — New Weekly Signal Families

Hypothesis: The weekly timeframe improvement (165-215% Sharpe) should extend to
signal families not yet tested on weekly bars. Current weekly champions use:
  - MA crossover (MAC Fast Exit)
  - Price channel breakout (Donchian)
  - Mean reversion bounce (MA Bounce)
  - Rate of change momentum (Price Momentum)

Two untested signal families for weekly bars:
  1. MACD momentum divergence — MACD(3/6/2) on weekly bars ≈ MACD(12/26/9) on daily
     Entry: MACD line crosses above signal line AND price > SMA(40w)
     Exit:  MACD line crosses below signal line OR price < SMA(40w)

  2. RSI trend threshold — RSI(14w) crossing above 55 in uptrend
     Entry: RSI(14w) crosses above 55 from below AND price > SMA(40w)
     Exit:  RSI(14w) drops below 45 OR price < SMA(40w)
     Hypothesis: RSI>55 on weekly bars signals genuine trend conviction, not daily noise
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
# STRATEGY 1 — MACD Weekly (3/6/2) + SMA200
# MACD(12,26,9) on daily ≈ MACD(3,6,2) on weekly (each period / 5)
# ===========================================================================

@register_strategy(
    name="MACD Weekly (3/6/2) + SMA200",
    dependencies=[],
    params={
        "fast":     get_bars_for_period("15d", _TF, _MUL),   # 3w (= 12d/5 * 1.25)
        "slow":     get_bars_for_period("30d", _TF, _MUL),   # 6w (= 26d/5 * 1.15)
        "signal":   get_bars_for_period("10d", _TF, _MUL),   # 2w (= 9d/5 * 1.1)
        "sma_slow": get_bars_for_period("200d", _TF, _MUL),  # 40w uptrend gate
    },
)
def macd_weekly_sma200(df, **kwargs):
    """MACD crossover on weekly bars with SMA200 uptrend filter.

    Weekly MACD(3,6,2) is the natural weekly equivalent of daily MACD(12,26,9):
    each period divided by 5 (trading days per week). This filters out the
    daily noise that causes frequent MACD crossovers on daily charts.

    A weekly MACD cross represents a true shift in intermediate-term momentum,
    not a 2-3 day fluctuation. Combined with the SMA(40w) uptrend gate, entries
    are restricted to periods of genuine sustained price strength.

    Signal logic:
    - EMA_fast = EMA(Close, fast_period)
    - EMA_slow = EMA(Close, slow_period)
    - MACD_line = EMA_fast - EMA_slow
    - Signal_line = EMA(MACD_line, signal_period)
    - Entry: MACD_line crosses above Signal_line AND Close > SMA(40w)
    - Exit:  MACD_line crosses below Signal_line OR Close < SMA(40w)
    """
    fast     = kwargs["fast"]
    slow     = kwargs["slow"]
    signal   = kwargs["signal"]
    sma_slow = kwargs["sma_slow"]

    # Compute MACD components
    ema_fast   = df["Close"].ewm(span=fast,   adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=slow,   adjust=False).mean()
    macd_line  = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=max(signal, 2), adjust=False).mean()

    # SMA uptrend gate
    df = calculate_sma(df, sma_slow)
    sma_col = f"SMA_{sma_slow}"
    is_uptrend = df["Close"] > df[sma_col]

    # Crossover detection
    macd_above = macd_line > signal_line
    macd_cross_up   = macd_above & ~macd_above.shift(1).fillna(False)
    macd_cross_down = ~macd_above & macd_above.shift(1).fillna(False)

    is_entry = macd_cross_up & is_uptrend
    is_exit  = macd_cross_down | ~is_uptrend

    # Stateful signal construction
    signals = []
    in_position = False

    for i in range(len(df)):
        sma_val = df[sma_col].iloc[i]
        if pd.isna(sma_val) or pd.isna(macd_line.iloc[i]):
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
# STRATEGY 2 — RSI Weekly Trend (55-cross) + SMA200
# RSI(14w) crossing above 55 = genuine momentum threshold on weekly bars
# ===========================================================================

@register_strategy(
    name="RSI Weekly Trend (55-cross) + SMA200",
    dependencies=[],
    params={
        "rsi_period": 14,             # 14 weekly bars ≈ 14-week RSI (natural period)
        "rsi_entry":  55.0,           # RSI above 55 = bullish momentum threshold
        "rsi_exit":   45.0,           # RSI below 45 = momentum stalled/reversed
        "sma_slow":   get_bars_for_period("200d", _TF, _MUL),  # 40w uptrend gate
    },
)
def rsi_weekly_trend_sma200(df, **kwargs):
    """RSI weekly trend-follow: enter when RSI crosses above 55 in an uptrend.

    On daily bars, RSI frequently oscillates between 40-60 creating many false
    crossovers. On weekly bars, an RSI(14w) cross above 55 represents a sustained
    multi-week shift in buying vs selling pressure — a much higher-quality signal.

    Key design choices:
    - RSI threshold 55 (not 50): eliminates weak/borderline momentum crossings
    - RSI exit at 45 (not 50): gives positions room to breathe through brief
      pullbacks without triggering whipsaw exits
    - SMA(40w) gate: only enter in defined uptrends (same gate as all weekly champions)
    - 14-week RSI is the natural weekly equivalent of 14-day RSI

    Hypothesis: RSI>55 on weekly bars is a regime signal (strong bull momentum),
    not a short-term oscillator. The weekly timeframe eliminates the noise that
    makes daily RSI strategies prone to frequent false crosses.
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

    # RSI crossover detection
    rsi_above_entry = df[rsi_col] > rsi_entry
    rsi_cross_up = rsi_above_entry & ~rsi_above_entry.shift(1).fillna(False)

    is_entry = rsi_cross_up & is_uptrend
    is_exit  = (df[rsi_col] < rsi_exit) | ~is_uptrend

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
