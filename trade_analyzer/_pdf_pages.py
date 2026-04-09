# _pdf_pages.py  — new composite page builders for the professional tearsheet
#
# Called by analyzer.py via generate_tearsheet_pdf().
# All functions return plt.Figure objects; the caller assembles them into a PdfPages.
#
# Dependencies: only trade_analyzer sub-modules + matplotlib/pandas/numpy.
from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any, Optional

import matplotlib.gridspec as mgridspec
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch

from . import calculations
from . import default_config as config
from . import plotting as _plotting


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _T() -> dict:
    return config.THEME


def _na(v) -> str:
    """Format a value for display; return 'N/A' when missing."""
    if v is None:
        return 'N/A'
    try:
        if pd.isna(v):
            return 'N/A'
    except (TypeError, ValueError):
        pass
    return v


def _style_ax(ax, title='', xlabel='', ylabel=''):
    T = _T()
    if title:
        ax.set_title(title, fontsize=config.FONT_SIZE_H2,
                     color=T['primary'], fontweight='bold', pad=5)
    if xlabel:
        ax.set_xlabel(xlabel, labelpad=3, fontsize=config.FONT_SIZE_BASE)
    if ylabel:
        ax.set_ylabel(ylabel, labelpad=3, fontsize=config.FONT_SIZE_BASE)
    for sp in ax.spines.values():
        sp.set_edgecolor(T['neutral'])
        sp.set_linewidth(0.5)
    ax.tick_params(axis='both', labelsize=config.FONT_SIZE_BASE - 1,
                   color=T['text_muted'], labelcolor=T['text_muted'])


def draw_kpi_tile(
    ax,
    label: str,
    value: str,
    subtitle: str = '',
    positive: Optional[bool] = None,
):
    """Render a single KPI tile into *ax* (axis should have been turned off)."""
    T = _T()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    # Background patch
    bg = FancyBboxPatch((0.04, 0.06), 0.92, 0.88,
                        boxstyle='round,pad=0.02',
                        facecolor=T['kpi_bg'], edgecolor=T['kpi_border'],
                        linewidth=0.8, zorder=0)
    ax.add_patch(bg)

    val_color = T['primary']
    if positive is True:
        val_color = T['positive']
    elif positive is False:
        val_color = T['negative']

    ax.text(0.5, 0.80, label.upper(), ha='center', va='center',
            fontsize=config.FONT_SIZE_KPI_LABEL, color=T['text_muted'],
            fontweight='bold', transform=ax.transAxes)
    ax.text(0.5, 0.50, str(value), ha='center', va='center',
            fontsize=config.FONT_SIZE_KPI_VALUE, color=val_color,
            fontweight='bold', transform=ax.transAxes)
    if subtitle:
        ax.text(0.5, 0.20, subtitle, ha='center', va='center',
                fontsize=config.FONT_SIZE_KPI_LABEL, color=T['text_muted'],
                transform=ax.transAxes)


def draw_dataframe_table(
    ax,
    df: pd.DataFrame,
    col_widths: Optional[list] = None,
    header_bg: Optional[str] = None,
    alt_row: bool = True,
    font_size: int = 8,
) -> None:
    """Render *df* as a styled matplotlib table inside *ax*."""
    T = _T()
    ax.axis('off')
    if df.empty:
        ax.text(0.5, 0.5, 'No data', ha='center', va='center', transform=ax.transAxes)
        return

    header_bg = header_bg or T['primary']
    nrows, ncols = df.shape
    cell_text = df.values.tolist()
    col_labels = list(df.columns)

    # auto column widths
    if col_widths is None:
        col_widths = [1.0 / (ncols + 1)] * ncols

    # row colours
    row_colors = []
    for i in range(nrows):
        c = T['kpi_bg'] if (alt_row and i % 2 == 1) else T['bg']
        row_colors.append([c] * ncols)

    tbl = ax.table(
        cellText=cell_text,
        colLabels=col_labels,
        colWidths=col_widths,
        cellLoc='right',
        loc='center',
        cellColours=row_colors,
    )
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(font_size)
    tbl.scale(1.0, 1.3)

    # Style header
    for col_idx in range(ncols):
        cell = tbl[(0, col_idx)]
        cell.set_facecolor(header_bg)
        cell.set_text_props(color='white', fontweight='bold', fontsize=font_size)

    # Left-align first column
    for row_idx in range(1, nrows + 1):
        tbl[(row_idx, 0)].set_text_props(ha='left')


def _stamp_header_footer(fig: plt.Figure, strategy_name: str, run_date: str,
                          page_num: int, total_pages: int):
    """Add a thin header line (strategy name) and footer (page X of Y) to fig."""
    T = _T()
    fig.text(0.01, 0.985, strategy_name, ha='left', va='top',
             fontsize=7, color=T['text_muted'], style='italic',
             transform=fig.transFigure)
    fig.text(0.99, 0.985, run_date, ha='right', va='top',
             fontsize=7, color=T['text_muted'],
             transform=fig.transFigure)
    fig.text(0.5, 0.008, f'Page {page_num} of {total_pages}',
             ha='center', va='bottom', fontsize=7, color=T['text_muted'],
             transform=fig.transFigure)


# ---------------------------------------------------------------------------
# Page builders
# ---------------------------------------------------------------------------

def build_cover_page(report_meta: dict) -> plt.Figure:
    """
    Page 1 — cover.
    report_meta keys: name, run_date, start_date, end_date, total_return,
                      cagr, max_dd, sharpe, profit_factor, total_trades,
                      initial_equity.
    """
    T = _T()
    fig = plt.figure(figsize=config.FIG_FULL)
    fig.patch.set_facecolor(T['bg'])

    # Navy banner at top
    banner_ax = fig.add_axes([0, 0.82, 1, 0.18])
    banner_ax.set_facecolor(T['primary'])
    banner_ax.axis('off')
    banner_ax.text(0.5, 0.65, 'Trade Analysis Report',
                   ha='center', va='center', fontsize=20, color='white',
                   fontweight='bold', transform=banner_ax.transAxes)
    banner_ax.text(0.5, 0.25, report_meta.get('name', ''),
                   ha='center', va='center', fontsize=13, color='#bbdefb',
                   transform=banner_ax.transAxes)

    # Date range
    period_ax = fig.add_axes([0.0, 0.74, 1.0, 0.08])
    period_ax.axis('off')
    start = report_meta.get('start_date', 'N/A')
    end = report_meta.get('end_date', 'N/A')
    run_date = report_meta.get('run_date', datetime.now().strftime('%Y-%m-%d'))
    period_ax.text(0.5, 0.5, f'Backtest period: {start} — {end}  |  Generated: {run_date}',
                   ha='center', va='center', fontsize=10, color=T['text_muted'],
                   transform=period_ax.transAxes)

    # 6 KPI tiles in a 3×2 grid
    tile_data = [
        ('Total Return', _fmt_pct(report_meta.get('total_return')),
         None if report_meta.get('total_return') is None else report_meta.get('total_return', 0) >= 0),
        ('CAGR', _fmt_pct(report_meta.get('cagr')),
         None if report_meta.get('cagr') is None else report_meta.get('cagr', 0) >= 0),
        ('Max Drawdown', _fmt_pct(report_meta.get('max_dd'), force_sign=False),
         False if report_meta.get('max_dd') else None),
        ('Sharpe Ratio', _fmt_float(report_meta.get('sharpe'), 2),
         None if report_meta.get('sharpe') is None else report_meta.get('sharpe', 0) >= 1.0),
        ('Profit Factor', _fmt_float(report_meta.get('profit_factor'), 2),
         None if report_meta.get('profit_factor') is None else report_meta.get('profit_factor', 0) >= 1.5),
        ('Total Trades', _fmt_int(report_meta.get('total_trades')), None),
    ]

    cols, rows = 3, 2
    tile_w, tile_h = 0.28, 0.26
    left_start = 0.055
    top_start = 0.68
    h_gap = 0.035
    v_gap = 0.04

    for idx, (label, value, positive) in enumerate(tile_data):
        col = idx % cols
        row = idx // cols
        left = left_start + col * (tile_w + h_gap)
        bottom = top_start - row * (tile_h + v_gap) - tile_h
        ax = fig.add_axes([left, bottom, tile_w, tile_h])
        draw_kpi_tile(ax, label, value, positive=positive)

    # Footer
    fig.text(0.5, 0.03,
             f'Initial Equity: ${report_meta.get("initial_equity", 0):,.0f}',
             ha='center', va='bottom', fontsize=9, color=T['text_muted'])
    return fig


def build_executive_summary_page(
    trades_df: pd.DataFrame,
    daily_equity: pd.Series,
    benchmark_df: Optional[pd.DataFrame],
    benchmark_ticker: str,
    equity_dd_percent: pd.Series,
    core_metrics: dict,
    risk_free_rate: float,
    initial_equity: float,
    wfa_split_date: Optional[str] = None,
) -> plt.Figure:
    """
    Page 2 — executive summary: 8 KPI tiles + equity-vs-benchmark + underwater.
    """
    T = _T()
    fig = plt.figure(figsize=config.FIG_FULL)
    fig.patch.set_facecolor(T['bg'])

    # Title strip
    title_ax = fig.add_axes([0, 0.955, 1, 0.045])
    title_ax.set_facecolor(T['primary'])
    title_ax.axis('off')
    title_ax.text(0.5, 0.5, 'Executive Summary',
                  ha='center', va='center', fontsize=13, color='white',
                  fontweight='bold', transform=title_ax.transAxes)

    # Build outer GridSpec
    gs = mgridspec.GridSpec(
        3, 1, figure=fig,
        top=0.94, bottom=0.04, left=0.07, right=0.97,
        hspace=0.35,
        height_ratios=[1, 2.8, 0.85],
    )

    # --- Row 0: 8 KPI tiles in a nested grid ---
    gs_kpi = mgridspec.GridSpecFromSubplotSpec(2, 4, subplot_spec=gs[0], hspace=0.25, wspace=0.10)

    total_profit = core_metrics.get('total_profit', 0) or 0
    final_equity = initial_equity + total_profit
    total_return = (final_equity / initial_equity - 1) if initial_equity > 0 else None
    total_dur = core_metrics.get('duration_years', 0) or 0
    cagr = calculations.calculate_cagr(initial_equity, final_equity, total_dur) if total_dur > 0 else None
    sharpe = calculations.calculate_sharpe_ratio(
        core_metrics.get('daily_returns', pd.Series(dtype=float)),
        risk_free_rate, 252) if not isinstance(core_metrics.get('daily_returns'), type(None)) else None

    _, _, _, max_dd = calculations.calculate_equity_drawdown(daily_equity)

    tiles = [
        ('Net Profit', _fmt_curr(total_profit), total_profit >= 0),
        ('Total Return', _fmt_pct(total_return),
         None if total_return is None else total_return >= 0),
        ('CAGR', _fmt_pct(cagr), None if cagr is None else cagr >= 0),
        ('Sharpe', _fmt_float(core_metrics.get('sharpe'), 2),
         None if core_metrics.get('sharpe') is None else core_metrics.get('sharpe', 0) >= 1.0),
        ('Sortino', _fmt_float(core_metrics.get('sortino'), 2),
         None if core_metrics.get('sortino') is None else core_metrics.get('sortino', 0) >= 1.0),
        ('Max Drawdown', f"{max_dd:.1f}%" if max_dd else 'N/A', False),
        ('Win Rate', _fmt_pct(core_metrics.get('win_rate')), None),
        ('Profit Factor', _fmt_float(core_metrics.get('profit_factor'), 2),
         None if core_metrics.get('profit_factor') is None else core_metrics.get('profit_factor', 0) >= 1.0),
    ]
    for idx, (label, value, positive) in enumerate(tiles):
        r, c = divmod(idx, 4)
        ax_tile = fig.add_subplot(gs_kpi[r, c])
        draw_kpi_tile(ax_tile, label, value, positive=positive)

    # --- Row 1: Equity vs benchmark ---
    ax_eq = fig.add_subplot(gs[1])
    _draw_equity_inline(ax_eq, daily_equity, benchmark_df, benchmark_ticker,
                        wfa_split_date=wfa_split_date)
    _style_ax(ax_eq, title='Equity vs Benchmark', ylabel='Portfolio Value ($)')
    ax_eq.tick_params(axis='x', labelsize=7, rotation=20)
    _plotting._fmt_dollar(ax_eq)

    # --- Row 2: Underwater —
    ax_uw = fig.add_subplot(gs[2])
    _draw_underwater_inline(ax_uw, trades_df, equity_dd_percent)
    _style_ax(ax_uw, ylabel='Drawdown (%)')
    ax_uw.tick_params(axis='x', labelsize=7, rotation=20)

    return fig


def build_risk_return_page(
    trades_df: pd.DataFrame,
    daily_equity: pd.Series,
    risk_free_rate: float,
    rolling_window: int,
    var_95: float,
    cvar_95: float,
    var_99: float,
    cvar_99: float,
) -> plt.Figure:
    """Page 3 — Rolling metrics + return distribution + R-multiple + VaR."""
    T = _T()
    fig = plt.figure(figsize=config.FIG_FULL)
    _add_page_title(fig, 'Risk & Return Analysis')

    gs = mgridspec.GridSpec(2, 2, figure=fig,
                            top=0.91, bottom=0.06, left=0.08, right=0.97,
                            hspace=0.45, wspace=0.30)

    # — Rolling metrics (top-left, spans both columns) —
    gs_rolling = mgridspec.GridSpecFromSubplotSpec(2, 1, subplot_spec=gs[0, :],
                                                   hspace=0.15, height_ratios=[1, 1])

    use_dates = 'Ex. date' in trades_df and pd.api.types.is_datetime64_any_dtype(trades_df['Ex. date'])
    x = trades_df['Ex. date'] if use_dates else trades_df.index

    ax_pf = fig.add_subplot(gs_rolling[0])
    if 'Rolling_PF' in trades_df and trades_df['Rolling_PF'].notna().any():
        ax_pf.plot(x, trades_df['Rolling_PF'], color=T['primary'], linewidth=1.2,
                   label=f'{rolling_window}-trade Rolling PF')
        ax_pf.axhline(1.0, color=T['negative'], linestyle='--', linewidth=0.9)
        ax_pf.set_ylim(bottom=0)
        ax_pf.legend(fontsize=7, loc='upper left')
    _style_ax(ax_pf, title=f'Rolling {rolling_window}-Trade Profit Factor', ylabel='PF')
    ax_pf.set_xticklabels([])

    ax_sh = fig.add_subplot(gs_rolling[1])
    if 'Rolling_Sharpe' in trades_df and trades_df['Rolling_Sharpe'].notna().any():
        ax_sh.plot(x, trades_df['Rolling_Sharpe'], color=T['positive'], linewidth=1.2,
                   label=f'{rolling_window}-trade Rolling Sharpe')
        ax_sh.axhline(0.0, color=T['negative'], linestyle='--', linewidth=0.9)
        ax_sh.fill_between(x, trades_df['Rolling_Sharpe'], 0,
                           where=trades_df['Rolling_Sharpe'] >= 0,
                           color=T['positive'], alpha=0.12)
        ax_sh.fill_between(x, trades_df['Rolling_Sharpe'], 0,
                           where=trades_df['Rolling_Sharpe'] < 0,
                           color=T['negative'], alpha=0.12)
        ax_sh.legend(fontsize=7, loc='upper left')
    _style_ax(ax_sh, ylabel=f'Sharpe (Rf={risk_free_rate*100:.1f}%)',
              xlabel='Date' if use_dates else 'Trade #')
    if use_dates:
        ax_sh.tick_params(axis='x', rotation=20, labelsize=7)

    # — Return distribution (bottom-left) —
    ax_ret = fig.add_subplot(gs[1, 0])
    if '% Profit' in trades_df and pd.api.types.is_numeric_dtype(trades_df['% Profit']):
        import seaborn as sns
        series = trades_df['% Profit'].dropna()
        sns.histplot(series, bins=40, kde=True, ax=ax_ret, color=T['primary'],
                     alpha=0.6, edgecolor=T['bg'],
                     line_kws={'linewidth': 1.3, 'color': T['accent']})
        ax_ret.axvline(0, color=T['neutral'], linestyle='--', linewidth=0.9)
        ax_ret.axvline(series.mean(), color=T['accent'], linestyle='--', linewidth=1.2,
                       label=f'Mean {series.mean():.2f}%')
        ax_ret.xaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0))
        ax_ret.legend(fontsize=7)
    _style_ax(ax_ret, title='Return Distribution', xlabel='% Profit', ylabel='Trades')

    # — R-Multiple (bottom-right) —
    ax_r = fig.add_subplot(gs[1, 1])
    if 'RMultiple' in trades_df and pd.api.types.is_numeric_dtype(trades_df['RMultiple']):
        r_vals = trades_df['RMultiple'].dropna()
        if len(r_vals) >= 2:
            import seaborn as sns
            sns.histplot(r_vals, bins=30, ax=ax_r, color=T['primary'],
                         alpha=0.6, edgecolor=T['bg'])
            expectancy = r_vals.mean()
            sqn_std = r_vals.std(ddof=1)
            sqn = (expectancy / sqn_std * np.sqrt(len(r_vals))) if sqn_std > 0 else 0.0
            ax_r.axvline(0, color=T['negative'], linestyle='--', linewidth=1.0, label='Breakeven')
            ax_r.axvline(expectancy, color=T['positive'], linestyle='--', linewidth=1.2,
                         label=f'E[R]={expectancy:.3f}  SQN={sqn:.2f}')
            ax_r.legend(fontsize=7)
        else:
            ax_r.text(0.5, 0.5, 'Insufficient R data', ha='center', va='center',
                      transform=ax_r.transAxes, fontsize=9)
    else:
        ax_r.text(0.5, 0.5, 'RMultiple column not available',
                  ha='center', va='center', transform=ax_r.transAxes, fontsize=9)
        ax_r.axis('off')
    _style_ax(ax_r, title='R-Multiple Distribution', xlabel='R-Multiple', ylabel='Trades')

    return fig


def build_drawdowns_page(
    trades_df: pd.DataFrame,
    equity_dd_percent: pd.Series,
    dd_periods_df: pd.DataFrame,
    max_equity_dd_pct: float,
) -> plt.Figure:
    """Page 4 — Underwater + drawdown periods table + duration histogram."""
    T = _T()
    fig = plt.figure(figsize=config.FIG_FULL)
    _add_page_title(fig, 'Drawdown Analysis')

    gs = mgridspec.GridSpec(2, 2, figure=fig,
                            top=0.91, bottom=0.06, left=0.08, right=0.97,
                            hspace=0.45, wspace=0.30)

    # — Underwater (spans both cols) —
    ax_uw = fig.add_subplot(gs[0, :])
    _draw_underwater_inline(ax_uw, trades_df, equity_dd_percent)
    _style_ax(ax_uw, title=f'Drawdown History  (Max: {max_equity_dd_pct:.1f}%)',
              ylabel='Drawdown (%)')

    # — Drawdown periods table (bottom-left) —
    ax_tbl = fig.add_subplot(gs[1, 0])
    ax_tbl.axis('off')
    if dd_periods_df is not None and not dd_periods_df.empty:
        needed = ['Start_Date', 'Trough_Date', 'End_Date', 'Duration_Days', 'DD_Amount']
        avail = [c for c in needed if c in dd_periods_df.columns]
        top5 = dd_periods_df.sort_values('DD_Amount', ascending=False,
                                         na_position='last').head(5)[avail].copy()
        # Format
        for dc in ['Start_Date', 'Trough_Date', 'End_Date']:
            if dc in top5:
                top5[dc] = top5[dc].apply(
                    lambda v: v.strftime('%Y-%m-%d') if pd.notna(v) else 'Ongoing')
        if 'Duration_Days' in top5:
            top5['Duration_Days'] = top5['Duration_Days'].apply(
                lambda v: f'{v:.0f}d' if pd.notna(v) else 'N/A')
        if 'DD_Amount' in top5:
            top5['DD_Amount'] = top5['DD_Amount'].apply(
                lambda v: f'${v:,.0f}' if pd.notna(v) else 'N/A')
        top5.columns = [c.replace('_', '\n') for c in top5.columns]
        draw_dataframe_table(ax_tbl, top5, font_size=7)
        ax_tbl.set_title('Top 5 Drawdown Periods', fontsize=config.FONT_SIZE_H2,
                          color=T['primary'], fontweight='bold', pad=6)
    else:
        ax_tbl.text(0.5, 0.5, 'No completed drawdown periods.',
                    ha='center', va='center', transform=ax_tbl.transAxes)

    # — DD duration histogram (bottom-right) —
    ax_dur = fig.add_subplot(gs[1, 1])
    if dd_periods_df is not None and not dd_periods_df.empty and 'Duration_Days' in dd_periods_df:
        dur = dd_periods_df['Duration_Days'].dropna()
        if not dur.empty:
            ax_dur.hist(dur, bins=20, color=T['negative'], alpha=0.7, edgecolor=T['bg'])
            ax_dur.axvline(dur.mean(), color=T['accent'], linestyle='--', linewidth=1.2,
                           label=f'Mean {dur.mean():.0f}d')
            ax_dur.legend(fontsize=8)
    _style_ax(ax_dur, title='Drawdown Duration Distribution',
              xlabel='Duration (days)', ylabel='Frequency')

    return fig


def build_seasonality_page(monthly_perf: pd.DataFrame) -> plt.Figure:
    """Page 5 — Year × month heatmap."""
    T = _T()
    fig = plt.figure(figsize=config.FIG_FULL)
    _add_page_title(fig, 'Monthly Seasonality')

    if monthly_perf is None or monthly_perf.empty:
        ax = fig.add_axes([0.05, 0.1, 0.9, 0.8])
        ax.axis('off')
        ax.text(0.5, 0.5, 'Monthly performance data not available.',
                ha='center', va='center', transform=ax.transAxes)
        return fig

    # Plot heatmap figure and copy into this figure
    hmap_fig = _plotting.plot_monthly_performance(monthly_perf)
    if hmap_fig is not None and isinstance(hmap_fig, plt.Figure):
        # Transfer the axes from the generated figure
        for src_ax in hmap_fig.get_axes():
            src_ax.remove()
            src_ax.figure = fig
            fig.add_axes(src_ax)
        plt.close(hmap_fig)
    return fig


def build_trade_analysis_page(trades_df: pd.DataFrame) -> plt.Figure:
    """Page 6 — MAE/MFE scatter + duration histogram + profit dist (gridspec)."""
    T = _T()
    fig = plt.figure(figsize=config.FIG_FULL)
    _add_page_title(fig, 'Trade Analysis')

    gs = mgridspec.GridSpec(2, 2, figure=fig,
                            top=0.91, bottom=0.06, left=0.08, right=0.97,
                            hspace=0.40, wspace=0.30)

    # — MAE scatter (top-left) —
    ax_mae = fig.add_subplot(gs[0, 0])
    _draw_mae_mfe_inline(ax_mae, trades_df, xcol='MAE', xlabel='MAE (%)')
    _style_ax(ax_mae, title='Profit% vs MAE', xlabel='MAE (%)', ylabel='% Profit')

    # — MFE scatter (top-right) —
    ax_mfe = fig.add_subplot(gs[0, 1])
    _draw_mae_mfe_inline(ax_mfe, trades_df, xcol='MFE', xlabel='MFE (%)')
    _style_ax(ax_mfe, title='Profit% vs MFE', xlabel='MFE (%)', ylabel='% Profit')

    # — Duration histogram (bottom-left) —
    ax_dur = fig.add_subplot(gs[1, 0])
    if '# bars' in trades_df and pd.api.types.is_numeric_dtype(trades_df['# bars']):
        bs = trades_df['# bars'].dropna()
        ax_dur.hist(bs, bins=30, color=T['primary'], alpha=0.7, edgecolor=T['bg'])
        ax_dur.axvline(bs.mean(), color=T['accent'], linestyle='--', linewidth=1.2,
                       label=f'Mean {bs.mean():.1f}')
        ax_dur.legend(fontsize=8)
    _style_ax(ax_dur, title='Duration Distribution', xlabel='Bars Held', ylabel='Trades')

    # — % Profit dist (bottom-right) —
    ax_pct = fig.add_subplot(gs[1, 1])
    if '% Profit' in trades_df and pd.api.types.is_numeric_dtype(trades_df['% Profit']):
        import seaborn as sns
        s = trades_df['% Profit'].dropna()
        sns.histplot(s, bins=40, kde=True, ax=ax_pct,
                     color=T['primary'], alpha=0.6, edgecolor=T['bg'],
                     line_kws={'linewidth': 1.2, 'color': T['accent']})
        ax_pct.axvline(0, color=T['neutral'], linestyle='--', linewidth=0.9)
        ax_pct.xaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0))
    _style_ax(ax_pct, title='Return Distribution (%)', xlabel='% Profit', ylabel='Trades')

    return fig


def build_symbol_performance_page(symbol_perf: pd.DataFrame) -> plt.Figure:
    """Page 7 — symbol performance table (top 25, sorted by total profit)."""
    T = _T()
    fig = plt.figure(figsize=config.FIG_FULL)
    _add_page_title(fig, 'Performance by Symbol  (top 25 by Profit)')

    ax = fig.add_axes([0.02, 0.04, 0.96, 0.86])
    ax.axis('off')

    if symbol_perf is None or symbol_perf.empty:
        ax.text(0.5, 0.5, 'Symbol performance data not available.',
                ha='center', va='center', transform=ax.transAxes)
        return fig

    display = symbol_perf.sort_values('Total_Profit', ascending=False).head(25).copy()
    display = display.reset_index()  # move Symbol from index to column

    fmt_cols = {
        'Total_Profit': lambda v: f'${v:,.0f}' if pd.notna(v) else 'N/A',
        'Win_Rate':     lambda v: f'{v:.1f}%' if pd.notna(v) else 'N/A',
        'Avg_Profit':   lambda v: f'${v:,.0f}' if pd.notna(v) else 'N/A',
        'Avg_Loss':     lambda v: f'${v:,.0f}' if pd.notna(v) else 'N/A',
        'Profit_Factor': lambda v: f'{v:.2f}' if pd.notna(v) and not np.isinf(v) else ('∞' if np.isinf(v) else 'N/A'),
        'Total_Trades': lambda v: f'{v:.0f}' if pd.notna(v) else 'N/A',
        'Avg_Pct_Return': lambda v: f'{v:.2f}%' if pd.notna(v) else 'N/A',
        'Avg_Bars_Held': lambda v: f'{v:.1f}' if pd.notna(v) else 'N/A',
    }
    for col, fmt in fmt_cols.items():
        if col in display.columns:
            display[col] = display[col].apply(fmt)

    # Trim column headers for readability
    rename = {
        'Total_Profit': 'Profit', 'Win_Rate': 'Win%', 'Avg_Profit': 'AvgWin',
        'Avg_Loss': 'AvgLoss', 'Profit_Factor': 'PF', 'Total_Trades': 'Trades',
        'Avg_Pct_Return': 'Avg%Ret', 'Avg_Bars_Held': 'AvgBars',
    }
    display = display.rename(columns=rename)
    # Keep desired cols in order
    keep = ['Symbol', 'Trades', 'Profit', 'Win%', 'AvgWin', 'AvgLoss', 'PF', 'Avg%Ret', 'AvgBars']
    keep = [c for c in keep if c in display.columns]
    display = display[keep]

    col_widths = _auto_col_widths(display)
    draw_dataframe_table(ax, display, col_widths=col_widths, font_size=7)

    n_total = len(symbol_perf)
    if n_total > 25:
        fig.text(0.5, 0.025, f'Showing top 25 of {n_total} symbols by profit.',
                 ha='center', va='bottom', fontsize=7, color=T['text_muted'])
    return fig


def build_top_bottom_trades_page(trades_df: pd.DataFrame, top_n: int = 10) -> plt.Figure:
    """Page 8 — top N winners + top N losers side by side."""
    T = _T()
    fig = plt.figure(figsize=config.FIG_FULL)
    _add_page_title(fig, f'Top {top_n} Trades — Winners & Losers')

    gs = mgridspec.GridSpec(1, 2, figure=fig,
                            top=0.90, bottom=0.04, left=0.03, right=0.97,
                            wspace=0.10)

    cols = [c for c in ['Symbol', 'Date', 'Ex. date', 'Profit', '% Profit', '# bars']
            if c in trades_df.columns]

    for panel_idx, (label, ascending) in enumerate([('Winners', False), ('Losers', True)]):
        ax = fig.add_subplot(gs[0, panel_idx])
        ax.axis('off')

        if 'Profit' in trades_df.columns:
            df = trades_df.sort_values('Profit', ascending=ascending).head(top_n)[cols].copy()
            for dc in ['Date', 'Ex. date']:
                if dc in df and pd.api.types.is_datetime64_any_dtype(df[dc]):
                    df[dc] = df[dc].dt.strftime('%Y-%m-%d')
            if 'Profit' in df:
                df['Profit'] = df['Profit'].apply(
                    lambda v: f'${v:,.0f}' if pd.notna(v) else 'N/A')
            if '% Profit' in df:
                df['% Profit'] = df['% Profit'].apply(
                    lambda v: f'{v:.2f}%' if pd.notna(v) else 'N/A')
            if '# bars' in df:
                df['# bars'] = df['# bars'].apply(
                    lambda v: f'{v:.0f}' if pd.notna(v) else 'N/A')
            color = T['positive'] if label == 'Winners' else T['negative']
            draw_dataframe_table(ax, df, font_size=7, header_bg=color)
            ax.set_title(label, fontsize=config.FONT_SIZE_H2, fontweight='bold',
                         color=color, pad=6)
        else:
            ax.text(0.5, 0.5, 'No trade data.', ha='center', va='center',
                    transform=ax.transAxes)
    return fig


def build_monte_carlo_page(
    mc_results: dict,
    initial_equity: float,
    mc_dd_neg: bool,
) -> Optional[plt.Figure]:
    """Page 9 — MC fan chart + 3 distribution histograms + percentile table."""
    if not mc_results:
        return None
    T = _T()
    fig = plt.figure(figsize=config.FIG_FULL)
    _add_page_title(fig, 'Monte Carlo Simulation')

    gs = mgridspec.GridSpec(3, 2, figure=fig,
                            top=0.91, bottom=0.05, left=0.08, right=0.97,
                            hspace=0.50, wspace=0.30,
                            height_ratios=[1.8, 1.0, 0.9])

    # — Fan chart (spans both cols) —
    ax_fan = fig.add_subplot(gs[0, :])
    equity_paths = mc_results.get('simulated_equity_paths')
    if equity_paths is not None and not equity_paths.empty:
        n_sims = equity_paths.shape[1]
        x = equity_paths.index
        p5  = equity_paths.quantile(0.05,  axis=1)
        p25 = equity_paths.quantile(0.25,  axis=1)
        p50 = equity_paths.quantile(0.50,  axis=1)
        p75 = equity_paths.quantile(0.75,  axis=1)
        p95 = equity_paths.quantile(0.95,  axis=1)
        ax_fan.fill_between(x, p5, p95, color=T['mc_fill'], alpha=0.45, label='5–95th pct')
        ax_fan.fill_between(x, p25, p75, color=T['primary'], alpha=0.20, label='25–75th pct')
        ax_fan.plot(x, p50, color=T['primary'], linewidth=2.0, label='Median')
        ax_fan.axhline(initial_equity, color=T['neutral'], linestyle=':', linewidth=1.0,
                       label=f'Initial (${initial_equity:,.0f})')
        ax_fan.yaxis.set_major_formatter(
            mtick.FuncFormatter(lambda v, _: f'${v:,.0f}'))
        ax_fan.legend(fontsize=7, loc='upper left')
        _style_ax(ax_fan, title=f'Equity Paths ({n_sims:,} simulations)',
                  xlabel='Trade #', ylabel='Simulated Equity ($)')
    else:
        ax_fan.text(0.5, 0.5, 'MC equity paths not available.',
                    ha='center', va='center', transform=ax_fan.transAxes)

    # — Final equity dist (row 1, col 0) —
    import seaborn as sns
    ax_fe = fig.add_subplot(gs[1, 0])
    fe = mc_results.get('final_equities')
    if fe is not None and not fe.empty:
        sns.histplot(fe.dropna(), bins=40, ax=ax_fe, color=T['primary'], alpha=0.65, kde=True,
                     edgecolor=T['bg'], line_kws={'linewidth': 1.2, 'color': T['accent']})
        ax_fe.xaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f'${v:,.0f}'))
        ax_fe.axvline(fe.median(), color=T['accent'], linestyle='--', linewidth=1.0)
    _style_ax(ax_fe, title='Final Equity', xlabel='$ Equity', ylabel='Freq')

    # — CAGR dist (row 1, col 1) —
    ax_cagr = fig.add_subplot(gs[1, 1])
    cagr = mc_results.get('cagrs')
    if cagr is not None and not cagr.empty:
        cagr_pct = cagr.dropna() * 100
        sns.histplot(cagr_pct, bins=40, ax=ax_cagr, color=T['positive'], alpha=0.65, kde=True,
                     edgecolor=T['bg'], line_kws={'linewidth': 1.2, 'color': T['accent']})
        ax_cagr.xaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0))
        ax_cagr.axvline(0, color=T['negative'], linestyle='--', linewidth=0.9)
    _style_ax(ax_cagr, title='CAGR', xlabel='CAGR (%)', ylabel='Freq')

    # — Percentile table (row 2, spans both) —
    ax_tbl = fig.add_subplot(gs[2, :])
    ax_tbl.axis('off')
    _draw_mc_percentile_table(ax_tbl, mc_results, initial_equity, mc_dd_neg)

    return fig


def build_wfa_page(
    wfa_result: dict,
    wfa_split_date: Optional[str],
    wfa_split_ratio: Optional[float],
    trades_df: pd.DataFrame,
    daily_equity: pd.Series,
) -> Optional[plt.Figure]:
    """Page 10 — WFA verdict + IS vs OOS equity. Returns None when WFA disabled."""
    if not wfa_result or wfa_split_date is None:
        return None

    T = _T()
    fig = plt.figure(figsize=config.FIG_FULL)
    _add_page_title(fig, 'Walk-Forward Analysis (WFA)')

    gs = mgridspec.GridSpec(2, 2, figure=fig,
                            top=0.91, bottom=0.06, left=0.08, right=0.97,
                            hspace=0.40, wspace=0.25,
                            height_ratios=[0.6, 1.4])

    # — Verdict tile (top-left) —
    verdict = wfa_result.get('wfa_verdict', 'N/A')
    oos_pnl = wfa_result.get('oos_pnl_pct')
    positive_v = None
    if verdict == 'Pass':
        positive_v = True
    elif verdict == 'Likely Overfitted':
        positive_v = False

    ax_v = fig.add_subplot(gs[0, 0])
    draw_kpi_tile(ax_v, 'WFA Verdict', verdict, positive=positive_v)

    ax_oos = fig.add_subplot(gs[0, 1])
    oos_str = f'{oos_pnl:+.2%}' if oos_pnl is not None else 'N/A'
    oos_pos = (True if (oos_pnl or 0) > 0 else False) if oos_pnl is not None else None
    draw_kpi_tile(ax_oos, 'OOS P&L', oos_str, positive=oos_pos)

    # — IS vs OOS equity split (bottom spans both) —
    ax_eq = fig.add_subplot(gs[1, :])
    use_dates = 'Ex. date' in trades_df and pd.api.types.is_datetime64_any_dtype(trades_df['Ex. date'])
    x = trades_df['Ex. date'] if use_dates else trades_df.index

    if 'Equity' in trades_df and pd.api.types.is_numeric_dtype(trades_df['Equity']):
        try:
            split_dt = pd.to_datetime(wfa_split_date)
            if use_dates:
                is_mask = trades_df['Ex. date'] < split_dt
                oos_mask = ~is_mask
            else:
                # approximate by index fraction
                split_idx = int(len(trades_df) * (wfa_split_ratio or 0.8))
                is_mask = trades_df.index < split_idx
                oos_mask = ~is_mask

            ax_eq.plot(x[is_mask], trades_df['Equity'][is_mask],
                       color=T['primary'], linewidth=1.4, label='In-Sample')
            ax_eq.plot(x[oos_mask], trades_df['Equity'][oos_mask],
                       color=T['accent'], linewidth=1.4, label='Out-of-Sample')
            if use_dates:
                ax_eq.axvline(split_dt, color=T['negative'], linestyle='--',
                              linewidth=1.2, label=f'Split: {wfa_split_date}')
            ax_eq.yaxis.set_major_formatter(
                mtick.FuncFormatter(lambda v, _: f'${v:,.0f}'))
            ax_eq.legend(fontsize=8, loc='upper left')
        except Exception:
            ax_eq.text(0.5, 0.5, 'Could not plot IS/OOS equity split.',
                       ha='center', va='center', transform=ax_eq.transAxes)
    else:
        ax_eq.text(0.5, 0.5, 'Equity data not available.',
                   ha='center', va='center', transform=ax_eq.transAxes)
    _style_ax(ax_eq, title='Equity Curve — IS vs OOS',
              xlabel='Date' if use_dates else 'Trade #',
              ylabel='Portfolio Value ($)')

    return fig


def build_appendix_metrics_page(overall_metrics_text: str) -> plt.Figure:
    """Appendix page: full verbose text metrics in monospace."""
    return _build_text_page('Appendix — Full Performance Metrics', overall_metrics_text)


def build_appendix_data_quality_page(cleaning_summary: str) -> plt.Figure:
    """Appendix page: data cleaning summary."""
    return _build_text_page('Appendix — Data Quality Summary', cleaning_summary)


# ---------------------------------------------------------------------------
# Main PDF entry point
# ---------------------------------------------------------------------------

def generate_tearsheet_pdf(report_data: dict, output_path: str):
    """
    New-style tearsheet PDF generator.

    Parameters
    ----------
    report_data : dict with keys:
        name, run_date, trades_df, initial_equity, daily_equity, daily_returns,
        benchmark_df, benchmark_returns, benchmark_ticker, monthly_perf,
        symbol_perf, mc_results, wfa_result, wfa_split_date, wfa_split_ratio,
        equity_dd_percent, dd_periods_df, max_equity_dd_pct, core_metrics,
        risk_free_rate, rolling_window, cleaning_summary, overall_metrics_text,
        top_n_trades
    output_path : str  — destination .pdf path
    """
    print(f"\n--- Generating Tearsheet PDF: {output_path} ---")
    T = _T()

    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
    except Exception:
        pass

    trades_df        = report_data.get('trades_df', pd.DataFrame())
    initial_equity   = report_data.get('initial_equity', 50_000)
    daily_equity     = report_data.get('daily_equity', pd.Series(dtype=float))
    daily_returns    = report_data.get('daily_returns', pd.Series(dtype=float))
    benchmark_df     = report_data.get('benchmark_df')
    benchmark_ticker = report_data.get('benchmark_ticker', 'SPY')
    monthly_perf     = report_data.get('monthly_perf', pd.DataFrame())
    symbol_perf      = report_data.get('symbol_perf', pd.DataFrame())
    mc_results       = report_data.get('mc_results', {})
    wfa_result       = report_data.get('wfa_result', {})
    wfa_split_date   = report_data.get('wfa_split_date')
    wfa_split_ratio  = report_data.get('wfa_split_ratio')
    equity_dd_pct    = report_data.get('equity_dd_percent', pd.Series(dtype=float))
    dd_periods_df    = report_data.get('dd_periods_df', pd.DataFrame())
    max_dd_pct       = report_data.get('max_equity_dd_pct', 0.0) or 0.0
    core_metrics     = report_data.get('core_metrics', {})
    risk_free_rate   = report_data.get('risk_free_rate', 0.0)
    rolling_window   = report_data.get('rolling_window', 50)
    cleaning_summary = report_data.get('cleaning_summary', '')
    overall_text     = report_data.get('overall_metrics_text', '')
    top_n_trades     = report_data.get('top_n_trades', 10)
    mc_dd_neg        = report_data.get('mc_dd_neg', True)
    report_name      = report_data.get('name', 'Strategy')
    run_date         = report_data.get('run_date', datetime.now().strftime('%Y-%m-%d'))

    # --- Compute headline metrics for cover ---
    total_profit = core_metrics.get('total_profit', 0) or 0
    final_equity = initial_equity + total_profit
    total_return = (final_equity / initial_equity - 1) if initial_equity > 0 else None
    if not trades_df.empty:
        start_d = trades_df['Date'].min() if 'Date' in trades_df else None
        end_d   = trades_df['Ex. date'].max() if 'Ex. date' in trades_df else None
        start_str = start_d.strftime('%Y-%m-%d') if pd.notna(start_d) else 'N/A'
        end_str   = end_d.strftime('%Y-%m-%d') if pd.notna(end_d) else 'N/A'
        dur_years = ((end_d - start_d).days / 365.25
                     if pd.notna(start_d) and pd.notna(end_d) else 0)
    else:
        start_str, end_str, dur_years = 'N/A', 'N/A', 0

    cagr = calculations.calculate_cagr(initial_equity, final_equity, dur_years) if dur_years > 0 else None
    sharpe_val = core_metrics.get('sharpe')
    pf_val = core_metrics.get('profit_factor')

    # VaR/CVaR
    var_95 = cvar_95 = var_99 = cvar_99 = np.nan
    if 'Profit' in trades_df.columns:
        var_95, cvar_95 = calculations.calculate_var_cvar(trades_df['Profit'], level=0.05)
        var_99, cvar_99 = calculations.calculate_var_cvar(trades_df['Profit'], level=0.01)

    report_meta = {
        'name': report_name, 'run_date': run_date,
        'start_date': start_str, 'end_date': end_str,
        'total_return': total_return, 'cagr': cagr,
        'max_dd': max_dd_pct / 100.0 if max_dd_pct else None,
        'sharpe': sharpe_val, 'profit_factor': pf_val,
        'total_trades': core_metrics.get('total_trades'),
        'initial_equity': initial_equity,
    }

    # --- Build pages ---
    with _plotting.themed():
        pages = []

        # P1: Cover
        pages.append(('Cover', build_cover_page(report_meta)))

        # P2: Executive Summary
        pages.append(('Executive Summary', build_executive_summary_page(
            trades_df, daily_equity, benchmark_df, benchmark_ticker,
            equity_dd_pct, core_metrics, risk_free_rate, initial_equity,
            wfa_split_date=wfa_split_date,
        )))

        # P3: Equity + Drawdown chart (full page)
        pages.append(('Equity & Drawdown', _plotting.plot_equity_and_drawdown(
            trades_df, equity_dd_pct, wfa_split_date)))

        # P4: Benchmark comparison
        pages.append(('Benchmark Comparison', _plotting.plot_benchmark_comparison(
            daily_equity, benchmark_df, benchmark_ticker)))

        # P5: Risk & Return
        pages.append(('Risk & Return', build_risk_return_page(
            trades_df, daily_equity, risk_free_rate, rolling_window,
            var_95, cvar_95, var_99, cvar_99,
        )))

        # P6: Drawdowns
        pages.append(('Drawdowns', build_drawdowns_page(
            trades_df, equity_dd_pct, dd_periods_df, max_dd_pct,
        )))

        # P7: Seasonality
        if monthly_perf is not None and not monthly_perf.empty:
            pages.append(('Seasonality', build_seasonality_page(monthly_perf)))

        # P8: Trade Analysis
        pages.append(('Trade Analysis', build_trade_analysis_page(trades_df)))

        # P9: Symbol Performance
        if symbol_perf is not None and not symbol_perf.empty:
            pages.append(('Symbol Performance', build_symbol_performance_page(symbol_perf)))

        # P10: Top/Bottom Trades
        pages.append(('Top/Bottom Trades', build_top_bottom_trades_page(
            trades_df, top_n=top_n_trades)))

        # P11: Monte Carlo
        mc_page = build_monte_carlo_page(mc_results, initial_equity, mc_dd_neg)
        if mc_page is not None:
            pages.append(('Monte Carlo', mc_page))

        # P12: WFA (optional)
        wfa_page = build_wfa_page(wfa_result, wfa_split_date, wfa_split_ratio,
                                   trades_df, daily_equity)
        if wfa_page is not None:
            pages.append(('Walk-Forward Analysis', wfa_page))

        # Appendix
        if overall_text:
            pages.append(('Appendix — Metrics', build_appendix_metrics_page(overall_text)))
        if cleaning_summary:
            pages.append(('Appendix — Data Quality', build_appendix_data_quality_page(cleaning_summary)))

        # --- Two-pass: stamp headers/footers then save ---
        total_pages = len(pages)
        try:
            with PdfPages(output_path) as pdf_pages:
                for page_num, (page_title, fig) in enumerate(pages, start=1):
                    if fig is None or not isinstance(fig, plt.Figure):
                        continue
                    try:
                        _stamp_header_footer(fig, report_name, run_date,
                                             page_num, total_pages)
                        pdf_pages.savefig(fig, bbox_inches='tight', pad_inches=0.05)
                    except Exception as page_err:
                        print(f"WARNING: Could not save page '{page_title}': {page_err}")
                    finally:
                        if plt.fignum_exists(fig.number):
                            plt.close(fig)
            print(f"Tearsheet PDF saved: {output_path}  ({total_pages} pages)")
        except Exception as pdf_err:
            print(f"FATAL: PDF save failed: {pdf_err}")
            traceback.print_exc()
        finally:
            plt.close('all')

    return output_path


# ---------------------------------------------------------------------------
# Inline drawing helpers (draw INTO an existing ax rather than creating fig)
# ---------------------------------------------------------------------------

def _draw_equity_inline(ax, daily_equity: pd.Series, benchmark_df, benchmark_ticker: str,
                         wfa_split_date=None):
    T = _T()
    if daily_equity.empty:
        ax.text(0.5, 0.5, 'No equity data', ha='center', va='center',
                transform=ax.transAxes)
        return

    # Normalise tz
    eq = daily_equity.copy()
    eq.index = pd.to_datetime(eq.index)
    if eq.index.tz is not None:
        eq.index = eq.index.tz_localize(None)

    ax.plot(eq.index, eq.values, color=T['primary'], linewidth=1.4, label='Strategy')

    if benchmark_df is not None and not benchmark_df.empty and 'Benchmark_Price' in benchmark_df.columns:
        try:
            bdf = benchmark_df.copy()
            bdf.index = pd.to_datetime(bdf.index)
            if bdf.index.tz is not None:
                bdf.index = bdf.index.tz_localize(None)
            common = eq.index.intersection(bdf.index)
            if len(common) > 1:
                eq_c = eq.loc[common]
                bp_c = bdf.loc[common, 'Benchmark_Price']
                bp_norm = (bp_c / bp_c.iloc[0]) * eq_c.iloc[0]
                ax.plot(bp_norm.index, bp_norm.values, color=T['accent'],
                        linewidth=1.2, linestyle='--', label=f'{benchmark_ticker} B&H')
        except Exception:
            pass

    if wfa_split_date:
        try:
            ax.axvline(pd.to_datetime(wfa_split_date), color=T['negative'],
                       linestyle='--', linewidth=1.0, label=f'WFA split')
        except Exception:
            pass

    ax.legend(fontsize=7, loc='upper left')
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f'${v:,.0f}'))
    ax.tick_params(axis='x', labelsize=7)


def _draw_underwater_inline(ax, trades_df: pd.DataFrame, equity_dd_percent: pd.Series):
    T = _T()
    if not isinstance(equity_dd_percent, pd.Series) or equity_dd_percent.empty:
        ax.text(0.5, 0.5, 'No drawdown data', ha='center', va='center',
                transform=ax.transAxes)
        return

    use_dates = 'Ex. date' in trades_df.columns and pd.api.types.is_datetime64_any_dtype(trades_df['Ex. date'])
    x = trades_df['Ex. date'] if use_dates else trades_df.index
    underwater = -equity_dd_percent

    ax.fill_between(x, underwater, 0, color=T['dd_fill'], alpha=0.8)
    ax.plot(x, underwater, color=T['negative'], linewidth=0.7)
    ax.axhline(0, color=T['neutral'], linestyle='-', linewidth=0.5)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=0))
    bottom = min(underwater.min() * 1.05, -1)
    ax.set_ylim(bottom=bottom, top=0.5)
    ax.tick_params(axis='x', labelsize=7)


def _draw_mae_mfe_inline(ax, trades_df: pd.DataFrame, xcol: str, xlabel: str):
    T = _T()
    required = [xcol, '% Profit', 'Win']
    if any(c not in trades_df.columns for c in required):
        ax.text(0.5, 0.5, f'{xcol} data not available.', ha='center', va='center',
                transform=ax.transAxes)
        return
    df = trades_df.dropna(subset=required).copy()
    if df.empty:
        return
    df['Win'] = df['Win'].astype(bool)
    wins, losses = df[df['Win']], df[~df['Win']]
    ax.scatter(losses[xcol], losses['% Profit'], color=T['negative'],
               alpha=0.35, s=12, edgecolors='none', label='Loss')
    ax.scatter(wins[xcol], wins['% Profit'], color=T['positive'],
               alpha=0.35, s=12, edgecolors='none', label='Win')
    ax.axhline(0, color=T['neutral'], linestyle='--', linewidth=0.7)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=1))
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=100.0, decimals=1))
    ax.legend(fontsize=7)


def _draw_mc_percentile_table(ax, mc_results: dict, initial_equity: float, mc_dd_neg: bool):
    T = _T()
    if 'mc_detailed_percentiles' not in mc_results:
        ax.text(0.5, 0.5, 'MC percentile data not available.',
                ha='center', va='center', transform=ax.transAxes)
        return
    detailed = mc_results['mc_detailed_percentiles']
    if not isinstance(detailed, dict) or not detailed:
        return

    try:
        df = pd.DataFrame(detailed)
        ordered_keys = ['Final Equity', 'CAGR', 'Max Drawdown $', 'Max Drawdown %', 'Lowest Equity']
        df = df[[c for c in ordered_keys if c in df.columns]]

        pct_labels = [f'P{p}' for p in config.MC_PERCENTILES]
        avail = [p for p in pct_labels if p.replace('P', '') + 'th' in df.index or p in df.index]
        # Use the raw index as-is if first format doesn't match
        df.index = [f'P{idx.replace("th", "").replace("st", "").replace("nd", "").replace("rd", "")}' for idx in df.index]

        def fmt(val, col_name):
            if pd.isna(val):
                return 'N/A'
            if 'Equity' in col_name or 'Drawdown $' in col_name:
                return f'${val:,.0f}'
            elif 'CAGR' in col_name:
                return f'{val*100:.1f}%'
            elif '%' in col_name:
                return f'{val:.1f}%'
            return f'{val:.2f}'

        fmt_df = df.copy().reset_index()
        fmt_df.columns = ['Pct'] + list(df.columns)
        for col in df.columns:
            fmt_df[col] = fmt_df[col].apply(lambda v: fmt(v, col))

        rename = {'Final Equity': 'Final Eq.', 'Max Drawdown $': 'Max DD$',
                  'Max Drawdown %': 'Max DD%', 'Lowest Equity': 'Min Eq.'}
        fmt_df = fmt_df.rename(columns=rename)

        col_widths = _auto_col_widths(fmt_df)
        draw_dataframe_table(ax, fmt_df, col_widths=col_widths, font_size=7)
    except Exception as e:
        ax.text(0.5, 0.5, f'Error rendering MC table: {e}',
                ha='center', va='center', transform=ax.transAxes, fontsize=8)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _add_page_title(fig: plt.Figure, title: str):
    T = _T()
    title_ax = fig.add_axes([0, 0.955, 1, 0.045])
    title_ax.set_facecolor(T['primary'])
    title_ax.axis('off')
    title_ax.text(0.5, 0.5, title, ha='center', va='center',
                  fontsize=11, color='white', fontweight='bold',
                  transform=title_ax.transAxes)


def _build_text_page(page_title: str, text: str) -> plt.Figure:
    T = _T()
    fig = plt.figure(figsize=config.FIG_FULL)
    _add_page_title(fig, page_title)
    ax = fig.add_axes([0.04, 0.04, 0.92, 0.88])
    ax.axis('off')
    ax.text(0.01, 0.97, text, va='top', ha='left', transform=ax.transAxes,
            fontsize=7, family='monospace', color=T['text'],
            wrap=False)
    return fig


def _fmt_pct(val, force_sign=True) -> str:
    if val is None:
        return 'N/A'
    try:
        if pd.isna(val):
            return 'N/A'
    except (TypeError, ValueError):
        pass
    sign = '+' if force_sign and val >= 0 else ''
    return f'{sign}{val*100:.1f}%'


def _fmt_float(val, decimals: int = 2) -> str:
    if val is None:
        return 'N/A'
    try:
        if pd.isna(val):
            return 'N/A'
    except (TypeError, ValueError):
        pass
    return f'{val:.{decimals}f}'


def _fmt_int(val) -> str:
    if val is None:
        return 'N/A'
    try:
        if pd.isna(val):
            return 'N/A'
    except (TypeError, ValueError):
        pass
    return f'{int(val):,}'


def _fmt_curr(val) -> str:
    if val is None:
        return 'N/A'
    try:
        if pd.isna(val):
            return 'N/A'
    except (TypeError, ValueError):
        pass
    sign = '+' if val >= 0 else ''
    return f'{sign}${val:,.0f}'


def _auto_col_widths(df: pd.DataFrame) -> list:
    """Equal-width columns that sum to ~1.0, with first col slightly wider."""
    n = len(df.columns)
    if n <= 1:
        return [1.0]
    first_w = min(0.18, 1.0 / n * 1.5)
    rest_w = (1.0 - first_w) / (n - 1)
    return [first_w] + [rest_w] * (n - 1)
