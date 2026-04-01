# helpers/config_validator.py
"""
Config key validation — warns on unknown or typo'd keys in CONFIG.

Public API
----------
validate_config(config: dict) -> list[str]
    Returns a list of warning messages for unrecognised keys.
    Each message includes a "did you mean?" suggestion if a close match exists.
"""

import difflib
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known valid config keys — the canonical allowlist.
# Update this set when adding new config keys to config.py.
# ---------------------------------------------------------------------------

KNOWN_KEYS: set[str] = {
    # SECTION 1: Data Provider
    "data_provider",
    "csv_data_dir",
    # SECTION 2: Backtest Period & Capital
    "start_date",
    "end_date",
    "initial_capital",
    # SECTION 3: Timeframe
    "timeframe",
    "timeframe_multiplier",
    # SECTION 4: Price Adjustment & Benchmarks
    "price_adjustment",
    "benchmark_symbol",
    # SECTION 5: File Output
    "save_individual_trades",
    # SECTION 6: Filtering
    "mc_score_min_to_show_in_summary",
    "min_calmar_to_show_in_summary",
    "min_pandl_to_show_in_summary",
    "max_acceptable_drawdown",
    "min_performance_vs_spy",
    "min_performance_vs_qqq",
    "save_only_filtered_trades",
    "show_qqq_losers",
    # SECTION 7: Portfolio Settings
    "symbols_to_test",
    "portfolios",
    "min_bars_required",
    # SECTION 8: Allocation & Execution
    "allocation_per_trade",
    "max_pct_adv",
    "execution_time",
    "roc_thresholds",
    # SECTION 9: Stop Loss
    "stop_loss_configs",
    # SECTION 10: Monte Carlo
    "min_trades_for_mc",
    "num_mc_simulations",
    # SECTION 11: Walk-Forward Analysis
    "wfa_split_ratio",
    "wfa_folds",
    "wfa_min_fold_trades",
    # SECTION 12: Trading Costs
    "slippage_pct",
    "commission_per_share",
    "risk_free_rate",
    # SECTION 13: Stress Testing
    "noise_injection_pct",
    # SECTION 14: Strategy Selection
    "strategies",
    # SECTION 15: Sensitivity Sweep
    "sensitivity_sweep_enabled",
    "sensitivity_sweep_pct",
    "sensitivity_sweep_steps",
    "sensitivity_sweep_min_val",
    # SECTION 16: Rolling Metrics
    "rolling_sharpe_window",
    # SECTION 17: Short Selling
    "htb_rate_annual",
    # SECTION 18: MC Sampling
    "mc_sampling",
    "mc_block_size",
    # SECTION 19: Volume Impact
    "volume_impact_coeff",
    # SECTION 20: ML Export
    "export_ml_features",
    # SECTION 21: Verbose Summary Table
    "verbose_output",
    # SECTION 22: Position Sizing
    "position_sizing_method",
    "kelly_fraction",
    "target_risk_per_trade",
    "max_portfolio_heat",
    # S3
    "s3_reports_bucket",
    "upload_to_s3",
}


def validate_config(config: dict) -> list[str]:
    """
    Check config dict for keys not in the known allowlist.

    For each unknown key, uses difflib to suggest the closest known key
    if the match is close enough (cutoff 0.6).

    Parameters
    ----------
    config : dict
        The CONFIG dictionary from config.py.

    Returns
    -------
    list[str]
        List of warning message strings. Empty if all keys are valid.
    """
    warnings = []

    for key in config:
        if key not in KNOWN_KEYS:
            # Find close matches for a "did you mean?" suggestion
            close = difflib.get_close_matches(key, KNOWN_KEYS, n=1, cutoff=0.6)
            if close:
                msg = f"WARNING: unrecognised config key '{key}' -- did you mean '{close[0]}'?"
            else:
                msg = f"WARNING: unrecognised config key '{key}'"
            warnings.append(msg)
            logger.warning(msg)

    return warnings


def validate_intraday_config(config: dict) -> list[str]:
    """
    Validate intraday-specific configuration and warn about potential issues.

    Checks for intraday timeframes (H, MIN) and provides warnings about:
    - Metrics annualization (now supported via get_bars_per_year)
    - WFA compatibility (limited support - splits by calendar days)

    Parameters
    ----------
    config : dict
        The CONFIG dictionary from config.py.

    Returns
    -------
    list[str]
        List of info/warning message strings. Empty if using daily timeframe.
    """
    warnings = []
    timeframe = config.get("timeframe", "D").upper()

    if timeframe in ("H", "MIN"):
        multiplier = config.get("timeframe_multiplier", 1)
        tf_desc = f"{multiplier}{timeframe.lower()}" if multiplier != 1 else timeframe

        warnings.append(
            f"INFO: Intraday backtesting detected (timeframe={tf_desc}). "
            "Metrics (Sharpe, Sortino, HTB fees) are automatically adjusted for bars-per-year. "
            "WFA splits are calculated by bar count for accurate IS/OOS ratios. "
            "Ensure your data provider supports intraday data."
        )

    return warnings
