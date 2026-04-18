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


# ===========================================================================
# EC-R13 STRATEGIES — Visual Smoothness Architecture
#
# EC-R12 finding: 5% allocation alone doesn't fix jagged curves. The root cause
# is strategy-level: momentum selects high-volatility stocks → explosive single-
# stock moves spike the portfolio curve regardless of position count.
#
# EC-R13 approach: eliminate high-volatility stock selection entirely via:
#   S1: SMA200 Universe Filter — hold any symbol above SMA200 (no momentum bias)
#   S2: MA Bounce + Low-Vol ATR Filter — same bounce logic but screen out >2.5% ATR
#   S3: EMA21/63 Trend — medium-term trend holding weeks-to-months, not spike-chasing
# ===========================================================================

@register_strategy(
    name="EC: SMA200 Universe Filter + SPY SMA96 Gate",
    dependencies=["spy"],
    params={
        "sma_length":      get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("96d",  _TF, _MUL),
    },
)
def ec_sma200_universe_filter(df, spy_df=None, **kwargs):
    """Hold whenever price > SMA200 and macro regime OK. No momentum bias.
    In bull markets holds 20-30 of 46 symbols simultaneously → naturally smooth."""
    sma_length = kwargs["sma_length"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    above_sma  = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])
    df["Signal"] = np.where(above_sma & spy_ok, 1, -1)
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC: MA Bounce + Low-Vol ATR Filter + SPY SMA96 Gate",
    dependencies=["spy"],
    params={
        "ma_length":       get_bars_for_period("50d",  _TF, _MUL),
        "filter_bars":     3,
        "gate_length":     get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("96d",  _TF, _MUL),
        "atr_period":      14,
        "max_atr_pct":     0.025,   # skip entries where ATR_14/Close > 2.5%
    },
)
def ec_ma_bounce_low_vol(df, spy_df=None, **kwargs):
    """MA Bounce with ATR volatility filter — avoids high-vol names that cause spikes."""
    df = ma_bounce_logic(df, ma_length=kwargs["ma_length"], filter_bars=kwargs["filter_bars"])
    bounce_signal = df["Signal"].copy()

    df = calculate_sma(df, length=kwargs["gate_length"])
    sma_col    = f'SMA_{kwargs["gate_length"]}'
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    # ATR-based volatility screen: true range / close
    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    df["Signal"] = np.where(
        bounce_signal == 1,
        np.where(is_uptrend & spy_ok & low_vol, 1, -1),
        -1,
    )
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC: EMA21/63 Trend + SMA200 + SPY SMA96 Gate",
    dependencies=["spy"],
    params={
        "ema_fast":        21,
        "ema_slow":        63,
        "sma_trend":       get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("96d",  _TF, _MUL),
    },
)
def ec_ema_trend(df, spy_df=None, **kwargs):
    """EMA21 > EMA63 medium-term trend — holds for weeks-to-months, no momentum spike bias."""
    ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
    sma_length = kwargs["sma_trend"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    in_trend = ema_fast > ema_slow

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(ema_slow.iloc[i]) or pd.isna(df[sma_col].iloc[i]):
            signals.append(-1)
            continue
        trend_ok = in_trend.iloc[i] and is_uptrend.iloc[i] and spy_ok.iloc[i]
        if not in_position:
            if trend_ok:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if not trend_ok:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# EC-R14 STRATEGIES — Sharpe-Optimized Smooth Curve Architecture
#
# EC-R13 finding: MA Bounce + Low-Vol ATR filter is architecturally correct.
# Sharpe 0.88 (portfolio-level) is the new proxy metric for visual smoothness.
# EC-R14 targets: Sharpe > 1.0.
#
# S1: SMA200 + Low-Vol Filter — hold all above SMA200 where ATR < 2.5%
#     (removes high-vol names that cause correlated staircase jumps)
# S2: MA Bounce + tighter ATR 1.5% — fewer but calmer entries than 2.5%
# S3: MA Bounce on ETF-only universe — inherently diversified instruments,
#     no single-stock spike risk (handled via config universe swap, strategy
#     code identical to MA Bounce + Low-Vol but threshold adjusted)
# ===========================================================================

@register_strategy(
    name="EC: SMA200 + Low-Vol Filter + SPY SMA96 Gate",
    dependencies=["spy"],
    params={
        "sma_length":      get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("96d",  _TF, _MUL),
        "atr_period":      14,
        "max_atr_pct":     0.025,
    },
)
def ec_sma200_low_vol(df, spy_df=None, **kwargs):
    """Hold whenever above SMA200 AND low-vol AND SPY gate OK.
    Removes high-volatility names from the always-hold basket → no correlated spikes."""
    sma_length = kwargs["sma_length"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    above_sma  = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    df["Signal"] = np.where(above_sma & spy_ok & low_vol, 1, -1)
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC: MA Bounce + Tight Low-Vol (1.5% ATR) + SPY SMA96 Gate",
    dependencies=["spy"],
    params={
        "ma_length":       get_bars_for_period("50d",  _TF, _MUL),
        "filter_bars":     3,
        "gate_length":     get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("96d",  _TF, _MUL),
        "atr_period":      14,
        "max_atr_pct":     0.015,   # tighter: ATR_14/Close < 1.5% (was 2.5%)
    },
)
def ec_ma_bounce_tight_low_vol(df, spy_df=None, **kwargs):
    """MA Bounce with tighter ATR threshold (1.5%) — selects only calmer names."""
    df = ma_bounce_logic(df, ma_length=kwargs["ma_length"], filter_bars=kwargs["filter_bars"])
    bounce_signal = df["Signal"].copy()

    df = calculate_sma(df, length=kwargs["gate_length"])
    sma_col    = f'SMA_{kwargs["gate_length"]}'
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    df["Signal"] = np.where(
        bounce_signal == 1,
        np.where(is_uptrend & spy_ok & low_vol, 1, -1),
        -1,
    )
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# EC-R20 STRATEGIES — Beat SPY + No Prolonged Drawdowns
#
# EC-R19 findings: Low-vol ATR filter structurally caps CAGR below SPY (selects
# boring low-return stocks by design). SPY SMA96 gate causes 1-2 year exclusion
# periods after bear markets (2022-2024 drawdown was directly caused by slow
# SPY SMA96 re-entry).
#
# EC-R20 requirements (ALL must pass):
#   1. Visually gradual increase — no staircases, no jagged upthrusts
#   2. No prolonged drawdowns (> 12 months duration)
#   3. CAGR must exceed SPY B&H return
#   4. WFA Pass (3/3), MC Score >= 4, OOS P&L positive
#
# Three architecture directions:
#   A: S&P 500 + MA Bounce (no ATR filter) + per-stock SMA200 only (no SPY gate)
#   B: S&P 500 + SMA200 hold + fast SPY SMA50 gate
#   C: S&P 500 + EMA21/63 trend + per-stock SMA200 only (no SPY gate)
# ===========================================================================

@register_strategy(
    name="EC-R20: MA Bounce + SMA200 Gate (No ATR, No SPY Gate)",
    dependencies=["spy"],
    params={
        "ma_length":   get_bars_for_period("50d",  _TF, _MUL),
        "filter_bars": 3,
        "gate_length": get_bars_for_period("200d", _TF, _MUL),
    },
)
def ec_r20_ma_bounce_no_atr(df, spy_df=None, **kwargs):
    """MA Bounce without ATR filter — all stocks eligible, no SPY macro gate.
    S&P 500 universe gives 50-100 concurrent setups; breadth smooths exits.
    Individual SMA200 per stock handles drawdown protection without slow SPY re-entry."""
    df = ma_bounce_logic(df, ma_length=kwargs["ma_length"], filter_bars=kwargs["filter_bars"])
    bounce_signal = df["Signal"].copy()
    df = calculate_sma(df, length=kwargs["gate_length"])
    sma_col    = f'SMA_{kwargs["gate_length"]}'
    is_uptrend = df["Close"] > df[sma_col]
    df["Signal"] = np.where(bounce_signal == 1, np.where(is_uptrend, 1, -1), -1)
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R20: SMA200 Hold + SPY SMA50 Gate",
    dependencies=["spy"],
    params={
        "sma_length":      get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("50d",  _TF, _MUL),
    },
)
def ec_r20_sma200_hold_spy50(df, spy_df=None, **kwargs):
    """Hold whenever stock above SMA200 AND SPY > SMA50. Always-invested approach
    with fast SPY re-entry (SMA50 clears within weeks of bear market bottom vs
    months for SMA96/SMA200). S&P 500 breadth ensures many concurrent positions."""
    sma_length = kwargs["sma_length"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    above_sma  = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])
    df["Signal"] = np.where(above_sma & spy_ok, 1, -1)
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R20: EMA21/63 Trend + SMA200 Gate (No SPY Gate)",
    dependencies=["spy"],
    params={
        "ema_fast":    21,
        "ema_slow":    63,
        "sma_trend":   get_bars_for_period("200d", _TF, _MUL),
    },
)
def ec_r20_ema_trend_no_spy(df, spy_df=None, **kwargs):
    """EMA21 > EMA63 medium-term trend with per-stock SMA200 gate, no SPY macro gate.
    Avoids the 2022-2024 prolonged exclusion caused by slow SPY SMA96 re-entry.
    S&P 500 breadth: always holds multiple concurrent positions → smooth portfolio curve."""
    ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"], adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"], adjust=False).mean()
    sma_length = kwargs["sma_trend"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    is_uptrend = df["Close"] > df[sma_col]
    in_trend   = ema_fast > ema_slow

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]):
            signals.append(-1)
            continue
        trend_ok = in_trend.iloc[i] and is_uptrend.iloc[i]
        if not in_position:
            if trend_ok:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if not trend_ok:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# EC-R21 STRATEGIES — Momentum Selection to Beat SPY
#
# EC-R20 finding: Cash drag is the structural barrier. SMA200-hold strategies
# are out of the market 30-40% of the time → cannot beat always-in SPY.
#
# Solution: Select only the MARKET'S LEADERS (top-performing stocks) so that
# the subset we hold actually beats SPY average. Academic momentum premium:
# stocks that outperform the market over 3-12 months continue to outperform.
#
# Three variants:
#   A: Relative Momentum (6m, +5% vs SPY) + SMA200 + SPY SMA50 (fast gate)
#   B: Absolute Momentum (ROC 6m > 15%) + SMA200 + SPY SMA50 (fast gate)
#   C: Relative Momentum (6m, +5% vs SPY) + SMA200 only (no SPY macro gate)
# ===========================================================================

@register_strategy(
    name="EC-R21: Relative Momentum (6m+5%) + SMA200 + SPY SMA50",
    dependencies=["spy"],
    params={
        "roc_bars":        get_bars_for_period("126d", _TF, _MUL),  # 6-month lookback
        "rel_thresh":      1.05,                                      # stock beats SPY by 5%+
        "sma_slow":        get_bars_for_period("200d", _TF, _MUL),  # per-stock uptrend gate
        "spy_gate_length": get_bars_for_period("50d",  _TF, _MUL),  # fast SPY gate
    },
)
def ec_r21_rel_momentum_spy50(df, spy_df=None, **kwargs):
    """Hold stocks that have beaten SPY by 5%+ over past 6 months AND above SMA200.
    Concentrates in market leaders → captures momentum premium → expected to beat SPY.
    Fast SPY SMA50 gate avoids prolonged bear market exposure."""
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

    is_leader   = relative > rel_thresh
    cross_up    = is_leader & ~is_leader.shift(1).fillna(False)
    is_entry    = cross_up & is_uptrend & spy_ok
    is_exit     = (relative <= 1.0) | (~is_uptrend) | (~spy_ok)

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


@register_strategy(
    name="EC-R21: Absolute Momentum (ROC 6m 15pct) + SMA200 + SPY SMA50",
    dependencies=["spy"],
    params={
        "roc_period":      get_bars_for_period("126d", _TF, _MUL),
        "roc_threshold":   15.0,
        "sma_slow":        get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("50d",  _TF, _MUL),
    },
)
def ec_r21_abs_momentum_spy50(df, spy_df=None, **kwargs):
    """Hold stocks that have risen 15%+ in the past 6 months AND above SMA200.
    Fast SPY SMA50 gate. Absolute momentum selects bull market leaders naturally."""
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


@register_strategy(
    name="EC-R21: Relative Momentum (6m+5%) + SMA200 Only (No SPY Gate)",
    dependencies=["spy"],
    params={
        "roc_bars":  get_bars_for_period("126d", _TF, _MUL),
        "rel_thresh": 1.05,
        "sma_slow":   get_bars_for_period("200d", _TF, _MUL),
    },
)
def ec_r21_rel_momentum_no_spy(df, spy_df=None, **kwargs):
    """Relative momentum (stock beats SPY 6m by 5%+) with only per-stock SMA200 gate.
    No SPY macro gate → faster recovery after bear markets. Relies on individual
    stock SMA200 filter to avoid the worst drawdowns."""
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

    is_leader   = relative > rel_thresh
    cross_up    = is_leader & ~is_leader.shift(1).fillna(False)
    is_entry    = cross_up & is_uptrend
    is_exit     = (relative <= 1.0) | (~is_uptrend)

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
# EC-R22 STRATEGIES — Many Small Positions on S&P 500 at 1.5% Allocation
#
# EC-R21 finding: concentrated positions (5% each) → visible staircase steps.
# EC-R22 hypothesis: 1.5% allocation → ~66 simultaneous positions → each
# individual exit contributes only 0.225% to portfolio (vs 0.75% at 5%).
# Steps become invisible at that scale.
#
# All three variants use:
#   - S&P 500 universe (1200+ names, ~400-600 pass ATR filter)
#   - ATR < 2.5% filter (no explosive single-stock moves)
#   - SPY SMA50 macro gate (fast exit in bear markets)
# ===========================================================================

@register_strategy(
    name="EC-R22: MA Bounce + Low-Vol ATR + SPY SMA50 [S&P500 SmallAlloc]",
    dependencies=["spy"],
    params={
        "ma_length":       get_bars_for_period("50d",  _TF, _MUL),
        "filter_bars":     3,
        "gate_length":     get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("50d",  _TF, _MUL),
        "atr_period":      14,
        "max_atr_pct":     0.025,
    },
)
def ec_r22_ma_bounce_small_alloc(df, spy_df=None, **kwargs):
    """MA Bounce + ATR<2.5% filter + SPY SMA50 gate on S&P 500.
    At 1.5% allocation: ~66 positions → each exit is <0.25% portfolio impact."""
    df = ma_bounce_logic(df, ma_length=kwargs["ma_length"], filter_bars=kwargs["filter_bars"])
    bounce_signal = df["Signal"].copy()

    df = calculate_sma(df, length=kwargs["gate_length"])
    sma_col    = f'SMA_{kwargs["gate_length"]}'
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    df["Signal"] = np.where(
        bounce_signal == 1,
        np.where(is_uptrend & spy_ok & low_vol, 1, -1),
        -1,
    )
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R22: SMA200 Hold + Low-Vol ATR + SPY SMA50 [S&P500 SmallAlloc]",
    dependencies=["spy"],
    params={
        "sma_length":      get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("50d",  _TF, _MUL),
        "atr_period":      14,
        "max_atr_pct":     0.025,
    },
)
def ec_r22_sma200_hold_small_alloc(df, spy_df=None, **kwargs):
    """Hold whenever stock above SMA200, ATR<2.5%, SPY>SMA50.
    S&P 500 + low-vol filter → 200-300 concurrent holdings at 1.5% each → smooth."""
    sma_length = kwargs["sma_length"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    above_sma  = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    df["Signal"] = np.where(above_sma & spy_ok & low_vol, 1, -1)
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R22: EMA21/63 + Low-Vol ATR + SMA200 + SPY SMA50 [S&P500 SmallAlloc]",
    dependencies=["spy"],
    params={
        "ema_fast":        21,
        "ema_slow":        63,
        "sma_trend":       get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("50d",  _TF, _MUL),
        "atr_period":      14,
        "max_atr_pct":     0.025,
    },
)
def ec_r22_ema_trend_small_alloc(df, spy_df=None, **kwargs):
    """EMA21>EMA63 medium-term trend + ATR<2.5% filter + SPY SMA50 gate on S&P 500.
    Many smooth concurrent positions via low-vol screen at 1.5% allocation."""
    ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
    sma_length = kwargs["sma_trend"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])
    in_trend   = ema_fast > ema_slow

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]) or pd.isna(atr.iloc[i]):
            signals.append(-1)
            continue
        trend_ok = in_trend.iloc[i] and is_uptrend.iloc[i] and spy_ok.iloc[i] and low_vol.iloc[i]
        if not in_position:
            if trend_ok:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if not (in_trend.iloc[i] and is_uptrend.iloc[i] and spy_ok.iloc[i]):
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# EC-R23 STRATEGIES — Sector ETF Universe (16 symbols) at 6.5% Allocation
#
# EC-R22 tests position-count smoothing on stocks. EC-R23 tests instrument-
# level smoothing: ETFs are internally diversified → no single-company event
# risk (earnings, FDA decisions, etc.) → inherently smoother price action.
#
# With 16 ETFs at 6.5% each: up to 15 concurrent positions (97.5% invested).
# In a bull market with SPY SMA50 gate ON: holds 8-14 sectors simultaneously.
# In bear market (SPY gate OFF): exits all → flat curve during crashes.
#
# All variants use sectors_etf_only.json universe.
# ===========================================================================

@register_strategy(
    name="EC-R23: MA Bounce + SMA200 + SPY SMA50 [Sectors ETF]",
    dependencies=["spy"],
    params={
        "ma_length":       get_bars_for_period("50d",  _TF, _MUL),
        "filter_bars":     3,
        "gate_length":     get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("50d",  _TF, _MUL),
    },
)
def ec_r23_ma_bounce_etf(df, spy_df=None, **kwargs):
    """MA Bounce on sector ETFs with SMA200 + SPY SMA50 gate.
    No ATR filter — ETFs are inherently low-vol vs individual stocks."""
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
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R23: EMA21/63 Trend + SMA200 + SPY SMA50 [Sectors ETF]",
    dependencies=["spy"],
    params={
        "ema_fast":        21,
        "ema_slow":        63,
        "sma_trend":       get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("50d",  _TF, _MUL),
    },
)
def ec_r23_ema_trend_etf(df, spy_df=None, **kwargs):
    """EMA21>EMA63 medium-term trend on sector ETFs.
    ETF universe → smoother trend signals, no gap-risk from single-stock events."""
    ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
    sma_length = kwargs["sma_trend"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])
    in_trend   = ema_fast > ema_slow

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]):
            signals.append(-1)
            continue
        trend_ok = in_trend.iloc[i] and is_uptrend.iloc[i] and spy_ok.iloc[i]
        if not in_position:
            if trend_ok:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if not trend_ok:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R23: SMA200 Hold + SPY SMA50 [Sectors ETF]",
    dependencies=["spy"],
    params={
        "sma_length":      get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("50d",  _TF, _MUL),
    },
)
def ec_r23_sma200_hold_etf(df, spy_df=None, **kwargs):
    """Hold sector ETF whenever above SMA200 and SPY > SMA50.
    Maximises invested time in sectors trending up → minimal cash drag on 16 ETFs."""
    sma_length = kwargs["sma_length"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    above_sma  = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])
    df["Signal"] = np.where(above_sma & spy_ok, 1, -1)
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# EC-R24 STRATEGIES — Proven EC-R19 Signal on S&P 500 at Reduced Allocation
#
# EC-R22 and EC-R23 findings:
#  - Small-allocation on S&P 500: SMA200 Hold was smoother than MA Bounce
#  - Sector ETFs: too few symbols → more correlated exits → worse curve
#  - Root SPY-gate problem: mass coordinated exits cause the biggest steps
#
# EC-R24 hypothesis: Apply EC-R19's proven architecture (MA Bounce + Low-Vol
# ATR 2.5% + SPY SMA96 gate) to the S&P 500 universe at 2.5% allocation.
#   - 2.5% alloc → ~40 concurrent positions → each step = 2.5% × gain (small)
#   - S&P 500 → more qualifying stocks in choppy 2014-2017 → fills plateau gap
#   - SPY SMA96 gate preserved (proven bear-market protection from EC-R19)
#
# Also test SMA200 Hold on same universe — EC-R22 showed SMA200 Hold smoother
# than MA Bounce at small allocations.
# ===========================================================================

@register_strategy(
    name="EC-R24: MA Bounce + Low-Vol ATR + SPY SMA96 [S&P500 2.5%]",
    dependencies=["spy"],
    params={
        "ma_length":       get_bars_for_period("50d",  _TF, _MUL),
        "filter_bars":     3,
        "gate_length":     get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("96d",  _TF, _MUL),
        "atr_period":      14,
        "max_atr_pct":     0.025,
    },
)
def ec_r24_ma_bounce_sp500_medium_alloc(df, spy_df=None, **kwargs):
    """EC-R19's proven signal (MA Bounce + ATR<2.5% + SPY SMA96) on S&P 500 at 2.5%.
    More qualifying stocks than Sectors+DJI 46 → fills 2014-2017 plateau.
    Smaller allocation → steps are smaller in absolute portfolio impact."""
    df = ma_bounce_logic(df, ma_length=kwargs["ma_length"], filter_bars=kwargs["filter_bars"])
    bounce_signal = df["Signal"].copy()

    df = calculate_sma(df, length=kwargs["gate_length"])
    sma_col    = f'SMA_{kwargs["gate_length"]}'
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    df["Signal"] = np.where(
        bounce_signal == 1,
        np.where(is_uptrend & spy_ok & low_vol, 1, -1),
        -1,
    )
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R24: SMA200 Hold + Low-Vol ATR + SPY SMA96 [S&P500 2.5%]",
    dependencies=["spy"],
    params={
        "sma_length":      get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("96d",  _TF, _MUL),
        "atr_period":      14,
        "max_atr_pct":     0.025,
    },
)
def ec_r24_sma200_hold_sp500_medium_alloc(df, spy_df=None, **kwargs):
    """SMA200 Hold + ATR<2.5% + SPY SMA96 on S&P 500 at 2.5%.
    Always-in when above SMA200 → no bounce-timing correlation → more distributed exits.
    EC-R22 showed SMA200 Hold smoother than MA Bounce at small allocations."""
    sma_length = kwargs["sma_length"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    above_sma  = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    df["Signal"] = np.where(above_sma & spy_ok & low_vol, 1, -1)
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R24: EMA21/63 + Low-Vol ATR + SPY SMA96 [S&P500 2.5%]",
    dependencies=["spy"],
    params={
        "ema_fast":        21,
        "ema_slow":        63,
        "sma_trend":       get_bars_for_period("200d", _TF, _MUL),
        "spy_gate_length": get_bars_for_period("96d",  _TF, _MUL),
        "atr_period":      14,
        "max_atr_pct":     0.025,
    },
)
def ec_r24_ema_trend_sp500_medium_alloc(df, spy_df=None, **kwargs):
    """EMA21>EMA63 trend + ATR<2.5% + SMA200 + SPY SMA96 on S&P 500 at 2.5%.
    Medium-term trend signal avoids short-duration spike trades that cause visible steps."""
    ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
    sma_length = kwargs["sma_trend"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    is_uptrend = df["Close"] > df[sma_col]
    spy_ok     = _spy_regime_ok(spy_df, df.index, kwargs["spy_gate_length"])
    in_trend   = ema_fast > ema_slow

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]) or pd.isna(atr.iloc[i]):
            signals.append(-1)
            continue
        trend_ok = in_trend.iloc[i] and is_uptrend.iloc[i] and spy_ok.iloc[i] and low_vol.iloc[i]
        if not in_position:
            if trend_ok:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if not (in_trend.iloc[i] and is_uptrend.iloc[i] and spy_ok.iloc[i]):
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# EC-R25 STRATEGIES — No SPY Macro Gate (Per-Stock SMA200 Only)
#
# EC-R24 finding: SPY SMA96 gate creates 2+ year flat periods (2007-2010,
# 2022) that look like deliberate crash-avoidance → "suspect" / overfit.
#
# EC-R25 hypothesis: Remove the SPY macro gate entirely. Each stock exits
# ONLY when it individually falls below its own SMA200. No coordinated
# mass exit → no flat periods. The 2008-2009 period will show a real
# drawdown (honest) from low-vol stocks declining, then recovery.
#
# A modest real drawdown (15-25%) that recovers is more credible and
# visually smoother over the full cycle than a 2-year flat line.
#
# Universe: S&P 500, 2.5% allocation, start 1993-01-01.
# ===========================================================================

@register_strategy(
    name="EC-R25: MA Bounce + Low-Vol ATR (No SPY Gate) [S&P500 2.5%]",
    dependencies=[],
    params={
        "ma_length":   get_bars_for_period("50d",  _TF, _MUL),
        "filter_bars": 3,
        "gate_length": get_bars_for_period("200d", _TF, _MUL),
        "atr_period":  14,
        "max_atr_pct": 0.025,
    },
)
def ec_r25_ma_bounce_no_gate(df, **kwargs):
    """MA Bounce + ATR<2.5% + per-stock SMA200 only. No SPY macro gate.
    Eliminates the 2007-2010 flat period. Shows honest participation in
    bear markets through low-vol stock selection. Not regime-gated."""
    df = ma_bounce_logic(df, ma_length=kwargs["ma_length"], filter_bars=kwargs["filter_bars"])
    bounce_signal = df["Signal"].copy()

    df = calculate_sma(df, length=kwargs["gate_length"])
    sma_col    = f'SMA_{kwargs["gate_length"]}'
    is_uptrend = df["Close"] > df[sma_col]

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    df["Signal"] = np.where(
        bounce_signal == 1,
        np.where(is_uptrend & low_vol, 1, -1),
        -1,
    )
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R25: SMA200 Hold + Low-Vol ATR (No SPY Gate) [S&P500 2.5%]",
    dependencies=[],
    params={
        "sma_length":  get_bars_for_period("200d", _TF, _MUL),
        "atr_period":  14,
        "max_atr_pct": 0.025,
    },
)
def ec_r25_sma200_hold_no_gate(df, **kwargs):
    """Hold whenever stock above SMA200 AND ATR<2.5%. No SPY macro gate.
    Always-in for low-vol uptrending stocks. In 2008-2009, stocks exit
    individually as they fall below SMA200 — staggered not simultaneous."""
    sma_length = kwargs["sma_length"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    above_sma  = df["Close"] > df[sma_col]

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    df["Signal"] = np.where(above_sma & low_vol, 1, -1)
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R25: EMA21/63 + Low-Vol ATR (No SPY Gate) [S&P500 2.5%]",
    dependencies=[],
    params={
        "ema_fast":    21,
        "ema_slow":    63,
        "sma_trend":   get_bars_for_period("200d", _TF, _MUL),
        "atr_period":  14,
        "max_atr_pct": 0.025,
    },
)
def ec_r25_ema_trend_no_gate(df, **kwargs):
    """EMA21>EMA63 + SMA200 + ATR<2.5%, no SPY macro gate.
    Medium-term trend on low-vol stocks — exits distributed across time."""
    ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
    sma_length = kwargs["sma_trend"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    is_uptrend = df["Close"] > df[sma_col]
    in_trend   = ema_fast > ema_slow

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]) or pd.isna(atr.iloc[i]):
            signals.append(-1)
            continue
        entry_ok = in_trend.iloc[i] and is_uptrend.iloc[i] and low_vol.iloc[i]
        exit_ok  = not in_trend.iloc[i] or not is_uptrend.iloc[i]
        if not in_position:
            if entry_ok:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if exit_ok:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# EC-R27 STRATEGIES — Longer EMA Periods on Sectors+DJI 46 (No SPY Gate)
#
# EC-R26 finding: EMA21/63 no-gate on Sectors+DJI 46 is the best visual
# candidate (Calmar 0.41, MaxDD 15.82%, OOS +287%, WFA Pass 3/3).
# The 2010-2020 section of the equity curve is genuinely close to a steady
# incline. Remaining visible steps come from short-duration trend reversals.
#
# EC-R27 hypothesis: Longer EMA windows (30/90, 40/120) hold positions longer.
# Fewer exit events → fewer "step" moments → potentially smoother curve.
# The tradeoff: slower to exit in downturns → potentially larger MaxDD.
#
# Also test EMA21/63 on Sectors+DJI 46 at 3.5% allocation (more CAGR).
# ===========================================================================

@register_strategy(
    name="EC-R27: EMA30/90 + Low-Vol ATR (No Gate) [DJI46]",
    dependencies=[],
    params={
        "ema_fast":    30,
        "ema_slow":    90,
        "sma_trend":   get_bars_for_period("200d", _TF, _MUL),
        "atr_period":  14,
        "max_atr_pct": 0.025,
    },
)
def ec_r27_ema30_90_no_gate(df, **kwargs):
    """EMA30>EMA90 medium-long trend + ATR<2.5% + SMA200. No SPY macro gate.
    Longer EMA window → holds positions longer → fewer exit events → smoother curve.
    Targeted at Sectors+DJI 46 universe which has smooth-moving instruments."""
    ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
    sma_length = kwargs["sma_trend"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    is_uptrend = df["Close"] > df[sma_col]
    in_trend   = ema_fast > ema_slow

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]) or pd.isna(atr.iloc[i]):
            signals.append(-1)
            continue
        entry_ok = in_trend.iloc[i] and is_uptrend.iloc[i] and low_vol.iloc[i]
        exit_ok  = not in_trend.iloc[i] or not is_uptrend.iloc[i]
        if not in_position:
            if entry_ok:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if exit_ok:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R27: EMA40/120 + Low-Vol ATR (No Gate) [DJI46]",
    dependencies=[],
    params={
        "ema_fast":    40,
        "ema_slow":    120,
        "sma_trend":   get_bars_for_period("200d", _TF, _MUL),
        "atr_period":  14,
        "max_atr_pct": 0.025,
    },
)
def ec_r27_ema40_120_no_gate(df, **kwargs):
    """EMA40>EMA120 long trend + ATR<2.5% + SMA200. No SPY macro gate.
    Even longer EMA window → fewest exit events → most gradual curve possible
    within the EMA trend-following architecture."""
    ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
    sma_length = kwargs["sma_trend"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    is_uptrend = df["Close"] > df[sma_col]
    in_trend   = ema_fast > ema_slow

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]) or pd.isna(atr.iloc[i]):
            signals.append(-1)
            continue
        entry_ok = in_trend.iloc[i] and is_uptrend.iloc[i] and low_vol.iloc[i]
        exit_ok  = not in_trend.iloc[i] or not is_uptrend.iloc[i]
        if not in_position:
            if entry_ok:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if exit_ok:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R27: EMA50/150 + Low-Vol ATR (No Gate) [DJI46]",
    dependencies=[],
    params={
        "ema_fast":    50,
        "ema_slow":    150,
        "sma_trend":   get_bars_for_period("200d", _TF, _MUL),
        "atr_period":  14,
        "max_atr_pct": 0.025,
    },
)
def ec_r27_ema50_150_no_gate(df, **kwargs):
    """EMA50>EMA150 very long trend + ATR<2.5% + SMA200. No SPY macro gate.
    50/150 is analogous to the classic 10/30 week system on daily bars.
    Very infrequent exits → minimum step events in the portfolio curve."""
    ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
    sma_length = kwargs["sma_trend"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    is_uptrend = df["Close"] > df[sma_col]
    in_trend   = ema_fast > ema_slow

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]) or pd.isna(atr.iloc[i]):
            signals.append(-1)
            continue
        entry_ok = in_trend.iloc[i] and is_uptrend.iloc[i] and low_vol.iloc[i]
        exit_ok  = not in_trend.iloc[i] or not is_uptrend.iloc[i]
        if not in_position:
            if entry_ok:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if exit_ok:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# EC-R28/R29 STRATEGIES — Law of Large Numbers + Tighter Volatility Filter
#
# EC-R27 finding: EMA50/150 on Sectors+DJI 46 is closest to steady incline
# but visible step-up moves remain in 2017-2020. Root cause: 46 symbols are
# too few and too correlated — many exit/enter simultaneously in strong
# market moves, creating portfolio-level steps.
#
# Two new directions:
# EC-R28: Russell Top 200 at 1% alloc → 100+ concurrent positions →
#   each step = 1% × avg_gain ≈ 0.15% → imperceptible individually.
#   Law of large numbers should smooth the portfolio return distribution.
#
# EC-R29: Tighter ATR filter (1.5% vs 2.5%) on Sectors+DJI 46 →
#   only the calmest 15-20 of 46 stocks qualify at any time →
#   smaller individual stock moves → smaller portfolio steps.
#
# Both use EMA50/150 (best performer from EC-R27) and no SPY macro gate.
# ===========================================================================

@register_strategy(
    name="EC-R28: EMA50/150 + Tight ATR 1.5% (No Gate) [Russell200 1%]",
    dependencies=[],
    params={
        "ema_fast":    50,
        "ema_slow":    150,
        "sma_trend":   get_bars_for_period("200d", _TF, _MUL),
        "atr_period":  14,
        "max_atr_pct": 0.015,   # 1.5% — tighter than 2.5%
    },
)
def ec_r28_ema50_150_tight_atr(df, **kwargs):
    """EMA50>EMA150 + ATR<1.5% + SMA200. No SPY macro gate.
    Tighter ATR filter selects only the calmest stocks. At 1% allocation on
    Russell Top 200, law of large numbers smooths the aggregate portfolio curve."""
    ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
    sma_length = kwargs["sma_trend"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    is_uptrend = df["Close"] > df[sma_col]
    in_trend   = ema_fast > ema_slow

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]) or pd.isna(atr.iloc[i]):
            signals.append(-1)
            continue
        entry_ok = in_trend.iloc[i] and is_uptrend.iloc[i] and low_vol.iloc[i]
        exit_ok  = not in_trend.iloc[i] or not is_uptrend.iloc[i]
        if not in_position:
            if entry_ok:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if exit_ok:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R28: EMA50/150 + ATR 2.5% (No Gate) [Russell200 1%]",
    dependencies=[],
    params={
        "ema_fast":    50,
        "ema_slow":    150,
        "sma_trend":   get_bars_for_period("200d", _TF, _MUL),
        "atr_period":  14,
        "max_atr_pct": 0.025,   # standard 2.5%
    },
)
def ec_r28_ema50_150_standard_atr(df, **kwargs):
    """EMA50>EMA150 + ATR<2.5% + SMA200. No SPY macro gate.
    Same params as EC-R27 champion on Russell Top 200 at 1% alloc.
    100+ concurrent positions → law of large numbers portfolio smoothing."""
    ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
    sma_length = kwargs["sma_trend"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    is_uptrend = df["Close"] > df[sma_col]
    in_trend   = ema_fast > ema_slow

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]) or pd.isna(atr.iloc[i]):
            signals.append(-1)
            continue
        entry_ok = in_trend.iloc[i] and is_uptrend.iloc[i] and low_vol.iloc[i]
        exit_ok  = not in_trend.iloc[i] or not is_uptrend.iloc[i]
        if not in_position:
            if entry_ok:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if exit_ok:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R29: EMA50/150 + Tight ATR 1.5% (No Gate) [DJI46]",
    dependencies=[],
    params={
        "ema_fast":    50,
        "ema_slow":    150,
        "sma_trend":   get_bars_for_period("200d", _TF, _MUL),
        "atr_period":  14,
        "max_atr_pct": 0.015,   # tighter: 1.5% vs 2.5%
    },
)
def ec_r29_ema50_150_tight_dji46(df, **kwargs):
    """EMA50>EMA150 + ATR<1.5% + SMA200. No SPY macro gate.
    Tighter ATR on Sectors+DJI 46: only the calmest 15-20 of 46 instruments.
    Smaller individual stock moves → smaller portfolio steps on each exit."""
    ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
    sma_length = kwargs["sma_trend"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    is_uptrend = df["Close"] > df[sma_col]
    in_trend   = ema_fast > ema_slow

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]) or pd.isna(atr.iloc[i]):
            signals.append(-1)
            continue
        entry_ok = in_trend.iloc[i] and is_uptrend.iloc[i] and low_vol.iloc[i]
        exit_ok  = not in_trend.iloc[i] or not is_uptrend.iloc[i]
        if not in_position:
            if entry_ok:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            if exit_ok:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# EC-R32 STRATEGIES — Trailing Stop Exit to Stagger Exits
#
# EC-R28/R31 finding: correlated EMA crossovers still create visible steps
# because many stocks cross their EMA threshold simultaneously in strong
# market moves. Individual positions have NO independent exit timing.
#
# EC-R32 hypothesis: Replace the EMA exit signal with a TRAILING STOP
# exit (price falls X×ATR below 30-day rolling high). Each position has
# its OWN 30-day high → exits at DIFFERENT times based on each stock's
# individual price action → staggered exits → smoother portfolio curve.
#
# Entry: EMA50>EMA150 AND ATR<2.5% AND above SMA200 (same as EC-R28)
# Exit: price falls 2×ATR below its rolling 30-day high OR SMA200 breach
#   — The 2×ATR trailing stop fires at different times per stock
#   — SMA200 is the hard safety net for prolonged downtrends
# ===========================================================================

@register_strategy(
    name="EC-R32: EMA50/150 + Trailing ATR Stop (No Gate) [Russell200 1%]",
    dependencies=[],
    params={
        "ema_fast":         50,
        "ema_slow":         150,
        "sma_trend":        get_bars_for_period("200d", _TF, _MUL),
        "atr_period":       14,
        "max_atr_pct":      0.025,
        "trail_window":     30,
        "trail_atr_mult":   2.0,
    },
)
def ec_r32_ema_trailing_stop(df, **kwargs):
    """EMA50>EMA150 entry + ATR trailing stop exit. No SPY macro gate.
    Key difference: each position exits when IT personally falls 2×ATR below
    its own 30-day high — staggered timing vs simultaneous EMA crossover.
    SMA200 is the secondary exit for prolonged downtrends."""
    ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
    sma_length = kwargs["sma_trend"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    is_uptrend = df["Close"] > df[sma_col]
    in_trend   = ema_fast > ema_slow

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

    trail_window  = kwargs["trail_window"]
    trail_mult    = kwargs["trail_atr_mult"]

    signals = []
    in_position   = False
    entry_high    = None

    for i in range(len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]) or pd.isna(atr.iloc[i]):
            signals.append(-1)
            continue

        close = df["Close"].iloc[i]
        atr_i = atr.iloc[i]

        if not in_position:
            entry_ok = in_trend.iloc[i] and is_uptrend.iloc[i] and low_vol.iloc[i]
            if entry_ok:
                in_position = True
                entry_high  = close
                signals.append(1)
            else:
                signals.append(-1)
        else:
            # Update rolling high since entry
            start = max(0, i - trail_window + 1)
            rolling_high = df["Close"].iloc[start:i+1].max()
            trailing_stop = rolling_high - trail_mult * atr_i

            # Exit conditions
            trail_hit  = close < trailing_stop
            sma_exit   = not is_uptrend.iloc[i]

            if trail_hit or sma_exit:
                in_position = False
                entry_high  = None
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


@register_strategy(
    name="EC-R32: EMA50/150 + Trailing ATR Stop 3x (No Gate) [Russell200 1%]",
    dependencies=[],
    params={
        "ema_fast":         50,
        "ema_slow":         150,
        "sma_trend":        get_bars_for_period("200d", _TF, _MUL),
        "atr_period":       14,
        "max_atr_pct":      0.025,
        "trail_window":     30,
        "trail_atr_mult":   3.0,
    },
)
def ec_r32_ema_trailing_stop_wide(df, **kwargs):
    """Same as EC-R32 but 3×ATR trailing stop (wider = fewer exits = longer holds).
    Wider stop allows more room for normal volatility before exiting."""
    ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
    ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
    sma_length = kwargs["sma_trend"]
    df         = calculate_sma(df, sma_length)
    sma_col    = f"SMA_{sma_length}"
    is_uptrend = df["Close"] > df[sma_col]

    hl  = df["High"] - df["Low"]
    hpc = (df["High"] - df["Close"].shift(1)).abs()
    lpc = (df["Low"]  - df["Close"].shift(1)).abs()
    tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    atr = tr.rolling(kwargs["atr_period"]).mean()
    low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]
    in_trend = ema_fast > ema_slow

    trail_window = kwargs["trail_window"]
    trail_mult   = kwargs["trail_atr_mult"]

    signals = []
    in_position = False
    for i in range(len(df)):
        if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]) or pd.isna(atr.iloc[i]):
            signals.append(-1)
            continue
        close = df["Close"].iloc[i]
        atr_i = atr.iloc[i]

        if not in_position:
            if in_trend.iloc[i] and is_uptrend.iloc[i] and low_vol.iloc[i]:
                in_position = True
                signals.append(1)
            else:
                signals.append(-1)
        else:
            start = max(0, i - trail_window + 1)
            rolling_high = df["Close"].iloc[start:i+1].max()
            trail_hit  = close < (rolling_high - trail_mult * atr_i)
            sma_exit   = not is_uptrend.iloc[i]
            if trail_hit or sma_exit:
                in_position = False
                signals.append(-1)
            else:
                signals.append(1)

    df["Signal"] = signals
    df.drop(columns=[sma_col], errors="ignore", inplace=True)
    return df


# ===========================================================================
# EC-R33 STRATEGIES — Weekly Bars on Russell Top 200 (No SPY Gate)
#
# Daily EMA strategies still have correlated exits in strong trending
# markets because many stocks cross their daily EMA simultaneously.
#
# Weekly bars fundamentally change the exit frequency:
#   - 52 signal opportunities per year vs 252 for daily
#   - Each position held for weeks to months per bar
#   - Exits happen at MOST once per week per stock → much less correlated
#   - Portfolio equity shows smoother progression with fewer discrete steps
#
# Parameters for weekly bars:
#   - EMA12w (12 weeks ≈ 3 months) / EMA26w (26 weeks ≈ 6 months)
#   - ATR filter: weekly ATR < 8% (weekly ATR ≈ √5 × daily ATR ≈ 5.6% for 2.5% daily)
#   - SMA40w (40 weeks ≈ 200 days) as trend filter
#
# Note: These strategies are weekly-only. Config must set timeframe="W".
# ===========================================================================

if _TF == "W":
    @register_strategy(
        name="EC-R33: EMA12w/26w + ATR 8% (No Gate) [Russell200 weekly]",
        dependencies=[],
        params={
            "ema_fast":    12,    # 12 weeks ≈ 3 months
            "ema_slow":    26,    # 26 weeks ≈ 6 months
            "sma_trend":   40,    # 40 weeks ≈ 200 trading days
            "atr_period":  14,    # 14-week ATR
            "max_atr_pct": 0.08,  # 8% weekly ATR ≈ 2.5% daily ATR × √5
        },
    )
    def ec_r33_ema_weekly_12_26(df, **kwargs):
        """EMA12w>EMA26w + weekly ATR<8% + SMA40w. No SPY gate. Weekly bars.
        Weekly signals mean exits happen at most once per week per stock.
        Much less correlated with other stocks → smoother portfolio curve."""
        ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
        ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
        sma_length = kwargs["sma_trend"]
        df         = calculate_sma(df, sma_length)
        sma_col    = f"SMA_{sma_length}"
        is_uptrend = df["Close"] > df[sma_col]
        in_trend   = ema_fast > ema_slow

        hl  = df["High"] - df["Low"]
        hpc = (df["High"] - df["Close"].shift(1)).abs()
        lpc = (df["Low"]  - df["Close"].shift(1)).abs()
        tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
        atr = tr.rolling(kwargs["atr_period"]).mean()
        low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

        signals = []
        in_position = False
        for i in range(len(df)):
            if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]) or pd.isna(atr.iloc[i]):
                signals.append(-1)
                continue
            entry_ok = in_trend.iloc[i] and is_uptrend.iloc[i] and low_vol.iloc[i]
            exit_ok  = not in_trend.iloc[i] or not is_uptrend.iloc[i]
            if not in_position:
                if entry_ok:
                    in_position = True
                    signals.append(1)
                else:
                    signals.append(-1)
            else:
                if exit_ok:
                    in_position = False
                    signals.append(-1)
                else:
                    signals.append(1)

        df["Signal"] = signals
        df.drop(columns=[sma_col], errors="ignore", inplace=True)
        return df

    @register_strategy(
        name="EC-R33: EMA21w/52w + ATR 8% (No Gate) [Russell200 weekly]",
        dependencies=[],
        params={
            "ema_fast":    21,    # 21 weeks ≈ 5 months
            "ema_slow":    52,    # 52 weeks = 1 year
            "sma_trend":   104,   # 104 weeks = 2 years (longer than SMA200d on weekly)
            "atr_period":  14,
            "max_atr_pct": 0.08,
        },
    )
    def ec_r33_ema_weekly_21_52(df, **kwargs):
        """EMA21w>EMA52w + weekly ATR<8% + SMA104w. No SPY gate. Weekly bars.
        Longer 21w/52w trend windows = hold positions even longer → fewer exits."""
        ema_fast   = df["Close"].ewm(span=kwargs["ema_fast"],  adjust=False).mean()
        ema_slow   = df["Close"].ewm(span=kwargs["ema_slow"],  adjust=False).mean()
        sma_length = kwargs["sma_trend"]
        df         = calculate_sma(df, sma_length)
        sma_col    = f"SMA_{sma_length}"
        is_uptrend = df["Close"] > df[sma_col]
        in_trend   = ema_fast > ema_slow

        hl  = df["High"] - df["Low"]
        hpc = (df["High"] - df["Close"].shift(1)).abs()
        lpc = (df["Low"]  - df["Close"].shift(1)).abs()
        tr  = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
        atr = tr.rolling(kwargs["atr_period"]).mean()
        low_vol = (atr / df["Close"]) < kwargs["max_atr_pct"]

        signals = []
        in_position = False
        for i in range(len(df)):
            if pd.isna(ema_fast.iloc[i]) or pd.isna(df[sma_col].iloc[i]) or pd.isna(atr.iloc[i]):
                signals.append(-1)
                continue
            entry_ok = in_trend.iloc[i] and is_uptrend.iloc[i] and low_vol.iloc[i]
            exit_ok  = not in_trend.iloc[i] or not is_uptrend.iloc[i]
            if not in_position:
                if entry_ok:
                    in_position = True
                    signals.append(1)
                else:
                    signals.append(-1)
            else:
                if exit_ok:
                    in_position = False
                    signals.append(-1)
                else:
                    signals.append(1)

        df["Signal"] = signals
        df.drop(columns=[sma_col], errors="ignore", inplace=True)
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
