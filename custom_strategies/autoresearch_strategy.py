"""
Autoresearch strategy — Claude iterates on this file.
Starting point: simple SMA Crossover (20/50).
"""

from helpers.registry import register_strategy
from helpers.indicators import sma_crossover_logic


@register_strategy(
    name="AutoResearch SMA",
    dependencies=[],
)
def autoresearch_sma(df, **kwargs):
    """
    Base strategy: SMA Crossover.
    Claude will iterate on this to improve total return.
    """
    df = sma_crossover_logic(df, fast=10, slow=50)
    return df