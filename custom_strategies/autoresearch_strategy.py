"""
Autoresearch strategy — Claude iterates on this file.
Starting point: simple SMA Crossover (20/50).
"""

import numpy as np
from helpers.registry import register_strategy
from helpers.indicators import ema_crossover_unfiltered_logic, calculate_rsi


@register_strategy(
    name="AutoResearch SMA",
    dependencies=[],
)
def autoresearch_sma(df, **kwargs):
    """
    Strategy: EMA Crossover with RSI > 50 filter.
    Only enter long when RSI confirms momentum.
    """
    df = ema_crossover_unfiltered_logic(df, fast_ema=12, slow_ema=120)
    df = calculate_rsi(df, length=14)
    original_signal = df['Signal'].copy()
    # Only allow buy signals when RSI > 50
    df['Signal'] = np.where((original_signal == 1) & (df['RSI_14'] > 50), 1, original_signal)
    return df
