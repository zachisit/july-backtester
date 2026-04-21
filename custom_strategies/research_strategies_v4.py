# custom_strategies/research_strategies_v4.py
"""
Round 5 Research Strategies — five structurally distinct approaches
designed to be uncorrelated with the MA Confluence champion family.

Research context: MA Confluence (Full Stack + Fast Exit) dominate Rounds 1-4.
Both use price-based MA alignment for entry and MA cross for exit. To build a
robust portfolio we need strategies from DIFFERENT signal sources.

Five signal families tested here:

  1. CMF Momentum + SMA200 Gate (20/0.0/-0.05)
     Volume-flow signal — Chaikin Money Flow measures buying/selling pressure
     directly from price×volume. Completely uncorrelated with MA alignment.

  2. MACD + RSI + SMA200 Triple Gate (12/26/9/14)
     Three independent confirmations: price trend (SMA200) + momentum
     direction (MACD cross) + momentum strength (RSI > 50).

  3. ATR Trailing Stop (40/14/2.5x) + SMA200
     Dynamic exit mechanism. Entry = 40-bar high breakout. Exit = ATR-based
     trailing stop that rises with price. Protects profits more aggressively
     than fixed MA-cross exits used in MA Confluence family.

  4. MA Bounce (50d/3bar) + SMA200 Gate
     Mean reversion WITHIN a trend. Buys pullbacks to the 50-SMA while
     price is above SMA200. Opposite entry logic to Donchian (new highs) and
     MA Confluence (trend alignment) — enters on weakness, not strength.

  5. Keltner Breakout (20d/1.5x) + MA Full Stack Gate
     Volatility breakout gated by three-MA bullish alignment. Entry fires
     only when BOTH the Keltner upper band is broken AND the MAs are in
     full bullish order — double confirmation of trend strength.

All five use existing helpers/indicators.py functions. No new indicator
logic needed. All use get_bars_for_period for timeframe compatibility.

Target: find at least one new strategy that passes all 4 robustness checks
(WFA Pass, RollWFA 3/3, MC Score 5, RS(min) > -10) while being <0.70
correlated with MA Confluence Full Stack.
"""

import numpy as np
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import (
    chaikin_money_flow_logic,
    macd_rsi_filter_logic,
    atr_trailing_stop_with_trend_filter_logic,
    ma_bounce_logic,
    keltner_channel_breakout_logic,
    calculate_sma,
)
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ===========================================================================
# STRATEGY 1 — CMF Momentum + SMA200 Gate (20d)
# ===========================================================================

@register_strategy(
    name="CMF Momentum (20d) + SMA200 Gate",
    dependencies=[],
    params={
        "cmf_length":    get_bars_for_period("20d", _TF, _MUL),
        "buy_threshold": 0.0,
        "sell_threshold": -0.05,
        "gate_length":   get_bars_for_period("200d", _TF, _MUL),
    },
)
def cmf_sma200_momentum(df, **kwargs):
    """Chaikin Money Flow crossover gated by SMA-200 trend filter.

    Signal source rationale: CMF measures net buying/selling pressure as
    a fraction of total volume — (Close - Low - (High - Close)) / (High - Low)
    weighted by volume and summed over 20 bars. When CMF > 0, institutions
    are accumulating on the day's close relative to the range. When CMF < 0,
    they are distributing. This is entirely different from MA alignment
    (which is pure price structure) or ROC (which is pure price velocity).

    Why this configuration:
    - buy_threshold=0.0: CMF crossing zero means net accumulation just
      turned positive — the earliest signal of institutional buying interest.
    - sell_threshold=-0.05: requires CMF to drop to -5% net distribution
      before exiting, reducing whipsaws around the zero line.
    - SMA200 gate: CMF can cross above zero during bear market bounces.
      Requiring price > SMA200 ensures we only trade during confirmed
      bull regimes where CMF signals have highest hit rate.

    Expected behavior: moderate trade count (~400-700 on 6 symbols over 22
    years), relatively high win rate (CMF zero-cross in uptrend is a
    high-quality entry), Sharpe target +0.30 to +0.50.

    Correlation with MA Confluence: expected LOW. CMF fires on volume
    flow dynamics; MA Confluence fires on price-MA structural alignment.
    Two strategies can disagree on the same bar — that's the diversification.
    """
    # Step 1: CMF signal (entry on CMF cross above 0, exit on cross below -5%)
    df = chaikin_money_flow_logic(
        df,
        length=kwargs["cmf_length"],
        buy_threshold=kwargs["buy_threshold"],
        sell_threshold=kwargs["sell_threshold"],
    )
    cmf_signal = df["Signal"].copy()

    # Step 2: SMA200 trend gate — suppress longs in bear markets
    df = calculate_sma(df, length=kwargs["gate_length"])
    sma_col = f'SMA_{kwargs["gate_length"]}'
    is_uptrend = df["Close"] > df[sma_col]

    # Step 3: hold long only if CMF bullish AND in uptrend; exits unconditional
    df["Signal"] = np.where(
        cmf_signal == 1,
        np.where(is_uptrend, 1, -1),
        -1,
    )
    return df


# ===========================================================================
# STRATEGY 2 — MACD + RSI + SMA200 Triple Gate (12/26/9/14)
# ===========================================================================

@register_strategy(
    name="MACD + RSI + SMA200 Triple Gate (12/26/9/14)",
    dependencies=[],
    params={
        "macd_fast":   get_bars_for_period("12d", _TF, _MUL),
        "macd_slow":   get_bars_for_period("26d", _TF, _MUL),
        "macd_signal": get_bars_for_period("9d",  _TF, _MUL),
        "rsi_length":  get_bars_for_period("14d", _TF, _MUL),
        "gate_length": get_bars_for_period("200d", _TF, _MUL),
    },
)
def macd_rsi_sma200_triple(df, **kwargs):
    """MACD+RSI dual-signal entry with SMA-200 trend gate — three independent layers.

    Round 3 tested MACD crossover alone (198% P&L, Calmar 0.23) — poor
    results because a bare MACD takes long positions during ALL MACD
    crossovers regardless of regime, including bear market rallies.

    This strategy adds two independent filters on top of MACD:

    Layer 1 — SMA200 regime gate: no longs when price is below SMA200.
      Prevents holding through 2008, 2022-type bear markets.

    Layer 2 — RSI > 50 momentum confirmation (built into macd_rsi_filter_logic):
      Only enters on MACD crossovers where RSI is simultaneously above 50.
      This eliminates "weak MACD crosses" that occur during price stalls
      where RSI is depressed — the typical false-signal environment.

    Layer 3 — MACD structural direction (built into macd_rsi_filter_logic):
      Entry only on the actual MACD line crossing the signal line from below
      (a specific event, not just a state). This reduces signal frequency
      to only the most meaningful momentum shifts.

    Three-layer expectation:
    - Trade count: 200-400 (significantly fewer than bare MACD's ~1167)
    - WinRate: 50-60% (each entry confirmed from three angles)
    - Calmar: 0.40+ (bear market suppression via SMA200 cuts MaxDD)
    - RS(min): expected > -10 (no extended flat periods in bear markets)
    """
    # Step 1: MACD+RSI combined signal (RSI>50 gate built-in)
    df = macd_rsi_filter_logic(
        df,
        macd_fast=kwargs["macd_fast"],
        macd_slow=kwargs["macd_slow"],
        macd_signal=kwargs["macd_signal"],
        rsi_length=kwargs["rsi_length"],
    )
    macd_rsi_signal = df["Signal"].copy()

    # Step 2: SMA200 overlay — block all longs in confirmed downtrend
    df = calculate_sma(df, length=kwargs["gate_length"])
    sma_col = f'SMA_{kwargs["gate_length"]}'
    is_uptrend = df["Close"] > df[sma_col]

    # Step 3: combine — long only when MACD+RSI bullish AND in uptrend
    df["Signal"] = np.where(
        macd_rsi_signal == 1,
        np.where(is_uptrend, 1, -1),
        -1,
    )
    return df


# ===========================================================================
# STRATEGY 3 — ATR Trailing Stop (40/14/2.5x) + SMA200
# ===========================================================================

@register_strategy(
    name="ATR Trailing Stop (40d/2.5x) + SMA200",
    dependencies=[],
    params={
        "entry_period":   get_bars_for_period("40d",  _TF, _MUL),
        "atr_period":     get_bars_for_period("14d",  _TF, _MUL),
        "atr_multiplier": 2.5,
        "ma_length":      get_bars_for_period("200d", _TF, _MUL),
    },
)
def atr_trailing_stop_40_25x(df, **kwargs):
    """40-bar breakout entry with 2.5x ATR dynamic trailing stop and SMA200 gate.

    Note: This function uses atr_trailing_stop_with_trend_filter_logic which
    detects entry on the current bar's High and fills at the same bar's Close —
    an intrabar fill assumption. On daily bars this is optimistic vs. filling at
    the next open. Results serve as an upper bound on strategy performance;
    treat the OOS figures as directionally valid, not live-tradeable as-is.

    Why ATR trailing stop vs. fixed MA-cross exit:
    - MA Confluence exits on MA structural breakdown (slow, leaves large reversal)
    - ATR trailing stop rises CONTINUOUSLY as price rises, locking in gains
    - During a strong NVDA-style run: trailing stop follows price up, exits on
      the FIRST significant pull (ATR×2.5 below recent close) rather than waiting
      for all three MAs to flip bearish (which can be 30-60 bars later)
    - Expected Calmar improvement: MaxDD should be lower than MA Confluence because
      exits happen sooner on the downside leg

    Why 40-bar entry (same as Donchian champion):
    - 40-bar new high is a strong structural momentum signal
    - Proven to work on tech stocks in Round 2/3 (Donchian 40/20 was top 3)
    - Same entry quality, different exit mechanism — isolates the exit variable

    Why 2.5x ATR (tighter than default 3x):
    - 3x ATR is very wide on high-volatility tech stocks (NVDA ATR can be 5-10%)
    - 2.5x ATR reduces holding through whipsaws while still allowing normal
      intraday/weekly volatility to play out
    - If too tight, the strategy fires too frequently — round 5 results will tell

    SMA200 built into atr_trailing_stop_with_trend_filter_logic:
    - No additional code needed — it exits immediately when price crosses below SMA200
    - This handles 2008, 2022 regime changes at the structural level
    """
    return atr_trailing_stop_with_trend_filter_logic(
        df,
        entry_period=kwargs["entry_period"],
        atr_period=kwargs["atr_period"],
        atr_multiplier=kwargs["atr_multiplier"],
        ma_length=kwargs["ma_length"],
    )


# ===========================================================================
# STRATEGY 4 — MA Bounce (50d/3bar) + SMA200 Gate
# ===========================================================================

@register_strategy(
    name="MA Bounce (50d/3bar) + SMA200 Gate",
    dependencies=[],
    params={
        "ma_length":   get_bars_for_period("50d",  _TF, _MUL),
        "filter_bars": 3,
        "gate_length": get_bars_for_period("200d", _TF, _MUL),
    },
)
def ma_bounce_50_sma200(df, **kwargs):
    """50-SMA bounce entries (pullback within uptrend) gated by SMA-200.

    This is the OPPOSITE entry philosophy from Donchian and MA Confluence:
    - Donchian: buys when price makes a NEW HIGH (breakout strength)
    - MA Confluence: buys when all MAs first align bullishly (momentum quality)
    - MA Bounce: buys when price PULLS BACK to the 50-SMA and recovers
      (dip-buying within a confirmed trend)

    The 50-SMA is the canonical intermediate-term support level for tech stocks.
    NVDA, AAPL, MSFT, and AMZN all use the 50-SMA as support during their
    major bull runs — institutional traders buy at this level deliberately,
    creating a self-fulfilling bounce. The strategy captures this pattern.

    Mechanism (from ma_bounce_logic):
    - Entry: bar's Low touches or crosses below 50-SMA AND Close is back above
      the 50-SMA AND no confirmed downtrend (defined as ≤ filter_bars consecutive
      closes below 50-SMA)
    - Exit: filter_bars (3) consecutive closes below 50-SMA confirms downtrend

    Why filter_bars=3 instead of default 2:
    - 2 bars can trigger on normal intra-week volatility
    - 3 consecutive closes below the 50-SMA is a more meaningful structural break
    - Fewer false exits → better win rate on stocks with volatile intraday ranges

    SMA200 gate rationale:
    - 50-SMA bounces in bear markets (price < SMA200) are "sucker rallies"
    - Requiring price > SMA200 ensures we only buy pullbacks in healthy uptrends
    - Exits (3 closes below 50-SMA) always fire unconditionally — no gating on exit

    Expected profile: higher win rate than breakout strategies (~60-70%), lower
    per-trade expectancy (smaller gains per trade), moderate trade count.
    Structurally uncorrelated with MA Confluence (different entry logic entirely).
    """
    # Step 1: 50-SMA bounce signal
    df = ma_bounce_logic(df, ma_length=kwargs["ma_length"], filter_bars=kwargs["filter_bars"])
    bounce_signal = df["Signal"].copy()

    # Step 2: SMA200 trend gate — only allow bounce entries in confirmed uptrend
    df = calculate_sma(df, length=kwargs["gate_length"])
    sma_col = f'SMA_{kwargs["gate_length"]}'
    is_uptrend = df["Close"] > df[sma_col]

    # Step 3: gate entries on uptrend; exits always fire (bounce_signal==-1 maps to -1)
    df["Signal"] = np.where(
        bounce_signal == 1,
        np.where(is_uptrend, 1, -1),
        -1,
    )
    return df


# ===========================================================================
# STRATEGY 5 — Keltner Breakout (20d/1.5x) + MA Full Stack Gate
# ===========================================================================

@register_strategy(
    name="Keltner (20d/1.5x) + MA Full Stack Gate",
    dependencies=[],
    params={
        "ema_length":     get_bars_for_period("20d", _TF, _MUL),
        "atr_length":     get_bars_for_period("14d", _TF, _MUL),
        "atr_multiplier": 1.5,
        "ma_fast":        get_bars_for_period("10d", _TF, _MUL),
        "ma_medium":      get_bars_for_period("20d", _TF, _MUL),
        "ma_slow":        get_bars_for_period("50d", _TF, _MUL),
    },
)
def keltner_ma_full_stack(df, **kwargs):
    """Keltner channel breakout entry gated by three-MA bullish alignment.

    Insight from Rounds 2-3: Two best strategy families are MA Confluence
    (pure MA alignment signal) and Donchian (pure breakout signal). Both
    succeed independently — but do they succeed TOGETHER as a filter pair?

    This strategy tests the hypothesis: Keltner breakouts that occur WHILE
    the 10/20/50 MA stack is already bullish are far more likely to follow
    through than breakouts that occur in choppy or misaligned markets.

    The combination creates a double-confirmation entry:
    1. Keltner upper-band breakout: price closes above EMA + 1.5×ATR
       → immediate evidence of an EXPANSION in momentum (volatility breakout)
    2. Full MA stack alignment: MA_10 > MA_50 AND MA_20 > MA_50
       → structural evidence that the TREND is healthy before the breakout

    Without the MA filter: Keltner breakouts happen frequently and include
    many "false starts" where volatility briefly spikes but the underlying
    trend is not supportive. Round 2 Keltner (1.5x) without filter got
    Sharpe +0.17, Calmar 0.44 — decent but not great.

    With MA filter: we expect significantly fewer but higher-quality entries,
    improving win rate and per-trade expectancy at the cost of trade count.

    Exit logic: Keltner signal goes -1 when price closes below the EMA
    (the middle of the channel), which is a measured reversal signal.
    If the MA stack breaks down (bearish alignment), the Keltner signal
    will already have exited or will exit on next close below EMA.

    Note: MA alignment check is computed inline (not via ma_confluence_logic)
    because we only need the CURRENT STATE (bullish/not), not the first-bar
    event that ma_confluence_logic generates. We check both fast>slow and
    medium>slow, matching the MA Confluence "full stack" definition exactly.
    """
    # Step 1: Keltner channel breakout signal
    df = keltner_channel_breakout_logic(
        df,
        ema_length=kwargs["ema_length"],
        atr_length=kwargs["atr_length"],
        atr_multiplier=kwargs["atr_multiplier"],
    )
    keltner_signal = df["Signal"].copy()

    # Step 2: compute three-MA bullish alignment (same definition as MA Confluence)
    ma_fast_col = f'KC_MA_fast_{kwargs["ma_fast"]}'
    ma_mid_col  = f'KC_MA_mid_{kwargs["ma_medium"]}'
    ma_slow_col = f'KC_MA_slow_{kwargs["ma_slow"]}'
    df[ma_fast_col] = df["Close"].rolling(window=kwargs["ma_fast"]).mean()
    df[ma_mid_col]  = df["Close"].rolling(window=kwargs["ma_medium"]).mean()
    df[ma_slow_col] = df["Close"].rolling(window=kwargs["ma_slow"]).mean()

    is_ma_aligned = (
        (df[ma_fast_col] > df[ma_slow_col]) &
        (df[ma_mid_col]  > df[ma_slow_col])
    )

    # Step 3: only hold Keltner long when MA stack is bullish; exits unconditional
    df["Signal"] = np.where(
        keltner_signal == 1,
        np.where(is_ma_aligned, 1, -1),
        -1,
    )
    return df
