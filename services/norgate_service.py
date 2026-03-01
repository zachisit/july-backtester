# services/norgate_service.py

import norgatedata
import pandas as pd

def get_price_data(symbol, start_date, end_date, config):
    """
    Norgate implementation for fetching price data.
    """
    try:
        # It now reads the special object that was conditionally set in config.py
        adjustment_setting = config["price_adjustment"]
        df = norgatedata.price_timeseries(
            symbol,
            interval=config["timeframe"],
            start_date=start_date,
            end_date=end_date,
            stock_price_adjustment_setting=adjustment_setting,
            padding_setting=norgatedata.PaddingType.NONE,
            timeseriesformat='pandas-dataframe'
        )
        if df is None or df.empty:
            return None
        
        # Standardize column names
        df.columns = [col.capitalize() for col in df.columns]
        df.index.name = 'Datetime'
        return df
    except Exception as e:
        print(f"  -> Norgate ERROR fetching data for '{symbol}': {e}")
        return None