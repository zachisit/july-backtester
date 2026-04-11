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
    # Options: "polygon", "norgate", "yahoo", "csv", "parquet"
    "data_provider": "norgate",

    # --- CSV Data Directory (only used when data_provider = "csv") ---
    # Path to the folder containing per-symbol CSV files.
    # Relative paths are resolved from the project root.
    # Each file must be named {SYMBOL}.csv (case-insensitive).
    # Required columns: Date, Open, High, Low, Close, Volume
    "csv_data_dir": "csv_data",

    # --- Parquet Data Directory (only used when data_provider = "parquet") ---
    # Path to the folder containing per-symbol Parquet files.
    # Relative paths are resolved from the project root.
    # Each file must be named {SYMBOL}.parquet (case-insensitive).
    # Required columns: Open, High, Low, Close, Volume with a DatetimeIndex.
    "parquet_data_dir": "parquet_data",

    # ============================================================
    # SECTION 2: BACKTEST PERIOD & CAPITAL
    # ============================================================
    # --- Start Date ---
    # Either set the specific start date, or set a time way in the past
    #   e.g. '1900-01-01' and the code will dynamically grab the last
    #   available start date from the Data Provider that you're using
    "start_date": "1990-01-01",
    
    # --- Start Date ---
    # Either hard code a specific date, or use the below to dynamically
    #   grab the current date the app is ran
    "end_date": datetime.now().strftime("%Y-%m-%d"),

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
    #
    # IMPORTANT: Changing to intraday timeframes (H, MIN) affects metric
    # calculations. Sharpe ratio, Sortino ratio, and other annualized metrics
    # are automatically adjusted based on bars-per-year:
    #   - Daily (D): 252 bars/year
    #   - Hourly (H): ~1,638 bars/year (252 × 6.5 hours)
    #   - 5-minute (MIN, multiplier=5): ~19,656 bars/year
    # HTB (short selling) fees are also compounded per bar instead of per day.
    "timeframe": "W",  # Weekly — Q25: Russell 2000 small-cap test
    #"timeframe": "H",  # Hourly
    #"timeframe": "MIN",              # Use "D", "H", "MIN", "W", "M"
    #"timeframe_multiplier": 5,       # e.g., 1, 5, 15, 30 for minutes
    #"timeframe": "W",  # Weekly
    #"timeframe": "M",  # Monthly

    # ============================================================
    # SECTION 4: PRICE ADJUSTMENT & BENCHMARKS
    # ============================================================
    # For the majority of the time you'll want to use 'total_return'
    #   for a more realistic scenario.
    # Use a simple string for this setting. The service modules interpret it.
    "price_adjustment": "total_return", # Options: "total_return" or "none"

    # --- Comparison Tickers ---
    # Controls which external symbols are fetched alongside your portfolio data.
    # Roles:
    #   "benchmark"  — shown as a B&H return column in the summary table
    #   "dependency" — injected into strategies that declare dependencies=["spy"] etc.
    #   "both"       — serves both roles
    # Set to [] to run with no comparison tickers (e.g. pure parquet runs where you
    # have no SPY/VIX files). The engine falls back to config start_date/end_date for
    # the period. Strategies declaring dependencies=["spy"] etc. will be skipped.
    "comparison_tickers": [
      #  {"symbol": "SPY",   "role": "both",       "label": "SPY"},
      #  {"symbol": "I:VIX", "role": "both", "label": "VIX"},
      #  {"symbol": "I:TNX", "role": "both", "label": "TNX"},
    ],

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
    # Add one or more named baskets to run. Each basket is independent
    #   and will appear as its own section in the output report.
    #
    # Single ticker:
    #   "AAPL": ["AAPL"],
    #
    # Multiple tickers:
    #   "Semiconductors": ["NVDA", "AVGO", "QCOM", "AMD"],
    #
    # JSON file (relative to project root):
    #   "Nasdaq 100": "nasdaq_100.json",
    #
    # Norgate watchlist:
    #   "Nasdaq Biotechnology": "norgate:Nasdaq Biotechnology",
    #
    # --- Minimum Bars Required ---
    # Symbols with fewer bars than this are skipped entirely.
    # 250 ≈ one year of daily data. Increase if your strategies need
    #   longer lookback periods (e.g. 200d SMA needs at least 200 bars).
    "min_bars_required": 250,

    "portfolios": {
        "Russell 2000": "russell-2000.json",
    },

    # ============================================================
    # SECTION 8: ALLOCATION, EXECUTION FILTERING
    # ============================================================
    # --- Allocation Per Trade Settings ---
    # Percentage of total equity to allocate to each new position
    #   e.g., 10% for a max of 10 concurrent positions
    "allocation_per_trade": 0.033,  # 3.3% per position — 5-strategy combined

    # --- Volume-Based Liquidity Filter ---
    # Maximum fraction of the 20-day Average Daily Volume (ADV) that a single
    # order is allowed to consume.  0.05 = no position may exceed 5 % of ADV.
    # Set to None or 0 to disable the filter entirely.
    "max_pct_adv": 0.05,

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
    # SECTION 11: WALK-FORWARD ANALYSIS (WFA)
    # ============================================================
    # Chronologically splits each strategy's trade history into an
    # In-Sample (IS) window and an Out-of-Sample (OOS) window to
    # test whether backtest results hold up on unseen data.
    #
    # wfa_split_ratio: fraction of the actual data period used for IS.
    #   0.80  → first 80 % of bars are IS, last 20 % are OOS (default)
    #   None or 0 → WFA disabled; OOS P&L and WFA Verdict show "N/A"
    "wfa_split_ratio": 0.80,

    # Rolling multi-fold WFA (opt-in — keep None for normal runs).
    # wfa_folds: None or 0 → disabled; int >= 2 → number of equal-width OOS folds.
    # wfa_min_fold_trades: minimum OOS trades required to score a fold.
    "wfa_folds": 3,
    "wfa_min_fold_trades": 5,

    # ============================================================
    # SECTION 12: TRADING COST SETTINGS
    # ============================================================
    # --- Slippage Percentage ---
    "slippage_pct": 0.0005,
    
    # --- Commission Per Trade ---
    "commission_per_share": 0.002,

    # --- Risk-Free Rate (annual) ---
    # Used in Sharpe ratio calculation. Default 5% per annum (US T-bill proxy).
    "risk_free_rate": 0.05,

    # ============================================================
    # SECTION 13: STRESS TESTING — PRICE NOISE INJECTION
    # ============================================================
    # Inject random noise into OHLC price data before running strategies.
    # 0.0 = disabled (default). 0.01 = ±1% uniform noise per bar per price.
    # Use this to test whether a strategy is robust to small data perturbations.
    "noise_injection_pct": 0.0,

    # ============================================================
    # SECTION 14: STRATEGY SELECTION
    # ============================================================
    # Controls which registered plugins are actually run.
    #
    # "all"  → run every strategy discovered in custom_strategies/  (default)
    #
    # list   → run only the named strategies, e.g.:
    #   "strategies": [
    #       "SMA Crossover (20d/50d)",
    #       "RSI Mean Reversion (14/30)",
    #       "EMA Crossover w/ SPY+VIX Filter",
    #   ],
    #
    # Names must match the 'name' argument passed to @register_strategy exactly
    # (case-sensitive). Any name not found in the registry logs a WARNING and is
    # skipped — a typo will not cause a crash.
    "strategies": ["MA Bounce (50d/3bar) + SMA200 Gate", "MA Confluence (10/20/50) Fast Exit", "Donchian Breakout (40/20)", "Price Momentum (6m ROC, 15pct) + SMA200", "RSI Weekly Trend (55-cross) + SMA200"],

    # ============================================================
    # SECTION 15: PARAMETER SENSITIVITY SWEEP
    # ============================================================
    # Automatically varies each numeric param in a strategy's @register_strategy
    # params dict by ±pct across ±steps steps, then prints a fragility verdict.
    # Opt-in only — keep disabled for normal runs (multiplies task count).
    "sensitivity_sweep_enabled": False,
    "sensitivity_sweep_pct": 0.20,        # ±20% per step
    "sensitivity_sweep_steps": 2,         # 2 steps each side → 5 values per param
    "sensitivity_sweep_min_val": 2,       # floor (prevents e.g. SMA period = 0)

    # ============================================================
    # SECTION 16: ROLLING METRICS
    # ============================================================
    "rolling_sharpe_window": 126,         # trading days (~6 months). 0 or None to disable.

    # ============================================================
    # SECTION 17: SHORT SELLING
    # ============================================================
    # Hard-To-Borrow annual rate debited daily from cash while a short is open.
    # 0.02 = 2% p.a. (easy-to-borrow large cap)
    # 0.10 = 10% p.a. (hard-to-borrow small/mid cap)
    # 0.0  = disable borrow cost
    "htb_rate_annual": 0.02,

    # ============================================================
    # SECTION 18: MONTE CARLO SAMPLING METHOD
    # ============================================================
    # "iid"   — current default: trades resampled independently (fast, ignores streaks)
    # "block" — block-bootstrap: samples consecutive blocks of trades, preserving
    #            win/loss autocorrelation and regime clustering.
    # mc_block_size: number of consecutive trades per block. None = auto (sqrt of trade count).
    "mc_sampling": "iid",
    "mc_block_size": None,

    # ============================================================
    # SECTION 19: VOLUME-BASED MARKET IMPACT SLIPPAGE
    # ============================================================
    # Adds a square-root market impact on top of slippage_pct.
    # impact_slippage = volume_impact_coeff * sqrt(shares / adv_20)
    # 0.0 = disabled (default). 0.1 = mild impact. 0.5 = aggressive.
    # Only fires when Volume data is available and adv_20 > 0.
    "volume_impact_coeff": 0.0,

    # ============================================================
    # SECTION 20: ML TRADE FEATURE EXPORT
    # ============================================================
    # When True, writes a consolidated Parquet file of all trades (all strategies,
    # all portfolios) to output/runs/<run_id>/ml_features.parquet after the run.
    # Requires pyarrow or fastparquet: pip install pyarrow
    "export_ml_features": False,

    # ============================================================
    # SECTION 21: VERBOSE SUMMARY TABLE
    # ============================================================
    # When False (default), terminal summary tables show a compact
    # 7-column view: Strategy, P&L (%), vs. SPY (B&H), Sharpe,
    # Max DD, MC Score, WFA Verdict.
    # When True, all 23 columns are displayed.
    # Override at runtime with: python main.py --verbose
    "verbose_output": True,
}

if CONFIG.get("data_provider") == "norgate":  # noqa: SIM102
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
