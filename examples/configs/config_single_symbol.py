# examples/configs/config_single_symbol.py
"""
CONFIG EXAMPLE: Single-Symbol Quick Test
=========================================
Tests all active strategies against SPY using Yahoo Finance (free, no API key).

This is the fastest way to validate your setup. Expected runtime: ~30 seconds.

How to use:
    1. Copy this file to the project root as config.py:
           cp examples/configs/config_single_symbol.py config.py
    2. Run the backtester:
           python main.py

What to look for in the output:
    - The RUN SUMMARY box should show "Strategies: N" matching your plugin count
    - The terminal table shows P&L, Sharpe, Max DD, and MC Score for each strategy
    - Trade CSVs are saved to output/runs/<run_id>/
"""

from datetime import datetime

CONFIG = {
    # --- Data Provider ---
    # Yahoo Finance: free, no API key needed. Good for quick tests.
    "data_provider": "yahoo",

    # --- Backtest Period ---
    # 10 years of SPY data — enough for all default strategies to warm up.
    "start_date": "2015-01-01",
    "end_date": datetime.now().strftime("%Y-%m-%d"),

    # --- Capital ---
    "initial_capital": 100000.0,

    # --- What to Test ---
    # Single-asset mode: just SPY. Wrap in a portfolio dict so the engine
    # runs in portfolio mode (which is the primary execution path).
    "portfolios": {
        "Quick Test": ["SPY"],
    },

    # --- Timeframe ---
    "timeframe": "D",
    "timeframe_multiplier": 1,

    # --- Position Sizing ---
    "allocation_per_trade": 0.10,  # 10% of equity per position
    "max_pct_adv": 0.05,

    # --- Execution ---
    "execution_time": "open",

    # --- Stop Loss ---
    # No stop for this quick test. Add more entries to test multiple stops.
    "stop_loss_configs": [
        {"type": "none"},
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
    "wfa_folds": None,
    "wfa_min_fold_trades": 5,

    # --- Output ---
    "save_individual_trades": True,
    "save_only_filtered_trades": False,
    "upload_to_s3": False,

    # --- Filters (show everything) ---
    "mc_score_min_to_show_in_summary": -9999,
    "min_pandl_to_show_in_summary": -9999,
    "max_acceptable_drawdown": 1.0,
    "min_performance_vs_spy": -9999,
    "min_performance_vs_qqq": -9999,
    "show_qqq_losers": False,

    # --- Strategy Selection ---
    # "all" runs every registered plugin. Change to a list to test specific ones:
    #   "strategies": ["SMA Crossover (20d/50d)"],
    "strategies": "all",

    # --- Sweep & Extras (disabled for quick tests) ---
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
