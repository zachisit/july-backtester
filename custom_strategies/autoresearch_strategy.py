"""
Autoresearch strategy — Claude iterates on this file.
"""

from helpers.registry import register_strategy
from helpers.indicators import ema_crossover_unfiltered_logic


@register_strategy(
    name="AutoResearch SMA",
    dependencies=[],
)
def autoresearch_sma(df, **kwargs):
    """EMA Crossover (15/50) — reduce whipsaws with slightly slower fast EMA."""
    df = ema_crossover_unfiltered_logic(df, fast_ema=15, slow_ema=50)
    return df