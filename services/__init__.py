import logging
from config import CONFIG

# Import Polygon helpers at module level for backwards compatibility.
# These are only used when data_provider == "polygon".
from .polygon_service import get_last_n_bars, get_price_data, get_previous_close_data

logger = logging.getLogger(__name__)

def get_data_service():
    """
    Factory function that returns the appropriate ``get_price_data`` callable
    for the configured data provider.

    Supported providers (config["data_provider"]):
        "polygon" — Polygon.io REST API  (default)
        "norgate" — Norgate Data local API
        "yahoo"   — Yahoo Finance via yfinance
        "csv"     — Local CSV files (see config["csv_data_dir"])
    """
    provider = CONFIG.get("data_provider", "polygon").lower()

    if provider == "polygon":
        logger.info("Using Polygon.io data service.")
        return get_price_data

    if provider == "norgate":
        logger.info("Using Norgate data service.")
        from .norgate_service import get_price_data as _fetcher
        return _fetcher

    if provider == "yahoo":
        logger.info("Using Yahoo Finance data service.")
        from .yahoo_service import get_price_data as _fetcher
        return _fetcher

    if provider == "csv":
        logger.info("Using local CSV data service.")
        from .csv_service import get_price_data as _fetcher
        return _fetcher

    raise ValueError(
        f"Unsupported data_provider '{provider}'. "
        f"Valid options: 'polygon', 'norgate', 'yahoo', 'csv'."
    )

def get_previous_close_service():
    """
    Factory function to get the data fetching service for the SINGLE PREVIOUS DAY.
    """
    provider = CONFIG.get("data_provider", "polygon").lower()
    if provider == "polygon":
        logger.info("--- Using Polygon.io Data Service for Previous Close ---")
        return get_previous_close_data
    # Add other providers here in the future if needed
    else:
        raise ValueError(f"Unsupported data provider: {provider}")
    
def get_last_n_bars_service():
    """Factory function for the last N bars fetcher."""
    provider = CONFIG.get("data_provider", "polygon").lower()
    if provider == "polygon":
        return get_last_n_bars
    else:
        raise ValueError(f"Unsupported data provider: {provider}")