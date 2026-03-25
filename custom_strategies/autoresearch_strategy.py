"""
Autoresearch strategy — Claude iterates on this file.
Starting point: simple SMA Crossover (20/50).
"""

import numpy as np
from helpers.registry import register_strategy
from helpers.indicators import ema_crossover_unfiltered_logic


@register_strategy(
    name="AutoResearch SMA",
    dependencies=["spy"],
)
def autoresearch_sma(df, **kwargs):
    """
    EMA Crossover (12/26) with SPY SMA200 trend filter.
    Only enter long when SPY is above its 200-day SMA.
    """
    spy_df = kwargs.get("spy_df")
    df = ema_crossover_unfiltered_logic(df, fast_ema=12, slow_ema=26)
    if spy_df is not None and len(spy_df) > 0:
        spy_sma200 = spy_df['Close'].rolling(200).mean()
        spy_above = spy_df['Close'] > spy_sma200
        spy_above = spy_above.reindex(df.index, method='ffill').fillna(False)
        df['Signal'] = np.where(spy_above, df['Signal'], -1)
    return df