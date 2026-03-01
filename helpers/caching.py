# helpers/caching.py (Corrected for safe filenames)

import os
import pandas as pd
from datetime import datetime, timedelta
import logging
import re # Import the regular expressions module

logger = logging.getLogger(__name__)

# --- CONFIGURABLE SETTINGS ---
CACHE_DIR = "data_cache"
CACHE_TTL_HOURS = 24 

os.makedirs(CACHE_DIR, exist_ok=True)

def _sanitize_filename(symbol: str) -> str:
    """Replaces characters invalid for filenames with an underscore."""
    # This regex will replace any character that is NOT a letter, digit, hyphen, or underscore.
    return re.sub(r'[^a-zA-Z0-9_-]', '_', symbol)

def get_cached_data(symbol: str, start: str, end: str, timeframe: str, multiplier: int) -> pd.DataFrame | None:
    """Checks for and loads a DataFrame from a local Parquet cache."""
    # Sanitize the symbol for use in a filename
    safe_symbol = _sanitize_filename(symbol)

    end_date_str = datetime.now().strftime('%Y-%m-%d') if end == datetime.now().strftime('%Y-%m-%d') else end
    
    # Use the sanitized symbol to create the filename
    filename = f"{safe_symbol}_{start}_{end_date_str}_{timeframe}_{multiplier}.parquet"
    filepath = os.path.join(CACHE_DIR, filename)

    if os.path.exists(filepath):
        file_mod_time = datetime.fromtimestamp(os.path.getmtime(filepath))
        if datetime.now() - file_mod_time < timedelta(hours=CACHE_TTL_HOURS):
            logger.debug(f"  -> Cache HIT for '{symbol}'. Loading from '{filepath}'.")
            try:
                return pd.read_parquet(filepath)
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