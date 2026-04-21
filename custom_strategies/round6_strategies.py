# custom_strategies/round6_strategies.py
"""
Round 6 Research Strategies — five targeted fixes designed from Round 5 failures.

Round 5 identified five specific problems to address:

  1. CMF MaxDD 29.4% + RS(min)=-16.59
     Root cause: sell_threshold=-0.05 lets positions ride distribution phases
     too long.  Fix: tighten CMF exit AND add RSI<40 secondary exit path.

  2. MA Bounce WinRate 34.7%
     Root cause: buys every 50-SMA touch including overbought ones where
     RSI is 60-70.  Fix: require RSI<50 at bounce time (genuine exhaustion).

  3. Donchian (60d/20d) + MA Alignment Gate — new hypothesis
     Longer entry window (3-month new high) plus MA fast/slow alignment
     to confirm trend quality before breakout entry.  Not tested in Round 5.

  4. Keltner Sharpe -0.02 — replace with OBV + MA Confluence Alignment
     Keltner delays entries past the optimal point.  OBV crossover above
     its MA fires earlier and at volume-confirmed inflection points.
     Gate with full MA stack for trend quality.

  5. MA Confluence Full Stack MC Score 2 — add ATR trailing stop
     The bearish-stack exit gives back large gains in sharp reversals.
     Adding an ATR trailing stop as a secondary exit rescues the MC score
     by cutting losses faster when price drops hard.

All strategies use only existing helpers/indicators.py functions.
"""

import numpy as np
import pandas as pd
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import (
    chaikin_money_flow_logic,
    calculate_rsi,
    ma_bounce_logic,
    calculate_sma,
    donchian_channel_breakout_logic,
    obv_price_confirmation_logic,
    calculate_atr,
)
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ===========================================================================
# STRATEGY 1 — CMF + RSI Exit Gate (20d)
# Fix: CMF MaxDD 29.4% and RS(min)=-16.59
# ===========================================================================

@register_strategy(
    name="CMF+RSI Exit Gate (20d)",
    dependencies=[],
    params={
        "length":     get_bars_for_period("20d", _TF, _MUL),
        "rsi_length": get_bars_for_period("14d", _TF, _MUL),
        "rsi_exit":   40,
        "gate_length": get_bars_for_period("200d", _TF, _MUL),
    },
)
def cmf_rsi_exit_gate_20(df, **kwargs):
    """CMF momentum with dual exit: tighter CMF threshold + RSI<40 secondary exit.

    Round 5 problem: CMF+SMA200 had MaxDD 29.4% and RS(min)=-16.59 because
    the sell_threshold=-0.05 allowed positions to stay open while CMF sat
    between 0 and -0.05 (a distribution zone lasting weeks or months).

    Two-path exit design:
    - Exit Path A (CMF): sell when CMF drops below 0.00 (zero-cross down).
      Previously the threshold was -0.05 — tightening to 0.00 means ANY
      net outflow triggers review, cutting distribution-phase holds.
    - Exit Path B (RSI): if RSI(14) drops below 40 while long, exit
      immediately regardless of CMF state. RSI<40 means price momentum
      has already deteriorated — we do not need CMF to confirm.

    The RSI path adds a fast-reaction mechanism that CMF lacks (CMF is a
    smoothed 20-bar sum, inherently lagged). Together they cover two failure
    modes: gradual distribution (caught by tighter CMF) and sharp price
    drops (caught by RSI).

    SMA200 gate still required to prevent entry during confirmed downtrends.
    Only entries are gated; exits from both paths are unconditional.
    """
    length      = kwargs["length"]
    rsi_length  = kwargs["rsi_length"]
    rsi_exit    = kwargs["rsi_exit"]
    gate_length = kwargs["gate_length"]

    # Step 1: CMF with tighter sell threshold (0.00 vs prior -0.05)
    df = chaikin_money_flow_logic(
        df,
        length=length,
        buy_threshold=0.05,
        sell_threshold=0.00,
    )
    cmf_signal = df["Signal"].copy()

    # Step 2: RSI secondary exit — any bar where long AND RSI < rsi_exit
    df = calculate_rsi(df, rsi_length)
    rsi_col = f"RSI_{rsi_length}"

    # Step 3: SMA200 gate for entries
    df = calculate_sma(df, gate_length)
    sma_col = f"SMA_{gate_length}"
    is_uptrend = df["Close"] > df[sma_col]

    # Step 4: Combine — block entries in downtrend, add RSI forced exit
    gated_signal = np.where(
        cmf_signal == 1,
        np.where(is_uptrend, 1, -1),
        -1,
    )

    # Apply RSI exit on top of CMF+SMA200 signal (converts any held long to -1)
    rsi_breakdown = (gated_signal == 1) & (df[rsi_col] < rsi_exit)
    df["Signal"] = np.where(rsi_breakdown, -1, gated_signal)

    # Re-forward-fill to maintain state
    df["Signal"] = pd.Series(df["Signal"]).replace(0, np.nan).ffill().fillna(0)
    return df


# ===========================================================================
# STRATEGY 2 — MA Bounce + RSI Timing (50d)
# Fix: MA Bounce WinRate 34.7% — add RSI<50 timing gate
# ===========================================================================

@register_strategy(
    name="MA Bounce+RSI Timing (50d)",
    dependencies=[],
    params={
        "ma_length":   get_bars_for_period("50d",  _TF, _MUL),
        "filter_bars": 3,
        "rsi_length":  get_bars_for_period("14d",  _TF, _MUL),
        "rsi_gate":    50,
        "gate_length": get_bars_for_period("200d", _TF, _MUL),
    },
)
def ma_bounce_rsi_timing_50(df, **kwargs):
    """50-SMA bounce entries filtered to genuine oversold conditions (RSI<50).

    Round 5 problem: MA Bounce (50d/3bar)+SMA200 had WinRate 34.7%.  Many
    losing trades were bounces that occurred when RSI was already elevated
    (60-70), meaning price was oscillating around a strong MA, not genuinely
    recovering from a pullback.  These high-RSI "bounces" typically fail
    because there is no real demand imbalance — price is just touching the MA
    during normal compression.

    Fix: require RSI(14) < 50 at the time of the bounce candle.  RSI<50
    means price has genuinely pulled back below its 14-bar midpoint before
    recovering to the 50-SMA.  This screens for:
    - Real pullbacks within an uptrend (where the bounce has follow-through)
    - NOT: overbought oscillation (where "bouncing" off the MA is fragile)

    Implementation: compute bounce events from ma_bounce_logic, then gate
    each entry event on RSI<50 AND price>SMA200.  Exits from ma_bounce_logic
    (3 consecutive closes below 50-SMA) are preserved unconditionally — we
    still exit fast when the bounce fails regardless of RSI state.

    Expected improvement vs Round 5 MA Bounce:
    - WinRate: 34.7% → 42-48% (filtering overbought bounces)
    - Trade count: reduced 20-30% (fewer but higher-quality entries)
    - Sharpe: +0.38 → +0.45+ (fewer losing trades, similar winning trade size)
    - MaxDD: stays below 22% (same exit logic)
    """
    ma_length   = kwargs["ma_length"]
    filter_bars = kwargs["filter_bars"]
    rsi_length  = kwargs["rsi_length"]
    rsi_gate    = kwargs["rsi_gate"]
    gate_length = kwargs["gate_length"]

    # Step 1: RSI and SMA200 (before ma_bounce_logic modifies df)
    df = calculate_rsi(df, rsi_length)
    rsi_col = f"RSI_{rsi_length}"
    df = calculate_sma(df, gate_length)
    sma200_col = f"SMA_{gate_length}"

    # Step 2: base bounce signal
    df = ma_bounce_logic(df, ma_length=ma_length, filter_bars=filter_bars)

    # Step 3: identify raw entry events (first bar where Signal transitions to 1)
    raw_entry = (df["Signal"].shift(1).fillna(0) != 1) & (df["Signal"] == 1)

    # Step 4: gate entries — bounce only valid when RSI<50 AND in uptrend
    in_uptrend   = df["Close"] > df[sma200_col]
    rsi_oversold = df[rsi_col] < rsi_gate
    valid_entry  = raw_entry & rsi_oversold & in_uptrend

    # Step 5: exits from ma_bounce_logic are unconditional
    exit_signal = df["Signal"] == -1

    # Rebuild signal from scratch: valid entries only, original exits preserved
    df["Signal"] = np.where(valid_entry, 1, np.where(exit_signal, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
    return df


# ===========================================================================
# STRATEGY 3 — Donchian Breakout (60d/20d) + MA Alignment Gate
# New hypothesis: longer window + trend alignment = fewer, higher-quality entries
# ===========================================================================

@register_strategy(
    name="Donchian Breakout (60d/20d)+MA Alignment",
    dependencies=[],
    params={
        "entry_period": get_bars_for_period("60d", _TF, _MUL),
        "exit_period":  get_bars_for_period("20d", _TF, _MUL),
        "ma_fast":      get_bars_for_period("10d", _TF, _MUL),
        "ma_slow":      get_bars_for_period("50d", _TF, _MUL),
    },
)
def donchian_60_20_ma_alignment(df, **kwargs):
    """60-bar Donchian breakout gated by 10/50 MA fast alignment.

    Insight from Round 2: Donchian (40/20) was a top-3 performer because
    40-bar new highs represent meaningful structural momentum.  The hypothesis:
    60-bar new highs (3-month highs) are even more selective, firing only
    when a stock is genuinely leading the market — not just bouncing within
    a range.

    MA alignment gate (fast_only):
    - Requires MA_fast (10) > MA_slow (50) AND Close > MA_slow
    - This is the "fast_only" condition from ma_confluence_logic
    - Gate ensures we only take breakouts when the underlying trend
      is already healthy (fast MA above slow MA), reducing false breakouts
      that occur at the start of a recovery when the trend is uncertain

    Entry architecture:
    - Donchian generates the breakout event (new 60-bar high)
    - MA alignment is a state filter (must be true on entry bar)
    - If alignment is false, the breakout is skipped (no entry)
    - Exits: 20-bar new low breakdown (unconditional, no MA gate on exit)

    Expected profile vs Donchian (40/20):
    - Fewer trades (60-bar window fires less frequently)
    - Higher per-trade expectancy (more selective entry)
    - Lower MaxDD (MA alignment prevents entries near market peaks)
    - Comparable or better OOS stability (longer window = more robust signal)
    """
    entry_period = kwargs["entry_period"]
    exit_period  = kwargs["exit_period"]
    ma_fast      = kwargs["ma_fast"]
    ma_slow      = kwargs["ma_slow"]

    # Step 1: Donchian breakout signal (60-bar entry, 20-bar exit)
    df = donchian_channel_breakout_logic(
        df,
        entry_period=entry_period,
        exit_period=exit_period,
    )
    donchian_signal = df["Signal"].copy()

    # Step 2: MA fast/slow alignment check (fast_only: Close > slow AND fast > slow)
    df["_maf"] = df["Close"].rolling(window=ma_fast).mean()
    df["_mas"] = df["Close"].rolling(window=ma_slow).mean()
    is_aligned = (df["Close"] > df["_mas"]) & (df["_maf"] > df["_mas"])

    # Step 3: Extract raw entry and exit events from Donchian signal
    raw_entry = (donchian_signal.shift(1).fillna(0) != 1) & (donchian_signal == 1)
    raw_exit  = (donchian_signal.shift(1).fillna(0) != -1) & (donchian_signal == -1)

    # Step 4: Gate entries on MA alignment; exits are unconditional
    valid_entry = raw_entry & is_aligned
    df["Signal"] = np.where(valid_entry, 1, np.where(raw_exit, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)

    # Cleanup temp columns
    df.drop(columns=["_maf", "_mas"], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 4 — OBV + MA Confluence Alignment Gate (20d/50d)
# Fix: Keltner Sharpe -0.02 — replace Keltner breakout with OBV volume-flow
# ===========================================================================

@register_strategy(
    name="OBV+MA Confluence Alignment (20/50)",
    dependencies=[],
    params={
        "obv_ma_length":   get_bars_for_period("20d", _TF, _MUL),
        "price_ma_length": get_bars_for_period("50d", _TF, _MUL),
        "ma_fast":         get_bars_for_period("10d", _TF, _MUL),
        "ma_medium":       get_bars_for_period("20d", _TF, _MUL),
        "ma_slow":         get_bars_for_period("50d", _TF, _MUL),
    },
)
def obv_ma_confluence_alignment(df, **kwargs):
    """OBV volume-flow entry gated by full MA stack alignment; dual exit.

    Round 5 problem: Keltner+MA Full Stack had Sharpe -0.02.  The Keltner
    upper-band breakout requirement (price must close above EMA+1.5×ATR)
    delayed entries because tech stocks in strong uptrends rarely close
    above the upper Keltner band — they ride the middle EMA.  The MA
    alignment gate was doing the right thing; the entry trigger was wrong.

    OBV (On-Balance Volume) as entry trigger instead:
    - OBV rising above its 20-bar MA means institutional accumulation
      is outpacing distribution on a volume-adjusted basis
    - OBV signals fire EARLIER than Keltner breakouts — they lead price
      rather than confirming an already-extended move
    - Combined with full MA stack alignment, the entry says:
      "Institutions are buying (OBV) into an already-trending stock (MAs)"
    - This combination should have higher win rate and lower MaxDD than
      Keltner (which enters on extended moves that often mean-revert)

    Dual exit (from obv_price_confirmation_logic):
    - OBV crosses below its MA AND price drops below 50-EMA simultaneously
    - This dual-confirm exit prevents premature exits during consolidation
    - ADDITIONAL exit: full bearish MA stack forms (all three MAs flip)

    Note: obv_price_confirmation_logic uses pandas-ta internally for OBV.
    Ensure pandas-ta is installed (it is in the standard environment).
    """
    obv_ma_length   = kwargs["obv_ma_length"]
    price_ma_length = kwargs["price_ma_length"]
    ma_fast         = kwargs["ma_fast"]
    ma_medium       = kwargs["ma_medium"]
    ma_slow         = kwargs["ma_slow"]

    # Step 1: OBV + price confirmation signal
    df = obv_price_confirmation_logic(
        df,
        obv_ma_length=obv_ma_length,
        price_ma_length=price_ma_length,
    )
    obv_signal = df["Signal"].copy()

    # Step 2: three-MA alignment state (full bullish stack)
    df["_maf"] = df["Close"].rolling(window=ma_fast).mean()
    df["_mam"] = df["Close"].rolling(window=ma_medium).mean()
    df["_mas"] = df["Close"].rolling(window=ma_slow).mean()

    is_full_stack = (
        (df["Close"] > df["_mas"]) &
        (df["_maf"]  > df["_mas"]) &
        (df["_mam"]  > df["_mas"])
    )
    is_bearish_stack = (
        (df["Close"] < df["_mas"]) &
        (df["_maf"]  < df["_mas"]) &
        (df["_mam"]  < df["_mas"])
    )

    # Step 3: entry events — OBV crosses up AND full MA stack aligned
    obv_entry   = (obv_signal.shift(1).fillna(0) != 1) & (obv_signal == 1)
    valid_entry = obv_entry & is_full_stack

    # Step 4: exit events — OBV breakdown OR bearish MA stack
    obv_exit  = (obv_signal.shift(1).fillna(0) != -1) & (obv_signal == -1)
    ma_exit   = (is_bearish_stack.shift(1).fillna(False) == False) & (is_bearish_stack == True)
    any_exit  = obv_exit | ma_exit

    df["Signal"] = np.where(valid_entry, 1, np.where(any_exit, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)

    df.drop(columns=["_maf", "_mam", "_mas"], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 5 — MA Confluence + ATR Trailing Stop (10/20/50)
# Fix: MA Confluence Full Stack MC Score 2 — faster exit cuts tail risk
# ===========================================================================

@register_strategy(
    name="MA Confluence+ATR Exit (10/20/50)",
    dependencies=[],
    params={
        "ma_fast":        get_bars_for_period("10d", _TF, _MUL),
        "ma_medium":      get_bars_for_period("20d", _TF, _MUL),
        "ma_slow":        get_bars_for_period("50d", _TF, _MUL),
        "atr_period":     get_bars_for_period("14d", _TF, _MUL),
        "atr_multiplier": 2.0,
    },
)
def ma_confluence_atr_exit(df, **kwargs):
    """MA Confluence full-stack entry with dual exit: medium-MA cross OR ATR stop.

    Round 5 problem: MA Confluence Full Stack dropped from MC Score 5 to MC
    Score 2 when history was extended to 1990.  Root cause: the bearish-stack
    exit (all three MAs must flip) is extremely slow — during a crash (2000-02,
    2008-09, 2022) all three MAs flip bearish 30-60 bars after the price peak,
    giving back 15-25% from the high before exiting.  The MC simulation then
    clusters these large-loss events into worst-case scenarios that exceed the
    backtest MaxDD by a significant margin.

    Two-exit hybrid design:
    - Exit A (MA): Close drops below MA_medium (20-bar SMA) — a faster signal
      than the full bearish stack.  On most trends, price crossing below the
      20-bar MA is a reliable early-reversal indicator.
    - Exit B (ATR): Dynamic trailing stop at (Close - atr_multiplier × ATR).
      Stop is initialized at entry and ratchets up with price, never moving
      down.  If Low crosses below the trailing stop, exit immediately.  This
      is a hard floor that prevents large reversals from developing — the
      exact weakness that collapsed the MC score.

    Why 2.0x ATR (tighter than Round 5's 2.5x which had RS(min)=-48):
    - 2.5x ATR on NVDA (ATR ≈ 5-8% of price) = 12.5-20% trailing stop
    - Too wide — allows drawdowns larger than the MA exit would trigger
    - 2.0x ATR = 10-16% trailing stop on NVDA — meaningful but not too tight
    - Tighter stops force exits sooner, improving MC score at the cost of
      occasionally stopping out of winning trades before the MA fires

    Expected improvement vs Round 5 MA Confluence Full Stack:
    - MC Score: 2 → 4 or 5 (smaller maximum drawdown in stress scenarios)
    - MaxDD: 35.3% → ~22-28% (ATR stop prevents full crash rides)
    - Sharpe: +0.43 → +0.48+ (better risk-adjusted return)
    - P&L: some compression (ATR exits some winners early) but OOS should
      remain strong because the improved exit is regime-agnostic
    """
    ma_fast        = kwargs["ma_fast"]
    ma_medium      = kwargs["ma_medium"]
    ma_slow        = kwargs["ma_slow"]
    atr_period     = kwargs["atr_period"]
    atr_multiplier = kwargs["atr_multiplier"]

    # Step 1: MA confluence components
    df["_maf"] = df["Close"].rolling(window=ma_fast).mean()
    df["_mam"] = df["Close"].rolling(window=ma_medium).mean()
    df["_mas"] = df["Close"].rolling(window=ma_slow).mean()

    is_bullish_stack = (
        (df["Close"] > df["_mas"]) &
        (df["_maf"]  > df["_mas"]) &
        (df["_mam"]  > df["_mas"])
    )
    entry_event = (is_bullish_stack.shift(1).fillna(False) == False) & (is_bullish_stack == True)

    # MA exit condition: close drops below medium MA
    ma_exit_cond = df["Close"] < df["_mam"]

    # Step 2: ATR for trailing stop
    df = calculate_atr(df, period=atr_period)

    # Step 3: stateful loop — entry on first-stack-bar, exit on ATR stop or MA cross
    n = len(df)
    signals      = [0] * n
    in_position  = False
    trailing_stop = 0.0

    for i in range(1, n):
        if pd.isna(df["ATR"].iloc[i]) or pd.isna(df["_mas"].iloc[i]):
            continue

        if in_position:
            # Check Exit A: ATR trailing stop hit (Low crosses stop)
            atr_hit = df["Low"].iloc[i] < trailing_stop
            # Check Exit B: Close drops below medium MA
            ma_hit  = ma_exit_cond.iloc[i]

            if atr_hit or ma_hit:
                signals[i]   = -1
                in_position  = False
                trailing_stop = 0.0
                continue

            # Update trailing stop (only moves up)
            new_stop     = df["Close"].iloc[i] - (df["ATR"].iloc[i] * atr_multiplier)
            trailing_stop = max(trailing_stop, new_stop)
            signals[i]   = 1
            continue

        # Check entry: first bar of full bullish stack
        if entry_event.iloc[i]:
            in_position   = True
            trailing_stop = df["Close"].iloc[i] - (df["ATR"].iloc[i] * atr_multiplier)
            signals[i]    = 1

    df["Signal"] = pd.Series(signals, index=df.index).replace(0, np.nan).ffill().fillna(0)
    df.drop(columns=["_maf", "_mam", "_mas"], errors="ignore", inplace=True)
    return df
