"""
polygon_daily_update.py — daily Polygon → Parquet updater (Issue #191).

Keeps the ``parquet_data/`` submodule current after the Norgate freeze at
2026-04-22. For every symbol that already has a Parquet file it fetches the new
daily bars from Polygon and appends them, writing files in exactly the format
the backtester's ``data_provider: "parquet"`` path expects:

    Index  : DatetimeIndex, UTC-aware, name='Datetime', midnight-normalized
    Columns: ['Open', 'High', 'Low', 'Close', 'Volume']

Symbol universe (three kinds, by filename prefix):
    (none)  AAPL.parquet   → equity. Fetched via the grouped endpoint
                             (one call per date returns every ticker) — cheap.
    $       $VIX.parquet    → index. Mapped to Polygon's ``I:VIX`` via
                             helpers.ticker_normalizer.normalize_ticker and
                             fetched per-ticker (indices are not in grouped/stocks).
    #       #AMEXAD.parquet → Norgate-only market-breadth indicator. Not on
                             Polygon — skipped and frozen at 2026-04-22.

Adjustment seam (see #191): Polygon ``adjusted=true`` is split-adjusted only
(no dividend reinvestment), whereas Norgate was total-return. Bars at/after the
seam therefore diverge for dividend payers. This is accepted per the issue
decision — split-adjusted only, no dividend pull.

Usage:
    python scripts/polygon_daily_update.py                  # update to last trading day
    python scripts/polygon_daily_update.py --start 2026-04-23   # backfill override
    python scripts/polygon_daily_update.py --dry-run        # plan only, no writes
    python scripts/polygon_daily_update.py --limit 50       # process first 50 files (testing)
    python scripts/polygon_daily_update.py --only AAPL,MSFT,\\$VIX   # subset
"""

import os
import sys
import time
import logging
import argparse
from datetime import datetime, timedelta

import pandas as pd
import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from helpers.ticker_normalizer import normalize_ticker  # noqa: E402

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("polygon_daily_update")

API_BASE = "https://api.polygon.io"
DEFAULT_DATA_DIR = os.path.join("parquet_data", "data")
SEAM_DATE = "2026-04-23"          # first day Norgate did NOT cover (last Norgate bar = 2026-04-22)
CANONICAL_COLS = ["Open", "High", "Low", "Close", "Volume"]
_RATE_LIMIT_SLEEP = 0.0           # seconds between per-ticker index calls; bumped on HTTP 429


# ──────────────────────────────────────────────────────────────────────────────
# Symbol classification
# ──────────────────────────────────────────────────────────────────────────────
def classify_symbol(filename: str) -> tuple[str, str]:
    """Map a parquet filename to (kind, base_symbol).

    kind is one of "equity", "index", "breadth". base_symbol keeps the original
    Norgate prefix ($ for indices) so normalize_ticker can map it to Polygon.
    """
    base = filename[:-len(".parquet")] if filename.lower().endswith(".parquet") else filename
    if base.startswith("#"):
        return "breadth", base
    if base.startswith("$"):
        return "index", base
    return "equity", base


# ──────────────────────────────────────────────────────────────────────────────
# Polygon HTTP
# ──────────────────────────────────────────────────────────────────────────────
def get_api_key() -> str:
    key = os.environ.get("POLYGON_API_KEY")
    if not key:
        logger.error("POLYGON_API_KEY not set (env or .env). Cannot fetch from Polygon.")
        sys.exit(1)
    return key


def polygon_get(session: requests.Session, api_key: str, path: str, params: dict | None = None) -> dict:
    """GET a Polygon endpoint and return parsed JSON. Returns {} on HTTP error."""
    p = {"apiKey": api_key}
    if params:
        p.update(params)
    try:
        resp = session.get(API_BASE + path, params=p, timeout=30)
        if resp.status_code == 429:
            logger.warning("Polygon rate limit (429) on %s — backing off 5s.", path)
            time.sleep(5)
            resp = session.get(API_BASE + path, params=p, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        logger.warning("Polygon HTTP error on %s: %s", path, e)
        return {}


def fetch_grouped_day(session, api_key, date_str: str, adjusted: bool) -> dict[str, dict]:
    """One grouped call → {TICKER_UPPER: {o,h,l,c,v}} for every equity on date_str.

    Empty dict on a market holiday / weekend (resultsCount == 0).
    """
    resp = polygon_get(
        session, api_key,
        f"/v2/aggs/grouped/locale/us/market/stocks/{date_str}",
        {"adjusted": "true" if adjusted else "false"},
    )
    out: dict[str, dict] = {}
    for bar in resp.get("results", []) or []:
        t = bar.get("T")
        if not t:
            continue
        out[t.upper()] = {
            "o": bar.get("o"), "h": bar.get("h"),
            "l": bar.get("l"), "c": bar.get("c"), "v": bar.get("v", 0),
        }
    return out


def fetch_ticker_range(session, api_key, polygon_symbol: str, start: str, end: str, adjusted: bool) -> list[dict]:
    """Per-ticker aggregates over [start, end] — used for index ($) symbols."""
    resp = polygon_get(
        session, api_key,
        f"/v2/aggs/ticker/{polygon_symbol}/range/1/day/{start}/{end}",
        {"adjusted": "true" if adjusted else "false", "sort": "asc", "limit": 50000},
    )
    return resp.get("results", []) or []


# ──────────────────────────────────────────────────────────────────────────────
# Parquet I/O
# ──────────────────────────────────────────────────────────────────────────────
def read_last_date(path: str) -> pd.Timestamp | None:
    """Return the last (max) DatetimeIndex value in a parquet file, or None."""
    try:
        df = pd.read_parquet(path)
    except Exception as e:  # noqa: BLE001
        logger.warning("Could not read %s: %s", path, e)
        return None
    if df.empty:
        return None
    idx = pd.to_datetime(df.index, utc=True)
    return idx.max()


def bars_to_df(rows: list[dict]) -> pd.DataFrame:
    """Convert Polygon agg rows (with 't' ms timestamps) to the canonical frame."""
    if not rows:
        return pd.DataFrame(columns=CANONICAL_COLS)
    df = pd.DataFrame(rows)
    df["Datetime"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.normalize()
    df = df.set_index("Datetime")
    df = df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
    present = [c for c in CANONICAL_COLS if c in df.columns]
    return df[present]


def grouped_rows_to_df(day_rows: list[tuple[str, dict]]) -> pd.DataFrame:
    """Build a canonical frame from [(date_str, {o,h,l,c,v}), ...] grouped hits."""
    if not day_rows:
        return pd.DataFrame(columns=CANONICAL_COLS)
    recs = []
    for date_str, bar in day_rows:
        recs.append({
            "Datetime": pd.Timestamp(date_str, tz="UTC").normalize(),
            "Open": bar.get("o"), "High": bar.get("h"), "Low": bar.get("l"),
            "Close": bar.get("c"), "Volume": bar.get("v", 0),
        })
    df = pd.DataFrame(recs).set_index("Datetime")
    return df[[c for c in CANONICAL_COLS if c in df.columns]]


def append_and_write(path: str, new_df: pd.DataFrame, dry_run: bool) -> int:
    """Append new_df to the existing parquet, dedup on index (keep last), sort.

    Returns the number of genuinely new rows written (after dedup).
    """
    if new_df is None or new_df.empty:
        return 0
    new_df = new_df.copy()
    new_df.index = pd.to_datetime(new_df.index, utc=True)

    if os.path.exists(path):
        try:
            existing = pd.read_parquet(path)
        except Exception as e:  # noqa: BLE001
            logger.warning("Could not read existing %s for append: %s", path, e)
            existing = pd.DataFrame(columns=CANONICAL_COLS)
        existing.index = pd.to_datetime(existing.index, utc=True)
        before = len(existing)
        combined = pd.concat([existing, new_df])
    else:
        before = 0
        combined = new_df

    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    combined.index.name = "Datetime"
    added = len(combined) - before
    if added <= 0:
        return 0
    if not dry_run:
        combined.to_parquet(path)
    return added


def last_trading_day(session, api_key, before: str | None = None) -> str:
    """Most recent trading day (YYYY-MM-DD) per Polygon SPY data."""
    d = datetime.now() if before is None else datetime.strptime(before, "%Y-%m-%d")
    for _ in range(10):
        d -= timedelta(days=1)
        ds = d.strftime("%Y-%m-%d")
        resp = polygon_get(session, api_key, f"/v2/aggs/ticker/SPY/range/1/day/{ds}/{ds}")
        if resp.get("resultsCount", 0) > 0:
            return ds
    raise RuntimeError("Could not determine last trading day from Polygon.")


def _business_days(start: str, end: str) -> list[str]:
    """Trading days in [start, end].

    Prefers the NYSE calendar (skips market holidays like MLK Day, Thanksgiving)
    when ``pandas_market_calendars`` is installed; otherwise falls back to
    weekday-only ``bdate_range``. Holidays only cost a wasted empty API call under
    the fallback, so the dependency is optional, not required.
    """
    try:
        import pandas_market_calendars as mcal
        sched = mcal.get_calendar("NYSE").schedule(start_date=start, end_date=end)
        return [d.strftime("%Y-%m-%d") for d in sched.index]
    except Exception:
        return [d.strftime("%Y-%m-%d") for d in pd.bdate_range(start=start, end=end)]


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Daily Polygon -> Parquet updater (#191)")
    ap.add_argument("--start", help="Backfill start date YYYY-MM-DD (override per-file last date)")
    ap.add_argument("--end", help="End date YYYY-MM-DD (default: last trading day)")
    ap.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help=f"Parquet dir (default {DEFAULT_DATA_DIR})")
    ap.add_argument("--dry-run", action="store_true", help="Plan only — no writes")
    ap.add_argument("--limit", type=int, default=0, help="Process only the first N files (testing)")
    ap.add_argument("--only", help="Comma-separated symbol filter, e.g. 'AAPL,MSFT,$VIX'")
    ap.add_argument("--no-adjust", action="store_true", help="Fetch unadjusted bars (default: split-adjusted)")
    args = ap.parse_args(argv)

    adjusted = not args.no_adjust
    api_key = get_api_key()
    session = requests.Session()

    data_dir = args.data_dir
    if not os.path.isdir(data_dir):
        logger.error("Data dir not found: %s (is the parquet_data submodule checked out?)", data_dir)
        return 1

    files = sorted(f for f in os.listdir(data_dir) if f.lower().endswith(".parquet"))
    if args.only:
        wanted = {s.strip() for s in args.only.split(",")}
        files = [f for f in files if classify_symbol(f)[1] in wanted]
    if args.limit:
        files = files[: args.limit]

    equities, indices, breadth = {}, {}, []
    for f in files:
        kind, base = classify_symbol(f)
        if kind == "breadth":
            breadth.append(base)
        elif kind == "index":
            indices[base] = os.path.join(data_dir, f)
        else:
            equities[base.upper()] = os.path.join(data_dir, f)

    logger.info("Universe: %d equities, %d indices, %d breadth (skipped).",
                len(equities), len(indices), len(breadth))

    end_date = args.end or last_trading_day(session, api_key)
    logger.info("Target end date: %s | adjusted=%s | dry_run=%s", end_date, adjusted, args.dry_run)

    # Per-file last dates (to append only genuinely new rows).
    eq_last: dict[str, pd.Timestamp | None] = {sym: read_last_date(p) for sym, p in equities.items()}

    # ── Equities via grouped endpoint (one call per trading day) ──────────────
    eq_updated = eq_skipped = 0
    if equities:
        if args.start:
            grouped_start = args.start
        else:
            valid = [d for d in eq_last.values() if d is not None]
            grouped_start = ((min(valid) + timedelta(days=1)).strftime("%Y-%m-%d")
                             if valid else SEAM_DATE)
        days = _business_days(grouped_start, end_date)
        logger.info("Equities: fetching %d grouped day(s) from %s to %s.", len(days), grouped_start, end_date)

        accum: dict[str, list[tuple[str, dict]]] = {sym: [] for sym in equities}
        for i, ds in enumerate(days, 1):
            hits = fetch_grouped_day(session, api_key, ds, adjusted)
            for sym in equities:
                bar = hits.get(sym)
                if bar is not None:
                    accum[sym].append((ds, bar))
            if i % 10 == 0 or i == len(days):
                logger.info("  grouped %d/%d days fetched.", i, len(days))

        for sym, path in equities.items():
            last = eq_last[sym]
            rows = accum[sym]
            if last is not None:
                rows = [(ds, b) for ds, b in rows if pd.Timestamp(ds, tz="UTC").normalize() > last]
            df = grouped_rows_to_df(rows)
            added = append_and_write(path, df, args.dry_run)
            if added:
                eq_updated += 1
            else:
                eq_skipped += 1
        logger.info("Equities done: %d updated, %d unchanged.", eq_updated, eq_skipped)

    # ── Indices via per-ticker aggregates ─────────────────────────────────────
    idx_updated = idx_skipped = idx_failed = 0
    for base, path in indices.items():
        poly_sym = normalize_ticker(base, "polygon")
        last = read_last_date(path)
        start = args.start or ((last + timedelta(days=1)).strftime("%Y-%m-%d") if last is not None else SEAM_DATE)
        if start > end_date:
            idx_skipped += 1
            continue
        rows = fetch_ticker_range(session, api_key, poly_sym, start, end_date, adjusted)
        if not rows:
            logger.warning("Index %s (%s): no bars from Polygon for %s..%s.", base, poly_sym, start, end_date)
            idx_failed += 1
            continue
        df = bars_to_df(rows)
        if last is not None:
            df = df[df.index > last]
        added = append_and_write(path, df, args.dry_run)
        idx_updated += 1 if added else 0
        idx_skipped += 0 if added else 1
        if _RATE_LIMIT_SLEEP:
            time.sleep(_RATE_LIMIT_SLEEP)
    if indices:
        logger.info("Indices done: %d updated, %d unchanged, %d failed.", idx_updated, idx_skipped, idx_failed)

    if breadth:
        logger.info("Breadth (#) frozen/skipped: %d files (Norgate-only, not on Polygon).", len(breadth))

    logger.info("%sComplete. Equities updated=%d, indices updated=%d.",
                "[DRY RUN] " if args.dry_run else "", eq_updated, idx_updated)
    return 0


if __name__ == "__main__":
    sys.exit(main())
