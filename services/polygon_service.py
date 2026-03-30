# services/polygon_service.py (Definitively Corrected for Authentication)

import datetime
import os
import requests
import pandas as pd
import orjson
import logging
from datetime import datetime, timedelta
from dotenv import load_dotenv
from helpers.caching import get_cached_data, set_cached_data
from helpers.ticker_normalizer import normalize_ticker

load_dotenv()

logger = logging.getLogger(__name__)
SESSION = requests.Session()

def get_previous_close_data(symbol, config):
    """
    Fetches only the single previous day's OHLC bar using Polygon's /prev endpoint.
    This is the most reliable way to get the last settled closing data.
    """
    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key:
        raise ValueError("POLYGON_API_KEY is not set. Add it to your .env file or environment.")

    is_index = symbol.upper().startswith("I:")
    # Use "total_return" setting from config to determine 'adjusted' flag
    is_adjusted = "false" if is_index else ("true" if config.get("price_adjustment") == "total_return" else "false")
    
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev"
    params = {"apiKey": api_key, "adjusted": is_adjusted}

    try:
        response = SESSION.get(url, params=params)
        response.raise_for_status()
        data = orjson.loads(response.content)

        if data.get('status') in ['OK', 'DELAYED'] and data.get('results'):
            df = pd.DataFrame(data['results'])
            # Ensure the timestamp is parsed as timezone-aware (UTC)
            df['Datetime'] = pd.to_datetime(df['t'], unit='ms', utc=True)
            df.set_index('Datetime', inplace=True)
            df.rename(columns={'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume'}, inplace=True)
            
            expected_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
            available_cols = [col for col in expected_cols if col in df.columns]
            return df[available_cols]
        
        logger.warning(f"No previous day data returned for '{symbol}'. Response: {data}")
        return None
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Polygon HTTP ERROR for previous close on '{symbol}': {e}")
        return None
       
def get_price_data(symbol, start_date, end_date, config):
    """
    Polygon.io implementation for fetching price data.
    This version includes automatic pagination, correctly authenticates
    ALL requests, and dynamically handles different timeframes.
    """
    # Normalize ticker for Polygon format (e.g., "^VIX" → "I:VIX", "SPY" → "SPY")
    polygon_symbol = normalize_ticker(symbol, "polygon")

    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key:
        raise ValueError("POLYGON_API_KEY is not set. Add it to your .env file or environment.")

    # --- START: New Dynamic Timeframe Logic ---
    timeframe_code = config.get("timeframe", "D")
    timespan_map = {
        "D": "day", "H": "hour", "MIN": "minute", "W": "week", "M": "month"
    }
    timespan = timespan_map.get(timeframe_code)
    multiplier = config.get("timeframe_multiplier", 1)

    if not timespan:
        raise ValueError(f"Invalid timeframe '{timeframe_code}' in config. Must be one of {list(timespan_map.keys())}")
    # --- END: New Dynamic Timeframe Logic ---

    cached_df = get_cached_data(polygon_symbol, start_date, end_date, timespan, multiplier)
    if cached_df is not None:
        return cached_df

    is_index = polygon_symbol.upper().startswith("I:")
    is_adjusted = "false" if is_index else ("true" if config.get("price_adjustment") == "total_return" else "false")

    # The URL is now built dynamically using the timespan and multiplier.
    next_url = f"https://api.polygon.io/v2/aggs/ticker/{polygon_symbol}/range/{multiplier}/{timespan}/{start_date}/{end_date}"
    
    params = {
        "apiKey": api_key,
        "adjusted": is_adjusted,
        "sort": "asc",
        "limit": 50000
    }

    all_results = []
    request_count = 0

    while next_url:
        request_count += 1
        logger.debug(f"Fetching page {request_count} for '{symbol}' from URL: {next_url.split('?')[0]}")
        
        try:
            response = SESSION.get(next_url, params=params)
            response.raise_for_status()
            data = orjson.loads(response.content)

            if data.get('status') == 'ERROR':
                error_message = data.get('error', 'Unknown Polygon API error')
                logger.warning(f"Polygon API ERROR ... for '{symbol}': {error_message}")
                break

            results = data.get('results', [])
            if results:
                all_results.extend(results)

            next_url = data.get('next_url')
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Polygon HTTP ERROR on page {request_count} for '{symbol}': {e}")
            return None

    if not all_results:
        logger.debug(f"No data returned for '{symbol}' after {request_count} page(s).")
        return None

    logger.debug(f"Successfully fetched {len(all_results)} total bars for '{symbol}' in {request_count} API call(s).")

    df = pd.DataFrame(all_results)
    df['Datetime'] = pd.to_datetime(df['t'], unit='ms', utc=True)
    df.set_index('Datetime', inplace=True)
    df.rename(columns={
        'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume'
    }, inplace=True)
    
    expected_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    available_cols = [col for col in expected_cols if col in df.columns]

    # Normalize datetime index for daily data (set time to midnight)
    # This ensures consistent datetime handling across daily and intraday timeframes
    if config.get("timeframe", "D").upper() == "D":
        df.index = df.index.normalize()

    if not df.empty:
        set_cached_data(df, polygon_symbol, start_date, end_date, timespan, multiplier)

    return df[available_cols]

def get_last_n_bars(symbol, n_bars, config):
    """
    Fetches the last N settled daily bars for a symbol.
    This is a highly reliable way to get "yesterday" and "the day before."
    """
    api_key = os.environ.get("POLYGON_API_KEY")
    if not api_key:
        raise ValueError("POLYGON_API_KEY is not set. Add it to your .env file or environment.")

    # We query a recent range to ensure we capture the latest data
    end_date = datetime.utcnow().strftime('%Y-%m-%d')
    start_date = (datetime.utcnow() - timedelta(days=n_bars + 20)).strftime('%Y-%m-%d')

    is_index = symbol.upper().startswith("I:")
    is_adjusted = "false" if is_index else ("true" if config.get("price_adjustment") == "total_return" else "false")

    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/{start_date}/{end_date}"
    params = {
        "apiKey": api_key,
        "adjusted": is_adjusted,
        "sort": "desc",  # <-- CRITICAL: Sort in descending order (newest first)
        "limit": n_bars  # <-- CRITICAL: Only ask for the exact number of bars we need
    }

    try:
        response = SESSION.get(url, params=params)
        response.raise_for_status()
        data = orjson.loads(response.content)

        # print(f"[DEBUG - get_last_n_bars for {symbol}] Full API Response: {data}")

        if data.get('status') in ['OK', 'DELAYED'] and data.get('results'):
            df = pd.DataFrame(data['results'])
            df['Datetime'] = pd.to_datetime(df['t'], unit='ms', utc=True)
            df.set_index('Datetime', inplace=True)
            df.rename(columns={'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume'}, inplace=True)
            # CRITICAL: Re-sort back to ascending (oldest first) for indicator calculations
            df.sort_index(inplace=True)
            return df[['Open', 'High', 'Low', 'Close', 'Volume']]
        
        logger.warning(f"No previous day data returned for '{symbol}'. Status: {data.get('status')}, Results Count: {data.get('resultsCount')}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Polygon HTTP ERROR for last N bars on '{symbol}': {e}")
        return None