#!/usr/bin/env python3
"""
FCF Yield vs. 10-Year Treasury — Buffett's gravity chart.

Plots a company's operating cash flow yield (TTM op CF / market cap) against
the 10-year Treasury yield on the same percentage axis. When CF yield > Treasury,
the equity is generating more cash than you'd earn risk-free — Buffett's signal
that the "gravity" pulling stocks down is weaker than the business's cash power.

  Green shading = CF yield > Treasury (historically strong forward returns)
  Red shading   = Treasury yield > CF yield (bonds are competitive)

Note: Polygon does not expose capex as a line item, so this uses operating cash
flow as the numerator (a slightly generous FCF proxy). Label is "Op CF Yield".

Price:    Polygon or Norgate (reads config["data_provider"])
CF data:  Polygon /vX/reference/financials (quarterly, paginated, TTM)
Treasury: yfinance ^TNX

Usage:
    python scripts/fcf_yield_chart.py AAPL MSFT META
    python scripts/fcf_yield_chart.py AAPL --start 2015-01-01 --output-dir /tmp/charts
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
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

def _polygon_key():
    return os.environ.get(CONFIG.get("polygon_api_secret_name", "POLYGON_API_KEY"))


def _fetch_price(symbol: str, start: str) -> pd.Series:
    provider = CONFIG.get("data_provider", "polygon").lower()
    if provider == "norgate":
        from services.norgate_service import get_price_data
        cfg = {**CONFIG, "timeframe": "D", "timeframe_multiplier": 1}
        df = get_price_data(symbol, start, END_DATE, cfg)
        if df is not None and not df.empty:
            s = df["Close"]
            s.index = pd.to_datetime(s.index).tz_localize(None)
            return s.rename("Price")
        raise ValueError("Norgate returned no data")
    from services.polygon_service import get_price_data
    cfg = {**CONFIG, "timeframe": "D", "timeframe_multiplier": 1}
    df = get_price_data(symbol, start, END_DATE, cfg)
    if df is not None and not df.empty:
        s = df["Close"]
        s.index = pd.to_datetime(s.index).tz_localize(None)
        return s.rename("Price")
    raise ValueError(f"No price data for {symbol}")


def _fetch_treasury(start: str) -> pd.Series:
    import yfinance as yf
    tnx = yf.Ticker("^TNX").history(start=start, auto_adjust=False)
    if tnx.empty:
        raise ValueError("No Treasury data from yfinance ^TNX")
    s = tnx["Close"].rename("TNX_pct")
    s.index = pd.to_datetime(s.index).tz_localize(None)
    return s


def _fetch_quarterly_cf(symbol: str) -> pd.DataFrame:
    """
    Returns DataFrame indexed by quarter end date with columns:
      op_cf_q   — quarterly operating cash flow (USD)
      shares_q  — quarterly diluted average shares
    """
    key = _polygon_key()
    if not key:
        raise ValueError("POLYGON_API_KEY not set")

    url = "https://api.polygon.io/vX/reference/financials"
    params = {
        "ticker": symbol,
        "timeframe": "quarterly",
        "limit": 100,
        "sort": "period_of_report_date",
        "order": "asc",
        "apiKey": key,
    }

    all_results, next_url = [], url
    while next_url:
        resp = requests.get(next_url, params=params, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        all_results.extend(body.get("results", []))
        next_url = body.get("next_url")
        params = {"apiKey": key}

    if not all_results:
        raise ValueError(f"No Polygon financials for {symbol}")

    records = []
    for r in all_results:
        date_str = r.get("end_date")
        cf  = r.get("financials", {}).get("cash_flow_statement", {})
        inc = r.get("financials", {}).get("income_statement", {})

        op_cf = (
            cf.get("net_cash_flow_from_operating_activities", {}).get("value")
            or cf.get("net_cash_flow_from_operating_activities_continuing", {}).get("value")
        )
        shares = (
            inc.get("diluted_average_shares", {}).get("value")
            or inc.get("basic_average_shares", {}).get("value")
        )

        if date_str and op_cf is not None and shares and shares > 0:
            records.append({
                "date":    pd.Timestamp(date_str),
                "op_cf_q": float(op_cf),
                "shares_q": float(shares),
            })

    if not records:
        raise ValueError(f"No op CF + shares data for {symbol}")

    return pd.DataFrame(records).set_index("date").sort_index()


def _build_yield_series(price: pd.Series, cf_df: pd.DataFrame) -> pd.Series:
    """
    TTM Op CF Yield % = (rolling 4-quarter sum of op_cf) /
                        (avg diluted shares × daily price) × 100
    """
    ttm_cf     = cf_df["op_cf_q"].rolling(4).sum().dropna()
    ttm_shares = cf_df["shares_q"].rolling(4).mean().dropna()

    # Forward-fill both quarterly series to daily price index
    idx = ttm_cf.index.union(ttm_shares.index).union(price.index).sort_values()
    cf_daily     = ttm_cf.reindex(idx).ffill().reindex(price.index)
    shares_daily = ttm_shares.reindex(idx).ffill().reindex(price.index)

    mktcap = price * shares_daily          # USD
    yield_pct = (cf_daily / mktcap * 100).replace([np.inf, -np.inf], np.nan)

    # Sanity clip: yields outside −30%…+80% are data artefacts
    yield_pct = yield_pct.clip(-30, 80)
    return yield_pct.dropna().rename("CF_Yield_pct")


# ── Chart ────────────────────────────────────────────────────────────────────

def _quarter_fmt(x, _pos=None) -> str:
    try:
        dt = mdates.num2date(x)
        return f"Q{(dt.month-1)//3+1} {dt.year}"
    except Exception:
        return ""


def _annotate_crossovers(ax, idx, cf_yield, treasury, n_max=6):
    """Mark the most recent N crossovers with thin vertical dashed lines."""
    above = (cf_yield > treasury).astype(int)
    changes = above.diff().fillna(0)
    cross_dates = changes[changes != 0].index[-n_max:]
    for dt in cross_dates:
        ax.axvline(dt, color="#888888", linewidth=0.6, linestyle=":", alpha=0.7)


def plot_fcf_chart(symbol: str, start: str, output_dir: str | None) -> None:
    print(f"  Fetching {symbol}...")
    price    = _fetch_price(symbol, start)
    treasury = _fetch_treasury(start)
    cf_df    = _fetch_quarterly_cf(symbol)

    cf_yield = _build_yield_series(price, cf_df)

    # Align to common daily index
    common   = cf_yield.index.intersection(treasury.index)
    cf_a     = cf_yield.reindex(common)
    tnx_a    = treasury.reindex(common).ffill()
    spread   = cf_a - tnx_a

    cur_cf   = float(cf_a.iloc[-1])
    cur_tnx  = float(tnx_a.iloc[-1])
    cur_spr  = cur_cf - cur_tnx
    pct_time_above = (spread > 0).mean() * 100

    # ── Figure ───────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(15, 6))
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#f7f7f7")

    # Shading
    ax.fill_between(common, cf_a.values, tnx_a.values,
                    where=(cf_a.values >= tnx_a.values),
                    color="#27ae60", alpha=0.18, zorder=1)
    ax.fill_between(common, cf_a.values, tnx_a.values,
                    where=(cf_a.values < tnx_a.values),
                    color="#e74c3c", alpha=0.12, zorder=1)

    # Lines
    ax.plot(common, tnx_a.values, color="#3a7fd5", linewidth=1.1,
            label="10-Year Treasury Yield", zorder=3)
    ax.plot(common, cf_a.values,  color="#f5a623", linewidth=1.9,
            label=f"{symbol} Operating CF Yield (TTM)", zorder=4)

    _annotate_crossovers(ax, common, cf_a, tnx_a)

    # Axes
    y_lo = min(0, float(cf_a.min()) - 0.5, float(tnx_a.min()) - 0.5)
    y_hi = max(float(cf_a.max()), float(tnx_a.max())) + 1.0
    ax.set_ylim(y_lo, y_hi)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.1f}%"))
    ax.set_ylabel("Yield (%)", fontsize=10)

    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7]))
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(_quarter_fmt))
    plt.xticks(rotation=45, ha="right", fontsize=7)
    ax.grid(True, linestyle="--", alpha=0.35, zorder=1)

    # Legend
    green_p = mpatches.Patch(color="#27ae60", alpha=0.45,
                              label=f"CF yield > Treasury  ({pct_time_above:.0f}% of period)")
    red_p   = mpatches.Patch(color="#e74c3c", alpha=0.35,
                              label="Treasury > CF yield")
    h, l = ax.get_legend_handles_labels()
    ax.legend(h + [green_p, red_p], l + [green_p.get_label(), red_p.get_label()],
              loc="upper left", fontsize=8)

    # Status box
    sig_color = "#27ae60" if cur_spr > 0 else "#c0392b"
    sig_label = "CF YIELD ABOVE TREASURY ✓" if cur_spr > 0 else "TREASURY YIELD WINS ✗"
    ax.annotate(
        f"Op CF Yield: {cur_cf:.2f}%    10Y Treasury: {cur_tnx:.2f}%    "
        f"Spread: {cur_spr:+.2f}%    {sig_label}",
        xy=(0.01, 0.96), xycoords="axes fraction",
        fontsize=8, fontweight="bold", color=sig_color,
        bbox=dict(boxstyle="round,pad=0.35", facecolor="white",
                  edgecolor="#dddddd", alpha=0.92),
    )

    # Quote
    ax.annotate(
        "\"Interest rates are to asset values what gravity is to matter.\"  — Warren Buffett",
        xy=(0.01, 0.04), xycoords="axes fraction",
        fontsize=7.5, color="#777777", style="italic",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                  edgecolor="none", alpha=0.75),
    )

    plt.title(f"{symbol} — Operating CF Yield vs. 10-Year Treasury",
              fontsize=13, fontweight="bold", pad=10)
    fig.text(0.99, 0.01,
             "Price: Polygon  |  CF: Polygon /vX/reference/financials  |  Rates: yfinance ^TNX",
             ha="right", fontsize=6.5, color="#aaaaaa")
    plt.tight_layout()

    # Summary
    print(f"  {symbol}: CF Yield={cur_cf:.2f}%  10Y={cur_tnx:.2f}%  "
          f"Spread={cur_spr:+.2f}%  "
          f"{'ABOVE TREASURY' if cur_spr > 0 else 'BELOW TREASURY'}  "
          f"(above {pct_time_above:.0f}% of period)")

    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        path = os.path.join(output_dir, f"{symbol}_fcf_yield.png")
        plt.savefig(path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  Saved → {path}")
    else:
        plt.show()


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser(
        description="Op CF Yield vs 10Y Treasury — Buffett gravity chart"
    )
    p.add_argument("symbols", nargs="+", help="Tickers, e.g. AAPL MSFT META")
    p.add_argument("--output-dir", default=None,
                   help="Save PNGs here instead of showing interactively")
    p.add_argument("--start", default="2015-01-01",
                   help="History start (default: 2015-01-01)")
    args = p.parse_args()

    for sym in (s.upper() for s in args.symbols):
        try:
            plot_fcf_chart(sym, start=args.start, output_dir=args.output_dir)
        except Exception as exc:
            print(f"  ERROR {sym}: {exc}")


if __name__ == "__main__":
    main()
