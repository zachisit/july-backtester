"""
Autoresearch strategy — Claude iterates on this file.
Starting point: simple SMA Crossover (20/50).
"""

from helpers.registry import register_strategy
from helpers.indicators import bollinger_breakout_logic


@register_strategy(
    name="AutoResearch SMA",
    dependencies=[],
)
def autoresearch_sma(df, **kwargs):
    """
    Strategy: Bollinger Breakout (length=120, std=2.0).
    """
    df = bollinger_breakout_logic(df, length=120, std_dev=2.0)
    return df
