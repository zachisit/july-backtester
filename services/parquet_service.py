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

from helpers.filename_utils import (
    filename_candidates as _filename_candidates,
    sanitize_symbol_for_filename as _sanitize_filename,
)
from helpers.ticker_normalizer import normalize_ticker

logger = logging.getLogger(__name__)

# Project root = parent of this services/ package
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CANONICAL_COLS = ["Open", "High", "Low", "Close", "Volume"]


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

    Also checks for Norgate-style date-suffixed files (e.g. ALTR-201512.parquet)
    used for delisted/acquired tickers:
      - exactly one dated file, no live bare file -> returned directly.
      - more than one dated file -> returns the sentinel "_multi_|<dir>|<safe>".
        These are DISTINCT SECURITIES that happen to share a bare ticker
        (Norgate's TICKER-YYYYMM suffix names the month a security stopped
        trading, and different companies have reused the same bare ticker
        over time — see issue #395). The caller (get_price_data) must refuse
        to merge them, not concatenate.
      - a live bare file exists alongside dated file(s) -> the live file wins
        (existing behaviour), but a warning is logged naming the delisted
        history that is being masked, since it would otherwise be dropped
        with no indication anything was hidden (issue #395 item 3).
    """
    if not os.path.isdir(parquet_dir):
        logger.warning(f"Parquet data directory does not exist: {parquet_dir}")
        return None

    # Sanitize the symbol so I:VIX looks for I_VIX.parquet.
    # Every spelling, not just the guarded one: the Windows reserved-name guard
    # prefixes "_", but the frozen Norgate corpus stores the real delisted
    # tickers CON and PRN unguarded (CON-199804.parquet, PRN-200207.parquet).
    # Looking only for "_CON" returns None and drops the symbol silently.
    spellings = _filename_candidates(symbol)

    listing = os.listdir(parquet_dir)

    # Try exact match first, then case-insensitive
    exact_path, exact_safe = None, None
    for safe in spellings:
        for candidate in [f"{safe}.parquet", f"{safe.upper()}.parquet",
                          f"{safe.lower()}.parquet"]:
            path = os.path.join(parquet_dir, candidate)
            if os.path.isfile(path):
                exact_path, exact_safe = path, safe
                break
        if exact_path:
            break

    # Brute-force case-insensitive scan
    if exact_path is None:
        for safe in spellings:
            target = f"{safe.upper()}.parquet"
            for fname in listing:
                if fname.upper() == target:
                    exact_path, exact_safe = os.path.join(parquet_dir, fname), safe
                    break
            if exact_path:
                break

    if exact_path is not None:
        # issue #395 item 3: a live/exact bare file can mask delisted history
        # filed under date-suffixed names for the same bare ticker (e.g. ABI
        # resolves to a 228-bar live file while ABI-199908/ABI-200811 sit
        # right next to it, silently dropped). Warn so this is visible.
        prefix = exact_safe.upper() + "-"
        masked = sorted(
            fname for fname in listing
            if fname.upper().startswith(prefix) and fname.upper().endswith(".PARQUET")
        )
        if masked:
            candidates = [os.path.splitext(f)[0] for f in masked]
            logger.warning(
                f"'{symbol}' resolved to '{os.path.basename(exact_path)}', but "
                f"{len(masked)} delisted date-suffixed file(s) sharing this bare "
                f"ticker exist and are being masked/dropped: {candidates}. "
                f"If that history is needed, request the security ID directly "
                f"(e.g. '{candidates[0]}')."
            )
        return exact_path

    # Fallback: Norgate date-suffixed files e.g. ALTR-201512.parquet
    for safe in spellings:
        prefix = safe.upper() + "-"
        dated = sorted(
            fname for fname in listing
            if fname.upper().startswith(prefix) and fname.upper().endswith(".PARQUET")
        )
        if len(dated) == 1:
            return os.path.join(parquet_dir, dated[0])
        if len(dated) > 1:
            # issue #395: more than one distinct security shares this bare
            # ticker. Signal ambiguity to the caller, which must refuse to
            # merge rather than concatenate them.
            return "_multi_|" + parquet_dir + "|" + safe

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
    # Prefer the user's literal sanitized filename (I:VIX -> I_VIX.parquet),
    # then fall back to the provider-normalized convention (I:VIX -> VIX).
    requested_symbol = symbol
    filepath = _find_parquet(requested_symbol, parquet_dir)
    symbol = normalize_ticker(requested_symbol, "parquet")
    if filepath is None and symbol != requested_symbol:
        filepath = _find_parquet(symbol, parquet_dir)

    if filepath is None:
        logger.warning(
            f"Parquet file not found for '{symbol}'. "
            f"Looked in: {parquet_dir}"
        )
        return None

    # Multiple date-suffix period files under one bare ticker (Norgate
    # delisted format) means distinct securities reused the same bare
    # ticker at different times. issue #395: there is no correct way to
    # merge them from a bare ticker alone (their spans can overlap, and
    # even end-to-end splices splice two unrelated companies into one
    # series) — refuse rather than guess.
    if filepath.startswith("_multi_|"):
        _, fdir, safe = filepath.split("|", 2)
        prefix = safe.upper() + "-"
        parts = sorted(
            f for f in os.listdir(fdir)
            if f.upper().startswith(prefix) and f.upper().endswith(".PARQUET")
        )
        candidates = [os.path.splitext(f)[0] for f in parts]
        logger.error(
            f"'{symbol}' is ambiguous: {len(candidates)} distinct delisted "
            f"securities share this bare ticker ({candidates}). Refusing to "
            f"merge them into one series (see issue #395) — pass one of the "
            f"security IDs above instead of the bare ticker."
        )
        return None
    else:
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