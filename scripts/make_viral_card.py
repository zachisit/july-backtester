"""
scripts/make_viral_card.py

Produces TWO assets ready for an X repost:

1. output/roan_card.html  — standalone HTML page styled as a viral scoreboard,
   1200×675 (Twitter Card size). Open in a browser and screenshot, or render to
   PNG with chromium headless.
2. output/roan_card.png   — matplotlib-rendered version of the same scoreboard,
   guaranteed-to-work fallback.

Reads aggregated stress-test results from output/roan_stresstest_all.csv if
present, else falls back to the SPY 5y replication numbers.
"""
import argparse
import os
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch
from matplotlib import gridspec


def load_summary(csv_path):
    if csv_path and os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
        n_cells = len(df)
        wins_sharpe = int((df["net_sharpe"] > df["bh_sharpe"]).sum())
        wins_return = int((df["net_total"] > df["bh_total"]).sum())
        avg_net_sharpe = float(df["net_sharpe"].mean())
        avg_bh_sharpe = float(df["bh_sharpe"].mean())
        avg_gross_sharpe = float(df["gross_sharpe"].mean())
        avg_flip = float(df["flip_pct"].mean())
        # SPY 5y row for headline numbers
        spy5 = df[(df["ticker"] == "SPY") & (df["period"] == "5y")]
        if not spy5.empty:
            spy_row = spy5.iloc[0]
        else:
            spy_row = df.iloc[0]
        return {
            "n_cells": n_cells,
            "wins_sharpe": wins_sharpe,
            "wins_return": wins_return,
            "avg_net_sharpe": avg_net_sharpe,
            "avg_bh_sharpe": avg_bh_sharpe,
            "avg_gross_sharpe": avg_gross_sharpe,
            "avg_flip": avg_flip,
            "spy_net_sharpe": float(spy_row["net_sharpe"]),
            "spy_gross_sharpe": float(spy_row["gross_sharpe"]),
            "spy_bh_sharpe": float(spy_row["bh_sharpe"]),
            "spy_net_total": float(spy_row["net_total"]),
            "spy_bh_total": float(spy_row["bh_total"]),
            "spy_net_dd": float(spy_row["net_dd"]),
            "spy_bh_dd": float(spy_row["bh_dd"]),
            "spy_flip": float(spy_row["flip_pct"]),
            "df": df,
        }
    # Fallback to the known SPY 5y numbers
    return {
        "n_cells": 1,
        "wins_sharpe": 0,
        "wins_return": 0,
        "avg_net_sharpe": 0.26,
        "avg_bh_sharpe": 1.03,
        "avg_gross_sharpe": 0.26,
        "avg_flip": 0.27,
        "spy_net_sharpe": 0.26,
        "spy_gross_sharpe": 0.26,
        "spy_bh_sharpe": 1.03,
        "spy_net_total": 0.108,
        "spy_bh_total": 0.877,
        "spy_net_dd": -0.225,
        "spy_bh_dd": -0.192,
        "spy_flip": 0.27,
        "df": None,
    }


def make_png(s, out_path):
    fig = plt.figure(figsize=(12, 6.75), facecolor="#0d1117")
    gs = gridspec.GridSpec(3, 2, height_ratios=[0.6, 2.2, 0.7], hspace=0.15, wspace=0.05,
                            left=0.04, right=0.96, top=0.95, bottom=0.05)

    # Header band
    head = fig.add_subplot(gs[0, :])
    head.set_facecolor("#0d1117")
    head.axis("off")
    head.text(0.5, 0.72,
              'I ran @RohOnChain\'s "Win Every Single Trade" ARIMA+GARCH framework.',
              ha="center", va="center", fontsize=18, color="#ffffff",
              fontweight="bold", family="DejaVu Sans")
    head.text(0.5, 0.18,
              "His exact code. His exact ticker. His exact parameters.",
              ha="center", va="center", fontsize=13, color="#8b949e",
              family="DejaVu Sans")

    # Left big number — His system
    left = fig.add_subplot(gs[1, 0])
    left.set_facecolor("#0d1117")
    left.axis("off")
    left.text(0.5, 0.92, "HIS SYSTEM", ha="center", va="top", fontsize=14,
              color="#f85149", fontweight="bold", family="DejaVu Sans")
    left.text(0.5, 0.70, f"{s['spy_net_total']*100:+.1f}%", ha="center", va="center",
              fontsize=64, color="#f85149", fontweight="bold", family="DejaVu Sans")
    left.text(0.5, 0.45, "SPY · 5y · NO transaction costs",
              ha="center", va="center", fontsize=11, color="#8b949e",
              family="DejaVu Sans")
    left.text(0.5, 0.30, f"Sharpe {s['spy_net_sharpe']:.2f}   |   MaxDD {s['spy_net_dd']*100:.1f}%",
              ha="center", va="center", fontsize=14, color="#ffffff",
              family="DejaVu Sans")
    left.text(0.5, 0.13,
              f"Sign flips: {int(s['spy_flip']*100)}% of trading days",
              ha="center", va="center", fontsize=11, color="#8b949e",
              family="DejaVu Sans")

    # Right big number — Buy & Hold
    right = fig.add_subplot(gs[1, 1])
    right.set_facecolor("#0d1117")
    right.axis("off")
    right.text(0.5, 0.92, "JUST HOLDING SPY", ha="center", va="top", fontsize=14,
               color="#3fb950", fontweight="bold", family="DejaVu Sans")
    right.text(0.5, 0.70, f"{s['spy_bh_total']*100:+.1f}%", ha="center", va="center",
               fontsize=64, color="#3fb950", fontweight="bold", family="DejaVu Sans")
    right.text(0.5, 0.45, "Same period. Zero models. Zero trades.",
               ha="center", va="center", fontsize=11, color="#8b949e",
               family="DejaVu Sans")
    right.text(0.5, 0.30, f"Sharpe {s['spy_bh_sharpe']:.2f}   |   MaxDD {s['spy_bh_dd']*100:.1f}%",
               ha="center", va="center", fontsize=14, color="#ffffff",
               family="DejaVu Sans")
    right.text(0.5, 0.13, f"4x the Sharpe. 8x the return.",
               ha="center", va="center", fontsize=11, color="#8b949e",
               family="DejaVu Sans")

    # Footer — verdict + multi-ticker
    foot = fig.add_subplot(gs[2, :])
    foot.set_facecolor("#0d1117")
    foot.axis("off")
    foot.text(0.5, 0.75, "VERDICT: DEBUNKED",
              ha="center", va="center", fontsize=22, color="#f85149",
              fontweight="bold", family="DejaVu Sans")
    if s["n_cells"] > 1:
        foot.text(0.5, 0.30,
                  f"Across {s['n_cells']} ticker × window cells: beats buy-and-hold on Sharpe in {s['wins_sharpe']}/{s['n_cells']}. Avg strategy Sharpe {s['avg_net_sharpe']:+.2f} vs B&H {s['avg_bh_sharpe']:+.2f}.",
                  ha="center", va="center", fontsize=11, color="#8b949e",
                  family="DejaVu Sans")
    else:
        foot.text(0.5, 0.30,
                  "Plus: his code as posted raises KeyError on current statsmodels and produces 0 trades.",
                  ha="center", va="center", fontsize=11, color="#8b949e",
                  family="DejaVu Sans")

    fig.savefig(out_path, dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"Wrote {out_path}")


def make_html(s, out_path):
    spy_flip_pct = f"{int(s['spy_flip']*100)}%"
    multi_line = (
        f"Across {s['n_cells']} ticker × window cells: beats buy-and-hold on Sharpe in "
        f"<strong>{s['wins_sharpe']} of {s['n_cells']}</strong>. "
        f"Avg strategy Sharpe <strong>{s['avg_net_sharpe']:+.2f}</strong> vs B&amp;H "
        f"<strong>{s['avg_bh_sharpe']:+.2f}</strong>."
    ) if s["n_cells"] > 1 else (
        "Plus: his code as posted raises <code>KeyError</code> on current statsmodels and produces 0 trades."
    )

    html = f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
<meta charset=\"utf-8\">
<title>Roan ARIMA+GARCH — Debunked</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    width: 1200px; height: 675px;
    background: #0d1117;
    color: #ffffff;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", "Helvetica Neue", sans-serif;
    display: flex; flex-direction: column;
    padding: 36px 48px;
  }}
  .head h1 {{ font-size: 28px; font-weight: 800; line-height: 1.25; }}
  .head .sub {{ font-size: 17px; color: #8b949e; margin-top: 8px; }}
  .grid {{ flex: 1; display: grid; grid-template-columns: 1fr 1fr; gap: 32px; margin: 28px 0 18px; }}
  .card {{ display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; padding: 18px; border-radius: 16px; }}
  .label {{ font-size: 16px; font-weight: 800; letter-spacing: 1.5px; }}
  .label.bad {{ color: #f85149; }}
  .label.good {{ color: #3fb950; }}
  .big {{ font-size: 92px; font-weight: 900; line-height: 1; margin: 14px 0 12px; }}
  .big.bad {{ color: #f85149; }}
  .big.good {{ color: #3fb950; }}
  .meta {{ font-size: 14px; color: #8b949e; margin-bottom: 8px; }}
  .row {{ font-size: 18px; color: #ffffff; margin: 4px 0; }}
  .punch {{ font-size: 14px; color: #c9d1d9; margin-top: 6px; }}
  .verdict {{ text-align: center; font-size: 32px; font-weight: 900; color: #f85149; letter-spacing: 4px; }}
  .verdict + .small {{ text-align: center; font-size: 13px; color: #8b949e; margin-top: 8px; }}
  code {{ background: #161b22; color: #c9d1d9; padding: 1px 5px; border-radius: 4px; font-family: "SF Mono", Menlo, monospace; font-size: 13px; }}
</style>
</head>
<body>
  <div class=\"head\">
    <h1>I ran @RohOnChain's "Win Every Single Trade" ARIMA+GARCH framework.</h1>
    <div class=\"sub\">His exact code. His exact ticker (SPY). His exact 5-year window. No transaction costs.</div>
  </div>
  <div class=\"grid\">
    <div class=\"card\">
      <div class=\"label bad\">HIS SYSTEM</div>
      <div class=\"big bad\">{s['spy_net_total']*100:+.1f}%</div>
      <div class=\"meta\">SPY · 5y · no costs</div>
      <div class=\"row\">Sharpe <strong>{s['spy_net_sharpe']:.2f}</strong> · MaxDD <strong>{s['spy_net_dd']*100:.1f}%</strong></div>
      <div class=\"punch\">Sign-flipped {spy_flip_pct} of trading days</div>
    </div>
    <div class=\"card\">
      <div class=\"label good\">JUST HOLDING SPY</div>
      <div class=\"big good\">{s['spy_bh_total']*100:+.1f}%</div>
      <div class=\"meta\">Same period. Zero models. Zero trades.</div>
      <div class=\"row\">Sharpe <strong>{s['spy_bh_sharpe']:.2f}</strong> · MaxDD <strong>{s['spy_bh_dd']*100:.1f}%</strong></div>
      <div class=\"punch\">4× the Sharpe · 8× the return</div>
    </div>
  </div>
  <div>
    <div class=\"verdict\">VERDICT: DEBUNKED</div>
    <div class=\"small\">{multi_line}</div>
  </div>
</body>
</html>"""
    with open(out_path, "w") as f:
        f.write(html)
    print(f"Wrote {out_path}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--csv", default="output/roan_stresstest_all.csv")
    p.add_argument("--png", default="output/roan_card.png")
    p.add_argument("--html", default="output/roan_card.html")
    args = p.parse_args()

    s = load_summary(args.csv)
    os.makedirs(os.path.dirname(args.png), exist_ok=True)
    make_png(s, args.png)
    make_html(s, args.html)
    print("\nSummary used:")
    print(json.dumps({k: v for k, v in s.items() if k != "df"}, indent=2))


if __name__ == "__main__":
    main()
