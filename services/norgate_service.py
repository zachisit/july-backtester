# services/norgate_service.py

import norgatedata
import pandas as pd

from helpers.ticker_normalizer import normalize_ticker

def get_price_data(symbol, start_date, end_date, config):
    """
    Norgate implementation for fetching price data.

    Supports `include_delisted` config key to include delisted/failed companies.
    """
    # Normalize ticker for Norgate format (e.g., "^VIX" → "I:VIX", "SPY" → "SPY")
    norgate_symbol = normalize_ticker(symbol, "norgate")

    try:
        # It now reads the special object that was conditionally set in config.py
        adjustment_setting = config["price_adjustment"]

        # Use ALLMARKETDAYS padding when include_delisted is True to get delisted stocks
        padding_setting = norgatedata.PaddingType.ALLMARKETDAYS if config.get("include_delisted", False) else norgatedata.PaddingType.NONE

        df = norgatedata.price_timeseries(
            norgate_symbol,
            interval=config["timeframe"],
            start_date=start_date,
            end_date=end_date,
            stock_price_adjustment_setting=adjustment_setting,
            padding_setting=padding_setting,
            timeseriesformat='pandas-dataframe'
        )
        if df is None or df.empty:
            return None
        
        # Standardize column names
        df.columns = [col.capitalize() for col in df.columns]
        df.index.name = 'Datetime'

        # Normalize datetime index for daily data (set time to midnight)
        # This ensures consistent datetime handling across daily and intraday timeframes
        if config.get("timeframe", "D").upper() == "D":
            df.index = pd.to_datetime(df.index)
            df.index = df.index.normalize()

        return df
    except Exception as e:
        print(f"  -> Norgate ERROR fetching data for '{symbol}': {e}")
        return None