# custom_strategies/btc_strategies_v2.py
"""Bitcoin RSI Trend Optimized variants (BTC-R7).

Derived from the BTC-R4 sensitivity sweep of BTC RSI Trend (14/60/40) + SMA200
across 625 parameter combinations (5^4 grid). Top-performing parameter zones
identified — NOT cherry-picked from a single run:

Key findings from BTC-R4 sweep (625 variants):
  - All top-5 Calmar variants share exit_level=56 (tighter exit than base 40)
  - Most high-Calmar variants use gate_length=120 (shorter than base 200)
  - rsi_length=11 and rsi_length=20 both appear in top-5 (flanking base 14)
  - Calmar ceiling: 1.86 (vs base 1.32 — 41% improvement available)

Strategies in this file:
  1. BTC RSI Trend (11/60/56) + SMA120
     rsi_length=11 (shorter RSI — captures momentum faster)
     entry=60, exit=56 (tighter exit — preserves more momentum gains)
     gate=SMA120 (shorter trend filter — re-entries earlier in bull markets)

  2. BTC RSI Trend (20/60/56) + SMA120
     rsi_length=20 (longer RSI — more selective entries, higher conviction)
     entry=60, exit=56 (same tight exit as variant 1)
     gate=SMA120 (same shorter trend filter)

Both variants represent structurally distinct parameter zones from the sweep
that have never been formally named or independently validated. BTC-R7 provides
that validation: standalone base test + 125-variant confirmation sweep.
"""

import numpy as np
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import calculate_sma, calculate_rsi
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ===========================================================================
# STRATEGY 1 — BTC RSI Trend (11/60/56) + SMA120
# ===========================================================================

@register_strategy(
    name="BTC RSI Trend (11/60/56) + SMA120",
    dependencies=[],
    params={
        "rsi_length":    get_bars_for_period("11d", _TF, _MUL),
        "entry_level":   60,
        "exit_level":    56,
        "gate_length":   get_bars_for_period("120d", _TF, _MUL),
    },
)
def btc_rsi_trend_11_56_120(df, **kwargs):
    """RSI(11) momentum entry (>60) with SMA(120) uptrend gate; exit on RSI<56.

    Optimized variant derived from BTC-R4 sweep. Key differences vs base:
    - rsi_length=11 vs 14: faster RSI — picks up momentum 3 bars earlier
    - exit_level=56 vs 40: tighter exit — captures more of the momentum gain
      before exhaustion, reducing give-back in volatile BTC conditions
    - gate=SMA120 vs SMA200: shorter trend filter — confirms uptrend 80 bars
      earlier than SMA200, enabling earlier re-entries after corrections

    Entry: RSI(11) > 60 AND Close > SMA(120)
    Exit:  RSI(11) < 56 (momentum tightening — unconditional)
    """
    rsi_length  = kwargs["rsi_length"]
    entry_level = kwargs["entry_level"]
    exit_level  = kwargs["exit_level"]
    gate_length = kwargs["gate_length"]

    df = calculate_rsi(df, length=rsi_length)
    rsi_col = f'RSI_{rsi_length}'

    df = calculate_sma(df, length=gate_length)
    sma_col = f'SMA_{gate_length}'

    is_uptrend      = df["Close"] > df[sma_col]
    rsi_above_entry = df[rsi_col] > entry_level
    rsi_below_exit  = df[rsi_col] < exit_level

    buy_signal  = rsi_above_entry & is_uptrend
    sell_signal = rsi_below_exit

    df["Signal"] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
    return df


# ===========================================================================
# STRATEGY 2 — BTC RSI Trend (20/60/56) + SMA120
# ===========================================================================

@register_strategy(
    name="BTC RSI Trend (20/60/56) + SMA120",
    dependencies=[],
    params={
        "rsi_length":    get_bars_for_period("20d", _TF, _MUL),
        "entry_level":   60,
        "exit_level":    56,
        "gate_length":   get_bars_for_period("120d", _TF, _MUL),
    },
)
def btc_rsi_trend_20_56_120(df, **kwargs):
    """RSI(20) momentum entry (>60) with SMA(120) uptrend gate; exit on RSI<56.

    Optimized variant derived from BTC-R4 sweep. Key differences vs base:
    - rsi_length=20 vs 14: slower RSI — higher conviction entries, filters more
      noise than RSI(11); trades slightly less frequently but with more signal
    - exit_level=56 vs 40: tighter exit — same rationale as variant 1
    - gate=SMA120 vs SMA200: same shorter trend filter as variant 1

    RSI(20) at > 60 on daily bars represents ~20 days of net positive closes —
    a more structural signal than RSI(11). Both variants are valid; they differ
    in trade frequency and entry selectivity.

    Entry: RSI(20) > 60 AND Close > SMA(120)
    Exit:  RSI(20) < 56 (momentum tightening — unconditional)
    """
    rsi_length  = kwargs["rsi_length"]
    entry_level = kwargs["entry_level"]
    exit_level  = kwargs["exit_level"]
    gate_length = kwargs["gate_length"]

    df = calculate_rsi(df, length=rsi_length)
    rsi_col = f'RSI_{rsi_length}'

    df = calculate_sma(df, length=gate_length)
    sma_col = f'SMA_{gate_length}'

    is_uptrend      = df["Close"] > df[sma_col]
    rsi_above_entry = df[rsi_col] > entry_level
    rsi_below_exit  = df[rsi_col] < exit_level

    buy_signal  = rsi_above_entry & is_uptrend
    sell_signal = rsi_below_exit

    df["Signal"] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
    return df
