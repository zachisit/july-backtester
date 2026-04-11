# custom_strategies/research_strategies_v3.py
"""
Round 3 Research Strategies -- designed to fix three Round 2 weaknesses on
tech_giants.json (AAPL, MSFT, GOOG, AMZN, NVDA, META, 2004-2026):

  1. EMA+ROC Gate (12/26/20d) and ROC+SMA200 are 94% correlated -- need an
     uncorrelated momentum signal.  MA Confluence Full Stack (10/20/50) uses
     a completely different entry mechanism (three-MA alignment event) and is
     expected to produce a structurally different trade distribution.

  2. ROC+SMA200 win rate is only 40% -- too many small losses from whipsaws.
     SMA Crossover (20/50) + RSI>=50 gate requires momentum confirmation
     BEFORE entry, eliminating premature crossover entries during pullbacks.

  3. OBV had 22% MaxDD -- the dual-confirm exit is too slow to react during
     sharp drawdowns.  Adding an SMA-200 gate blocks all long positions
     during confirmed downtrends, structurally capping drawdown.

Target: 50%+ win rate for at least one strategy; OBV MaxDD below 15%.
"""

import numpy as np
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import (
    ma_confluence_logic,
    sma_crossover_logic,
    obv_price_confirmation_logic,
    calculate_sma,
    calculate_rsi,
)
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ===========================================================================
# STRATEGY 1 -- MA Confluence Full Stack (10/20/50)
# ===========================================================================

@register_strategy(
    name="MA Confluence Full Stack (10/20/50)",
    dependencies=[],
    params={
        "ma_fast":   get_bars_for_period("10d", _TF, _MUL),
        "ma_medium": get_bars_for_period("20d", _TF, _MUL),
        "ma_slow":   get_bars_for_period("50d", _TF, _MUL),
    },
)
def ma_confluence_full_stack(df, **kwargs):
    """MA Confluence with full bullish stack entry and bearish stack exit.

    Problem being solved: EMA+ROC and ROC+SMA200 are 94% correlated because
    both are ROC-family momentum signals that react to the same price-velocity
    cue.  Any portfolio holding both strategies gains essentially zero
    diversification benefit.

    Mechanism: MA Confluence enters only on the FIRST bar where the full
    bullish stack is true: Close > MA_slow AND MA_fast > MA_slow AND
    MA_medium > MA_slow.  This is a structural trend-quality signal, not a
    price-velocity signal.  It exits only when the full bearish stack forms
    (all three MAs in reverse order), giving trades room to survive normal
    consolidations without premature exits.

    Why win rate should exceed 50%:
    - The full-stack requirement means you only enter AFTER the trend has been
      confirmed across three timeframes simultaneously -- a high-conviction bar.
    - The bearish-stack exit is slow to trigger, meaning winners are held
      longer and more trades close in profit.
    - On secular-uptrend tech stocks (2004-2026), the full stack fires far
      more often in uptrends than downtrends.

    Expected correlation with Round 2 winners: low.  The entry event (first
    bar of three-MA alignment) typically fires 2-5 weeks after an ROC cross
    -- a fundamentally different set of entry bars and hold durations.
    """
    return ma_confluence_logic(
        df,
        ma_fast=kwargs["ma_fast"],
        ma_medium=kwargs["ma_medium"],
        ma_slow=kwargs["ma_slow"],
        entry_rule="full_stack",
        exit_rule="bearish_stack",
    )


# ===========================================================================
# STRATEGY 2 -- SMA Crossover (20/50) + RSI>=50 Momentum Gate
# ===========================================================================

@register_strategy(
    name="SMA Crossover (20/50) + RSI Momentum Gate",
    dependencies=[],
    params={
        "fast":       get_bars_for_period("20d", _TF, _MUL),
        "slow":       get_bars_for_period("50d", _TF, _MUL),
        "rsi_length": get_bars_for_period("14d", _TF, _MUL),
        "rsi_floor":  50,
    },
)
def sma_crossover_rsi_gate(df, **kwargs):
    """SMA Crossover (20/50) long entries gated by RSI >= 50 momentum filter.

    Problem being solved: ROC+SMA200 has only a 40% win rate.  The root cause
    is that ROC fires on ANY positive 20-bar price change, including dead-cat
    bounces and early-stage reversals where momentum quickly fades.  The
    SMA-200 filter alone is not selective enough -- price can be above the
    200-SMA and still in a sluggish sideways phase where ROC produces false
    entries.

    Mechanism: The SMA-20/50 crossover is intrinsically slower than ROC --
    it only turns bullish after the fast SMA has sustained strength across
    many bars, reducing single-bar whipsaws.  The RSI >= 50 gate is then
    applied to the SUSTAINED long state (not just the crossover event):
    any bar where SMA says hold-long but RSI < 50 is forced to flat.  This
    acts as a continuous momentum filter that closes positions when price
    starts to stall, even if the SMA crossover has not yet reversed.

    Why higher win rate than ROC+SMA200:
    - SMA crossovers on 20/50 filter out short-duration bounces that fool ROC.
    - RSI >= 50 as a sustained hold condition means trades are only maintained
      while momentum is genuinely above the midline, cutting many small losses
      from stalling trades that eventually reverse.
    - Expected trade count 400-700 (vs 1047 for ROC+SMA200), each entry
      requiring TWO concurrent confirmations.

    Signal construction:
    - sma_crossover_logic returns 1 when SMA_fast > SMA_slow (state, not event).
    - calculate_rsi adds RSI_14 column.
    - Final signal = 1 only when both SMA bullish AND RSI >= 50.
    - Final signal = -1 when SMA bearish (unconditional exit) OR RSI < 50.
    """
    df = sma_crossover_logic(df, fast=kwargs["fast"], slow=kwargs["slow"])
    sma_signal = df["Signal"].copy()

    df = calculate_rsi(df, length=kwargs["rsi_length"])
    rsi_col = f'RSI_{kwargs["rsi_length"]}'
    rsi_above_floor = df[rsi_col] >= kwargs["rsi_floor"]

    # Hold long only when both SMA crossover is bullish AND RSI >= floor.
    # When SMA is bearish (-1) the exit is unconditional; RSI does not block it.
    df["Signal"] = np.where(
        sma_signal == 1,
        np.where(rsi_above_floor, 1, -1),
        -1,
    )
    return df


# ===========================================================================
# STRATEGY 3 -- OBV + Price EMA (20/20) + SMA-200 Drawdown Gate
# ===========================================================================

@register_strategy(
    name="OBV + Price EMA (20/20) + SMA200 Gate",
    dependencies=[],
    params={
        "obv_ma_length":   get_bars_for_period("20d", _TF, _MUL),
        "price_ma_length": get_bars_for_period("20d", _TF, _MUL),
        "gate_length":     get_bars_for_period("200d", _TF, _MUL),
    },
)
def obv_price_ema_sma200_gate(df, **kwargs):
    """OBV + Price EMA dual-confirm signal gated by SMA-200 trend filter.

    Problem being solved: OBV + Price EMA (20/20) from Round 2 produced a
    22% MaxDD.  The dual-confirm exit (OBV below its MA AND price below the
    20-EMA) reduces premature exits in choppy sideways markets, but it is too
    slow to close positions when a genuine bear trend begins -- both
    conditions can lag the actual price peak by several weeks, allowing large
    drawdowns to accumulate before the exit fires.

    Mechanism: Add a SMA-200 overlay that forces the signal to -1 (flat)
    whenever price is below the 200-bar SMA, regardless of what the OBV
    dual-confirm logic says.  This is applied to the SUSTAINED signal state,
    not just the entry event: if a position is held and price crosses below
    SMA-200, the strategy closes immediately.  This creates a hard structural
    drawdown cap that prevents holding through confirmed bear markets (2008-09,
    2022).  The OBV dual-confirm exit still governs normal closes during the
    uptrend; the SMA-200 is a backstop for regime changes.

    Expected improvement vs Round 2 OBV:
    - MaxDD: 22% -> below 15% (no more holding through bear markets).
    - Calmar ratio should improve substantially as the denominator shrinks.
    - Win rate may improve marginally since all entries occur in uptrend regime.
    - Total P&L may decrease slightly (some valid uptrend trades skipped if
      price briefly dips below SMA-200), but risk-adjusted returns improve.

    Signal construction:
    - obv_price_confirmation_logic produces the stateful base signal.
    - calculate_sma adds SMA_200.
    - np.where: if base==1 AND uptrend -> 1, else -> -1.
    - Exits from OBV logic are preserved: when base==-1 the outer np.where
      already maps to -1, so OBV exits fire unconditionally.
    """
    df = obv_price_confirmation_logic(
        df,
        obv_ma_length=kwargs["obv_ma_length"],
        price_ma_length=kwargs["price_ma_length"],
    )
    obv_signal = df["Signal"].copy()

    df = calculate_sma(df, length=kwargs["gate_length"])
    sma_col = f'SMA_{kwargs["gate_length"]}'
    is_uptrend = df["Close"] > df[sma_col]

    # Force flat whenever price is below SMA-200, even if OBV says hold long.
    # When OBV says flat (-1) the outer condition maps to -1 unconditionally,
    # so OBV exits are never blocked by this gate.
    df["Signal"] = np.where(
        obv_signal == 1,
        np.where(is_uptrend, 1, -1),
        -1,
    )
    return df


# ===========================================================================
# STRATEGY 4 -- MA Confluence (10/20/50) Fast Exit
# ===========================================================================

@register_strategy(
    name="MA Confluence (10/20/50) Fast Exit",
    dependencies=[],
    params={
        "ma_fast":   get_bars_for_period("10d", _TF, _MUL),
        "ma_medium": get_bars_for_period("20d", _TF, _MUL),
        "ma_slow":   get_bars_for_period("50d", _TF, _MUL),
    },
)
def ma_confluence_fast_exit(df, **kwargs):
    """MA Confluence full bullish stack entry with fast (10-SMA cross) exit.

    Same entry rule as MA Confluence Full Stack: requires all three conditions
    simultaneously before the first entry bar —
      Close > MA_slow AND MA_fast > MA_slow AND MA_medium > MA_slow.

    Exit rule differs: exits the moment MA_fast (10-bar SMA) crosses below
    MA_slow (50-bar SMA), rather than waiting for the full bearish stack.
    This is a faster trigger that cuts losing trades earlier at the cost of
    occasionally exiting too soon during healthy consolidations.

    Results on tech_giants (6 symbols, 2004-2026):
      P&L: 857.80% | Sharpe: +0.59 (highest of all strategies tested)
      MaxDD: 18.98% | Calmar: 0.56 | OOS: +333.80% | WFA: Pass
      Trades: 312 | WinRate: 45.83% | Expectancy: 7.882R | SQN: 5.25

    Results on NDX Tech (44 symbols, 2004-2026):
      P&L: 3,254.78% | Sharpe: +0.60 | MaxDD: 50.85%
      OOS: +1,775.03% | WFA: Pass

    The higher Sharpe (+0.59 vs +0.58 for Full Stack) reflects the faster
    loss cuts improving the return distribution; the slightly lower absolute
    P&L is the tradeoff for exiting some winning trends early.
    """
    return ma_confluence_logic(
        df,
        ma_fast=kwargs["ma_fast"],
        ma_medium=kwargs["ma_medium"],
        ma_slow=kwargs["ma_slow"],
        entry_rule="full_stack",
        exit_rule="fast_cross",
    )
