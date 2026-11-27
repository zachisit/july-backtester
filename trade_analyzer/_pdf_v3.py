# _pdf_v3.py — "v3" institutional tearsheet (dense 2-page layout).
#
# Inspired by clean quant-fund performance reports: a metrics-first page 1
# (header + 5 KPI tiles + two-column detailed-metrics tables) and a charts page
# 2 (trailing-period tiles + monthly $ strip + equity / drawdown / rolling
# small-multiples). Rendered in the project's navy/gold theme
# (default_config.THEME) with matplotlib only — no new dependencies.
#
# Entry point: generate_tearsheet_v3(report_data, output_path). The report_data
# dict is the same one built by analyzer.py for generate_tearsheet_pdf, plus an
# optional 'trading_days' key.
from __future__ import annotations

import os
import traceback
from datetime import datetime
from typing import Optional

import matplotlib.gridspec as mgridspec
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import FancyBboxPatch

from . import calculations
from . import default_config as config
from . import metrics_v3 as mv3
from . import plotting as _plotting


def _app_version() -> str:
    """Best-effort read of the project version (version.py at the repo root)."""
    try:
        from version import __version__  # type: ignore
        return f"v{__version__}"
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _is_na(v) -> bool:
    if v is None:
        return True
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


def _curr(v, signed: bool = False) -> str:
    if _is_na(v):
        return "N/A"
    v = float(v)
    if np.isinf(v):
        return "∞"
    sign = "-" if v < 0 else ("+" if signed else "")
    return f"{sign}${abs(v):,.0f}"


def _pct(v, decimals: int = 2, signed: bool = False, already_pct: bool = False) -> str:
    if _is_na(v):
        return "N/A"
    v = float(v)
    if np.isinf(v):
        return "∞"
    x = v if already_pct else v * 100.0
    sign = "+" if (signed and x >= 0) else ""
    return f"{sign}{x:.{decimals}f}%"


def _num(v, decimals: int = 2) -> str:
    if _is_na(v):
        return "N/A"
    v = float(v)
    if np.isinf(v):
        return "∞"
    return f"{v:.{decimals}f}"


def _int(v) -> str:
    if _is_na(v):
        return "N/A"
    try:
        return f"{int(round(float(v))):,}"
    except (TypeError, ValueError):
        return "N/A"


# ---------------------------------------------------------------------------
# Low-level drawing primitives
# ---------------------------------------------------------------------------

def _T() -> dict:
    return config.THEME


def _draw_kpi_tile(ax, label: str, value: str, subtitle: str = "",
                   positive: Optional[bool] = None):
    """A bordered KPI card in the house navy/gold identity: soft-fill rounded box,
    a gold rule down the left edge, small-caps label, large value, muted subtitle."""
    T = _T()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    bg = FancyBboxPatch((0.04, 0.10), 0.92, 0.80,
                        boxstyle="round,pad=0.012,rounding_size=0.04",
                        facecolor=T["kpi_bg"], edgecolor=T["kpi_border"],
                        linewidth=0.8, zorder=0, mutation_aspect=0.5)
    ax.add_patch(bg)
    # gold accent bar down the left edge of the card
    ax.plot([0.075, 0.075], [0.20, 0.80], color=T["accent"], linewidth=2.6,
            solid_capstyle="butt", transform=ax.transAxes, zorder=1)

    val_color = T["primary"]
    if positive is True:
        val_color = T["positive"]
    elif positive is False:
        val_color = T["negative"]

    ax.text(0.15, 0.68, label.upper(), ha="left", va="center",
            fontsize=7, color=T["text_muted"], fontweight="bold",
            transform=ax.transAxes)
    ax.text(0.15, 0.43, str(value), ha="left", va="center",
            fontsize=15, color=val_color, fontweight="bold",
            transform=ax.transAxes)
    if subtitle:
        ax.text(0.15, 0.21, subtitle, ha="left", va="center",
                fontsize=7, color=T["text_muted"], transform=ax.transAxes)


def _draw_metric_column(ax, blocks: list):
    """Render a stacked list of metric sections into a [0,1]×[0,1] axis.

    ``blocks`` is a list of (section_title, rows) where rows is a list of
    (label, value_str, is_negative_bool)."""
    T = _T()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    # total logical lines = sum(rows) + one header line per block
    total_lines = sum(len(rows) for _, rows in blocks) + len(blocks)
    # a little breathing room between blocks
    total_slots = total_lines + max(0, len(blocks) - 1) * 0.5
    line_h = 1.0 / max(total_slots, 1)
    y = 1.0

    for section_title, rows in blocks:
        # section header — navy label with a short gold underline (house identity)
        y -= line_h
        ax.text(0.0, y + line_h * 0.20, section_title.upper(), ha="left", va="center",
                fontsize=8, color=T["primary"], fontweight="bold",
                transform=ax.transAxes)
        ax.plot([0.0, 0.20], [y - line_h * 0.10, y - line_h * 0.10],
                color=T["accent"], linewidth=1.8, transform=ax.transAxes)
        for label, value, is_neg in rows:
            y -= line_h
            vcolor = T["negative"] if is_neg else T["text"]
            ax.text(0.0, y + line_h * 0.5, label, ha="left", va="center",
                    fontsize=7.5, color=T["text_muted"], transform=ax.transAxes)
            ax.text(1.0, y + line_h * 0.5, value, ha="right", va="center",
                    fontsize=7.5, color=vcolor, fontweight="bold",
                    transform=ax.transAxes)
            ax.plot([0.0, 1.0], [y, y], color=T["grid"], linewidth=0.4,
                    transform=ax.transAxes)
        y -= line_h * 0.5  # gap between blocks


# ---------------------------------------------------------------------------
# Page 1 — header + KPIs + detailed metrics
# ---------------------------------------------------------------------------

def build_v3_page1(meta: dict, M: dict) -> plt.Figure:
    T = _T()
    fig = plt.figure(figsize=config.FIG_FULL)
    fig.patch.set_facecolor(T["bg"])

    # --- Navy title bar (house identity) ---
    # NB: keep the axes patch visible (do NOT call axis('off'), which hides the
    # navy fill); suppress ticks/spines manually instead.
    bar = fig.add_axes([0.0, 0.905, 1.0, 0.095])
    bar.set_facecolor(T["primary"])
    bar.set_xlim(0, 1)
    bar.set_ylim(0, 1)
    bar.set_xticks([])
    bar.set_yticks([])
    for _sp in bar.spines.values():
        _sp.set_visible(False)
    bar.text(0.05, 0.80, "STRATEGY TEARSHEET", ha="left", va="center",
             fontsize=7.5, color="#bbdefb", fontweight="bold", transform=bar.transAxes)
    bar.text(0.05, 0.40, meta.get("name", "Strategy"), ha="left", va="center",
             fontsize=19, color="white", fontweight="bold", transform=bar.transAxes)
    _ver = meta.get("app_version", "")
    if _ver:
        bar.text(0.95, 0.80, _ver, ha="right", va="center", fontsize=7.5,
                 color="#bbdefb", transform=bar.transAxes)
    bar.text(0.95, 0.40, f"Generated {meta.get('run_date', '')}", ha="right",
             va="center", fontsize=8, color="#bbdefb", transform=bar.transAxes)
    # gold rule beneath the bar
    _hline(fig, 0.0, 1.0, 0.902, color=T["accent"], lw=2.5)

    # sub-line + OOS marker
    subline = (f"{meta.get('start_date', 'N/A')}  →  {meta.get('end_date', 'N/A')}"
               f"   ·   {_int(meta.get('total_trades'))} trades"
               f"   ·   {_num(meta.get('duration_years'), 1)} years")
    fig.text(0.05, 0.882, subline, ha="left", va="center",
             fontsize=8.5, color=T["text_muted"])
    if meta.get("oos_date"):
        _oos_label = f"Walk-forward OOS split · {meta['oos_date']}"
        if meta.get("wfa_approx"):
            # Split not taken from the run's own inputs; flag it (#477).
            _oos_label += " (closed-trade approximation)"
        fig.text(0.95, 0.882, _oos_label,
                 ha="right", va="center", fontsize=8, color=T["text_muted"],
                 style="italic")

    # --- Headline (5 bordered KPI tiles) ---
    fig.text(0.05, 0.858, "HEADLINE", ha="left", va="bottom",
             fontsize=8, color=T["primary"], fontweight="bold")
    kpi_specs = [
        ("Net P&L", _curr(M.get("total_profit")), "", (M.get("total_profit") or 0) >= 0),
        ("Return / DD", _num(M.get("ret_dd")), f"{_num(meta.get('duration_years'), 1)} yrs", None),
        ("Sharpe", _num(M.get("sharpe")), f"Sortino {_num(M.get('sortino'))}", None),
        ("Max Drawdown", _curr(-abs(M.get("max_dd_dollars") or 0)),
         _pct(-abs(M.get("max_dd_pct") or 0), already_pct=True), False),
        ("Win Rate", _pct(M.get("win_rate")), f"PF {_num(M.get('profit_factor'))}", None),
    ]
    gs_kpi = mgridspec.GridSpec(1, 5, figure=fig, left=0.05, right=0.95,
                                top=0.85, bottom=0.725, wspace=0.14)
    for i, (label, value, subtitle, pos) in enumerate(kpi_specs):
        ax = fig.add_subplot(gs_kpi[0, i])
        _draw_kpi_tile(ax, label, value, subtitle, positive=pos)

    # --- Full metrics (two columns) ---
    fig.text(0.05, 0.688, "FULL METRICS", ha="left", va="bottom",
             fontsize=8, color=T["primary"], fontweight="bold")
    _hline(fig, 0.05, 0.95, 0.683, color=T["grid"], lw=0.6)

    left_blocks = [
        ("Performance", [
            ("Net P&L", _curr(M.get("total_profit")), (M.get("total_profit") or 0) < 0),
            ("Gross P&L", _curr(M.get("gross_profit")), False),
            ("Est. Costs", _curr(-abs(M.get("transaction_fees") or 0)),
             (M.get("transaction_fees") or 0) > 0),
            ("Sharpe", _num(M.get("sharpe")), False),
            ("Sortino", _num(M.get("sortino")), False),
            ("Calmar", _num(M.get("calmar")), False),
            ("Omega", _num(M.get("omega")), False),
            ("Gain / Pain (Ω-1)", _num(M.get("gain_to_pain")), False),
            ("Serenity*", _num(M.get("serenity")), False),
            ("Recovery Factor", _num(M.get("recovery_factor")), False),
        ]),
        ("Periodic Returns", [
            ("Avg Month P&L", _curr(M.get("avg_monthly_pnl")), (M.get("avg_monthly_pnl") or 0) < 0),
            ("Best / Worst Month",
             f"{_pct(M.get('best_month'), signed=True)}  /  {_pct(M.get('worst_month'), signed=True)}",
             False),
            ("Best / Worst Day",
             f"{_pct(M.get('best_day'), signed=True)}  /  {_pct(M.get('worst_day'), signed=True)}",
             False),
            ("Best / Worst Year",
             f"{_pct(M.get('best_year'), signed=True)}  /  {_pct(M.get('worst_year'), signed=True)}",
             False),
            ("Positive Months", _pct(M.get("positive_months"), decimals=1), False),
            ("Positive Years", _pct(M.get("positive_years"), decimals=1), False),
        ]),
    ]

    _fees = M.get("transaction_fees") or 0.0
    _ntr = M.get("total_trades") or 0
    fee_per_trade = (_fees / _ntr) if _ntr else 0.0
    right_blocks = [
        ("Risk & Shape", [
            ("Max Drawdown %", _pct(-abs(M.get("max_dd_pct") or 0), already_pct=True), True),
            ("Max Drawdown $", _curr(-abs(M.get("max_dd_dollars") or 0)), True),
            ("Volatility (ann.)", _pct(M.get("volatility_ann")), False),
            ("VaR 95% (active)", _pct(M.get("var_95")), True),
            ("CVaR 95% (active)", _pct(M.get("cvar_95")), True),
            ("Ulcer Index", _num(M.get("ulcer_index"), 4), False),
            ("% Time in Drawdown", _pct(M.get("pct_time_in_dd"), decimals=1), False),
            ("Skewness (mo.)", _num(M.get("skewness")), False),
            ("Excess Kurtosis (mo.)", _num(M.get("excess_kurtosis")), False),
        ]),
        ("Trade Stats", [
            ("Trades", _int(M.get("total_trades")), False),
            ("Cost / Trade", _curr(fee_per_trade), False),
            ("Win Rate", _pct(M.get("win_rate")), False),
            ("Profit Factor", _num(M.get("profit_factor")), False),
            ("Expectancy", _curr(M.get("expectancy_usd")),
             (M.get("expectancy_usd") or 0) < 0),
            ("Expectancy (R)", f"{_num(M.get('r_expectancy'))} R", False),
            ("Payoff Ratio", _num(M.get("payoff_ratio")), False),
            ("Best / Worst Trade",
             f"{_curr(M.get('best_trade'))}  /  {_curr(M.get('worst_trade'))}", False),
            ("Avg Win / Loss",
             f"{_curr(M.get('avg_win'))}  /  {_curr(M.get('avg_loss'))}", False),
            ("Max Win / Loss Streak",
             f"{_int(M.get('max_consec_wins'))}  /  {_int(M.get('max_consec_losses'))}", False),
        ]),
    ]

    ax_left = fig.add_axes([0.05, 0.055, 0.42, 0.615])
    _draw_metric_column(ax_left, left_blocks)
    ax_right = fig.add_axes([0.53, 0.055, 0.42, 0.615])
    _draw_metric_column(ax_right, right_blocks)

    # footnote for the Serenity proxy
    fig.text(0.05, 0.028,
             "*Serenity = Ulcer- and tail-penalized return (reproducible proxy; "
             "see metrics_v3.serenity_index).",
             ha="left", va="center", fontsize=6, color=T["text_muted"], style="italic")

    return fig


# ---------------------------------------------------------------------------
# Page 2 — trailing tiles + monthly strip + charts
# ---------------------------------------------------------------------------

def build_v3_page2(meta: dict, M: dict, series: dict) -> plt.Figure:
    T = _T()
    fig = plt.figure(figsize=config.FIG_FULL)
    fig.patch.set_facecolor(T["bg"])

    daily_equity = series["daily_equity"]
    daily_returns = series["daily_returns"]
    initial_equity = series["initial_equity"]
    oos_date = meta.get("oos_date")
    dd_periods_df = series.get("dd_periods_df")
    trading_days = series.get("trading_days", 252)
    rf = series.get("risk_free_rate", 0.0)

    # --- Trailing period tiles ---
    fig.text(0.05, 0.978, "TRAILING RETURNS", ha="left", va="center",
             fontsize=8, color=T["primary"], fontweight="bold")
    pr = M.get("period_returns", {})
    order = ["1M", "3M", "6M", "YTD", "1Y", "ITD"]
    gs_tiles = mgridspec.GridSpec(1, 6, figure=fig, left=0.05, right=0.95,
                                  top=0.962, bottom=0.90, wspace=0.0)
    for i, key in enumerate(order):
        ax = fig.add_subplot(gs_tiles[0, i])
        ax.axis("off")
        val = pr.get(key)
        color = T["text_muted"] if _is_na(val) else (T["positive"] if val >= 0 else T["negative"])
        ax.text(0.5, 0.80, key, ha="center", va="center", fontsize=7.5,
                color=T["text_muted"], fontweight="bold", transform=ax.transAxes)
        ax.text(0.5, 0.38, _pct(val, signed=True), ha="center", va="center",
                fontsize=13, color=color, fontweight="bold", transform=ax.transAxes)
        if i > 0:
            ax.axvline(0.0, color=T["grid"], linewidth=0.8)
    _hline(fig, 0.05, 0.95, 0.895)

    # --- Monthly $ strip ---
    labels, values, total = mv3.monthly_pnl_strip(daily_equity, initial_equity, n_months=8)
    ncell = len(labels) + 1
    if ncell > 1:
        gs_strip = mgridspec.GridSpec(1, ncell, figure=fig, left=0.05, right=0.95,
                                      top=0.88, bottom=0.825, wspace=0.0)
        cells = list(zip(labels, values)) + [("TOTAL", total)]
        for i, (lab, val) in enumerate(cells):
            ax = fig.add_subplot(gs_strip[0, i])
            ax.axis("off")
            is_total = (i == ncell - 1)
            color = T["text"] if is_total else (T["positive"] if val >= 0 else T["negative"])
            if not is_total and val < 0:
                color = T["negative"]
            ax.text(0.5, 0.78, lab.upper(), ha="center", va="center", fontsize=6.5,
                    color=T["text_muted"], fontweight="bold" if is_total else "normal",
                    transform=ax.transAxes)
            ax.text(0.5, 0.34, _curr(val), ha="center", va="center",
                    fontsize=8.5 if is_total else 8,
                    color=color, fontweight="bold", transform=ax.transAxes)
            if i > 0:
                ax.axvline(0.0, color=T["grid"], linewidth=0.8)
    fig.text(0.05, 0.808,
             "Monthly net P&L ($) — TOTAL is the sum of the months shown.",
             ha="left", va="center", fontsize=6, color=T["text_muted"], style="italic")

    # --- Charts (3 rows × 2 cols) ---
    gs = mgridspec.GridSpec(3, 2, figure=fig, left=0.06, right=0.96,
                            top=0.775, bottom=0.05, hspace=0.55, wspace=0.18)

    # Row 0 col 0: Equity (net)
    ax = fig.add_subplot(gs[0, 0])
    _plot_equity(ax, daily_equity, initial_equity, oos_date=None)
    _finish(ax, "Equity Curve (Net)")

    # Row 0 col 1: In-sample vs Live (OOS shaded)
    ax = fig.add_subplot(gs[0, 1])
    _plot_equity(ax, daily_equity, initial_equity, oos_date=oos_date)
    _finish(ax, "Equity — In-Sample vs Live")

    # Row 1 col 0: Drawdown ($)
    ax = fig.add_subplot(gs[1, 0])
    _plot_drawdown_dollars(ax, daily_equity)
    _finish(ax, "Drawdown ($)")

    # Row 1 col 1: Deepest drawdowns
    ax = fig.add_subplot(gs[1, 1])
    _plot_worst_drawdowns(ax, daily_equity, dd_periods_df)
    _finish(ax, "Deepest Drawdowns")

    # Row 2 col 0: 6-month rolling Sharpe
    ax = fig.add_subplot(gs[2, 0])
    rs = mv3.rolling_sharpe(daily_returns, window=126, risk_free_rate=rf,
                            trading_days=trading_days)
    _plot_rolling(ax, rs, color=T["primary"], zero_line=True, pct=False)
    _finish(ax, "6-Month Rolling Sharpe")

    # Row 2 col 1: 6-month rolling volatility
    ax = fig.add_subplot(gs[2, 1])
    rv = mv3.rolling_volatility(daily_returns, window=126, trading_days=trading_days)
    _plot_rolling(ax, rv, color=T["accent"], zero_line=False, pct=True)
    _finish(ax, "6-Month Rolling Volatility")

    return fig


# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

def _finish(ax, title: str):
    T = _T()
    ax.set_title(title, fontsize=8.5, color=T["primary"], fontweight="bold",
                 loc="left", pad=4)
    ax.tick_params(axis="both", labelsize=6.5, color=T["text_muted"],
                   labelcolor=T["text_muted"])
    ax.tick_params(axis="x", rotation=0)
    for sp in ax.spines.values():
        sp.set_edgecolor(T["neutral"])
        sp.set_linewidth(0.5)
    for lab in ax.get_xticklabels():
        lab.set_fontsize(6.5)


def _prep(series: pd.Series) -> pd.Series:
    s = series.dropna().copy()
    s.index = pd.to_datetime(s.index)
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_localize(None)
    return s.sort_index()


def _plot_equity(ax, daily_equity, initial_equity, oos_date=None):
    T = _T()
    eq = _prep(daily_equity)
    if eq.empty:
        ax.text(0.5, 0.5, "No equity data", ha="center", va="center",
                transform=ax.transAxes, fontsize=8)
        return
    ax.plot(eq.index, eq.values, color=T["primary"], linewidth=1.2)
    ax.fill_between(eq.index, eq.values, eq.values.min(), color=T["primary"], alpha=0.06)
    if oos_date:
        try:
            split = pd.to_datetime(oos_date)
            if getattr(split, "tz", None) is not None:
                split = split.tz_localize(None)
            if eq.index.min() < split < eq.index.max():
                ax.axvspan(split, eq.index.max(), color=T["neutral"], alpha=0.10)
                ax.axvline(split, color=T["neutral"], linestyle="--", linewidth=0.8)
                ax.text(split, ax.get_ylim()[1], " Live", ha="left", va="top",
                        fontsize=6.5, color=T["text_muted"])
        except Exception:
            pass
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"${v:,.0f}"))


def _plot_drawdown_dollars(ax, daily_equity):
    T = _T()
    eq = _prep(daily_equity)
    if eq.empty:
        ax.text(0.5, 0.5, "No equity data", ha="center", va="center",
                transform=ax.transAxes, fontsize=8)
        return
    dd = eq - eq.cummax()  # <= 0, in $
    ax.fill_between(dd.index, dd.values, 0, color=T["negative"], alpha=0.35)
    ax.plot(dd.index, dd.values, color=T["negative"], linewidth=0.6)
    ax.axhline(0, color=T["neutral"], linewidth=0.5)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"${v:,.0f}"))


def _plot_worst_drawdowns(ax, daily_equity, dd_periods_df):
    T = _T()
    eq = _prep(daily_equity)
    if eq.empty:
        ax.text(0.5, 0.5, "No equity data", ha="center", va="center",
                transform=ax.transAxes, fontsize=8)
        return
    ax.plot(eq.index, eq.values, color=T["primary"], linewidth=1.0)
    if isinstance(dd_periods_df, pd.DataFrame) and not dd_periods_df.empty \
            and "DD_Amount" in dd_periods_df.columns:
        top5 = dd_periods_df.sort_values("DD_Amount", ascending=False,
                                         na_position="last").head(5)
        for _, row in top5.iterrows():
            s = row.get("Start_Date")
            e = row.get("End_Date")
            if pd.isna(s):
                continue
            s = pd.to_datetime(s)
            e = pd.to_datetime(e) if pd.notna(e) else eq.index.max()
            if getattr(s, "tz", None) is not None:
                s = s.tz_localize(None)
            if getattr(e, "tz", None) is not None:
                e = e.tz_localize(None)
            try:
                ax.axvspan(s, e, color=T["negative"], alpha=0.12)
            except Exception:
                pass
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda v, _: f"${v:,.0f}"))


def _plot_rolling(ax, s: pd.Series, color, zero_line: bool, pct: bool):
    T = _T()
    if not isinstance(s, pd.Series) or s.empty:
        ax.text(0.5, 0.5, "Insufficient history\n(<126 bars)", ha="center",
                va="center", transform=ax.transAxes, fontsize=8,
                color=T["text_muted"])
        return
    s = _prep(s)
    ax.plot(s.index, s.values, color=color, linewidth=1.0)
    if zero_line:
        ax.axhline(0, color=T["negative"], linestyle="--", linewidth=0.7)
    if pct:
        ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1.0, decimals=0))
    ax.fill_between(s.index, s.values, 0, color=color, alpha=0.06)


def _hline(fig, x0, x1, y, color=None, lw=0.8):
    from matplotlib.lines import Line2D
    color = color or _T()["neutral"]
    fig.add_artist(Line2D([x0, x1], [y, y], transform=fig.transFigure,
                          color=color, linewidth=lw))


def _stamp(fig, name, run_date, page_num, total_pages):
    T = _T()
    fig.text(0.5, 0.012, f"{name}   ·   Page {page_num} of {total_pages}",
             ha="center", va="bottom", fontsize=6.5, color=T["text_muted"],
             transform=fig.transFigure)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def generate_tearsheet_v3(report_data: dict, output_path: str) -> str:
    """Render the dense 2-page v3 tearsheet.

    Accepts the same report_data dict as generate_tearsheet_pdf (plus optional
    'trading_days'). Computes the extra institutional metrics via
    metrics_v3.compute_v3_metrics and lays out two A4-landscape pages."""
    print(f"\n--- Generating v3 Tearsheet PDF: {output_path} ---")
    T = _T()
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
    except Exception:
        pass

    trades_df = report_data.get("trades_df", pd.DataFrame())
    initial_equity = report_data.get("initial_equity", 50_000) or 50_000
    daily_equity = report_data.get("daily_equity", pd.Series(dtype=float))
    daily_returns = report_data.get("daily_returns", pd.Series(dtype=float))
    core_metrics = report_data.get("core_metrics", {}) or {}
    max_dd_pct = report_data.get("max_equity_dd_pct", 0.0) or 0.0
    dd_periods_df = report_data.get("dd_periods_df", pd.DataFrame())
    risk_free_rate = report_data.get("risk_free_rate", 0.0) or 0.0
    trading_days = report_data.get("trading_days", 252) or 252
    report_name = report_data.get("name", "Strategy")
    run_date = report_data.get("run_date", datetime.now().strftime("%Y-%m-%d"))
    wfa_split_date = report_data.get("wfa_split_date")

    # Max drawdown in $ from the equity curve
    max_dd_dollars = 0.0
    if isinstance(daily_equity, pd.Series) and not daily_equity.empty:
        _eq = mv3._clean_equity(daily_equity)
        if not _eq.empty:
            max_dd_dollars = float((_eq.cummax() - _eq).max())

    M = mv3.compute_v3_metrics(
        daily_equity, daily_returns, trades_df, core_metrics,
        initial_equity=initial_equity, max_dd_dollars=max_dd_dollars,
        max_dd_pct=max_dd_pct, trading_days=trading_days,
        risk_free_rate=risk_free_rate,
    )

    # Header meta
    start_str = end_str = "N/A"
    dur_years = core_metrics.get("duration_years", 0) or 0
    if isinstance(trades_df, pd.DataFrame) and not trades_df.empty:
        if "Date" in trades_df and trades_df["Date"].notna().any():
            start_str = pd.to_datetime(trades_df["Date"]).min().strftime("%d %b %Y")
        if "Ex. date" in trades_df and trades_df["Ex. date"].notna().any():
            end_str = pd.to_datetime(trades_df["Ex. date"]).max().strftime("%d %b %Y")

    meta = {
        "name": report_name,
        "run_date": run_date,
        "app_version": _app_version(),
        "start_date": start_str,
        "end_date": end_str,
        "total_trades": M.get("total_trades"),
        "duration_years": dur_years,
        "oos_date": wfa_split_date,
        "wfa_approx": (report_data.get("wfa_result") or {}).get("wfa_basis") == "approximation",
    }
    series = {
        "daily_equity": daily_equity,
        "daily_returns": daily_returns,
        "initial_equity": initial_equity,
        "dd_periods_df": dd_periods_df,
        "trading_days": trading_days,
        "risk_free_rate": risk_free_rate,
    }

    with _plotting.themed():
        # Disable $...$ mathtext parsing so paired dollar amounts in one label
        # (e.g. "$2,234 / -$1,959") render literally instead of as math.
        _old_parse_math = plt.rcParams.get("text.parse_math", True)
        plt.rcParams["text.parse_math"] = False
        pages = [
            ("Overview", build_v3_page1(meta, M)),
            ("Charts", build_v3_page2(meta, M, series)),
        ]
        total_pages = len(pages)
        try:
            with PdfPages(output_path) as pdf:
                for n, (title, fig) in enumerate(pages, start=1):
                    if fig is None or not isinstance(fig, plt.Figure):
                        continue
                    try:
                        _stamp(fig, report_name, run_date, n, total_pages)
                        pdf.savefig(fig, facecolor=fig.get_facecolor())
                    except Exception as pe:
                        print(f"WARNING: could not save v3 page '{title}': {pe}")
                    finally:
                        if plt.fignum_exists(fig.number):
                            plt.close(fig)
            print(f"v3 Tearsheet PDF saved: {output_path}  ({total_pages} pages)")
        except Exception as e:
            print(f"FATAL: v3 PDF save failed: {e}")
            traceback.print_exc()
        finally:
            plt.rcParams["text.parse_math"] = _old_parse_math
            plt.close("all")

    return output_path
