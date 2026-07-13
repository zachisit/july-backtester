#!/usr/bin/env python3
"""
Lynch Scanner — screens sector leaders for P/E compression vs. earnings growth.

Price data: Polygon or Norgate (reads config["data_provider"]).
EPS data:   Polygon /vX/reference/financials (annual, 4 fiscal years).

Signal logic:
  BUY    — current PE ≤ 80% of median AND EPS CAGR > 0
  WATCH  — current PE ≤ 90% of median AND EPS CAGR > 0
  FAIR   — within ±5% of median
  RICH   — current PE > 105% of median
  AVOID  — EPS CAGR ≤ 0 (earnings declining)

Usage:
    python scripts/lynch_scanner.py
    python scripts/lynch_scanner.py --start 2010-01-01
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import requests

from config import CONFIG
from dotenv import load_dotenv

load_dotenv()

END_DATE = "2026-12-31"

SECTORS = {
    "Technology":            ["MSFT", "NVDA", "AAPL"],
    "Communication Svcs":   ["META", "GOOGL", "NFLX"],
    "Consumer Discret.":    ["AMZN", "TSLA", "HD"],
    "Consumer Staples":     ["WMT", "COST", "PG"],
    "Healthcare":            ["LLY", "UNH", "JNJ"],
    "Financials":            ["JPM", "V", "MA"],
    "Industrials":           ["GE", "CAT", "UNP"],
    "Energy":                ["XOM", "CVX", "COP"],
    "Materials":             ["LIN", "SHW", "FCX"],
    "Utilities":             ["NEE", "SO", "DUK"],
    "Real Estate":           ["PLD", "AMT", "EQIX"],
}

# REITs: Polygon reports GAAP EPS which is suppressed by depreciation; FFO is the
# correct earnings metric but isn't in this endpoint. Flag them rather than mislead.
REIT_FLAG = {"PLD", "AMT", "EQIX"}


# ── Data ─────────────────────────────────────────────────────────────────────

def _polygon_key() -> str | None:
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
    raise ValueError("Polygon returned no price data")


def _fetch_ttm_eps(symbol: str) -> pd.Series:
    """
    Quarterly diluted EPS from Polygon (paginated, full history) → TTM rolling 4-sum.
    Returns TTM EPS series indexed by quarter end date.
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

    all_results = []
    next_url: str | None = url
    while next_url:
        resp = requests.get(next_url, params=params, timeout=15)
        resp.raise_for_status()
        body = resp.json()
        all_results.extend(body.get("results", []))
        cursor = body.get("next_url")
        next_url = cursor
        params = {"apiKey": key}

    if not all_results:
        raise ValueError("No financials from Polygon")

    records = []
    for r in all_results:
        date_str = r.get("end_date")
        inc = r.get("financials", {}).get("income_statement", {})
        val = (
            inc.get("diluted_earnings_per_share", {}).get("value")
            or inc.get("basic_earnings_per_share", {}).get("value")
        )
        if date_str and val is not None:
            records.append((pd.Timestamp(date_str), float(val)))

    if not records:
        raise ValueError("No EPS values in Polygon financials")

    eps_q = pd.Series(dict(records)).sort_index()

    if len(eps_q) < 4:
        raise ValueError(f"Only {len(eps_q)} quarters; need ≥4 for TTM")

    ttm = eps_q.rolling(4).sum().dropna()
    return ttm.rename("TTM_EPS")


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score(symbol: str, start: str) -> dict:
    price = _fetch_price(symbol, start)
    eps = _fetch_ttm_eps(symbol)

    # Clip TTM series to price window
    eps = eps[(eps.index >= price.index[0]) & (eps.index <= price.index[-1])]
    if eps.empty:
        raise ValueError("EPS does not overlap price history")

    # Forward-fill quarterly TTM EPS to daily for median PE calculation
    combined_idx = eps.index.union(price.index).sort_values()
    daily_eps = eps.reindex(combined_idx).ffill().reindex(price.index)

    valid = daily_eps.dropna()
    if valid.empty:
        raise ValueError("EPS forward-fill produced no valid days")

    pe_series = (price.reindex(valid.index) / valid).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    pe_series = pe_series[pe_series > 0]

    if pe_series.empty:
        raise ValueError("No valid PE observations")

    median_pe = float(np.median(pe_series))
    current_pe = float(price.iloc[-1] / eps.iloc[-1]) if eps.iloc[-1] != 0 else float("nan")

    # EPS CAGR: first available TTM → latest TTM
    eps_cagr = None
    if len(eps) >= 2:
        first, last = float(eps.iloc[0]), float(eps.iloc[-1])
        years = (eps.index[-1] - eps.index[0]).days / 365.25
        if first > 0 and last > 0 and years > 0:
            eps_cagr = (last / first) ** (1 / years) - 1

    pe_disc = (current_pe / median_pe - 1) if median_pe and not np.isnan(current_pe) else None

    if np.isnan(current_pe) or pe_disc is None or eps_cagr is None:
        signal = "N/A"
    elif eps_cagr <= 0:
        signal = "AVOID"
    elif pe_disc <= -0.20:
        signal = "BUY"
    elif pe_disc <= -0.10:
        signal = "WATCH"
    elif pe_disc <= 0.05:
        signal = "FAIR"
    else:
        signal = "RICH"

    return {
        "current_pe": current_pe,
        "median_pe": median_pe,
        "pe_disc_pct": pe_disc * 100 if pe_disc is not None else None,
        "eps_cagr_pct": eps_cagr * 100 if eps_cagr is not None else None,
        "signal": signal,
        "price": float(price.iloc[-1]),
    }


# ── Display ───────────────────────────────────────────────────────────────────

SIGNAL_COLOUR = {
    "BUY":   "\033[92m",
    "WATCH": "\033[93m",
    "FAIR":  "\033[96m",
    "RICH":  "\033[91m",
    "AVOID": "\033[91m",
    "FLAG":  "\033[90m",
    "N/A":   "\033[90m",
    "ERR":   "\033[90m",
}
RESET = "\033[0m"
SIGNAL_ORDER = {"BUY": 0, "WATCH": 1, "FAIR": 2, "RICH": 3, "AVOID": 4, "FLAG": 5, "N/A": 6, "ERR": 7}


def _f(val, fmt, fallback="N/A"):
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return fallback
    return fmt.format(val)


def main():
    p = argparse.ArgumentParser(description="Lynch sector-leader scanner")
    p.add_argument("--start", default="2015-01-01",
                   help="Price history start for median PE (default: 2015-01-01)")
    args = p.parse_args()

    all_rows, buy_rows = [], []

    provider = CONFIG.get("data_provider", "polygon").title()
    print(f"\nLynch Scanner  |  Price: {provider}  |  EPS: Polygon  |  history from {args.start}\n")
    print(
        f"{'Sector':<22} {'Sym':<6} {'Price':>8} {'Cur PE':>8} "
        f"{'Med PE':>8} {'Disc':>8} {'EPS CAGR':>10}  Signal"
    )
    print("─" * 84)

    for sector, tickers in SECTORS.items():
        for sym in tickers:
            try:
                if sym in REIT_FLAG:
                    row = {"signal": "FLAG", "error": "REIT — use FFO not EPS"}
                else:
                    row = _score(sym, args.start)
            except Exception as exc:
                row = {"signal": "ERR", "error": str(exc)}

            row = {"sector": sector, "symbol": sym, **row}
            all_rows.append(row)
            if row["signal"] == "BUY":
                buy_rows.append(row)

            sig = row["signal"]
            c = SIGNAL_COLOUR.get(sig, "")
            print(
                f"{sector:<22} {sym:<6} "
                f"{_f(row.get('price'), '${:,.2f}'):>8} "
                f"{_f(row.get('current_pe'), '{:.1f}×'):>8} "
                f"{_f(row.get('median_pe'), '{:.1f}×'):>8} "
                f"{_f(row.get('pe_disc_pct'), '{:+.1f}%'):>8} "
                f"{_f(row.get('eps_cagr_pct'), '{:+.1f}%/yr'):>10}  "
                f"{c}{sig}{RESET}"
            )

            time.sleep(0.25)

    print("─" * 84)

    print(f"\n{'  BUY SIGNALS  ':=^60}")
    if buy_rows:
        buy_rows.sort(key=lambda r: r.get("pe_disc_pct") or 0)
        for r in buy_rows:
            print(
                f"  {r['symbol']:<6}  {r['sector']:<22}  "
                f"cur {_f(r['current_pe'], '{:.1f}×'):>7}  "
                f"med {_f(r['median_pe'], '{:.1f}×'):>7}  "
                f"disc {_f(r['pe_disc_pct'], '{:+.1f}%'):>7}  "
                f"EPS {_f(r['eps_cagr_pct'], '{:+.1f}%/yr'):>9}/yr"
            )
    else:
        print("  None — market broadly at or above historical P/E averages.")

    print()
    flag_syms = [r["symbol"] for r in all_rows if r.get("signal") in ("FLAG", "ERR")]
    if flag_syms:
        for r in all_rows:
            if r.get("signal") in ("FLAG", "ERR"):
                print(f"  {r['symbol']}: {r.get('error','')}")
    print()


if __name__ == "__main__":
    main()
