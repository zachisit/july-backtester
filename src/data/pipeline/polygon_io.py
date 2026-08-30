"""Task 3 — Polygon raw data acquisition (immutable, idempotent).

Pulls and stores VERBATIM:
  * grouped-daily bars (adjusted=false)  -> polygon_raw/YYYY-MM-DD.json
  * splits    (>= PATCH_START)           -> polygon_raw/corporate_actions/splits.json
  * dividends (>= PATCH_START)           -> polygon_raw/corporate_actions/dividends.json

Raw is never mutated; re-pulling a date overwrites that one file (idempotent).
Trading days are discovered empirically: a date whose grouped-daily response has
results is a trading day; weekends/holidays come back empty and are skipped.
"""
import os
import json
import time

import requests
import urllib3
import pandas as pd

from . import paths

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_SESSION = requests.Session()
_SESSION.verify = False
_MIN_INTERVAL = float(os.environ.get("POLYGON_MIN_REQUEST_INTERVAL_SEC", "0.20"))
_last_call = [0.0]


def _throttle():
    dt = time.time() - _last_call[0]
    if dt < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - dt)
    _last_call[0] = time.time()


def _get(url, params=None, max_retries=5):
    params = dict(params or {})
    params.setdefault("apiKey", paths.POLYGON_API_KEY)
    for attempt in range(max_retries):
        _throttle()
        r = _SESSION.get(url, params=params, timeout=60)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Polygon GET failed after {max_retries} retries: {url}")


# ----------------------------------------------------------------- grouped ---
def _grouped_path(date_str):
    return os.path.join(paths.POLYGON_RAW, f"{date_str}.json")


def pull_grouped_daily(date_str, force=False):
    """Pull one date's grouped-daily (adjusted=false). Returns the parsed dict.

    Idempotent: if the file exists and not force, load from disk (no API call).
    A non-trading day returns a dict with empty/absent results and is still
    cached so we don't re-hit the API for it.
    """
    path = _grouped_path(date_str)
    if os.path.exists(path) and not force:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    url = f"{paths.POLYGON_BASE}/v2/aggs/grouped/locale/us/market/stocks/{date_str}"
    data = _get(url, {"adjusted": "false"})
    paths.ensure_dirs()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return data


def is_trading_day(data):
    return bool(data.get("results"))


def pull_range(start, end, force_dates=None, logger=None):
    """Pull grouped-daily for every calendar date in [start, end].

    force_dates: iterable of 'YYYY-MM-DD' to re-pull even if cached (trailing window).
    Returns the sorted list of trading-day strings that have data.
    """
    force_dates = set(force_dates or [])
    start = pd.Timestamp(start)
    end = pd.Timestamp(end)
    trading_days = []
    for d in pd.date_range(start, end, freq="D"):
        ds = d.strftime("%Y-%m-%d")
        if d.weekday() >= 5:           # skip Sat/Sun without an API call
            continue
        data = pull_grouped_daily(ds, force=(ds in force_dates))
        n = len(data.get("results", []) or [])
        if n:
            trading_days.append(ds)
        if logger:
            logger.info(f"grouped {ds}: {n} symbols{' (forced)' if ds in force_dates else ''}")
    return sorted(trading_days)


# ------------------------------------------------------------- corp actions ---
def _ca_dir():
    d = os.path.join(paths.POLYGON_RAW, "corporate_actions")
    os.makedirs(d, exist_ok=True)
    return d


def _paginate(url, params):
    rows = []
    data = _get(url, params)
    rows.extend(data.get("results", []) or [])
    nxt = data.get("next_url")
    while nxt:
        data = _get(nxt, {})
        rows.extend(data.get("results", []) or [])
        nxt = data.get("next_url")
    return rows


def pull_splits(since=None, logger=None):
    """All splits with execution_date >= since (default PATCH_START)."""
    since = (since or paths.PATCH_START)
    since_str = pd.Timestamp(since).strftime("%Y-%m-%d")
    rows = _paginate(f"{paths.POLYGON_BASE}/v3/reference/splits",
                     {"execution_date.gte": since_str, "limit": 1000})
    with open(os.path.join(_ca_dir(), "splits.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f)
    if logger:
        logger.info(f"splits since {since_str}: {len(rows)}")
    return rows


def pull_dividends(since=None, logger=None):
    """All dividends with ex_dividend_date >= since (default PATCH_START)."""
    since = (since or paths.PATCH_START)
    since_str = pd.Timestamp(since).strftime("%Y-%m-%d")
    rows = _paginate(f"{paths.POLYGON_BASE}/v3/reference/dividends",
                     {"ex_dividend_date.gte": since_str, "limit": 1000})
    with open(os.path.join(_ca_dir(), "dividends.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f)
    if logger:
        logger.info(f"dividends since {since_str}: {len(rows)}")
    return rows


def pull_index_daily(index_sym, start, end, force=False):
    """Fetch a Polygon index daily series (I:<sym>), adjusted=false.

    Indices have no splits/dividends, so the patch factor is 1.0. Cached to
    polygon_raw/indices/<sym>.json for provenance. Returns a DataFrame
    (date index) or None.
    """
    sym = index_sym.replace("I:", "").replace("$", "").upper()
    idir = os.path.join(paths.POLYGON_RAW, "indices")
    os.makedirs(idir, exist_ok=True)
    cache = os.path.join(idir, f"{sym}.json")
    if os.path.exists(cache) and not force:
        with open(cache, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        s = pd.Timestamp(start).strftime("%Y-%m-%d")
        e = pd.Timestamp(end).strftime("%Y-%m-%d")
        url = f"{paths.POLYGON_BASE}/v2/aggs/ticker/I:{sym}/range/1/day/{s}/{e}"
        data = _get(url, {"adjusted": "false", "sort": "asc", "limit": 50000})
        with open(cache, "w", encoding="utf-8") as f:
            json.dump(data, f)
    res = data.get("results") or []
    if not res:
        return None
    df = pd.DataFrame(res)
    df["date"] = pd.to_datetime(df["t"], unit="ms").dt.normalize()
    df = df.set_index("date")
    cols = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
    df = df.rename(columns=cols)
    for c in ("open", "high", "low", "close"):
        if c not in df.columns:
            df[c] = df.get("close")
    if "volume" not in df.columns:
        df["volume"] = 0.0
    return df[["open", "high", "low", "close", "volume"]]


def load_raw_grouped(date_str):
    path = _grouped_path(date_str)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def cached_trading_days():
    """Trading-day strings already cached on disk (have results)."""
    out = []
    for fn in os.listdir(paths.POLYGON_RAW):
        if fn.endswith(".json") and fn[0].isdigit():
            ds = fn[:-5]
            data = load_raw_grouped(ds)
            if data and is_trading_day(data):
                out.append(ds)
    return sorted(out)
