"""
scripts/plot_btc_equity_curves.py

Plots equity curves for all 6 confirmed BTC champion strategies on a single
figure, with BTC B&H as a reference line.

Usage:
    python scripts/plot_btc_equity_curves.py
    python scripts/plot_btc_equity_curves.py --run-id btc-6champs-equity-curves_2026-04-12_19-28-50
    python scripts/plot_btc_equity_curves.py --log  # log scale y-axis

The script auto-detects the most recent btc-6champs-* run if --run-id is
not specified.
"""

import argparse
import os
import sys
import glob

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as mticker

# ── project root on path ───────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# ── constants ──────────────────────────────────────────────────────────────
INITIAL_CAPITAL = 100_000.0

STRATEGY_DISPLAY = {
    "BTC_RSI_Trend_20_60_56_+_SMA120":    "RSI Trend (20/60/56) + SMA120  [Calmar 1.77, MaxDD 34%]",
    "BTC_RSI_Trend_11_60_56_+_SMA120":    "RSI Trend (11/60/56) + SMA120  [Calmar 1.63, MaxDD 40%]",
    "BTC_RSI_Trend_14_60_40_+_SMA200":    "RSI Trend (14/60/40) + SMA200  [Calmar 1.32, MaxDD 44%]",
    "BTC_Price_Momentum_54d_5%_+_SMA200": "Price Momentum (54d/5%) + SMA200  [Calmar 1.29, MaxDD 45%]",
    "MA_Bounce_50d_3bar_+_SMA200_Gate":   "MA Bounce (50d/3bar) + SMA200  [Calmar 1.22, MaxDD 46%]",
    "BTC_Donchian_Wider_52_13":           "Donchian Wider (52/13)  [Calmar 0.84, MaxDD 53%]",
}

# Distinct, colourblind-friendly palette
COLOURS = [
    "#E63946",  # red
    "#F4A261",  # orange
    "#2A9D8F",  # teal
    "#457B9D",  # blue
    "#8338EC",  # purple
    "#06D6A0",  # green
]


def find_latest_run(runs_dir: str) -> str:
    pattern = os.path.join(runs_dir, "btc-6champs-*")
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"No btc-6champs-* run found in {runs_dir}. "
            "Run: python main.py --name btc-6champs-equity-curves"
        )
    return os.path.basename(matches[-1])


def load_equity_curve(csv_path: str) -> pd.Series:
    """Reconstruct step-function equity curve from trade log."""
    df = pd.read_csv(csv_path, parse_dates=["ExitDate"])
    df["ExitDate"] = pd.to_datetime(df["ExitDate"], utc=True).dt.normalize()
    df = df.sort_values("ExitDate").reset_index(drop=True)

    equity = INITIAL_CAPITAL + df["Profit"].cumsum()
    equity.index = df["ExitDate"]
    # Prepend start point
    start = df["EntryDate"].min()
    start_ts = pd.to_datetime(start, utc=True).normalize()
    equity = pd.concat([pd.Series([INITIAL_CAPITAL], index=[start_ts]), equity])
    return equity


def load_btc_bah(cache_dir: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Load BTC price from parquet cache and normalise to $100k."""
    pattern = os.path.join(cache_dir, "X_BTCUSD_*.parquet")
    files = sorted(glob.glob(pattern))
    if not files:
        return None
    df = pd.read_parquet(files[-1])
    df.index = pd.to_datetime(df.index, utc=True).normalize()
    df = df.sort_index()
    df = df.loc[(df.index >= start) & (df.index <= end)]
    if df.empty:
        return None
    equity = (df["Close"] / df["Close"].iloc[0]) * INITIAL_CAPITAL
    return equity


def extract_strategy_key(filename: str) -> str:
    """Strip portfolio prefix and _trade_log suffix from filename stem."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    # filename: Bitcoin_(BTC)_<strategy_key>_trade_log
    prefix = "Bitcoin_(BTC)_"
    suffix = "_trade_log"
    if stem.startswith(prefix):
        stem = stem[len(prefix):]
    if stem.endswith(suffix):
        stem = stem[: -len(suffix)]
    return stem


def main():
    parser = argparse.ArgumentParser(description="Plot BTC champion equity curves")
    parser.add_argument("--run-id", default=None, help="Run folder name (auto-detect if omitted)")
    parser.add_argument("--log", action="store_true", help="Log-scale y-axis")
    parser.add_argument("--output", default=None, help="Output PNG path (default: output/btc_equity_curves.png)")
    args = parser.parse_args()

    runs_dir = os.path.join(PROJECT_ROOT, "output", "runs")
    cache_dir = os.path.join(PROJECT_ROOT, "data_cache")

    run_id = args.run_id or find_latest_run(runs_dir)
    trade_log_dir = os.path.join(runs_dir, run_id, "raw_trades", "Bitcoin_(BTC)")
    print(f"Using run: {run_id}")

    csv_files = sorted(glob.glob(os.path.join(trade_log_dir, "*_trade_log.csv")))
    if not csv_files:
        print(f"ERROR: No trade log CSVs found in {trade_log_dir}")
        sys.exit(1)

    # ── build equity curves ───────────────────────────────────────────────
    curves = {}
    for csv_path in csv_files:
        key = extract_strategy_key(csv_path)
        eq = load_equity_curve(csv_path)
        display = STRATEGY_DISPLAY.get(key, key)
        curves[display] = eq

    # ── global date range ─────────────────────────────────────────────────
    all_dates = pd.concat(list(curves.values())).index
    start_date = all_dates.min()
    end_date   = all_dates.max()

    btc_bah = load_btc_bah(cache_dir, start_date, end_date)

    # ── plot ──────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(14, 8))
    fig.patch.set_facecolor("#0D1117")
    ax.set_facecolor("#0D1117")

    for spine in ax.spines.values():
        spine.set_edgecolor("#444")

    ax.tick_params(colors="#AAA", labelsize=9)
    ax.xaxis.label.set_color("#AAA")
    ax.yaxis.label.set_color("#AAA")

    # BTC B&H reference
    if btc_bah is not None:
        ax.plot(
            btc_bah.index,
            btc_bah.values,
            color="#FFFFFF",
            linewidth=1.2,
            linestyle="--",
            alpha=0.45,
            label="BTC Buy & Hold",
            zorder=1,
        )

    # Strategy equity curves
    for (display, eq), colour in zip(sorted(curves.items()), COLOURS):
        ax.plot(
            eq.index,
            eq.values,
            color=colour,
            linewidth=1.8,
            alpha=0.92,
            label=display,
            zorder=2,
        )

    # Baseline
    ax.axhline(INITIAL_CAPITAL, color="#555", linewidth=0.8, linestyle=":", zorder=0)

    # Axes
    if args.log:
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda x, _: f"${x:,.0f}" if x >= 1000 else f"${x:.0f}"
        ))
    else:
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda x, _: f"${x / 1_000_000:.1f}M" if x >= 1_000_000 else f"${x / 1_000:.0f}K"
        ))

    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 7, 10]))

    ax.grid(axis="y", color="#2A2A2A", linewidth=0.6)
    ax.grid(axis="x", color="#2A2A2A", linewidth=0.4)

    # Legend
    legend = ax.legend(
        loc="upper left",
        fontsize=8.5,
        framealpha=0.85,
        facecolor="#1A1A2E",
        edgecolor="#444",
        labelcolor="#DDD",
    )

    # Title & labels
    ax.set_title(
        "Bitcoin Confirmed Champion Strategies — Equity Curves (2017–2026)\n"
        "$100,000 initial capital · Daily bars · Polygon data · 100% allocation",
        color="#EEE",
        fontsize=13,
        pad=12,
    )
    ax.set_xlabel("Year", color="#AAA", fontsize=10)
    ax.set_ylabel("Portfolio Value", color="#AAA", fontsize=10)

    plt.tight_layout()

    output_path = args.output or os.path.join(PROJECT_ROOT, "output", "btc_equity_curves.png")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Saved: {output_path}")

    # Also save log-scale version alongside
    if not args.log:
        ax.set_yscale("log")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(
            lambda x, _: f"${x:,.0f}" if x >= 1000 else f"${x:.0f}"
        ))
        ax.set_title(
            "Bitcoin Confirmed Champion Strategies — Equity Curves (2017–2026) [log scale]\n"
            "$100,000 initial capital · Daily bars · Polygon data · 100% allocation",
            color="#EEE",
            fontsize=13,
            pad=12,
        )
        log_path = output_path.replace(".png", "_log.png")
        plt.savefig(log_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        print(f"Saved: {log_path}")

    plt.close()


if __name__ == "__main__":
    main()
