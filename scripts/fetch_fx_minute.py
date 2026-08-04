"""
Fetch and cache 1-minute Polygon FX bars.

Polygon serves 1-min forex aggregates back to 2010 on the current plan — much
deeper history than the equity intraday endpoints allow — which makes minute-
resolution FX research practical without a paid tick vendor.

Bars are written as one parquet per (pair, year) under --cache-dir, so re-runs
cost nothing and a partial fetch can be resumed by re-running the same command.
Output is OHLCV with a tz-aware America/New_York DatetimeIndex, matching the
convention used elsewhere in this repo.

    # everything: 7 majors, 6 crosses, XAUUSD
    python scripts/fetch_fx_minute.py --cache-dir fx_minute_cache

    # a subset / shorter window
    python scripts/fetch_fx_minute.py --pairs C:EURUSD,C:GBPUSD --start 2020 --end 2026

Then load with load_pair(), or point your own code at the cache directory:

    from scripts.fetch_fx_minute import load_pair
    df = load_pair("C:EURUSD", 2020, 2026, "fx_minute_cache")

Note: Polygon coverage is not uniform across symbols — C:XAUUSD, for example,
returns no 1-min data for 2012 and only partial 2011. Check the printed bar
counts per year before relying on a specific window.
"""

import argparse
import os
import sys
import time

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from helpers.aws_utils import get_secret  # noqa: E402

ET = "America/New_York"
BASE = "https://api.polygon.io"

# Majors, then the liquid crosses, then gold spot (a metal, kept separate in
# reporting but quoted and traded like a pair).
MAJORS = ["C:EURUSD", "C:GBPUSD", "C:USDJPY", "C:USDCHF",
          "C:AUDUSD", "C:USDCAD", "C:NZDUSD"]
CROSSES = ["C:EURGBP", "C:EURJPY", "C:GBPJPY", "C:AUDJPY", "C:EURAUD", "C:CHFJPY"]
METALS = ["C:XAUUSD"]
ALL_PAIRS = MAJORS + CROSSES + METALS

# Pip size per pair — the unit the cost model is expressed in.
def pip_size(pair: str) -> float:
    sym = pair.replace("C:", "")
    if sym.startswith("XAU"):
        return 0.10
    return 0.01 if sym.endswith("JPY") else 0.0001


def fetch_year(pair: str, year: int, api_key: str, session: requests.Session) -> pd.DataFrame:
    """Pull one calendar year of 1-min bars, following Polygon's pagination."""
    url = (f"{BASE}/v2/aggs/ticker/{pair}/range/1/minute/"
           f"{year}-01-01/{year}-12-31")
    params = {"apiKey": api_key, "limit": 50000, "sort": "asc", "adjusted": "true"}
    frames, pages = [], 0

    while url:
        r = None
        for attempt in range(5):
            try:
                r = session.get(url, params=params, timeout=60)
            except requests.RequestException:
                time.sleep(2 * (attempt + 1))
                continue
            if r.status_code == 429 or 500 <= r.status_code < 600:
                time.sleep(5 * (attempt + 1))
                continue
            break
        else:
            if r is not None and 500 <= r.status_code < 600:
                raise RuntimeError(f"{pair} {year}: HTTP {r.status_code} {r.text[:200]}")
            raise RuntimeError(f"{pair} {year}: repeated request failures")

        if r.status_code != 200:
            raise RuntimeError(f"{pair} {year}: HTTP {r.status_code} {r.text[:200]}")

        j = r.json()
        res = j.get("results") or []
        if res:
            frames.append(pd.DataFrame(res))
        pages += 1
        url = j.get("next_url")
        params = {"apiKey": api_key}   # next_url already carries the query
        if not url:
            break

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low",
                            "c": "close", "v": "volume", "t": "ts"})
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts").tz_convert(ET).sort_index()
    df = df[~df.index.duplicated(keep="first")]
    return df[["open", "high", "low", "close", "volume"]]


def load_pair(pair: str, start_year: int, end_year: int, cache_dir: str,
              api_key: str = None) -> pd.DataFrame:
    """Load a pair across years, fetching and caching anything missing."""
    os.makedirs(cache_dir, exist_ok=True)
    session = requests.Session()
    frames = []
    for year in range(start_year, end_year + 1):
        path = os.path.join(cache_dir, f"{pair.replace(':', '_')}_{year}.parquet")
        if os.path.exists(path):
            frames.append(pd.read_parquet(path))
            continue
        if api_key is None:
            api_key = get_secret("POLYGON_API_KEY")
        df = fetch_year(pair, year, api_key, session)
        if df.empty:
            print(f"  {pair} {year}: no data", flush=True)
            continue
        df.to_parquet(path)
        print(f"  {pair} {year}: {len(df):,} bars", flush=True)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames).sort_index()
    return out[~out.index.duplicated(keep="first")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", default=",".join(ALL_PAIRS))
    ap.add_argument("--start", type=int, default=2010)
    ap.add_argument("--end", type=int, default=2026)
    ap.add_argument("--cache-dir", default="fx_minute_cache")
    args = ap.parse_args()

    api_key = get_secret("POLYGON_API_KEY")
    if not api_key:
        raise SystemExit("POLYGON_API_KEY not set")

    for pair in args.pairs.split(","):
        t0 = time.time()
        df = load_pair(pair, args.start, args.end, args.cache_dir, api_key)
        if df.empty:
            print(f"{pair}: EMPTY")
            continue
        print(f"{pair}: {len(df):,} bars  {df.index.min().date()} -> "
              f"{df.index.max().date()}  ({time.time() - t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
