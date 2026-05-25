"""
scripts/make_receipts_table_image.py

Renders the 12-cell stress test table as a styled PNG suitable for the X
thread (tweet 4: "Receipt #2: Even after fixing the bug, it loses").
"""
import argparse
import os
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


BG = "#0d1117"
FG = "#c9d1d9"
RED = "#f85149"
GREEN = "#3fb950"
GREY = "#8b949e"
HEADER = "#161b22"


def fmt_pct(x): return f"{x*100:+.1f}%"
def fmt_sharpe(x): return f"{x:+.2f}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="output/roan_stresstest_all.csv")
    p.add_argument("--out", default="output/receipts_table.png")
    args = p.parse_args()

    df = pd.read_csv(args.csv)

    headers = ["Ticker", "Period", "Strat\nSharpe", "B&H\nSharpe",
               "Strat\nReturn", "B&H\nReturn", "Strat\nMaxDD", "B&H\nMaxDD",
               "% sign\nflips"]
    rows = []
    cell_colors = []
    for _, r in df.iterrows():
        rows.append([
            r["ticker"], r["period"],
            fmt_sharpe(r["net_sharpe"]),
            fmt_sharpe(r["bh_sharpe"]),
            fmt_pct(r["net_total"]),
            fmt_pct(r["bh_total"]),
            fmt_pct(r["net_dd"]),
            fmt_pct(r["bh_dd"]),
            f"{r['flip_pct']*100:.1f}%",
        ])
        # Color: strat columns RED if losing to B&H, otherwise FG
        strat_sharpe_color = RED if r["net_sharpe"] < r["bh_sharpe"] else GREEN
        strat_total_color = RED if r["net_total"] < r["bh_total"] else GREEN
        strat_dd_color = RED if r["net_dd"] < r["bh_dd"] else GREEN  # more negative = worse
        cell_colors.append([
            FG, FG,
            strat_sharpe_color, GREEN,
            strat_total_color, GREEN,
            strat_dd_color, FG,
            FG,
        ])

    fig, ax = plt.subplots(figsize=(13, 8), facecolor=BG)
    ax.set_facecolor(BG)
    ax.axis("off")

    # Title block
    fig.text(0.5, 0.96, "Roan's ARIMA(1,0,1)+GARCH(1,1) — Stress Test",
             ha="center", va="top", color="#ffffff", fontsize=20, fontweight="bold")
    fig.text(0.5, 0.92, "6 tickers × 2 windows = 12 cells. 5bps cost per position change. His exact code.",
             ha="center", va="top", color=GREY, fontsize=12)

    table = ax.table(
        cellText=rows,
        colLabels=headers,
        loc="center",
        cellLoc="center",
        colColours=[HEADER] * len(headers),
    )
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.0, 2.0)

    # Apply per-cell coloring
    for i, row in enumerate(cell_colors, start=1):  # header is row 0
        for j, c in enumerate(row):
            cell = table[i, j]
            cell.get_text().set_color(c)
            cell.set_facecolor(BG)
            cell.set_edgecolor(HEADER)
    # Header row styling
    for j in range(len(headers)):
        cell = table[0, j]
        cell.get_text().set_color("#ffffff")
        cell.get_text().set_fontweight("bold")
        cell.set_facecolor(HEADER)
        cell.set_edgecolor(HEADER)

    # Footer summary
    fig.text(0.5, 0.06,
             "Beats buy-and-hold on Sharpe: 0 / 12     |     Beats on total return: 0 / 12",
             ha="center", va="center", color=RED, fontsize=14, fontweight="bold")
    fig.text(0.5, 0.025,
             "Avg strategy Sharpe: -0.13     |     Avg B&H Sharpe: +0.76     |     Avg sign flips: 32% of trading days",
             ha="center", va="center", color=GREY, fontsize=11)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=150, facecolor=fig.get_facecolor(), bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
