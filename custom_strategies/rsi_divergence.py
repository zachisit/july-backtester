# custom_strategies/rsi_divergence.py
"""RSI–price divergence strategy (weekly timeframe focus).

Detects classic regular divergences between price and a 14-period RSI and
trades them long-only:

  * Bullish divergence  → price makes a **lower** swing low while RSI makes a
                          **higher** swing low → BUY (Signal = 1).
  * Bearish divergence  → price makes a **higher** swing high while RSI makes a
                          **lower** swing high → SELL/exit (Signal = -1).

Signal is forward-filled so the position is held between events (same
convention as helpers.indicators.rsi_logic).

Look-ahead safety
-----------------
Swing pivots are confirmed using a symmetric fractal window of ``pivot`` bars
on each side.  A pivot centred on bar ``j`` is only *known* once bar ``j+pivot``
has printed, so the divergence signal is emitted at bar ``j+pivot`` (the
confirmation bar) — never at ``j`` itself.  No information beyond the emission
bar is used, so the signal is free of look-ahead bias.  The engine then applies
its normal execution lag (``execution_time="open"`` fills at the next bar's open).

All logic is self-contained here — no edits to helpers/indicators.py.
"""

import numpy as np
import pandas as pd

from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from config import CONFIG

_TF = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


def _wilder_rsi(close: pd.Series, length: int) -> pd.Series:
    """14-period RSI using Wilder's smoothing (matches indicators.rsi_logic)."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0).ewm(alpha=1 / length, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1 / length, adjust=False).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def rsi_divergence_logic(df, length=14, pivot=3, max_gap=26):
    """Return ``df`` with a ``Signal`` column driven by RSI/price divergence.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV frame with Open/High/Low/Close.
    length : int
        RSI lookback in bars (14 weekly bars when timeframe="W").
    pivot : int
        Fractal half-window. A swing needs ``pivot`` bars on each side to
        confirm; the signal fires ``pivot`` bars after the swing.
    max_gap : int
        Maximum number of bars allowed between the two swings being compared.
        Prevents pairing a fresh swing with a stale one from long ago.
    """
    df = df.copy()
    rsi = _wilder_rsi(df["Close"], length)
    df["RSI"] = rsi

    high = df["High"].to_numpy()
    low = df["Low"].to_numpy()
    rsi_v = rsi.to_numpy()
    n = len(df)
    signal = np.zeros(n)

    prev_low_price = prev_low_rsi = None
    prev_low_idx = None
    prev_high_price = prev_high_rsi = None
    prev_high_idx = None

    for j in range(pivot, n - pivot):
        conf = j + pivot  # confirmation bar — earliest bar this pivot is known

        # --- swing low? strict minimum of the [j-pivot, j+pivot] window ---
        win_low = low[j - pivot: j + pivot + 1]
        if low[j] == win_low.min() and (win_low == low[j]).sum() == 1:
            if (prev_low_price is not None and (j - prev_low_idx) <= max_gap
                    and not np.isnan(rsi_v[j]) and not np.isnan(prev_low_rsi)):
                # Bullish divergence: lower price low, higher RSI low
                if low[j] < prev_low_price and rsi_v[j] > prev_low_rsi:
                    signal[conf] = 1
            prev_low_price, prev_low_rsi, prev_low_idx = low[j], rsi_v[j], j

        # --- swing high? strict maximum of the [j-pivot, j+pivot] window ---
        win_high = high[j - pivot: j + pivot + 1]
        if high[j] == win_high.max() and (win_high == high[j]).sum() == 1:
            if (prev_high_price is not None and (j - prev_high_idx) <= max_gap
                    and not np.isnan(rsi_v[j]) and not np.isnan(prev_high_rsi)):
                # Bearish divergence: higher price high, lower RSI high
                if high[j] > prev_high_price and rsi_v[j] < prev_high_rsi:
                    signal[conf] = -1
            prev_high_price, prev_high_rsi, prev_high_idx = high[j], rsi_v[j], j

    df["Signal"] = pd.Series(signal, index=df.index).replace(0, np.nan).ffill().fillna(0)
    return df


@register_strategy(
    name="RSI Divergence (14)",
    dependencies=[],
    params={
        "length": 14,                                      # 14 RSI periods (literal, per spec)
        "pivot": get_bars_for_period("15d", _TF, _MUL),    # ~3-week swing window (W:3 / D:15)
        "max_gap": get_bars_for_period("130d", _TF, _MUL), # compare swings ≤~26wk apart (W:26 / D:130)
    },
)
def rsi_divergence(df, **kwargs):
    """Long-only RSI/price divergence: buy bullish divergence, exit on bearish."""
    return rsi_divergence_logic(
        df,
        length=kwargs["length"],
        pivot=kwargs["pivot"],
        max_gap=kwargs["max_gap"],
    )
