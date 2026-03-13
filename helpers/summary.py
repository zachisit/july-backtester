# helpers/summary.py

import pandas as pd
import os
from config import CONFIG
import numpy as np

from helpers.aws_utils import upload_file_to_s3
from helpers.correlation import compute_avg_correlations, DEFAULT_THRESHOLD

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
        
def generate_single_asset_summary_report(symbol_results, spy_benchmark_result, qqq_benchmark_result, symbol, symbol_trades_folder, run_id):
    """
    Prints the per-symbol summary and saves all profitable trade logs.
    """
    print("\n\n" + "=" * 80)
    print(f"Strategy Performance Summary for: {symbol}".center(80))
    print(f"Timeframe: {CONFIG['timeframe']} | Period: {CONFIG['start_date']} to {CONFIG['end_date']}".center(80))
    print("=" * 80)
    
    if spy_benchmark_result:
        spy_return = spy_benchmark_result.get('pnl_percent', 0.0)
        print(f"Benchmark (SPY) Buy & Hold Return: {spy_return:.2%}".center(80))
    if qqq_benchmark_result:
        qqq_return = qqq_benchmark_result.get('pnl_percent', 0.0)
        print(f"Benchmark (QQQ) Buy & Hold Return: {qqq_return:.2%}".center(80))
    print("=" * 80)
    
    if not symbol_results:
        print(f"\nNo successful strategy results to display for {symbol}.")
        return

    summary_df = pd.DataFrame(symbol_results)
    max_dd_filter = CONFIG.get("max_acceptable_drawdown", 1.0)
    mc_score_min = CONFIG.get("mc_score_min_to_show_in_summary", -999)
    min_pnl = CONFIG.get("min_pandl_to_show_in_summary", -999.0) # Corrected: Read as percentage
    min_calmar = CONFIG.get("min_calmar_to_show_in_summary", -999.0)
    min_vs_spy = CONFIG.get("min_performance_vs_spy", -9999.0)
    min_vs_qqq = CONFIG.get("min_performance_vs_qqq", -9999.0)

    filtered_df = summary_df[
        (summary_df['max_drawdown'] <= max_dd_filter) &
        (summary_df['mc_score'] >= mc_score_min) &
        (summary_df['pnl_percent'] * 100 >= min_pnl) & # Corrected: Compare as percentage
        (summary_df['calmar_ratio'] >= min_calmar) &
        (summary_df['vs_spy_benchmark'] * 100 >= min_vs_spy) &
        (summary_df['vs_qqq_benchmark'] * 100 >= min_vs_qqq)
    ].copy()

    if filtered_df.empty:
        print(f"\nNo strategies for {symbol} met the required criteria.")
        print(f"(Filters: Max DD < {max_dd_filter:.0%}, Min MC Score >= {mc_score_min}, Min P&L >= {min_pnl:.2f}%, Min Calmar >= {min_calmar:.2f}, "
              f"vs SPY >= {min_vs_spy:.2f}%, vs QQQ >= {min_vs_qqq:.2f}%)")
    else:
        # (Formatting logic is fine)
        for col, f_str in [('pnl_percent', "{:.2%}"), ('max_drawdown', "{:.2%}"), ('win_rate', "{:.2%}"), ('calmar_ratio', "{:.2f}"), ('sharpe_ratio', "{:.2f}"), ('profit_factor', "{:.2f}"), ('vs_spy_benchmark', "{:+.2%}"), ('vs_qqq_benchmark', "{:+.2%}"), ('oos_pnl_pct', "{:+.2%}"), ('expectancy', "{:.3f}"), ('sqn', "{:.2f}")]:
            if col in filtered_df.columns:
                filtered_df[col] = filtered_df[col].apply(lambda x: f_str.format(x) if isinstance(x, (int, float)) else x)
        if 'avg_trade_duration' in filtered_df.columns:
            filtered_df['avg_trade_duration'] = filtered_df['avg_trade_duration'].apply(lambda x: int(np.ceil(x)) if pd.notna(x) and isinstance(x, (int, float)) else x)
        filtered_df.rename(columns={'pnl_percent': 'P&L (%)', 'max_drawdown': 'Max DD', 'calmar_ratio': 'Calmar', 'sharpe_ratio': 'Sharpe', 'profit_factor': 'Profit Factor', 'win_rate': 'Win Rate', 'avg_trade_duration': 'Avg. Hold (d)', 'mc_verdict': 'MC Verdict', 'mc_score': 'MC Score', 'vs_spy_benchmark': 'vs. SPY (B&H)', 'vs_qqq_benchmark': 'vs. QQQ (B&H)', 'oos_pnl_pct': 'OOS P&L (%)', 'wfa_verdict': 'WFA Verdict', 'expectancy': 'Expectancy (R)', 'sqn': 'SQN'}, inplace=True)
        report_cols = ['Strategy', 'P&L (%)', 'vs. SPY (B&H)', 'vs. QQQ (B&H)', 'Max DD', 'Calmar', 'Sharpe', 'Profit Factor', 'Win Rate', 'Avg. Hold (d)', 'Trades', 'Expectancy (R)', 'SQN', 'OOS P&L (%)', 'WFA Verdict', 'MC Verdict', 'MC Score']
        summary_df_display = filtered_df.reindex(columns=report_cols).fillna('N/A').sort_values(by='MC Score', ascending=False).reset_index(drop=True)
        print(f"\n--- Strategy Comparison for {symbol} (filtered, sorted by MC Score) ---")
        print(summary_df_display.to_string(index=False))
    
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

def generate_final_summary(all_results):
    """
    Generates the final summary for the single-asset mode.
    """
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
    min_vs_spy = CONFIG.get("min_performance_vs_spy", -9999.0)
    min_vs_qqq = CONFIG.get("min_performance_vs_qqq", -9999.0)
    max_dd_filter = CONFIG.get("max_acceptable_drawdown", -9999.0)
    min_trades = CONFIG.get("min_trades_for_mc", 15)

    filtered_df = summary_df[
        (summary_df['Trades'] >= min_trades) &
        (summary_df['max_drawdown'] <= max_dd_filter) &
        (summary_df['mc_score'] >= mc_score_min) &
        (summary_df['pnl_percent'] * 100 >= min_pnl) &
        (summary_df['calmar_ratio'] >= min_calmar) &
        (summary_df['vs_spy_benchmark'] * 100 >= min_vs_spy) &
        (summary_df['vs_qqq_benchmark'] * 100 >= min_vs_qqq)
    ].copy()
    
    if filtered_df.empty:
        print("\nNo strategies met the final criteria.")
        print(f"(Filters: Min Trades >= {min_trades}, Max DD < {max_dd_filter:.0%}, Min MC Score >= {mc_score_min}, "
              f"Min P&L >= {min_pnl:.2f}%, Min Calmar >= {min_calmar:.2f}, "
              f"vs SPY >= {min_vs_spy:.2f}%, vs QQQ >= {min_vs_qqq:.2f}%)")
        return
        
    final_df = filtered_df.sort_values(by='mc_score', ascending=False).head(5).reset_index(drop=True)
    
    for col, f_str in [('pnl_percent', "{:.2%}"), ('max_drawdown', "{:.2%}"), ('win_rate', "{:.2%}"),
                       ('calmar_ratio', "{:.2f}"), ('sharpe_ratio', "{:.2f}"), ('profit_factor', "{:.2f}"),
                       ('vs_spy_benchmark', "{:+.2%}"), ('vs_qqq_benchmark', "{:+.2%}"),
                       ('oos_pnl_pct', "{:+.2%}"), ('expectancy', "{:.3f}"), ('sqn', "{:.2f}")]:
        if col in final_df.columns:
            final_df[col] = final_df[col].apply(lambda x: f_str.format(x) if isinstance(x, (int, float)) else x)
    if 'avg_trade_duration' in final_df.columns:
        final_df['avg_trade_duration'] = final_df['avg_trade_duration'].apply(
            lambda x: int(np.ceil(x)) if pd.notna(x) and isinstance(x, (int, float)) else x)

    final_df.rename(columns={
        'Asset': 'Symbol', 'pnl_percent': 'P&L (%)', 'max_drawdown': 'Max DD', 'calmar_ratio': 'Calmar',
        'sharpe_ratio': 'Sharpe', 'profit_factor': 'Profit Factor', 'win_rate': 'Win Rate',
        'avg_trade_duration': 'Avg. Hold (d)', 'mc_verdict': 'MC Verdict', 'mc_score': 'MC Score',
        'vs_spy_benchmark': 'vs. SPY (B&H)', 'vs_qqq_benchmark': 'vs. QQQ (B&H)',
        'oos_pnl_pct': 'OOS P&L (%)', 'wfa_verdict': 'WFA Verdict',
        'expectancy': 'Expectancy (R)', 'sqn': 'SQN',
    }, inplace=True)

    report_cols = ['Symbol', 'Strategy', 'P&L (%)', 'vs. SPY (B&H)', 'vs. QQQ (B&H)', 'Max DD', 'Calmar', 'Sharpe', 'Profit Factor', 'Win Rate', 'Avg. Hold (d)', 'Trades', 'Expectancy (R)', 'SQN', 'OOS P&L (%)', 'WFA Verdict', 'MC Verdict', 'MC Score']
    final_df_display = final_df.reindex(columns=report_cols).fillna('N/A')
    
    print("\nBased on all filters, the most promising single-asset combinations are:\n")
    print(final_df_display.to_string(index=False))
    
    try:
        output_dir = "output"
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, "top_5_single_asset_summary.csv")
        final_df_display.to_csv(filepath, index=False)
        print(f"\nSuccessfully saved top 5 single-asset summary to '{filepath}'")
    except Exception as e:
        print(f"\n  -> WARNING: Could not save the top 5 single-asset summary. Error: {e}")

    print("\n" + "=" * 80)

def generate_per_portfolio_summary(portfolio_results, portfolio_name, spy_return, qqq_return, run_id, corr_matrix=None):
    """
    Prints the per-portfolio strategy summary and saves all trade logs.
    """

    print("\n\n" + "=" * 80)
    print(f"Strategy Performance Summary for Portfolio: {portfolio_name}".center(80))
    print("=" * 80)
    print(f"Benchmark (SPY) Buy & Hold Return: {spy_return:.2%}".center(80))
    print(f"Benchmark (QQQ) Buy & Hold Return: {qqq_return:.2%}".center(80))
    print("=" * 80)

    if not portfolio_results:
        print(f"\nNo successful strategy results to display for {portfolio_name}.")
        return

    # --- Step 1: Create the main DataFrame from ALL results ---
    summary_df = pd.DataFrame(portfolio_results).copy()

    # --- Step 2: Create a separate, FILTERED DataFrame for DISPLAY purposes only ---
    min_vs_spy = CONFIG.get("min_performance_vs_spy", -9999.0)
    min_vs_qqq = CONFIG.get("min_performance_vs_qqq", -9999.0)
    max_dd_filter = CONFIG.get("max_acceptable_drawdown", 1.0)
    mc_score_min = CONFIG.get("mc_score_min_to_show_in_summary", -999)
    min_pnl = CONFIG.get("min_pandl_to_show_in_summary", -999.0)
    min_calmar = CONFIG.get("min_calmar_to_show_in_summary", -999.0)
    
    # Always include the check for trades > 0
    display_df = summary_df[
        (summary_df['Trades'] > 0) &
        (summary_df['max_drawdown'] <= max_dd_filter) &
        (summary_df['mc_score'] >= mc_score_min) &
        (summary_df['pnl_percent'] * 100 >= min_pnl) &
        (summary_df['calmar_ratio'] >= min_calmar) &
        (summary_df['vs_spy_benchmark'] * 100 >= min_vs_spy) &
        (summary_df['vs_qqq_benchmark'] * 100 >= min_vs_qqq)
    ].copy()

    # --- Step 3: Use the filtered display_df to show the summary table ---
    if display_df.empty:
        print(f"\nNo strategies for {portfolio_name} met the required display criteria.")
        print(f"(Filters: Min Trades > 0, Max DD < {max_dd_filter:.0%}, Min MC Score >= {mc_score_min}, Min P&L >= {min_pnl:.2f}%, Min Calmar >= {min_calmar:.2f}, "
              f"vs SPY >= {min_vs_spy:.2f}%, vs QQQ >= {min_vs_qqq:.2f}%)")
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

        # Formatting logic
        for col, f_str in [('pnl_percent', "{:.2%}"), ('max_drawdown', "{:.2%}"), ('win_rate', "{:.2%}"), ('calmar_ratio', "{:.2f}"), ('sharpe_ratio', "{:.2f}"), ('profit_factor', "{:.2f}"), ('vs_spy_benchmark', "{:+.2%}"), ('vs_qqq_benchmark', "{:+.2%}"), ('oos_pnl_pct', "{:+.2%}"), ('expectancy', "{:.3f}"), ('sqn', "{:.2f}")]:
            if col in display_df.columns: display_df[col] = display_df[col].apply(lambda x: f_str.format(x) if isinstance(x, (int, float)) else x)
        if 'avg_trade_duration' in display_df.columns: display_df['avg_trade_duration'] = display_df['avg_trade_duration'].apply(lambda x: int(np.ceil(x)) if pd.notna(x) and isinstance(x, (int, float)) else x)
        display_df.rename(columns={'pnl_percent': 'P&L (%)', 'max_drawdown': 'Max DD', 'calmar_ratio': 'Calmar', 'sharpe_ratio': 'Sharpe', 'profit_factor': 'Profit Factor', 'win_rate': 'Win Rate', 'avg_trade_duration': 'Avg. Hold (d)', 'mc_verdict': 'MC Verdict', 'mc_score': 'MC Score', 'vs_spy_benchmark': 'vs. SPY (B&H)', 'vs_qqq_benchmark': 'vs. QQQ (B&H)', 'oos_pnl_pct': 'OOS P&L (%)', 'wfa_verdict': 'WFA Verdict', 'avg_corr': 'Avg. Corr', 'expectancy': 'Expectancy (R)', 'sqn': 'SQN'}, inplace=True)
        report_cols = ['Strategy', 'P&L (%)', 'vs. SPY (B&H)', 'vs. QQQ (B&H)', 'Max DD', 'Calmar', 'Sharpe', 'Profit Factor', 'Win Rate', 'Avg. Hold (d)', 'Trades', 'Expectancy (R)', 'SQN', 'OOS P&L (%)', 'WFA Verdict', 'Avg. Corr', 'MC Verdict', 'MC Score']
        summary_df_display = display_df.reindex(columns=report_cols).fillna('N/A').sort_values(by='MC Score', ascending=False).reset_index(drop=True)
        print(f"\n--- Strategy Comparison for {portfolio_name} (filtered, sorted by MC Score) ---")
        print(summary_df_display.to_string(index=False))

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
            # Get the list of strategy names that passed the filter
            # (Need to define display_df earlier in the function if it's not already)
            display_df = pd.DataFrame(portfolio_results) # Or use the filtered one if available
            filtered_strategy_names = display_df['Strategy'].tolist()
            results_to_save = [r for r in portfolio_results if r['Strategy'] in filtered_strategy_names]
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

def generate_portfolio_summary_report(all_results, duration_seconds=None, run_id=None):
    """
    Generates the final, overall portfolio summary report.
    """
    print("\n\n" + "=" * 80)
    print("Overall Top Portfolio Strategies".center(80))
    print("=" * 80)

    min_vs_spy = CONFIG.get("min_performance_vs_spy", -9999.0)
    min_vs_qqq = CONFIG.get("min_performance_vs_qqq", -9999.0)
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
    
    filtered_df = summary_df[
        (summary_df['Trades'] > 0) &
        (summary_df['mc_score'] >= mc_score_min) &
        (summary_df['pnl_percent'] * 100 >= min_pnl) &
        (summary_df['calmar_ratio'] >= min_calmar) &
        (summary_df['vs_spy_benchmark'] * 100 >= min_vs_spy) &
        (summary_df['vs_qqq_benchmark'] * 100 >= min_vs_qqq) &
        (summary_df['max_drawdown'] <= max_dd_filter)
    ].copy()

    if filtered_df.empty:
        print("\nNo strategies met the final filtering criteria.")
        return

    # --- Formatting and Renaming Section ---
    for col, f_str in [('pnl_percent', "{:.2%}"), ('max_drawdown', "{:.2%}"), ('win_rate', "{:.2%}"), ('calmar_ratio', "{:.2f}"),
                       ('sharpe_ratio', "{:.2f}"), ('profit_factor', "{:.2f}"), ('vs_spy_benchmark', "{:+.2%}"), ('vs_qqq_benchmark', "{:+.2%}"),
                       ('oos_pnl_pct', "{:+.2%}"), ('expectancy', "{:.3f}"), ('sqn', "{:.2f}")]:
        if col in filtered_df.columns:
            filtered_df[col] = filtered_df[col].apply(lambda x: f_str.format(x) if isinstance(x, (int, float)) else x)

    if 'avg_trade_duration' in filtered_df.columns:
        filtered_df['avg_trade_duration'] = filtered_df['avg_trade_duration'].apply(
            lambda x: int(np.ceil(x)) if pd.notna(x) and isinstance(x, (int, float)) else 'N/A')

    filtered_df.rename(columns={
        'pnl_percent': 'P&L (%)', 'max_drawdown': 'Max DD', 'calmar_ratio': 'Calmar',
        'win_rate': 'Win Rate', 'sharpe_ratio': 'Sharpe', 'profit_factor': 'Profit Factor',
        'avg_trade_duration': 'Avg. Hold (d)', 'mc_verdict': 'MC Verdict', 'mc_score': 'MC Score',
        'vs_spy_benchmark': 'vs. SPY (B&H)', 'vs_qqq_benchmark': 'vs. QQQ (B&H)',
        'oos_pnl_pct': 'OOS P&L (%)', 'wfa_verdict': 'WFA Verdict',
        'expectancy': 'Expectancy (R)', 'sqn': 'SQN',
    }, inplace=True)

    report_cols = ['Portfolio', 'Strategy', 'P&L (%)', 'vs. SPY (B&H)', 'vs. QQQ (B&H)', 'Max DD', 'Calmar', 'Sharpe', 'Profit Factor', 'Win Rate', 'Avg. Hold (d)', 'Trades', 'Expectancy (R)', 'SQN', 'OOS P&L (%)', 'WFA Verdict', 'MC Verdict', 'MC Score']
    summary_df_display = filtered_df.reindex(columns=report_cols).fillna('N/A')
    
    summary_df_sorted = summary_df_display.sort_values(by='MC Score', ascending=False)
    
    print("\n--- Strategy Comparison Across All Portfolios (filtered, sorted by MC Score) ---")
    print(summary_df_sorted.to_string(index=False))

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