# examples/configs/config_nasdaq100.py
"""
CONFIG EXAMPLE: Nasdaq 100 Full Portfolio Run
==============================================
Runs all strategies against every stock in the Nasdaq 100 index.
Uses all CPU cores via multiprocessing.

Expected runtime:
    - First run:  10-30 minutes (data fetching + caching)
    - Repeat runs: 2-5 minutes  (data loaded from cache)

How to use:
    1. Copy this file to the project root as config.py:
           cp examples/configs/config_nasdaq100.py config.py
    2. Set your API key in .env (if using Polygon):
           echo "POLYGON_API_KEY=your_key_here" > .env
    3. Dry-run first to check task count:
           python main.py --dry-run
    4. Run the full backtest:
           python main.py --name "nasdaq100-sweep"

Tips:
    - Start with the --dry-run flag to see the total task count before committing.
    - With 22 strategies × 101 symbols × 1 stop config = ~2,222 tasks.
    - Results are saved to output/runs/<run_id>/overall_portfolio_summary.csv
"""

from datetime import datetime

CONFIG = {
    # --- Data Provider ---
    # Polygon gives the best data quality but requires a paid plan.
    # Switch to "yahoo" for free data (lower quality, but fine for research).
    "data_provider": "polygon",

    # --- Backtest Period ---
    # 20+ years of history for robust Walk-Forward Analysis.
    "start_date": "2004-01-01",
    "end_date": datetime.now().strftime("%Y-%m-%d"),

    # --- Capital ---
    "initial_capital": 100000.0,

    # --- What to Test ---
    # The nasdaq_100.json file ships with the repo in tickers_to_scan/.
    "portfolios": {
        "Nasdaq 100": "nasdaq_100.json",
    },

    # --- Timeframe ---
    "timeframe": "D",
    "timeframe_multiplier": 1,

    # --- Position Sizing ---
    "allocation_per_trade": 0.10,
    "max_pct_adv": 0.05,

    # --- Execution ---
    "execution_time": "open",

    # --- Stop Loss ---
    # Test both no-stop and a 5% fixed stop in the same run.
    # Note: this doubles the total task count.
    "stop_loss_configs": [
        {"type": "none"},
        # {"type": "percentage", "value": 0.05},
    ],

    # --- Costs ---
    "slippage_pct": 0.0005,
    "commission_per_share": 0.002,
    "risk_free_rate": 0.05,

    # --- Monte Carlo ---
    "min_trades_for_mc": 50,
    "num_mc_simulations": 1000,
    "mc_sampling": "iid",
    "mc_block_size": None,

    # --- Walk-Forward Analysis ---
    "wfa_split_ratio": 0.80,
    "wfa_folds": None,           # Set to 5 for rolling multi-fold WFA
    "wfa_min_fold_trades": 5,

    # --- Output ---
    "save_individual_trades": True,
    "save_only_filtered_trades": False,
    "upload_to_s3": False,
    "s3_reports_bucket": "",

    # --- Filters ---
    # Only show strategies that beat SPY and have MC score >= 3.
    "mc_score_min_to_show_in_summary": 3,
    "min_pandl_to_show_in_summary": 5.0,
    "max_acceptable_drawdown": 0.30,
    "min_performance_vs_spy": 0.0,
    "min_performance_vs_qqq": -9999,
    "show_qqq_losers": False,

    # --- Strategy Selection ---
    "strategies": "all",

    # --- Sweep & Extras ---
    "sensitivity_sweep_enabled": False,
    "sensitivity_sweep_pct": 0.20,
    "sensitivity_sweep_steps": 2,
    "sensitivity_sweep_min_val": 2,
    "noise_injection_pct": 0.0,
    "export_ml_features": False,
    "rolling_sharpe_window": 126,
    "volume_impact_coeff": 0.0,
    "htb_rate_annual": 0.02,
    "price_adjustment": "total_return",
    "benchmark_symbol": "SPY",
    "min_bars_required": 250,
    "roc_thresholds": [0.0, 0.5],
}
