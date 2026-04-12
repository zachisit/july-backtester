# helpers/summary.py

import pandas as pd
import os
from config import CONFIG
import numpy as np

from helpers.aws_utils import upload_file_to_s3
from helpers.correlation import compute_avg_correlations, DEFAULT_THRESHOLD

# ---------------------------------------------------------------------------
# Benchmark Column Builder
# ---------------------------------------------------------------------------
def _build_benchmark_columns(benchmark_returns):
    """Build dynamic benchmark column mappings from benchmark_returns dict.

    Parameters
    ----------
    benchmark_returns : dict
        Dictionary of benchmark labels to their returns, e.g., {"SPY": 0.123, "QQQ": 0.456}

    Returns
    -------
    dict
        {
            "result_keys": ["vs_spy_benchmark", "vs_qqq_benchmark", ...],
            "display_names": {"vs_spy_benchmark": "vs. SPY (B&H)", ...},
            "format_spec": {"vs_spy_benchmark": "{:+.2%}", ...},
            "short_names": {"vs. SPY (B&H)": "vs. SPY", ...},
        }
    """
    result_keys = []
    display_names = {}
    format_spec = {}
    short_names = {}

    for label in benchmark_returns.keys():
        # Result key: vs_spy_benchmark, vs_qqq_benchmark, vs_financials_benchmark
        key = f'vs_{label.lower().replace(" ", "_")}_benchmark'
        # Display name: vs. SPY (B&H), vs. QQQ (B&H), vs. Financials (B&H)
        display = f'vs. {label} (B&H)'
        # Short name for verbose tables: vs. SPY, vs. QQQ, vs. Financials
        short = f'vs. {label}'

        result_keys.append(key)
        display_names[key] = display
        format_spec[key] = "{:+.2%}"
        short_names[display] = short

    return {
        "result_keys": result_keys,
        "display_names": display_names,
        "format_spec": format_spec,
        "short_names": short_names,
    }


# ---------------------------------------------------------------------------
# Table column definitions for tiered terminal output.
# Table 1 is always shown; Tables 2 and 3 only appear with --verbose.
# Strategy is the join key and appears in every table.
#
# NOTE: Benchmark columns (vs. SPY, vs. QQQ, etc.) are dynamically injected
# by each summary function based on the benchmark_returns dict passed to it.
# ---------------------------------------------------------------------------
def _get_t1_cols(benchmark_columns):
    """Get Table 1 columns with first benchmark dynamically injected."""
    if benchmark_columns["result_keys"]:
        first_benchmark = benchmark_columns["display_names"][benchmark_columns["result_keys"][0]]
        return ['Strategy', 'P&L (%)', first_benchmark, 'Sharpe', 'Max DD', 'MC Score', 'WFA Verdict']
    else:
        return ['Strategy', 'P&L (%)', 'Sharpe', 'Max DD', 'MC Score', 'WFA Verdict']

def _get_t2_cols(benchmark_columns):
    """Get Table 2 columns with remaining benchmarks dynamically injected."""
    # Include all benchmarks except the first (which is in T1)
    extra_benchmarks = [benchmark_columns["display_names"][k] for k in benchmark_columns["result_keys"][1:]]
    return (['Strategy'] + extra_benchmarks +
            ['Calmar', 'Roll.Sharpe(avg)', 'Roll.Sharpe(min)', 'Roll.Sharpe(last)',
             'Max Rcvry (d)', 'Avg Rcvry (d)', 'Profit Factor', 'Win Rate', 'Trades',
             'Expectancy (R)', 'SQN', 'Delisted Pos', 'Delisting Loss (%)'])

_T3_COLS = ['Strategy', 'OOS P&L (%)', 'WFA Verdict', 'Rolling WFA',
            'Avg. Corr', 'MC Verdict', 'MC Score']

# Short display names for verbose tables only (T2 and T3).
# Core Performance (T1) headers are already short and stay unchanged.
# Benchmark short names are dynamically added by _build_benchmark_columns().
_VERBOSE_SHORT_NAMES = {
    'Roll.Sharpe(avg)':    'RS(avg)',
    'Roll.Sharpe(min)':    'RS(min)',
    'Roll.Sharpe(last)':   'RS(last)',
    'Max Rcvry (d)':       'MaxRcvry',
    'Avg Rcvry (d)':       'AvgRcvry',
    'Profit Factor':       'PF',
    'Win Rate':            'WinRate',
    'Expectancy (R)':      'Expct(R)',
    'OOS P&L (%)':         'OOS P&L',
    'Rolling WFA':         'RollWFA',
    'Avg. Corr':           'Corr',
    'MC Verdict':          'MC',
    'Delisted Pos':        'Delist',
    'Delisting Loss (%)':  'DelistL%',
}


def _print_table(df, title):
    """Print a DataFrame as a bordered terminal table with visible dividers."""
    if df.empty:
        return
    col_widths = {col: max(len(col), df[col].astype(str).str.len().max())
                  for col in df.columns}
    row_width = sum(col_widths.values()) + 3 * (len(df.columns) - 1)
    divider = "-" * row_width
    header = "   ".join(col.ljust(col_widths[col]) for col in df.columns)
    print(f"\n{title}")
    print(divider)
    print(header)
    print(divider)
    for _, row in df.iterrows():
        print("   ".join(str(row[col]).ljust(col_widths[col]) for col in df.columns))
    print(divider)


def save_trades_to_csv(result, local_folder, run_id):
    """Saves the trade log locally and optionally uploads it to S3."""
    if not result.get('trade_log') or result.get('Trades', 0) == 0:
        return
    
    # Sanitize names for filenames/paths
    strategy_name_safe = result['Strategy'].replace('/', '_').replace(' ', '_').replace('(', '').replace(')', '').replace(':', '')
    portfolio_name_safe = result.get('Portfolio', 'Portfolio').replace(" ", "_")
    symbol = result.get('Asset', portfolio_name_safe)

    filename = f"{symbol}_{strategy_name_safe}_trade_log.csv"
    local_filepath = os.path.join(local_folder, filename)

    try:
        pd.DataFrame(result['trade_log']).to_csv(local_filepath, index=False)

        # Upload to S3 if enabled
        s3_bucket = CONFIG.get("s3_reports_bucket")
        if CONFIG.get("upload_to_s3") and s3_bucket:
            s3_key = f"{run_id}/{portfolio_name_safe}/trades/{filename}"
            upload_file_to_s3(local_filepath, s3_bucket, s3_key)

    except Exception as e:
        print(f"  -> WARNING: Could not save trade log for {strategy_name_safe}. Error: {e}")
        
def generate_single_asset_summary_report(symbol_results, benchmark_returns, symbol, symbol_trades_folder, run_id):
    """
    Prints the per-symbol summary and saves all profitable trade logs.

    Parameters
    ----------
    benchmark_returns : dict
        Dictionary of benchmark labels to their returns, e.g., {"SPY": 0.123, "QQQ": 0.456}
    """
    # Build dynamic benchmark column mappings
    benchmark_columns = _build_benchmark_columns(benchmark_returns)

    print("\n\n" + "=" * 80)
    print(f"Strategy Performance Summary for: {symbol}".center(80))
    print(f"Timeframe: {CONFIG['timeframe']} | Period: {CONFIG['start_date']} to {CONFIG['end_date']}".center(80))
    print("=" * 80)
    for label, ret in benchmark_returns.items():
        print(f"Benchmark ({label}) Buy & Hold Return: {ret:.2%}".center(80))
    print("=" * 80)
    
    if not symbol_results:
        print(f"\nNo successful strategy results to display for {symbol}.")
        return

    summary_df = pd.DataFrame(symbol_results)
    max_dd_filter = CONFIG.get("max_acceptable_drawdown", 1.0)
    mc_score_min = CONFIG.get("mc_score_min_to_show_in_summary", -999)
    min_pnl = CONFIG.get("min_pandl_to_show_in_summary", -999.0)
    min_calmar = CONFIG.get("min_calmar_to_show_in_summary", -999.0)

    # Build filter mask
    filter_mask = (
        (summary_df['max_drawdown'] <= max_dd_filter) &
        (summary_df['mc_score'] >= mc_score_min) &
        (summary_df['pnl_percent'] * 100 >= min_pnl) &
        (summary_df['calmar_ratio'] >= min_calmar)
    )

    # Dynamic benchmark filtering (legacy keys apply to first 2 benchmarks)
    benchmark_filter_msgs = []
    for idx, result_key in enumerate(benchmark_columns["result_keys"]):
        if idx == 0:
            min_perf = CONFIG.get("min_performance_vs_spy", -9999.0)
            label = list(benchmark_returns.keys())[0]
        elif idx == 1:
            min_perf = CONFIG.get("min_performance_vs_qqq", -9999.0)
            label = list(benchmark_returns.keys())[1]
        else:
            min_perf = -9999.0
            label = list(benchmark_returns.keys())[idx]

        if result_key in summary_df.columns:
            filter_mask &= (summary_df[result_key] * 100 >= min_perf)
            benchmark_filter_msgs.append(f"vs {label} >= {min_perf:.2f}%")

    filtered_df = summary_df[filter_mask].copy()

    if filtered_df.empty:
        print(f"\nNo strategies for {symbol} met the required criteria.")
        filter_msg = (f"(Filters: Max DD < {max_dd_filter:.0%}, Min MC Score >= {mc_score_min}, "
                      f"Min P&L >= {min_pnl:.2f}%, Min Calmar >= {min_calmar:.2f}")
        if benchmark_filter_msgs:
            filter_msg += ", " + ", ".join(benchmark_filter_msgs)
        filter_msg += ")"
        print(filter_msg)
    else:
        # Formatting logic (dynamic benchmark columns)
        format_map = [
            ('pnl_percent', "{:.2%}"), ('max_drawdown', "{:.2%}"), ('win_rate', "{:.2%}"),
            ('calmar_ratio', "{:.2f}"), ('sharpe_ratio', "{:.2f}"), ('profit_factor', "{:.2f}"),
            ('oos_pnl_pct', "{:+.2%}"), ('expectancy', "{:.3f}"), ('sqn', "{:.2f}"),
            ('rolling_sharpe_mean', "{:.2f}"), ('rolling_sharpe_min', "{:.2f}"),
            ('rolling_sharpe_final', "{:.2f}"), ('avg_recovery_days', "{:.0f}")
        ]
        for result_key in benchmark_columns["result_keys"]:
            format_map.append((result_key, benchmark_columns["format_spec"][result_key]))

        for col, f_str in format_map:
            if col in filtered_df.columns:
                filtered_df[col] = filtered_df[col].apply(lambda x: f_str.format(x) if isinstance(x, (int, float)) else x)

        if 'avg_trade_duration' in filtered_df.columns:
            filtered_df['avg_trade_duration'] = filtered_df['avg_trade_duration'].apply(
                lambda x: int(np.ceil(x)) if pd.notna(x) and isinstance(x, (int, float)) else x
            )

        # Dynamic column renaming
        rename_map = {
            'pnl_percent': 'P&L (%)', 'max_drawdown': 'Max DD', 'calmar_ratio': 'Calmar',
            'sharpe_ratio': 'Sharpe', 'profit_factor': 'Profit Factor', 'win_rate': 'Win Rate',
            'avg_trade_duration': 'Avg. Hold (d)', 'mc_verdict': 'MC Verdict', 'mc_score': 'MC Score',
            'oos_pnl_pct': 'OOS P&L (%)', 'wfa_verdict': 'WFA Verdict',
            'wfa_rolling_verdict': 'Rolling WFA', 'expectancy': 'Expectancy (R)', 'sqn': 'SQN',
            'rolling_sharpe_mean': 'Roll.Sharpe(avg)', 'rolling_sharpe_min': 'Roll.Sharpe(min)',
            'rolling_sharpe_final': 'Roll.Sharpe(last)',
            'max_recovery_days': 'Max Rcvry (d)', 'avg_recovery_days': 'Avg Rcvry (d)',
        }
        rename_map.update(benchmark_columns["display_names"])
        filtered_df.rename(columns=rename_map, inplace=True)

        # Dynamic report columns
        benchmark_display_names = [benchmark_columns["display_names"][k] for k in benchmark_columns["result_keys"]]
        report_cols = (['Strategy', 'P&L (%)'] + benchmark_display_names +
                      ['Max DD', 'Max Rcvry (d)', 'Avg Rcvry (d)', 'Calmar', 'Sharpe',
                       'Roll.Sharpe(avg)', 'Roll.Sharpe(min)', 'Roll.Sharpe(last)',
                       'Profit Factor', 'Win Rate', 'Avg. Hold (d)', 'Trades',
                       'Expectancy (R)', 'SQN', 'OOS P&L (%)', 'WFA Verdict', 'Rolling WFA',
                       'MC Verdict', 'MC Score'])

        summary_df_display = filtered_df.reindex(columns=report_cols).fillna('N/A').sort_values(by='MC Score', ascending=False).reset_index(drop=True)

        # Dynamic table columns
        _t1 = [c for c in _get_t1_cols(benchmark_columns) if c in summary_df_display.columns]
        _print_table(summary_df_display[_t1], f"--- Core Performance: {symbol} ---")

        if CONFIG.get("verbose_output", False):
            verbose_short_names = {**_VERBOSE_SHORT_NAMES, **benchmark_columns["short_names"]}
            _t2 = [c for c in _get_t2_cols(benchmark_columns) if c in summary_df_display.columns]
            if len(_t2) > 1:
                _print_table(summary_df_display[_t2].rename(columns=verbose_short_names), "--- Extended Metrics ---")
            _t3 = [c for c in _T3_COLS if c in summary_df_display.columns]
            if len(_t3) > 1:
                _print_table(summary_df_display[_t3].rename(columns=verbose_short_names), "--- Robustness ---")
        else:
            print("\n  Run with --verbose for extended metrics and robustness scores.")
    
    if CONFIG.get("save_individual_trades", False):
        print("\n" + "-" * 80)
        s3_enabled = CONFIG.get("upload_to_s3") and CONFIG.get("s3_reports_bucket")
        action = "Saving and uploading" if s3_enabled else "Saving"
        print(f"{action} profitable trade logs for {symbol}...")
        profitable_strategies = pd.DataFrame(symbol_results)[pd.DataFrame(symbol_results)['pnl_percent'] > 0]
        if profitable_strategies.empty:
            print(f"No profitable strategies found for {symbol}.")
        else:
            for index, row in profitable_strategies.iterrows():
                full_result_dict = next((r for r in symbol_results if r['Strategy'] == row['Strategy']), None)
                if full_result_dict:
                    save_trades_to_csv(full_result_dict, symbol_trades_folder, run_id)
            done_action = "Saved and uploaded" if s3_enabled else "Saved"
            print(f"{done_action} {len(profitable_strategies)} trade logs.")
        print("-" * 80)
    else:
        print(f"\nSkipping individual trade log saving for {symbol} as per config.")

def generate_final_summary(all_results, benchmark_returns):
    """
    Generates the final summary for the single-asset mode.

    Parameters
    ----------
    benchmark_returns : dict
        Dictionary of benchmark labels to their returns, e.g., {"SPY": 0.123, "QQQ": 0.456}
    """
    # Build dynamic benchmark column mappings
    benchmark_columns = _build_benchmark_columns(benchmark_returns)

    print("\n\n" + "=" * 80)
    print("Overall Top 5 Single-Asset Strategies".center(80))
    print("=" * 80)
    if not all_results:
        print("\nNo results to summarize.")
        return

    summary_df = pd.DataFrame(all_results)
    mc_score_min = CONFIG.get("mc_score_min_to_show_in_summary", -999)
    min_pnl = CONFIG.get("min_pandl_to_show_in_summary", -999.0)
    min_calmar = CONFIG.get("min_calmar_to_show_in_summary", -999.0)
    max_dd_filter = CONFIG.get("max_acceptable_drawdown", -9999.0)
    min_trades = CONFIG.get("min_trades_for_mc", 15)

    # Build filter mask
    filter_mask = (
        (summary_df['Trades'] >= min_trades) &
        (summary_df['max_drawdown'] <= max_dd_filter) &
        (summary_df['mc_score'] >= mc_score_min) &
        (summary_df['pnl_percent'] * 100 >= min_pnl) &
        (summary_df['calmar_ratio'] >= min_calmar)
    )

    # Dynamic benchmark filtering
    benchmark_filter_msgs = []
    for idx, result_key in enumerate(benchmark_columns["result_keys"]):
        if idx == 0:
            min_perf = CONFIG.get("min_performance_vs_spy", -9999.0)
            label = list(benchmark_returns.keys())[0]
        elif idx == 1:
            min_perf = CONFIG.get("min_performance_vs_qqq", -9999.0)
            label = list(benchmark_returns.keys())[1]
        else:
            min_perf = -9999.0
            label = list(benchmark_returns.keys())[idx]

        if result_key in summary_df.columns:
            filter_mask &= (summary_df[result_key] * 100 >= min_perf)
            benchmark_filter_msgs.append(f"vs {label} >= {min_perf:.2f}%")

    filtered_df = summary_df[filter_mask].copy()

    if filtered_df.empty:
        print("\nNo strategies met the final criteria.")
        filter_msg = (f"(Filters: Min Trades >= {min_trades}, Max DD < {max_dd_filter:.0%}, "
                      f"Min MC Score >= {mc_score_min}, Min P&L >= {min_pnl:.2f}%, "
                      f"Min Calmar >= {min_calmar:.2f}")
        if benchmark_filter_msgs:
            filter_msg += ", " + ", ".join(benchmark_filter_msgs)
        filter_msg += ")"
        print(filter_msg)
        return
        
    final_df = filtered_df.sort_values(by='mc_score', ascending=False).head(5).reset_index(drop=True)

    # Formatting logic (dynamic benchmark columns)
    format_map = [
        ('pnl_percent', "{:.2%}"), ('max_drawdown', "{:.2%}"), ('win_rate', "{:.2%}"),
        ('calmar_ratio', "{:.2f}"), ('sharpe_ratio', "{:.2f}"), ('profit_factor', "{:.2f}"),
        ('oos_pnl_pct', "{:+.2%}"), ('expectancy', "{:.3f}"), ('sqn', "{:.2f}"),
        ('rolling_sharpe_mean', "{:.2f}"), ('rolling_sharpe_min', "{:.2f}"),
        ('rolling_sharpe_final', "{:.2f}"), ('avg_recovery_days', "{:.0f}")
    ]
    for result_key in benchmark_columns["result_keys"]:
        format_map.append((result_key, benchmark_columns["format_spec"][result_key]))

    for col, f_str in format_map:
        if col in final_df.columns:
            final_df[col] = final_df[col].apply(lambda x: f_str.format(x) if isinstance(x, (int, float)) else x)

    if 'avg_trade_duration' in final_df.columns:
        final_df['avg_trade_duration'] = final_df['avg_trade_duration'].apply(
            lambda x: int(np.ceil(x)) if pd.notna(x) and isinstance(x, (int, float)) else x
        )

    # Dynamic column renaming
    rename_map = {
        'Asset': 'Symbol', 'pnl_percent': 'P&L (%)', 'max_drawdown': 'Max DD', 'calmar_ratio': 'Calmar',
        'sharpe_ratio': 'Sharpe', 'profit_factor': 'Profit Factor', 'win_rate': 'Win Rate',
        'avg_trade_duration': 'Avg. Hold (d)', 'mc_verdict': 'MC Verdict', 'mc_score': 'MC Score',
        'oos_pnl_pct': 'OOS P&L (%)', 'wfa_verdict': 'WFA Verdict', 'wfa_rolling_verdict': 'Rolling WFA',
        'expectancy': 'Expectancy (R)', 'sqn': 'SQN',
        'rolling_sharpe_mean': 'Roll.Sharpe(avg)', 'rolling_sharpe_min': 'Roll.Sharpe(min)',
        'rolling_sharpe_final': 'Roll.Sharpe(last)',
        'max_recovery_days': 'Max Rcvry (d)', 'avg_recovery_days': 'Avg Rcvry (d)',
    }
    rename_map.update(benchmark_columns["display_names"])
    final_df.rename(columns=rename_map, inplace=True)

    # Dynamic report columns
    benchmark_display_names = [benchmark_columns["display_names"][k] for k in benchmark_columns["result_keys"]]
    report_cols = (['Symbol', 'Strategy', 'P&L (%)'] + benchmark_display_names +
                  ['Max DD', 'Max Rcvry (d)', 'Avg Rcvry (d)', 'Calmar', 'Sharpe',
                   'Roll.Sharpe(avg)', 'Roll.Sharpe(min)', 'Roll.Sharpe(last)',
                   'Profit Factor', 'Win Rate', 'Avg. Hold (d)', 'Trades',
                   'Expectancy (R)', 'SQN', 'OOS P&L (%)', 'WFA Verdict', 'Rolling WFA',
                   'MC Verdict', 'MC Score'])

    final_df_display = final_df.reindex(columns=report_cols).fillna('N/A')

    print("\nBased on all filters, the most promising single-asset combinations are:")
    _pfx = ['Symbol'] if 'Symbol' in final_df_display.columns else []
    _t1_cols = _get_t1_cols(benchmark_columns)
    _t1 = list(dict.fromkeys(_pfx + [c for c in _t1_cols if c in final_df_display.columns]))
    _print_table(final_df_display[_t1], "--- Core Performance ---")

    if CONFIG.get("verbose_output", False):
        verbose_short_names = {**_VERBOSE_SHORT_NAMES, **benchmark_columns["short_names"]}
        _t2_cols = _get_t2_cols(benchmark_columns)
        _t2 = list(dict.fromkeys(_pfx + [c for c in _t2_cols if c in final_df_display.columns]))
        if len(_t2) > len(_pfx) + 1:
            _print_table(final_df_display[_t2].rename(columns=verbose_short_names), "--- Extended Metrics ---")
        _t3 = list(dict.fromkeys(_pfx + [c for c in _T3_COLS if c in final_df_display.columns]))
        if len(_t3) > len(_pfx) + 1:
            _print_table(final_df_display[_t3].rename(columns=verbose_short_names), "--- Robustness ---")
    else:
        print("\n  Run with --verbose for extended metrics and robustness scores.")
    
    try:
        output_dir = "output"
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, "top_5_single_asset_summary.csv")
        final_df_display.to_csv(filepath, index=False)
        print(f"\nSuccessfully saved top 5 single-asset summary to '{filepath}'")
    except Exception as e:
        print(f"\n  -> WARNING: Could not save the top 5 single-asset summary. Error: {e}")

    print("\n" + "=" * 80)

def generate_per_portfolio_summary(portfolio_results, portfolio_name, benchmark_returns, run_id, corr_matrix=None):
    """
    Prints the per-portfolio strategy summary and saves all trade logs.

    Parameters
    ----------
    benchmark_returns : dict
        Dictionary of benchmark labels to their returns, e.g., {"SPY": 0.123, "QQQ": 0.456}
    """
    # Build dynamic benchmark column mappings
    benchmark_columns = _build_benchmark_columns(benchmark_returns)

    print("\n\n" + "=" * 80)
    print(f"Strategy Performance Summary for Portfolio: {portfolio_name}".center(80))
    print("=" * 80)
    for label, ret in benchmark_returns.items():
        print(f"Benchmark ({label}) Buy & Hold Return: {ret:.2%}".center(80))
    print("=" * 80)

    if not portfolio_results:
        print(f"\nNo successful strategy results to display for {portfolio_name}.")
        return

    # --- Step 1: Create the main DataFrame from ALL results ---
    summary_df = pd.DataFrame(portfolio_results).copy()

    # --- Step 2: Create a separate, FILTERED DataFrame for DISPLAY purposes only ---
    # Legacy config keys (min_performance_vs_spy, min_performance_vs_qqq) are still supported for backward compatibility
    # They apply to the first two benchmarks if present
    max_dd_filter = CONFIG.get("max_acceptable_drawdown", 1.0)
    mc_score_min = CONFIG.get("mc_score_min_to_show_in_summary", -999)
    min_pnl = CONFIG.get("min_pandl_to_show_in_summary", -999.0)
    min_calmar = CONFIG.get("min_calmar_to_show_in_summary", -999.0)

    # Build filter conditions
    filter_mask = (
        (summary_df['Trades'] > 0) &
        (summary_df['max_drawdown'] <= max_dd_filter) &
        (summary_df['mc_score'] >= mc_score_min) &
        (summary_df['pnl_percent'] * 100 >= min_pnl) &
        (summary_df['calmar_ratio'] >= min_calmar)
    )

    # Dynamic benchmark filtering (legacy keys apply to first 2 benchmarks)
    benchmark_filter_msgs = []
    for idx, result_key in enumerate(benchmark_columns["result_keys"]):
        if idx == 0:
            # First benchmark: check min_performance_vs_spy for backward compatibility
            min_perf = CONFIG.get("min_performance_vs_spy", -9999.0)
            label = list(benchmark_returns.keys())[0]
        elif idx == 1:
            # Second benchmark: check min_performance_vs_qqq for backward compatibility
            min_perf = CONFIG.get("min_performance_vs_qqq", -9999.0)
            label = list(benchmark_returns.keys())[1]
        else:
            # Additional benchmarks: no legacy config key, default to -9999.0
            min_perf = -9999.0
            label = list(benchmark_returns.keys())[idx]

        if result_key in summary_df.columns:
            filter_mask &= (summary_df[result_key] * 100 >= min_perf)
            benchmark_filter_msgs.append(f"vs {label} >= {min_perf:.2f}%")

    display_df = summary_df[filter_mask].copy()

    # Capture the set of strategy names that passed the display filter for use in Step 4b.
    passed_display_filter = set(display_df['Strategy'].tolist())

    # --- Step 3: Use the filtered display_df to show the summary table ---
    if display_df.empty:
        print(f"\nNo strategies for {portfolio_name} met the required display criteria.")
        filter_msg = (f"(Filters: Min Trades > 0, Max DD < {max_dd_filter:.0%}, "
                      f"Min MC Score >= {mc_score_min}, Min P&L >= {min_pnl:.2f}%, "
                      f"Min Calmar >= {min_calmar:.2f}")
        if benchmark_filter_msgs:
            filter_msg += ", " + ", ".join(benchmark_filter_msgs)
        filter_msg += ")"
        print(filter_msg)
    else:
        # --- Avg. Corr column (from pre-computed correlation matrix) ---
        if corr_matrix is not None and not corr_matrix.empty:
            avg_corrs = compute_avg_correlations(corr_matrix)
            # Build flag: True if any off-diagonal |r| > threshold for that strategy
            high_corr_strategies = set()
            for col in corr_matrix.columns:
                for other in corr_matrix.columns:
                    if other != col:
                        val = corr_matrix.loc[col, other]
                        if pd.notna(val) and abs(val) > DEFAULT_THRESHOLD:
                            high_corr_strategies.add(col)
                            break

            def _fmt_avg_corr(strategy_name):
                val = avg_corrs.get(strategy_name)
                if val is None or (isinstance(val, float) and np.isnan(val)):
                    return 'N/A'
                flag = '*' if strategy_name in high_corr_strategies else ''
                return f"{val:.2f}{flag}"

            display_df['avg_corr'] = display_df['Strategy'].apply(_fmt_avg_corr)
        else:
            display_df['avg_corr'] = 'N/A'

        # Sort by numeric mc_score BEFORE the formatting loop converts it to a string.
        display_df.sort_values(by='mc_score', ascending=False, inplace=True)
        display_df.reset_index(drop=True, inplace=True)

        # Formatting logic (dynamic benchmark columns)
        format_map = [
            ('pnl_percent', "{:.2%}"), ('max_drawdown', "{:.2%}"), ('win_rate', "{:.2%}"),
            ('calmar_ratio', "{:.2f}"), ('sharpe_ratio', "{:.2f}"), ('profit_factor', "{:.2f}"),
            ('oos_pnl_pct', "{:+.2%}"), ('expectancy', "{:.3f}"), ('sqn', "{:.2f}"),
            ('rolling_sharpe_mean', "{:.2f}"), ('rolling_sharpe_min', "{:.2f}"),
            ('rolling_sharpe_final', "{:.2f}"), ('avg_recovery_days', "{:.0f}"),
            ('delisting_loss_pct', "{:.2%}")
        ]
        # Add all benchmark columns with their format specs
        for result_key in benchmark_columns["result_keys"]:
            format_map.append((result_key, benchmark_columns["format_spec"][result_key]))

        for col, f_str in format_map:
            if col in display_df.columns:
                display_df[col] = display_df[col].apply(lambda x: f_str.format(x) if isinstance(x, (int, float)) else x)

        if 'avg_trade_duration' in display_df.columns:
            display_df['avg_trade_duration'] = display_df['avg_trade_duration'].apply(
                lambda x: int(np.ceil(x)) if pd.notna(x) and isinstance(x, (int, float)) else x
            )

        # Dynamic column renaming
        rename_map = {
            'pnl_percent': 'P&L (%)', 'max_drawdown': 'Max DD', 'calmar_ratio': 'Calmar',
            'sharpe_ratio': 'Sharpe', 'profit_factor': 'Profit Factor', 'win_rate': 'Win Rate',
            'avg_trade_duration': 'Avg. Hold (d)', 'mc_verdict': 'MC Verdict', 'mc_score': 'MC Score',
            'oos_pnl_pct': 'OOS P&L (%)', 'wfa_verdict': 'WFA Verdict',
            'wfa_rolling_verdict': 'Rolling WFA', 'avg_corr': 'Avg. Corr',
            'expectancy': 'Expectancy (R)', 'sqn': 'SQN',
            'rolling_sharpe_mean': 'Roll.Sharpe(avg)', 'rolling_sharpe_min': 'Roll.Sharpe(min)',
            'rolling_sharpe_final': 'Roll.Sharpe(last)',
            'max_recovery_days': 'Max Rcvry (d)', 'avg_recovery_days': 'Avg Rcvry (d)',
            'positions_delisted': 'Delisted Pos', 'delisting_loss_pct': 'Delisting Loss (%)',
        }
        # Add benchmark column renames
        rename_map.update(benchmark_columns["display_names"])
        display_df.rename(columns=rename_map, inplace=True)

        # Dynamic report columns
        benchmark_display_names = [benchmark_columns["display_names"][k] for k in benchmark_columns["result_keys"]]
        report_cols = (['Strategy', 'P&L (%)'] + benchmark_display_names +
                      ['Max DD', 'Max Rcvry (d)', 'Avg Rcvry (d)', 'Calmar', 'Sharpe',
                       'Roll.Sharpe(avg)', 'Roll.Sharpe(min)', 'Roll.Sharpe(last)',
                       'Profit Factor', 'Win Rate', 'Avg. Hold (d)', 'Trades',
                       'Expectancy (R)', 'SQN', 'Delisted Pos', 'Delisting Loss (%)',
                       'OOS P&L (%)', 'WFA Verdict', 'Rolling WFA',
                       'Avg. Corr', 'MC Verdict', 'MC Score'])

        summary_df_display = display_df.reindex(columns=report_cols).fillna('N/A').reset_index(drop=True)

        # Dynamic table columns
        _t1 = [c for c in _get_t1_cols(benchmark_columns) if c in summary_df_display.columns]
        _print_table(summary_df_display[_t1], f"--- Core Performance: {portfolio_name} ---")

        if CONFIG.get("verbose_output", False):
            # Merge benchmark short names into verbose short names
            verbose_short_names = {**_VERBOSE_SHORT_NAMES, **benchmark_columns["short_names"]}
            _t2 = [c for c in _get_t2_cols(benchmark_columns) if c in summary_df_display.columns]
            if len(_t2) > 1:
                _print_table(summary_df_display[_t2].rename(columns=verbose_short_names), "--- Extended Metrics ---")
            _t3 = [c for c in _T3_COLS if c in summary_df_display.columns]
            if len(_t3) > 1:
                _print_table(summary_df_display[_t3].rename(columns=verbose_short_names), "--- Robustness ---")
        else:
            print("\n  Run with --verbose for extended metrics and robustness scores.")

    # --- Step 4a: Export analyzer-compatible CSVs ---
    portfolio_name_safe = portfolio_name.replace(" ", "_")
    analyzer_csv_folder = os.path.join("output", "runs", run_id, "analyzer_csvs", portfolio_name_safe)

    # Column mapping: backtester trade_log keys -> trade_analyzer expected columns
    COLUMN_MAP = {
        'EntryDate': 'Date',
        'ExitDate': 'Ex. date',
        'EntryPrice': 'Price',
        'ExitPrice': 'Ex. Price',
        'Profit': 'Profit',
        'ProfitPct': '% Profit',
        'is_win': 'Win',
        'HoldDuration': '# bars',
        'Shares': 'Shares',
        'MAE_pct': 'MAE',
        'MFE_pct': 'MFE',
        'Symbol': 'Symbol',
        'ExitReason': 'ExitReason',
    }

    pending_csvs = []
    for result in portfolio_results:
        if not result.get('trade_log') or len(result['trade_log']) == 0:
            continue
        strategy_name_safe = result['Strategy'].replace('/', '_').replace(' ', '_').replace('(', '').replace(')', '').replace(':', '')
        raw_df = pd.DataFrame(result['trade_log'])
        mapped_df = raw_df.rename(columns=COLUMN_MAP)
        # Convert fractional values to percentages for the analyzer
        if '% Profit' in mapped_df.columns:
            mapped_df['% Profit'] = mapped_df['% Profit'] * 100.0
        if 'MAE' in mapped_df.columns:
            mapped_df['MAE'] = mapped_df['MAE'] * 100.0
        if 'MFE' in mapped_df.columns:
            mapped_df['MFE'] = mapped_df['MFE'] * 100.0
        csv_filename = f"{strategy_name_safe}.csv"
        pending_csvs.append((os.path.join(analyzer_csv_folder, csv_filename), mapped_df))

    analyzer_csvs_saved = len(pending_csvs)
    if analyzer_csvs_saved > 0:
        os.makedirs(analyzer_csv_folder, exist_ok=True)
        for csv_path, mapped_df in pending_csvs:
            mapped_df.to_csv(csv_path, index=False)
        print(f"  Exported {analyzer_csvs_saved} analyzer-compatible CSVs to {analyzer_csv_folder}")

    # --- Step 4b: Use the ORIGINAL, UNFILTERED list to save ALL generated trade logs ---
    if CONFIG.get("save_individual_trades", False):
        print("\n" + "-" * 80)
        portfolio_trades_folder = os.path.join("output", "runs", run_id, "raw_trades", portfolio_name_safe)
        os.makedirs(portfolio_trades_folder, exist_ok=True)
        
        s3_enabled = CONFIG.get("upload_to_s3") and CONFIG.get("s3_reports_bucket")
        action = "Saving and uploading" if s3_enabled else "Saving"
        done_action = "Saved and uploaded" if s3_enabled else "Saved"

        results_to_save = []
        if CONFIG.get("save_only_filtered_trades", False):
            print(f"{action} filtered trade logs for portfolio: {portfolio_name}...")
            results_to_save = [r for r in portfolio_results if r['Strategy'] in passed_display_filter]
        else:
            print(f"{action} all valid trade logs for portfolio: {portfolio_name}...")
            results_to_save = portfolio_results

        saved_logs = 0
        for result in results_to_save:
            if result.get('trade_log') and len(result['trade_log']) > 0:
                save_trades_to_csv(result, portfolio_trades_folder, run_id)
                saved_logs += 1

        if saved_logs > 0:
            print(f"{done_action} {saved_logs} trade logs.")
        else:
            print("No trade logs met the criteria for saving.")
        print("-" * 80)
    else:
        # If the flag is false, just print a message.
        print(f"\nSkipping individual trade log saving for {portfolio_name} as per config.")

def format_duration(seconds):
    """Helper to format seconds into a human-readable string."""
    if seconds is None:
        return "N/A"
    mins, secs = divmod(seconds, 60)
    return f"{int(mins)} minutes, {secs:.2f} seconds"

def generate_portfolio_summary_report(all_results, benchmark_returns, duration_seconds=None, run_id=None):
    """
    Generates the final, overall portfolio summary report.

    Parameters
    ----------
    benchmark_returns : dict
        Dictionary of benchmark labels to their returns, e.g., {"SPY": 0.123, "QQQ": 0.456}
    """
    # Build dynamic benchmark column mappings
    benchmark_columns = _build_benchmark_columns(benchmark_returns)

    print("\n\n" + "=" * 80)
    print("Overall Top Portfolio Strategies".center(80))
    print("=" * 80)

    mc_score_min = CONFIG.get("mc_score_min_to_show_in_summary", -999)
    min_pnl = CONFIG.get("min_pandl_to_show_in_summary", -999.0)
    min_calmar = CONFIG.get("min_calmar_to_show_in_summary", -999.0)
    max_dd_filter = CONFIG.get("max_acceptable_drawdown", 1.0)

    if duration_seconds is not None:
        print(f"Total Backtest Runtime: {format_duration(duration_seconds)}".center(80))
        print("=" * 80)

    if not all_results:
        print("\nNo portfolio results to summarize.")
        return

    summary_df = pd.DataFrame(all_results)

    # Build filter mask
    filter_mask = (
        (summary_df['Trades'] > 0) &
        (summary_df['mc_score'] >= mc_score_min) &
        (summary_df['pnl_percent'] * 100 >= min_pnl) &
        (summary_df['calmar_ratio'] >= min_calmar) &
        (summary_df['max_drawdown'] <= max_dd_filter)
    )

    # Dynamic benchmark filtering
    for idx, result_key in enumerate(benchmark_columns["result_keys"]):
        if idx == 0:
            min_perf = CONFIG.get("min_performance_vs_spy", -9999.0)
        elif idx == 1:
            min_perf = CONFIG.get("min_performance_vs_qqq", -9999.0)
        else:
            min_perf = -9999.0

        if result_key in summary_df.columns:
            filter_mask &= (summary_df[result_key] * 100 >= min_perf)

    filtered_df = summary_df[filter_mask].copy()

    if filtered_df.empty:
        print("\nNo strategies met the final filtering criteria.")
        return

    # Sort by numeric mc_score BEFORE the formatting loop converts it to a string.
    filtered_df.sort_values(by='mc_score', ascending=False, inplace=True)
    filtered_df.reset_index(drop=True, inplace=True)

    # Formatting logic (dynamic benchmark columns)
    format_map = [
        ('pnl_percent', "{:.2%}"), ('max_drawdown', "{:.2%}"), ('win_rate', "{:.2%}"),
        ('calmar_ratio', "{:.2f}"), ('sharpe_ratio', "{:.2f}"), ('profit_factor', "{:.2f}"),
        ('oos_pnl_pct', "{:+.2%}"), ('expectancy', "{:.3f}"), ('sqn', "{:.2f}"),
        ('rolling_sharpe_mean', "{:.2f}"), ('rolling_sharpe_min', "{:.2f}"),
        ('rolling_sharpe_final', "{:.2f}"), ('avg_recovery_days', "{:.0f}")
    ]
    for result_key in benchmark_columns["result_keys"]:
        format_map.append((result_key, benchmark_columns["format_spec"][result_key]))

    for col, f_str in format_map:
        if col in filtered_df.columns:
            filtered_df[col] = filtered_df[col].apply(lambda x: f_str.format(x) if isinstance(x, (int, float)) else x)

    if 'avg_trade_duration' in filtered_df.columns:
        filtered_df['avg_trade_duration'] = filtered_df['avg_trade_duration'].apply(
            lambda x: int(np.ceil(x)) if pd.notna(x) and isinstance(x, (int, float)) else 'N/A'
        )

    # Dynamic column renaming
    rename_map = {
        'pnl_percent': 'P&L (%)', 'max_drawdown': 'Max DD', 'calmar_ratio': 'Calmar',
        'win_rate': 'Win Rate', 'sharpe_ratio': 'Sharpe', 'profit_factor': 'Profit Factor',
        'avg_trade_duration': 'Avg. Hold (d)', 'mc_verdict': 'MC Verdict', 'mc_score': 'MC Score',
        'oos_pnl_pct': 'OOS P&L (%)', 'wfa_verdict': 'WFA Verdict', 'wfa_rolling_verdict': 'Rolling WFA',
        'expectancy': 'Expectancy (R)', 'sqn': 'SQN',
        'rolling_sharpe_mean': 'Roll.Sharpe(avg)', 'rolling_sharpe_min': 'Roll.Sharpe(min)',
        'rolling_sharpe_final': 'Roll.Sharpe(last)',
        'max_recovery_days': 'Max Rcvry (d)', 'avg_recovery_days': 'Avg Rcvry (d)',
    }
    rename_map.update(benchmark_columns["display_names"])
    filtered_df.rename(columns=rename_map, inplace=True)

    # Dynamic report columns
    benchmark_display_names = [benchmark_columns["display_names"][k] for k in benchmark_columns["result_keys"]]
    report_cols = (['Portfolio', 'Strategy', 'P&L (%)'] + benchmark_display_names +
                  ['Max DD', 'Max Rcvry (d)', 'Avg Rcvry (d)', 'Calmar', 'Sharpe',
                   'Roll.Sharpe(avg)', 'Roll.Sharpe(min)', 'Roll.Sharpe(last)',
                   'Profit Factor', 'Win Rate', 'Avg. Hold (d)', 'Trades',
                   'Expectancy (R)', 'SQN', 'OOS P&L (%)', 'WFA Verdict', 'Rolling WFA',
                   'MC Verdict', 'MC Score'])

    summary_df_display = filtered_df.reindex(columns=report_cols).fillna('N/A')
    summary_df_sorted = summary_df_display

    _pfx = ['Portfolio'] if 'Portfolio' in summary_df_sorted.columns else []
    _t1_cols = _get_t1_cols(benchmark_columns)
    _t1 = list(dict.fromkeys(_pfx + [c for c in _t1_cols if c in summary_df_sorted.columns]))
    _print_table(summary_df_sorted[_t1], "--- Core Performance: All Portfolios ---")

    if CONFIG.get("verbose_output", False):
        verbose_short_names = {**_VERBOSE_SHORT_NAMES, **benchmark_columns["short_names"]}
        _t2_cols = _get_t2_cols(benchmark_columns)
        _t2 = list(dict.fromkeys(_pfx + [c for c in _t2_cols if c in summary_df_sorted.columns]))
        if len(_t2) > len(_pfx) + 1:
            _print_table(summary_df_sorted[_t2].rename(columns=verbose_short_names), "--- Extended Metrics ---")
        _t3 = list(dict.fromkeys(_pfx + [c for c in _T3_COLS if c in summary_df_sorted.columns]))
        if len(_t3) > len(_pfx) + 1:
            _print_table(summary_df_sorted[_t3].rename(columns=verbose_short_names), "--- Robustness ---")
    else:
        print("\n  Run with --verbose for extended metrics and robustness scores.")

    try:
        output_dir = os.path.join("output", "runs", run_id) if run_id else "output"
        os.makedirs(output_dir, exist_ok=True)
        filename = "overall_portfolio_summary.csv"
        local_filepath = os.path.join(output_dir, filename)
        
        # Add run metadata columns so results are self-describing across runs
        summary_df_sorted.insert(0, 'run_id', run_id or 'unknown')
        summary_df_sorted.insert(1, 'data_provider', CONFIG.get('data_provider', 'polygon'))
        summary_df_sorted.insert(2, 'start_date', CONFIG.get('start_date', ''))
        summary_df_sorted.insert(3, 'end_date', CONFIG.get('end_date', ''))
        summary_df_sorted.insert(4, 'timeframe', f"{CONFIG.get('timeframe_multiplier', 1)}{CONFIG.get('timeframe', 'D')}")

        summary_df_sorted.to_csv(local_filepath, index=False)
        print(f"\nSuccessfully saved overall portfolio summary to '{local_filepath}'")

        # Upload the summary to S3 if enabled
        s3_bucket = CONFIG.get("s3_reports_bucket")
        if CONFIG.get("upload_to_s3") and s3_bucket and run_id:
            s3_key = f"{run_id}/{filename}"
            if upload_file_to_s3(local_filepath, s3_bucket, s3_key):
                print(f"Successfully uploaded summary to s3://{s3_bucket}/{s3_key}")

    except Exception as e:
        print(f"\n  -> WARNING: Could not save the overall portfolio summary. Error: {e}")


def generate_sensitivity_report(all_results: list[dict], run_id: str) -> None:
    """Print a parameter sensitivity fragility report when the sweep is enabled."""
    from config import CONFIG
    if not CONFIG.get("sensitivity_sweep_enabled", False) or not all_results:
        return
    groups = {}
    for r in all_results:
        base = r.get("Strategy", "").split(" [")[0]
        groups.setdefault(base, []).append(r)
    swept = {k: v for k, v in groups.items() if len(v) > 1}
    if not swept:
        return
    print("\n" + "=" * 70)
    print("  PARAMETER SENSITIVITY REPORT")
    print("=" * 70)
    for base_name, variants in swept.items():
        profitable = [v for v in variants if v.get("pnl_percent", -1) > 0]
        pct = len(profitable) / len(variants) * 100
        flag = f"*** FRAGILE — profitable in only {pct:.0f}% of variants ***" if pct < 30 else \
               f"Robust — profitable in {pct:.0f}% of variants ({len(profitable)}/{len(variants)})"
        print(f"\n  {base_name}\n  {flag}")
        print(f"\n  {'Variant':<35} {'P&L':>8} {'Sharpe':>8} {'Max DD':>8} {'MC Score':>9}")
        print("  " + "-" * 70)
        for r in sorted(variants, key=lambda x: (0 if "(base)" in x.get("Strategy", "") else 1, -x.get("pnl_percent", -999))):
            label = r.get("Strategy", "").split(" [")[-1].rstrip("]") if " [" in r.get("Strategy", "") else "(base)"
            mark = " <-- base" if label == "(base)" else ""
            print(f"  {label:<35} {r.get('pnl_percent', 0):>7.1%} {r.get('sharpe_ratio', 0) or 0:>8.2f} {r.get('max_drawdown', 0) or 0:>7.1%}  {r.get('mc_score', 0) or 0:>8}{mark}")
    print("=" * 70)