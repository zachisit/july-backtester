"""
Autoresearch strategy — Claude iterates on this file.
Starting point: simple SMA Crossover (20/50).
"""

from helpers.registry import register_strategy
from helpers.indicators import macd_crossover_logic


@register_strategy(
    name="AutoResearch SMA",
    dependencies=[],
)
def autoresearch_sma(df, **kwargs):
    """
    MACD Crossover (12/26/9) - classic momentum.
    """
    df = macd_crossover_logic(df, fast=12, slow=26, signal=9)
    return df