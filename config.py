# config.py

from datetime import datetime
import numpy as np

CONFIG = {
    # --- S3 Bucket for Reports ---
    "s3_reports_bucket": "july-backtester-reports",

    # --- Data Provider Settings ---
    "data_provider": "polygon",  # Options: "norgate" or "polygon"

    "polygon_api_secret_name": "POLYGON_API_SECRET_NAME",

    # --- General Settings ---
    "start_date": "2004-01-01",
    #"start_date": "2025-06-13",
    "end_date": datetime.now().strftime('%Y-%m-%d'),
    "initial_capital": 100000.0,
    "timeframe": "D",  # Daily
    #"timeframe": "H",  # Hourly
    #"timeframe": "MIN",              # Use "D", "H", "MIN", "W", "M"
    #"timeframe_multiplier": 5,       # e.g., 1, 5, 15, 30 for minutes
    # Use a simple string for this setting. The service modules interpret it.
    "price_adjustment": "total_return", # Options: "total_return" or "none"
    "benchmark_symbol": "SPY",

    "trades_folder": "trades",
    "reports_folder": "reports", 
    # Set to True to save a CSV of every trade for every profitable strategy.
    # Set to False to only save the final summary reports.
    "save_individual_trades": True,

    # --- General Filtering Settings ---
    "mc_score_min_to_show_in_summary": -9999,
    #"mc_score_min_to_show_in_summary": 3,
    #"min_calmar_to_show_in_summary": -9999,
    #"min_calmar_to_show_in_summary": 0.0,
    # Enter this value as a percentage, e.g., 4.0 for 4%
    #"min_pandl_to_show_in_summary": 5.0, # 4.0 = 4%
    "min_pandl_to_show_in_summary": -9999, # 4.0 = 4%
    # To show all results regardless of P&L, set this to a large negative number
    #"min_pandl_to_show_in_summary": -9999.0, # A very large negative number effectively disables the filter
    # Set this to 1.0 or higher to effectively disable the filter.
    # A strategy's drawdown is always a positive number (e.g., 0.25 for 25%).
    # The check is `max_drawdown <= max_acceptable_drawdown`.
    # So `0.25 <= 1.0` is TRUE.
    "max_acceptable_drawdown": 1.0, 
    #"max_acceptable_drawdown": 0.25, 

    # --- Benchmark Performance Filters ---
    # Enter as a percentage. e.g., 0.0 means "must beat benchmark", -10.0 means "can lag by up to 10%".
    #"min_performance_vs_spy": 10,
    #"min_performance_vs_qqq": 10,
    "min_performance_vs_spy": -9999,
    "min_performance_vs_qqq": -9999,

    # Either save all trades regardless if they fit within the 
    #   various params set forth in this file
    #   Or only save the filtered param strategy's results
    "save_only_filtered_trades": False, 

    # --- Single Asset Mode Settings ---
    "symbols_to_test": ['BITB'],
    
    # --- Portfolio Mode Settings ---
    "portfolios": {
        # "BITB ETF": ["BITB"],
        # "bbai":["BBAI"],
        #"TechGiants": "tech_giants.json",
        # "Semiconductors": ["NVDA", "AVGO", "QCOM", "AMD", "INTC"],
        #"High_Vol": "high_volatility.json",
         "Nasdaq": "nasdaq.json",
        "Nasdaq 100 Tech": "nasdaq_100_tech.json",
        "Nasdaq 100": "nasdaq_100.json",
         #"Nasdaq Biotech": "nasdaq_biotech_tickers.json",
        #"NYSE": "nyse.json",
        #"Russell 1000": "russell_1000.json",
        # "Russell Micro": "russell_micro.json",
        # "Russell 2000": "russell-2000.json", 
        # "Russell 3000": "russell-3000.json", 
        #"Sectors": "sectors.json",
        #"Dow Jones": "dow-jones-industrial-average.json",
        #"SP 500": "sp-500.json",
        

        #"Stocks To Scan Original List of Tickers": "stocks_to_scan.json",


        # Norgate Only
        #"Dow Jones Industrials": "norgate:Dow Jones Industrial Average",
         #"Nasdaq 100 Technology Sector": "norgate:Nasdaq 100 Technology Sector",
        #  "Nasdaq Biotechnology": "norgate:Nasdaq Biotechnology",
        #  "Nasdaq Internet": "norgate:Nasdaq Internet",
        #  "Russell 1000": "norgate:Russell 1000",
        #  "S&P 100": "norgate:S&P 100",
        #  "NYSE Composite": "norgate:NYSE Composite",
         #"Sectors": "norgate:Sectors",

    },
    # % of total equity to allocate to each new position
    "allocation_per_trade": 0.10, # e.g., 10% for a max of 10 concurrent positions

    # --- Common Strategy Settings ---
    "roc_thresholds": [0.0, 0.5],
    "stop_loss_configs": [
        {"type": "none"},
        # {"type": "percentage", "value": 0.03},
        # {"type": "percentage", "value": 0.05},
        # {"type": "percentage", "value": 0.10},
        # {"type": "atr", "period": 14, "multiplier": 3.0}
    ],
    # "stop_loss_configs": [
    #     {"type": "none"},
    #     #{"type": "atr", "period": 14, "multiplier": 3.0}
    # ],
    "execution_time":"open",
    "show_qqq_losers":"false",

    # --- Monte Carlo Settings ---
    "min_trades_for_mc": 50,
    "num_mc_simulations": 1000,

    # --- Trading Cost Settings ---
    "slippage_pct": 0.0005,
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