"""helpers/noise.py

Price noise injection for stress-testing strategy robustness.

Applies independent uniform random multipliers to each OHLC cell, then
reconstructs High = row-wise max(O,H,L,C) and Low = row-wise min(O,H,L,C)
to guarantee that every candlestick remains valid after perturbation.

Volume, index, and any non-OHLC columns are left untouched.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def inject_price_noise(df: pd.DataFrame, noise_pct: float) -> pd.DataFrame:
    """Return a copy of *df* with uniform random noise applied to OHLC prices.

    For each bar and each price column (Open, High, Low, Close), an
    independent multiplier drawn from Uniform(1 - noise_pct, 1 + noise_pct)
    is applied.  After perturbation, High and Low are reconstructed as the
    row-wise maximum and minimum across all four price columns so that no
    candlestick becomes invalid (High < Low or price order violations).

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV dataframe with at least columns ``['Open', 'High', 'Low', 'Close']``.
    noise_pct : float
        Half-width of the uniform noise range, expressed as a fraction of
        price.  ``0.01`` means ±1%.  Values <= 0 return the dataframe
        unchanged (no copy).

    Returns
    -------
    pd.DataFrame
        A new dataframe with noisy OHLC columns.  The original is never
        mutated.
    """
    if noise_pct <= 0:
        return df

    out = df.copy()
    n = len(out)

    for col in ("Open", "High", "Low", "Close"):
        multipliers = np.random.uniform(1.0 - noise_pct, 1.0 + noise_pct, size=n)
        out[col] = out[col] * multipliers

    # Reconstruct High/Low to prevent invalid candlesticks
    ohlc = out[["Open", "High", "Low", "Close"]]
    out["High"] = ohlc.max(axis=1)
    out["Low"] = ohlc.min(axis=1)

    return out
