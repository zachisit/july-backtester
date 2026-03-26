"""
Autoresearch strategy — Claude iterates on this file.
Starting point: simple SMA Crossover (20/50).
"""

import numpy as np
from helpers.registry import register_strategy
from helpers.indicators import ema_crossover_unfiltered_logic, calculate_sma


@register_strategy(
    name="AutoResearch SMA",
    dependencies=[],
)
def autoresearch_sma(df, **kwargs):
    """
    Strategy: EMA Crossover (12/120) with SMA200 trend filter.
    Only enter long when price is above SMA200.
    """
    df = ema_crossover_unfiltered_logic(df, fast_ema=12, slow_ema=120)
    df = calculate_sma(df, 200)
    original_signal = df['Signal'].copy()
    is_uptrend = df['Close'] > df['SMA_200']
    # Block buy signals when below SMA200, keep exit signals
    df['Signal'] = np.where((original_signal == 1) & ~is_uptrend, -1, original_signal)
    return df
