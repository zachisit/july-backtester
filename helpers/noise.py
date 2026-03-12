"""helpers/noise.py

Price noise injection for stress-testing strategy robustness.

Applies independent uniform random multipliers to each OHLC cell, then
reconstructs High = row-wise max(O,H,L,C) and Low = row-wise min(O,H,L,C)
to guarantee that every candlestick remains valid after perturbation.

Volume, index, and any non-OHLC columns are left untouched.

Also provides generate_noise_chart_from_csv() for lazy PDF rendering.
"""

from __future__ import annotations

import os

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


def _draw_candles(ax, opens, highs, lows, closes, color_up, color_down, alpha: float, body_width: float = 0.35):
    """Draw candlesticks onto *ax* using integer x positions."""
    xs = range(len(opens))
    for i, (o, h, l, c) in enumerate(zip(opens, highs, lows, closes)):
        color = color_up if c >= o else color_down
        # Full wick
        ax.vlines(i, l, h, colors=color, linewidth=0.8, alpha=alpha)
        # Body (thicker line from min(O,C) to max(O,C))
        ax.vlines(i, min(o, c), max(o, c), colors=color, linewidth=body_width * 20, alpha=alpha)


def generate_noise_chart_from_csv(csv_path: str, output_img_path: str) -> None:
    """Read *csv_path* and write a Ghost Candlestick overlay PNG to *output_img_path*.

    The CSV is expected to have been written by main.py's noise sample export and
    contains columns: Symbol, Clean_Open, Clean_High, Clean_Low, Clean_Close,
    Noisy_Open, Noisy_High, Noisy_Low, Noisy_Close.

    Clean candlesticks are plotted in grey at alpha=0.4 (background).
    Noisy candlesticks are plotted in solid green/red at alpha=1.0 (foreground).

    Parameters
    ----------
    csv_path : str
        Path to the noise_sample_data.csv file.
    output_img_path : str
        Destination path for the PNG image.  Parent directory must exist.
    """
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    df = pd.read_csv(csv_path, index_col=0)

    symbol = df["Symbol"].iloc[0] if "Symbol" in df.columns else "Unknown"

    opens_c  = df["Clean_Open"].values
    highs_c  = df["Clean_High"].values
    lows_c   = df["Clean_Low"].values
    closes_c = df["Clean_Close"].values

    opens_n  = df["Noisy_Open"].values
    highs_n  = df["Noisy_High"].values
    lows_n   = df["Noisy_Low"].values
    closes_n = df["Noisy_Close"].values

    n = len(df)
    x_ticks = list(range(0, n, max(1, n // 6)))
    labels = [str(df.index[i])[:10] for i in x_ticks]

    fig, ax = plt.subplots(figsize=(12, 4), dpi=150)
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    # Clean candlesticks — grey ghost in background
    _draw_candles(ax, opens_c, highs_c, lows_c, closes_c,
                  color_up="#888888", color_down="#888888", alpha=0.4)

    # Noisy candlesticks — solid green/red on top
    _draw_candles(ax, opens_n, highs_n, lows_n, closes_n,
                  color_up="#00c853", color_down="#d50000", alpha=1.0)

    ax.set_xticks(x_ticks)
    ax.set_xticklabels(labels, rotation=30, ha="right", color="#cccccc", fontsize=8)
    ax.tick_params(axis="y", colors="#cccccc")
    ax.spines["bottom"].set_color("#444444")
    ax.spines["left"].set_color("#444444")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_title(f"Noise Injection Overlay  —  {symbol}  (last {n} bars)",
                 color="white", fontsize=12, pad=12)
    ax.set_xlabel("Date", color="#aaaaaa", fontsize=9)
    ax.set_ylabel("Price", color="#aaaaaa", fontsize=9)

    legend_handles = [
        mpatches.Patch(color="#888888", alpha=0.5, label="Clean (original)"),
        mpatches.Patch(color="#00c853", label="Noisy — up bar"),
        mpatches.Patch(color="#d50000", label="Noisy — down bar"),
    ]
    ax.legend(handles=legend_handles, loc="upper left",
              facecolor="#2a2a3e", edgecolor="#444444", labelcolor="white", fontsize=8)

    fig.tight_layout()
    fig.savefig(output_img_path, dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
