#!/usr/bin/env python3
"""
Regime Filter Test — SMA 50/200 crossover with VIX gate on SPY

Tests Andrew Lo's Adaptive Markets claim: edges are regime-dependent.
Compares three variants of the same signal:
  1. No filter      — trade whenever SMA says long
  2. VIX < 20 gate  — only enter in calm regimes; exit when VIX spikes
  3. VIX < 25 gate  — wider threshold

Benchmark: SPY buy & hold

Output:
  - Console comparison table
  - Two-panel chart (equity curves + VIX history with regime bands)

Usage:
    python scripts/regime_filter_test.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd
import yfinance as yf

# ── Parameters ────────────────────────────────────────────────────────────────
SYMBOL = "SPY"
VIX_TICKER = "^VIX"
START = "2004-01-01"
END = "2025-01-01"
FAST = 50
SLOW = 200
ALLOCATION = 0.10
SLIPPAGE = 0.0005
INITIAL_CAPITAL = 100_000.0
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Data ──────────────────────────────────────────────────────────────────────
def fetch(symbol: str) -> pd.DataFrame:
    df = yf.download(symbol, start=START, end=END, auto_adjust=True, progress=False)
    df.index = pd.to_datetime(df.index).normalize()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


# ── Backtest ──────────────────────────────────────────────────────────────────
def backtest(df: pd.DataFrame, vix_df: pd.DataFrame = None, vix_threshold: float = None):
    """SMA 50/200. Optional VIX gate: exit/block entry when VIX >= threshold."""
    close = df["Close"].values
    sma_fast = pd.Series(close).rolling(FAST).mean().values
    sma_slow = pd.Series(close).rolling(SLOW).mean().values

    vix_aligned = None
    if vix_df is not None and vix_threshold is not None:
        vix_aligned = vix_df["Close"].reindex(df.index, method="ffill").values

    cash = INITIAL_CAPITAL
    shares = 0
    entry_price = 0.0
    equity = np.empty(len(df))
    n_trades = 0

    for i in range(len(df)):
        price = float(close[i])
        if np.isnan(sma_fast[i]) or np.isnan(sma_slow[i]):
            equity[i] = cash + shares * price
            continue

        bullish = sma_fast[i] > sma_slow[i]
        vix_ok = True
        if vix_aligned is not None:
            v = vix_aligned[i]
            if not np.isnan(v) and v >= vix_threshold:
                vix_ok = False

        want_long = bullish and vix_ok

        if want_long and shares == 0:
            alloc_amt = (cash + shares * price) * ALLOCATION
            new_shares = int(alloc_amt / (price * (1 + SLIPPAGE)))
            if new_shares > 0:
                cost = new_shares * price * (1 + SLIPPAGE)
                if cost <= cash:
                    shares = new_shares
                    entry_price = price * (1 + SLIPPAGE)
                    cash -= cost
                    n_trades += 1

        elif not want_long and shares > 0:
            cash += shares * price * (1 - SLIPPAGE)
            shares = 0

        equity[i] = cash + shares * price

    if shares > 0:
        cash += shares * float(close[-1]) * (1 - SLIPPAGE)

    return pd.Series(equity, index=df.index), n_trades


# ── Metrics ───────────────────────────────────────────────────────────────────
def compute_stats(equity: pd.Series, n_trades: int) -> dict:
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    if years <= 0 or equity.iloc[-1] <= 0:
        return {}

    cagr = (equity.iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1

    daily_ret = equity.pct_change().dropna()
    sharpe = (
        daily_ret.mean() / daily_ret.std() * np.sqrt(252) if daily_ret.std() > 0 else np.nan
    )

    hwm = equity.cummax()
    max_dd = ((equity - hwm) / hwm).min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else np.nan

    return {
        "CAGR": cagr,
        "Sharpe": sharpe,
        "MaxDD": max_dd,
        "Calmar": calmar,
        "Trades": n_trades,
        "Final $": equity.iloc[-1],
    }


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print("Fetching SPY and VIX …")
    spy = fetch(SYMBOL)
    vix = fetch(VIX_TICKER)
    print(f"  SPY: {len(spy)} bars    VIX: {len(vix)} bars")

    variants = [
        ("No Filter",        None,  None),
        ("VIX < 20 Gate",    vix,   20),
        ("VIX < 25 Gate",    vix,   25),
    ]

    equities = {}
    stats_all = {}

    for label, vdf, thresh in variants:
        eq, n = backtest(spy, vdf, thresh)
        equities[label] = eq
        stats_all[label] = compute_stats(eq, n)

    # Buy & hold benchmark
    bah = (spy["Close"] / spy["Close"].iloc[0]) * INITIAL_CAPITAL
    equities["SPY Buy & Hold"] = bah
    stats_all["SPY Buy & Hold"] = compute_stats(bah, 1)

    # ── Print table ───────────────────────────────────────────────────────────
    header = f"{'Strategy':<22}  {'CAGR':>7}  {'Sharpe':>7}  {'MaxDD':>8}  {'Calmar':>7}  {'Trades':>7}  {'Final $':>10}"
    print(f"\n{'─'*len(header)}")
    print(header)
    print(f"{'─'*len(header)}")
    for label, s in stats_all.items():
        print(
            f"{label:<22}  {s['CAGR']:>7.1%}  {s['Sharpe']:>7.2f}  "
            f"{s['MaxDD']:>8.1%}  {s['Calmar']:>7.2f}  {s['Trades']:>7}  "
            f"${s['Final $']:>9,.0f}"
        )
    print(f"{'─'*len(header)}")

    # Verdict
    base = stats_all["No Filter"]
    vix20 = stats_all["VIX < 20 Gate"]
    vix25 = stats_all["VIX < 25 Gate"]
    print("\nVerdict:")
    for label, s in [("VIX<20", vix20), ("VIX<25", vix25)]:
        cagr_delta = s["CAGR"] - base["CAGR"]
        sharpe_delta = s["Sharpe"] - base["Sharpe"]
        dd_delta = s["MaxDD"] - base["MaxDD"]  # negative = worse DD
        sign = "+" if cagr_delta >= 0 else ""
        print(
            f"  {label} gate: CAGR {sign}{cagr_delta:.1%}  "
            f"Sharpe {'+' if sharpe_delta >= 0 else ''}{sharpe_delta:.2f}  "
            f"MaxDD {'+' if dd_delta >= 0 else ''}{dd_delta:.1%}"
        )

    # ── Plot ──────────────────────────────────────────────────────────────────
    colors = {
        "SPY Buy & Hold": ("lightgray", "-", 1.2),
        "No Filter":       ("steelblue", "-", 2.2),
        "VIX < 20 Gate":   ("darkorange", "--", 1.8),
        "VIX < 25 Gate":   ("seagreen", "-.", 1.8),
    }

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 9), gridspec_kw={"height_ratios": [2, 1]})
    fig.suptitle(
        f"Regime Filter Test — {SYMBOL} SMA {FAST}/{SLOW} with VIX Gate  (2004–2025)\n"
        "Does the trend edge survive in high-volatility regimes? (Adaptive Markets Hypothesis)",
        fontsize=12,
        fontweight="bold",
    )

    for label, eq in equities.items():
        color, ls, lw = colors[label]
        s = stats_all[label]
        ax1.plot(
            eq.index,
            eq / 1000,
            color=color,
            ls=ls,
            lw=lw,
            label=f"{label}  CAGR={s['CAGR']:.1%}  Sharpe={s['Sharpe']:.2f}  MaxDD={s['MaxDD']:.0%}",
            alpha=0.9 if label != "SPY Buy & Hold" else 0.6,
        )

    ax1.set_ylabel("Portfolio Value ($k)")
    ax1.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"${v:.0f}k"))
    ax1.legend(fontsize=8.5, loc="upper left")
    ax1.grid(True, alpha=0.25)

    # VIX history with regime bands
    ax2.fill_between(vix.index, vix["Close"], 0, alpha=0.15, color="gray")
    ax2.plot(vix.index, vix["Close"], color="gray", lw=0.8, alpha=0.7)
    ax2.axhline(20, color="darkorange", ls="--", lw=1.3, label="VIX=20 (orange gate)")
    ax2.axhline(25, color="seagreen", ls="-.", lw=1.3, label="VIX=25 (green gate)")

    # Shade high-VIX regimes
    above20 = vix["Close"] >= 20
    ax2.fill_between(vix.index, 0, vix["Close"].where(above20), alpha=0.25, color="red",
                     label="VIX ≥ 20 (gated out)")

    ax2.set_ylabel("VIX")
    ax2.set_xlabel("Date")
    ax2.legend(fontsize=8.5)
    ax2.grid(True, alpha=0.25)
    ax2.set_title("Red = periods the VIX gate blocks trading", fontsize=10)

    plt.tight_layout()
    out = os.path.join(OUT_DIR, "regime_filter.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\nChart → {out}")
    plt.show()


if __name__ == "__main__":
    main()
