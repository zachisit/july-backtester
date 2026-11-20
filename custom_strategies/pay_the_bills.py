"""

Two variants for A/B comparison:
1. Turn of Month (Baseline)   — pure calendar flow effect (2 params)
2. Turn of Month + SMA200     — adds a 200-day trend filter (3 params)

Signal convention: 1 = long, -1 = exit/flat.
"""

import numpy as np
import pandas as pd

from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from config import CONFIG

_TIMEFRAME = CONFIG.get("timeframe", "D")
_MULTIPLIER = CONFIG.get("timeframe_multiplier", 1)


def _get_close(df: pd.DataFrame) -> pd.Series:
    for col in ("Close", "close", "Adj Close", "adj_close"):
        if col in df.columns:
            return df[col]
    raise KeyError(f"No close column found in DataFrame: {list(df.columns)}")


def _tom_window_mask(index: pd.DatetimeIndex, entry_days_before_eom: int, exit_trading_day: int) -> pd.Series:
    dates = pd.to_datetime(index)
    year_month = dates.to_period("M")

    td_from_start = pd.Series(range(len(dates)), index=index).groupby(year_month).cumcount() + 1
    month_lengths = pd.Series(range(len(dates)), index=index).groupby(year_month).transform("count")
    td_from_end = month_lengths - td_from_start + 1

    return (td_from_end <= entry_days_before_eom) | (td_from_start <= exit_trading_day)


@register_strategy(
    name="Turn of Month (Baseline)",
    dependencies=[],
    params={
        "entry_days_before_eom": 1,
        "exit_trading_day": 4,
    },
)
def tom_baseline(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    in_window = _tom_window_mask(
        df.index,
        entry_days_before_eom=kwargs["entry_days_before_eom"],
        exit_trading_day=kwargs["exit_trading_day"],
    )
    out = df.copy()
    out["Signal"] = np.where(in_window, 1, -1)
    return out


@register_strategy(
    name="Turn of Month + SMA200",
    dependencies=[],
    params={
        "entry_days_before_eom": 1,
        "exit_trading_day": 4,
        "sma_period": get_bars_for_period("200d", _TIMEFRAME, _MULTIPLIER),
    },
)
def tom_sma200(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    close = _get_close(df)
    sma = close.rolling(window=kwargs["sma_period"], min_periods=kwargs["sma_period"]).mean()
    in_window = _tom_window_mask(
        df.index,
        entry_days_before_eom=kwargs["entry_days_before_eom"],
        exit_trading_day=kwargs["exit_trading_day"],
    )
    out = df.copy()
    out["Signal"] = np.where(in_window & (close > sma), 1, -1)
    return out

@register_strategy(
    name="Multi-Asset Trend (SMA200)",
    dependencies=[],
    params={
        "sma_period": get_bars_for_period("200d", _TIMEFRAME, _MULTIPLIER),
    },
)
def multi_asset_trend_sma200(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    close = _get_close(df)
    sma = close.rolling(window=kwargs["sma_period"], min_periods=kwargs["sma_period"]).mean()
    out = df.copy()
    out["Signal"] = np.where(close > sma, 1, -1)
    return out


@register_strategy(
    name="Multi-Asset Trend (SMA50/200 Gate)",
    dependencies=[],
    params={
        "fast_period": get_bars_for_period("50d", _TIMEFRAME, _MULTIPLIER),
        "slow_period": get_bars_for_period("200d", _TIMEFRAME, _MULTIPLIER),
    },
)
def multi_asset_trend_sma50_200(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    close = _get_close(df)
    sma_fast = close.rolling(window=kwargs["fast_period"], min_periods=kwargs["fast_period"]).mean()
    sma_slow = close.rolling(window=kwargs["slow_period"], min_periods=kwargs["slow_period"]).mean()

    signal = np.where((close > sma_slow) & (close > sma_fast), 1, np.where(close < sma_slow, -1, np.nan))
    out = df.copy()
    out["Signal"] = pd.Series(signal, index=df.index).ffill().fillna(-1).astype(int)
    return out