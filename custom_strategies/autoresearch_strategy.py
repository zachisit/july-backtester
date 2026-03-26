"""
Autoresearch strategy — Claude iterates on this file.
Starting point: simple SMA Crossover (20/50).
"""

from helpers.registry import register_strategy
from helpers.indicators import roc_logic


@register_strategy(
    name="AutoResearch SMA",
    dependencies=[],
)
def autoresearch_sma(df, **kwargs):
    """
    Strategy: ROC(120) trend following.
    """
    df = roc_logic(df, length=120, threshold=0)
    return df
