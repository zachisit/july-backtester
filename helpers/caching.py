# helpers/caching.py (Corrected for safe filenames)

import os
import pandas as pd
from datetime import datetime, timedelta
import logging

from helpers.filename_utils import (
    resolve_existing as _resolve_existing,
    sanitize_symbol_for_filename as _sanitize_filename,
)

logger = logging.getLogger(__name__)

# --- CONFIGURABLE SETTINGS ---
CACHE_DIR = "data_cache"
CACHE_TTL_HOURS = 24

os.makedirs(CACHE_DIR, exist_ok=True)

def get_cached_data(symbol: str, start: str, end: str, timeframe: str, multiplier: int) -> pd.DataFrame | None:
    """Checks for and loads a DataFrame from a local Parquet cache."""
    # Sanitize the symbol for use in a filename
    end_date_str = datetime.now().strftime('%Y-%m-%d') if end == datetime.now().strftime('%Y-%m-%d') else end

    # READ path: resolve across every candidate spelling, not just the guarded
    # one (#345). A cache written before the reserved-name guard stores CON/PRN
    # unguarded; checking only "_CON" reports "not cached" for a file that
    # exists, and re-fetches a delisted symbol on every run. Silent, and exactly
    # the survivorship-critical names.
    safe_symbol = _sanitize_filename(symbol)
    filename = f"{safe_symbol}_{start}_{end_date_str}_{timeframe}_{multiplier}.parquet"
    filepath = _resolve_existing(
        CACHE_DIR, symbol,
        template=f"{{name}}_{start}_{end_date_str}_{timeframe}_{multiplier}.parquet",
    ) or os.path.join(CACHE_DIR, filename)

    if os.path.exists(filepath):
        file_mod_time = datetime.fromtimestamp(os.path.getmtime(filepath))
        if datetime.now() - file_mod_time < timedelta(hours=CACHE_TTL_HOURS):
            logger.debug(f"  -> Cache HIT for '{symbol}'. Loading from '{filepath}'.")
            try:
                df = pd.read_parquet(filepath)
                # Validate that cached data actually covers the requested start date.
                # A provider may have returned plan-capped data (e.g. only 5 years) for
                # a longer request, storing truncated rows under the full-range cache key.
                # After a plan upgrade the cache would silently serve the old capped data.
                requested_start = pd.Timestamp(start).tz_localize("UTC")
                cache_start = df.index.min()
                if hasattr(cache_start, "tzinfo") and cache_start.tzinfo is None:
                    cache_start = cache_start.tz_localize("UTC")
                lag_days = (cache_start - requested_start).days
                if lag_days > 30:
                    logger.warning(
                        f"  -> Cache STALE for '{symbol}': cached start {cache_start.date()} "
                        f"lags requested {start} by {lag_days} days — discarding and re-fetching."
                    )
                    return None
                return df
            except Exception as e:
                logger.warning(f"Could not read cache file '{filepath}'. Will re-fetch. Error: {e}")
                return None
    
    logger.debug(f"  -> Cache MISS for '{symbol}'.")
    return None

def set_cached_data(df: pd.DataFrame, symbol: str, start: str, end: str, timeframe: str, multiplier: int):
    """Saves a DataFrame to the local Parquet cache."""
    # Sanitize the symbol for use in a filename
    safe_symbol = _sanitize_filename(symbol)

    end_date_str = datetime.now().strftime('%Y-%m-%d') if end == datetime.now().strftime('%Y-%m-%d') else end
    
    # Use the sanitized symbol to create the filename
    filename = f"{safe_symbol}_{start}_{end_date_str}_{timeframe}_{multiplier}.parquet"
    filepath = os.path.join(CACHE_DIR, filename)
    try:
        df.to_parquet(filepath)
        logger.debug(f"  -> Saved '{symbol}' to cache at '{filepath}'.")
    except Exception as e:
        logger.error(f"Failed to write to cache file '{filepath}'. Error: {e}")