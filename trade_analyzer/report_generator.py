# report_generator.py
import math
import os 
import re 
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
from matplotlib.backends.backend_pdf import PdfPages
import pandas as pd
import numpy as np
import traceback
from pandas.core.dtypes.dtypes import PeriodDtype

from . import default_config as config
from . import calculations
from . import utils

def create_text_figure(lines_to_draw, page_title=""):
    """Creates a matplotlib figure containing the provided lines of text."""
    fig = plt.figure(figsize=config.A4_LANDSCAPE)
    plt.axis('off')
    start_y, line_height = 0.90, 0.018 
    plt.text(0.01, 0.96, page_title, weight='bold', size=12, ha='left', va='top')
    current_y = start_y
    for line in lines_to_draw:
        plt.text(0.01, current_y, line, family='monospace', size=8, ha='left', va='top', wrap=False)
        current_y -= line_height
        if current_y < 0.02:
            if config.VERBOSE_DEBUG: print(f"Warning: Text overflow on PDF page '{page_title}'.")
            break
    return fig

def add_line_to_summary(summary_lines_list, label, value, is_curr=False, is_pct=False, is_raw_pct_val=False, fmt_spec=None):
    """Helper to format and append a line to a list of summary strings."""
    val_str = "N/A"
    # Check for NaN or None before checking for Inf
    if pd.notna(value):
        # Check for Inf after checking for NaN
        if isinstance(value, (float, np.floating)) and np.isinf(value):
            val_str = "inf" if value > 0 else "-inf"
        else:
            try:
                if is_curr: val_str = f"${value:,.2f}"
                elif is_pct: val_str = f"{value:.2%}" # Assumes input is fractional (0.01 -> 1.00%)
                elif is_raw_pct_val: val_str = f"{value:.2f}%" # Assumes input is already scaled (1.0 -> 1.00%)
                elif fmt_spec: val_str = fmt_spec.format(value)
                else: val_str = str(value) # Default conversion
            except (ValueError, TypeError): val_str = "Format Error"
    # Append the formatted line
    summary_lines_list.append(f"{label:<45} {val_str}")

def generate_overall_metrics_summary(
    trades_df, daily_returns, benchmark_returns, benchmark_df, daily_equity,
    benchmark_ticker, initial_equity, risk_free_rate, trading_days_per_year
):
    """
    Generates the text summary for overall performance metrics,
    including standard portfolio Sharpe and per-trade Sharpe diagnostics.
    """
    title = "Overall Performance Metrics"
    summary_lines = [] # Use a list to build the summary
    try:
        # --- Basic Core Metrics ---
        core_metrics = calculations.calculate_core_metrics(trades_df)
        final_equity = initial_equity + core_metrics.get('total_profit', 0)
        total_trades = core_metrics.get('total_trades', 0)

        # --- Duration & CAGR ---
        start_date = trades_df['Date'].min()
        end_date = trades_df['Ex. date'].max()
        total_duration_years = 0.0
        trades_per_year = 0.0
        duration_text = "N/A"
        if pd.notna(start_date) and pd.notna(end_date) and end_date > start_date:
            duration_delta = end_date - start_date
            total_duration_years = duration_delta.days / 365.25
            duration_text = f"{total_duration_years:.2f} years ({duration_delta.days} days)"
            if total_duration_years > 1e-6:
                 trades_per_year = total_trades / total_duration_years

        cagr = calculations.calculate_cagr(initial_equity, final_equity, total_duration_years)

        # --- Standard Portfolio Ratios (using daily returns) ---
        annualized_portfolio_sharpe = calculations.calculate_sharpe_ratio(daily_returns, risk_free_rate, trading_days_per_year)
        annualized_sortino = calculations.calculate_sortino_ratio(daily_returns, risk_free_rate, trading_days_per_year)

        # --- Historical Backtest Drawdown (from Equity Curve) ---
        equity_curve_for_hist_dd = pd.Series(dtype=float)
        if 'Equity' in trades_df.columns and pd.api.types.is_numeric_dtype(trades_df['Equity']) and trades_df['Equity'].notna().all():
            equity_curve_for_hist_dd = trades_df['Equity']
        elif not daily_equity.empty:
            equity_curve_for_hist_dd = daily_equity
            
        _, _, _, max_equity_dd_percent = calculations.calculate_equity_drawdown(equity_curve_for_hist_dd)

        # --- Calmar Ratio ---
        calmar_ratio = calculations.calculate_calmar(cagr, max_equity_dd_percent)

        # --- Alpha / Beta ---
        alpha, beta = np.nan, np.nan
        if daily_returns is not None and benchmark_returns is not None and not daily_returns.empty and not benchmark_returns.empty:
             common_index = daily_returns.index.intersection(benchmark_returns.index)
             if len(common_index) > 1:
                  aligned_strategy = daily_returns.loc[common_index]
                  aligned_benchmark = benchmark_returns.loc[common_index]
                  alpha, beta = calculations.calculate_alpha_beta(aligned_strategy, aligned_benchmark, risk_free_rate, trading_days_per_year)

        # --- VaR / CVaR (from trade profits) ---
        var_95, cvar_95 = calculations.calculate_var_cvar(trades_df['Profit'], level=0.05)
        var_99, cvar_99 = calculations.calculate_var_cvar(trades_df['Profit'], level=0.01)

        # --- Benchmark Return ---
        benchmark_total_return = np.nan
        if benchmark_df is not None and not benchmark_df.empty:
            common_dates_idx = trades_df['Ex. date'] if daily_equity.empty else daily_equity.index
            common_dates = benchmark_df.index.intersection(common_dates_idx)
            if len(common_dates) > 1:
                bench_aligned = benchmark_df.loc[common_dates].sort_index()
                if not bench_aligned.empty:
                    start_price = bench_aligned['Benchmark_Price'].iloc[0]
                    end_price = bench_aligned['Benchmark_Price'].iloc[-1]
                    if pd.notna(start_price) and start_price > 0 and pd.notna(end_price):
                        benchmark_total_return = (end_price / start_price) - 1

        # --- Sharpe Ratio of Trades (Diagnostics) ---
        sharpe_of_trades_arith_non_ann = np.nan
        sharpe_of_trades_log_non_ann = np.nan

        if '% Profit' in trades_df.columns and pd.api.types.is_numeric_dtype(trades_df['% Profit']):
            per_trade_arith_returns = trades_df['% Profit'] / 100.0
            per_trade_arith_returns_clean = per_trade_arith_returns.dropna()
            
            if len(per_trade_arith_returns_clean) >= 2:
                # --- Arithmetic ---
                mean_arith = per_trade_arith_returns_clean.mean()
                std_arith = per_trade_arith_returns_clean.std()
                if pd.notna(std_arith) and std_arith > 1e-9:
                    sharpe_of_trades_arith_non_ann = mean_arith / std_arith
                
                # --- Logarithmic ---
                try:
                    # Calculate log returns: log(1 + R_arith)
                    # Add 1 before taking log, handle potential returns <= -1 (100% loss)
                    log_ret_base = 1 + per_trade_arith_returns_clean
                    # Avoid log(0) or log(negative) for losses >= 100%
                    log_ret_base = log_ret_base[log_ret_base > 1e-9] # Filter out problematic values
                    
                    if len(log_ret_base) >= 2:
                        per_trade_log_returns = np.log(log_ret_base)
                        mean_log = per_trade_log_returns.mean()
                        std_log = per_trade_log_returns.std()
                        if pd.notna(std_log) and std_log > 1e-9:
                           sharpe_of_trades_log_non_ann = mean_log / std_log
                    elif config.VERBOSE_DEBUG:
                        print("[DEBUG SHARPE OF TRADES LOG] Not enough valid data points after filtering for log.")
                        
                except Exception as log_err:
                    if config.VERBOSE_DEBUG:
                        print(f"[DEBUG SHARPE OF TRADES LOG] Error calculating log returns: {log_err}")

        # === Format Summary Text ===
        # Use previously defined add_line_to_summary helper function
        add_line = lambda label, value, **kwargs: add_line_to_summary(summary_lines, label, value, **kwargs)

        # --- Add lines using the helper ---
        add_line("Total Net Profit:", core_metrics.get('total_profit'), is_curr=True)
        # ... (Add all other standard lines as before) ...
        add_line("Total Trades:", total_trades, fmt_spec="{:,.0f}")
        if 'Shares' in trades_df.columns and pd.api.types.is_numeric_dtype(trades_df['Shares']):
             add_line("Total Shares Purchased:", trades_df['Shares'].sum(), fmt_spec="{:,.0f}")
        add_line("Strategy Total Return:", ((final_equity / initial_equity) - 1 if initial_equity > 0 else np.nan), is_pct=True)
        summary_lines.append("")
        add_line("Gross Profit:", core_metrics.get('gross_profit'), is_curr=True)
        add_line("Gross Loss:", core_metrics.get('gross_loss'), is_curr=True)
        add_line("Profit Factor:", core_metrics.get('profit_factor'), fmt_spec="{:.2f}")
        summary_lines.append("")
        add_line("Win Rate:", core_metrics.get('win_rate'), is_pct=True)
        add_line("Average Winning Trade:", core_metrics.get('avg_win'), is_curr=True)
        add_line("Average Losing Trade:", core_metrics.get('avg_loss'), is_curr=True)
        add_line("Average Trade Profit:", core_metrics.get('avg_trade_profit'), is_curr=True)
        avg_win, avg_loss = core_metrics.get('avg_win', np.nan), core_metrics.get('avg_loss', np.nan)
        ratio_wl = abs(avg_win / avg_loss) if pd.notna(avg_win) and pd.notna(avg_loss) and avg_loss != 0 else np.nan
        add_line("Ratio Avg Win / Avg Loss:", ratio_wl, fmt_spec="{:.2f}")
        summary_lines.append("")
        add_line("Max Consecutive Wins:", core_metrics.get('max_consecutive_wins'), fmt_spec="{:.0f}")
        add_line("Max Consecutive Losses:", core_metrics.get('max_consecutive_losses'), fmt_spec="{:.0f}")
        summary_lines.append("")
        add_line("Expectancy per Trade:", core_metrics.get('expectancy'), is_curr=True)
        summary_lines.append("")
        add_line("Total Duration:", duration_text)
        add_line("Average Trades per Year:", trades_per_year, fmt_spec="{:.1f}")
        add_line("CAGR:", cagr, is_pct=True)
        summary_lines.append("")
        # --- Risk & Ratio Metrics ---
        add_line(f"Sharpe Ratio (Ann., Portfolio Daily, Rf={risk_free_rate*100:.1f}%):", annualized_portfolio_sharpe, fmt_spec="{:.2f}")
        add_line(f"Sortino Ratio (Ann., Portfolio Daily, Rf={risk_free_rate*100:.1f}%):", annualized_sortino, fmt_spec="{:.2f}")
        add_line("Calmar Ratio (CAGR / Max Equity DD%):", calmar_ratio, fmt_spec="{:.2f}")
        add_line("Max Equity Drawdown:", max_equity_dd_percent, is_raw_pct_val=True)
        summary_lines.append("")
        # --- Add Sharpe of Trades Diagnostics ---
        add_line("Sharpe (Per Trade, Arith Ret, Non-Ann, Rf=0%):", sharpe_of_trades_arith_non_ann, fmt_spec="{:.2f}")
        add_line("Sharpe (Per Trade, Log Ret, Non-Ann, Rf=0%):", sharpe_of_trades_log_non_ann, fmt_spec="{:.2f}")
        summary_lines.append("")
        # --- Tail Risk ---
        summary_lines.append("Tail Risk Analysis (Based on Trade Profit $):" + "\n" + "-"*50)
        add_line("95% Value at Risk (VaR):", var_95, is_curr=True)
        add_line("95% Conditional VaR (CVaR):", cvar_95, is_curr=True)
        add_line("99% Value at Risk (VaR):", var_99, is_curr=True)
        add_line("99% Conditional VaR (CVaR):", cvar_99, is_curr=True)
        summary_lines.append("")
        # --- Benchmark Comparison ---
        summary_lines.append("Benchmark Comparison (" + benchmark_ticker + "):" + "\n" + "-"*50)
        add_line(f"{benchmark_ticker} Buy & Hold Return (period):", benchmark_total_return, is_pct=True)
        add_line(f"Beta vs {benchmark_ticker}:", beta, fmt_spec="{:.2f}")
        add_line(f"Alpha vs {benchmark_ticker} (Ann., Rf={risk_free_rate*100:.1f}%):", alpha, is_pct=True)

        summary_text = "\n".join(summary_lines)

    except Exception as e:
        summary_text = f"Error in Overall Metrics: {e}\n{traceback.format_exc()}"
        print(f"ERROR generating overall_metrics_summary: {e}")
        traceback.print_exc()

    return title, summary_text


def generate_wfa_summary(wfa_result: dict, wfa_split_date: str | None, wfa_split_ratio) -> tuple[str, str]:
    """Generate the Walk-Forward Analysis section for the report.

    Parameters
    ----------
    wfa_result      : dict returned by ``helpers.wfa.evaluate_wfa``
                      (keys: ``oos_pnl_pct``, ``wfa_verdict``), or empty dict if
                      WFA was not run.
    wfa_split_date  : ISO date string of the IS/OOS boundary, or None.
    wfa_split_ratio : The configured split ratio (e.g. 0.80), or None if disabled.
    """
    title = "Walk-Forward Analysis (WFA)"
    lines = []

    if not wfa_result or wfa_split_date is None:
        if not wfa_split_ratio or float(wfa_split_ratio or 0) <= 0:
            lines.append("WFA is disabled. Set WFA_SPLIT_RATIO (e.g. 0.80) to enable.")
        else:
            lines.append("WFA could not be computed (insufficient trade data or date information).")
        return title, "\n".join(lines)

    is_pct = int(float(wfa_split_ratio) * 100)
    oos_pct = 100 - is_pct
    lines.append(f"Split Ratio   : {is_pct}% In-Sample / {oos_pct}% Out-of-Sample")
    lines.append(f"IS/OOS Boundary : {wfa_split_date}")
    lines.append("")

    oos_pnl = wfa_result.get("oos_pnl_pct")
    verdict = wfa_result.get("wfa_verdict", "N/A")

    if oos_pnl is not None:
        lines.append(f"{'OOS P&L (% of capital):':<45} {oos_pnl:+.2%}")
    else:
        lines.append(f"{'OOS P&L (% of capital):':<45} N/A")

    lines.append(f"{'WFA Verdict:':<45} {verdict}")
    lines.append("")

    if verdict == "Pass":
        lines.append("Result: Out-of-Sample performance is consistent with In-Sample. No overfitting signal detected.")
    elif verdict == "Likely Overfitted":
        lines.append("Result: CAUTION — OOS performance significantly underperforms IS.")
        lines.append("        This may indicate curve-fitting to historical data.")
        lines.append("        Triggers: IS profitable + OOS loss (sign flip), OR OOS annualised return")
        lines.append("        degraded >75% relative to IS annualised return.")
    else:
        lines.append("Result: N/A — Insufficient OOS trades to issue a verdict (minimum 5 required).")

    return title, "\n".join(lines)


# In report_generator.py

# (imports and other functions)

def generate_drawdown_summary(dd_periods_df, max_dd_profit_pct, max_equity_dd_pct, drawdown_as_negative=False):
    """Generates text summary for detailed drawdown analysis."""
    title = "Detailed Drawdown Analysis"
    summary_lines = []
    try:
        # Helper function for adding lines
        def add_line(label, value, is_pct_val=False, is_curr=False, fmt_spec=None):
            val_str = "N/A"
            if pd.notna(value):
                try:
                    display_value = value
                    # Apply sign based on drawdown_as_negative for display
                    # Ensure value is treated as magnitude here before potentially negating
                    if is_pct_val:
                        if drawdown_as_negative and value > 0: display_value = -abs(value)
                        else: display_value = abs(value) # Display as positive magnitude if not negative flag
                        val_str = f"{display_value:.2f}%"
                    elif is_curr: val_str = f"${value:,.2f}" # Assuming DD Amount is always positive magnitude from calc
                    elif fmt_spec: val_str = fmt_spec.format(value)
                    else: val_str = str(value)
                except (ValueError, TypeError): val_str = "Format Error"
            summary_lines.append(f"{label:<45} {val_str}")

        # Display only the Max Equity Drawdown % (which is the standard system drawdown)
        # Removed the line for Max Drawdown based on Cumulative Profit
        add_line("Max System Drawdown (Based on Equity %):", max_equity_dd_pct, is_pct_val=True)
        summary_lines.append("") # Add a blank line for spacing

        # --- Detailed Drawdown Periods Table (based on Cumulative Profit) ---
        # Note: The underlying dd_periods_df IS calculated based on cumulative profit in calculations.py
        # This calculation might need review if cum_profit starts near zero and goes negative.
        if dd_periods_df is not None and not dd_periods_df.empty:
             summary_lines.append("Drawdown Duration & Recovery Periods (Based on Cumulative Profit Peaks/Troughs):" + "\n" + "-"*75)
             add_line("Average Drawdown Duration (Trades):", dd_periods_df.get('Duration_Trades', pd.Series(dtype=float)).mean(), fmt_spec="{:.1f}")
             add_line("Maximum Drawdown Duration (Trades):", dd_periods_df.get('Duration_Trades', pd.Series(dtype=float)).max(), fmt_spec="{:.0f}")
             add_line("Average Drawdown Duration (Days):", dd_periods_df.get('Duration_Days', pd.Series(dtype=float)).mean(), fmt_spec="{:.0f}")
             add_line("Maximum Drawdown Duration (Days):", dd_periods_df.get('Duration_Days', pd.Series(dtype=float)).max(), fmt_spec="{:.0f}")
             summary_lines.append("")
             add_line("Average Recovery Time (Trades):", dd_periods_df['Recovery_Trades'].dropna().mean() if 'Recovery_Trades' in dd_periods_df else np.nan, fmt_spec="{:.1f}")
             add_line("Maximum Recovery Time (Trades):", dd_periods_df['Recovery_Trades'].dropna().max() if 'Recovery_Trades' in dd_periods_df else np.nan, fmt_spec="{:.0f}")
             add_line("Average Recovery Time (Days):", dd_periods_df['Recovery_Days'].dropna().mean() if 'Recovery_Days' in dd_periods_df else np.nan, fmt_spec="{:.0f}")
             add_line("Maximum Recovery Time (Days):", dd_periods_df['Recovery_Days'].dropna().max() if 'Recovery_Days' in dd_periods_df else np.nan, fmt_spec="{:.0f}")
             summary_lines.append("\nDefinitions:\n - Duration: Time from equity peak to new equity peak.\n - Recovery Time: Time from drawdown trough to new equity peak.\n")

             # --- Top Drawdown Periods Table ---
             required_cols_top5 = ['Start_Date', 'Trough_Date', 'End_Date', 'DD_Amount', 'Duration_Days', 'Peak_Value']
             if all(col in dd_periods_df for col in required_cols_top5):
                  # Sort by DD Amount to show largest dollar drawdowns from cum profit peaks
                  top_5_dds = dd_periods_df.sort_values('DD_Amount', ascending=False, na_position='last').head(5)
                  summary_lines.append("\nTop 5 Largest Drawdown Periods (by $ Amount, based on Cum. Profit Peaks):" + "\n" + "-"*90)
                  header = f"{'Start Date':<12} {'Trough Date':<12} {'End Date':<12} {'Duration(d)':<13} {'DD Amount($)':<15} {'Peak Val($)':<15}"
                  summary_lines.append(header)
                  summary_lines.append("-" * len(header))
                  for _, row in top_5_dds.iterrows():
                       start_dt_str = row['Start_Date'].strftime('%Y-%m-%d') if pd.notna(row['Start_Date']) else 'N/A'
                       trough_dt_str = row['Trough_Date'].strftime('%Y-%m-%d') if pd.notna(row['Trough_Date']) else 'N/A'
                       end_dt_str = row['End_Date'].strftime('%Y-%m-%d') if pd.notna(row['End_Date']) else 'Ongoing'
                       duration_days_str = f"{row['Duration_Days']:.0f}" if pd.notna(row['Duration_Days']) else 'N/A'
                       # DD_Amount is positive magnitude from calculation
                       dd_amount_str = f"{row['DD_Amount']:,.2f}"
                       peak_val_str = f"{row.get('Peak_Value', np.nan):,.2f}"
                       summary_lines.append(f"{start_dt_str:<12} {trough_dt_str:<12} {end_dt_str:<12} {duration_days_str:<13} {dd_amount_str:<15} {peak_val_str:<15}")
             else: summary_lines.append("\nCould not display Top 5 Drawdown Periods (missing columns).")
        else: summary_lines.append("No completed drawdown periods found for detailed analysis based on cumulative profit.")

    except Exception as e:
        print(f"ERROR generating drawdown summary: {e}")
        traceback.print_exc()
        summary_lines = [f"Error encountered during drawdown summary generation:\n{e}\n{traceback.format_exc()}"]

    return title, "\n".join(summary_lines)

def generate_symbol_performance_summary(trades_df, unprofitable_pf_threshold): # RESTORED
    """Calculates performance per symbol and generates text summary."""
    title = "Performance per Symbol Analysis"
    summary_text = ""
    symbol_perf = pd.DataFrame()
    try:
        if 'Symbol' not in trades_df.columns:
            return title, "Error: 'Symbol' column not found.", symbol_perf
        symbol_perf_agg = {
            'Total_Trades': ('Symbol', 'size'), 'Total_Profit': ('Profit', 'sum'),
            'Win_Rate': ('Win', 'mean'), 'Avg_Profit': ('Profit', lambda x: x[x > 0].mean()),
            'Avg_Loss': ('Profit', lambda x: x[x <= 0].mean()),
            'Profit_Factor': ('Profit', lambda x: abs(x[x > 0].sum() / x[x <= 0].sum()) if x[x <= 0].sum() != 0 else (np.inf if x[x > 0].sum() > 0 else 0))}
        if '% Profit' in trades_df.columns: symbol_perf_agg['Avg_Pct_Return'] = ('% Profit', 'mean')
        if '# bars' in trades_df.columns: symbol_perf_agg['Avg_Bars_Held'] = ('# bars', 'mean')
        symbol_perf = trades_df.groupby('Symbol').agg(**symbol_perf_agg).fillna(0)
        symbol_perf['Win_Rate'] *= 100
        symbol_perf = symbol_perf.sort_values('Win_Rate', ascending=False)
        formatters = {'Total_Profit': '${:,.2f}'.format, 'Win_Rate': '{:.1f}%'.format,
                      'Avg_Profit': '${:,.2f}'.format, 'Avg_Loss': '${:,.2f}'.format,
                      'Profit_Factor': '{:.2f}'.format, 'Total_Trades': '{:.0f}'.format,
                      'Avg_Pct_Return': '{:.2f}%'.format, 'Avg_Bars_Held': '{:.1f}'.format}
        valid_formatters = {k: v for k, v in formatters.items() if k in symbol_perf.columns}
        with pd.option_context('display.max_rows', None, 'display.max_columns', None, 'display.width', 1000):
            symbol_perf_str = symbol_perf.to_string(formatters=valid_formatters)
        summary_text += "Performance per Symbol (Sorted by Win Rate):\n" + "="*80 + "\n" + symbol_perf_str
        problem_symbols = symbol_perf[(symbol_perf['Profit_Factor'] < unprofitable_pf_threshold) & (symbol_perf['Profit_Factor'] != np.inf)]
        if not problem_symbols.empty:
            problem_cols = [col for col in ['Total_Trades', 'Total_Profit', 'Win_Rate', 'Profit_Factor'] if col in problem_symbols.columns]
            with pd.option_context('display.max_rows', None, 'display.max_columns', None, 'display.width', 1000):
                problem_symbols_str = problem_symbols[problem_cols].sort_values('Profit_Factor').to_string(formatters=valid_formatters)
            summary_text += f"\n\nSymbols with Profit Factor < {unprofitable_pf_threshold:.2f} (Sorted by PF):\n" + "="*80 + "\n" + problem_symbols_str
        else: summary_text += f"\n\nNo symbols found with Profit Factor < {unprofitable_pf_threshold:.2f}.\n"
    except Exception as e:
        summary_text = f"Error in Symbol Performance: {e}\n{traceback.format_exc()}"
    return title, summary_text, symbol_perf

# ... (generate_prof_unprof_comparison, generate_losing_month_summary, etc. as before) ...
# Ensure they are complete from your original code. For brevity, I'll assume they are and focus on MC.
def generate_prof_unprof_comparison(trades_df, symbol_perf_df, profitable_threshold, unprofitable_threshold):
    title = "Profitable vs. Unprofitable Symbol Comparison"
    summary_lines = [f"Comparison based on PF >= {profitable_threshold:.2f} vs PF < {unprofitable_threshold:.2f}\n"]
    # ... (implementation from original)
    return title, "\n".join(summary_lines)

def generate_prof_unprof_comparison(trades_df, symbol_perf_df, profitable_threshold, unprofitable_threshold):
    """Generates text summary comparing profitable vs unprofitable symbols."""
    #print("Generating profitable vs unprofitable symbol comparison...")
    title = "Profitable vs. Unprofitable Symbol Comparison"
    summary_lines = [f"Comparison based on PF >= {profitable_threshold:.2f} vs PF < {unprofitable_threshold:.2f}\n"]
    try:
        if symbol_perf_df.empty or 'Profit_Factor' not in symbol_perf_df.columns:
            summary_lines.append("Could not perform comparison (Symbol performance data unavailable).")
            return title, "\n".join(summary_lines)

        profitable_symbols_list = symbol_perf_df[symbol_perf_df['Profit_Factor'] >= profitable_threshold].index.tolist()
        unprofitable_symbols_list = symbol_perf_df[symbol_perf_df['Profit_Factor'] < unprofitable_threshold].index.tolist()

        def get_group_stats(symbols_list, group_name):
             stats_lines = []
             if symbols_list:
                 group_trades = trades_df[trades_df['Symbol'].isin(symbols_list)]
                 stats_lines.append(f"{group_name} ({len(symbols_list)} symbols, {len(group_trades)} trades):")
                 if not group_trades.empty:
                     avg_pct = group_trades['% Profit'].mean() if '% Profit' in group_trades else np.nan
                     avg_bars = group_trades['# bars'].mean() if '# bars' in group_trades else np.nan
                     win_rate = group_trades['Win'].mean() if 'Win' in group_trades else np.nan
                     stats_lines.append(f"  Avg % Profit per Trade: {avg_pct:.2f}%" if pd.notna(avg_pct) else "  Avg % Profit per Trade: N/A")
                     stats_lines.append(f"  Avg Bars Held: {avg_bars:.2f}" if pd.notna(avg_bars) else "  Avg Bars Held: N/A")
                     stats_lines.append(f"  Overall Win Rate: {win_rate:.2%}" if pd.notna(win_rate) else "  Overall Win Rate: N/A")
                 else: stats_lines.append("  (No trades found for these symbols)")
             else: stats_lines.append(f"No symbols found for {group_name} criteria.")
             return stats_lines

        summary_lines.extend(get_group_stats(profitable_symbols_list, "Profitable Symbols"))
        summary_lines.append("")
        summary_lines.extend(get_group_stats(unprofitable_symbols_list, "Unprofitable Symbols"))
        summary_lines.append("\nInterpretation Notes:\n- Compare Avg Bars Held, Avg % Profit, Win Rate between groups.")

    except Exception as e:
        print(f"ERROR generating profitable/unprofitable comparison: {e}")
        traceback.print_exc()
        summary_lines = [f"Error encountered during comparison generation:\n{e}\n{traceback.format_exc()}"]
    return title, "\n".join(summary_lines)

# --- generate_losing_month_summary ---
def generate_losing_month_summary(trades_df, monthly_perf_df, top_n):
    """Generates text summary for top losing symbols during losing months."""
    #print("Generating losing month summary...")
    title = f"Top {top_n} Losing Symbol Contributors During Losing Months"
    summary_lines = []
    try:
        if monthly_perf_df is None or monthly_perf_df.empty or \
           not all(c in monthly_perf_df for c in ['Entry YrMo', 'Monthly_Profit']):
            summary_lines.append("Could not perform analysis (Monthly performance data unavailable or missing columns).")
            return title, "\n".join(summary_lines)
        if trades_df is None or trades_df.empty or \
           not all(c in trades_df for c in ['Entry YrMo', 'Symbol', 'Profit']):
            summary_lines.append("Could not perform analysis (Trades data missing required columns).")
            return title, "\n".join(summary_lines)

        if 'Entry YrMo' not in trades_df.columns:
            summary_lines.append("Error: 'Entry YrMo' column missing in trades_df.")
            return title, "\n".join(summary_lines)

        if not pd.api.types.is_string_dtype(monthly_perf_df['Entry YrMo']):
             if config.VERBOSE_DEBUG: print("Warning: monthly_perf_df['Entry YrMo'] is not string type. Attempting conversion.")
             monthly_perf_df['Entry YrMo'] = monthly_perf_df['Entry YrMo'].astype(str)

        losing_months_df = monthly_perf_df[monthly_perf_df['Monthly_Profit'] < 0].copy()

        if losing_months_df.empty:
            summary_lines.append("No losing months found based on monthly performance data.")
            return title, "\n".join(summary_lines)

        trades_df_temp = trades_df.copy()
        # Convert trade Entry YrMo (which might be Period or string) to string for matching
        trades_df_temp['Entry_YrMo_Str'] = trades_df_temp['Entry YrMo'].astype(str)

        losing_months_list = losing_months_df['Entry YrMo'].tolist()
        trades_in_losing_months = trades_df_temp[trades_df_temp['Entry_YrMo_Str'].isin(losing_months_list)].copy()


        if trades_in_losing_months.empty:
            summary_lines.append("Losing months found, but no trades occurred within those specific months.")
            return title, "\n".join(summary_lines)

        contrib_by_sym_detailed = trades_in_losing_months.groupby(['Entry_YrMo_Str', 'Symbol'])['Profit'].sum().reset_index()

        original_max_rows = pd.get_option('display.max_rows')
        original_max_cols = pd.get_option('display.max_columns')
        original_width = pd.get_option('display.width')
        pd.set_option('display.max_rows', None)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)

        for _, month_row in losing_months_df.sort_values('Entry YrMo').iterrows():
            month_str = month_row['Entry YrMo']
            monthly_total_loss = month_row['Monthly_Profit']
            loss_str = f"{monthly_total_loss:,.2f}" if pd.notna(monthly_total_loss) else "N/A"
            summary_lines.append(f"\nMonth: {month_str} (Total Loss: ${loss_str})")

            month_sym_losses = contrib_by_sym_detailed[contrib_by_sym_detailed['Entry_YrMo_Str'] == month_str].sort_values('Profit', ascending=True)
            top_contributors = month_sym_losses[month_sym_losses['Profit'] < 0].head(top_n)

            if not top_contributors.empty:
                summary_lines.append(top_contributors[['Symbol', 'Profit']].to_string(index=False, float_format='${:,.2f}'.format, header=[' Symbol', ' Contribution']))
            else:
                summary_lines.append("  (No specific symbols found with net loss contributing this month)")

        pd.set_option('display.max_rows', original_max_rows)
        pd.set_option('display.max_columns', original_max_cols)
        pd.set_option('display.width', original_width)

    except Exception as e:
        print(f"ERROR generating losing month summary: {e}")
        traceback.print_exc()
        summary_lines = [f"Error encountered during summary generation:\n{e}\n{traceback.format_exc()}"]

    return title, "\n".join(summary_lines)

# --- generate_wins_losses_summary ---
def generate_wins_losses_summary(trades_df, top_n):
    """Generates text summaries for the largest winning and losing trades."""
    #print("Generating largest wins/losses summaries...")
    results_list = []
    try:
        if trades_df.empty or 'Profit' not in trades_df.columns:
             results_list.append({'title': f'Top {top_n} Wins/Losses', 'data': 'Trades data empty or missing Profit.'})
             return results_list

        cols_to_display = ['Symbol', 'Date', 'Ex. date', '% Profit', 'Profit', '# bars']
        cols_exist = [col for col in cols_to_display if col in trades_df.columns]
        if not cols_exist or 'Profit' not in cols_exist:
             results_list.append({'title': f'Top {top_n} Wins/Losses', 'data': "Missing essential columns."})
             return results_list

        wl_formatters = {'Profit': '${:,.2f}'.format}
        if '% Profit' in cols_exist and pd.api.types.is_numeric_dtype(trades_df['% Profit']): wl_formatters['% Profit'] = '{:.2f}%'.format
        if '# bars' in cols_exist and pd.api.types.is_numeric_dtype(trades_df['# bars']): wl_formatters['# bars'] = '{:.0f}'.format
        if 'Date' in cols_exist and pd.api.types.is_datetime64_any_dtype(trades_df['Date']): wl_formatters['Date'] = '{:%Y-%m-%d}'.format
        if 'Ex. date' in cols_exist and pd.api.types.is_datetime64_any_dtype(trades_df['Ex. date']): wl_formatters['Ex. date'] = '{:%Y-%m-%d}'.format

        original_max_rows = pd.get_option('display.max_rows')
        original_max_cols = pd.get_option('display.max_columns')
        original_width = pd.get_option('display.width')
        pd.set_option('display.max_rows', None)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)

        def add_summary(sort_col, ascending, title_suffix):
            if sort_col not in trades_df.columns or not pd.api.types.is_numeric_dtype(trades_df[sort_col]):
                results_list.append({'title': f"Top {top_n} {title_suffix}", 'data': f"Skipped: '{sort_col}' column missing or invalid."})
                return
            sorted_df = trades_df.sort_values(sort_col, ascending=ascending).head(top_n)
            summary_data = sorted_df[cols_exist].to_string(index=False, formatters=wl_formatters)
            results_list.append({'title': f"Top {top_n} {title_suffix}", 'data': summary_data})

        add_summary('% Profit', False, "Largest Wins (Sorted by % Profit)")
        add_summary('% Profit', True, "Largest Losses (Sorted by % Profit)")
        add_summary('Profit', False, "Largest Wins (Sorted by $ Amount)")
        add_summary('Profit', True, "Largest Losses (Sorted by $ Amount)")

        pd.set_option('display.max_rows', original_max_rows)
        pd.set_option('display.max_columns', original_max_cols)
        pd.set_option('display.width', original_width)

    except Exception as e:
        print(f"ERROR generating wins/losses summary: {e}")
        traceback.print_exc()
        results_list.append({'title': f'Top {top_n} Wins/Losses', 'data': f"Error during summary generation:\n{e}\n{traceback.format_exc()}"})
    return results_list

# --- generate_duration_summary ---
def generate_duration_summary(trades_df):
    """Generates text summary for average trade duration for wins vs losses."""
    #print("Generating trade duration summary...")
    title = "Average Trade Duration Summary (# bars)"
    summary_text = "N/A"
    try:
        if trades_df.empty or '# bars' not in trades_df or 'Win' not in trades_df or \
           not pd.api.types.is_numeric_dtype(trades_df['# bars']):
            summary_text = "Skipped: Missing/invalid '# bars' or 'Win' column."
            return title, summary_text
        try: win_bool = trades_df['Win'].fillna(False).astype(bool)
        except: return title, "Skipped: Cannot convert 'Win' column to boolean."

        bars_series = trades_df['# bars'].dropna()
        if bars_series.empty: return title, "Skipped: '# bars' column has no valid data."

        avg_win_bars = bars_series[win_bool].mean()
        avg_loss_bars = bars_series[~win_bool].mean()
        win_text = f"Average bars held for Wins: {avg_win_bars:.2f}" if pd.notna(avg_win_bars) else "Average bars held for Wins: N/A"
        loss_text = f"Average bars held for Losses: {avg_loss_bars:.2f}" if pd.notna(avg_loss_bars) else "Average bars held for Losses: N/A"
        summary_text = f"{win_text}\n{loss_text}"
    except Exception as e:
        print(f"ERROR generating duration summary: {e}")
        traceback.print_exc()
        summary_text = f"Error during summary generation:\n{e}\n{traceback.format_exc()}"
    return title, summary_text

# --- generate_mae_mfe_summary ---
def generate_mae_mfe_summary(trades_df):
    """Generates text summary for average MAE (losses) and MFE (wins)."""
    #print("Generating MAE/MFE summary...")
    title = "Average MAE/MFE Summary"
    summary_text = "N/A"
    try:
        req_cols = ['MAE', 'MFE', 'Win']
        if trades_df.empty or not all(c in trades_df for c in req_cols) or \
           not pd.api.types.is_numeric_dtype(trades_df['MAE']) or \
           not pd.api.types.is_numeric_dtype(trades_df['MFE']):
            summary_text = "Skipped: Missing/invalid MAE, MFE, or Win columns."
            return title, summary_text
        try: win_bool = trades_df['Win'].fillna(False).astype(bool)
        except: return title, "Skipped: Cannot convert 'Win' column to boolean."

        mae_mfe_df = trades_df.dropna(subset=req_cols).copy()
        if mae_mfe_df.empty: return title, "Skipped: No valid data points after dropna."

        avg_mae_losses = mae_mfe_df.loc[~win_bool, 'MAE'].mean()
        avg_mfe_wins = mae_mfe_df.loc[win_bool, 'MFE'].mean()
        mae_text = f"Average MAE for Losses: {avg_mae_losses:.2f}%" if pd.notna(avg_mae_losses) else "Average MAE for Losses: N/A"
        mfe_text = f"Average MFE for Wins: {avg_mfe_wins:.2f}%" if pd.notna(avg_mfe_wins) else "Average MFE for Wins: N/A"
        summary_text = f"{mae_text}\n{mfe_text}"
    except Exception as e:
        print(f"ERROR generating MAE/MFE summary: {e}")
        traceback.print_exc()
        summary_text = f"Error during summary generation:\n{e}\n{traceback.format_exc()}"
    return title, summary_text

# --- generate_profit_dist_stats ---
def generate_profit_dist_stats(trades_df):
    """Generates text summary for profit distribution statistics."""
    #print("Generating profit distribution stats summary...")
    title = "Profit Distribution Stats (% Profit)"
    summary_text = "N/A"
    try:
        if trades_df.empty or '% Profit' not in trades_df or not pd.api.types.is_numeric_dtype(trades_df['% Profit']):
            summary_text = "Skipped: Missing/invalid '% Profit' column."
            return title, summary_text
        profit_pct_series = trades_df['% Profit'].dropna()
        if profit_pct_series.empty or len(profit_pct_series) < 3: # Skew/Kurt need > 2 points
             summary_text = "Skipped: Insufficient valid '% Profit' data for stats."
             return title, summary_text
        skewness = profit_pct_series.skew()
        kurt = profit_pct_series.kurt()
        summary_text = (f"Skewness of % Profit: {skewness:.2f}\n"
                        f"Kurtosis of % Profit: {kurt:.2f}")
    except Exception as e:
        print(f"ERROR generating profit distribution stats: {e}")
        traceback.print_exc()
        summary_text = f"Error during stats generation:\n{e}\n{traceback.format_exc()}"
    return title, summary_text

# --- generate_mc_summary ---
def generate_mc_summary(mc_results: dict, initial_equity: float, drawdown_as_negative: bool) -> tuple[str, str]:
    """Generates a text summary from Monte Carlo simulation results."""
    title = "Monte Carlo Simulation Summary"
    summary_lines = []
    num_sims = len(mc_results.get('final_equities', []))
    if num_sims == 0:
         summary_lines.append("Simulation results are not available or empty.")
         return title, "\n".join(summary_lines)

    summary_lines.append(f"Based on {num_sims} simulation paths.")
    summary_lines.append("-" * 40)
    try:
        # Helper to add lines, now aware of how different metrics are scaled/signed
        def add_stat_line(label, series_data, quantile_val=None, is_cagr_pct=False, is_dd_pct=False, is_money=False):
            line_lbl = f"  {label:<20}" # Adjusted for potentially longer percentile labels like "99th Percentile:"
            val_to_disp = "N/A"
            if series_data is not None and not series_data.empty and series_data.notna().any():
                 val = series_data.dropna().mean() if quantile_val is None else series_data.dropna().quantile(quantile_val)
                 if pd.notna(val):
                     try:
                         if is_money: val_to_disp = f"${val:,.2f}"
                         elif is_cagr_pct: val_to_disp = f"{val * 100:.2f}%" # CAGR is fractional, scale to %
                         elif is_dd_pct: val_to_disp = f"{val:.2f}%"       # DD% is already scaled, may be negative
                         else: val_to_disp = f"{val:.2f}" # Default formatting
                     except (ValueError, TypeError): val_to_disp = "Format Error"
            summary_lines.append(line_lbl + val_to_disp)

        fe_series = mc_results.get('final_equities')
        cagr_series = mc_results.get('cagrs')
        # These are now correctly signed (negative if drawdown_as_negative was true)
        # or positive magnitudes if drawdown_as_negative was false.
        # The display formatters will handle the '%' sign.
        dd_amt_series = mc_results.get('max_drawdown_amounts')
        dd_pct_series = mc_results.get('max_drawdown_percentages')
        le_series = mc_results.get('lowest_equities')

        # Percentile labels helper
        def get_p_label(p_val):
            if 10 <= p_val <= 20: return f"{p_val}th Percentile:"
            return {1:f"{p_val}st Percentile:", 2:f"{p_val}nd Percentile:", 3:f"{p_val}rd Percentile:"}.get(p_val % 10, f"{p_val}th Percentile:")

        summary_lines.append("Final Equity:")
        add_stat_line("Average:", fe_series, is_money=True)
        for p_val in config.MC_PERCENTILES: add_stat_line(get_p_label(p_val), fe_series, quantile_val=p_val/100.0, is_money=True)
        if fe_series is not None and not fe_series.empty:
            summary_lines.append(f"  {'Probability Profit':<20} {(fe_series.dropna() > initial_equity).mean():.2%}")
        summary_lines.append("")

        summary_lines.append("CAGR:")
        add_stat_line("Average:", cagr_series, is_cagr_pct=True)
        for p_val in config.MC_PERCENTILES: add_stat_line(get_p_label(p_val), cagr_series, quantile_val=p_val/100.0, is_cagr_pct=True)
        summary_lines.append("")
        
        summary_lines.append("Maximum Drawdown ($):") # Values are already signed as per drawdown_as_negative
        add_stat_line("Average:", dd_amt_series, is_money=True)
        for p_val in config.MC_PERCENTILES: add_stat_line(get_p_label(p_val), dd_amt_series, quantile_val=p_val/100.0, is_money=True)
        summary_lines.append("")
        
        summary_lines.append("Maximum Drawdown (%):") # Values are already signed and scaled
        add_stat_line("Average:", dd_pct_series, is_dd_pct=True)
        for p_val in config.MC_PERCENTILES: add_stat_line(get_p_label(p_val), dd_pct_series, quantile_val=p_val/100.0, is_dd_pct=True)
        summary_lines.append("")
        
        summary_lines.append("Lowest Equity Reached:")
        add_stat_line("Average:", le_series, is_money=True)
        for p_val in config.MC_PERCENTILES: add_stat_line(get_p_label(p_val), le_series, quantile_val=p_val/100.0, is_money=True)

    except Exception as e:
        print(f"ERROR generating MC summary text: {e}") # Added for debugging
        traceback.print_exc() # Added for debugging
        summary_lines.append(f"\nError encountered during MC summary generation:\n{e}\n{traceback.format_exc()}")

    return title, "\n".join(summary_lines)

# --- generate_mc_percentile_table ---
def generate_mc_percentile_table(mc_results: dict, drawdown_as_negative: bool) -> tuple[str, str]:
    """Generates a formatted text table of Monte Carlo percentile statistics."""
    title = "Monte Carlo Percentile Statistics"
    if not mc_results or 'mc_detailed_percentiles' not in mc_results:
        return title, "MC detailed percentiles data not found."
    detailed_stats = mc_results['mc_detailed_percentiles']
    if not isinstance(detailed_stats, dict) or not detailed_stats:
        return title, "MC detailed percentiles data is invalid."
    try:
        df = pd.DataFrame(detailed_stats)
        column_map = {'Final Equity': 'Final Equity', 'CAGR': 'Annual Return %',
                        'Max Drawdown $': 'Max. Drawdown $', 'Max Drawdown %': 'Max. Drawdown %',
                        'Lowest Equity': 'Lowest Eq.'}
        
        # Ensure columns are in the desired order and renamed
        ordered_mc_keys = ['Final Equity', 'CAGR', 'Max Drawdown $', 'Max Drawdown %', 'Lowest Equity']
        df_ordered = df[[col for col in ordered_mc_keys if col in df.columns]].copy() # Create a copy to avoid SettingWithCopyWarning
        df_ordered.rename(columns=column_map, inplace=True)
        
        percentile_idx_config = [f"{p}th" for p in config.MC_PERCENTILES]
        # Ensure the index for df_final uses only percentiles that are actually in df_ordered after potential drops
        # And maintain the order from config.MC_PERCENTILES
        available_percentiles_in_df = [p_label for p_label in percentile_idx_config if p_label in df_ordered.index]
        df_final = df_ordered.reindex(available_percentiles_in_df)
        df_final.index = [p.replace('th', '%') for p in df_final.index]

        def fmt_cagr(x): return f"{x*100:.2f}%" if pd.notna(x) else 'N/A'
        def fmt_dd_pct(x): return f"{x:.2f}%" if pd.notna(x) else 'N/A' 
        def fmt_money(x): return f"${x:,.0f}" if pd.notna(x) else 'N/A'

        formatters_map = {'Final Equity': fmt_money, 'Annual Return %': fmt_cagr,
                      'Max. Drawdown $': fmt_money, 'Max. Drawdown %': fmt_dd_pct,
                      'Lowest Eq.': fmt_money}
        
        # Apply formatters only for columns that exist in df_final
        active_formatters = {col: fmt_func for col, fmt_func in formatters_map.items() if col in df_final.columns}

        with pd.option_context('display.max_rows', None, 'display.max_columns', None, 'display.width', 120):
            # Pass the filtered formatters dictionary
            table_string = df_final.to_string(formatters=active_formatters, justify='right', na_rep='N/A')
            
    except Exception as e:
        print(f"ERROR generating MC percentile table: {e}") # Added print for debugging
        traceback.print_exc() # Added traceback
        table_string = f"Error generating MC percentile table: {e}\n{traceback.format_exc()}"
    return title, table_string

# --- generate_pdf_report ---
def generate_pdf_report(report_sections, output_path, report_title_suffix=""):
    """
    Generates the PDF report from a list of sections, handling pagination for text.

    Args:
        report_sections (list): List of dictionaries defining report content.
                                Each dict: {'type': 'text'|'plot', 'title': str, 'data': str|Figure}
        output_path (str): Path to save the output PDF file.
        report_title_suffix (str, optional): Suffix to add to the main report title. Defaults to "".
    """
    print(f"\n--- Generating PDF Report: {output_path} ---")
    pdf_pages = None
    page_counter = 1 # Start page numbering at 1

    # --- Create list of pages for TOC ---
    toc_entries = []
    current_content_page = 2 # Content starts on page 2 (after TOC)
    for i, section in enumerate(report_sections):
        title = section.get('title', f'Untitled Section {i+1}')
        section_type = section.get('type', 'text')
        data = section.get('data', '')

        # Estimate pages needed for this section
        pages_for_section = 1
        if section_type == 'text' and isinstance(data, str):
            lines = data.split('\n')
            if len(lines) > config.LINES_PER_TEXT_PAGE:
                pages_for_section = math.ceil(len(lines) / config.LINES_PER_TEXT_PAGE)

        toc_entries.append({'title': title, 'start_page': current_content_page})
        current_content_page += pages_for_section

    try:
        # Ensure output directory exists before creating PdfPages object
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        pdf_pages = PdfPages(output_path)

        # --- Create Table of Contents Page ---
        if config.VERBOSE_DEBUG: print("Creating Table of Contents figure...")
        fig_toc = plt.figure(figsize=config.A4_LANDSCAPE)
        plt.axis('off')

        main_title = f"Trade Analysis Report{report_title_suffix}"
        plt.text(0.01, 0.96, main_title, weight='bold', size=12, ha='left', va='top')
        plt.text(0.01, 0.93, "Table of Contents", weight='bold', size=11, ha='left', va='top')

        # ******* TOC LAYOUT FIX START *******
        start_y_toc = 0.88
        line_height_toc = 0.018
        current_y_toc = start_y_toc
        title_x = 0.01      # X position for titles (left aligned)
        page_num_x = 0.98   # X position for page numbers (right aligned)
        max_title_width = 0.8 # Max proportion of width for title to prevent overlap

        if toc_entries:
            for entry in toc_entries:
                title_str = str(entry['title'])
                page_num = entry['start_page']

                # Truncate title if too long (optional, but good practice)
                # This is a simple character limit, might need adjustment based on font
                max_chars = 100
                if len(title_str) > max_chars:
                    title_str = title_str[:max_chars-3] + "..."

                # Plot title (left aligned)
                plt.text(title_x, current_y_toc, title_str,
                         family='monospace', size=8, ha='left', va='top', wrap=False,
                         clip_on=True) # Use clip_on=True

                # Plot page number (right aligned)
                plt.text(page_num_x, current_y_toc, f"Page {page_num}",
                         family='monospace', size=8, ha='right', va='top', wrap=False)

                current_y_toc -= line_height_toc
                if current_y_toc < 0.02:
                    print("Warning: TOC entries exceeded page height.")
                    break # Stop if going off page
        else:
            plt.text(title_x, current_y_toc, "No report sections generated.",
                     family='monospace', size=8, ha='left', va='top', wrap=False)
        # ******* TOC LAYOUT FIX END *******

        # Save TOC as Page 1
        utils.save_pdf_fig(fig_toc, pdf_pages, f"Page {page_counter}") # Use current page counter
        page_counter += 1
        if config.VERBOSE_DEBUG: print("Added Table of Contents to PDF (Page 1).")


        # --- Add Content Pages ---
        for i, section in enumerate(report_sections):
             section_title = section.get('title', f'Untitled Section {i+1}')
             section_type = section.get('type', 'text')
             section_data = section.get('data', '')
             page_num_str = f"Page {page_counter}" # Use running counter

             if config.VERBOSE_DEBUG: print(f"Adding '{section_title}' to PDF ({page_num_str})...")

             try:
                 if section_type == 'plot':
                     fig_plot = section_data
                     if isinstance(fig_plot, plt.Figure):
                          # Save the plot figure to PDF (this will also close it)
                          utils.save_pdf_fig(fig_plot, pdf_pages, page_num_str)
                          page_counter += 1
                     else:
                          print(f"WARNING: Invalid plot object for '{section_title}'. Creating placeholder PDF page.")
                          fig_placeholder = create_text_figure([f"Plot generation failed or data invalid for:", section_title], f"Plot Error: {section_title}")
                          utils.save_pdf_fig(fig_placeholder, pdf_pages, page_num_str)
                          page_counter += 1

                 elif section_type == 'text':
                     if not isinstance(section_data, str):
                          section_data = str(section_data) # Ensure it's a string

                     lines = section_data.split('\n')
                     num_lines = len(lines)
                     lines_per_page = config.LINES_PER_TEXT_PAGE

                     # Calculate how many pages this text section will take
                     num_pages_for_section = math.ceil(num_lines / lines_per_page)
                     if num_pages_for_section == 0: num_pages_for_section = 1 # Ensure at least one page even if empty

                     for page_index in range(num_pages_for_section):
                         start_line = page_index * lines_per_page
                         end_line = start_line + lines_per_page
                         lines_chunk = lines[start_line:end_line]

                         # Add page number to title if multiple pages for this section
                         page_specific_title = section_title
                         if num_pages_for_section > 1:
                             page_specific_title += f" (Page {page_index + 1} of {num_pages_for_section})"

                         # Create text figure for this chunk
                         fig_text = create_text_figure(lines_chunk, page_specific_title)

                         # Save the figure for this page chunk (this will also close it)
                         page_num_str_current = f"Page {page_counter}"
                         utils.save_pdf_fig(fig_text, pdf_pages, page_num_str_current)
                         page_counter += 1 # Increment page number for each chunk saved

                 else:
                      print(f"WARNING: Unknown section type '{section_type}' for title '{section_title}'. Skipping PDF page.")

             except Exception as page_err:
                  print(f"ERROR: Failed to add section '{section_title}' to PDF (Page {page_counter}). Error: {page_err}")
                  traceback.print_exc()
                  # Attempt to close any potentially open figures from the failed section
                  if section_type == 'plot' and isinstance(section_data, plt.Figure) and plt.fignum_exists(section_data.number):
                      plt.close(section_data)
                  plt.close('all') # Close any other dangling figures just in case
                  try:
                       # Add an error placeholder page to the PDF
                       page_num_str_err = f"Page {page_counter}"
                       error_details = f"Error details:\n{page_err}\n\n{traceback.format_exc()}"
                       fig_err_page = create_text_figure([f"Could not render section '{section_title}'.", "", error_details[:1500]], f"Error Rendering Section: {section_title}") # Limit traceback length
                       utils.save_pdf_fig(fig_err_page, pdf_pages, page_num_str_err)
                       page_counter += 1 # Increment even for error page
                  except Exception as placeholder_err:
                       print(f"ERROR: Failed to add error placeholder page to PDF. {placeholder_err}")
                       plt.close('all')

    except Exception as pdf_err:
         print(f"FATAL: Error during PDF file creation process for '{output_path}': {pdf_err}")
         traceback.print_exc()
    finally:
        if pdf_pages is not None:
            try:
                pdf_pages.close() # Close the PDF file handle
                print(f"PDF generation process finished. Report saved to '{output_path}'")
            except Exception as close_err:
                print(f"Error closing PDF file '{output_path}': {close_err}")
        # Ensure all matplotlib figures are closed, regardless of PDF success/failure
        plt.close('all')


# --- generate_markdown_report ---
def generate_markdown_report(report_sections, output_md_path, output_image_dir):
    """
    Generates a Markdown report from a list of sections.

    Args:
        report_sections (list): List of dictionaries defining report content.
                                Each dict: {'type': 'text'|'plot', 'title': str, 'data': str|Figure}
        output_md_path (str): Path to save the output Markdown (.md) file.
        output_image_dir (str): Path to the directory where plot images should be saved.
    """
    print(f"\n--- Generating Markdown Report: {output_md_path} ---")
    md_content = []
    # Ensure the image directory exists
    os.makedirs(output_image_dir, exist_ok=True)
    image_save_counter = 0 # To create unique filenames for plots

    try:
        # Add main title (optional, could be filename)
        report_title = os.path.splitext(os.path.basename(output_md_path))[0]
        md_content.append(f"# {report_title.replace('_', ' ').title()}")
        md_content.append("---")

        for i, section in enumerate(report_sections):
            section_title = section.get('title', f'Untitled Section {i+1}')
            section_type = section.get('type', 'text')
            section_data = section.get('data', '')

            md_content.append(f"\n## {section_title}\n")

            if section_type == 'text':
                if isinstance(section_data, str):
                    # Wrap text data in a code block for monospace formatting
                    md_content.append("```text")
                    md_content.append(section_data.strip())
                    md_content.append("```")
                else:
                    md_content.append("```text")
                    md_content.append(f"Warning: Non-string data provided for text section '{section_title}'.")
                    md_content.append(str(section_data))
                    md_content.append("```")

            elif section_type == 'plot':
                fig_plot = section_data
                if isinstance(fig_plot, plt.Figure):
                    image_save_counter += 1
                    # Sanitize title for filename
                    safe_title = re.sub(r'[^\w\-]+', '_', section_title).strip('_').lower()
                    if not safe_title: safe_title = f"plot_{i+1}" # Fallback filename
                    image_filename = f"{safe_title}_{image_save_counter}.{config.MARKDOWN_PLOT_FORMAT}"
                    image_path_abs = os.path.join(output_image_dir, image_filename)

                    # Save the figure as an image (function ensures directory exists)
                    # This function does NOT close the figure
                    save_success = utils.save_figure_as_image(fig_plot, image_path_abs)

                    if save_success:
                        # Get relative path from MD file to image directory
                        md_dir = os.path.dirname(output_md_path)
                        try:
                            image_path_rel = os.path.relpath(image_path_abs, md_dir)
                            # Convert backslashes to forward slashes for Markdown compatibility
                            image_path_rel = image_path_rel.replace(os.sep, '/')
                        except ValueError:
                             # Handle case where paths are on different drives (Windows)
                             print(f"Warning: Cannot create relative path for image '{image_filename}'. Using absolute path (might not work everywhere).")
                             image_path_rel = image_path_abs # Fallback to absolute

                        # Add Markdown image link
                        md_content.append(f"![{section_title}]({image_path_rel})")
                    else:
                        md_content.append(f"*Error: Could not save plot image for '{section_title}'.*")
                        # Figure might still be open, PDF generation will handle closing it.
                else:
                    md_content.append(f"*Warning: Invalid plot object for '{section_title}'. Cannot generate image.*")

            else:
                md_content.append(f"*Warning: Unknown section type '{section_type}' for title '{section_title}'. Skipping Markdown content.*")

        # --- Write Markdown File ---
        with open(output_md_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(md_content))
        print(f"Markdown report saved to '{output_md_path}'")

    except Exception as md_err:
        print(f"FATAL: Error generating Markdown report '{output_md_path}': {md_err}")
        traceback.print_exc()
        # Write error message to the MD file if possible
        try:
            with open(output_md_path, 'w', encoding='utf-8') as f:
                f.write(f"# Report Generation Error\n\n")
                f.write(f"An error occurred while generating the Markdown report:\n\n")
                f.write("```\n")
                f.write(f"{md_err}\n\n")
                f.write(traceback.format_exc())
                f.write("\n```")
        except Exception as write_err:
            print(f"ERROR: Could not even write error details to Markdown file '{output_md_path}': {write_err}")

    # Note: Figures are intentionally NOT closed here.
    # They need to remain open for the PDF generation step which follows.
    # generate_pdf_report calls utils.save_pdf_fig which handles closing.

def extract_key_metrics_for_console(report_sections: list) -> dict:
    """
    Extracts the key performance metrics from the report sections.

    Args:
        report_sections (list): The list of report sections generated by the analysis.

    Returns:
        dict: A dictionary containing the extracted metrics, or an empty dict if not found.
    """
    metrics = {}
    try:
        for section in report_sections:
            if section['title'] == "Overall Performance Metrics":
                summary_text = section.get('data', '')
                lines = summary_text.split('\n')
                for line in lines:
                    if ":" in line:
                        label, value = line.split(":", 1)
                        label = label.strip()
                        value = value.strip()
                        try:
                            # Attempt to convert to float, if possible
                            metrics[label] = float(value.replace("$", "").replace("%", "").replace(",", ""))
                        except ValueError:
                            metrics[label] = value
            elif section['title'] == "Monte Carlo: Percentile Analysis":
                summary_text = section.get('data', '')
                lines = summary_text.split('\n')
                for line in lines:
                    if "Average" in line:
                      label_part = line.split("Average", 1)[0].strip()
                      if label_part in ['CAGR', 'Final Equity', 'Max Drawdown %']:
                        value_str = line.split("Average", 1)[1].strip()
                        try:
                            # Extract the numeric value
                            value = float(re.search(r'[-+]?\d*\.\d+|\d+', value_str).group())
                            metrics[f"MC Average {label_part}"] = value
                        except (ValueError, AttributeError):
                            metrics[f"MC Average {label_part}"] = value_str

        # Add specific metrics with more robust extraction
        for section in report_sections:
            if section['title'] == "Overall Performance Metrics":
                summary_text = section.get('data', '')
                # Use regex to find specific metrics more reliably
                cagr_match = re.search(r"CAGR:\s*([-+]?\d+\.\d+)%", summary_text)
                if cagr_match:
                    metrics["CAGR"] = float(cagr_match.group(1))
                max_dd_match = re.search(r"Max Equity Drawdown:\s*([-+]?\d+\.\d+)%", summary_text)
                if max_dd_match:
                    metrics["Max Equity Drawdown"] = float(max_dd_match.group(1))

    except Exception as e:
        print(f"Error extracting key metrics: {e}")
        traceback.print_exc()  # Print the traceback
    return metrics