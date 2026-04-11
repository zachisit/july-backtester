# custom_strategies/round7_strategies.py
"""
Round 7 Research Strategies — designed from first principles, not as patches.

Round 6 taught three lessons:
  - Don't RSI-gate bounce strategies (destroys timing advantage)
  - ATR trailing stops need 3.0x+ on high-vol tech names
  - 6-symbol RS(min) is noisy; only trust 44-symbol results

Five genuinely new approaches tested here:

  1. CMF (10d) + SMA200 Gate
     Faster 10-bar CMF reduces the lag that caused 29% MaxDD in Round 5.
     Hypothesis: shorter window = faster detection of distribution phases.

  2. Donchian (40/20) + RSI Momentum Gate
     The R2 champion with one addition: require RSI>50 at breakout time.
     RSI>50 means the stock has momentum above its midline — reduces
     false breakouts from oversold bounces that quickly reverse.

  3. EMA Crossover (8/21) + CMF Gate
     EMA 8/21 is a fast structural signal. CMF>0 as a sustained hold
     condition (not just entry) means we exit any EMA-long when volume
     flow turns negative — a volume-based trailing exit that adapts to
     distribution phases faster than a second MA.

  4. ROC (20d) + MA Confluence State Gate
     Rate of Change as primary direction signal, gated by MA full-stack
     alignment. ROC>0 fires frequently; only acting when the MA stack
     is also bullish should cut false signals dramatically.

  5. SMA Crossover (20/50) + OBV Confirmation
     The classic golden cross (20-SMA crossing above 50-SMA) gated by
     OBV being above its own 20-bar MA. Combines a slow structural signal
     with a volume-flow confirmation — two independent signals that both
     measure trend quality from different angles.
"""

import numpy as np
import pandas as pd
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import (
    chaikin_money_flow_logic,
    calculate_sma,
    donchian_channel_breakout_logic,
    calculate_rsi,
    ema_crossover_unfiltered_logic,
    roc_logic,
    sma_crossover_logic,
    obv_price_confirmation_logic,
)
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ===========================================================================
# STRATEGY 1 — CMF (10d) + SMA200 Gate
# Hypothesis: faster CMF = less lag = lower MaxDD
# ===========================================================================

@register_strategy(
    name="CMF (10d) + SMA200 Gate",
    dependencies=[],
    params={
        "cmf_length":     get_bars_for_period("10d",  _TF, _MUL),
        "buy_threshold":  0.05,
        "sell_threshold": -0.05,
        "gate_length":    get_bars_for_period("200d", _TF, _MUL),
    },
)
def cmf_10d_sma200(df, **kwargs):
    """Chaikin Money Flow with 10-bar window (half the Round 5 CMF length).

    Round 5 problem: CMF (20d)+SMA200 had MaxDD 29.4% and RS(min)=-16.59
    because the 20-bar sum is slow to respond when distribution begins.
    A 10-bar CMF is twice as responsive — it detects volume-flow reversals
    earlier, allowing exits before large drawdowns develop.

    Trade-off: 10-bar CMF is noisier (more whipsaws around the thresholds).
    The sell_threshold=-0.05 is kept at the Round 5 level to avoid over-
    triggering on noise — we want faster detection of REAL distribution,
    not micro-fluctuations around zero. The buy_threshold=0.05 ensures
    we enter only on confirmed net accumulation, not marginal crossovers.

    SMA200 gate is unchanged — prevents any entries during bear regimes.
    The CMF 10d may also implicitly detect regime changes faster because
    volume distribution periods show up in the shorter window sooner.
    """
    df = chaikin_money_flow_logic(
        df,
        length=kwargs["cmf_length"],
        buy_threshold=kwargs["buy_threshold"],
        sell_threshold=kwargs["sell_threshold"],
    )
    cmf_signal = df["Signal"].copy()

    df = calculate_sma(df, kwargs["gate_length"])
    sma_col    = f'SMA_{kwargs["gate_length"]}'
    is_uptrend = df["Close"] > df[sma_col]

    df["Signal"] = np.where(
        cmf_signal == 1,
        np.where(is_uptrend, 1, -1),
        -1,
    )
    return df


# ===========================================================================
# STRATEGY 2 — Donchian (40/20) + RSI Momentum Gate
# Hypothesis: require RSI>50 at breakout to reduce false breakouts
# ===========================================================================

@register_strategy(
    name="Donchian (40/20) + RSI Momentum Gate",
    dependencies=[],
    params={
        "entry_period": get_bars_for_period("40d", _TF, _MUL),
        "exit_period":  get_bars_for_period("20d", _TF, _MUL),
        "rsi_length":   get_bars_for_period("14d", _TF, _MUL),
        "rsi_floor":    50,
    },
)
def donchian_40_20_rsi_gate(df, **kwargs):
    """Donchian (40/20) — the Round 2 champion — gated by RSI>50 at breakout.

    Donchian (40/20) is the second-best strategy on 44 symbols (48,426% P&L,
    OOS +41,665%). Its only weakness: some breakouts occur when RSI is below
    50, meaning the stock just made a 40-bar high but momentum is already
    fading — a classic breakout-failure setup.

    RSI>50 gate at entry:
    - RSI>50 means price is above its 14-bar average gain/loss midpoint
    - Combined with a 40-bar new high, this confirms BOTH structural
      momentum (new high) AND oscillator momentum (RSI above midline)
    - Expected: fewer but higher-conviction entries; higher win rate

    Exit logic: unchanged from Donchian (40/20) — 20-bar new low.
    The RSI gate is ONLY applied to entries, never to exits. If we're
    long and RSI drops below 50, we stay in until the 20-bar new low
    forms (the structural exit). This avoids the MA Bounce+RSI mistake
    where RSI gating was applied to exits and destroyed the strategy.

    Note: RSI gate is applied to the ENTRY EVENT (first bar of Signal==1),
    not to the sustained hold state. Once in a trade, RSI is ignored.
    """
    entry_period = kwargs["entry_period"]
    exit_period  = kwargs["exit_period"]
    rsi_length   = kwargs["rsi_length"]
    rsi_floor    = kwargs["rsi_floor"]

    # Step 1: Donchian signal
    df = donchian_channel_breakout_logic(
        df,
        entry_period=entry_period,
        exit_period=exit_period,
    )
    donchian_signal = df["Signal"].copy()

    # Step 2: RSI at entry time
    df = calculate_rsi(df, rsi_length)
    rsi_col = f"RSI_{rsi_length}"

    # Step 3: identify raw entry and exit events
    raw_entry = (donchian_signal.shift(1).fillna(0) != 1) & (donchian_signal == 1)
    raw_exit  = (donchian_signal.shift(1).fillna(0) != -1) & (donchian_signal == -1)

    # Step 4: gate entries on RSI>50; exits are always unconditional
    rsi_above_floor = df[rsi_col] >= rsi_floor
    valid_entry     = raw_entry & rsi_above_floor

    df["Signal"] = np.where(valid_entry, 1, np.where(raw_exit, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
    return df


# ===========================================================================
# STRATEGY 3 — EMA Crossover (8/21) + CMF Sustained Hold Gate
# Hypothesis: use CMF>0 as a continuous filter on EMA long positions
# ===========================================================================

@register_strategy(
    name="EMA Crossover (8/21) + CMF Hold Gate",
    dependencies=[],
    params={
        "fast_ema":      get_bars_for_period("8d",  _TF, _MUL),
        "slow_ema":      get_bars_for_period("21d", _TF, _MUL),
        "cmf_length":    get_bars_for_period("20d", _TF, _MUL),
    },
)
def ema_8_21_cmf_hold_gate(df, **kwargs):
    """EMA 8/21 crossover with CMF>0 sustained hold condition.

    EMA Crossover (8/21)+ROC Gate was tested in Round 3 — the 8/21 pair
    produced 458% P&L, Sharpe +0.36 on 6 symbols.  The ROC gate worked
    reasonably well, but ROC and EMA are both price-based signals (high
    correlation).

    This strategy replaces the ROC hold gate with CMF>0:
    - EMA crossover (8>21) triggers the entry (structural signal)
    - CMF>0 (net accumulation) must be maintained for position to be held
    - Any bar where EMA says hold BUT CMF<0 → close the position
    - This is a VOLUME-BASED exit on top of a PRICE-BASED entry

    Why CMF as a sustained hold condition (not just entry):
    - CMF can turn negative while EMA is still crossed (distribution begins)
    - Using CMF as continuous filter exits positions during distribution
      phases BEFORE the EMA crossover reverses — faster and more responsive
    - Combines two completely uncorrelated signal sources in the exit

    This is NOT the same as the failed CMF+RSI gate (Round 6):
    - CMF+RSI tried to fix CMF's exits with RSI — added complexity, made it worse
    - Here, CMF is being used to improve EMA's exits — net new signal source
    - The entry is still EMA (clean structural signal); CMF just filters holds
    """
    fast_ema   = kwargs["fast_ema"]
    slow_ema   = kwargs["slow_ema"]
    cmf_length = kwargs["cmf_length"]

    # Step 1: EMA crossover signal (1 when fast > slow, -1 when fast < slow)
    df = ema_crossover_unfiltered_logic(df, fast_ema=fast_ema, slow_ema=slow_ema)
    ema_signal = df["Signal"].copy()

    # Step 2: compute CMF as a continuous indicator (not as a signal)
    mfm = ((df["Close"] - df["Low"]) - (df["High"] - df["Close"])) / (df["High"] - df["Low"])
    mfm = mfm.fillna(0)
    mfv = mfm * df["Volume"]
    df["_CMF"] = mfv.rolling(cmf_length).sum() / df["Volume"].rolling(cmf_length).sum()

    # Step 3: hold long only when EMA bullish AND CMF > 0
    cmf_positive = df["_CMF"] > 0

    df["Signal"] = np.where(
        ema_signal == 1,
        np.where(cmf_positive, 1, -1),
        -1,
    )

    df.drop(columns=["_CMF"], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 4 — ROC (20d) + MA Full Stack State Gate
# Hypothesis: ROC fires frequently; MA alignment cuts false signals
# ===========================================================================

@register_strategy(
    name="ROC (20d) + MA Full Stack Gate",
    dependencies=[],
    params={
        "roc_length": get_bars_for_period("20d", _TF, _MUL),
        "roc_threshold": 0,
        "ma_fast":    get_bars_for_period("10d", _TF, _MUL),
        "ma_medium":  get_bars_for_period("20d", _TF, _MUL),
        "ma_slow":    get_bars_for_period("50d", _TF, _MUL),
    },
)
def roc_20d_ma_full_stack(df, **kwargs):
    """ROC (20d) momentum gated by MA 10/20/50 full bullish stack state.

    ROC Momentum (20d) was the R1 winner on tech_giants (554% P&L) but with
    negative Sharpe on AAPL alone — too many whipsaws.  The SMA200 filter
    in Round 2 helped (433% P&L, Sharpe +0.37) but the correlation with
    EMA+ROC was r=0.94 (same signal family).

    This strategy uses the MA FULL STACK (10/20/50 all aligned) as the gate
    instead of just SMA200.  The full stack is a MUCH stricter requirement:
    - All three MAs in order means trend quality is confirmed at 3 timeframes
    - ROC>0 on top means price velocity is positive in the short term
    - Together: "strong trend AND accelerating" — the highest-conviction setup

    Entry: ROC crosses from negative to positive WHILE MA stack is bullish.
    Exit: ROC turns negative (ROC<0) OR MA stack turns bearish (any MA out of order).
    This dual exit prevents riding out the full MA breakdown — if ROC turns
    negative first, we exit before the MA breakdown confirms, which should
    cut losses faster than a pure MA-based exit.

    Key difference from EMA+ROC Gate (R2): that strategy used EMA crossover
    as the structural signal and ROC as the confirmation. Here ROC IS the
    primary signal and the MA full stack is the regime filter — a structural
    inversion that should produce very different entry timing.
    """
    roc_length    = kwargs["roc_length"]
    roc_threshold = kwargs["roc_threshold"]
    ma_fast       = kwargs["ma_fast"]
    ma_medium     = kwargs["ma_medium"]
    ma_slow       = kwargs["ma_slow"]

    # Step 1: ROC signal (1 when ROC>0, -1 when ROC<0)
    df = roc_logic(df, length=roc_length, threshold=roc_threshold)
    roc_signal = df["Signal"].copy()

    # Step 2: compute three-MA state
    df["_maf"] = df["Close"].rolling(window=ma_fast).mean()
    df["_mam"] = df["Close"].rolling(window=ma_medium).mean()
    df["_mas"] = df["Close"].rolling(window=ma_slow).mean()

    is_full_stack = (
        (df["Close"] > df["_mas"]) &
        (df["_maf"]  > df["_mas"]) &
        (df["_mam"]  > df["_mas"])
    )

    # Step 3: long only when BOTH ROC bullish AND MA full stack aligned
    df["Signal"] = np.where(
        roc_signal == 1,
        np.where(is_full_stack, 1, -1),
        -1,
    )

    df.drop(columns=["_maf", "_mam", "_mas"], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 5 — SMA Crossover (20/50) + OBV Confirmation
# Hypothesis: slow structural signal + volume confirmation = robust entries
# ===========================================================================

@register_strategy(
    name="SMA Crossover (20/50) + OBV Confirmation",
    dependencies=[],
    params={
        "fast":           get_bars_for_period("20d", _TF, _MUL),
        "slow":           get_bars_for_period("50d", _TF, _MUL),
        "obv_ma_length":  get_bars_for_period("20d", _TF, _MUL),
        "price_ma_length": get_bars_for_period("20d", _TF, _MUL),
    },
)
def sma_crossover_20_50_obv_confirm(df, **kwargs):
    """SMA 20/50 golden-cross state with OBV dual-confirm held during position.

    Classic 20/50 SMA golden cross (fast SMA crossing above slow SMA) is a
    well-known, simple trend signal.  Without any filter it fires on every
    EMA alignment, including early recoveries where volume doesn't support
    the move.  OBV being above its MA means institutions are net buying —
    the volume flow supports the price-based signal.

    Two-layer gate:
    - Layer 1 (entry): SMA 20 crosses above SMA 50 (golden cross state)
    - Layer 2 (sustained hold): OBV must be above its 20-bar MA at all times
      during the hold. If OBV drops below its MA, close the position even
      if the SMA crossover hasn't reversed yet.

    This is a volume-based trailing exit (same concept as EMA+CMF but using
    OBV instead of CMF). OBV is computed from raw price×volume data, while
    CMF uses price position within the bar range — different angle on volume.

    `obv_price_confirmation_logic` provides the OBV state signal directly.
    By using it as a hold condition (not an entry), we get the volume floor
    without needing OBV to independently trigger entries.

    Expected profile: fewer trades than plain SMA crossover (must have both
    SMA crossed AND OBV bullish). Higher win rate. Lower MaxDD because OBV
    failure triggers exit before the SMA death cross forms.
    """
    fast          = kwargs["fast"]
    slow          = kwargs["slow"]
    obv_ma_length = kwargs["obv_ma_length"]
    price_ma_len  = kwargs["price_ma_length"]

    # Step 1: SMA crossover state signal (1 when fast > slow)
    df = sma_crossover_logic(df, fast=fast, slow=slow)
    sma_signal = df["Signal"].copy()

    # Step 2: OBV + price dual-confirm signal (1 when OBV above its MA AND price above EMA)
    df = obv_price_confirmation_logic(
        df,
        obv_ma_length=obv_ma_length,
        price_ma_length=price_ma_len,
    )
    obv_state = df["Signal"].copy()

    # Step 3: hold long only when BOTH SMA crossed bullish AND OBV bullish
    # Exit when either signal turns negative
    df["Signal"] = np.where(
        sma_signal == 1,
        np.where(obv_state == 1, 1, -1),
        -1,
    )
    return df
