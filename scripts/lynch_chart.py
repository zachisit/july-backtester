#!/usr/bin/env python3
"""
Lynch Chart — stock price vs. trailing-twelve-month diluted EPS.

Price data: Polygon or Norgate (reads config["data_provider"]).
EPS data:   Polygon /vX/reference/financials (quarterly, paginated → TTM).

Usage:
    python scripts/lynch_chart.py MSFT
    python scripts/lynch_chart.py NVO WMT COST --output-dir /tmp/charts
    python scripts/lynch_chart.py AAPL --start 2010-01-01
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
import requests

from config import CONFIG
from dotenv import load_dotenv

load_dotenv()

END_DATE = "2026-12-31"


# ── Data fetching ────────────────────────────────────────────────────────────

def _polygon_key() -> str | None:
    return os.environ.get(CONFIG.get("polygon_api_secret_name", "POLYGON_API_KEY"))


def _fetch_price(symbol: str, start: str) -> pd.Series:
    provider = CONFIG.get("data_provider", "polygon").lower()

    if provider == "norgate":
        from services.norgate_service import get_price_data
        cfg = {**CONFIG, "timeframe": "D", "timeframe_multiplier": 1}
        df = get_price_data(symbol, start, END_DATE, cfg)
        if df is not None and not df.empty:
            price = df["Close"]
            price.index = pd.to_datetime(price.index).tz_localize(None)
            return price.rename("Price")
        raise ValueError(f"Norgate returned no data for {symbol}")

    if provider == "polygon" or _polygon_key():
        from services.polygon_service import get_price_data
        cfg = {**CONFIG, "timeframe": "D", "timeframe_multiplier": 1}
        df = get_price_data(symbol, start, END_DATE, cfg)
        if df is not None and not df.empty:
            price = df["Close"]
            price.index = pd.to_datetime(price.index).tz_localize(None)
            return price.rename("Price")

    raise ValueError(f"No price data for {symbol} (provider={provider})")


def _fetch_ttm_eps(symbol: str, start: str) -> pd.Series:
    """
    Polygon /vX/reference/financials — quarterly, paginated.
    Returns TTM EPS (rolling 4-quarter sum) indexed by period_of_report_date.
    """
    key = _polygon_key()
    if not key:
        raise ValueError("POLYGON_API_KEY not set — needed for EPS data")

    url = "https://api.polygon.io/vX/reference/financials"
    params = {
        "ticker": symbol,
        "timeframe": "quarterly",
        "limit": 100,
        "sort": "period_of_report_date",
        "order": "asc",
        "apiKey": key,
    }

    all_results = []
    next_url: str | None = url
    while next_url:
        resp = requests.get(next_url, params=params, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        all_results.extend(body.get("results", []))
        cursor = body.get("next_url")
        next_url = cursor
        params = {"apiKey": key}  # cursor already encodes the rest

    if not all_results:
        raise ValueError(f"Polygon returned no financials for {symbol}")

    records = []
    for r in all_results:
        date_str = r.get("end_date")  # Polygon uses end_date for the period end
        inc = r.get("financials", {}).get("income_statement", {})
        val = (
            inc.get("diluted_earnings_per_share", {}).get("value")
            or inc.get("basic_earnings_per_share", {}).get("value")
        )
        if date_str and val is not None:
            records.append((pd.Timestamp(date_str), float(val)))

    if not records:
        raise ValueError(f"No EPS values in Polygon financials for {symbol}")

    eps_q = pd.Series(dict(records)).sort_index()
    eps_q = eps_q[eps_q.index >= pd.Timestamp(start)]

    if len(eps_q) < 4:
        raise ValueError(
            f"Only {len(eps_q)} quarters of EPS after {start}; need ≥4 for TTM"
        )

    ttm = eps_q.rolling(4).sum().dropna()
    return ttm.rename("TTM_EPS")


# ── Chart ────────────────────────────────────────────────────────────────────

def _quarter_fmt(x, _pos=None) -> str:
    try:
        dt = mdates.num2date(x)
        q = (dt.month - 1) // 3 + 1
        return f"Q{q} {dt.year}"
    except Exception:
        return ""


def _pct_change_1y(series: pd.Series):
    if series.empty:
        return None
    cutoff = series.index[-1] - pd.DateOffset(years=1)
    past = series[series.index <= cutoff]
    if past.empty:
        return None
    start_val, end_val = float(past.iloc[-1]), float(series.iloc[-1])
    return None if start_val == 0 else (end_val - start_val) / abs(start_val)


def plot_lynch_chart(symbol: str, start: str, output_dir: str | None) -> None:
    print(f"  Fetching {symbol}...")
    price = _fetch_price(symbol, start)
    ttm_eps = _fetch_ttm_eps(symbol, start)

    # Clip EPS to price window
    ttm_eps = ttm_eps[
        (ttm_eps.index >= price.index[0]) & (ttm_eps.index <= price.index[-1])
    ]

    if ttm_eps.empty:
        raise ValueError("No EPS data overlaps the price history window")

    # Implied PE: median(price / forward-filled daily EPS)
    daily_eps = ttm_eps.reindex(price.index, method="ffill").dropna()
    aligned_price = price.reindex(daily_eps.index)
    ratios = (aligned_price / daily_eps).replace([np.inf, -np.inf], np.nan).dropna()
    ratios = ratios[ratios > 0]
    implied_pe = float(np.median(ratios)) if not ratios.empty else 25.0
    current_pe = (
        float(price.iloc[-1] / ttm_eps.iloc[-1])
        if ttm_eps.iloc[-1] != 0
        else float("nan")
    )

    price_1y = _pct_change_1y(price)
    eps_1y = _pct_change_1y(ttm_eps)

    # ── Figure ───────────────────────────────────────────────────────────────
    fig, ax1 = plt.subplots(figsize=(15, 6))
    fig.patch.set_facecolor("white")
    ax1.set_facecolor("#f7f7f7")

    # Price — blue, left axis
    ax1.plot(
        price.index, price.values,
        color="#3a7fd5", linewidth=0.85, label="Price", zorder=2,
    )
    ax1.set_ylabel("Stock Price", fontsize=10)
    ax1.set_ylim(bottom=0)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:,.0f}"))

    # TTM EPS — orange, right axis
    ax2 = ax1.twinx()
    ax2.plot(
        ttm_eps.index, ttm_eps.values,
        color="#f5a623", linewidth=2.0, marker="o", markersize=4.5,
        label="EPS Dil (TTM)", zorder=3,
    )
    ax2.set_ylabel("TTM EPS (diluted)", fontsize=10)
    ax2.set_ylim(bottom=0)
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"${x:.2f}"))

    # Align axes: right ylim = left ylim / implied_pe
    lo1, hi1 = ax1.get_ylim()
    ax2.set_ylim(lo1 / implied_pe, hi1 / implied_pe)

    # EPS callout labels — alternate heights to reduce overlap
    for i, (date, val) in enumerate(ttm_eps.items()):
        offset = 14 if i % 2 == 0 else 26
        ax2.annotate(
            f"${val:.2f}",
            xy=(date, val),
            xytext=(0, offset),
            textcoords="offset points",
            ha="center", va="bottom",
            fontsize=6.5, fontweight="bold", color="white",
            bbox=dict(
                boxstyle="round,pad=0.3", facecolor="#2b2b2b",
                edgecolor="none", alpha=0.88,
            ),
            zorder=4,
        )

    # X axis — quarterly labels, thinned so they don't collide
    n_quarters = len(ttm_eps)
    if n_quarters > 20:
        # Show every 2nd quarter when history is long
        ax1.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
        ax1.xaxis.set_minor_locator(mdates.MonthLocator(bymonth=[4, 10]))
    else:
        ax1.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 4, 7, 10]))
    ax1.xaxis.set_major_formatter(mticker.FuncFormatter(_quarter_fmt))
    plt.xticks(rotation=45, ha="right", fontsize=7)

    ax1.grid(True, linestyle="--", alpha=0.35, zorder=1)

    # Title and legend
    plt.title(f"{symbol} — Earnings vs. Price", fontsize=13, fontweight="bold", pad=10)
    h1, l1 = ax1.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax1.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=9)

    # PE annotation box
    pe_color = "#c0392b" if current_pe > implied_pe * 1.1 else (
        "#27ae60" if current_pe < implied_pe * 0.9 else "#555555"
    )
    ax2.annotate(
        f"Median P/E: {implied_pe:.1f}×    Current P/E: {current_pe:.1f}×",
        xy=(0.01, 0.96), xycoords="axes fraction",
        fontsize=8, color=pe_color, fontweight="bold",
        bbox=dict(
            boxstyle="round,pad=0.35", facecolor="white",
            edgecolor="#cccccc", alpha=0.9,
        ),
    )

    fig.text(
        0.99, 0.01,
        f"Price: {CONFIG.get('data_provider','polygon').title()} | EPS: Polygon /vX/reference/financials",
        ha="right", fontsize=6.5, color="#aaaaaa",
    )

    plt.tight_layout()

    # ── Summary ──────────────────────────────────────────────────────────────
    p_str = f"{price_1y:+.1%}" if price_1y is not None else "N/A"
    e_str = f"{eps_1y:+.1%}" if eps_1y is not None else "N/A"
    discount = (current_pe / implied_pe - 1) * 100 if implied_pe else float("nan")
    signal = (
        "BUY"   if discount <= -20 and (eps_1y or 0) > 0 else
        "WATCH" if discount <= -10 and (eps_1y or 0) > 0 else
        "FAIR"  if abs(discount) <= 5 else
        "RICH"  if discount > 5 else "AVOID"
    )
    print(
        f"  {symbol}: 12m Price={p_str}  12m EPS={e_str}  "
        f"Median P/E={implied_pe:.1f}×  Current P/E={current_pe:.1f}×  "
        f"Disc={discount:+.1f}%  → {signal}"
    )

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"{symbol}_lynch_chart.png")
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  Saved → {path}")
    else:
        plt.show()


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(description="Lynch Chart: price vs. TTM diluted EPS")
    p.add_argument("symbols", nargs="+", help="Ticker symbols, e.g. MSFT AAPL NVO")
    p.add_argument("--output-dir", default=None,
                   help="Save PNGs here instead of showing interactively")
    p.add_argument("--start", default="2015-01-01",
                   help="History start date (default: 2015-01-01)")
    args = p.parse_args()

    for sym in (s.upper() for s in args.symbols):
        try:
            plot_lynch_chart(sym, start=args.start, output_dir=args.output_dir)
        except Exception as exc:
            print(f"  ERROR {sym}: {exc}")


if __name__ == "__main__":
    main()
