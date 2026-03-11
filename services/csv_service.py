# services/csv_service.py
"""
Local CSV data provider.

Reads historical OHLCV data from CSV files stored in a configured directory.
One file per symbol, named ``{SYMBOL}.csv`` (case-insensitive lookup).

Expected CSV schema (column names are case-insensitive):
    Date | Datetime | Timestamp  — any recognisable date/datetime string
    Open, High, Low, Close (or "Adj Close"), Volume

The date column may be either a named column or the CSV index.

Returned DataFrame:
    Index  : DatetimeIndex, UTC-aware, name='Datetime'
    Columns: ['Open', 'High', 'Low', 'Close', 'Volume']  — all numeric

Configuration key:
    config["csv_data_dir"]  — path to the directory containing the CSVs.
                              Relative paths are resolved from the project root
                              (the directory that contains config.py).
                              Defaults to "csv_data".
"""

import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)

# Project root = parent of this services/ package
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CANONICAL_COLS = ["Open", "High", "Low", "Close", "Volume"]

# Column name aliases recognised as the date/index column
_DATE_ALIASES = {"date", "datetime", "time", "timestamp"}

# Column name aliases mapped to canonical names
_COL_ALIASES: dict[str, str] = {
    "open":             "Open",
    "high":             "High",
    "low":              "Low",
    "close":            "Close",
    "close/last":       "Close",
    "adj close":        "Close",
    "adjusted close":   "Close",
    "volume":           "Volume",
}


# Characters illegal in Windows filenames (and generally problematic on any OS)
_ILLEGAL_FILENAME_CHARS = r'\/:*?"<>|'


def _sanitize_filename(symbol: str) -> str:
    """
    Replace characters that are illegal in Windows filenames with underscores.

    Examples
    --------
    ``"I:VIX"``   → ``"I_VIX"``
    ``"$I:TNX"``  → ``"$I_TNX"``
    ``"AAPL"``    → ``"AAPL"``   (unchanged)
    """
    for ch in _ILLEGAL_FILENAME_CHARS:
        symbol = symbol.replace(ch, "_")
    return symbol


def _resolve_dir(config: dict) -> str:
    """Return absolute path to the CSV data directory."""
    csv_dir = config.get("csv_data_dir", "csv_data")
    if not os.path.isabs(csv_dir):
        csv_dir = os.path.join(_PROJECT_ROOT, csv_dir)
    return csv_dir


def _find_csv(symbol: str, csv_dir: str) -> str | None:
    """Return the first matching CSV path for *symbol*, or None.

    Special characters that are illegal in Windows filenames (e.g. ``:`` in
    ``I:VIX``) are replaced with underscores before constructing the path, so
    the expected file for ``I:VIX`` is ``I_VIX.csv``.
    """
    safe = _sanitize_filename(symbol)
    candidates = [
        os.path.join(csv_dir, f"{safe.upper()}.csv"),
        os.path.join(csv_dir, f"{safe.lower()}.csv"),
        os.path.join(csv_dir, f"{safe}.csv"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Rename columns to their canonical equivalents in-place (returns new df).
    Date-like columns → "Date"; OHLCV columns → Title-Case canonical names.
    """
    col_map: dict[str, str] = {}
    for col in df.columns:
        key = col.strip().lower()
        if key in _DATE_ALIASES:
            col_map[col] = "Date"
        elif key in _COL_ALIASES:
            col_map[col] = _COL_ALIASES[key]
    df = df.rename(columns=col_map)
    # Drop duplicate column names that arise when both 'Close' and 'Adj Close'
    # are present — both map to 'Close'.  Keep the first occurrence.
    return df.loc[:, ~df.columns.duplicated(keep="first")]


def _to_utc_index(df: pd.DataFrame, filepath: str) -> pd.DataFrame | None:
    """
    Ensure *df* has a UTC-aware DatetimeIndex named 'Datetime'.
    Handles: 'Date' column, existing DatetimeIndex, or string index.
    Returns None if the date cannot be parsed.
    """
    if "Date" in df.columns:
        try:
            df["Date"] = pd.to_datetime(df["Date"])
        except Exception as exc:
            logger.error(f"CSV '{filepath}': cannot parse 'Date' column: {exc}")
            return None
        df = df.set_index("Date")
    elif not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index)
        except Exception as exc:
            logger.error(f"CSV '{filepath}': cannot parse index as dates: {exc}")
            return None

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    df.index.name = "Datetime"
    return df


def get_price_data(symbol: str, start_date: str, end_date: str, config: dict):
    """
    Load OHLCV history for *symbol* from a local CSV file.

    Parameters
    ----------
    symbol     : ticker string — looked up as ``{csv_data_dir}/{SYMBOL}.csv``
    start_date : ISO date string "YYYY-MM-DD" (inclusive filter)
    end_date   : ISO date string "YYYY-MM-DD" (inclusive filter)
    config     : CONFIG dict from config.py

    Returns
    -------
    pd.DataFrame with columns [Open, High, Low, Close, Volume] and a
    UTC DatetimeIndex named 'Datetime', or None on any error / no data.
    """
    csv_dir = _resolve_dir(config)
    filepath = _find_csv(symbol, csv_dir)

    if filepath is None:
        safe = _sanitize_filename(symbol)
        candidates = [
            os.path.join(csv_dir, f"{safe.upper()}.csv"),
            os.path.join(csv_dir, f"{safe.lower()}.csv"),
        ]
        logger.warning(
            f"CSV file not found for '{symbol}' "
            f"(filename base: '{safe}'). Looked in: {candidates}"
        )
        return None

    # --- Read ---
    try:
        df = pd.read_csv(filepath)
    except Exception as exc:
        logger.error(f"CSV ERROR reading '{filepath}': {exc}")
        return None

    if df.empty:
        logger.debug(f"CSV file '{filepath}' is empty.")
        return None

    # --- Normalise columns ---
    df = _normalise_columns(df)

    # --- Date index ---
    df = _to_utc_index(df, filepath)
    if df is None:
        return None

    # --- Validate required columns ---
    missing = [c for c in _CANONICAL_COLS if c not in df.columns]
    if missing:
        logger.error(
            f"CSV '{filepath}': missing required columns {missing}. "
            f"Found: {list(df.columns)}"
        )
        return None

    # --- Keep only canonical columns, coerce to numeric ---
    df = df[_CANONICAL_COLS].copy()
    for col in _CANONICAL_COLS:
        # Strip currency formatting ($1,234.56 → 1234.56) before numeric coercion
        if df[col].dtype == object:
            df[col] = df[col].astype(str).str.replace(r"[$,]", "", regex=True).str.strip()
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # --- Filter by date range ---
    if start_date:
        start_ts = pd.Timestamp(start_date, tz="UTC")
        df = df[df.index >= start_ts]
    if end_date:
        end_ts = pd.Timestamp(end_date, tz="UTC")
        df = df[df.index <= end_ts]

    if df.empty:
        logger.debug(
            f"CSV '{filepath}': no data in range [{start_date} → {end_date}]."
        )
        return None

    return df
