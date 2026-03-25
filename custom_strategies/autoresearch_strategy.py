"""
Autoresearch strategy — Claude iterates on this file.
Starting point: simple SMA Crossover (20/50).
"""

import numpy as np
from helpers.registry import register_strategy
from helpers.indicators import ema_crossover_unfiltered_logic


@register_strategy(
    name="AutoResearch SMA",
    dependencies=[],
)
def autoresearch_sma(df, **kwargs):
    """
    EMA Crossover (15/50) with volume confirmation.
    Only enter on above-average volume days.
    """
    df = ema_crossover_unfiltered_logic(df, fast_ema=15, slow_ema=50)
    if 'Volume' in df.columns:
        avg_vol = df['Volume'].rolling(20).mean()
        low_vol = df['Volume'] < avg_vol * 0.3
        # On very low volume crossover days, suppress entry signal
        df.loc[low_vol & (df['Signal'] == 1), 'Signal'] = 0
    return df