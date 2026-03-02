# config.py

from datetime import datetime
import numpy as np

CONFIG = {
    # --- S3 Bucket for Reports ---
    "s3_reports_bucket": "july-backtester-reports",

    # --- S3 Bucket for Reports ---
    # If set to true, make sure the env variable is set for the
    #   s3 bucket to store the files into
    "upload_to_s3": False,

    # ============================================================
    # SECTION 1: DATA PROVIDER
    # ============================================================
    # The Data Provider is hardcoded with two options at this time
    "data_provider": "polygon",  # Options: "norgate" or "polygon"

    # ============================================================
    # SECTION 2: BACKTEST PERIOD & CAPITAL
    # ============================================================
    # --- Start Date ---
    # Either set the specific start date, or set a time way in the past
    #   e.g. '1900-01-01' and the code will dynamically grab the last
    #   available start date from the Data Provider that you're using
    "start_date": "2004-01-01",
    
    # --- Start Date ---
    # Either hard code a specific date, or use the below to dynamically
    #   grab the current date the app is ran
    "end_date": datetime.now().strftime('%Y-%m-%d'),

    # --- Initial Capital ---
    # No currency symbol or commas. Based in USD.
    "initial_capital": 100000.0,

    # ============================================================
    # SECTION 3: TIMEFRAME SERIES
    # ============================================================
    # Your Data Provider will dictate what's possible here.
    # For most providers the values can be swapped out based on
    #   'daily' or a specific time series. Refer to what is possible
    #   with your connected Data
    "timeframe": "D",  # Daily
    #"timeframe": "H",  # Hourly
    #"timeframe": "MIN",              # Use "D", "H", "MIN", "W", "M"
    #"timeframe_multiplier": 5,       # e.g., 1, 5, 15, 30 for minutes

    # ============================================================
    # SECTION 4: PRICE ADJUSTMENT & BENCHMARKS
    # ============================================================
    # For the majority of the time you'll want to use 'total_return'
    #   for a more realistic scenario.
    # Use a simple string for this setting. The service modules interpret it.
    "price_adjustment": "total_return", # Options: "total_return" or "none"

    # --- Benchmark Symbol ---
    # Pipe in a benchmark to compare the backtest to.
    # Based on 'buy and hold' comparison only.
    # Limited to one symbol.
    "benchmark_symbol": "SPY",

    # ============================================================
    # SECTION 5: FILE OUTPUT
    # ============================================================
    # Set to True to save a CSV of every trade for every profitable strategy.
    # Set to False to only save the final summary reports.
    "save_individual_trades": True,

    # ============================================================
    # SECTION 6: BACKTEST FILTERING SETTINGS
    # ============================================================
    # --- Monte Claro Filtering ---
    # Restrict simulations to show in the Report in the terminal
    #   and file saving to meet a specific Monte Carlo threshold.
    # To show all (no restrictions) set value to '-9999'.
    "mc_score_min_to_show_in_summary": -9999,
    
    # --- Calmar Filtering ---
    # Restrict simulations to show in the Report in the terminal
    #   and file saving to meet a specific Calmar threshold.
    # To show all (no restrictions) set value to '-9999'.
    # To show as a percentage, use a decimal value instead of
    #   a percentage, e.g., 4.0 for 4%
    # Comment out completely to not provide any filtering.

    #"min_calmar_to_show_in_summary": -9999,
    
    # --- P&L Filtering ---
    # Restrict simulations to show in the Report in the terminal
    #   and file saving to meet a specific P&L threshold.
    # To show all (no restrictions) set value to '-9999'.
    # To show as a percentage, use a decimal value instead of
    #   a percentage, e.g., 4.0 for 4%
    "min_pandl_to_show_in_summary": -9999,
    
    # --- Max Drawdown Filtering ---
    # Set this to 1.0 or higher to effectively disable the filter.
    # A strategy's drawdown is always a positive number (e.g., 0.25 for 25%).
    # The check is `max_drawdown <= max_acceptable_drawdown`,
    #   So `0.25 <= 1.0` is TRUE.
    "max_acceptable_drawdown": 1.0,

    # --- Benchmark Performance Filters ---
    # Enter as a percentage. e.g., 0.0 means "must beat benchmark", 
    #   -10.0 means "can lag by up to 10%".
    "min_performance_vs_spy": -9999,
    "min_performance_vs_qqq": -9999,

    # Either save all trades regardless if they fit within the 
    #   various params set forth in this file
    #   Or only save the filtered param strategy's results
    "save_only_filtered_trades": False, 

    # ============================================================
    # SECTION 7: PORTFOLIO SETTINGS
    # ============================================================
    # --- Single Asset Mode Settings ---
    # Trick the system into thinking you're testing an entire 
    #   portfolio by wrapping individual entries in brackets.
    #   e.g., ['BITB','BBAI', ...] or a single entry ['BBAI']
    "symbols_to_test": ['BITB'],
    
    # --- Portfolio Mode Settings ---
    # Inside the 'portfolios' object list the various baskets
    #   to iterate over. Comment out per each run when not in
    #   use so you can easily come back later if needed and
    #   not have to remember what basket is what. 
    # 
    # Declare an unlimited number of baskets for backtesting in a
    #   single run.
    #
    # Either declare a list of one or more tickers, e.g. 
    #   "BITB ETF": ["BITB"],
    #   or multiple tickers e.g.,
    #   "Semiconductors": ["NVDA", "AVGO", "QCOM", "AMD", ...],
    #   without having to save a separate JSON file of tickers
    #
    # If a JSON file exists of tickers, call the file directly e.g.,
    #   "Nasdaq": "nasdaq.json",
    #
    # For Norgate Data users:
    #   Norgate allows you to call the basket of tickers they package
    #   up nicely for you directly. Very handy. The rubric of that looks
    #   like the following:
    #   "Nasdaq Biotechnology": "norgate:Nasdaq Biotechnology",
    "portfolios": {
        "Nasdaq 100": "nasdaq_100.json",
        #"Nasdaq Biotech": "nasdaq_biotech_tickers.json",
        #"Russell 1000": "russell_1000.json",
    },

    # ============================================================
    # SECTION 8: ALLOCATION, EXECUTION FILTERING
    # ============================================================
    # --- Allocation Per Trade Settings ---
    # Percentage of total equity to allocate to each new position
    #   e.g., 10% for a max of 10 concurrent positions
    "allocation_per_trade": 0.10, 

    # --- Allocation Per Trade Settings ---
    # At what time do you want the fill to occur.
    # What's available may depend on your Data Provider.
    "execution_time":"open",

    # --- ROC Thresholds Settings ---
    "roc_thresholds": [0.0, 0.5],

    # --- Show QQQ Losers ---
    # Remove those simulations that couldn't beat the
    #   comparison of a simulation vs QQQ B&H
    "show_qqq_losers": False,

    # ============================================================
    # SECTION 9: STOP LOSS SETTINGS
    # ============================================================
    # Set as many variations for stops with your backtest.
    # Note: the more variations, the longer the backtest will take
    #   to perform.
    #
    # Supports "none", e.g.
    #   {"type": "none"}
    #
    # "percentage", e.g.,
    #   {"type": "percentage", "value": 0.03},
    #   {"type": "percentage", "value": 0.05},
    #   {"type": "percentage", "value": 0.10}, 
    #
    # and "atr" types of stops
    #   {"type": "atr", "period": 14, "multiplier": 3.0}
    "stop_loss_configs": [
        {"type": "none"},
    ],

    # ============================================================
    # SECTION 10: MONTE CARLO SETTINGS
    # ============================================================
    "min_trades_for_mc": 50,
    "num_mc_simulations": 1000,

    # ============================================================
    # SECTION 10: TRADING COST SETTINGS
    # ============================================================
    # --- Slippage Percentage ---
    "slippage_pct": 0.0005,
    
    # --- Commission Per Trade ---
    "commission_per_share": 0.002,
}

if CONFIG.get("data_provider") == "norgate":
    try:
        import norgatedata
        
        # Overwrite the string setting with the actual Norgate object
        if CONFIG["price_adjustment"] == "total_return":
            CONFIG["price_adjustment"] = norgatedata.StockPriceAdjustmentType.TOTALRETURN
        else:
            CONFIG["price_adjustment"] = norgatedata.StockPriceAdjustmentType.NONE
            
    except ImportError:
        # This will only be raised if the config is set to 'norgate' but the library isn't installed.
        raise ImportError("Configuration Error: data_provider is set to 'norgate', but the norgatedata package is not installed.")