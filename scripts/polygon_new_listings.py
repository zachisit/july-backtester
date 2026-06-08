"""
polygon_new_listings.py — weekly IPO scan (Issue #191, §5).

The daily updater (polygon_daily_update.py) only touches symbols that already
have a Parquet file, so brand-new listings would never enter the universe.
This script closes that gap on a weekly cadence:

  1. Pull Polygon's active stock universe (/v3/reference/tickers, paginated).
  2. Diff it against the equity Parquet files already in parquet_data/data/.
  3. For each genuinely new ticker, fetch its full daily history and write a
     new Parquet file in the canonical format.

A new IPO has no usable history for momentum/MR strategies until it has 60–200
bars, so weekly latency costs nothing — this is intentionally NOT in the daily
hot path. Run it from its own weekly cron.

Usage:
    python scripts/polygon_new_listings.py                 # add new listings (full history)
    python scripts/polygon_new_listings.py --since 2026-04-23   # cap history start
    python scripts/polygon_new_listings.py --dry-run       # list new tickers, no writes
    python scripts/polygon_new_listings.py --limit 25      # cap how many new files to create
"""

import os
import sys
import logging
import argparse
from datetime import datetime

import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # so we can import the sibling script

from polygon_daily_update import (  # noqa: E402
    API_BASE, SEAM_DATE, DEFAULT_DATA_DIR,
    classify_symbol, get_api_key, polygon_get, fetch_ticker_range,
    bars_to_df, append_and_write, last_trading_day,
)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("polygon_new_listings")

# Default earliest history to fetch for a brand-new file. Most IPOs are recent,
# so this is just a floor; Polygon returns from the listing date onward anyway.
DEFAULT_HISTORY_START = "2004-01-01"


def fetch_active_equities(session, api_key: str) -> set[str]:
    """Return the set of active common-stock tickers from Polygon reference data."""
    tickers: set[str] = set()
    path = "/v3/reference/tickers"
    params = {"market": "stocks", "active": "true", "type": "CS", "limit": 1000, "order": "asc"}
    page = 0
    while path:
        resp = polygon_get(session, api_key, path, params)
        for row in resp.get("results", []) or []:
            t = row.get("ticker")
            if t:
                tickers.add(t.upper())
        page += 1
        next_url = resp.get("next_url")
        if not next_url:
            break
        # next_url is absolute and carries the cursor; strip base + re-attach apiKey via polygon_get.
        path = next_url.replace(API_BASE, "")
        params = None  # cursor already encoded in next_url
        if page % 5 == 0:
            logger.info("  reference: %d pages, %d tickers so far...", page, len(tickers))
    logger.info("Polygon active common-stock universe: %d tickers (%d pages).", len(tickers), page)
    return tickers


def existing_equity_symbols(data_dir: str) -> set[str]:
    """Uppercased set of equity symbols that already have a Parquet file."""
    out: set[str] = set()
    for f in os.listdir(data_dir):
        if not f.lower().endswith(".parquet"):
            continue
        kind, base = classify_symbol(f)
        if kind == "equity":
            out.add(base.upper())
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Weekly Polygon new-listings scan (#191)")
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    ap.add_argument("--since", default=DEFAULT_HISTORY_START,
                    help=f"Earliest history date to fetch for new files (default {DEFAULT_HISTORY_START})")
    ap.add_argument("--end", help="End date YYYY-MM-DD (default: last trading day)")
    ap.add_argument("--dry-run", action="store_true", help="List new tickers only — no writes")
    ap.add_argument("--limit", type=int, default=0, help="Cap how many new files to create (testing)")
    ap.add_argument("--no-adjust", action="store_true", help="Fetch unadjusted bars (default: split-adjusted)")
    args = ap.parse_args(argv)

    adjusted = not args.no_adjust
    api_key = get_api_key()
    session = requests.Session()

    if not os.path.isdir(args.data_dir):
        logger.error("Data dir not found: %s (is the parquet_data submodule checked out?)", args.data_dir)
        return 1

    active = fetch_active_equities(session, api_key)
    have = existing_equity_symbols(args.data_dir)
    new_tickers = sorted(active - have)
    logger.info("New listings to add: %d (active %d − existing %d).", len(new_tickers), len(active), len(have))

    if not new_tickers:
        logger.info("Universe already current — nothing to add.")
        return 0

    if args.limit:
        new_tickers = new_tickers[: args.limit]

    if args.dry_run:
        logger.info("[DRY RUN] Would create %d files: %s%s",
                    len(new_tickers), ", ".join(new_tickers[:20]),
                    " ..." if len(new_tickers) > 20 else "")
        return 0

    end_date = args.end or last_trading_day(session, api_key)
    created = failed = 0
    for sym in new_tickers:
        rows = fetch_ticker_range(session, api_key, sym, args.since, end_date, adjusted)
        if not rows:
            logger.warning("New ticker %s: no bars %s..%s — skipped.", sym, args.since, end_date)
            failed += 1
            continue
        df = bars_to_df(rows)
        path = os.path.join(args.data_dir, f"{sym}.parquet")
        added = append_and_write(path, df, dry_run=False)
        if added:
            created += 1
            logger.info("  + %s.parquet (%d bars, last %s)", sym, added, df.index.max().date())
        else:
            failed += 1

    logger.info("New-listings scan complete: %d created, %d failed/empty.", created, failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
