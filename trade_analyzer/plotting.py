# plotting.py
import contextlib
import traceback
from typing import Optional

import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
import seaborn as sns

from . import default_config as config


# ---------------------------------------------------------------------------
# Theme helpers
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def themed():
    """Context manager: apply the report theme to rcParams, then restore."""
    T = config.THEME
    old = {
        'font.family':          plt.rcParams.get('font.family'),
        'font.size':            plt.rcParams.get('font.size'),
        'axes.facecolor':       plt.rcParams.get('axes.facecolor'),
        'axes.edgecolor':       plt.rcParams.get('axes.edgecolor'),
        'axes.labelcolor':      plt.rcParams.get('axes.labelcolor'),
        'axes.grid':            plt.rcParams.get('axes.grid'),
        'grid.color':           plt.rcParams.get('grid.color'),
        'grid.linestyle':       plt.rcParams.get('grid.linestyle'),
        'grid.alpha':           plt.rcParams.get('grid.alpha'),
        'xtick.color':          plt.rcParams.get('xtick.color'),
        'ytick.color':          plt.rcParams.get('ytick.color'),
        'text.color':           plt.rcParams.get('text.color'),
        'legend.framealpha':    plt.rcParams.get('legend.framealpha'),
        'legend.fontsize':      plt.rcParams.get('legend.fontsize'),
        'figure.facecolor':     plt.rcParams.get('figure.facecolor'),
    }
    plt.rcParams.update({
        'font.family':          config.FONT_FAMILY,
        'font.size':            config.FONT_SIZE_BASE,
        'axes.facecolor':       T['bg'],
        'axes.edgecolor':       T['neutral'],
        'axes.labelcolor':      T['text'],
        'axes.grid':            True,
        'grid.color':           T['grid'],
        'grid.linestyle':       '--',
        'grid.alpha':           0.7,
        'xtick.color':          T['text_muted'],
        'ytick.color':          T['text_muted'],
        'text.color':           T['text'],
        'legend.framealpha':    0.85,
        'legend.fontsize':      config.FONT_SIZE_BASE - 1,
        'figure.facecolor':     T['bg'],
    })
    try:
        yield
    finally:
        plt.rcParams.update(old)


def _apply_theme():
    """Apply report theme to current rcParams (no restore)."""
    T = config.THEME
    plt.rcParams.update({
        'font.family':          config.FONT_FAMILY,
        'font.size':            config.FONT_SIZE_BASE,
        'axes.facecolor':       T['bg'],
        'axes.edgecolor':       T['neutral'],
        'axes.labelcolor':      T['text'],
        'axes.grid':            True,
        'grid.color':           T['grid'],
        'grid.linestyle':       '--',
        'grid.alpha':           0.7,
        'xtick.color':          T['text_muted'],
        'ytick.color':          T['text_muted'],
        'text.color':           T['text'],
        'legend.framealpha':    0.85,
        'legend.fontsize':      config.FONT_SIZE_BASE - 1,
        'figure.facecolor':     T['bg'],
    })


def _fmt_dollar(ax, axis='y'):
    fmt = mtick.FuncFormatter(lambda x, _: f'${x:,.0f}')
    if axis == 'y':
        ax.yaxis.set_major_formatter(fmt)
    else:
        ax.xaxis.set_major_formatter(fmt)


def _style_ax(ax, title='', xlabel='', ylabel='', title_size=None):
    T = config.THEME
    if title:
        ax.set_title(title, fontsize=title_size or config.FONT_SIZE_H2,
                     color=T['primary'], fontweight='bold', pad=6)
    if xlabel:
        ax.set_xlabel(xlabel, labelpad=4)
    if ylabel:
        ax.set_ylabel(ylabel, labelpad=4)
    ax.tick_params(axis='both', labelsize=config.FONT_SIZE_BASE - 1)
    for spine in ax.spines.values():
        spine.set_edgecolor(T['neutral'])
        spine.set_linewidth(0.6)


def create_placeholder_figure(title_text: str, message_text: str) -> plt.Figure:
    """Creates a simple placeholder figure with text."""
    fig = plt.figure(figsize=config.FIG_FULL)
    plt.axis('off')
    plt.text(0.5, 0.6, title_text, ha='center', va='center',
             fontsize=12, weight='bold', color=config.THEME['primary'], wrap=True)
    plt.text(0.5, 0.4, message_text, ha='center', va='center',
             fontsize=9, color=config.THEME['negative'], wrap=True)
    return fig


# ---------------------------------------------------------------------------
# Plot functions
# ---------------------------------------------------------------------------

def plot_monthly_performance(monthly_perf_df: pd.DataFrame) -> Optional[plt.Figure]:
    """Monthly P&L as a year × month heatmap (replaces bar chart)."""
    title = "Monthly Returns Heatmap"
    if monthly_perf_df.empty or 'Entry YrMo' not in monthly_perf_df or 'Monthly_Profit' not in monthly_perf_df:
        return create_placeholder_figure(title, "Plot Skipped: Monthly performance data missing.")

    fig = None
    try:
        df = monthly_perf_df.copy()
        # Parse period / string into year + month numbers
        df['_yrmo'] = df['Entry YrMo'].astype(str)
        df['_year'] = df['_yrmo'].str[:4].astype(int, errors='ignore')
        df['_month'] = df['_yrmo'].str[5:7].astype(int, errors='ignore')
        # Build pivot
        pivot = df.pivot_table(index='_year', columns='_month', values='Monthly_Profit', aggfunc='sum')
        month_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        pivot.columns = [month_labels[m - 1] for m in pivot.columns]

        T = config.THEME
        fig, ax = plt.subplots(figsize=config.FIG_FULL)
        abs_max = pivot.abs().max().max()
        if abs_max == 0 or pd.isna(abs_max):
            abs_max = 1.0
        sns.heatmap(
            pivot, ax=ax, cmap='RdYlGn', center=0,
            vmin=-abs_max, vmax=abs_max,
            linewidths=0.4, linecolor=T['grid'],
            annot=True, fmt='.0f', annot_kws={'size': 7},
            cbar_kws={'label': 'Net Profit ($)', 'shrink': 0.6},
        )
        _style_ax(ax, title=title, xlabel='Month', ylabel='Year')
        ax.set_xticklabels(ax.get_xticklabels(), rotation=0)
        ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
        fig.tight_layout(pad=1.2)
    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig:
            plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")
    return fig


def plot_equity_and_drawdown(
    trades_df: pd.DataFrame,
    equity_dd_percent: pd.Series,
    wfa_split_date: Optional[str] = None,
) -> Optional[plt.Figure]:
    """Equity curve (with calendar dates) + drawdown panel."""
    title = "Equity Curve and Drawdown"
    fig = None
    T = config.THEME
    try:
        # Determine x-axis: prefer calendar dates from 'Ex. date', else trade index
        use_dates = 'Ex. date' in trades_df.columns and pd.api.types.is_datetime64_any_dtype(trades_df['Ex. date'])
        x = trades_df['Ex. date'] if use_dates else trades_df.index

        fig, axes = plt.subplots(
            2, 1, figsize=config.FIG_FULL, sharex=True,
            gridspec_kw={'height_ratios': [3, 1]},
        )
        fig.suptitle(title, fontsize=config.FONT_SIZE_TITLE,
                     color=T['primary'], fontweight='bold', y=0.98)

        # — Equity subplot —
        if 'Equity' in trades_df and pd.api.types.is_numeric_dtype(trades_df['Equity']):
            axes[0].plot(x, trades_df['Equity'], color=T['primary'], linewidth=1.6, label='Equity')
            axes[0].fill_between(x, trades_df['Equity'].min() * 0.99, trades_df['Equity'],
                                 color=T['primary'], alpha=0.06)
            _fmt_dollar(axes[0])
        else:
            axes[0].text(0.5, 0.5, 'Equity data not available',
                         ha='center', va='center', transform=axes[0].transAxes)
        _style_ax(axes[0], ylabel='Portfolio Value ($)')

        # — Drawdown subplot —
        if isinstance(equity_dd_percent, pd.Series) and not equity_dd_percent.empty \
                and pd.api.types.is_numeric_dtype(equity_dd_percent):
            neg_dd = -equity_dd_percent
            axes[1].fill_between(x, neg_dd, 0, color=T['dd_fill'], alpha=0.8)
            axes[1].plot(x, neg_dd, color=T['negative'], linewidth=0.8)
            axes[1].yaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=0))
            bottom = min(-equity_dd_percent.max() * 1.05, -1)
            axes[1].set_ylim(bottom=bottom, top=0.5)
        else:
            axes[1].text(0.5, 0.5, 'Drawdown data not available',
                         ha='center', va='center', transform=axes[1].transAxes)
        _style_ax(axes[1], ylabel='Drawdown (%)',
                  xlabel='Date' if use_dates else 'Trade Number')

        # — WFA split line —
        if wfa_split_date and use_dates:
            try:
                split_dt = pd.to_datetime(wfa_split_date)
                for ax in axes:
                    ax.axvline(split_dt, color=T['accent'], linestyle='--',
                               linewidth=1.5, label=f'WFA Split ({wfa_split_date})', zorder=5)
                axes[0].legend(loc='upper left', fontsize=8)
            except Exception:
                pass

        if use_dates:
            fig.autofmt_xdate(rotation=25, ha='right')
        fig.tight_layout(pad=1.1, rect=[0, 0, 1, 0.96])
    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig:
            plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")
    return fig


def plot_underwater(
    trades_df: pd.DataFrame,
    equity_dd_percent: pd.Series,
) -> Optional[plt.Figure]:
    """Underwater (drawdown) banner — short, wide."""
    title = "Underwater Plot (Drawdown & Duration)"
    fig = None
    T = config.THEME
    try:
        if not isinstance(equity_dd_percent, pd.Series) or equity_dd_percent.empty \
                or not pd.api.types.is_numeric_dtype(equity_dd_percent):
            return create_placeholder_figure(title, "Plot Skipped: Drawdown data missing or invalid.")

        use_dates = 'Ex. date' in trades_df.columns and pd.api.types.is_datetime64_any_dtype(trades_df['Ex. date'])
        x = trades_df['Ex. date'] if use_dates else trades_df.index
        underwater = -equity_dd_percent

        fig, ax = plt.subplots(figsize=config.FIG_HALF_H)
        ax.fill_between(x, underwater, 0, color=T['dd_fill'], alpha=0.85)
        ax.plot(x, underwater, color=T['negative'], linewidth=0.8)
        ax.axhline(0, color=T['neutral'], linestyle='-', linewidth=0.8)
        ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=0))
        bottom = min(underwater.min() * 1.05, -1)
        ax.set_ylim(bottom=bottom, top=0.5)
        _style_ax(ax, title=title, xlabel='Date' if use_dates else 'Trade Number',
                  ylabel='Drawdown (%)')
        if use_dates:
            fig.autofmt_xdate(rotation=25, ha='right')
        fig.tight_layout(pad=1.1)
    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig:
            plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")
    return fig


def plot_duration_histogram(trades_df: pd.DataFrame) -> Optional[plt.Figure]:
    """Histogram for trade duration (# bars)."""
    title = 'Trade Duration Distribution'
    fig = None
    T = config.THEME
    try:
        if '# bars' not in trades_df.columns or not pd.api.types.is_numeric_dtype(trades_df['# bars']):
            return create_placeholder_figure(title, "Plot Skipped: '# bars' missing or invalid.")
        bars_series = trades_df['# bars'].dropna()
        if bars_series.empty:
            return create_placeholder_figure(title, "Plot Skipped: '# bars' has no valid data.")

        fig, ax = plt.subplots(figsize=config.FIG_FULL)
        ax.hist(bars_series, bins=30, color=T['primary'], alpha=0.75, edgecolor=T['bg'])
        ax.axvline(bars_series.mean(), color=T['accent'], linestyle='--', linewidth=1.5,
                   label=f'Mean: {bars_series.mean():.1f}')
        ax.axvline(bars_series.median(), color=T['positive'], linestyle='--', linewidth=1.5,
                   label=f'Median: {bars_series.median():.0f}')
        ax.legend()
        _style_ax(ax, title=title, xlabel='Bars Held', ylabel='Number of Trades')
        fig.tight_layout(pad=1.2)
    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig:
            plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")
    return fig


def plot_duration_scatter(trades_df: pd.DataFrame) -> Optional[plt.Figure]:
    """Scatter: Profit % vs. Trade Duration."""
    title = 'Profit % vs. Trade Duration'
    fig = None
    T = config.THEME
    try:
        required_cols = ['# bars', '% Profit', 'Win']
        missing = [c for c in required_cols if c not in trades_df.columns]
        if missing:
            return create_placeholder_figure(title, f"Plot Skipped: Missing {missing}.")
        scatter_data = trades_df.dropna(subset=required_cols).copy()
        if scatter_data.empty:
            return create_placeholder_figure(title, "Plot Skipped: No overlapping data.")
        scatter_data['Win'] = scatter_data['Win'].astype(bool)

        fig, ax = plt.subplots(figsize=config.FIG_FULL)
        wins = scatter_data[scatter_data['Win']]
        losses = scatter_data[~scatter_data['Win']]
        ax.scatter(losses['# bars'], losses['% Profit'], color=T['negative'],
                   alpha=0.4, s=18, label='Loss', edgecolors='none')
        ax.scatter(wins['# bars'], wins['% Profit'], color=T['positive'],
                   alpha=0.4, s=18, label='Win', edgecolors='none')
        ax.axhline(0, color=T['neutral'], linestyle='--', linewidth=0.8)
        ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=1))
        ax.legend()
        _style_ax(ax, title=title, xlabel='Bars Held', ylabel='% Profit per Trade')
        fig.tight_layout(pad=1.2)
    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig:
            plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")
    return fig


def plot_mae_mfe(trades_df: pd.DataFrame) -> Optional[plt.Figure]:
    """MAE / MFE scatter plots."""
    title = "MAE / MFE Analysis"
    fig = None
    T = config.THEME
    try:
        required_cols = ['MAE', 'MFE', '% Profit', 'Win']
        missing = [c for c in required_cols if c not in trades_df.columns]
        if missing:
            return create_placeholder_figure(title, f"Plot Skipped: Missing {missing}.")
        df = trades_df.dropna(subset=required_cols).copy()
        if df.empty:
            return create_placeholder_figure(title, "Plot Skipped: No overlapping data.")
        df['Win'] = df['Win'].astype(bool)
        wins, losses = df[df['Win']], df[~df['Win']]

        fig, axes = plt.subplots(1, 2, figsize=config.FIG_FULL, sharey=True)
        fig.suptitle(title, fontsize=config.FONT_SIZE_TITLE,
                     color=T['primary'], fontweight='bold', y=0.99)

        for ax, xcol, xlabel in [(axes[0], 'MAE', 'MAE (%)'), (axes[1], 'MFE', 'MFE (%)')]:
            ax.scatter(losses[xcol], losses['% Profit'], color=T['negative'],
                       alpha=0.4, s=16, label='Loss', edgecolors='none')
            ax.scatter(wins[xcol], wins['% Profit'], color=T['positive'],
                       alpha=0.4, s=16, label='Win', edgecolors='none')
            ax.axhline(0, color=T['neutral'], linestyle='--', linewidth=0.8)
            ax.xaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=1))
            ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=1))
            ax.legend(fontsize=8)
            _style_ax(ax, xlabel=xlabel, ylabel='% Profit per Trade')

        fig.tight_layout(pad=1.1, rect=[0, 0, 1, 0.95])
    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig:
            plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")
    return fig


def plot_profit_distribution(trades_df: pd.DataFrame) -> Optional[plt.Figure]:
    """Histogram + KDE for % Profit per trade."""
    title = 'Return Distribution (% Profit per Trade)'
    fig = None
    T = config.THEME
    try:
        if '% Profit' not in trades_df.columns or not pd.api.types.is_numeric_dtype(trades_df['% Profit']):
            return create_placeholder_figure(title, "Plot Skipped: '% Profit' missing or invalid.")
        series = trades_df['% Profit'].dropna()
        if series.empty:
            return create_placeholder_figure(title, "Plot Skipped: No valid data.")

        fig, ax = plt.subplots(figsize=config.FIG_FULL)
        sns.histplot(series, bins=50, kde=True, ax=ax,
                     color=T['primary'], alpha=0.65, edgecolor=T['bg'],
                     line_kws={'linewidth': 1.5, 'color': T['accent']})
        ax.axvline(0, color=T['neutral'], linestyle='--', linewidth=1.0, label='Breakeven')
        ax.axvline(series.mean(), color=T['accent'], linestyle='--', linewidth=1.5,
                   label=f'Mean: {series.mean():.2f}%')
        ax.xaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0))
        ax.legend()
        _style_ax(ax, title=title, xlabel='% Profit', ylabel='Number of Trades')
        fig.tight_layout(pad=1.2)
    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig:
            plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")
    return fig


def plot_benchmark_comparison(
    daily_equity: pd.Series,
    benchmark_df: Optional[pd.DataFrame],
    benchmark_ticker: str,
) -> Optional[plt.Figure]:
    """Strategy equity vs benchmark (normalized) — calendar date x-axis."""
    title = f"Strategy Equity vs {benchmark_ticker} Buy & Hold"
    fig = None
    T = config.THEME
    try:
        if daily_equity.empty:
            return create_placeholder_figure(title, "Plot Skipped: Strategy daily equity empty.")
        if benchmark_df is None or benchmark_df.empty or 'Benchmark_Price' not in benchmark_df.columns:
            return create_placeholder_figure(title, f"Plot Skipped: Benchmark data missing.")

        # Normalise timezone
        equity_idx = pd.to_datetime(daily_equity.index)
        if equity_idx.tz is not None:
            equity_idx = equity_idx.tz_localize(None)
        bench_idx = pd.to_datetime(benchmark_df.index)
        if bench_idx.tz is not None:
            bench_idx = bench_idx.tz_localize(None)
        eq = daily_equity.copy(); eq.index = equity_idx
        bdf = benchmark_df.copy(); bdf.index = bench_idx

        common = eq.index.intersection(bdf.index)
        if len(common) < 2:
            return create_placeholder_figure(title, "Plot Skipped: No overlapping dates.")

        eq_final = eq.loc[common].dropna()
        bp_final = bdf.loc[common, 'Benchmark_Price'].dropna()
        common2 = eq_final.index.intersection(bp_final.index)
        if len(common2) < 2:
            return create_placeholder_figure(title, "Plot Skipped: No data after dropna.")

        eq_final = eq_final.loc[common2]
        bp_final = bp_final.loc[common2]
        bp_norm = (bp_final / bp_final.iloc[0]) * eq_final.iloc[0]

        fig, ax = plt.subplots(figsize=config.FIG_FULL)
        ax.plot(eq_final.index, eq_final, color=T['primary'], linewidth=1.6, label='Strategy')
        ax.plot(bp_norm.index, bp_norm, color=T['accent'], linewidth=1.4,
                linestyle='--', label=f'{benchmark_ticker} B&H (normalised)')
        ax.fill_between(eq_final.index, bp_norm, eq_final,
                        where=(eq_final >= bp_norm), color=T['positive'], alpha=0.08)
        ax.fill_between(eq_final.index, bp_norm, eq_final,
                        where=(eq_final < bp_norm), color=T['negative'], alpha=0.08)
        _fmt_dollar(ax)
        ax.legend()
        _style_ax(ax, title=title, xlabel='Date', ylabel='Portfolio Value ($)')
        fig.autofmt_xdate(rotation=25, ha='right')
        fig.tight_layout(pad=1.1)
    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig:
            plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")
    return fig


def plot_rolling_metrics(
    trades_df: pd.DataFrame,
    window: int,
    risk_free_rate: float,
) -> Optional[plt.Figure]:
    """Rolling Profit Factor + rolling Sharpe (calendar date x-axis)."""
    title = f'Rolling {window}-Trade Metrics'
    fig = None
    T = config.THEME
    try:
        required_cols = ['Rolling_PF', 'Rolling_Sharpe']
        missing = [c for c in required_cols if c not in trades_df.columns]
        if missing:
            return create_placeholder_figure(title, f"Plot Skipped: Missing {missing}.")
        pf_valid = trades_df['Rolling_PF'].notna().any()
        sh_valid = trades_df['Rolling_Sharpe'].notna().any()
        if not pf_valid and not sh_valid:
            return create_placeholder_figure(title, "Plot Skipped: No valid rolling data.")

        use_dates = 'Ex. date' in trades_df.columns and pd.api.types.is_datetime64_any_dtype(trades_df['Ex. date'])
        x = trades_df['Ex. date'] if use_dates else trades_df.index

        fig, axes = plt.subplots(2, 1, figsize=config.FIG_FULL, sharex=True,
                                 gridspec_kw={'height_ratios': [1, 1]})
        fig.suptitle(title, fontsize=config.FONT_SIZE_TITLE,
                     color=T['primary'], fontweight='bold', y=0.98)

        # — PF subplot —
        if pf_valid:
            axes[0].plot(x, trades_df['Rolling_PF'], color=T['primary'], linewidth=1.4,
                         label=f'{window}-trade Rolling PF')
            axes[0].axhline(1.0, color=T['negative'], linestyle='--', linewidth=1.0, label='PF = 1.0')
            axes[0].set_ylim(bottom=0)
            axes[0].legend(loc='upper left')
        else:
            axes[0].text(0.5, 0.5, 'No PF data', ha='center', va='center',
                         transform=axes[0].transAxes)
        _style_ax(axes[0], ylabel='Profit Factor')

        # — Sharpe subplot —
        if sh_valid:
            axes[1].plot(x, trades_df['Rolling_Sharpe'], color=T['positive'], linewidth=1.4,
                         label=f'{window}-trade Rolling Sharpe')
            axes[1].axhline(0.0, color=T['negative'], linestyle='--', linewidth=1.0)
            # shade positive region
            axes[1].fill_between(x, trades_df['Rolling_Sharpe'], 0,
                                 where=(trades_df['Rolling_Sharpe'] >= 0),
                                 color=T['positive'], alpha=0.1)
            axes[1].fill_between(x, trades_df['Rolling_Sharpe'], 0,
                                 where=(trades_df['Rolling_Sharpe'] < 0),
                                 color=T['negative'], alpha=0.1)
            axes[1].legend(loc='upper left')
        else:
            axes[1].text(0.5, 0.5, 'No Sharpe data', ha='center', va='center',
                         transform=axes[1].transAxes)
        _style_ax(axes[1], ylabel=f'Sharpe (Rf={risk_free_rate*100:.1f}%)',
                  xlabel='Date' if use_dates else 'Trade Number')

        if use_dates:
            fig.autofmt_xdate(rotation=25, ha='right')
        fig.tight_layout(pad=1.1, rect=[0, 0.02, 1, 0.95])
    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig:
            plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")
    return fig


def plot_mc_fan(
    equity_paths_df: pd.DataFrame,
    initial_equity: float,
) -> Optional[plt.Figure]:
    """MC equity-path fan chart: percentile bands + median + initial equity."""
    title = "Monte Carlo — Simulated Equity Paths"
    fig = None
    T = config.THEME
    try:
        if not isinstance(equity_paths_df, pd.DataFrame) or equity_paths_df.empty:
            return create_placeholder_figure(title, "Plot Skipped: No MC equity paths.")

        n_sims = equity_paths_df.shape[1]
        x = equity_paths_df.index

        p5  = equity_paths_df.quantile(0.05,  axis=1)
        p25 = equity_paths_df.quantile(0.25,  axis=1)
        p50 = equity_paths_df.quantile(0.50,  axis=1)
        p75 = equity_paths_df.quantile(0.75,  axis=1)
        p95 = equity_paths_df.quantile(0.95,  axis=1)

        fig, ax = plt.subplots(figsize=config.FIG_FULL)
        # outer fan: 5–95
        ax.fill_between(x, p5, p95, color=T['mc_fill'], alpha=0.45, label='5–95th pct')
        # inner fan: 25–75
        ax.fill_between(x, p25, p75, color=T['primary'], alpha=0.20, label='25–75th pct')
        # median
        ax.plot(x, p50, color=T['primary'], linewidth=2.0, label='Median')
        # initial equity reference
        ax.axhline(initial_equity, color=T['neutral'], linestyle=':', linewidth=1.0,
                   label=f'Initial (${initial_equity:,.0f})')

        _fmt_dollar(ax)
        ax.legend(loc='upper left')
        _style_ax(ax, title=f"{title} ({n_sims:,} sims)",
                  xlabel='Trade #', ylabel='Simulated Equity ($)')
        fig.tight_layout(pad=1.2)
    except Exception as e:
        print(f"ERROR generating '{title}' plot: {e}")
        traceback.print_exc()
        if fig:
            plt.close(fig)
        fig = create_placeholder_figure(title, f"Error generating plot:\n{e}")
    return fig


# Keep legacy name used by analyzer.py
def plot_mc_min_max_equity(equity_paths_df: pd.DataFrame, initial_equity: float) -> Optional[plt.Figure]:
    return plot_mc_fan(equity_paths_df, initial_equity)


def _plot_mc_dist(data: pd.Series, plot_title: str, xlabel: str,
                  dollar: bool = False, pct: bool = False) -> Optional[plt.Figure]:
    """Generic MC distribution histogram + KDE."""
    fig = None
    T = config.THEME
    try:
        if data is None or data.empty or data.isna().all():
            return create_placeholder_figure(plot_title, f"Plot Skipped: No valid data for {xlabel}.")

        clean = data.dropna()
        fig, ax = plt.subplots(figsize=config.FIG_FULL)
        sns.histplot(clean, bins=50, kde=True, ax=ax,
                     color=T['primary'], alpha=0.65, edgecolor=T['bg'],
                     line_kws={'linewidth': 1.5, 'color': T['accent']})
        # percentile markers
        for pval, color in [(0.05, T['negative']), (0.50, T['accent']), (0.95, T['positive'])]:
            v = clean.quantile(pval)
            ax.axvline(v, color=color, linestyle='--', linewidth=1.2,
                       label=f'P{int(pval*100)}: {"$" if dollar else ""}{v:,.0f}{"%" if pct else ""}')
        if dollar:
            ax.xaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f'${x:,.0f}'))
        elif pct:
            ax.xaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0))
        ax.legend(fontsize=8)
        _style_ax(ax, title=f"{plot_title} ({clean.count():,} sims)",
                  xlabel=xlabel, ylabel='Frequency')
        fig.tight_layout(pad=1.2)
    except Exception as e:
        print(f"ERROR generating '{plot_title}' plot: {e}")
        traceback.print_exc()
        if fig:
            plt.close(fig)
        fig = create_placeholder_figure(plot_title, f"Error generating plot:\n{e}")
    return fig


def plot_mc_final_equity(final_equities: pd.Series) -> Optional[plt.Figure]:
    return _plot_mc_dist(final_equities, "MC — Final Equity Distribution", "Final Equity ($)", dollar=True)


def plot_mc_cagr(cagr_values: pd.Series) -> Optional[plt.Figure]:
    return _plot_mc_dist(cagr_values * 100, "MC — CAGR Distribution", "CAGR (%)", pct=True)


def plot_mc_drawdown_pct(dd_pct_values: pd.Series) -> Optional[plt.Figure]:
    return _plot_mc_dist(dd_pct_values, "MC — Max Drawdown % Distribution", "Max Drawdown (%)", pct=True)


def plot_mc_drawdown_amount(dd_amount_values: pd.Series) -> Optional[plt.Figure]:
    return _plot_mc_dist(dd_amount_values, "MC — Max Drawdown $ Distribution", "Max Drawdown ($)", dollar=True)


def plot_mc_lowest_equity(lowest_equity_values: pd.Series) -> Optional[plt.Figure]:
    return _plot_mc_dist(lowest_equity_values, "MC — Lowest Equity Distribution", "Lowest Equity ($)", dollar=True)


def plot_mc_distribution(data: pd.Series, plot_title: str, xlabel: str,
                         use_kde: bool = True) -> Optional[plt.Figure]:
    """Legacy shim used in older callers."""
    dollar = '$' in xlabel
    pct = '%' in xlabel and not dollar
    return _plot_mc_dist(data, plot_title, xlabel, dollar=dollar, pct=pct)
