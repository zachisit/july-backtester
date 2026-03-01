import logging
from config import CONFIG

# Import the specific functions directly from the service modules
from .polygon_service import get_last_n_bars, get_price_data, get_previous_close_data

logger = logging.getLogger(__name__)

def get_data_service():
    """
    Factory function to get the data fetching service for a date RANGE.
    """
    provider = CONFIG.get("data_provider", "polygon").lower()
    if provider == "polygon":
        logger.info("--- Using Polygon.io Data Service for Range Fetch ---")
        return get_price_data
    # Add other providers like norgate here in the future if needed
    # elif provider == "norgate":
    #     return norgate_get_price_data
    else:
        raise ValueError(f"Unsupported data provider: {provider}")

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