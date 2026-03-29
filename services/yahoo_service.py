# services/yahoo_service.py
"""
Yahoo Finance data provider via yfinance.

Fetcher signature matches the rest of the service layer:
    get_price_data(symbol, start_date, end_date, config) -> pd.DataFrame | None

Returned DataFrame:
    Index  : DatetimeIndex, UTC-aware, name='Datetime'
    Columns: ['Open', 'High', 'Low', 'Close', 'Volume']  — all numeric
"""

import logging

import pandas as pd

from helpers.ticker_normalizer import normalize_ticker

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Timeframe mapping
# ---------------------------------------------------------------------------
# Maps config["timeframe"] codes to Yahoo Finance interval strings.
# When timeframe_multiplier != 1 we compose dynamically for H and MIN.
_TF_BASE = {
    "D":   "1d",
    "W":   "1wk",
    "M":   "1mo",
    "H":   "1h",
    "MIN": "m",   # prefix with multiplier: "1m", "5m", "15m", etc.
}


def _build_interval(config: dict) -> str:
    """
    Return the yfinance ``interval`` string for the given config.

    Examples
    --------
    {"timeframe": "D"}                          -> "1d"
    {"timeframe": "H", "timeframe_multiplier": 4} -> "4h"
    {"timeframe": "MIN", "timeframe_multiplier": 5} -> "5m"
    """
    timeframe = config.get("timeframe", "D").upper()
    multiplier = int(config.get("timeframe_multiplier", 1))

    if timeframe not in _TF_BASE:
        raise ValueError(
            f"Unsupported timeframe '{timeframe}' for Yahoo Finance. "
            f"Must be one of: {list(_TF_BASE.keys())}"
        )

    if timeframe == "MIN":
        return f"{multiplier}m"

    if timeframe == "H":
        return f"{multiplier}h"

    # D / W / M — multiplier >1 is not natively supported by yfinance;
    # log a warning and fall back to the base interval.
    if multiplier != 1:
        logger.warning(
            f"Yahoo Finance does not support multiplier={multiplier} for "
            f"timeframe='{timeframe}'. Using base interval '{_TF_BASE[timeframe]}'."
        )

    return _TF_BASE[timeframe]


def get_price_data(symbol: str, start_date: str, end_date: str, config: dict):
    """
    Fetch OHLCV history from Yahoo Finance for *symbol* over [start_date, end_date].

    Parameters
    ----------
    symbol     : ticker string (e.g. "AAPL")
    start_date : ISO date string "YYYY-MM-DD"
    end_date   : ISO date string "YYYY-MM-DD"
    config     : CONFIG dict from config.py

    Returns
    -------
    pd.DataFrame with columns [Open, High, Low, Close, Volume] and a
    UTC DatetimeIndex named 'Datetime', or None on any error / no data.
    """
    try:
        import yfinance as yf
    except ImportError as exc:
        raise ImportError(
            "yfinance is not installed. Run: pip install yfinance"
        ) from exc

    interval = _build_interval(config)
    auto_adjust = config.get("price_adjustment", "total_return") == "total_return"

    # Normalise the ticker using provider-agnostic normalizer (e.g., "I:VIX" → "^VIX")
    yahoo_symbol = normalize_ticker(symbol, "yahoo")

    try:
        ticker = yf.Ticker(yahoo_symbol)
        df = ticker.history(
            start=start_date,
            end=end_date,
            interval=interval,
            auto_adjust=auto_adjust,
            actions=False,          # drop Dividends / Stock Splits columns
        )
    except Exception as exc:
        logger.error(f"Yahoo Finance ERROR fetching '{symbol}' (as '{yahoo_symbol}'): {exc}")
        return None

    if df is None or df.empty:
        logger.debug(
            f"Yahoo Finance returned no data for '{symbol}' (as '{yahoo_symbol}') "
            f"[{start_date} → {end_date}]."
        )
        return None

    # Normalise column names (yfinance may return Title Case or lower case)
    col_map = {c: c.title() for c in df.columns}
    # "Adj Close" → "Close" (when auto_adjust=False)
    col_map.update({c: "Close" for c in df.columns if c.lower() in ("adj close", "adjusted close")})
    df = df.rename(columns=col_map)

    # Keep only the canonical OHLCV columns that are present
    canonical = ["Open", "High", "Low", "Close", "Volume"]
    available = [c for c in canonical if c in df.columns]
    df = df[available].copy()

    # Normalise index → UTC DatetimeIndex named 'Datetime'
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    df.index.name = "Datetime"

    return df
