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
    Base strategy: EMA Crossover.
    Claude will iterate on this to improve total return.
    """
    df = ema_crossover_unfiltered_logic(df, fast_ema=12, slow_ema=70)
    return df
