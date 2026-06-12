#!/usr/bin/env python3
"""
fetch_leadership_bardata.py
============================
For each leadership trade in leadership_trades.csv, fetch daily OHLCV bars
from Polygon covering 30 days before entry through 30 days after exit.

Output: one CSV per trade in research/leadership_bardata/
  {trade_id}_{symbol}_entry{entry_date}_exit{exit_date}.csv

Columns: date, open, high, low, close, volume
Plus a metadata header block at the top of each file so interns have context.

Usage:
    python scripts/fetch_leadership_bardata.py
    python scripts/fetch_leadership_bardata.py --trades-csv /path/to/trades.csv
    python scripts/fetch_leadership_bardata.py --dry-run
"""

import os
import sys
import time
import argparse
import logging
import csv
from datetime import datetime, timedelta

import requests
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    # Also try the vsa tool .env as fallback
    if not os.environ.get("POLYGON_API_KEY"):
        load_dotenv(os.path.expanduser(
            "~/Desktop/gitlab/july-backtester-v2/tools/active/vsa/.env"
        ))
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fetch_leadership_bardata")

POLYGON_API_KEY = os.environ.get("POLYGON_API_KEY", "KgQLJzkqIIvsXLCZqCsXe2cSmt7h4nnE")
API_BASE = "https://api.polygon.io"
WINDOW_DAYS = 30
DEFAULT_TRADES_CSV = os.path.expanduser("~/Desktop/leadership_trades.csv")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "research", "leadership_bardata")


def fetch_bars(symbol: str, from_date: str, to_date: str) -> pd.DataFrame:
    """Fetch daily adjusted bars from Polygon for [from_date, to_date]."""
    url = f"{API_BASE}/v2/aggs/ticker/{symbol}/range/1/day/{from_date}/{to_date}"
    params = {
        "adjusted": "true",
        "sort": "asc",
        "limit": 50000,
        "apiKey": POLYGON_API_KEY,
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 429:
            logger.warning("Rate limited — sleeping 60s")
            time.sleep(60)
            resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("Polygon error for %s: %s", symbol, e)
        return pd.DataFrame()

    results = data.get("results") or []
    if not results:
        logger.warning("%s: no bars returned for %s → %s", symbol, from_date, to_date)
        return pd.DataFrame()

    df = pd.DataFrame(results)
    df["date"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.normalize().dt.date
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df[["date", "open", "high", "low", "close", "volume"]].copy()
    df = df.sort_values("date").reset_index(drop=True)
    return df


def write_trade_csv(trade: dict, df: pd.DataFrame, output_dir: str) -> str:
    """Write bars + metadata header to a per-trade CSV. Returns the file path."""
    tid = trade["trade_id"]
    sym = trade["symbol"]
    entry = trade["entry_date"]
    exit_ = trade["exit_date"]
    fname = f"{tid}_{sym}_entry{entry}_exit{exit_}.csv"
    path = os.path.join(output_dir, fname)

    with open(path, "w", newline="") as f:
        f.write("# LEADERSHIP TRADE BAR DATA\n")
        f.write(f"# trade_id     : {tid}\n")
        f.write(f"# symbol       : {sym}\n")
        f.write(f"# entry_date   : {entry}\n")
        f.write(f"# exit_date    : {exit_}\n")
        f.write(f"# entry_price  : {trade['entry_price']}\n")
        f.write(f"# exit_price   : {trade['exit_price']}\n")
        f.write(f"# profit_pct   : {trade['profit_pct']}\n")
        f.write(f"# realized_pnl : {trade['realized_pl_dollars']}\n")
        f.write(f"# shares       : {trade['shares']}\n")
        f.write(f"# exit_reason  : {trade['exit_reason']}\n")
        f.write(f"# bar_window   : {WINDOW_DAYS}d before entry → {WINDOW_DAYS}d after exit\n")
        f.write(f"# total_bars   : {len(df)}\n")
        f.write("#\n")
        df.to_csv(f, index=False)

    return path


def main():
    parser = argparse.ArgumentParser(description="Package leadership trade bar data for intern analysis")
    parser.add_argument("--trades-csv", default=DEFAULT_TRADES_CSV,
                        help=f"Path to trades CSV (default: {DEFAULT_TRADES_CSV})")
    parser.add_argument("--output-dir", default=OUTPUT_DIR,
                        help=f"Output directory (default: {OUTPUT_DIR})")
    parser.add_argument("--window", type=int, default=WINDOW_DAYS,
                        help=f"Days before/after trade to include (default: {WINDOW_DAYS})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would run without fetching")
    args = parser.parse_args()

    if not os.path.exists(args.trades_csv):
        logger.error("Trades CSV not found: %s", args.trades_csv)
        sys.exit(1)

    os.makedirs(args.output_dir, exist_ok=True)

    with open(args.trades_csv) as f:
        trades = list(csv.DictReader(f))

    logger.info("Loaded %d trades from %s", len(trades), args.trades_csv)
    logger.info("Output: %s", args.output_dir)

    ok = failed = skipped = 0

    for i, trade in enumerate(trades, 1):
        tid = trade["trade_id"]
        sym = trade["symbol"]
        entry = trade["entry_date"]
        exit_ = trade["exit_date"]

        # Compute window
        try:
            entry_dt = datetime.strptime(entry, "%Y-%m-%d")
            exit_dt = datetime.strptime(exit_, "%Y-%m-%d")
        except ValueError as e:
            logger.warning("Trade %s (%s): bad date — %s, skipping", tid, sym, e)
            failed += 1
            continue

        from_date = (entry_dt - timedelta(days=args.window)).strftime("%Y-%m-%d")
        to_date = (exit_dt + timedelta(days=args.window)).strftime("%Y-%m-%d")

        fname = f"{tid}_{sym}_entry{entry}_exit{exit_}.csv"
        out_path = os.path.join(args.output_dir, fname)

        if os.path.exists(out_path):
            logger.info("[%d/%d] %s %s — already exists, skipping", i, len(trades), sym, tid)
            skipped += 1
            continue

        if args.dry_run:
            logger.info("[DRY RUN] %s trade %s: %s → %s (window: %s → %s)",
                        sym, tid, entry, exit_, from_date, to_date)
            ok += 1
            continue

        logger.info("[%d/%d] %s trade %s: fetching %s → %s", i, len(trades), sym, tid, from_date, to_date)
        df = fetch_bars(sym, from_date, to_date)

        if df.empty:
            failed += 1
            continue

        path = write_trade_csv(trade, df, args.output_dir)
        logger.info("  → %d bars saved to %s", len(df), os.path.basename(path))
        ok += 1
        time.sleep(0.25)  # stay within Polygon rate limits

    print(f"\nDone — {ok} saved, {skipped} skipped (already exist), {failed} failed")
    print(f"Output: {args.output_dir}")


if __name__ == "__main__":
    main()
