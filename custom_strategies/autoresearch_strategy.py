"""
Autoresearch strategy — Claude iterates on this file.
Starting point: simple SMA Crossover (20/50).
"""

from helpers.registry import register_strategy
from helpers.indicators import sma_trend_filter_logic


@register_strategy(
    name="AutoResearch SMA",
    dependencies=[],
)
def autoresearch_sma(df, **kwargs):
    """
    Strategy: SMA200 trend filter — buy when above SMA200, sell when below.
    """
    df = sma_trend_filter_logic(df, ma_length=200)
    return df
