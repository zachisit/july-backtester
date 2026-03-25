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
    """EMA Crossover (8/30) — tighter crossover for faster signals."""
    df = ema_crossover_unfiltered_logic(df, fast_ema=8, slow_ema=30)
    return df