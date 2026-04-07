# services/parquet_service.py
"""
Local Parquet data provider.
Reads historical OHLCV data from Parquet files stored in a configured directory.
One file per symbol, named ``{SYMBOL}.parquet`` (case-insensitive lookup).

Expected Parquet schema:
    Index  : DatetimeIndex (named 'Datetime' or similar)
    Columns: Open, High, Low, Close, Volume — all numeric

Returned DataFrame:
    Index  : DatetimeIndex, UTC-aware, name='Datetime'
    Columns: ['Open', 'High', 'Low', 'Close', 'Volume']  — all numeric

Configuration key:
    config["parquet_data_dir"]  — path to the directory containing the Parquet files.
                                  Relative paths are resolved from the project root
                                  (the directory that contains config.py).
                                  Defaults to "parquet_data/data" (the data/ subdirectory
                                  inside the parquet_data git submodule).
"""

import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)

# Project root = parent of this services/ package
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CANONICAL_COLS = ["Open", "High", "Low", "Close", "Volume"]

# Characters illegal in Windows filenames (and generally problematic on any OS)
_ILLEGAL_FILENAME_CHARS = r'\/:*?"<>|'


def _sanitize_filename(symbol: str) -> str:
    """Replace characters that are illegal in Windows filenames with underscores."""
    for ch in _ILLEGAL_FILENAME_CHARS:
        symbol = symbol.replace(ch, "_")
    return symbol


def _resolve_dir(config: dict) -> str:
    """Return the absolute path to the parquet data directory."""
    raw = config.get("parquet_data_dir", "parquet_data/data")
    if os.path.isabs(raw):
        return raw
    return os.path.join(_PROJECT_ROOT, raw)


def _find_parquet(symbol: str, parquet_dir: str) -> str | None:
    """
    Find the Parquet file for *symbol* with case-insensitive lookup.
    Returns the full file path, or None if not found.
    """
    if not os.path.isdir(parquet_dir):
        logger.warning(f"Parquet data directory does not exist: {parquet_dir}")
        return None

    # Sanitize the symbol so I:VIX looks for I_VIX.parquet
    safe = _sanitize_filename(symbol)

    # Try exact match first, then case-insensitive
    for candidate in [f"{safe}.parquet", f"{safe.upper()}.parquet", f"{safe.lower()}.parquet"]:
        path = os.path.join(parquet_dir, candidate)
        if os.path.isfile(path):
            return path

    # Brute-force case-insensitive scan
    target = f"{safe.upper()}.parquet"
    for fname in os.listdir(parquet_dir):
        if fname.upper() == target:
            return os.path.join(parquet_dir, fname)

    return None


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure the DataFrame has the canonical column names
    [Open, High, Low, Close, Volume] regardless of source casing.
    """
    col_map = {}
    for col in df.columns:
        lower = col.strip().lower()
        if lower == "open":
            col_map[col] = "Open"
        elif lower == "high":
            col_map[col] = "High"
        elif lower == "low":
            col_map[col] = "Low"
        elif lower in ("close", "adj close", "adjusted close"):
            col_map[col] = "Close"
        elif lower == "volume":
            col_map[col] = "Volume"

    if col_map:
        df = df.rename(columns=col_map)

    # Keep only canonical columns that exist
    present = [c for c in _CANONICAL_COLS if c in df.columns]
    if len(present) < len(_CANONICAL_COLS):
        missing = set(_CANONICAL_COLS) - set(present)
        logger.warning(f"Parquet file missing columns: {missing}")
        return None

    return df[_CANONICAL_COLS]


def _to_utc_index(df: pd.DataFrame) -> pd.DataFrame | None:
    """
    Ensure the DataFrame index is a UTC-aware DatetimeIndex named 'Datetime'.
    """
    # If the index is already a DatetimeIndex, use it
    if isinstance(df.index, pd.DatetimeIndex):
        idx = df.index
    else:
        # Try to convert the index
        try:
            idx = pd.to_datetime(df.index)
        except Exception:
            logger.warning("Could not convert parquet index to DatetimeIndex.")
            return None

    # Make UTC-aware
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")

    df.index = idx
    df.index.name = "Datetime"
    return df


def get_price_data(symbol: str, start_date: str, end_date: str, config: dict):
    """
    Load OHLCV history for *symbol* from a local Parquet file.

    Parameters
    ----------
    symbol     : ticker string — looked up as ``{parquet_data_dir}/{SYMBOL}.parquet``
    start_date : ISO date string "YYYY-MM-DD" (inclusive filter)
    end_date   : ISO date string "YYYY-MM-DD" (inclusive filter)
    config     : CONFIG dict from config.py

    Returns
    -------
    pd.DataFrame with columns [Open, High, Low, Close, Volume] and a
    UTC DatetimeIndex named 'Datetime', or None on any error / no data.
    """
    parquet_dir = _resolve_dir(config)
    filepath = _find_parquet(symbol, parquet_dir)

    if filepath is None:
        logger.warning(
            f"Parquet file not found for '{symbol}'. "
            f"Looked in: {parquet_dir}"
        )
        return None

    try:
        df = pd.read_parquet(filepath)
    except Exception as e:
        logger.error(f"Failed to read parquet file '{filepath}': {e}")
        return None

    logger.debug(f"Loaded {len(df)} rows from {filepath}")

    # Normalise columns
    df = _normalise_columns(df)
    if df is None:
        return None

    # Normalise index to UTC DatetimeIndex
    df = _to_utc_index(df)
    if df is None:
        return None

    # Ensure numeric types
    for col in _CANONICAL_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Filter by date range
    start = pd.Timestamp(start_date, tz="UTC")
    end = pd.Timestamp(end_date, tz="UTC")
    df = df.loc[(df.index >= start) & (df.index <= end)]

    if df.empty:
        logger.warning(
            f"No data for '{symbol}' between {start_date} and {end_date} "
            f"in {filepath}."
        )
        return None

    # Drop any rows with NaN in OHLC
    df = df.dropna(subset=["Open", "High", "Low", "Close"])

    logger.debug(
        f"  {symbol}: {len(df)} bars, "
        f"{df.index[0].strftime('%Y-%m-%d')} → {df.index[-1].strftime('%Y-%m-%d')}"
    )

    return df