"""
Autoresearch strategy — Claude iterates on this file.
Starting point: simple SMA Crossover (20/50).
"""

from helpers.registry import register_strategy
from helpers.indicators import ema_crossover_unfiltered_logic


@register_strategy(
    name="AutoResearch SMA",
    dependencies=[],
)
def autoresearch_sma(df, **kwargs):
    """
    EMA Crossover (12/26) - faster signals than SMA 20/50.
    """
    df = ema_crossover_unfiltered_logic(df, fast_ema=16, slow_ema=50)
    return df