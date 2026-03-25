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
    """EMA Crossover (15/45) — tighter slow EMA for faster trend capture."""
    df = ema_crossover_unfiltered_logic(df, fast_ema=15, slow_ema=45)
    return df