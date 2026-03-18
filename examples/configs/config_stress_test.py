# examples/configs/config_stress_test.py
"""
CONFIG EXAMPLE: Stress Test Configuration
==========================================
Tests strategy robustness with three stress-testing tools enabled:

1. Price Noise Injection (±1%) — adds random perturbations to OHLC data
   to see if your edge survives noisy real-world conditions.

2. Parameter Sensitivity Sweep — varies each numeric parameter ±20% to
   check whether results are fragile to small parameter changes.

3. Block-Bootstrap Monte Carlo — preserves win/loss streaks instead of
   shuffling trades independently, giving a more realistic robustness score
   for regime-dependent strategies.

Expected runtime:
    WARNING — this is slow by design. The sensitivity sweep multiplies
    your task count by 5^(number of numeric params). For a strategy with
    2 params, that's 25x. Combined with noise injection, expect 10-30
    minutes even on a small portfolio.

    Recommendation: test on 2-3 symbols first, then scale up.

How to use:
    1. Copy this file to the project root as config.py:
           cp examples/configs/config_stress_test.py config.py
    2. Run a dry-run to see the task count:
           python main.py --dry-run
    3. Run the stress test:
           python main.py --name "stress-test"

What to look for:
    - If a strategy's WFA Verdict flips from Pass to "Likely Overfitted"
      with noise enabled, it was curve-fitted to specific price levels.
    - If the Sensitivity Report shows "*** FRAGILE ***", the strategy is
      only profitable at very specific parameter values — likely overfit.
    - If block-bootstrap MC Score drops vs i.i.d. MC Score, the strategy
      has regime-dependent streaks that independent resampling was hiding.
"""

from datetime import datetime

CONFIG = {
    # --- Data Provider ---
    "data_provider": "yahoo",

    # --- Backtest Period ---
    "start_date": "2010-01-01",
    "end_date": datetime.now().strftime("%Y-%m-%d"),

    # --- Capital ---
    "initial_capital": 100000.0,

    # --- What to Test ---
    # Start small for stress tests. Scale up once you've validated.
    "portfolios": {
        "Stress Test": ["SPY", "QQQ", "AAPL"],
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
    "stop_loss_configs": [
        {"type": "none"},
    ],

    # --- Costs ---
    "slippage_pct": 0.0005,
    "commission_per_share": 0.002,
    "risk_free_rate": 0.05,

    # =============================================
    # STRESS TEST SETTINGS (the interesting part)
    # =============================================

    # --- 1. Price Noise Injection ---
    # Adds ±1% uniform random noise to every OHLC cell on every bar.
    # High/Low bounds are enforced after noise — no invalid candlesticks.
    # Set to 0.0 to disable.
    "noise_injection_pct": 0.01,

    # --- 2. Parameter Sensitivity Sweep ---
    # Varies each numeric param ±20% in 2 steps each side → 5 values per param.
    # A 2-param strategy generates a 25-point grid (5 × 5).
    "sensitivity_sweep_enabled": True,
    "sensitivity_sweep_pct": 0.20,    # ±20% per step
    "sensitivity_sweep_steps": 2,     # 2 steps each side
    "sensitivity_sweep_min_val": 2,   # Floor (prevents e.g. SMA period = 0)

    # --- 3. Block-Bootstrap Monte Carlo ---
    # Samples consecutive blocks of trades instead of independent draws.
    # Preserves win/loss streaks and regime clustering.
    "mc_sampling": "block",
    "mc_block_size": None,            # None = auto: floor(sqrt(N))

    # --- Monte Carlo ---
    "min_trades_for_mc": 50,
    "num_mc_simulations": 1000,

    # --- Walk-Forward Analysis ---
    # Enable rolling folds for a more rigorous overfitting check.
    "wfa_split_ratio": 0.80,
    "wfa_folds": 5,                   # 5-fold rolling WFA
    "wfa_min_fold_trades": 5,

    # --- Volume Impact (mild institutional model) ---
    "volume_impact_coeff": 0.1,

    # --- Output ---
    "save_individual_trades": True,
    "save_only_filtered_trades": False,
    "upload_to_s3": False,

    # --- Filters (show everything for stress tests) ---
    "mc_score_min_to_show_in_summary": -9999,
    "min_pandl_to_show_in_summary": -9999,
    "max_acceptable_drawdown": 1.0,
    "min_performance_vs_spy": -9999,
    "min_performance_vs_qqq": -9999,
    "show_qqq_losers": False,

    # --- Strategy Selection ---
    # Focus on a few strategies for stress testing:
    "strategies": [
        "SMA Crossover (20d/50d)",
        "SMA Crossover (50d/200d)",
    ],

    # --- Extras ---
    "export_ml_features": True,
    "rolling_sharpe_window": 126,
    "htb_rate_annual": 0.02,
    "price_adjustment": "total_return",
    "benchmark_symbol": "SPY",
    "min_bars_required": 250,
    "roc_thresholds": [0.0, 0.5],
}
