# config.py
# Momentum Rotation v2 — NASDAQ 100 cross-sectional weekly rotation

from datetime import datetime

CONFIG = {
    # ============================================================
    # SECTION 1: DATA PROVIDER
    # ============================================================
    "data_provider": "parquet",
    "parquet_data_dir": "parquet_data/data",

    # ============================================================
    # SECTION 2: BACKTEST PERIOD & CAPITAL
    # ============================================================
    "start_date": "1990-01-01",
    "end_date": datetime.now().strftime("%Y-%m-%d"),
    "initial_capital": 100000.0,

    # ============================================================
    # SECTION 3: TIMEFRAME
    # ============================================================
    "timeframe": "D",
    "timeframe_multiplier": 1,

    # ============================================================
    # SECTION 4: PRICE ADJUSTMENT & BENCHMARKS
    # ============================================================
    "price_adjustment": "none",
    "comparison_tickers": [
        {"symbol": "QQQ", "role": "both", "label": "QQQ"},
    ],

    # ============================================================
    # SECTION 5: FILE OUTPUT
    # ============================================================
    "save_individual_trades": True,

    # ============================================================
    # SECTION 6: FILTERING
    # ============================================================
    "mc_score_min_to_show_in_summary": -9999,
    "min_pandl_to_show_in_summary": -9999,
    "max_acceptable_drawdown": 1.0,
    "min_performance_vs_spy": -9999,
    "min_performance_vs_qqq": -9999,
    "save_only_filtered_trades": False,

    # ============================================================
    # SECTION 7: PORTFOLIO
    # ============================================================
    "min_bars_required": 250,
    "portfolios": {
        "NASDAQ 100 Momentum Rotation": "nasdaq_100.json",
    },

    # ============================================================
    # SECTION 8: ALLOCATION & EXECUTION
    # ============================================================
    "allocation_per_trade": 0.20,
    "max_pct_adv": 0.02,
    "execution_time": "open",
    "roc_thresholds": [0.0, 0.5],

    # ============================================================
    # SECTION 9: STOP LOSS
    # ============================================================
    "stop_loss_configs": [
        {"type": "none"},
    ],

    # ============================================================
    # SECTION 10: MONTE CARLO
    # ============================================================
    "min_trades_for_mc": 20,
    "num_mc_simulations": 1000,
    "mc_sampling": "iid",
    "mc_block_size": None,

    # ============================================================
    # SECTION 11: WALK-FORWARD ANALYSIS
    # ============================================================
    "wfa_split_ratio": 0.69,
    "wfa_folds": 5,
    "wfa_min_fold_trades": 3,

    # ============================================================
    # SECTION 12: TRADING COSTS
    # ============================================================
    "slippage_pct": 0.0005,
    "commission_per_share": 0.002,
    "risk_free_rate": 0.05,

    # ============================================================
    # SECTION 13: STRESS TESTING
    # ============================================================
    "noise_injection_pct": 0.0,

    # ============================================================
    # SECTION 14: STRATEGY SELECTION
    # ============================================================
    "strategies": "all",

    # ============================================================
    # SECTION 15: SENSITIVITY SWEEP
    # ============================================================
    "sensitivity_sweep_enabled": False,
    "sensitivity_sweep_pct": 0.20,
    "sensitivity_sweep_steps": 2,
    "sensitivity_sweep_min_val": 2,

    # ============================================================
    # SECTION 16: ROLLING METRICS & EXTRAS
    # ============================================================
    "rolling_sharpe_window": 126,
    "htb_rate_annual": 0.02,
    "volume_impact_coeff": 0.0,
    "export_ml_features": False,
    "verbose_output": True,
    "upload_to_s3": False,
    "s3_reports_bucket": "",

    # ============================================================
    # SECTION 22: REALIZED-ONLY REPORTING
    # ============================================================
    "exclude_open_positions": False,

    # ============================================================
    # SECTION 23: SURVIVORSHIP BIAS
    # ============================================================
    # Include delisted/failed companies in backtests to avoid survivorship bias.
    # Only Norgate and Polygon support delisting data.
    # Yahoo and CSV providers will log a warning if enabled.
    "include_delisted": False,

    # How to price force-closed positions when a stock is delisted:
    # "last_close" — use the last known Close price (default, realistic)
    # "zero" — assume total loss (conservative, stress-test scenario)
    "delisting_price_assumption": "last_close",
}
