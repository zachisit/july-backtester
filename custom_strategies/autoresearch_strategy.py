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
    Iteration 5: EMA crossover (15/50) - push fast EMA higher to further reduce whipsaws.
    """
    df = ema_crossover_unfiltered_logic(df, fast_ema=15, slow_ema=50)
    return df