"""Plot a single strategy's equity curve vs SPY B&H over the actual run period.

Usage:
    python scripts/plot_equity_curve.py <equity_csv> <out_stem>

Reads <equity_csv> with columns [Date, Equity]. Loads SPY parquet, normalises
SPY to start at the same initial capital, computes drawdown banner, writes
<out_stem>.pdf and <out_stem>.png.
"""

import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/plot_equity_curve.py <equity_csv> <out_stem>")
        sys.exit(2)

    eq_path = Path(sys.argv[1]).resolve()
    out_stem = sys.argv[2]

    df = pd.read_csv(eq_path, parse_dates=["Date"])
    df = df.set_index("Date").sort_index()
    df.index = df.index.tz_localize(None) if df.index.tz else df.index
    eq = df["Equity"]

    # Drawdown
    peak = eq.cummax()
    dd = (eq - peak) / peak * 100

    # SPY B&H normalised
    spy_path = Path("/Users/zach/Desktop/github/july-backtester/parquet_data/data/SPY.parquet")
    spy = pd.read_parquet(spy_path)["Close"]
    spy.index = spy.index.tz_localize(None) if spy.index.tz else spy.index
    spy = spy.reindex(eq.index, method="ffill").dropna()
    eq_aligned = eq.reindex(spy.index)
    initial = eq.iloc[0]
    spy_norm = spy * (initial / spy.iloc[0])

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(14, 7), dpi=150,
        gridspec_kw={"height_ratios": [3, 1]}, sharex=True
    )

    ax1.plot(eq_aligned.index, eq_aligned.values, label="Strategy", color="#1f77b4", linewidth=1.5)
    ax1.plot(spy_norm.index, spy_norm.values, label="SPY B&H", color="gray", linestyle="--", linewidth=1.0)
    ax1.set_yscale("log")
    ax1.set_ylabel("Equity ($, log scale)")
    ax1.legend(loc="upper left")
    ax1.grid(True, which="both", alpha=0.3)
    ax1.set_title(f"Equity Curve — {out_stem.split('/')[-1]}", fontsize=11)

    ax2.fill_between(dd.index, dd.values, 0, color="red", alpha=0.3)
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Date")
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_locator(mdates.YearLocator(2))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)

    plt.tight_layout()
    out_pdf = f"{out_stem}.pdf"
    out_png = f"{out_stem}.png"
    plt.savefig(out_pdf, bbox_inches="tight")
    plt.savefig(out_png, bbox_inches="tight")
    plt.close()

    print(f"Wrote {out_pdf}")
    print(f"Wrote {out_png}")
    print(f"Period: {eq.index.min().date()} -> {eq.index.max().date()}")
    print(f"Final equity: ${eq.iloc[-1]:,.0f} (from ${initial:,.0f})")
    print(f"Strategy total return: {(eq.iloc[-1]/initial - 1)*100:.1f}%")
    print(f"SPY total return: {(spy_norm.iloc[-1]/initial - 1)*100:.1f}%")
    print(f"Max DD: {dd.min():.1f}%")


if __name__ == "__main__":
    main()
