# data_handler.py
import traceback
from datetime import timedelta
from typing import Tuple, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from . import default_config as config

def load_trades(csv_path: str) -> pd.DataFrame:
    """
    Loads trade data from the specified CSV file.

    Args:
        csv_path (str): The path to the trades CSV file.

    Returns:
        pd.DataFrame: DataFrame containing the loaded trades.

    Raises:
        FileNotFoundError: If the CSV file is not found.
        Exception: For other reading errors.
    """
    #print(f"\n--- Loading Data ---")
    try:
        trades_df = pd.read_csv(csv_path, delimiter=',')
        #print(f"Successfully loaded trades.csv from '{csv_path}'")
        if config.VERBOSE_DEBUG: print(f"[DEBUG DATA LOAD] Initial trades_df shape: {trades_df.shape}")
        return trades_df
    except FileNotFoundError:
        print(f"ERROR: Trades file not found at '{csv_path}'. Please ensure the file exists.")
        raise # Re-raise the exception
    except Exception as read_err:
        print(f"ERROR reading CSV file '{csv_path}': {read_err}")
        raise # Re-raise the exception

def clean_trades_data(trades_df: pd.DataFrame, initial_equity: float) -> Tuple[pd.DataFrame, str]:
    """
    Cleans and prepares the trades DataFrame for analysis.

    Args:
        trades_df (pd.DataFrame): The raw trades DataFrame.
        initial_equity (float): The initial equity for the backtest.

    Returns:
        Tuple[pd.DataFrame, str]: A tuple containing:
            - The cleaned and prepared trades DataFrame.
            - A string summarizing the cleaning process.

    Raises:
        ValueError: If required date columns ('Date', 'Ex. date') are missing.
    """
    #print("\n--- Attempting Data Cleaning ---")
    initial_load_count = len(trades_df)

    # --- Column Remapping (engine v2 → legacy analyzer names) ---
    # The backtester engine writes EntryDate/ExitDate/EntryPrice/ExitPrice/ProfitPct/etc.
    # but the analyzer was built against an older column schema (Date/Ex. date/Price/etc.).
    # This remapping bridges the two without touching every downstream reference.
    _COLUMN_MAP = {
        'EntryDate':    'Date',
        'ExitDate':     'Ex. date',
        'EntryPrice':   'Price',
        'ExitPrice':    'Ex. Price',
        'ProfitPct':    '% Profit',
        'MAE_pct':      'MAE',
        'MFE_pct':      'MFE',
        'HoldDuration': '# bars',
    }
    for new_name, old_name in _COLUMN_MAP.items():
        if new_name in trades_df.columns and old_name not in trades_df.columns:
            trades_df.rename(columns={new_name: old_name}, inplace=True)

    # Convert dates — strip tz so equity curves align with tz-naive yfinance data.
    # Parquet-sourced runs produce UTC-aware timestamps; utc=True normalises all
    # input formats (tz-naive, UTC, any offset) to UTC, then tz_convert(None) strips
    # the timezone to give a consistent tz-naive DatetimeIndex across all providers.
    if 'Date' in trades_df.columns:
        trades_df['Date'] = pd.to_datetime(trades_df['Date'], errors='coerce', utc=True).dt.tz_convert(None)
    else:
        raise ValueError("Required column 'Date' not found.")
    if 'Ex. date' in trades_df.columns:
        trades_df['Ex. date'] = pd.to_datetime(trades_df['Ex. date'], errors='coerce', utc=True).dt.tz_convert(None)
    else:
         raise ValueError("Required column 'Ex. date' not found.")
    
    # Clean 'MAE' if it exists
    if 'MAE' in trades_df.columns:
         if config.VERBOSE_DEBUG: print("Cleaning 'MAE' column...")
         trades_df['MAE'] = trades_df['MAE'].astype(str).str.replace('%', '', regex=False).str.strip()
         trades_df['MAE'] = trades_df['MAE'].replace(['-', '--', 'na', 'n/a', 'none', '', ' '], np.nan, regex=False)
         trades_df['MAE'] = trades_df['MAE'].replace({r'(?i)-?nan\(?ind\)?': np.nan}, regex=True)
         # Convert to numeric *AFTER* cleaning strings
         trades_df['MAE'] = pd.to_numeric(trades_df['MAE'], errors='coerce')
         # MAE is often negative, but usually represented as positive % in reports.
         # Keep it as is for now, plotting function handles positive/negative display.
         # trades_df['MAE'] = trades_df['MAE'].abs() # Optional: if you always want positive MAE
         if config.VERBOSE_DEBUG: print("'MAE' column cleaned.")
    else:
         print("Warning: Column 'MAE' not found.")

    # Clean 'MFE' if it exists
    if 'MFE' in trades_df.columns:
         if config.VERBOSE_DEBUG: print("Cleaning 'MFE' column...")
         trades_df['MFE'] = trades_df['MFE'].astype(str).str.replace('%', '', regex=False).str.strip()
         trades_df['MFE'] = trades_df['MFE'].replace(['-', '--', 'na', 'n/a', 'none', '', ' '], np.nan, regex=False)
         trades_df['MFE'] = trades_df['MFE'].replace({r'(?i)-?nan\(?ind\)?': np.nan}, regex=True)
         # Convert to numeric *AFTER* cleaning strings
         trades_df['MFE'] = pd.to_numeric(trades_df['MFE'], errors='coerce')
         if config.VERBOSE_DEBUG: print("'MFE' column cleaned.")
    else:
         print("Warning: Column 'MFE' not found.")

    # Convert numeric columns
    for col in config.NUMERIC_COLS:
         if col in trades_df.columns:
              trades_df[col] = pd.to_numeric(trades_df[col], errors='coerce')
         else:
              print(f"Warning: Expected numeric column '{col}' not found in CSV.")

    # Clean '% Profit'
    if '% Profit' in trades_df.columns:
         if config.VERBOSE_DEBUG: print("Cleaning '% Profit' column...")
         trades_df['% Profit'] = trades_df['% Profit'].astype(str).str.replace('%', '', regex=False).str.strip()
         # More robust NaN replacement
         trades_df['% Profit'] = trades_df['% Profit'].replace(
             ['-', '--', 'na', 'n/a', 'none', '', ' '], np.nan, regex=False
         )
         # Handle specific string NaNs like '-nan(ind)' if necessary (case-insensitive)
         trades_df['% Profit'] = trades_df['% Profit'].replace({r'(?i)-?nan\(?ind\)?': np.nan}, regex=True)
         trades_df['% Profit'] = pd.to_numeric(trades_df['% Profit'], errors='coerce')
         if config.VERBOSE_DEBUG: print("'% Profit' column cleaned.")
    else:
         print("Warning: Column '% Profit' not found.")

    # Check and drop NaNs in critical columns
    critical_cols_present = [col for col in config.CRITICAL_COLS if col in trades_df.columns]
    if config.VERBOSE_DEBUG: print(f"Checking for NaNs in critical columns: {critical_cols_present}")

    nan_check_df = trades_df[critical_cols_present].isnull()
    rows_with_nan = nan_check_df.any(axis=1)
    num_rows_with_nan = rows_with_nan.sum()
    nan_counts_str = trades_df[critical_cols_present].isnull().sum().to_string() if critical_cols_present else "N/A"
    problematic_rows_str = "None"

    if num_rows_with_nan > 0:
        print(f"\nFound {num_rows_with_nan} rows with NaN in critical columns.")
        problematic_rows_str = trades_df.loc[rows_with_nan, critical_cols_present].head(20).to_string()
        trades_df.dropna(subset=critical_cols_present, inplace=True)
        print(f"Dropped {num_rows_with_nan} rows.")
    else:
        print("No NaNs found in critical columns.")
        problematic_rows_str = "None (No rows dropped)"

    final_trade_count = len(trades_df)
    #print(f"Final trade count after cleaning: {final_trade_count}")

    cleaning_summary = (
         f"Initial trades loaded: {initial_load_count}\n"
         f"Rows dropped due to NaN in critical columns ({', '.join(critical_cols_present)}): {num_rows_with_nan}\n"
         f"NaN Counts per Critical Column:\n{nan_counts_str}\n\n"
         f"Sample of Dropped/Problematic Rows (if any):\n{problematic_rows_str}\n\n"
         f"Final Trade Count for Analysis: {final_trade_count}"
    )

    if trades_df.empty:
         print("\nDataFrame is empty after cleaning. Cannot proceed.")
         return trades_df, cleaning_summary # Return early

    # --- Sort and prepare further ---
    trades_df = trades_df.sort_values(by='Ex. date').reset_index(drop=True)
    if config.VERBOSE_DEBUG: print("[DEBUG DATA PREP] Sorted trades by 'Ex. date' and reset index.")

    # Add Entry Month/Year
    trades_df['Entry YrMo'] = trades_df['Date'].dt.to_period('M') if pd.api.types.is_datetime64_any_dtype(trades_df['Date']) else pd.NaT
    if config.VERBOSE_DEBUG: print("[DEBUG DATA PREP] Added 'Entry YrMo' column.")

    # Add Win column (boolean)
    trades_df['Win'] = trades_df['Profit'] > 0
    if config.VERBOSE_DEBUG: print("[DEBUG DATA PREP] Added 'Win' boolean column.")

    # Calculate Return_Frac (Fractional Return per Trade)
    if 'Profit' in trades_df.columns and initial_equity > 0:
        position_value_col = 'Position value' if 'Position value' in trades_df.columns else ('Position Value' if 'Position Value' in trades_df.columns else None)
        if position_value_col:
            estimated_capital_per_trade = trades_df[position_value_col].fillna(initial_equity * 0.1).clip(lower=1)
            if config.VERBOSE_DEBUG: print(f"[DEBUG DATA PREP] Using '{position_value_col}' for fractional return denominator.")
        else:
            estimated_capital_per_trade = pd.Series([initial_equity * 0.1] * len(trades_df), index=trades_df.index).clip(lower=1)
            if config.VERBOSE_DEBUG: print("[DEBUG DATA PREP] Using estimated 10% of initial equity for fractional return denominator.")
        trades_df['Return_Frac'] = trades_df['Profit'] / estimated_capital_per_trade
        if config.VERBOSE_DEBUG: print("[DEBUG DATA PREP] Calculated 'Return_Frac' based on 'Profit' and capital.")
    elif '% Profit' in trades_df.columns and pd.api.types.is_numeric_dtype(trades_df['% Profit']):
        trades_df['Return_Frac'] = trades_df['% Profit'] / 100.0
        if config.VERBOSE_DEBUG: print("[DEBUG DATA PREP] Calculated 'Return_Frac' based on '% Profit'.")
    else:
        print("Warning: Could not calculate 'Return_Frac'. Defaulting to 0.")
        trades_df['Return_Frac'] = 0.0

    # Calculate Cumulative Profit and Equity Curve
    trades_df['Cumulative_Profit'] = trades_df['Profit'].cumsum()
    trades_df['Equity'] = initial_equity + trades_df['Cumulative_Profit']
    if config.VERBOSE_DEBUG: print("[DEBUG DATA PREP] Calculated 'Cumulative_Profit' and 'Equity'.")

    return trades_df, cleaning_summary

def calculate_daily_returns(trades_df: pd.DataFrame, initial_equity: float) -> Tuple[pd.Series, pd.Series]:
    """
    Calculates daily equity and returns based on trade exit dates.

    Args:
        trades_df (pd.DataFrame): Cleaned trades DataFrame with 'Ex. date' and
                                  a cumulative profit column ('Cumulative_Profit' or 'Cum. Profit').
        initial_equity (float): Initial equity value.

    Returns:
        Tuple[pd.Series, pd.Series]: A tuple containing:
            - daily_equity Series (indexed by Date).
            - daily_returns Series (indexed by Date).
            Returns empty Series if calculation is not possible.
    """
    #print("\n--- Calculating Daily Returns ---")
    daily_equity = pd.Series(dtype=float)
    daily_returns = pd.Series(dtype=float)

    if trades_df.empty or not all(col in trades_df.columns for col in ['Date', 'Ex. date']):
        print("Warning: Insufficient data or missing date columns for daily returns calculation.")
        return daily_equity, daily_returns

    # Prioritize calculated 'Cumulative_Profit', fallback to 'Cum. Profit' if needed
    equity_source_col = None
    if 'Cumulative_Profit' in trades_df and pd.api.types.is_numeric_dtype(trades_df['Cumulative_Profit']):
        equity_source_col = 'Cumulative_Profit'
    elif 'Cum. Profit' in trades_df and pd.api.types.is_numeric_dtype(trades_df['Cum. Profit']):
        equity_source_col = 'Cum. Profit'

    if equity_source_col:
        if config.VERBOSE_DEBUG: print(f"[DEBUG DAILY RETURNS] Using '{equity_source_col}' as basis for daily equity.")
        equity_curve_raw = initial_equity + trades_df.set_index('Ex. date')[equity_source_col]

        first_trade_date = trades_df['Date'].min()
        last_trade_date = trades_df['Ex. date'].max()

        if pd.notna(first_trade_date) and pd.notna(last_trade_date):
            # Start equity series one day before the first trade entry
            start_point_date = first_trade_date - timedelta(days=1)
            start_point = pd.Series([initial_equity], index=[start_point_date])
            equity_curve = pd.concat([start_point, equity_curve_raw])

            # Handle potential duplicate indices from multiple trades closing on the same day
            # Keep the LAST equity value for that day
            equity_curve = equity_curve[~equity_curve.index.duplicated(keep='last')]

            # Create full date range and forward-fill equity
            full_date_range = pd.date_range(start=equity_curve.index.min(), end=last_trade_date, freq='D')
            daily_equity = equity_curve.reindex(full_date_range).ffill()
            # Fill any remaining NaNs at the beginning (if first trade wasn't day 1)
            daily_equity.fillna(initial_equity, inplace=True)

            if len(daily_equity) > 1:
                daily_returns = daily_equity.pct_change().dropna()
                # Handle potential infinities if equity goes to zero then recovers
                daily_returns.replace([np.inf, -np.inf], 0, inplace=True)
                #print(f"Calculated daily returns. Length: {len(daily_returns)}, Date Range: {daily_returns.index.min().date()} to {daily_returns.index.max().date()}")
            else:
                print("Warning: Not enough data points in daily_equity to calculate daily returns.")
        else:
            print("Warning: Invalid start/end dates for daily range generation.")
    else:
        print("Warning: No suitable cumulative profit column found for daily returns calculation.")

    return daily_equity, daily_returns

def download_benchmark_data(ticker: str, start_date: pd.Timestamp, end_date: pd.Timestamp) -> Optional[pd.DataFrame]:
    """
    Downloads and processes benchmark data from yfinance with enhanced error reporting.

    Args:
        ticker (str): The ticker symbol for the benchmark (e.g., 'SPY').
        start_date (pd.Timestamp): The approximate start date for the benchmark data.
        end_date (pd.Timestamp): The approximate end date for the benchmark data.

    Returns:
        Optional[pd.DataFrame]: DataFrame with 'Benchmark_Price' column indexed by Date,
                                or None if download/processing fails.
    """
    #print(f"\n--- Attempting Benchmark Data Download ({ticker}) ---")
    if config.VERBOSE_DEBUG: print(f"[DEBUG BENCHMARK DOWNLOAD] Entering download_benchmark_data for {ticker}")

    if pd.isna(start_date) or pd.isna(end_date):
        print(f"ERROR: Cannot download benchmark for {ticker}. Invalid start ({start_date}) or end ({end_date}) date provided.")
        return None

    data_clean = None # Initialize

    try:
        # Extend download slightly for robustness & yfinance end date convention
        download_start = start_date - timedelta(days=7) # Go back a bit further
        download_end = end_date + timedelta(days=2) # Go forward a bit further
        download_start_str = download_start.strftime('%Y-%m-%d')
        download_end_str = download_end.strftime('%Y-%m-%d')

        if config.VERBOSE_DEBUG: print(f"[DEBUG BENCHMARK DOWNLOAD] Calculated download range: {download_start_str} to {download_end_str}")
        #print(f"Downloading {ticker} data from {download_start_str} to {download_end_str} via yfinance...")

        data = yf.download(ticker, start=download_start_str, end=download_end_str, progress=False, auto_adjust=False, back_adjust=True)

        if data.empty:
            print(f"WARNING: No data returned by yfinance for {ticker} in the range {download_start_str} to {download_end_str}.")
            print("         Possible reasons: Invalid ticker, no data for date range, network issue.")
            # Return None if empty data is considered a failure for benchmark analysis
            return None

        if config.VERBOSE_DEBUG:
            print(f"[DEBUG BENCHMARK DOWNLOAD] Downloaded raw data shape: {data.shape}, Index range: {data.index.min()} to {data.index.max()}")
            print(f"[DEBUG BENCHMARK DOWNLOAD] Raw data columns: {data.columns}")

        # --- Robust Column Selection ---
        price_column_options = ['Close', 'Adj Close'] # Prefer 'Close' after back_adjust=True
        price_column = None
        if isinstance(data.columns, pd.MultiIndex):
            # Handle potential MultiIndex if columns like ('Close', 'SPY') exist
            available_cols_level0 = data.columns.get_level_values(0).unique()
            for col in price_column_options:
                if col in available_cols_level0:
                    price_column = col
                    if config.VERBOSE_DEBUG: print(f"[DEBUG BENCHMARK DOWNLOAD] Found '{price_column}' in MultiIndex columns level 0.")
                    break
        else: # Single level columns
            for col in price_column_options:
                if col in data.columns:
                    price_column = col
                    if config.VERBOSE_DEBUG: print(f"[DEBUG BENCHMARK DOWNLOAD] Found '{price_column}' in single-level columns.")
                    break

        if price_column is None:
             print(f"ERROR: Neither 'Close' nor 'Adj Close' found in downloaded {ticker} data.")
             print(f"Available columns: {data.columns}")
             return None

        # --- Process and clean the downloaded data ---
        if isinstance(data.columns, pd.MultiIndex):
             print("WARNING: Unexpected MultiIndex columns from yfinance download. Attempting to handle.")
             try:
                 # Try accessing with tuple ('Close', ticker) - this often fails if yf changes format
                 if (price_column, ticker) in data.columns:
                     data_clean_temp = data[(price_column, ticker)].to_frame(name='Benchmark_Price')
                 else:
                     # More robust: Select the price_column level, then take the first ticker column if multiple exist
                     data_slice = data[price_column]
                     if isinstance(data_slice, pd.DataFrame) and not data_slice.empty: # Multiple tickers under 'Close'
                         first_ticker_col = data_slice.columns[0]
                         data_clean_temp = data_slice[[first_ticker_col]].rename(columns={first_ticker_col: 'Benchmark_Price'})
                         print(f"WARNING: Using first ticker column '{first_ticker_col}' under '{price_column}' due to MultiIndex.")
                     elif isinstance(data_slice, pd.Series): # Single ticker under 'Close'
                         data_clean_temp = data_slice.to_frame(name='Benchmark_Price')
                     else:
                         raise ValueError("Could not extract Series/DataFrame from MultiIndex slice.")
                 if config.VERBOSE_DEBUG: print(f"[DEBUG BENCHMARK DOWNLOAD] Extracted '{price_column}' from MultiIndex.")

             except Exception as mi_err:
                  print(f"ERROR: Could not reliably extract price from MultiIndex columns for {ticker}. Error: {mi_err}")
                  return None
        else:
             # Standard single-level columns case
             data_clean_temp = data[[price_column]].rename(columns={price_column: 'Benchmark_Price'})
             if config.VERBOSE_DEBUG: print(f"[DEBUG BENCHMARK DOWNLOAD] Selected '{price_column}' column from single-level index.")

        # Convert index, assign name, handle NaNs
        data_clean_temp.index = pd.to_datetime(data_clean_temp.index)
        data_clean_temp.index.name = 'Date'
        data_clean_temp.dropna(inplace=True) # Drop any rows with NaN price

        data_clean = data_clean_temp
        if config.VERBOSE_DEBUG and data_clean is not None and not data_clean.empty:
            print(f"[DEBUG BENCHMARK DOWNLOAD] Processed data shape: {data_clean.shape}, Index range: {data_clean.index.min()} to {data_clean.index.max()}")
            print(f"[DEBUG BENCHMARK DOWNLOAD] Processed data head:\n{data_clean.head()}")
        #print(f"Successfully downloaded and processed {ticker} data.")

    except Exception as e:
        print(f"\n!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        print(f"!!! ERROR DURING BENCHMARK DOWNLOAD/PROCESSING for {ticker} !!!")
        print(f"!!! Type: {type(e).__name__}")
        print(f"!!! Details: {e}")
        print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!\n")
        print("--- Traceback ---")
        traceback.print_exc()
        print("--- End Traceback ---\n")
        print(f"Benchmark data for {ticker} could not be obtained due to the error above. Analysis involving benchmark will be skipped or limited.")
        data_clean = None

    # --- Final Check and Return ---
    if data_clean is not None and 'Benchmark_Price' not in data_clean.columns:
         print(f"ERROR: 'Benchmark_Price' column unexpectedly missing after processing for {ticker}. Columns: {data_clean.columns}")
         return None

    if data_clean is not None and data_clean.empty:
         print(f"Warning: Processed benchmark data for {ticker} is empty (e.g., after date filtering or NaN removal).")
         return None # Treat empty DataFrame after processing as failure

    if config.VERBOSE_DEBUG and data_clean is not None: print(f"[DEBUG BENCHMARK DOWNLOAD] Exiting download_benchmark_data for {ticker}. Returning DataFrame.")
    return data_clean