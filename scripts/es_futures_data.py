"""
ES futures 1-minute data loader (Polygon futures API) + continuous front-month stitching.

Polygon's futures aggregate history begins 2024-09-17 (probed 2026-09-17). Contract
tickers are ambiguous across decades (ESM4 may resolve to Jun-2024 or Jun-2034), so the
quarterly chain is enumerated explicitly and each contract's true span is read from the
data itself rather than assumed.

Roll rule: for each session, the active contract is the one with the highest volume on the
PREVIOUS session. Using prior-day volume keeps the roll decision look-ahead-free -- a real
trader rolls based on yesterday's tape, not today's.

Usage as a module:
    from es_futures_data import load_es_1min
    df = load_es_1min()   # tz-aware America/New_York index, RTH + full session
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE = "https://api.polygon.io/futures/v1"
CACHE_DIR = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "es_minute_cache"
NY = "America/New_York"

# Quarterly ES chain covering 2024-09-17 -> present. Order matters (chronological).
ES_CHAIN = ["ESZ4", "ESH5", "ESM5", "ESU5", "ESZ5", "ESH6", "ESM6", "ESU6", "ESZ6"]

# Contract specs
ES_SPEC = {"point_value": 50.0, "tick_size": 0.25, "tick_value": 12.50, "name": "ES"}
MES_SPEC = {"point_value": 5.0, "tick_size": 0.25, "tick_value": 1.25, "name": "MES"}


def _api_key() -> str:
    key = os.getenv("POLYGON_API_KEY")
    if not key:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[1] / ".env")
        load_dotenv("/Users/zach/Desktop/github/july-backtester/.env")
        key = os.getenv("POLYGON_API_KEY")
    if not key:
        raise RuntimeError("POLYGON_API_KEY not found in env or .env")
    return key


def fetch_contract_1min(ticker: str, *, force: bool = False, verbose: bool = True) -> pd.DataFrame:
    """Fetch every 1-min bar Polygon holds for one contract. Cached to parquet."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{ticker}_1min.parquet"
    if cache.exists() and not force:
        return pd.read_parquet(cache)

    key = _api_key()
    session = requests.Session()
    rows: list[dict] = []
    url = f"{BASE}/aggs/{ticker}"
    params = {
        "resolution": "1min",
        "limit": 50000,
        "sort": "window_start",
        "order": "asc",
        "apiKey": key,
    }
    page = 0
    while True:
        for attempt in range(5):
            r = session.get(url, params=params, timeout=120)
            if r.status_code == 200:
                break
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"{ticker}: HTTP {r.status_code} {r.text[:200]}")
        else:
            raise RuntimeError(f"{ticker}: exhausted retries")

        payload = r.json()
        batch = payload.get("results") or []
        rows.extend(batch)
        page += 1
        if verbose:
            print(f"    {ticker} page {page}: +{len(batch):,} (total {len(rows):,})", flush=True)
        nxt = payload.get("next_url")
        if not nxt or not batch:
            break
        url, params = nxt, {"apiKey": key}

    if not rows:
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume", "transactions"])
        df.to_parquet(cache)
        return df

    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["window_start"], unit="ns", utc=True)
    df = df.set_index("ts").sort_index()
    keep = ["open", "high", "low", "close", "volume", "transactions", "session_end_date"]
    df = df[[c for c in keep if c in df.columns]]
    df = df[~df.index.duplicated(keep="first")]
    df.to_parquet(cache)
    return df


def load_es_1min(*, chain: list[str] | None = None, force: bool = False,
                 verbose: bool = True) -> pd.DataFrame:
    """Continuous front-month ES 1-min series, tz-aware America/New_York.

    Returns columns: open, high, low, close, volume, contract.
    """
    chain = chain or ES_CHAIN
    stitched_cache = CACHE_DIR / "ES_continuous_1min.parquet"
    if stitched_cache.exists() and not force:
        return pd.read_parquet(stitched_cache)

    frames: dict[str, pd.DataFrame] = {}
    for ticker in chain:
        if verbose:
            print(f"  fetching {ticker} ...", flush=True)
        df = fetch_contract_1min(ticker, force=force, verbose=verbose)
        if len(df):
            frames[ticker] = df

    if not frames:
        raise RuntimeError("no ES contract data returned")

    # Daily volume per contract -> prior-day volume ranking -> per-session active contract
    daily_vol = {}
    for ticker, df in frames.items():
        local = df.tz_convert(NY)
        daily_vol[ticker] = local.groupby(local.index.date)["volume"].sum()
    vol = pd.DataFrame(daily_vol).sort_index()
    prior = vol.shift(1)
    # First session has no prior day: fall back to same-day volume so it is not dropped.
    prior.iloc[0] = vol.iloc[0]
    active = prior.idxmax(axis=1)
    active = active.dropna()

    out = []
    for ticker, df in frames.items():
        local = df.tz_convert(NY).copy()
        sess = pd.Series(local.index.date, index=local.index)
        wanted = sess.map(active) == ticker
        piece = local[wanted.fillna(False).values].copy()
        if len(piece):
            piece["contract"] = ticker
            out.append(piece)

    stitched = pd.concat(out).sort_index()
    stitched = stitched[~stitched.index.duplicated(keep="first")]
    stitched = stitched[["open", "high", "low", "close", "volume", "contract"]]
    stitched.to_parquet(stitched_cache)
    if verbose:
        sessions = len(set(stitched.index.date))
        print(f"  stitched: {len(stitched):,} bars, {sessions} sessions, "
              f"{stitched.index.min()} -> {stitched.index.max()}", flush=True)
        print("  roll map:", active.value_counts().sort_index().to_dict(), flush=True)
    return stitched


if __name__ == "__main__":
    df = load_es_1min(force="--force" in sys.argv)
    print(df.head())
    print(df.tail())
    print(df.groupby("contract").size())
