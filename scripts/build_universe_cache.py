"""
Build the rule-based universe cache from the Norgate parquet corpus (issue #70).

Rule-based universe resolution asks, for a given date: which securities were
trading, above a price floor, and liquid enough? Answering that from the raw
corpus would mean opening ~36.7k parquet files on every call. This script does
that pass ONCE and writes a compact cache keyed by (security, month).

Output: one parquet at ``universe_cache/universe_metrics.parquet`` with

    security       str    file stem, e.g. "AAPL" or "BSC-200805"
    ticker         str    base ticker with any -YYYYMM suffix stripped
    month          str    "YYYY-MM"
    last_close     float  final close in that month
    adv20          float  20-bar mean dollar volume as of the month's last bar
    bars_to_date   int    cumulative bars for this security up to month end
    bars_in_month  int    bars observed in the month

Two things this handles that produce silently wrong answers otherwise:

  * Norgate names delisted securities TICKER-YYYYMM, so one ticker maps to
    several distinct securities over time (WB is Wachovia until 2008 and Weibo
    from 2014). Rows are keyed by SECURITY, and `ticker` is carried alongside
    so resolution can disambiguate by date rather than by string.
  * `Datetime` is NOT column 0 in these files (`Open` is). Anything reading
    row-group statistics must locate the column by name -- reading column 0
    yields float stats that coerce to 1970 and look like real data.

Data quality: bars with a non-positive or non-finite close or a negative volume
are dropped before aggregation, and the count is reported per security. This
matters here specifically -- a threshold rule reads price and volume directly,
where a membership-list lookup never touches them. Known scattered-corrupt-bar
tickers (GS/WFC/BAC/JPM) are summarised explicitly at the end.

Usage:
    python scripts/build_universe_cache.py
    python scripts/build_universe_cache.py --corpus /path/to/parquet_data/data --out cache.parquet
    python scripts/build_universe_cache.py --limit 500     # smoke test
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from helpers.rule_based_universe import normalise_universe_ticker  # noqa: E402

DEFAULT_CORPUS = os.path.join(ROOT, "parquet_data", "data")
DEFAULT_OUT = os.path.join(ROOT, "universe_cache", "universe_metrics.parquet")

ADV_WINDOW = 20
WATCH = ("GS", "WFC", "BAC", "JPM")  # known scattered-corrupt bars — reported explicitly


def _security_and_ticker(path: str) -> tuple[str, str]:
    stem = os.path.basename(path)[:-8]
    base = re.sub(r"-\d{6}$", "", stem)
    # Dot->hyphen share-class normalisation (BRK.B -> BRK-B) and any explicit
    # rename alias (TFCFA -> FOXA) so the cache's `ticker` column matches what
    # PIT rosters and price providers use -- see rule_based_universe.py's
    # RULE_TICKER_ALIASES for why this can't be pure punctuation normalisation.
    return stem, normalise_universe_ticker(base)


def _monthly_metrics(df: pd.DataFrame) -> pd.DataFrame | None:
    """Collapse a daily OHLCV frame to one row per month."""
    if df.empty:
        return None
    close = df["Close"].astype(float)
    vol = df["Volume"].astype(float)
    dollar = close * vol
    adv = dollar.rolling(ADV_WINDOW, min_periods=1).mean()
    bars_to_date = pd.Series(np.arange(1, len(df) + 1), index=df.index)

    month = df.index.to_period("M").astype(str)
    grp = pd.DataFrame(
        {"month": month, "close": close.to_numpy(), "adv": adv.to_numpy(),
         "btd": bars_to_date.to_numpy()},
        index=df.index,
    ).groupby("month", sort=True)

    out = pd.DataFrame({
        "last_close": grp["close"].last(),
        "adv20": grp["adv"].last(),
        "bars_to_date": grp["btd"].last().astype("int32"),
        "bars_in_month": grp.size().astype("int16"),
    }).reset_index()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, help="process only the first N files (smoke test)")
    args = ap.parse_args()

    if not os.path.isdir(args.corpus):
        print(f"ERROR: corpus not found: {args.corpus}\n"
              f"Initialise the submodule: git submodule update --init parquet_data",
              file=sys.stderr)
        return 2

    paths = sorted(glob.glob(os.path.join(args.corpus, "*.parquet")))
    if args.limit:
        paths = paths[: args.limit]
    print(f"corpus : {args.corpus}\nfiles  : {len(paths)}\n")

    frames: list[pd.DataFrame] = []
    dropped_total = 0
    skipped_index = 0
    dropped_by_watch: dict[str, int] = {t: 0 for t in WATCH}
    failed: list[str] = []
    t0 = time.time()

    for i, path in enumerate(paths, 1):
        if i % 2500 == 0:
            print(f"  {i}/{len(paths)}  ({time.time()-t0:.0f}s)")
        security, ticker = _security_and_ticker(path)
        # Norgate's index/breadth series are prefixed '#' or '$' (exactly the
        # ~1,615 the corpus README counts as "US Indices"). They are not
        # tradeable and many legitimately carry non-positive closes -- #AMEXAD
        # is an advance-decline line, 4,682 of its 4,775 closes are <= 0.
        # Excluded here rather than filtered as "bad bars", which would report
        # ~33% corruption that does not exist.
        if not security[:1].isalnum():
            skipped_index += 1
            continue
        try:
            df = pd.read_parquet(path, columns=["Close", "Volume"])
        except Exception:
            failed.append(security)
            continue
        if df.empty:
            continue
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df = df.sort_index()

        n0 = len(df)
        close = pd.to_numeric(df["Close"], errors="coerce")
        vol = pd.to_numeric(df["Volume"], errors="coerce")
        ok = np.isfinite(close) & (close > 0) & np.isfinite(vol) & (vol >= 0)
        df = df[ok]
        dropped = n0 - len(df)
        dropped_total += dropped
        if ticker in dropped_by_watch:
            dropped_by_watch[ticker] += dropped
        if df.empty:
            continue

        m = _monthly_metrics(df)
        if m is None or m.empty:
            continue
        m.insert(0, "security", security)
        m.insert(1, "ticker", ticker)
        frames.append(m)

    if not frames:
        print("ERROR: nothing built", file=sys.stderr)
        return 1

    cache = pd.concat(frames, ignore_index=True)
    cache = cache.sort_values(["security", "month"]).reset_index(drop=True)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    cache.to_parquet(args.out, index=False)

    print(f"\nsecurities : {cache['security'].nunique()}")
    print(f"base tickers: {cache['ticker'].nunique()}")
    print(f"rows        : {len(cache)}")
    print(f"months      : {cache['month'].min()} .. {cache['month'].max()}")
    print(f"elapsed     : {time.time()-t0:.0f}s")
    print(f"\nwrote {args.out}")

    print(f"\nDATA QUALITY\n  non-tradeable index/breadth series skipped (# and $ prefixes): {skipped_index}")
    print(f"  bad bars dropped (non-finite/non-positive close, negative volume): {dropped_total}")
    for t, n in dropped_by_watch.items():
        print(f"    {t}: {n}")
    if failed:
        print(f"  unreadable files: {len(failed)}  e.g. {failed[:5]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
