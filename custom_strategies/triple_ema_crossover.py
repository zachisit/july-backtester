# custom_strategies/triple_ema_crossover.py
"""Triple EMA Crossover strategy — progressive filter variants.

Signal logic:
  Entry (1): fast EMA crosses above BOTH mid and slow EMAs (all three align bullishly).
  Exit (-1): fast EMA crosses below BOTH mid and slow EMAs (all three flip bearish).

Variants tested in order of complexity:
  V1 — bare triple EMA cross (5/13/50, 8/21/55, 10/20/50)
  V2 — + same-timeframe 200-bar trend filter (TF suffix)
  V3 — + daily HTF trend + ATR volatility expansion + 9:30-11am NYC session gate (PRO suffix)

Research context: replicating a $2M/yr discretionary trader's 3-EMA approach on
2H Polygon data. V1/V2 tested on US equities and 7 forex majors (2021-2026).
V3 adds the three discretionary filters the trader uses implicitly.
"""

import pandas as pd
import numpy as np
from helpers.registry import register_strategy
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _ema_cross_buy_sell(df, fast, mid, slow):
    """Return (buy, sell) boolean Series for the triple-cross signal."""
    f  = df["Close"].ewm(span=fast, adjust=False).mean()
    m  = df["Close"].ewm(span=mid,  adjust=False).mean()
    s  = df["Close"].ewm(span=slow, adjust=False).mean()
    fp, mp, sp = f.shift(1), m.shift(1), s.shift(1)
    buy  = ((fp <= mp) & (f > m) | (fp <= sp) & (f > s)) & (f > m) & (f > s)
    sell = ((fp >= mp) & (f < m) | (fp >= sp) & (f < s)) & (f < m) & (f < s)
    return buy, sell, f, m, s


def _daily_ema(df, span):
    """Resample 2H closes to daily, compute EMA, forward-fill back to 2H index."""
    daily = df["Close"].resample("1D").last().dropna()
    ema   = daily.ewm(span=span, adjust=False).mean()
    return ema.reindex(df.index, method="ffill")


def _nyc_session_mask(index, start_hour=8, end_hour=12):
    """Boolean mask for 2H bars whose start falls inside the NYC session window.

    9:30-11am NYC maps to 8am-12pm on a 2H bar grid (closest even-hour boundaries).
    """
    if index.tz is None:
        nyc_idx = index.tz_localize("UTC").tz_convert("America/New_York")
    else:
        nyc_idx = index.tz_convert("America/New_York")
    h = nyc_idx.hour
    return pd.Series((h >= start_hour) & (h < end_hour), index=index)


def _volatility_mask(df, atr_window=14, avg_window=50):
    """True when the rolling ATR is above its own rolling mean (volatility expanding)."""
    if "High" in df.columns and "Low" in df.columns:
        rng = df["High"] - df["Low"]
    else:
        rng = df["Close"].diff().abs()
    atr = rng.rolling(atr_window).mean()
    return atr > atr.rolling(avg_window).mean()


def _to_signal(buy, sell):
    sig = np.where(buy, 1, np.where(sell, -1, 0))
    return pd.Series(sig, index=buy.index).replace(0, np.nan).ffill().fillna(0)


# ---------------------------------------------------------------------------
# V1 — bare triple EMA (no filters)
# ---------------------------------------------------------------------------

def _v1(df, fast, mid, slow):
    df = df.copy()
    buy, sell, *_ = _ema_cross_buy_sell(df, fast, mid, slow)
    df["Signal"] = _to_signal(buy, sell)
    return df


@register_strategy(name="Triple EMA (5/13/50)",  dependencies=[], params={"fast": 5,  "mid": 13, "slow": 50})
def triple_ema_5_13_50(df, **kw):  return _v1(df, kw["fast"], kw["mid"], kw["slow"])

@register_strategy(name="Triple EMA (8/21/55)",  dependencies=[], params={"fast": 8,  "mid": 21, "slow": 55})
def triple_ema_8_21_55(df, **kw):  return _v1(df, kw["fast"], kw["mid"], kw["slow"])

@register_strategy(name="Triple EMA (10/20/50)", dependencies=[], params={"fast": 10, "mid": 20, "slow": 50})
def triple_ema_10_20_50(df, **kw): return _v1(df, kw["fast"], kw["mid"], kw["slow"])


# ---------------------------------------------------------------------------
# V2 — + same-timeframe 200-bar trend filter
# ---------------------------------------------------------------------------

def _v2(df, fast, mid, slow, trend=200):
    df = df.copy()
    buy, sell, *_ = _ema_cross_buy_sell(df, fast, mid, slow)
    trend_ema = df["Close"].ewm(span=trend, adjust=False).mean()
    buy = buy & (df["Close"] > trend_ema)
    df["Signal"] = _to_signal(buy, sell)
    return df


@register_strategy(name="Triple EMA (5/13/50) TF",  dependencies=[], params={"fast": 5,  "mid": 13, "slow": 50, "trend": 200})
def triple_ema_5_13_50_tf(df, **kw):  return _v2(df, kw["fast"], kw["mid"], kw["slow"], kw["trend"])

@register_strategy(name="Triple EMA (8/21/55) TF",  dependencies=[], params={"fast": 8,  "mid": 21, "slow": 55, "trend": 200})
def triple_ema_8_21_55_tf(df, **kw):  return _v2(df, kw["fast"], kw["mid"], kw["slow"], kw["trend"])

@register_strategy(name="Triple EMA (10/20/50) TF", dependencies=[], params={"fast": 10, "mid": 20, "slow": 50, "trend": 200})
def triple_ema_10_20_50_tf(df, **kw): return _v2(df, kw["fast"], kw["mid"], kw["slow"], kw["trend"])


# ---------------------------------------------------------------------------
# V3 — + daily HTF trend + ATR volatility expansion + NYC session gate
#
# Entry gates (all must be true):
#   1. Triple EMA cross bullish alignment
#   2. Close > daily 50-bar EMA (higher timeframe trend)
#   3. 14-bar ATR > 50-bar rolling ATR mean (volatility expanding)
#   4. Bar opens inside 8am-12pm NYC (captures 9:30-11am on 2H grid)
#
# Exits: fire unconditionally on bearish triple-cross.
# ---------------------------------------------------------------------------

def _v3(df, fast, mid, slow, htf_span=50, atr_window=14, avg_window=50):
    df = df.copy()
    buy, sell, *_ = _ema_cross_buy_sell(df, fast, mid, slow)

    # Gate 1: daily HTF trend
    htf = _daily_ema(df, htf_span)
    buy = buy & (df["Close"] > htf)

    # Gate 2: volatility expansion
    buy = buy & _volatility_mask(df, atr_window, avg_window)

    # Gate 3: NYC session (9:30-11am → 8am-12pm on 2H grid)
    try:
        session = _nyc_session_mask(df.index)
        buy = buy & session
    except Exception:
        # If timezone conversion fails (e.g. naive non-UTC index), skip gate silently
        pass

    df["Signal"] = _to_signal(buy, sell)
    return df


@register_strategy(
    name="Triple EMA (5/13/50) PRO",
    dependencies=[],
    params={"fast": 5, "mid": 13, "slow": 50, "htf_span": 50, "atr_window": 14, "avg_window": 50},
)
def triple_ema_5_13_50_pro(df, **kw):
    return _v3(df, kw["fast"], kw["mid"], kw["slow"],
               kw["htf_span"], kw["atr_window"], kw["avg_window"])


@register_strategy(
    name="Triple EMA (8/21/55) PRO",
    dependencies=[],
    params={"fast": 8, "mid": 21, "slow": 55, "htf_span": 50, "atr_window": 14, "avg_window": 50},
)
def triple_ema_8_21_55_pro(df, **kw):
    return _v3(df, kw["fast"], kw["mid"], kw["slow"],
               kw["htf_span"], kw["atr_window"], kw["avg_window"])


@register_strategy(
    name="Triple EMA (10/20/50) PRO",
    dependencies=[],
    params={"fast": 10, "mid": 20, "slow": 50, "htf_span": 50, "atr_window": 14, "avg_window": 50},
)
def triple_ema_10_20_50_pro(df, **kw):
    return _v3(df, kw["fast"], kw["mid"], kw["slow"],
               kw["htf_span"], kw["atr_window"], kw["avg_window"])
