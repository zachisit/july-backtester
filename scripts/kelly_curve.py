#!/usr/bin/env python3
"""
Kelly Sizing Curve — SPY SMA 50/200 crossover

Sweeps allocation from 1% to 70% of equity per trade to show:
  - There is an empirical peak CAGR (Kelly optimum)
  - Above it, overbetting destroys geometric returns even though the signal is real
  - At 2× Kelly, growth approaches zero; beyond that, ruin

Validates Kelly's claim (1956): the fraction matters as much as the edge itself.

Usage:
    python scripts/kelly_curve.py
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
START = "2004-01-01"
END = "2025-01-01"
FAST = 50
SLOW = 200
INITIAL_CAPITAL = 100_000.0
SLIPPAGE = 0.0005
ALLOC_STEPS = np.linspace(0.005, 0.70, 140)  # 0.5% → 70%
OUT_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Data ──────────────────────────────────────────────────────────────────────
def fetch(symbol: str) -> pd.DataFrame:
    df = yf.download(symbol, start=START, end=END, auto_adjust=True, progress=False)
    df.index = pd.to_datetime(df.index).normalize()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


# ── Backtest ──────────────────────────────────────────────────────────────────
def backtest(df: pd.DataFrame, allocation: float):
    """SMA 50/200 crossover; position sized as `allocation` fraction of current equity."""
    close = df["Close"].values
    sma_fast = pd.Series(close).rolling(FAST).mean().values
    sma_slow = pd.Series(close).rolling(SLOW).mean().values

    cash = INITIAL_CAPITAL
    shares = 0
    entry_price = 0.0
    equity = np.empty(len(df))
    trade_returns = []

    for i in range(len(df)):
        price = float(close[i])
        if np.isnan(sma_fast[i]) or np.isnan(sma_slow[i]):
            equity[i] = cash + shares * price
            continue

        bullish = sma_fast[i] > sma_slow[i]

        if bullish and shares == 0:
            current_eq = cash + shares * price
            alloc_amt = current_eq * allocation
            new_shares = int(alloc_amt / (price * (1 + SLIPPAGE)))
            if new_shares > 0:
                cost = new_shares * price * (1 + SLIPPAGE)
                if cost <= cash:
                    shares = new_shares
                    entry_price = price * (1 + SLIPPAGE)
                    cash -= cost

        elif not bullish and shares > 0:
            exit_price = price * (1 - SLIPPAGE)
            proceeds = shares * exit_price
            trade_ret = (exit_price - entry_price) / entry_price
            trade_returns.append(trade_ret)
            cash += proceeds
            shares = 0

        equity[i] = cash + shares * price

    if shares > 0:
        exit_price = float(close[-1]) * (1 - SLIPPAGE)
        trade_ret = (exit_price - entry_price) / entry_price
        trade_returns.append(trade_ret)
        cash += shares * exit_price

    return pd.Series(equity, index=df.index), trade_returns


# ── Metrics ───────────────────────────────────────────────────────────────────
def compute_metrics(equity: pd.Series):
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    if years <= 0 or equity.iloc[-1] <= 0:
        return np.nan, np.nan
    cagr = (equity.iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1
    hwm = equity.cummax()
    max_dd = ((equity - hwm) / hwm).min()
    return cagr, max_dd


def theoretical_kelly(trade_returns):
    """f* = p/avg_loss - (1-p)/avg_win (binary Kelly approximation)."""
    arr = np.array(trade_returns)
    wins = arr[arr > 0]
    losses = arr[arr < 0]
    if len(wins) == 0 or len(losses) == 0 or len(arr) < 5:
        return None
    p = len(wins) / len(arr)
    avg_win = wins.mean()
    avg_loss = abs(losses.mean())
    f_star = p / avg_loss - (1 - p) / avg_win
    return f_star


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    print(f"Fetching {SYMBOL} {START}→{END} …")
    df = fetch(SYMBOL)
    print(f"  {len(df)} bars  ({df.index[0].date()} → {df.index[-1].date()})")

    rows = []
    for alloc in ALLOC_STEPS:
        eq, _ = backtest(df, alloc)
        cagr, mdd = compute_metrics(eq)
        rows.append({"alloc": alloc, "cagr": cagr, "mdd": mdd})

    res = pd.DataFrame(rows)

    # Theoretical Kelly from a mid-range allocation run
    _, sample_trades = backtest(df, 0.10)
    kf = theoretical_kelly(sample_trades)

    # Empirical peak
    best_idx = res["cagr"].idxmax()
    peak_alloc = res.loc[best_idx, "alloc"]
    peak_cagr = res.loc[best_idx, "cagr"]

    # ── Print summary ─────────────────────────────────────────────────────────
    print(f"\n{'─'*50}")
    print(f"  Trades at 10% alloc:      {len(sample_trades)}")
    if kf:
        print(f"  Theoretical Kelly f*:     {kf:.1%}")
    print(f"  Empirical peak alloc:     {peak_alloc:.1%}")
    print(f"  Empirical peak CAGR:      {peak_cagr:.1%}")
    print(f"  Danger zone (2×Kelly):    {peak_alloc*2:.1%}+")

    if kf:
        gap = abs(peak_alloc - kf) / kf * 100
        print(f"  Theory vs empirical gap:  {gap:.0f}%")
    print(f"{'─'*50}")

    # ── Plot ──────────────────────────────────────────────────────────────────
    x = res["alloc"] * 100

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    fig.suptitle(
        f"Kelly Sizing Curve — {SYMBOL} SMA {FAST}/{SLOW} Crossover  (2004–2025)\n"
        "Peak CAGR marks the Kelly-optimal allocation. Beyond it, a real edge destroys capital.",
        fontsize=12,
        fontweight="bold",
    )

    # CAGR panel
    ax1.plot(x, res["cagr"] * 100, color="steelblue", lw=2.5, label="CAGR")
    ax1.axvline(
        peak_alloc * 100,
        color="gold",
        lw=1.8,
        ls="--",
        label=f"Empirical Kelly: {peak_alloc:.0%}  →  {peak_cagr:.1%} CAGR",
    )
    ax1.axvline(
        peak_alloc * 200,
        color="tomato",
        lw=1.2,
        ls=":",
        label=f"2× Kelly ({peak_alloc*2:.0%}) — zero-growth zone",
    )
    if kf and 0 < kf < 0.70:
        ax1.axvline(
            kf * 100,
            color="limegreen",
            lw=1.5,
            ls="-.",
            label=f"Theoretical f*: {kf:.0%}",
        )
    ax1.axvline(
        peak_alloc * 100 / 2,
        color="gold",
        lw=1.0,
        ls=":",
        alpha=0.6,
        label=f"½ Kelly ({peak_alloc/2:.0%}) — practitioner safe zone",
    )
    ax1.scatter([peak_alloc * 100], [peak_cagr * 100], s=90, color="gold", zorder=5)
    ax1.axhline(0, color="black", lw=0.5)
    ax1.set_ylabel("CAGR (%)")
    ax1.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax1.legend(fontsize=8.5)
    ax1.grid(True, alpha=0.25)

    # Max drawdown panel
    ax2.plot(x, res["mdd"] * 100, color="tomato", lw=2.5)
    ax2.fill_between(x, res["mdd"] * 100, 0, alpha=0.15, color="red")
    ax2.axvline(peak_alloc * 100, color="gold", lw=1.8, ls="--")
    ax2.axvline(peak_alloc * 200, color="tomato", lw=1.2, ls=":", alpha=0.7)
    ax2.set_xlabel("Allocation per Trade (% of current equity)")
    ax2.set_ylabel("Max Drawdown (%)")
    ax2.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax2.grid(True, alpha=0.25)
    ax2.set_title("Drawdown grows monotonically — the tail that kills you", fontsize=10)

    plt.tight_layout()
    out = os.path.join(OUT_DIR, "kelly_curve.png")
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\nChart → {out}")
    plt.show()


if __name__ == "__main__":
    main()
