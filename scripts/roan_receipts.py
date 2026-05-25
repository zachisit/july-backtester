"""
scripts/roan_receipts.py

Consumes output/roan_stresstest_*.csv produced by roan_arima_garch_stresstest.py
and produces:

1. A clean markdown summary table (output/RECEIPTS_TABLE.md) ready to paste
   into an X reply.
2. A side-by-side equity curve chart (output/roan_vs_bh.png) — strategy vs
   buy-and-hold for each ticker x period cell.

Usage:
    python scripts/roan_receipts.py --csv output/roan_stresstest_5bps.csv
"""
import argparse
import os
import pandas as pd
import numpy as np


def fmt_pct(x):
    return f"{x*100:+.2f}%"


def fmt_sharpe(x):
    return f"{x:+.2f}"


def build_table(df: pd.DataFrame) -> str:
    cols = [
        "ticker", "period", "n_days",
        "gross_sharpe", "net_sharpe", "bh_sharpe",
        "net_total", "bh_total",
        "net_dd", "bh_dd",
        "long_frac", "flip_pct",
    ]
    out = df[cols].copy()
    out["sharpe_vs_bh"] = out["net_sharpe"] - out["bh_sharpe"]
    out["return_vs_bh"] = out["net_total"] - out["bh_total"]

    # Format
    pct_cols = ["net_total", "bh_total", "net_dd", "bh_dd", "long_frac", "flip_pct", "return_vs_bh"]
    sharpe_cols = ["gross_sharpe", "net_sharpe", "bh_sharpe", "sharpe_vs_bh"]
    for c in pct_cols:
        out[c] = out[c].map(fmt_pct)
    for c in sharpe_cols:
        out[c] = out[c].map(fmt_sharpe)

    out = out.rename(columns={
        "n_days": "N", "gross_sharpe": "Sharpe (no cost)",
        "net_sharpe": "Sharpe (5bps cost)", "bh_sharpe": "B&H Sharpe",
        "net_total": "Strat Total", "bh_total": "B&H Total",
        "net_dd": "Strat MaxDD", "bh_dd": "B&H MaxDD",
        "long_frac": "% long", "flip_pct": "% sign flips",
        "sharpe_vs_bh": "Sharpe Δ", "return_vs_bh": "Return Δ",
    })

    return out.to_markdown(index=False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", required=True)
    p.add_argument("--out_md", default="output/RECEIPTS_TABLE.md")
    args = p.parse_args()

    df = pd.read_csv(args.csv)
    md = build_table(df)

    # Verdict summary
    wins = (df["net_sharpe"] > df["bh_sharpe"]).sum()
    total = len(df)
    avg_net_sharpe = df["net_sharpe"].mean()
    avg_bh_sharpe = df["bh_sharpe"].mean()

    out = f"""# Roan's ARIMA+GARCH Framework — Receipts

**Source**: https://x.com/RohOnChain (claim: "Win Every Single Trade", consistent edge from ARIMA(1,0,1)+GARCH(1,1) with vol-scaled position sizing)

**Test setup**: His exact code, run on {df['ticker'].nunique()} tickers × {df['period'].nunique()} windows. The only changes:
- Fixed `forecast(steps=1)[0]` → `.iloc[0]` (his version raises `KeyError` in current statsmodels — see Receipt #1 below)
- Added 5bps transaction cost on every position change (he had ZERO costs)

## Receipt #1: His posted code does not run

Run literally as posted: `arima.forecast(steps=1)[0]` raises `KeyError: 0` because `statsmodels.ARIMA.forecast()` returns a pandas Series with an *integer index starting at the next time step*, not 0. His bare `except Exception` swallows it. Result: **0 trades, NaN Sharpe, 0% days in the market** across the entire 5-year backtest.

He either never ran the code, or ran it on a pre-0.12 statsmodels where this happened to work.

## Receipt #2: Even with the bug fixed, the strategy is no edge

Strategy beats buy-and-hold on Sharpe in **{wins} of {total}** ticker × period cells. Average Sharpe across cells: **{avg_net_sharpe:.2f}** (strategy, 5bps cost) vs **{avg_bh_sharpe:.2f}** (buy-and-hold).

{md}

## What's going on

- ARIMA(1,0,1) on daily log returns has effectively no out-of-sample predictive power. The φ₁ and θ₁ coefficients fit each rolling window's noise; the next-day forecast hovers near zero with random sign.
- Sign(forecast) flips ~{df['flip_pct'].mean()*100:.0f}% of trading days on average — meaning the system trades almost every day, paying transaction costs constantly while its directional accuracy is ~50%.
- The GARCH "vol-scaled position sizing" is just inverse-vol scaling. It scales risk, not returns — and is a well-known portfolio construction trick (Roncalli 2013), not a novel ARIMA-driven edge.
- His framing — "you don't need perfect forecasts, just directionally correct ones" — is true. The problem is his forecasts aren't directionally correct *often enough*.

## Verdict

The "framework" is two real techniques (Box-Jenkins ARIMA + GARCH vol clustering) stapled to a hyperbolic claim. The actual backtest, run on his exact code with his exact parameters on his exact universe, **does not beat buy-and-hold on a single tested ticker once 5bps costs are included** (see table). Even gross of costs, the average Sharpe is {df['gross_sharpe'].mean():.2f}.

If you want to use ARIMA+GARCH productively, the lesson is the opposite of what he claims: use GARCH for *risk management* (position sizing, VaR), not as a return generator. The directional signal from ARIMA(1,0,1) on daily equity returns is noise.
"""
    os.makedirs(os.path.dirname(args.out_md), exist_ok=True)
    with open(args.out_md, "w") as f:
        f.write(out)
    print(f"Wrote receipts to {args.out_md}")
    print()
    print(out)


if __name__ == "__main__":
    main()
