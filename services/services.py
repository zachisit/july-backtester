# services.py

import logging
from config import CONFIG
# Import our new caching helpers
from helpers.caching import get_cached_data, set_cached_data

logger = logging.getLogger(__name__)

def get_data_service():
    """
    Factory function that returns the appropriate data fetching function
    based on the config, wrapped with a caching layer.
    """
    provider = CONFIG.get("data_provider", "polygon").lower()
    
    # --- Step 1: Get the actual, original data fetching function ---
    original_fetcher = None
    if provider == "polygon":
        try:
            from .polygon_service import get_price_data
            original_fetcher = get_price_data
        except ImportError:
            raise ImportError("Configuration Error: data_provider is 'polygon', but polygon_service.py could not be imported.")
    elif provider == "norgate":
        try:
            from .norgate_service import get_price_data
            original_fetcher = get_price_data
        except ImportError:
            raise ImportError("Configuration Error: data_provider is 'norgate', but norgate_service.py could not be imported.")
    else:
        raise ValueError(f"Unsupported data_provider in config: {provider}")

    # --- Step 2: Define a new function that wraps the original fetcher with caching logic ---
    def cached_fetcher(symbol, start_date, end_date, config):
        """
        This is the function that will be returned and used by main.py.
        It checks the cache first before calling the real API fetcher.
        """
        # We need the timeframe to create a unique cache filename
        timeframe = config.get("timeframe", "D")
        multiplier = config.get("timeframe_multiplier", 1)

        # Try to load from cache
        df = get_cached_data(symbol, start_date, end_date, timeframe, multiplier)

        if df is not None:
            # If we found it in the cache, we're done!
            return df

        # If not in cache, call the original API fetcher (e.g., polygon_service.get_price_data)
        logger.info(f"  -> Cache miss for '{symbol}'. Fetching from API...")
        df = original_fetcher(symbol, start_date, end_date, config)

        # If the fetch was successful, save the result to the cache for next time
        if df is not None and not df.empty:
            set_cached_data(df, symbol, start_date, end_date, timeframe, multiplier)
            
        return df

    # --- Step 3: Return the new, enhanced "cached_fetcher" function ---
    return cached_fetcher