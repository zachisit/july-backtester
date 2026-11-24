"""Pay the Bills — 12-month absolute momentum on SPY."""

import numpy as np
import pandas as pd

from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from config import CONFIG

_TIMEFRAME = CONFIG.get("timeframe", "D")
_MULTIPLIER = CONFIG.get("timeframe_multiplier", 1)


@register_strategy(
    name="Pay the Bills – 12M Momentum on SPY",
    dependencies=[],
    params={
        "lookback": get_bars_for_period("252d", _TIMEFRAME, _MULTIPLIER),
    },
)
def pay_the_bills_momentum(df, **kwargs):
    lookback = kwargs["lookback"]

    df["Momentum"] = df["Close"].pct_change(lookback)

    df["Signal"] = np.nan
    df.loc[df["Momentum"] > 0, "Signal"] = 1
    df.loc[df["Momentum"] <= 0, "Signal"] = -1
    df["Signal"] = df["Signal"].fillna(-1).astype(int)

    return df
