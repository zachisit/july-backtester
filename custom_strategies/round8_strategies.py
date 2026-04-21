# custom_strategies/round8_strategies.py
"""
Round 8 Research Strategies — Four targeted experiments informed by R7 lessons.

Round 7 taught four lessons:
  - RSI>50 is redundant on N-bar new-high breakouts (r=+1.00 proven)
  - CMF window length is not the problem — shorter = more noise
  - EMA+CMF Hold Gate: MaxRcvry 5008 days from conflicting exit conditions
  - ROC+MA Full Stack (SQN 6.95) proves high-trade-count strategies win on confidence

Four new experiments:

  1. MA Confluence (10/20/50) Fast Exit + ATR Trailing Stop (3.5x)
     Round 6's ATR attempt failed at 2.0x (too tight). 3.5x ATR on NVDA/META
     (ATR ≈ 5-8% of price) = 17.5-28% trailing stop — wide enough to survive
     normal volatility. Exit = MAC fast cross OR ATR stop, whichever first.
     Goal: rescue MC Score without destroying the equity curve.

  2. EMA Crossover (8/21) + OBV Hold Gate
     Round 7's EMA+CMF Hold Gate failed with MaxRcvry 5008 days because CMF
     fluctuates near zero, creating frequent false exits. OBV trend (OBV > OBV MA)
     is a much more stable hold condition — once OBV builds a trend, it persists
     unlike CMF. Same architecture, different volume indicator.

  3. Donchian (40/20) + Volume Breakout Confirmation
     Round 7 proved RSI>50 is redundant on breakouts. Volume confirmation is
     a genuinely different hypothesis: require volume > 1.5x 20-bar average on
     the breakout bar. Volume expansion confirms institutional participation.
     Breakouts on low volume (< average) often fail immediately.

  4. MA Bounce (50d) + OBV Confirmation
     MA Bounce (50d/3bar) is our r=0.02 diversifier with 45,283% P&L on 44 symbols.
     Gate bounce entries on OBV being above its 20-bar MA. If institutions are
     net buying (OBV above MA), the 50-SMA bounce is more likely to hold.
     If OBV is below its MA, the bounce is likely to fail (distribution phase).
"""

import numpy as np
import pandas as pd
import pandas_ta as ta
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import (
    ma_confluence_logic,
    calculate_atr,
    calculate_sma,
    donchian_channel_breakout_logic,
    ema_crossover_unfiltered_logic,
    ma_bounce_logic,
)
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ===========================================================================
# STRATEGY 1 — MA Confluence (10/20/50) Fast Exit + ATR Trailing Stop (3.5x)
# Hypothesis: wide ATR stop rescues MC Score without destroying equity curve
# ===========================================================================

@register_strategy(
    name="MA Confluence (10/20/50) Fast Exit + ATR 3.5x",
    dependencies=[],
    params={
        "ma_fast":        get_bars_for_period("10d",  _TF, _MUL),
        "ma_medium":      get_bars_for_period("20d",  _TF, _MUL),
        "ma_slow":        get_bars_for_period("50d",  _TF, _MUL),
        "atr_period":     get_bars_for_period("14d",  _TF, _MUL),
        "atr_multiplier": 3.5,
    },
)
def mac_fast_exit_atr_3_5x(df, **kwargs):
    """MA Confluence Fast Exit with a 3.5x ATR trailing stop added.

    Plain MA Confluence Fast Exit has MC Score -1 on 44-symbol universe
    due to synchronized tech crashes. The goal: add an ATR trailing stop
    that triggers BEFORE large drawdowns accumulate, improving the MC Score.

    Why 3.5x:
    - Round 6's 2.0x ATR generated 814 trades (vs 344 plain) — too tight
    - NVDA/META ATR ≈ 5-8% of price → 2.0x = 10-16% stop (hit on normal days)
    - 3.5x = 17.5-28% stop → only triggered by real breakdowns, not normal vol
    - If 3.5x still overfits (too many stops), next step would be 5.0x or
      a fixed percentage stop (e.g. 20% from entry)

    Exit rule (whichever fires first):
    - Primary: 10-SMA crosses below 50-SMA (the existing Fast Exit condition)
    - Secondary: Close drops below ATR trailing stop level

    Entry rule: unchanged — all three MAs in bullish order.
    """
    ma_fast        = kwargs["ma_fast"]
    ma_medium      = kwargs["ma_medium"]
    ma_slow        = kwargs["ma_slow"]
    atr_period     = kwargs["atr_period"]
    atr_multiplier = kwargs["atr_multiplier"]

    # Step 1: compute MA confluence indicators inline
    df["_maf"] = df["Close"].rolling(window=ma_fast).mean()
    df["_mam"] = df["Close"].rolling(window=ma_medium).mean()
    df["_mas"] = df["Close"].rolling(window=ma_slow).mean()

    # Step 2: compute ATR (adds 'ATR' column)
    df = calculate_atr(df, period=atr_period)

    # Entry condition: full bullish stack
    is_full_stack = (
        (df["Close"] > df["_mas"]) &
        (df["_maf"]  > df["_mas"]) &
        (df["_mam"]  > df["_mas"]) &
        (df["_maf"]  > df["_mam"])
    )
    # Fast exit condition: fast MA crosses below slow MA
    is_fast_exit = df["_maf"] < df["_mas"]

    # Step 3: stateful loop — track ATR trailing stop
    signals = []
    in_position = False
    atr_stop = 0.0

    for i in range(len(df)):
        close = df["Close"].iloc[i]
        low   = df["Low"].iloc[i]
        atr_val = df["ATR"].iloc[i]

        if pd.isna(atr_val) or pd.isna(df["_mas"].iloc[i]):
            signals.append(-1)
            continue

        if not in_position:
            if is_full_stack.iloc[i]:
                in_position = True
                atr_stop = close - atr_val * atr_multiplier
                signals.append(1)
            else:
                signals.append(-1)
        else:
            # Check exits: ATR stop or fast exit
            if low < atr_stop or is_fast_exit.iloc[i]:
                in_position = False
                atr_stop = 0.0
                signals.append(-1)
            else:
                # Still in — update trailing stop upward only
                new_stop = close - atr_val * atr_multiplier
                atr_stop = max(atr_stop, new_stop)
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=["_maf", "_mam", "_mas"], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 2 — EMA Crossover (8/21) + OBV Hold Gate
# Hypothesis: OBV trend is more stable than CMF as a sustained hold condition
# ===========================================================================

@register_strategy(
    name="EMA Crossover (8/21) + OBV Hold Gate",
    dependencies=[],
    params={
        "fast_ema":      get_bars_for_period("8d",  _TF, _MUL),
        "slow_ema":      get_bars_for_period("21d", _TF, _MUL),
        "obv_ma_length": get_bars_for_period("20d", _TF, _MUL),
    },
)
def ema_8_21_obv_hold_gate(df, **kwargs):
    """EMA 8/21 crossover with OBV trend as a sustained hold condition.

    Round 7 tested EMA (8/21) + CMF Hold Gate but got MaxRcvry 5,008 days.
    Root cause: CMF frequently crosses zero in both directions during trending
    periods, creating many false exits followed by EMA re-entry → extended
    flat/churn periods that stretch recovery time to 13+ years.

    OBV trend is fundamentally more stable:
    - OBV accumulates (running sum of volume × direction) — it builds momentum
    - Once OBV is trending above its MA, it tends to stay there for weeks/months
    - CMF resets each period (bounded oscillator), so it can oscillate without
      corresponding price weakness
    - OBV will only drop below its MA when there is genuinely sustained selling
      volume, which is a much stronger exit signal than CMF dipping below zero

    Same architecture as EMA+CMF but with a more stable hold indicator:
    - Entry: EMA 8 crosses above EMA 21 (structural signal)
    - Hold condition: OBV > 20-bar OBV MA (volume flow confirmation sustained)
    - Exit: EMA bearish cross OR OBV drops below its MA

    This strategy's correlation with MA Bounce (r ~ 0.08) and MA Confluence
    (r ~ 0.30) should be low — it exits on volume flow failure, not price structure.
    """
    fast_ema     = kwargs["fast_ema"]
    slow_ema     = kwargs["slow_ema"]
    obv_ma_length = kwargs["obv_ma_length"]

    # Step 1: EMA crossover signal
    df = ema_crossover_unfiltered_logic(df, fast_ema=fast_ema, slow_ema=slow_ema)
    ema_signal = df["Signal"].copy()

    # Step 2: compute OBV and OBV MA inline
    # pandas_ta OBV appended as 'OBV' column
    df.ta.obv(append=True)
    df["_OBV_MA"] = df["OBV"].rolling(window=obv_ma_length).mean()
    obv_above_ma = df["OBV"] > df["_OBV_MA"]

    # Step 3: hold long only when EMA bullish AND OBV trending up
    df["Signal"] = np.where(
        ema_signal == 1,
        np.where(obv_above_ma, 1, -1),
        -1,
    )

    df.drop(columns=["_OBV_MA"], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 3 — Donchian (40/20) + Volume Breakout Confirmation
# Hypothesis: breakouts on expanding volume have higher success rates
# ===========================================================================

@register_strategy(
    name="Donchian (40/20) + Volume Breakout",
    dependencies=[],
    params={
        "entry_period":    get_bars_for_period("40d", _TF, _MUL),
        "exit_period":     get_bars_for_period("20d", _TF, _MUL),
        "volume_ma_length": get_bars_for_period("20d", _TF, _MUL),
        "volume_multiplier": 1.5,
    },
)
def donchian_40_20_volume_breakout(df, **kwargs):
    """Donchian (40/20) gated by volume expansion on the breakout bar.

    Round 7 proved that RSI>50 at a 40-bar new high is always true (r=+1.00).
    Volume confirmation is a genuinely different hypothesis: false breakouts
    tend to occur on below-average volume (low conviction), while real trend
    initiations tend to have volume expansion (institutional participation).

    Gate: Volume on the breakout bar must exceed 1.5× the 20-bar average volume.

    This is applied ONLY to the entry event (first bar of Signal==1), not to
    the sustained hold. Once in a trade, we hold regardless of volume until the
    structural exit (20-bar new low). This avoids the mistakes seen with R6:
    - MA Bounce+RSI: gating the hold destroyed the strategy (90% filtered)
    - Here we only filter the INITIAL breakout quality, not subsequent bars

    Volume expansion ratio = 1.5x means we require 50% more volume than average.
    This should filter out low-conviction breakouts while keeping the highest-
    quality institutional-flow-backed breakouts.

    Expected: fewer entries (roughly 40-60% of Donchian entries will have
    volume < 1.5x average), higher win rate, similar or better Sharpe.
    """
    entry_period      = kwargs["entry_period"]
    exit_period       = kwargs["exit_period"]
    volume_ma_length  = kwargs["volume_ma_length"]
    volume_multiplier = kwargs["volume_multiplier"]

    # Step 1: Donchian signal
    df = donchian_channel_breakout_logic(
        df,
        entry_period=entry_period,
        exit_period=exit_period,
    )
    donchian_signal = df["Signal"].copy()

    # Step 2: volume expansion condition on breakout bar
    df["_vol_ma"] = df["Volume"].rolling(window=volume_ma_length).mean()
    volume_expanded = df["Volume"] > (df["_vol_ma"] * volume_multiplier)

    # Step 3: identify raw entry and exit events (same pattern as R7)
    raw_entry = (donchian_signal.shift(1).fillna(0) != 1) & (donchian_signal == 1)
    raw_exit  = (donchian_signal.shift(1).fillna(0) != -1) & (donchian_signal == -1)

    # Step 4: gate entries on volume expansion; exits unconditional
    valid_entry = raw_entry & volume_expanded

    df["Signal"] = np.where(valid_entry, 1, np.where(raw_exit, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)

    df.drop(columns=["_vol_ma"], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 4 — MA Bounce (50d/3bar) + OBV Confirmation Gate
# Hypothesis: volume-confirmed bounces have higher win rate and smoother curve
# ===========================================================================

@register_strategy(
    name="MA Bounce (50d/3bar) + OBV Gate",
    dependencies=[],
    params={
        "ma_length":     get_bars_for_period("50d",  _TF, _MUL),
        "filter_bars":   3,
        "obv_ma_length": get_bars_for_period("20d",  _TF, _MUL),
        "gate_length":   get_bars_for_period("200d", _TF, _MUL),
    },
)
def ma_bounce_50d_obv_gate(df, **kwargs):
    """MA Bounce (50d/3bar) with OBV trend gate at entry + SMA200 uptrend gate.

    MA Bounce (50d/3bar)+SMA200 is our structural diversifier: 45,283% P&L,
    r=0.02 vs MA Confluence, Sharpe +0.61. Win rate is 33% — low because the
    strategy enters all 50-SMA touches regardless of volume context.

    Adding OBV gate at entry:
    - If OBV is above its 20-bar MA at the time of the bounce → institutions
      are net accumulating → the bounce is more likely to hold
    - If OBV is below its MA → institutions are distributing → the 50-SMA
      bounce is more likely to fail and continue declining

    This gate is applied ONLY to the entry event (raw_entry), NOT to the
    sustained hold. This is the critical lesson from R6: gating the HOLD
    on an oscillator destroys the strategy (MA Bounce+RSI: 65 trades).
    The entry gate is a quality filter; the exit (3 closes below 50-SMA)
    remains the structural price-based exit.

    Expected: fewer entries than plain MA Bounce, higher win rate (~40-45%),
    same or better Sharpe, better RS(min), very low correlation with both
    MAC Fast Exit and Donchian (different signal combination entirely).
    """
    ma_length    = kwargs["ma_length"]
    filter_bars  = kwargs["filter_bars"]
    obv_ma_length = kwargs["obv_ma_length"]
    gate_length  = kwargs["gate_length"]

    # Step 1: MA Bounce signal
    df = ma_bounce_logic(df, ma_length=ma_length, filter_bars=filter_bars)
    bounce_signal = df["Signal"].copy()

    # Step 2: SMA200 uptrend gate (same as plain MA Bounce)
    df = calculate_sma(df, gate_length)
    sma_col = f"SMA_{gate_length}"
    is_uptrend = df["Close"] > df[sma_col]

    # Step 3: OBV trend at entry time
    df.ta.obv(append=True)
    df["_OBV_MA"] = df["OBV"].rolling(window=obv_ma_length).mean()
    obv_above_ma = df["OBV"] > df["_OBV_MA"]

    # Step 4: identify raw entry events from bounce signal
    raw_entry = (bounce_signal.shift(1).fillna(0) != 1) & (bounce_signal == 1)
    raw_exit  = (bounce_signal.shift(1).fillna(0) != -1) & (bounce_signal == -1)

    # Step 5: gate entries on BOTH SMA200 uptrend AND OBV above MA
    valid_entry = raw_entry & is_uptrend & obv_above_ma

    df["Signal"] = np.where(valid_entry, 1, np.where(raw_exit, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)

    df.drop(columns=["_OBV_MA"], errors="ignore", inplace=True)
    return df
