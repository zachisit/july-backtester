import os
import platform
import subprocess
import traceback
from datetime import datetime
from typing import List, Dict, Any, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import default_config as config
from . import calculations
from . import data_handler
from . import plotting
from . import report_generator
from . import utils


def generate_trade_report(trades_df: pd.DataFrame, output_dir: str, report_name: str, config_params: dict = None):
    """Generates a full PDF + Markdown trade analysis report from a DataFrame.

    Args:
        trades_df: DataFrame with columns matching the analyzer's expected format
                   (Date, Ex. date, Profit, % Profit, Price, Ex. Price, etc.)
        output_dir: Root directory where the report folder will be created.
        report_name: Name for the report subfolder and output files.
        config_params: Optional dict of overrides for default_config values.
                       Keys should match the uppercase attribute names in default_config.
    """
    if config_params is None:
        config_params = {}

    # Apply config overrides onto the default_config module so all downstream
    # modules (plotting, report_generator, calculations, etc.) pick them up.
    _original_config_values = {}
    for key, value in config_params.items():
        if hasattr(config, key):
            _original_config_values[key] = getattr(config, key)
        setattr(config, key, value)

    try:
        _run_analysis(trades_df, output_dir, report_name, config_params)
    finally:
        # Restore original config values
        for key, value in _original_config_values.items():
            setattr(config, key, value)
        for key in config_params:
            if key not in _original_config_values:
                try:
                    delattr(config, key)
                except AttributeError:
                    pass


def _run_analysis(trades_df_raw: pd.DataFrame, output_dir: str, report_name: str, config_params: dict):
    """Internal analysis runner — assumes config has already been patched."""

    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")

    initial_equity = config_params.get('INITIAL_EQUITY', config.INITIAL_EQUITY)
    benchmark_ticker = config_params.get('BENCHMARK_TICKER', config.BENCHMARK_TICKER)
    risk_free_rate = config_params.get('RISK_FREE_RATE', config.RISK_FREE_RATE)
    trading_days = config_params.get('TRADING_DAYS_PER_YEAR', config.TRADING_DAYS_PER_YEAR)
    rolling_window = config_params.get('ROLLING_WINDOW', config.ROLLING_WINDOW)
    mc_use_pct = config_params.get('MC_USE_PERCENTAGE_RETURNS', config.MC_USE_PERCENTAGE_RETURNS)
    mc_simulations = config_params.get('MC_SIMULATIONS', config.MC_SIMULATIONS)
    mc_dd_neg = config_params.get('MC_DRAWDOWN_AS_NEGATIVE', config.MC_DRAWDOWN_AS_NEGATIVE)
    wfa_split_ratio = config_params.get('WFA_SPLIT_RATIO', getattr(config, 'WFA_SPLIT_RATIO', None))
    unprofitable_pf = config_params.get('UNPROFITABLE_PF_THRESHOLD', config.UNPROFITABLE_PF_THRESHOLD)
    profitable_pf = config_params.get('PROFITABLE_PF_THRESHOLD', config.PROFITABLE_PF_THRESHOLD)
    top_n_losing = config_params.get('TOP_N_LOSING_SYMBOLS', config.TOP_N_LOSING_SYMBOLS)
    top_n_trades = config_params.get('TOP_N_TRADES_LIST', config.TOP_N_TRADES_LIST)
    md_image_subdir = config_params.get('MARKDOWN_IMAGE_SUBDIR', config.MARKDOWN_IMAGE_SUBDIR)

    # --- Build output paths ---
    try:
        os.makedirs(output_dir, exist_ok=True)
        output_run_directory = os.path.join(output_dir, report_name)
        os.makedirs(output_run_directory, exist_ok=True)
        print(f"Report directory: {output_run_directory}")

        output_pdf_path = os.path.join(output_run_directory, f"{report_name}.pdf")
        output_md_path = os.path.join(output_run_directory, f"{report_name}.md")
        output_image_directory = os.path.join(output_run_directory, md_image_subdir)
    except OSError as oe:
        print(f"FATAL ERROR: Could not create output directory. Error: {oe}")
        return
    except Exception as path_e:
        print(f"FATAL ERROR: Unexpected error setting up output paths. Error: {path_e}")
        traceback.print_exc()
        return

    print(f"\n--- Starting Analysis Run ({timestamp_str}) ---")
    report_sections: List[Dict[str, Any]] = []
    trades_df: Optional[pd.DataFrame] = None
    daily_equity: pd.Series = pd.Series(dtype=float)
    daily_returns: pd.Series = pd.Series(dtype=float)
    benchmark_df: Optional[pd.DataFrame] = None
    benchmark_returns: pd.Series = pd.Series(dtype=float)
    monthly_perf: pd.DataFrame = pd.DataFrame()
    symbol_perf: pd.DataFrame = pd.DataFrame()
    total_duration_years: float = 0.0
    pdf_save_attempted = False
    md_save_attempted = False
    _temp_noise_img_path = None

    try:
        # --- Clean the provided DataFrame (no CSV loading) ---
        print("\n--- Attempting Data Cleaning ---")
        trades_df, cleaning_summary = data_handler.clean_trades_data(trades_df_raw, initial_equity)
        report_sections.append({'type': 'text', 'title': "Data Cleaning Summary", 'data': cleaning_summary})

        if trades_df is None or trades_df.empty or len(trades_df) < 2:
            print("Exiting: Not enough valid trade data after cleaning.")
            report_sections.append({'type': 'text', 'title': "Analysis Halted", 'data': "Not enough valid trade data after cleaning (< 2 trades)."})
            raise StopIteration("Not enough valid trade data after cleaning.")

        start_dt = trades_df['Date'].min()
        end_dt = trades_df['Ex. date'].max()
        if pd.notna(start_dt) and pd.notna(end_dt) and end_dt > start_dt:
            total_duration_years = (end_dt - start_dt).days / 365.25
        else:
            print("Warning: Cannot accurately calculate strategy duration for CAGR.")
            total_duration_years = 0.0

        # --- WFA ---
        wfa_split_date: str | None = None
        wfa_result: dict = {}
        if wfa_split_ratio and 0 < float(wfa_split_ratio) < 1 and pd.notna(start_dt) and pd.notna(end_dt):
            try:
                import sys as _sys, os as _os
                _proj_root = _os.path.abspath(_os.path.join(_os.path.dirname(__file__), ".."))
                if _proj_root not in _sys.path:
                    _sys.path.insert(0, _proj_root)
                from helpers.wfa import get_split_date, split_trades, evaluate_wfa

                actual_start = start_dt.strftime("%Y-%m-%d")
                actual_end   = end_dt.strftime("%Y-%m-%d")
                wfa_split_date = get_split_date(actual_start, actual_end, float(wfa_split_ratio))

                # Build minimal trade dicts compatible with helpers/wfa
                wfa_trade_dicts = [
                    {"ExitDate": row["Ex. date"].strftime("%Y-%m-%d"), "Profit": row["Profit"]}
                    for _, row in trades_df.iterrows()
                    if pd.notna(row.get("Ex. date")) and pd.notna(row.get("Profit"))
                ]
                is_trades, oos_trades = split_trades(wfa_trade_dicts, wfa_split_date)
                wfa_result = evaluate_wfa(is_trades, oos_trades, initial_equity)
                print(f"WFA: split_date={wfa_split_date}  IS={len(is_trades)} trades  OOS={len(oos_trades)} trades  verdict={wfa_result.get('wfa_verdict')}")
            except Exception as wfa_err:
                print(f"WFA Warning: could not compute WFA metrics: {wfa_err}")

        daily_equity, daily_returns = data_handler.calculate_daily_returns(trades_df, initial_equity)
        benchmark_df = data_handler.download_benchmark_data(benchmark_ticker, start_dt, end_dt)
        if benchmark_df is not None and not benchmark_df.empty:
            benchmark_daily_ret_raw = benchmark_df['Benchmark_Price'].pct_change()
            if not daily_returns.empty:
                benchmark_returns = benchmark_daily_ret_raw.reindex(daily_returns.index).dropna()
                if benchmark_returns.empty:
                    benchmark_returns = pd.Series(dtype=float)
            else:
                benchmark_returns = pd.Series(dtype=float)
        else:
            benchmark_returns = pd.Series(dtype=float)

        # Resolve equity series for drawdown — prefer the backtester's daily MTM
        # portfolio_timeline (passed via PORTFOLIO_TIMELINE) so that all drawdown
        # figures in the PDF match the terminal's max_drawdown exactly.
        _portfolio_timeline = config_params.get('PORTFOLIO_TIMELINE')
        if _portfolio_timeline is not None and not _portfolio_timeline.empty:
            equity_for_dd_calc = _portfolio_timeline
        elif not daily_equity.empty:
            equity_for_dd_calc = daily_equity
        else:
            equity_for_dd_calc = pd.Series(dtype=float)

        print("\n--- Generating Report Sections ---")
        title, summary = report_generator.generate_overall_metrics_summary(
            trades_df, daily_returns, benchmark_returns, benchmark_df, equity_for_dd_calc,
            benchmark_ticker, initial_equity, risk_free_rate, trading_days
        )
        report_sections.append({'type': 'text', 'title': title, 'data': summary})

        # WFA section — immediately after overall metrics
        wfa_title, wfa_summary = report_generator.generate_wfa_summary(
            wfa_result, wfa_split_date, wfa_split_ratio
        )
        report_sections.append({'type': 'text', 'title': wfa_title, 'data': wfa_summary})

        # --- Stress Test Analysis — Noise Injection Overlay ---
        _noise_csv_path = config_params.get('NOISE_CSV_PATH')
        if _noise_csv_path and os.path.isfile(_noise_csv_path):
            try:
                import sys as _sys
                _proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                if _proj_root not in _sys.path:
                    _sys.path.insert(0, _proj_root)
                from helpers.noise import generate_noise_chart_from_csv

                _temp_noise_img_path = os.path.join(os.path.dirname(_noise_csv_path), "temp_noise_overlay.png")
                generate_noise_chart_from_csv(_noise_csv_path, _temp_noise_img_path)

                # Load PNG back as a matplotlib figure for embedding in the PDF.
                # Use the same (12, 4) banner dimensions as the saved chart so the
                # PDF page respects the natural 3:1 aspect ratio without distortion.
                _img = plt.imread(_temp_noise_img_path)
                _fig_noise = plt.figure(figsize=(12, 4))
                _ax_noise = _fig_noise.add_subplot(111)
                _ax_noise.imshow(_img)
                _ax_noise.axis('off')
                _fig_noise.tight_layout(pad=0)
                report_sections.append({
                    'type': 'plot',
                    'title': 'Stress Test Analysis — Noise Injection Overlay',
                    'data': _fig_noise,
                })
                print("Noise overlay chart embedded in report.")
            except Exception as _noise_err:
                print(f"Noise overlay warning: {_noise_err}")
                report_sections.append({
                    'type': 'text',
                    'title': 'Stress Test Analysis — Noise Injection Overlay',
                    'data': f"Skipped: {_noise_err}",
                })

        equity_for_dd_plot = trades_df.get('Equity')
        equity_dd_amount, equity_dd_percent, max_equity_dd_amt, max_equity_dd_pct = calculations.calculate_equity_drawdown(equity_for_dd_calc)

        dd_cum_profit = trades_df.get('Cumulative_Profit')
        dd_dates = trades_df.get('Ex. date')
        max_dd_profit_amt, max_dd_profit_pct, dd_periods_df = np.nan, np.nan, pd.DataFrame()
        if dd_cum_profit is not None and dd_dates is not None and not dd_cum_profit.empty and not dd_dates.empty:
            dd_amount_profit, dd_percent_profit, max_dd_profit_amt, max_dd_profit_pct, dd_periods_df = calculations.calculate_drawdown_details(dd_cum_profit, dd_dates)
        else:
            print("Warning: Could not calculate detailed profit-based drawdown.")

        title, summary = report_generator.generate_drawdown_summary(dd_periods_df, max_dd_profit_pct, max_equity_dd_pct, mc_dd_neg)
        report_sections.append({'type': 'text', 'title': title, 'data': summary})

        title, summary, symbol_perf = report_generator.generate_symbol_performance_summary(trades_df, unprofitable_pf)
        report_sections.append({'type': 'text', 'title': title, 'data': summary})

        title, summary = report_generator.generate_prof_unprof_comparison(trades_df, symbol_perf, profitable_pf, unprofitable_pf)
        report_sections.append({'type': 'text', 'title': title, 'data': summary})

        monthly_perf = pd.DataFrame()
        if 'Entry YrMo' in trades_df.columns and trades_df['Entry YrMo'].notna().any():
            try:
                monthly_grouped = trades_df.dropna(subset=['Entry YrMo']).groupby('Entry YrMo').agg(
                    Monthly_Profit=('Profit', 'sum'), Num_Trades=('Profit', 'size')
                )
                monthly_grouped.index.name = 'Entry YrMo_Period'
                monthly_perf = monthly_grouped.reset_index()
                monthly_perf['Entry YrMo'] = monthly_perf['Entry YrMo_Period'].astype(str)
                if not monthly_perf.empty:
                    fig_monthly = plotting.plot_monthly_performance(monthly_perf)
                    report_sections.append({'type': 'plot', 'title': 'Monthly Net Profit Plot', 'data': fig_monthly})
                else:
                    report_sections.append({'type': 'text', 'title': 'Monthly Net Profit Plot', 'data': "Skipped: No monthly data."})
            except Exception as e:
                report_sections.append({'type': 'text', 'title': 'Monthly Net Profit Plot', 'data': f"Error: {e}"})
        else:
            report_sections.append({'type': 'text', 'title': 'Monthly Net Profit Plot', 'data': "Skipped: 'Entry YrMo' data not available."})

        title, summary = report_generator.generate_losing_month_summary(trades_df, monthly_perf, top_n_losing)
        report_sections.append({'type': 'text', 'title': title, 'data': summary})
        results_wl = report_generator.generate_wins_losses_summary(trades_df, top_n_trades)
        for section in results_wl:
            report_sections.append(section)

        if '# bars' in trades_df.columns and pd.api.types.is_numeric_dtype(trades_df['# bars']):
            fig_dur_hist = plotting.plot_duration_histogram(trades_df)
            report_sections.append({'type': 'plot', 'title': 'Trade Duration Histogram', 'data': fig_dur_hist})
            fig_dur_scatter = plotting.plot_duration_scatter(trades_df)
            report_sections.append({'type': 'plot', 'title': 'Profit % vs. Duration Scatter Plot', 'data': fig_dur_scatter})
            title, summary = report_generator.generate_duration_summary(trades_df)
            report_sections.append({'type': 'text', 'title': title, 'data': summary})
        else:
            report_sections.append({'type': 'text', 'title': 'Trade Duration Analysis', 'data': "Skipped: '# bars' missing."})

        mae_valid = 'MAE' in trades_df.columns and pd.api.types.is_numeric_dtype(trades_df['MAE'])
        mfe_valid = 'MFE' in trades_df.columns and pd.api.types.is_numeric_dtype(trades_df['MFE'])
        profit_pct_valid = '% Profit' in trades_df.columns and pd.api.types.is_numeric_dtype(trades_df['% Profit'])
        win_valid = 'Win' in trades_df.columns
        if mae_valid and mfe_valid and profit_pct_valid and win_valid:
            fig_mae_mfe = plotting.plot_mae_mfe(trades_df)
            report_sections.append({'type': 'plot', 'title': 'MAE/MFE Analysis Plot', 'data': fig_mae_mfe})
            title, summary = report_generator.generate_mae_mfe_summary(trades_df)
            report_sections.append({'type': 'text', 'title': title, 'data': summary})
        else:
            report_sections.append({'type': 'text', 'title': 'MAE/MFE Analysis', 'data': "Skipped: MAE/MFE data missing."})

        if '% Profit' in trades_df.columns and pd.api.types.is_numeric_dtype(trades_df['% Profit']):
            fig_profit_dist = plotting.plot_profit_distribution(trades_df)
            report_sections.append({'type': 'plot', 'title': 'Profit Distribution Plot', 'data': fig_profit_dist})
            title, summary = report_generator.generate_profit_dist_stats(trades_df)
            report_sections.append({'type': 'text', 'title': title, 'data': summary})
        else:
            report_sections.append({'type': 'text', 'title': 'Profit Distribution Analysis', 'data': "Skipped: '% Profit' missing."})

        # --- R-Multiple Histogram ---
        if 'RMultiple' in trades_df.columns and pd.api.types.is_numeric_dtype(trades_df['RMultiple']):
            _r_vals = trades_df['RMultiple'].dropna()
            if len(_r_vals) >= 2:
                try:
                    _expectancy = float(_r_vals.mean())
                    _sqn_n = len(_r_vals)
                    _sqn_std = float(_r_vals.std(ddof=1))
                    _sqn = (_expectancy / _sqn_std) * np.sqrt(_sqn_n) if _sqn_std > 0 else 0.0
                    fig_r, ax_r = plt.subplots(figsize=(10, 4), dpi=150)
                    ax_r.hist(_r_vals, bins=30, color='purple', alpha=0.7, edgecolor='black')
                    ax_r.axvline(0, color='red', linestyle='--', linewidth=1.5, label='Breakeven (0R)')
                    ax_r.axvline(_expectancy, color='limegreen', linestyle='--', linewidth=1.5,
                                 label=f'Expectancy: {_expectancy:.3f}R  |  SQN: {_sqn:.2f}  |  n={_sqn_n}')
                    ax_r.set_xlabel('R-Multiple')
                    ax_r.set_ylabel('Number of Trades')
                    ax_r.set_title('Risk Profile — R-Multiple Distribution')
                    ax_r.legend()
                    fig_r.tight_layout()
                    report_sections.append({'type': 'plot', 'title': 'Risk Profile — R-Multiple Distribution', 'data': fig_r})
                except Exception as _r_err:
                    report_sections.append({'type': 'text', 'title': 'Risk Profile — R-Multiple Distribution', 'data': f"Error: {_r_err}"})
            else:
                report_sections.append({'type': 'text', 'title': 'Risk Profile — R-Multiple Distribution', 'data': "Skipped: fewer than 2 R-Multiple values."})
        else:
            report_sections.append({'type': 'text', 'title': 'Risk Profile — R-Multiple Distribution', 'data': "Skipped: 'RMultiple' column not present in trade data."})

        fig_bench = plotting.plot_benchmark_comparison(daily_equity, benchmark_df, benchmark_ticker)
        report_sections.append({'type': 'plot', 'title': f"Strategy Equity vs {benchmark_ticker}", 'data': fig_bench})

        fig_eq_dd = plotting.plot_equity_and_drawdown(trades_df, equity_dd_percent, wfa_split_date)
        report_sections.append({'type': 'plot', 'title': 'Equity Curve and Drawdown Plot', 'data': fig_eq_dd})

        fig_underwater = plotting.plot_underwater(trades_df, equity_dd_percent)
        report_sections.append({'type': 'plot', 'title': 'Underwater Plot (Drawdown & Duration)', 'data': fig_underwater})

        trades_per_year_rolling = 0
        if total_duration_years > 1e-6:
            trades_per_year_rolling = len(trades_df) / total_duration_years
        trades_df_for_rolling = calculations.calculate_rolling_metrics(
            trades_df.copy(), rolling_window, trades_per_year_rolling, risk_free_rate
        )
        fig_rolling = plotting.plot_rolling_metrics(trades_df_for_rolling, rolling_window, risk_free_rate)
        report_sections.append({'type': 'plot', 'title': f"Rolling {rolling_window}-Trade Metrics", 'data': fig_rolling})

        # --- Monte Carlo ---
        print("\n--- Running Monte Carlo Simulation ---")
        mc_results = {}
        try:
            trade_data_for_mc = pd.Series(dtype=float)
            data_source_used = "None"

            if mc_use_pct:
                if '% Profit' in trades_df.columns and pd.api.types.is_numeric_dtype(trades_df['% Profit']):
                    trade_data_for_mc = trades_df['% Profit'].copy()
                    data_source_used = "'% Profit'"
                else:
                    print("MC Warning: '% Profit' column missing or invalid.")
            else:
                if 'Profit' in trades_df.columns and pd.api.types.is_numeric_dtype(trades_df['Profit']):
                    trade_data_for_mc = trades_df['Profit'].copy()
                    data_source_used = "'Profit ($)'"
                else:
                    print("MC Warning: 'Profit' column missing or invalid.")

            if not trade_data_for_mc.empty and trade_data_for_mc.notna().any():
                mc_results = calculations.run_monte_carlo_simulation(
                    trade_data=trade_data_for_mc,
                    num_simulations=mc_simulations,
                    num_trades_per_sim=len(trades_df),
                    initial_equity=initial_equity,
                    duration_years=total_duration_years,
                    use_percentage_returns=mc_use_pct,
                    drawdown_as_negative=mc_dd_neg
                )
            else:
                print(f"MC Skipping: No valid trade data found in source: {data_source_used}")

            if mc_results:
                mc_table_title, mc_table_summary = report_generator.generate_mc_percentile_table(mc_results, mc_dd_neg)
                report_sections.append({'type': 'text', 'title': mc_table_title, 'data': mc_table_summary})
                mc_title, mc_summary = report_generator.generate_mc_summary(mc_results, initial_equity, mc_dd_neg)
                report_sections.append({'type': 'text', 'title': mc_title, 'data': mc_summary})

                mc_plots_to_generate = [
                    ('simulated_equity_paths', lambda data: plotting.plot_mc_min_max_equity(data, initial_equity), 'MC Simulated Equity Paths'),
                    ('max_drawdown_percentages', plotting.plot_mc_drawdown_pct, 'MC Max Drawdown % Distribution'),
                    ('lowest_equities', plotting.plot_mc_lowest_equity, 'MC Lowest Equity Distribution'),
                    ('final_equities', plotting.plot_mc_final_equity, 'MC Final Equity Distribution'),
                    ('cagrs', plotting.plot_mc_cagr, 'MC CAGR Distribution')
                ]
                for data_key, plot_func_or_lambda, default_title in mc_plots_to_generate:
                    plot_data = mc_results.get(data_key)
                    is_empty_or_invalid = plot_data is None or \
                                          (isinstance(plot_data, (pd.DataFrame, pd.Series)) and plot_data.empty) or \
                                          (isinstance(plot_data, pd.Series) and not plot_data.notna().any())
                    if not is_empty_or_invalid:
                        try:
                            fig = plot_func_or_lambda(plot_data)
                            if isinstance(fig, plt.Figure):
                                report_sections.append({'type': 'plot', 'title': default_title, 'data': fig})
                            else:
                                report_sections.append({'type': 'text', 'title': default_title, 'data': 'Plotting failed.'})
                        except Exception as plot_err:
                            report_sections.append({'type': 'text', 'title': default_title, 'data': f'Error: {plot_err}'})
                    else:
                        report_sections.append({'type': 'text', 'title': default_title, 'data': 'Data not available.'})
            else:
                report_sections.append({'type': 'text', 'title': "Monte Carlo Simulation Skipped", 'data': f"No results generated. Source: {data_source_used}"})

        except Exception as mc_err:
            print(f"ERROR during Monte Carlo Simulation section: {mc_err}")
            traceback.print_exc()
            report_sections.append({'type': 'text', 'title': "Monte Carlo Simulation Error", 'data': f"Error: {mc_err}\n{traceback.format_exc()}"})

        # --- Generate outputs ---
        print("\n--- Generating Markdown Report ---")
        try:
            report_generator.generate_markdown_report(report_sections, output_md_path, output_image_directory)
            md_save_attempted = True
        except Exception as md_gen_err:
            print(f"ERROR during Markdown report generation: {md_gen_err}")
            traceback.print_exc()
            md_save_attempted = True

        print("\n--- Generating PDF Report (Tearsheet) ---")
        try:
            # Build rolling metrics so page builders can use Rolling_PF / Rolling_Sharpe
            trades_per_year_for_rolling = (len(trades_df) / total_duration_years
                                           if total_duration_years > 1e-6 else 0)
            _trades_df_rolling = calculations.calculate_rolling_metrics(
                trades_df.copy(), rolling_window, trades_per_year_for_rolling, risk_free_rate
            )

            # Core scalars for KPI tiles
            _core_raw = calculations.calculate_core_metrics(trades_df)
            _sharpe_val = calculations.calculate_sharpe_ratio(
                daily_returns, risk_free_rate, trading_days)
            _sortino_val = calculations.calculate_sortino_ratio(
                daily_returns, risk_free_rate, trading_days)
            _core_for_pdf = dict(_core_raw)
            _core_for_pdf['sharpe'] = _sharpe_val
            _core_for_pdf['sortino'] = _sortino_val
            _core_for_pdf['duration_years'] = total_duration_years

            # Overall metrics text for appendix (re-use from report_sections)
            _overall_text = next(
                (s['data'] for s in report_sections if s.get('title') == 'Overall Performance Metrics'),
                ''
            )

            from ._pdf_pages import generate_tearsheet_pdf
            _report_data = {
                'name':                report_name,
                'run_date':            timestamp_str,
                'trades_df':           _trades_df_rolling,
                'initial_equity':      initial_equity,
                'daily_equity':        equity_for_dd_calc,
                'daily_returns':       daily_returns,
                'benchmark_df':        benchmark_df,
                'benchmark_returns':   benchmark_returns,
                'benchmark_ticker':    benchmark_ticker,
                'monthly_perf':        monthly_perf,
                'symbol_perf':         symbol_perf,
                'mc_results':          mc_results,
                'mc_dd_neg':           mc_dd_neg,
                'wfa_result':          wfa_result,
                'wfa_split_date':      wfa_split_date,
                'wfa_split_ratio':     wfa_split_ratio,
                'equity_dd_percent':   equity_dd_percent,
                'dd_periods_df':       dd_periods_df,
                'max_equity_dd_pct':   max_equity_dd_pct,
                'core_metrics':        _core_for_pdf,
                'risk_free_rate':      risk_free_rate,
                'rolling_window':      rolling_window,
                'cleaning_summary':    cleaning_summary if isinstance(cleaning_summary, str) else str(cleaning_summary),
                'overall_metrics_text': _overall_text,
                'top_n_trades':        top_n_trades,
            }
            generate_tearsheet_pdf(_report_data, output_pdf_path)
            pdf_save_attempted = True
        except Exception as pdf_gen_err:
            print(f"ERROR during PDF report generation: {pdf_gen_err}")
            traceback.print_exc()
            pdf_save_attempted = True
        finally:
            # Remove the temporary noise overlay PNG immediately after the PDF is saved
            if _temp_noise_img_path and os.path.isfile(_temp_noise_img_path):
                try:
                    os.remove(_temp_noise_img_path)
                except OSError:
                    pass

        try:
            key_metrics = report_generator.extract_key_metrics_for_console(report_sections)
            print("\n--- Key Metrics ---")
            for label, value in key_metrics.items():
                print(f"{label:<45} {value}")
        except Exception as print_err:
            print(f"Error extracting/printing key metrics: {print_err}")

    except StopIteration as si:
        print(f"Analysis stopped early: {si}")
    except ValueError as ve:
        print(f"\n--- Data Error Occurred ---\n{ve}\n{traceback.format_exc()}")
    except ImportError as ie:
        print(f"Import Error: {ie}.")
    except Exception as e:
        print(f"\n--- An Unhandled Error Occurred ---\n{e}\n{type(e).__name__}\n{traceback.format_exc()}")
        plt.close('all')

    finally:
        pdf_exists = os.path.exists(output_pdf_path)
        md_exists = os.path.exists(output_md_path)

        print("\n--- Report Generation Summary ---")
        if pdf_exists:
            print(f"PDF report successfully created: {output_pdf_path}")
        elif pdf_save_attempted:
            print(f"PDF report generation FAILED. Path: {output_pdf_path}")
        else:
            print("PDF report generation was not attempted.")

        if md_exists:
            print(f"Markdown report successfully created: {output_md_path}")
        elif md_save_attempted:
            print(f"Markdown report generation FAILED. Path: {output_md_path}")
        else:
            print("Markdown report generation was not attempted.")

        print(f"\n--- Analysis Run Finished ({timestamp_str}) ---")
