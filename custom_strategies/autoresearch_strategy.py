"""
Autoresearch strategy — Claude iterates on this file.
Starting point: simple SMA Crossover (20/50).
"""

from helpers.registry import register_strategy
from helpers.indicators import donchian_channel_breakout_logic


@register_strategy(
    name="AutoResearch SMA",
    dependencies=[],
)
def autoresearch_sma(df, **kwargs):
    """
    Strategy: Donchian Channel Breakout (50/25).
    """
    df = donchian_channel_breakout_logic(df, entry_period=50, exit_period=25)
    return df
