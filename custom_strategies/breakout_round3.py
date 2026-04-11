# custom_strategies/breakout_round3.py
"""Round 3 Breakout strategy plugins.

Three variants designed from Round 2 backtesting results
(AAPL, MSFT, GOOG, AMZN, NVDA, META — tech_giants.json, 2004-2026):

  1. Donchian (40/20) + SMA200 Trend Gate
       Goal: cut MaxDD from 15.73% toward ~10% by suppressing entries in
       confirmed bear markets, while preserving the 501% P&L base.

  2. BB Breakout (20d/1.5x) + ROC Momentum Gate
       Goal: fix the near-zero Sharpe (+0.03) of BB Breakout (20d/2.0x) by
       tightening the band width to 1.5x (more entries, better timing) and
       adding a 20-bar ROC > 0 gate to confirm momentum before entry.

  3. Donchian (60/20) — Wider Entry Window
       Goal: explore whether an even longer entry lookback (60-bar highs)
       produces higher-conviction breakouts than 40-bar, with stronger OOS
       stability (Keltner and BB Breakout had notably weaker OOS vs Donchian).

All three follow the standard plugin pattern and are registered automatically
when the custom_strategies directory is loaded.
"""

import numpy as np
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import (
    donchian_channel_breakout_logic,
    bollinger_breakout_logic,
    roc_logic,
    calculate_sma,
)
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ---------------------------------------------------------------------------
# Strategy 1: Donchian (40/20) + SMA200 Trend Gate
# ---------------------------------------------------------------------------

@register_strategy(
    name="Donchian (40/20) + SMA200 Trend Gate",
    dependencies=[],
    params={
        "entry_period": get_bars_for_period("40d", _TF, _MUL),
        "exit_period":  get_bars_for_period("20d", _TF, _MUL),
        "ma_length":    get_bars_for_period("200d", _TF, _MUL),
    },
)
def donchian_40_20_sma200_gate(df, **kwargs):
    """Donchian (40/20) entries gated by the symbol's own SMA-200 trend filter.

    Problem: Round 2's best strategy — Donchian (40/20) — achieved 501% P&L
    but carried a 15.73% MaxDD, because breakout entries were taken during
    confirmed downtrends (e.g. 2008, 2020 COVID crash, 2022 rate-hike drawdown).

    Fix: After computing raw Donchian signals, suppress any long entry (Signal==1)
    on days when the symbol's own Close is below its 200-bar SMA. This is a
    per-asset filter (no external data dependencies) — each tech stock gates
    itself. Exit signals (Signal==-1) are always preserved so open positions
    can close even during downtrend regimes.

    Expected improvement:
    - MaxDD: ~15.73% → ~10-12% (fewer entries at bear-market highs)
    - P&L: ~501% → ~380-450% (some valid breakouts suppressed during corrections)
    - Calmar: net improvement (DD reduction outpaces P&L sacrifice)
    - WFA: should remain Pass (SMA200 is a classic, robust filter)
    """
    entry_p  = kwargs["entry_period"]
    exit_p   = kwargs["exit_period"]
    ma_len   = kwargs["ma_length"]

    # Step 1: raw Donchian signals
    df = donchian_channel_breakout_logic(df, entry_period=entry_p, exit_period=exit_p)
    raw_signal = df["Signal"].copy()

    # Step 2: compute the symbol's own 200-bar SMA
    df = calculate_sma(df, length=ma_len)
    sma_col   = f"SMA_{ma_len}"
    is_uptrend = df["Close"] > df[sma_col]

    # Step 3: suppress long entries in downtrend; always allow exits
    df["Signal"] = np.where(
        raw_signal == 1,
        np.where(is_uptrend, 1, -1),
        raw_signal,
    )
    return df


# ---------------------------------------------------------------------------
# Strategy 2: BB Breakout (20d/1.5x) + ROC Momentum Gate
# ---------------------------------------------------------------------------

@register_strategy(
    name="BB Breakout (20d/1.5x) + ROC Gate",
    dependencies=[],
    params={
        "length":       get_bars_for_period("20d", _TF, _MUL),
        "std_dev":      1.5,
        "roc_length":   get_bars_for_period("20d", _TF, _MUL),
        "roc_threshold": 0,
    },
)
def bb_breakout_15x_roc_gate(df, **kwargs):
    """Bollinger Band breakout at 1.5x std dev, gated by 20-bar ROC > 0.

    Problems from Round 2:
    (a) BB Breakout (20d/2.0x) had the lowest Sharpe (+0.03) of the four
        top performers — barely above zero. The 2.0x band is wide enough
        that many "breakouts" are false signals in sideways markets.
    (b) OOS P&L (62.61%) was the weakest of the four, suggesting
        in-sample fitting to a few lucky trades.

    Fix 1 — tighten to 1.5x std dev: the upper band fires more frequently,
    improving trade count (more MC sample) and catching momentum earlier in
    the move rather than waiting for the full 2.0x extension.

    Fix 2 — ROC > 0 gate: the 20-bar rate-of-change must be positive before
    an entry is accepted. This rejects "breakouts" that occur against a
    falling 20-bar price trend (a common false signal in choppy markets).
    The ROC gate was the key ingredient in Round 2's second-best performer
    (EMA+ROC Gate, 488% P&L, Sharpe +0.39), so applying it here leverages
    a proven momentum confirmation.

    Expected improvement:
    - Sharpe: +0.03 → +0.20 to +0.30 (ROC filter cuts losing trades)
    - OOS P&L: 62% → 100%+ (regime-filtered entries generalise better)
    - Trade count: increases modestly from 1.5x band (better MC stability)
    - P&L: may dip slightly (some valid breakouts rejected) but risk-adjusted
      returns should improve materially
    """
    length   = kwargs["length"]
    std_dev  = kwargs["std_dev"]
    roc_len  = kwargs["roc_length"]
    roc_thr  = kwargs["roc_threshold"]

    # Step 1: Bollinger Band breakout signals (1.5x band)
    df = bollinger_breakout_logic(df, length=length, std_dev=std_dev)
    bb_signal = df["Signal"].copy()

    # Step 2: 20-bar ROC direction filter
    df = roc_logic(df, length=roc_len, threshold=roc_thr)
    roc_signal = df["Signal"].copy()  # 1 when ROC > 0, -1 otherwise

    # Step 3: long entry only when BOTH BB breakout fires AND ROC positive;
    #         BB exits (-1) are unconditional — never held against trend
    df["Signal"] = np.where(
        bb_signal == 1,
        np.where(roc_signal == 1, 1, -1),
        -1,
    )
    return df


# ---------------------------------------------------------------------------
# Strategy 3: Donchian (60/20) — Extended Entry Window
# ---------------------------------------------------------------------------

@register_strategy(
    name="Donchian Breakout (60/20)",
    dependencies=[],
    params={
        "entry_period": get_bars_for_period("60d", _TF, _MUL),
        "exit_period":  get_bars_for_period("20d", _TF, _MUL),
    },
)
def donchian_breakout_60_20(df, **kwargs):
    """Donchian channel breakout with a 60-bar entry window and 20-bar exit.

    Problem: Keltner (20d/1.5x) and BB Breakout (20d/2.0x) both showed
    significantly weaker OOS P&L (118% and 62%) relative to their in-sample
    figures, compared to Donchian (40/20) which had a strong 204% OOS P&L.
    This suggests that longer-window Donchian entries produce more robust,
    regime-agnostic breakout signals — likely because 60-bar new highs are
    structurally meaningful events that persist out-of-sample.

    Hypothesis: Extending the entry lookback from 40 to 60 bars raises the
    structural significance of each breakout event further. A 60-bar new high
    on any individual tech stock is a genuine multi-month price leadership
    signal — not a noise-driven channel touch. The 20-bar exit window (same
    as Round 2) preserves the asymmetric profit/loss ratio that made the
    40-bar variant successful.

    Expected profile vs Donchian (40/20):
    - P&L: somewhat lower (fewer total entries; missed some valid breakouts)
    - Trades: ~150-200 (vs ~265) — fewer but each carries more conviction
    - Expectancy(R): higher per-trade (stricter entry = higher average gain)
    - OOS P&L: similar or stronger than 204% (more robust structural signal)
    - MaxDD: potentially slightly lower (longer lookback avoids late-stage
      false breakouts that occur near cycle tops)
    """
    return donchian_channel_breakout_logic(
        df,
        entry_period=kwargs["entry_period"],
        exit_period=kwargs["exit_period"],
    )
