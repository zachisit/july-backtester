"""
Autoresearch strategy — Claude iterates on this file.
"""

import numpy as np
from helpers.registry import register_strategy
from helpers.indicators import ema_crossover_unfiltered_logic


@register_strategy(
    name="AutoResearch SMA",
    dependencies=["spy"],
)
def autoresearch_sma(df, **kwargs):
    """EMA Crossover (10/40) with SPY SMA200 trend filter."""
    spy_df = kwargs.get("spy_df")
    df = ema_crossover_unfiltered_logic(df, fast_ema=10, slow_ema=40)

    # Only enter when SPY is above its 200-day SMA (bull market filter)
    if spy_df is not None:
        spy_sma200 = spy_df["Close"].rolling(200).mean()
        spy_bullish = spy_df["Close"] > spy_sma200
        # Reindex to match df dates
        spy_bullish = spy_bullish.reindex(df.index, method="ffill").fillna(False)
        # Zero out buy signals when SPY is bearish
        df["Signal"] = np.where(
            (df["Signal"] == 1) & (~spy_bullish), 0, df["Signal"]
        )

    return df