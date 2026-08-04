"""services/futures_service.py

Polygon.io **futures** market data — the dedicated `/futures/v1` REST API, which is
structurally separate from the equities/index aggregates path used by
``services/polygon_service.py``.

Modeled on SignalDeck's ``futures_polygon_service.py`` (verified working on the
current Polygon plan; only ``/futures/v1/snapshot`` is 403-gated — we never call it).

Key gotchas replicated here:
  - ``window_start`` is a NANOSECOND epoch (19 digits) — parse with unit="ns".
  - Prefer ``settlement_price``; treat ``<= 0`` as absent (unsettled in-progress
    bar) and fall back to ``close``.
  - ``next_url`` cursors DROP the apiKey — re-attach it on every follow.
  - Pages can return duplicate / out-of-order bars — dedupe + sort before use.

Tickers are individual contract months (``PRODUCT + MONTH_CODE + YEAR_DIGIT``,
e.g. ``ESM6``). Continuous back-adjusted series are built on top of per-contract
data in ``helpers/continuous_contract.py``.

Fetcher signature matches the other providers:
    get_price_data(symbol, start_date, end_date, config) -> pd.DataFrame | None
with columns Open, High, Low, Close, Volume and a tz-aware Datetime index.
"""

from __future__ import annotations

import logging
import os

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_BASE = "https://api.polygon.io/futures/v1"
_LIMIT = 1000

# Polygon futures resolution unit per config timeframe. The multiplier is applied
# dynamically (e.g. MIN x5 -> "5min", H x4 -> "4hour") so intraday strategies on
# 5m/15m/45m bars fetch natively instead of pulling 1-min and resampling locally.
_RESOLUTION_UNIT = {"MIN": "min", "H": "hour"}


def _api_key() -> str:
    key = os.environ.get("POLYGON_API_KEY")
    if not key:
        raise ValueError("POLYGON_API_KEY is not set. Add it to your .env file or environment.")
    return key


def _resolution(config: dict) -> str:
    tf = str(config.get("timeframe", "D")).upper()
    mult = max(1, int(config.get("timeframe_multiplier", 1)))
    # Daily bars map to Polygon's session resolution (multiplier ignored).
    if tf == "D":
        return "1session"
    unit = _RESOLUTION_UNIT.get(tf)
    if unit is None:
        logger.warning("No futures resolution for timeframe '%s'; defaulting to '1session'.", tf)
        return "1session"
    return f"{mult}{unit}"


def _paginate(url: str, params: dict) -> list[dict]:
    """Follow Polygon's ``next_url`` cursor, re-attaching the apiKey each hop."""
    key = params.get("apiKey")
    rows: list[dict] = []
    next_url = url
    next_params = dict(params)
    pages = 0
    while next_url:
        pages += 1
        resp = requests.get(next_url, params=next_params)
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "ERROR":
            logger.warning("Polygon futures API error: %s", data.get("error"))
            break
        rows.extend(data.get("results", []) or [])
        next_url = data.get("next_url")
        # GOTCHA: next_url drops the apiKey — must re-attach on every cursor follow.
        next_params = {"apiKey": key} if next_url else next_params
    logger.debug("Fetched %d futures bars in %d page(s).", len(rows), pages)
    return rows


def _bars_to_frame(rows: list[dict]) -> pd.DataFrame | None:
    if not rows:
        return None
    df = pd.DataFrame(rows)
    if "window_start" not in df.columns:
        return None
    # GOTCHA: window_start is a NANOSECOND epoch.
    df["Datetime"] = pd.to_datetime(df["window_start"], unit="ns", utc=True)

    # GOTCHA: prefer settlement_price; treat <= 0 as absent and fall back to close.
    if "settlement_price" in df.columns:
        settle = pd.to_numeric(df["settlement_price"], errors="coerce")
        close = pd.to_numeric(df.get("close"), errors="coerce")
        df["Close"] = settle.where(settle > 0, close)
    else:
        df["Close"] = pd.to_numeric(df.get("close"), errors="coerce")

    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low", "volume": "Volume"})
    for col in ("Open", "High", "Low", "Volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
    df = df.set_index("Datetime")[cols]
    # GOTCHA: pages can return dupes / out-of-order bars.
    df = df.loc[~df.index.duplicated(keep="last")].sort_index()
    return df


def get_price_data(symbol, start_date, end_date, config):
    """Fetch OHLCV bars for a single futures contract month from Polygon.

    ``symbol`` is a contract-month ticker (e.g. ``"ESM6"``). Returns a DataFrame
    with Open/High/Low/Close/Volume and a tz-aware DatetimeIndex, or ``None``.
    """
    url = f"{_BASE}/aggs/{symbol}"
    params = {
        "apiKey": _api_key(),
        "resolution": _resolution(config),
        "window_start.gte": str(start_date),
        "window_start.lte": str(end_date),
        "order": "asc",
        "limit": _LIMIT,
    }
    try:
        rows = _paginate(url, params)
    except requests.exceptions.RequestException as e:
        logger.error("Polygon futures HTTP error for '%s': %s", symbol, e)
        return None

    df = _bars_to_frame(rows)
    if df is None or df.empty:
        logger.debug("No futures data returned for '%s'.", symbol)
        return None

    # Normalize daily bars to midnight, matching the other providers.
    if str(config.get("timeframe", "D")).upper() == "D":
        df.index = df.index.normalize()
    return df
