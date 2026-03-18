# examples/strategies/volume_spike_entry_example.py
"""
EXAMPLE STRATEGY: Volume Spike Entry
=====================================
Difficulty: Beginner

Buys when today's volume is 2x the 20-day average AND the close is up
from the prior day (institutional accumulation signal). Exits when volume
drops back below the 20-day average.

This example shows how to write signal logic INLINE in the plugin file
rather than calling a function from helpers/indicators.py. Both approaches
work — use whichever you prefer.

How to use:
    Copy this file into custom_strategies/ and run:
        python main.py --dry-run
"""

import numpy as np
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


@register_strategy(
    name="Volume Spike Entry (Example)",
    dependencies=[],
    params={
        "vol_lookback": get_bars_for_period("20d", _TF, _MUL),
        "vol_multiplier": 2.0,  # Non-numeric params (strings, bools) are
                                # also allowed — they pass through unchanged
                                # in the sensitivity sweep.
    },
)
def volume_spike_entry_example(df, **kwargs):
    """
    Buy on a volume spike with a positive close; exit when volume normalises.

    The logic is written inline here to show you don't *need* to put
    everything in helpers/indicators.py. For one-off strategies, inline
    is simpler. For reusable logic, put it in indicators.py.

    Parameters (via **kwargs)
    -------------------------
    vol_lookback : int
        Bars for the volume moving average.
    vol_multiplier : float
        How many times the average volume constitutes a "spike".
    """
    vol_lookback   = kwargs["vol_lookback"]
    vol_multiplier = kwargs["vol_multiplier"]

    # --- Signal logic (inline) ---

    # 1. Calculate the 20-day average volume
    df['AvgVolume'] = df['Volume'].rolling(vol_lookback).mean()

    # 2. Detect a volume spike: today's volume is 2x+ the average
    is_volume_spike = df['Volume'] > (df['AvgVolume'] * vol_multiplier)

    # 3. Confirm the close is higher than yesterday's close (bullish)
    is_up_day = df['Close'] > df['Close'].shift(1)

    # 4. Build the signal:
    #    Buy (1)  when both conditions are met
    #    Sell (-1) when volume drops back below average
    #    No change (0) otherwise — the engine forward-fills
    buy_signal  = is_volume_spike & is_up_day
    sell_signal = df['Volume'] < df['AvgVolume']

    df['Signal'] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))

    # 5. Forward-fill: the engine expects a continuous state.
    #    Replace 0 with NaN, then fill forward so "hold" persists.
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)

    return df
