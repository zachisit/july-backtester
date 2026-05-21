"""Plot the three gold-regime champion equity curves alongside SPY buy-and-hold
on a single image. Output: output/gold_champions_vs_spy.png
"""
import os
import sys

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

INITIAL_CAPITAL = 100_000.0
START_DATE = pd.Timestamp("1993-01-29")  # Universal champion's first real bar

CURVES = [
    {
        "label": "Champion 1 — 50/50 R21 + EC-VIX-27 (baseline)",
        "path": "output/runs/R21_EC27_50_50_extended_1993_equity.csv",
        "color": "#1f77b4",
    },
    {
        "label": "Champion 2 — 50/50 + EXTREME kill switch",
        "path": "output/runs/killswitch_33yr_50_50_extreme_overlay_equity.csv",
        "color": "#2ca02c",
    },
    {
        "label": "Champion 3 — 15/15/35/35 + EXTREME kill switch (Universal)",
        "path": "output/runs/killswitch_33yr_15_15_35_35_extreme_overlay_equity.csv",
        "color": "#d62728",
    },
]
SPY_PARQUET = "parquet_data/data/SPY.parquet"
OUT_PATH = "output/gold_champions_vs_spy.png"


def load_equity(path: str) -> pd.Series:
    df = pd.read_csv(os.path.join(PROJECT_ROOT, path), parse_dates=["Date"])
    s = df.set_index("Date")["Equity"].sort_index()
    s = s[s.index >= START_DATE]
    s = s / s.iloc[0] * INITIAL_CAPITAL  # rebase to $100k at START_DATE
    return s


def load_spy_buy_hold() -> pd.Series:
    spy = pd.read_parquet(os.path.join(PROJECT_ROOT, SPY_PARQUET))
    spy = spy.loc[spy.index >= START_DATE, "Close"]
    return spy / spy.iloc[0] * INITIAL_CAPITAL


def main() -> None:
    spy_eq = load_spy_buy_hold()
    series = [(c["label"], c["color"], load_equity(c["path"])) for c in CURVES]

    fig, ax = plt.subplots(figsize=(14, 7.5), dpi=140)

    ax.plot(spy_eq.index, spy_eq.values, label="SPY Buy & Hold",
            color="#7f7f7f", linewidth=1.4, linestyle="--")

    for label, color, s in series:
        ax.plot(s.index, s.values, label=label, color=color, linewidth=1.6)

    ax.set_yscale("log")
    fig.suptitle("Gold-Regime Champions vs SPY Buy & Hold",
                 fontsize=14, fontweight="bold", y=0.995)
    ax.set_title("1993-01-29 → 2026-04-22, all curves rebased to $100k at common start "
                 "(doc returns use 1990 anchor for 50/50 sleeves and differ)",
                 fontsize=9, color="#555555")
    ax.set_xlabel("Date")
    ax.set_ylabel("Equity (log scale, $100k start)")
    ax.grid(True, which="both", linestyle=":", alpha=0.4)
    ax.xaxis.set_major_locator(mdates.YearLocator(2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    fig.autofmt_xdate()

    final_lines = [f"SPY B&H:  ${spy_eq.iloc[-1]:>14,.0f}  ({spy_eq.iloc[-1] / INITIAL_CAPITAL - 1:+.1%})"]
    for label, _, s in series:
        short = label.split("—")[0].strip()
        final_lines.append(
            f"{short}:  ${s.iloc[-1]:>14,.0f}  ({s.iloc[-1] / INITIAL_CAPITAL - 1:+.1%})"
        )
    annotation = "Final equity:\n" + "\n".join(final_lines)
    ax.text(0.012, 0.97, annotation, transform=ax.transAxes,
            fontsize=8.5, family="monospace", va="top",
            bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                      edgecolor="#cccccc", alpha=0.92))

    ax.legend(loc="lower right", fontsize=9, framealpha=0.92)

    out = os.path.join(PROJECT_ROOT, OUT_PATH)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    fig.tight_layout()
    fig.savefig(out, dpi=140, bbox_inches="tight")
    print(f"Saved: {out}")
    print(f"\nFinal values (start: {INITIAL_CAPITAL:,.0f} on {START_DATE.date()}):")
    print(f"  SPY B&H:                  ${spy_eq.iloc[-1]:>14,.0f}  ({spy_eq.iloc[-1] / INITIAL_CAPITAL - 1:+.1%})")
    for label, _, s in series:
        print(f"  {label[:48]:<48}  ${s.iloc[-1]:>14,.0f}  ({s.iloc[-1] / INITIAL_CAPITAL - 1:+.1%})")


if __name__ == "__main__":
    main()
