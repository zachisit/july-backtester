# custom_strategies/rsi_divergence_v2.py
"""RSI/price divergence v2 — trend-filtered, breakout-confirmed, let-winners-run.

Fixes the three weaknesses of the v1 divergence strategy
(custom_strategies/rsi_divergence.py):

  1. Exit  — v1 exited on the *opposite* divergence, chopping winners off mid
             trend. v2 emits NO strategy exit on strength; it holds and lets the
             engine's **ATR trailing stop** (stop_loss_configs, type="atr") ratchet
             up behind price. A secondary trend-break exit (close < N-week SMA)
             backstops slow rollovers.
  2. Regime — v1 bought bullish divergences in any tape. v2 only takes them when
             **SPY is above its 40-week (200-day) SMA** — buy dips in uptrends,
             not falling knives. (dependencies=["spy"])
  3. Confirmation — v1 acted on the raw pivot. v2 arms on a confirmed bullish
             divergence, then requires price to **break above the swing high**
             between the two lows within ``confirm_window`` bars before entering.

Discrete-pulse convention (NO forward-fill)
-------------------------------------------
The engine enters whenever Signal==1 and the symbol is flat, so a forward-filled
1 would re-enter the bar after every stop-out. v2 therefore emits a single 1 on
the breakout bar, -1 on a trend-break exit, and 0 (hold / do-nothing) everywhere
else. Held positions persist through 0s and exit via the ATR trailing stop.

Look-ahead safety: pivots use a symmetric ``pivot``-bar fractal (known only at
bar j+pivot); the breakout trigger and regime check read only current/past bars.
"""

import numpy as np
import pandas as pd

from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from config import CONFIG

_TF = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


def _wilder_rsi(close: pd.Series, length: int) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1 / length, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1 / length, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def rsi_divergence_v2_logic(df, spy_df=None, length=14, pivot=3, max_gap=26,
                            regime_ma=40, exit_ma=30, confirm_window=6):
    df = df.copy()
    rsi = _wilder_rsi(df["Close"], length)

    high = df["High"].to_numpy()
    low = df["Low"].to_numpy()
    close = df["Close"].to_numpy()
    rsi_v = rsi.to_numpy()
    n = len(df)

    # --- regime: SPY above its 40-week SMA (spy_df already reindexed to df.index) ---
    if spy_df is not None and "Close" in spy_df.columns:
        spy_close = spy_df["Close"].reindex(df.index).ffill()
        spy_sma = spy_close.rolling(regime_ma).mean()
        regime_ok = (spy_close > spy_sma).fillna(False).to_numpy()
    else:
        regime_ok = np.zeros(n, dtype=bool)  # no SPY -> take nothing (fail closed)

    # --- stock trend-break exit level ---
    stock_sma = df["Close"].rolling(exit_ma).mean().to_numpy()

    # --- Pass 1: find confirmed bullish divergences -> (conf_idx, breakout_level) ---
    # breakout_level = the swing high between the two compared lows.
    arm_level = {}  # conf_idx -> price level that must be broken to enter
    prev_low_price = prev_low_rsi = None
    prev_low_idx = None
    for j in range(pivot, n - pivot):
        win_low = low[j - pivot: j + pivot + 1]
        if low[j] == win_low.min() and (win_low == low[j]).sum() == 1:
            if (prev_low_price is not None and (j - prev_low_idx) <= max_gap
                    and not np.isnan(rsi_v[j]) and not np.isnan(prev_low_rsi)
                    and low[j] < prev_low_price and rsi_v[j] > prev_low_rsi):
                conf = j + pivot                      # bar the pivot is first known
                swing_high = high[prev_low_idx: j + 1].max()  # peak between the lows
                arm_level[conf] = swing_high
            prev_low_price, prev_low_rsi, prev_low_idx = low[j], rsi_v[j], j

    # --- Pass 2: forward walk — arm on divergence, enter on confirmed breakout ---
    signal = np.zeros(n)
    armed = False
    armed_level = np.nan
    armed_expiry = -1
    for t in range(n):
        if t in arm_level:            # a fresh divergence confirms here -> (re)arm
            armed = True
            armed_level = arm_level[t]
            armed_expiry = t + confirm_window
        if armed:
            if t > armed_expiry:
                armed = False
            elif close[t] > armed_level and regime_ok[t]:
                signal[t] = 1         # breakout confirmed in an uptrend -> ENTER
                armed = False

    # --- trend-break exit (only where we aren't entering) ---
    below_trend = (close < stock_sma) & ~np.isnan(stock_sma)
    signal[(signal == 0) & below_trend] = -1

    df["Signal"] = signal             # discrete pulses, NO forward-fill
    return df


@register_strategy(
    name="RSI Divergence v2 (Trend+Confirm)",
    dependencies=["spy"],
    params={
        "length": 14,                                           # 14 RSI periods (literal, per spec)
        "pivot": get_bars_for_period("15d", _TF, _MUL),         # ~3-week swing window (W:3 / D:15)
        "max_gap": get_bars_for_period("130d", _TF, _MUL),      # compare swings ≤~26wk apart (W:26 / D:130)
        "regime_ma": get_bars_for_period("200d", _TF, _MUL),    # SPY 200-day trend filter (W:40 / D:200)
        "exit_ma": get_bars_for_period("150d", _TF, _MUL),      # stock ~150-day trend-break exit (W:30 / D:150)
        "confirm_window": get_bars_for_period("30d", _TF, _MUL),# breakout window ~6wk (W:6 / D:30)
    },
)
def rsi_divergence_v2(df, **kwargs):
    """Trend-filtered, breakout-confirmed bullish-divergence entries; ATR trail exit."""
    return rsi_divergence_v2_logic(
        df,
        spy_df=kwargs.get("spy_df"),
        length=kwargs["length"],
        pivot=kwargs["pivot"],
        max_gap=kwargs["max_gap"],
        regime_ma=kwargs["regime_ma"],
        exit_ma=kwargs["exit_ma"],
        confirm_window=kwargs["confirm_window"],
    )
