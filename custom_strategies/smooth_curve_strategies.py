# custom_strategies/smooth_curve_strategies.py
"""
Smooth Curve Research — Chapter 4 (EC-R1 onwards)

Goal: Steady, steadily-increasing equity curves. Prior research optimized for
Sharpe but NOT for equity curve smoothness.

Root cause: Conservative v2 (best prior portfolio) has Calmar 0.30-0.52 and
MaxRecovery 1,085-1,722 days. The per-stock SMA200 gate filters individual
stock downtrends but NOT market-wide crashes. During 2001-2003, 2008-2009,
2022, all stocks fall together — the per-stock gate fires too late.

Solution: Add a SPY macro regime gate (SPY > SMA200) to all 6 Conservative v2
champion strategies. When SPY < SMA(40w) [= SMA200 daily equivalent], force
exits and prevent new entries. Historically flat during:
  - 2001-2003 (dot-com, ~18 months)
  - 2008-2009 (GFC, ~8 months)
  - Dec 2018 (~2 months)
  - Mar-May 2020 (COVID, ~2 months)
  - Jan-Nov 2022 (rate hike bear, ~10 months)

New validation target: Calmar >= 1.0, MaxRecovery <= 365 days, MaxDD <= 25%.
"""

import numpy as np
import pandas as pd
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import (
    ma_bounce_logic,
    ma_confluence_logic,
    donchian_channel_breakout_logic,
    calculate_sma,
    calculate_rsi,
    calculate_williams_r,
)
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


def _spy_regime_ok(spy_df, df_index, sma_length):
    """Returns boolean Series aligned to df_index: True when SPY > SMA(sma_length)."""
    if spy_df is None or spy_df.empty:
        return pd.Series(True, index=df_index)
    spy_close = spy_df["Close"].reindex(df_index, method="ffill")
    spy_sma   = spy_close.rolling(sma_length).mean()
    return (spy_close > spy_sma).fillna(False)


# ===========================================================================
# STRATEGY 1 — MA Bounce (50d/3bar) + SMA200 Gate + SPY Macro Regime Gate
# ===========================================================================

@register_strategy(
    name="EC: MA Bounce + SPY Regime Gate",
    dependencies=["spy"],
    params={
        "ma_length":       get_bars_for_period("50d",  _TF, _MUL),
        "filter_bars":     3,
        "gate_length":     get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("200d", _TF, _MUL),
    },
)
def ec_ma_bounce_spy_regime(df, spy_df=None, **kwargs):
    df = ma_bounce_logic(df, ma_length=kwargs["ma_length"], filter_bars=kwargs["filter_bars"])
    bounce_signal = df["Signal"].copy()

    df = calculate_sma(df, length=kwargs["gate_length"])
    sma_col    = f'SMA_{kwargs["gate_length"]}'
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    df["Signal"] = np.where(
        bounce_signal == 1,
        np.where(is_uptrend & spy_ok, 1, -1),
        -1,
    )
    return df


# ===========================================================================
# STRATEGY 2 — MA Confluence Fast Exit + SPY Macro Regime Gate
# ===========================================================================

@register_strategy(
    name="EC: MAC Fast Exit + SPY Regime Gate",
    dependencies=["spy"],
    params={
        "ma_fast":         get_bars_for_period("10d",  _TF, _MUL),
        "ma_medium":       get_bars_for_period("20d",  _TF, _MUL),
        "ma_slow":         get_bars_for_period("50d",  _TF, _MUL),
        "spy_gate_length": get_bars_for_period("200d", _TF, _MUL),
    },
)
def ec_mac_fast_exit_spy_regime(df, spy_df=None, **kwargs):
    df = ma_confluence_logic(
        df,
        ma_fast=kwargs["ma_fast"],
        ma_medium=kwargs["ma_medium"],
        ma_slow=kwargs["ma_slow"],
        entry_rule="full_stack",
        exit_rule="fast_cross",
    )
    mac_signal = df["Signal"].copy()
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    df["Signal"] = np.where(
        mac_signal == 1,
        np.where(spy_ok, 1, -1),
        -1,
    )
    return df


# ===========================================================================
# STRATEGY 3 — Donchian (40/20) + SMA200 Gate + SPY Macro Regime Gate
# ===========================================================================

@register_strategy(
    name="EC: Donchian (40/20) + SPY Regime Gate",
    dependencies=["spy"],
    params={
        "entry_period":    get_bars_for_period("40d",  _TF, _MUL),
        "exit_period":     get_bars_for_period("20d",  _TF, _MUL),
        "ma_length":       get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("200d", _TF, _MUL),
    },
)
def ec_donchian_spy_regime(df, spy_df=None, **kwargs):
    df = donchian_channel_breakout_logic(
        df, entry_period=kwargs["entry_period"], exit_period=kwargs["exit_period"]
    )
    raw_signal = df["Signal"].copy()

    df = calculate_sma(df, length=kwargs["ma_length"])
    sma_col    = f'SMA_{kwargs["ma_length"]}'
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    df["Signal"] = np.where(
        raw_signal == 1,
        np.where(is_uptrend & spy_ok, 1, -1),
        raw_signal,
    )
    return df


# ===========================================================================
# STRATEGY 4 — Price Momentum (6m ROC >15%) + SMA200 + SPY Macro Regime Gate
# ===========================================================================

@register_strategy(
    name="EC: Price Momentum (6m/15%) + SPY Regime Gate",
    dependencies=["spy"],
    params={
        "roc_period":      get_bars_for_period("126d", _TF, _MUL),
        "roc_threshold":   15.0,
        "sma_slow":        get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("200d", _TF, _MUL),
    },
)
def ec_price_momentum_spy_regime(df, spy_df=None, **kwargs):
    roc_period    = kwargs["roc_period"]
    roc_threshold = kwargs["roc_threshold"]
    sma_slow      = kwargs["sma_slow"]

    df["_roc"]  = df["Close"].pct_change(periods=roc_period) * 100.0
    df          = calculate_sma(df, sma_slow)
    sma_col     = f"SMA_{sma_slow}"
    is_uptrend  = df["Close"] > df[sma_col]
    spy_ok      = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    is_entry = (df["_roc"] > roc_threshold) & is_uptrend & spy_ok
    is_exit  = (df["_roc"] < 0.0) | (~is_uptrend) | (~spy_ok)

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(df["_roc"].iloc[i]) or pd.isna(df[sma_col].iloc[i]):
            signals.append(-1)
            continue
        if not in_position:
            if is_entry.iloc[i]:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if is_exit.iloc[i]:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=["_roc", sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 4b — EC-R8: Price Momentum v2 (6.5m/18%) + SPY SMA120 Gate
# Params from EC-R7 sensitivity sweep: longer lookback + tighter SPY gate
# ===========================================================================

@register_strategy(
    name="EC: Price Momentum v2 (6.5m/18%) + SPY Gate",
    dependencies=["spy"],
    params={
        "roc_period":      get_bars_for_period("151d", _TF, _MUL),
        "roc_threshold":   18.0,
        "sma_slow":        get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("120d", _TF, _MUL),
    },
)
def ec_price_momentum_v2_spy_regime(df, spy_df=None, **kwargs):
    roc_period    = kwargs["roc_period"]
    roc_threshold = kwargs["roc_threshold"]
    sma_slow      = kwargs["sma_slow"]

    df["_roc"]  = df["Close"].pct_change(periods=roc_period) * 100.0
    df          = calculate_sma(df, sma_slow)
    sma_col     = f"SMA_{sma_slow}"
    is_uptrend  = df["Close"] > df[sma_col]
    spy_ok      = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    is_entry = (df["_roc"] > roc_threshold) & is_uptrend & spy_ok
    is_exit  = (df["_roc"] < 0.0) | (~is_uptrend) | (~spy_ok)

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(df["_roc"].iloc[i]) or pd.isna(df[sma_col].iloc[i]):
            signals.append(-1)
            continue
        if not in_position:
            if is_entry.iloc[i]:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if is_exit.iloc[i]:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=["_roc", sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 4c — EC-R10: Price Momentum v3 (6.5m/18%) + SPY SMA96 Gate
# EC-R9 sweep signal: spy_gate=96 → MaxDD ~15.7%, Sharpe ~0.79
# ===========================================================================

@register_strategy(
    name="EC: Price Momentum v3 (6.5m/18%) + SPY SMA96 Gate",
    dependencies=["spy"],
    params={
        "roc_period":      get_bars_for_period("151d", _TF, _MUL),
        "roc_threshold":   18.0,
        "sma_slow":        get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("96d",  _TF, _MUL),
    },
)
def ec_price_momentum_v3_spy_regime(df, spy_df=None, **kwargs):
    roc_period    = kwargs["roc_period"]
    roc_threshold = kwargs["roc_threshold"]
    sma_slow      = kwargs["sma_slow"]

    df["_roc"]  = df["Close"].pct_change(periods=roc_period) * 100.0
    df          = calculate_sma(df, sma_slow)
    sma_col     = f"SMA_{sma_slow}"
    is_uptrend  = df["Close"] > df[sma_col]
    spy_ok      = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    is_entry = (df["_roc"] > roc_threshold) & is_uptrend & spy_ok
    is_exit  = (df["_roc"] < 0.0) | (~is_uptrend) | (~spy_ok)

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(df["_roc"].iloc[i]) or pd.isna(df[sma_col].iloc[i]):
            signals.append(-1)
            continue
        if not in_position:
            if is_entry.iloc[i]:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if is_exit.iloc[i]:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=["_roc", sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 5 — RSI Weekly Trend (55-cross) + SMA200 + SPY Macro Regime Gate
# ===========================================================================

@register_strategy(
    name="EC: RSI Weekly Trend (55) + SPY Regime Gate",
    dependencies=["spy"],
    params={
        "rsi_period":      14,
        "rsi_entry":       55.0,
        "rsi_exit":        45.0,
        "sma_slow":        get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("200d", _TF, _MUL),
    },
)
def ec_rsi_weekly_spy_regime(df, spy_df=None, **kwargs):
    rsi_period = kwargs["rsi_period"]
    rsi_entry  = kwargs["rsi_entry"]
    rsi_exit   = kwargs["rsi_exit"]
    sma_slow   = kwargs["sma_slow"]

    df         = calculate_rsi(df, rsi_period)
    rsi_col    = f"RSI_{rsi_period}"
    df         = calculate_sma(df, sma_slow)
    sma_col    = f"SMA_{sma_slow}"
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    rsi_above_entry = df[rsi_col] > rsi_entry
    rsi_cross_up    = rsi_above_entry & ~rsi_above_entry.shift(1).fillna(False)
    is_entry = rsi_cross_up & is_uptrend & spy_ok
    is_exit  = (df[rsi_col] < rsi_exit) | (~is_uptrend) | (~spy_ok)

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(df[rsi_col].iloc[i]) or pd.isna(df[sma_col].iloc[i]):
            signals.append(-1)
            continue
        if not in_position:
            if is_entry.iloc[i]:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if is_exit.iloc[i]:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[rsi_col, sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 6 — Williams %R Weekly (>-20 cross) + SMA200 + SPY Macro Regime Gate
# ===========================================================================

@register_strategy(
    name="EC: Williams R Weekly (above-20) + SPY Regime Gate",
    dependencies=["spy"],
    params={
        "wr_length":       get_bars_for_period("70d",  _TF, _MUL),
        "entry_level":     -20.0,
        "exit_level":      -80.0,
        "sma_slow":        get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("200d", _TF, _MUL),
    },
)
def ec_williams_r_spy_regime(df, spy_df=None, **kwargs):
    wr_length   = kwargs["wr_length"]
    entry_level = kwargs["entry_level"]
    exit_level  = kwargs["exit_level"]
    sma_slow    = kwargs["sma_slow"]

    df         = calculate_williams_r(df, wr_length)
    wr_col     = f"WilliamsR_{wr_length}"
    df         = calculate_sma(df, sma_slow)
    sma_col    = f"SMA_{sma_slow}"
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    above_entry = df[wr_col] > entry_level
    wr_cross_up = above_entry & ~above_entry.shift(1).fillna(False)
    is_entry    = wr_cross_up & is_uptrend & spy_ok
    is_exit     = (df[wr_col] < exit_level) | (~is_uptrend) | (~spy_ok)

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(df[wr_col].iloc[i]) or pd.isna(df[sma_col].iloc[i]):
            signals.append(-1)
            continue
        if not in_position:
            if is_entry.iloc[i]:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if is_exit.iloc[i]:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[wr_col, sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# STRATEGY 7 — Relative Momentum (Stock vs SPY) + SPY Macro Regime Gate
# Based on confirmed weekly champion: "Relative Momentum (13w vs SPY) Weekly + SMA200"
# Hypothesis: stock-vs-SPY relative outperformance + macro regime gate on daily bars
# should improve Calmar vs absolute Price Momentum.
# ===========================================================================

@register_strategy(
    name="EC: Relative Momentum + SPY Regime Gate",
    dependencies=["spy"],
    params={
        "roc_bars":        get_bars_for_period("65d",  _TF, _MUL),  # 13w lookback
        "rel_thresh":      1.15,                                      # stock beats SPY by 15%+
        "sma_slow":        get_bars_for_period("200d", _TF, _MUL),  # per-stock uptrend gate
        "spy_gate_length": get_bars_for_period("200d", _TF, _MUL),  # macro regime gate
    },
)
def ec_relative_momentum_spy_regime(df, spy_df=None, **kwargs):
    roc_bars   = kwargs["roc_bars"]
    rel_thresh = kwargs["rel_thresh"]
    sma_slow   = kwargs["sma_slow"]

    spy_close = spy_df["Close"].reindex(df.index, method="ffill")
    stock_roc = df["Close"] / df["Close"].shift(roc_bars) - 1
    spy_roc   = spy_close / spy_close.shift(roc_bars) - 1
    relative  = (1 + stock_roc) / (1 + spy_roc.replace(0, np.nan))

    df         = calculate_sma(df, sma_slow)
    sma_col    = f"SMA_{sma_slow}"
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    is_outperforming = relative > rel_thresh
    cross_up = is_outperforming & ~is_outperforming.shift(1).fillna(False)
    is_entry = cross_up & is_uptrend & spy_ok
    is_exit  = (relative <= 1.0) | (~is_uptrend) | (~spy_ok)

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(relative.iloc[i]) or pd.isna(df[sma_col].iloc[i]):
            signals.append(-1)
            continue
        if not in_position:
            if is_entry.iloc[i]:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if is_exit.iloc[i]:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# EC2 VARIANTS — Tighter SPY Gate (SMA50 instead of SMA200)
#
# Hypothesis: SPY SMA50 fires 5-10 months earlier in bear markets vs SMA200.
#   2000 crash: SMA50 exit ~May 2000 vs SMA200 exit March 2001 (10 months earlier)
#   2008 crash: SMA50 exit ~Aug 2007 vs SMA200 exit Jan 2008 (5 months earlier)
# Expected: dramatically reduced MaxDD and MaxRecovery at the cost of some
# false exits during normal corrections (2011, 2014, 2016).
# ===========================================================================

@register_strategy(
    name="EC2: MA Bounce + SPY SMA50 Gate",
    dependencies=["spy"],
    params={
        "ma_length":       get_bars_for_period("50d",  _TF, _MUL),
        "filter_bars":     3,
        "gate_length":     get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("50d",  _TF, _MUL),  # tighter: SMA50 vs SMA200
    },
)
def ec2_ma_bounce_spy_sma50(df, spy_df=None, **kwargs):
    df = ma_bounce_logic(df, ma_length=kwargs["ma_length"], filter_bars=kwargs["filter_bars"])
    bounce_signal = df["Signal"].copy()

    df = calculate_sma(df, length=kwargs["gate_length"])
    sma_col    = f'SMA_{kwargs["gate_length"]}'
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    df["Signal"] = np.where(
        bounce_signal == 1,
        np.where(is_uptrend & spy_ok, 1, -1),
        -1,
    )
    return df


@register_strategy(
    name="EC2: MAC Fast Exit + SPY SMA50 Gate",
    dependencies=["spy"],
    params={
        "ma_fast":         get_bars_for_period("10d",  _TF, _MUL),
        "ma_medium":       get_bars_for_period("20d",  _TF, _MUL),
        "ma_slow":         get_bars_for_period("50d",  _TF, _MUL),
        "spy_gate_length": get_bars_for_period("50d",  _TF, _MUL),  # tighter: SMA50 vs SMA200
    },
)
def ec2_mac_fast_exit_spy_sma50(df, spy_df=None, **kwargs):
    df = ma_confluence_logic(
        df,
        ma_fast=kwargs["ma_fast"],
        ma_medium=kwargs["ma_medium"],
        ma_slow=kwargs["ma_slow"],
        entry_rule="full_stack",
        exit_rule="fast_cross",
    )
    mac_signal = df["Signal"].copy()
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    df["Signal"] = np.where(
        mac_signal == 1,
        np.where(spy_ok, 1, -1),
        -1,
    )
    return df


@register_strategy(
    name="EC2: Donchian (40/20) + SPY SMA50 Gate",
    dependencies=["spy"],
    params={
        "entry_period":    get_bars_for_period("40d",  _TF, _MUL),
        "exit_period":     get_bars_for_period("20d",  _TF, _MUL),
        "ma_length":       get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("50d",  _TF, _MUL),  # tighter: SMA50 vs SMA200
    },
)
def ec2_donchian_spy_sma50(df, spy_df=None, **kwargs):
    df = donchian_channel_breakout_logic(
        df, entry_period=kwargs["entry_period"], exit_period=kwargs["exit_period"]
    )
    raw_signal = df["Signal"].copy()

    df = calculate_sma(df, length=kwargs["ma_length"])
    sma_col    = f'SMA_{kwargs["ma_length"]}'
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    df["Signal"] = np.where(
        raw_signal == 1,
        np.where(is_uptrend & spy_ok, 1, -1),
        raw_signal,
    )
    return df


@register_strategy(
    name="EC2: Price Momentum (6m/15%) + SPY SMA50 Gate",
    dependencies=["spy"],
    params={
        "roc_period":      get_bars_for_period("126d", _TF, _MUL),
        "roc_threshold":   15.0,
        "sma_slow":        get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("50d",  _TF, _MUL),  # tighter: SMA50 vs SMA200
    },
)
def ec2_price_momentum_spy_sma50(df, spy_df=None, **kwargs):
    roc_period    = kwargs["roc_period"]
    roc_threshold = kwargs["roc_threshold"]
    sma_slow      = kwargs["sma_slow"]

    df["_roc"]  = df["Close"].pct_change(periods=roc_period) * 100.0
    df          = calculate_sma(df, sma_slow)
    sma_col     = f"SMA_{sma_slow}"
    is_uptrend  = df["Close"] > df[sma_col]
    spy_ok      = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    is_entry = (df["_roc"] > roc_threshold) & is_uptrend & spy_ok
    is_exit  = (df["_roc"] < 0.0) | (~is_uptrend) | (~spy_ok)

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(df["_roc"].iloc[i]) or pd.isna(df[sma_col].iloc[i]):
            signals.append(-1)
            continue
        if not in_position:
            if is_entry.iloc[i]:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if is_exit.iloc[i]:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=["_roc", sma_col], errors="ignore", inplace=True)
    return df
