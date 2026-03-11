# plotting.py
import traceback
from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd
import seaborn as sns

from . import default_config as config


def create_placeholder_figure(title_text: str, message_text: str) -> plt.Figure:
    """Creates a simple placeholder figure with text."""
    fig = plt.figure(figsize=config.A4_LANDSCAPE)
    plt.axis('off')
    plt.text(0.5, 0.6, title_text, ha='center', va='center', fontsize=14, weight='bold', wrap=True)
    plt.text(0.5, 0.4, message_text, ha='center', va='center', fontsize=10, color='red', wrap=True)
    # No tight_layout here, let save_pdf handle final adjustments if needed
    return fig


def plot_monthly_performance(monthly_perf_df: pd.DataFrame) -> Optional[plt.Figure]:
    """Generates the monthly performance bar chart."""
    title = "Monthly Net Profit"
    if monthly_perf_df.empty or not all(c in monthly_perf_df for c in ['Entry YrMo', 'Monthly_Profit']):
         print(f"Skipping '{title}' plot (missing data).")
         return create_placeholder_figure(title, "Plot Skipped: Monthly performance data missing or invalid.")

    fig = None # Initialize
    try:
        fig = plt.figure(figsize=config.A4_LANDSCAPE)
        plt.bar(monthly_perf_df['Entry YrMo'], monthly_perf_df['Monthly_Profit'],
                color=np.where(monthly_perf_df['Monthly_Profit'] >= 0, 'g', 'r'))
        plt.title(title)
        plt.xlabel('Month')
        plt.ylabel('Profit ($)')
        plt.xticks(rotation=90)
        if len(monthly_perf_df['Entry YrMo']) > config.MAX_XTICKS_BEFORE_RESIZE:
            plt.xticks(fontsize=6) # Reduce font size for many ticks
        plt.grid(axis='y', linestyle='--')
        plt.gca().yaxis.set_major_formatter(mtick.FormatStrFormatter('$%.0f'))
        fig.tight_layout(pad=1.1) # Apply layout before returning
    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig: plt.close(fig) # Close partial figure on error
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")

    return fig


def plot_equity_and_drawdown(
    trades_df: pd.DataFrame,
    equity_dd_percent: pd.Series,
    wfa_split_date: Optional[str] = None,
) -> Optional[plt.Figure]:
    """Generates the Equity Curve and Drawdown plot.

    Parameters
    ----------
    trades_df        : cleaned trades DataFrame (must have 'Ex. date' and 'Equity').
    equity_dd_percent: equity drawdown series aligned to ``trades_df.index``.
    wfa_split_date   : ISO date string (e.g. ``'2018-01-01'``) marking the IS/OOS
                       boundary.  When supplied, a vertical dashed line is drawn on
                       both subplots at the first trade whose exit date falls on or
                       after this date.  Pass ``None`` to omit the line.
    """
    title = "Equity Curve and Drawdown"
    fig = None # Initialize
    try:
        # Adjust figsize height slightly as original did (A4_LANDSCAPE[1]*0.9)
        fig, axes = plt.subplots(2, 1, figsize=(config.A4_LANDSCAPE[0], config.A4_LANDSCAPE[1]*0.9),
                                 sharex=True, gridspec_kw={'height_ratios': [2, 1]})
        fig.suptitle(title, fontsize=14) # Add overall title

        # Plot equity on axes[0]
        if 'Equity' in trades_df and pd.api.types.is_numeric_dtype(trades_df['Equity']):
             axes[0].plot(trades_df.index, trades_df['Equity'], label='Equity Curve', color='blue', linewidth=1.5)
             axes[0].set_ylabel('Equity ($)')
             axes[0].grid(True, linestyle='--')
             axes[0].legend(loc='upper left')
             axes[0].yaxis.set_major_formatter(mtick.FormatStrFormatter('$%.0f'))
        else:
             axes[0].text(0.5, 0.5, 'Equity data not available', ha='center', va='center', transform=axes[0].transAxes)
        axes[0].set_title('Equity Curve Over Trades') # Subplot title

        # Plot drawdown on axes[1]
        if isinstance(equity_dd_percent, pd.Series) and not equity_dd_percent.empty and pd.api.types.is_numeric_dtype(equity_dd_percent):
            axes[1].plot(trades_df.index, equity_dd_percent, label='Equity Drawdown %', color='red', linewidth=1.5)
            axes[1].fill_between(trades_df.index, equity_dd_percent, 0, color='red', alpha=0.3)
            axes[1].set_ylabel('Drawdown (%)')
            axes[1].grid(True, linestyle='--')
            axes[1].legend(loc='upper left')
            axes[1].yaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=1))
            axes[1].set_ylim(bottom=min(0, equity_dd_percent.min() - 5)) # Ensure y-axis starts at or below 0
        else:
             axes[1].text(0.5, 0.5, 'Drawdown data not available', ha='center', va='center', transform=axes[1].transAxes)
        axes[1].set_xlabel('Trade Number')

        # --- WFA split line ---
        if wfa_split_date and 'Ex. date' in trades_df.columns:
            try:
                split_dt = pd.to_datetime(wfa_split_date)
                # Find the integer index of the first OOS trade
                oos_mask = trades_df['Ex. date'] >= split_dt
                if oos_mask.any():
                    split_idx = trades_df.index[oos_mask][0]
                    for ax in axes:
                        ax.axvline(
                            x=split_idx,
                            color='orange',
                            linestyle='--',
                            linewidth=1.5,
                            label=f'WFA Split ({wfa_split_date})',
                            zorder=5,
                        )
                    # Re-draw legends to include the WFA line
                    axes[0].legend(loc='upper left', fontsize=8)
                    axes[1].legend(loc='upper left', fontsize=8)
            except Exception as vline_err:
                print(f"WFA plot Warning: could not draw split line: {vline_err}")

        fig.tight_layout(pad=1.1, rect=[0, 0, 1, 0.96]) # Adjust rect to prevent suptitle overlap

    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig: plt.close(fig) # Close partial figure on error
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")

    return fig


def plot_duration_histogram(trades_df: pd.DataFrame) -> Optional[plt.Figure]:
    """Generates the histogram for trade duration (# bars)."""
    title = 'Distribution of Trade Duration (# bars)'
    #print(f"Generating '{title}' plot...")

    fig = None
    try:
        if '# bars' not in trades_df.columns or not pd.api.types.is_numeric_dtype(trades_df['# bars']):
             reason = "'# bars' column missing or invalid"
             print(f"Skipping '{title}' plot ({reason}).")
             return create_placeholder_figure(title, f"Plot Skipped\n({reason})")

        bars_series = trades_df['# bars'].dropna()
        if bars_series.empty:
            reason = "'# bars' column has no valid data"
            print(f"Skipping '{title}' plot ({reason}).")
            return create_placeholder_figure(title, f"Plot Skipped\n({reason})")

        fig = plt.figure(figsize=config.A4_LANDSCAPE)
        sns.histplot(bars_series, bins=30, kde=False)
        plt.title(title)
        plt.xlabel('Number of Bars Held')
        plt.ylabel('Number of Trades')
        plt.grid(axis='y', linestyle='--')
        # Optional mean/median lines
        # plt.axvline(bars_series.mean(), color='r', linestyle='dashed', linewidth=1, label=f'Mean: {bars_series.mean():.1f}')
        # plt.axvline(bars_series.median(), color='g', linestyle='dashed', linewidth=1, label=f'Median: {bars_series.median():.0f}')
        # plt.legend()
        fig.tight_layout(pad=1.1)

    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig: plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")

    return fig


def plot_duration_scatter(trades_df: pd.DataFrame) -> Optional[plt.Figure]:
    """Generates the scatter plot for Profit % vs. Trade Duration."""
    title = 'Profit % vs. Trade Duration'
    #print(f"Generating '{title}' plot...")

    fig = None
    try:
        required_cols = ['# bars', '% Profit', 'Win']
        missing_cols = []
        if '# bars' not in trades_df.columns or not pd.api.types.is_numeric_dtype(trades_df['# bars']): missing_cols.append("# bars (numeric)")
        if '% Profit' not in trades_df.columns or not pd.api.types.is_numeric_dtype(trades_df['% Profit']): missing_cols.append("% Profit (numeric)")
        if 'Win' not in trades_df.columns or not pd.api.types.is_bool_dtype(trades_df['Win']):
            if 'Win' in trades_df.columns: # Check if convertible
                 try: _ = trades_df['Win'].astype(bool)
                 except: missing_cols.append("Win (not boolean/convertible)")
            else: missing_cols.append("Win (boolean)")

        if missing_cols:
             reason = f"Missing/invalid columns: {', '.join(missing_cols)}"
             print(f"Skipping '{title}' plot ({reason}).")
             return create_placeholder_figure(title, f"Plot Skipped\n({reason})")

        scatter_data = trades_df.dropna(subset=required_cols).copy()
        if scatter_data.empty:
            reason = "No overlapping data after dropna for required columns"
            print(f"Skipping '{title}' plot ({reason}).")
            return create_placeholder_figure(title, f"Plot Skipped\n({reason})")

        # Ensure 'Win' is boolean for hue mapping
        scatter_data['Win'] = scatter_data['Win'].astype(bool)

        fig = plt.figure(figsize=config.A4_LANDSCAPE)
        sns.scatterplot(data=scatter_data, x='# bars', y='% Profit', hue='Win', alpha=0.6)
        plt.title(title)
        plt.xlabel('Number of Bars Held')
        plt.ylabel('% Profit per Trade')
        plt.gca().yaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=1))
        plt.grid(linestyle='--')
        plt.axhline(0, color='grey', linestyle='--')
        fig.tight_layout(pad=1.1)

    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig: plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")

    return fig


def plot_mae_mfe(trades_df: pd.DataFrame) -> Optional[plt.Figure]:
    """Generates the scatter plots for Profit % vs. MAE and Profit % vs. MFE."""
    title = "MAE/MFE Analysis"
    #print(f"Generating '{title}' plots...")

    fig = None
    try:
        required_cols = ['MAE', 'MFE', '% Profit', 'Win']
        missing_cols = []
        if 'MAE' not in trades_df.columns or not pd.api.types.is_numeric_dtype(trades_df['MAE']): missing_cols.append("MAE (numeric)")
        if 'MFE' not in trades_df.columns or not pd.api.types.is_numeric_dtype(trades_df['MFE']): missing_cols.append("MFE (numeric)")
        if '% Profit' not in trades_df.columns or not pd.api.types.is_numeric_dtype(trades_df['% Profit']): missing_cols.append("% Profit (numeric)")
        if 'Win' not in trades_df.columns:
             missing_cols.append("Win (boolean)")
        elif not pd.api.types.is_bool_dtype(trades_df['Win']):
             try: _ = trades_df['Win'].astype(bool)
             except: missing_cols.append("Win (not boolean/convertible)")

        if missing_cols:
             reason = f"Missing/invalid columns: {', '.join(missing_cols)}"
             print(f"Skipping '{title}' plot ({reason}).")
             return create_placeholder_figure(title, f"Plot Skipped\n({reason})")

        mae_mfe_df = trades_df.dropna(subset=required_cols).copy()
        if mae_mfe_df.empty:
            reason = "No overlapping data after dropna for required columns"
            print(f"Skipping '{title}' plot ({reason}).")
            return create_placeholder_figure(title, f"Plot Skipped\n({reason})")

        mae_mfe_df['Win'] = mae_mfe_df['Win'].astype(bool)

        fig, axes = plt.subplots(1, 2, figsize=(config.A4_LANDSCAPE[0], config.A4_LANDSCAPE[1]*0.8))
        fig.suptitle(title, fontsize=14, y=0.99)

        # Plot 1: Profit % vs MAE
        sns.scatterplot(data=mae_mfe_df, x='MAE', y='% Profit', hue='Win', alpha=0.6, ax=axes[0])
        axes[0].set_title('Profit % vs. MAE (Max Adverse Excursion)')
        axes[0].set_xlabel('MAE (%)')
        axes[0].set_ylabel('% Profit per Trade')
        axes[0].grid(linestyle='--')
        axes[0].axhline(0, color='grey', linestyle='--')
        axes[0].xaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=1))
        axes[0].yaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=1))

        # Plot 2: Profit % vs MFE
        sns.scatterplot(data=mae_mfe_df, x='MFE', y='% Profit', hue='Win', alpha=0.6, ax=axes[1])
        axes[1].set_title('Profit % vs. MFE (Max Favorable Excursion)')
        axes[1].set_xlabel('MFE (%)')
        axes[1].set_ylabel('% Profit per Trade')
        axes[1].grid(linestyle='--')
        axes[1].axhline(0, color='grey', linestyle='--')
        axes[1].xaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=1))
        axes[1].yaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=1))

        fig.tight_layout(pad=1.1, rect=[0, 0, 1, 0.95]) # Adjust rect for suptitle

    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig: plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")

    return fig


def plot_profit_distribution(trades_df: pd.DataFrame) -> Optional[plt.Figure]:
    """Generates the histogram for the distribution of % Profit per trade."""
    title = 'Distribution of % Profit per Trade'
    #print(f"Generating '{title}' plot...")

    fig = None
    try:
        if '% Profit' not in trades_df.columns or not pd.api.types.is_numeric_dtype(trades_df['% Profit']):
            reason = "'% Profit' column missing or invalid."
            print(f"Skipping '{title}' plot ({reason}).")
            return create_placeholder_figure(title, f"Plot Skipped\n({reason})")

        profit_pct_series = trades_df['% Profit'].dropna()
        if profit_pct_series.empty:
            reason = "'% Profit' column has no valid data"
            print(f"Skipping '{title}' plot ({reason}).")
            return create_placeholder_figure(title, f"Plot Skipped\n({reason})")

        fig = plt.figure(figsize=config.A4_LANDSCAPE)
        sns.histplot(profit_pct_series, bins=50, kde=True)
        plt.title(title)
        plt.xlabel('% Profit')
        plt.ylabel('Number of Trades')
        plt.gca().xaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0))
        plt.axvline(0, color='grey', linestyle='--')
        plt.grid(axis='y', linestyle='--')
        fig.tight_layout(pad=1.1)

    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig: plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")

    return fig


def plot_benchmark_comparison(
    daily_equity: pd.Series,
    benchmark_df: Optional[pd.DataFrame],
    benchmark_ticker: str
) -> Optional[plt.Figure]:
    """
    Generates the Strategy Equity vs Benchmark Buy & Hold plot.
    Includes robust checks and placeholder generation on failure.

    Args:
        daily_equity (pd.Series): Series of strategy's daily equity values.
        benchmark_df (Optional[pd.DataFrame]): DataFrame with benchmark prices ('Benchmark_Price').
        benchmark_ticker (str): Ticker symbol of the benchmark.

    Returns:
        Optional[plt.Figure]: The generated plot figure or a placeholder.
    """
    title = f"Strategy Equity vs {benchmark_ticker} Buy & Hold"
    #print(f"Generating '{title}' plot...")
    fig = None # Initialize

    try:
        if daily_equity.empty:
             return create_placeholder_figure(title, "Plot Skipped: Strategy daily equity data is empty.")
        if benchmark_df is None or benchmark_df.empty or 'Benchmark_Price' not in benchmark_df.columns:
             return create_placeholder_figure(title, f"Plot Skipped: Benchmark data for {benchmark_ticker} is missing or invalid.")

        # Ensure indices are datetime
        try:
            equity_index = pd.to_datetime(daily_equity.index)
            benchmark_index = pd.to_datetime(benchmark_df.index)
            # Use copies to avoid SettingWithCopyWarning if slicing later
            daily_equity = daily_equity.copy()
            daily_equity.index = equity_index
            benchmark_df = benchmark_df.copy()
            benchmark_df.index = benchmark_index
        except Exception as e:
             return create_placeholder_figure(title, f"Plot Skipped: Error converting indices to datetime: {e}")

        # --- Alignment ---
        common_index = daily_equity.index.intersection(benchmark_df.index)
        if common_index.empty or len(common_index) < 2:
            return create_placeholder_figure(title, "Plot Skipped: No overlapping dates found between strategy equity and benchmark data.")

        # --- Data Preparation ---
        equity_for_plot = daily_equity.loc[common_index].dropna()
        benchmark_price_for_plot = benchmark_df.loc[common_index, 'Benchmark_Price'].dropna()

        # Re-align after dropna
        final_common_index = equity_for_plot.index.intersection(benchmark_price_for_plot.index)
        if final_common_index.empty or len(final_common_index) < 2:
             return create_placeholder_figure(title, "Plot Skipped: No overlapping data remaining after cleaning NaNs.")

        equity_final = equity_for_plot.loc[final_common_index]
        benchmark_price_final = benchmark_price_for_plot.loc[final_common_index]

        # --- Normalization ---
        first_equity_value = equity_final.iloc[0]
        first_benchmark_price = benchmark_price_final.iloc[0]

        if pd.isna(first_equity_value) or pd.isna(first_benchmark_price) or first_benchmark_price < 1e-9: # Check for zero or near-zero price
            reason = []
            if pd.isna(first_equity_value): reason.append("initial strategy equity is NaN")
            if pd.isna(first_benchmark_price): reason.append("initial benchmark price is NaN")
            if first_benchmark_price < 1e-9: reason.append("initial benchmark price is zero or near-zero")
            return create_placeholder_figure(title, f"Plot Skipped: Cannot normalize data ({', '.join(reason)}).")

        normalized_benchmark = (benchmark_price_final / first_benchmark_price) * first_equity_value

        # --- Generate Plot ---
        fig, ax = plt.subplots(figsize=config.A4_LANDSCAPE)
        ax.plot(equity_final.index, equity_final, label='Strategy Equity', color='blue', linewidth=1.5)
        ax.plot(normalized_benchmark.index, normalized_benchmark, label=f'{benchmark_ticker} Buy & Hold (Normalized)', color='darkgrey', linestyle='--')

        ax.set_title(title)
        ax.set_ylabel('Portfolio Value ($)')
        ax.set_xlabel('Date')
        ax.yaxis.set_major_formatter(mtick.FormatStrFormatter('$%.0f'))
        ax.legend()
        ax.grid(True, linestyle=':')
        plt.xticks(rotation=30, ha='right')
        fig.tight_layout(pad=1.1)

    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig: plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")

    return fig


def plot_rolling_metrics(
    trades_df: pd.DataFrame,
    window: int,
    risk_free_rate: float
) -> Optional[plt.Figure]:
    """
    Generates the plots for rolling Profit Factor and rolling Sharpe Ratio.

    Args:
        trades_df (pd.DataFrame): DataFrame with 'Rolling_PF' and 'Rolling_Sharpe' columns.
        window (int): The rolling window size used.
        risk_free_rate (float): The risk-free rate used for Sharpe display.

    Returns:
        Optional[plt.Figure]: The generated plot figure or a placeholder.
    """
    title = f'Rolling {window}-Trade Metrics'
    #print(f"Generating '{title}' plot...")

    fig = None
    try:
        required_cols = ['Rolling_PF', 'Rolling_Sharpe']
        missing_cols = [col for col in required_cols if col not in trades_df.columns]
        if missing_cols:
             reason = f"Missing calculated columns: {', '.join(missing_cols)}"
             print(f"Skipping '{title}' plot ({reason}).")
             return create_placeholder_figure(title, f"Plot Skipped\n({reason})")

        # Check if there's *any* non-NaN data to plot
        pf_valid = trades_df['Rolling_PF'].notna().any()
        sharpe_valid = trades_df['Rolling_Sharpe'].notna().any()
        if not pf_valid and not sharpe_valid:
             reason = "No valid data points found in 'Rolling_PF' or 'Rolling_Sharpe' columns"
             print(f"Skipping '{title}' plot ({reason}).")
             return create_placeholder_figure(title, f"Plot Skipped\n({reason})")

        # --- Generate Plot (with two subplots) ---
        fig, axes = plt.subplots(2, 1, figsize=(config.A4_LANDSCAPE[0], config.A4_LANDSCAPE[1]*0.9),
                                 sharex=True, gridspec_kw={'height_ratios': [1, 1]})
        fig.suptitle(title, fontsize=14) # Add overall title

        # Plot 1: Rolling Profit Factor
        if pf_valid:
            axes[0].plot(trades_df.index, trades_df['Rolling_PF'], label=f'{window}-Trade Rolling PF', color='blue', linewidth=1.5)
            axes[0].axhline(1.0, color='red', linestyle='--', linewidth=1, label='PF = 1.0 (Breakeven)')
            axes[0].set_ylim(bottom=0) # PF typically >= 0
        else:
            axes[0].text(0.5, 0.5, 'Rolling PF data not available or all NaN',
                         horizontalalignment='center', verticalalignment='center', transform=axes[0].transAxes)
        axes[0].set_title(f'Rolling {window}-Trade Profit Factor')
        axes[0].set_ylabel('Profit Factor')
        axes[0].grid(True, linestyle='--')
        axes[0].legend(loc='upper left')

        # Plot 2: Rolling Sharpe Ratio
        if sharpe_valid:
            axes[1].plot(trades_df.index, trades_df['Rolling_Sharpe'], label=f'{window}-Trade Rolling Sharpe', color='green', linewidth=1.5)
            axes[1].axhline(0.0, color='red', linestyle='--', linewidth=1, label='Sharpe = 0.0')
        else:
            axes[1].text(0.5, 0.5, 'Rolling Sharpe data not available or all NaN',
                         horizontalalignment='center', verticalalignment='center', transform=axes[1].transAxes)
        axes[1].set_title(f'Rolling {window}-Trade Sharpe Ratio (Annualized, Rf={risk_free_rate*100:.1f}%)')
        axes[1].set_ylabel('Sharpe Ratio')
        axes[1].set_xlabel('Trade Number')
        axes[1].grid(True, linestyle='--')
        axes[1].legend(loc='upper left')

        fig.tight_layout(pad=1.1, rect=[0, 0.03, 1, 0.95]) # Adjust rect for suptitle & x-label

        return fig

    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig: plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")

def plot_mc_min_max_equity(simulated_equity_paths: pd.DataFrame) -> Optional[plt.Figure]:
    """Plots min, max, average, and percentile equity paths from simulations."""
    title = "Monte Carlo: Simulated Equity Paths"
    #print(f"Generating '{title}' plot...")
    fig = None
    try:
        if simulated_equity_paths.empty or simulated_equity_paths.shape[1] < 1:
            return create_placeholder_figure(title, "Plot Skipped: No simulation paths provided.")

        avg_path = simulated_equity_paths.mean(axis=1)
        median_path = simulated_equity_paths.median(axis=1)
        # Calculate percentiles (adjust as needed)
        pct_5 = simulated_equity_paths.quantile(0.05, axis=1)
        pct_95 = simulated_equity_paths.quantile(0.95, axis=1)
        min_path = simulated_equity_paths.min(axis=1)
        max_path = simulated_equity_paths.max(axis=1)

        fig, ax = plt.subplots(figsize=config.A4_LANDSCAPE)
        ax.plot(avg_path.index, avg_path, label='Average Equity', color='blue', linewidth=2)
        ax.plot(median_path.index, median_path, label='Median Equity', color='orange', linestyle='--', linewidth=1.5)
        # Fill between percentiles
        ax.fill_between(pct_5.index, pct_5, pct_95, color='skyblue', alpha=0.3, label='5th-95th Percentile')
        # Optionally plot min/max
        # ax.plot(min_path.index, min_path, label='Min Equity', color='red', linestyle=':', linewidth=1)
        # ax.plot(max_path.index, max_path, label='Max Equity', color='green', linestyle=':', linewidth=1)

        ax.set_title(title + f" ({simulated_equity_paths.shape[1]} Simulations)")
        ax.set_xlabel("Trade Number in Simulation")
        ax.set_ylabel("Simulated Equity ($)")
        ax.yaxis.set_major_formatter(mtick.FormatStrFormatter('$%.0f'))
        ax.grid(True, linestyle=':')
        ax.legend(loc='upper left')
        fig.tight_layout(pad=1.1)

    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig: plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")
    return fig

def plot_mc_distribution(data: pd.Series, plot_title: str, xlabel: str, use_kde: bool = True) -> Optional[plt.Figure]:
    """Helper function to plot distributions (Histogram/KDE)."""
    #print(f"Generating '{plot_title}' plot...")
    fig = None
    try:
        if data.empty or data.isna().all():
             return create_placeholder_figure(plot_title, f"Plot Skipped: No valid data for {xlabel}.")

        fig, ax = plt.subplots(figsize=config.A4_LANDSCAPE)
        sns.histplot(data.dropna(), kde=use_kde, ax=ax, bins=50) # Use dropna()
        ax.set_title(plot_title + f" (Distribution from {data.count()} Simulations)") # Use count() for non-NaN
        ax.set_xlabel(xlabel)
        ax.set_ylabel("Frequency (Number of Simulations)")

        # Formatting based on xlabel content
        if '$' in xlabel:
            ax.xaxis.set_major_formatter(mtick.FormatStrFormatter('$%.0f'))
        elif '%' in xlabel:
            ax.xaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0)) # Assuming percent input

        ax.grid(True, axis='y', linestyle=':')
        fig.tight_layout(pad=1.1)

    except Exception as e:
        print(f"ERROR generating '{plot_title}' plot: {e}")
        traceback.print_exc()
        if fig: plt.close(fig)
        fig = create_placeholder_figure(plot_title, f"Error generating plot:\n{e}")
    return fig

def plot_mc_min_max_equity(equity_paths_df: pd.DataFrame, initial_equity: float) -> Optional[plt.Figure]:
    """
    Plots the minimum and maximum equity paths across all MC simulations.

    Args:
        equity_paths_df (pd.DataFrame): DataFrame where each column is a simulation path
                                        and rows represent trade steps.
        initial_equity (float): The starting equity for reference.

    Returns:
        Optional[plt.Figure]: The generated matplotlib Figure, or None on error.
    """
    plot_title = "MC Min/Max Equity"
    fig = None # Initialize

    if not isinstance(equity_paths_df, pd.DataFrame) or equity_paths_df.empty:
        print(f"Skipping '{plot_title}' plot (equity paths DataFrame missing or empty).")
        return create_placeholder_figure(plot_title, "Plot Skipped: Equity paths data missing or empty.")

    try:
        #print(f"Generating '{plot_title}' plot...")
        # Calculate min and max equity across all simulations for each step (row)
        min_equity_step = equity_paths_df.min(axis=1)
        max_equity_step = equity_paths_df.max(axis=1)
        median_equity_step = equity_paths_df.median(axis=1) # Optional: Plot median too

        fig, ax = plt.subplots(figsize=config.A4_LANDSCAPE)

        trade_steps = equity_paths_df.index # Should be 0 to num_trades_per_sim

        # Plot Max and Min lines
        ax.plot(trade_steps, max_equity_step, label='Max Equity', color='lightgreen', linewidth=1)
        ax.plot(trade_steps, min_equity_step, label='Min Equity', color='lightcoral', linewidth=1)

        # Optional: Plot Median line
        ax.plot(trade_steps, median_equity_step, label='Median Equity', color='blue', linestyle='--', linewidth=1.5)

        # Fill between Max and Min
        ax.fill_between(trade_steps, min_equity_step, max_equity_step, color='grey', alpha=0.3, label='Equity Range')

        # Add initial equity line
        ax.axhline(initial_equity, color='black', linestyle=':', linewidth=1, label=f'Initial Equity (${initial_equity:,.0f})')

        # Formatting
        ax.set_title(plot_title, fontsize=14)
        ax.set_xlabel("Trade #")
        ax.set_ylabel("Equity ($)")
        ax.yaxis.set_major_formatter(mtick.FormatStrFormatter('$%.0f'))
        ax.legend(loc='upper left')
        ax.grid(True, linestyle='--', alpha=0.6)

        fig.tight_layout(pad=1.1)
        #print(f"Successfully generated '{plot_title}' plot.")

    except Exception as e:
        print(f"ERROR generating '{plot_title}' plot: {e}")
        traceback.print_exc()
        if fig: plt.close(fig)
        fig = create_placeholder_figure(plot_title, f"Error generating plot:\n{e}")

    return fig

# Specific plot functions using the helper
def plot_mc_final_equity(final_equities: pd.Series) -> Optional[plt.Figure]:
    return plot_mc_distribution(final_equities, "Monte Carlo: Distribution of Final Equity", "Final Equity ($)")

def plot_mc_cagr(cagr_values: pd.Series) -> Optional[plt.Figure]:
    # Format CAGR as percentage before plotting if needed
    return plot_mc_distribution(cagr_values * 100, "Monte Carlo: Distribution of CAGR", "Compound Annual Growth Rate (%)")

def plot_mc_drawdown_pct(dd_pct_values: pd.Series) -> Optional[plt.Figure]:
    # Ensure DD % is positive for histogram (it should be from calculations.py)
    return plot_mc_distribution(dd_pct_values, "Monte Carlo: Distribution of Max Drawdown %", "Maximum Drawdown (%)")

def plot_mc_drawdown_amount(dd_amount_values: pd.Series) -> Optional[plt.Figure]:
    return plot_mc_distribution(dd_amount_values, "Monte Carlo: Distribution of Max Drawdown $", "Maximum Drawdown ($)")

def plot_mc_lowest_equity(lowest_equity_values: pd.Series) -> Optional[plt.Figure]:
    return plot_mc_distribution(lowest_equity_values, "Monte Carlo: Distribution of Lowest Equity", "Lowest Equity Reached ($)")
    return fig