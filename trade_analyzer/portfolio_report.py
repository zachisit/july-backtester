"""Portfolio tearsheet for target-weight (multi-asset, fully funded) runs (issue #487).

``report.py`` dispatches here when an analyzer CSV has a
``<Strategy>.portfolio.json`` marker beside it (written by
:mod:`helpers.target_weight_runner`). The trade-centric analyzer is not used
for these runs: rebalance fills of a basket are not round-trip trades, and
their per-fill "profit" would misstate the strategy. Every return, drawdown
and ratio here is computed from the **portfolio NAV ledger** of the whole
basket (risk products + cash sleeve + unsettled receivables).

Output: ``<output_dir>/<report_name>/<report_name>.pdf`` (4 A4-landscape
pages, house navy/gold identity) and ``.md`` with PNG charts in ``images/``.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

from . import default_config as config  # noqa: E402

MARKER_SUFFIX = ".portfolio.json"
_SERIES_COLORS = ["#1f4e79", "#7e57c2", "#d99a00", "#2e7d32", "#c62828", "#00838f"]
_PRODUCT_COLORS = ["#c62828", "#1f4e79", "#00838f", "#7e57c2", "#6d4c41"]
_CASH_COLOR = "#a5d6a7"
_UNSETTLED_COLOR = "#ffcc80"


def marker_path(csv_path) -> str:
    """Path of the portfolio-mode marker that would sit beside *csv_path*."""
    base, _ = os.path.splitext(str(csv_path))
    return base + MARKER_SUFFIX


def is_portfolio_csv(csv_path) -> bool:
    return os.path.isfile(marker_path(csv_path))


def load_artifacts(csv_path) -> dict:
    """Load the run artifacts a marker points at."""
    with open(marker_path(csv_path), "r", encoding="utf-8") as fh:
        marker = json.load(fh)
    art = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(str(csv_path))),
                                        marker["artifacts"]))
    with open(os.path.join(art, "metrics.json"), "r", encoding="utf-8") as fh:
        summary = json.load(fh)
    read = dict(index_col=0, parse_dates=True)
    return {
        "dir": art,
        "summary": summary,
        "ledger": pd.read_csv(os.path.join(art, "ledger.csv"), **read),
        "daily": pd.read_csv(os.path.join(art, "daily_returns.csv"), **read),
        "signals": pd.read_csv(os.path.join(art, "signals.csv"), **read),
        "fills": pd.read_csv(os.path.join(art, "fills.csv"), parse_dates=["Date", "SettlementDate"]),
        "annual": pd.read_csv(os.path.join(art, "annual_returns.csv"), index_col=0),
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _pct(v, d=2, signed=False):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "N/A"
    return f"{v:+.{d}%}" if signed else f"{v:.{d}%}"


def _num(v, d=2):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "N/A"
    return f"{v:.{d}f}"


def _money(v):
    return "N/A" if v is None else f"${v:,.0f}"


def _band_pp(band) -> str:
    """Band in percentage points, without rounding 2.5 pp to "2%"."""
    return f"{float(band) * 100:g} pp"


def _is_immediate(summary: dict) -> bool:
    return summary.get("settlement") == "immediate"


NON_DEPLOYABLE = ("NON-DEPLOYABLE BENCHMARK: this run reuses sale proceeds at the same open "
                  "(portfolio_settlement=immediate); it is not a cash-account result.")
#: Page-1 flag; short enough to sit beside the NAV-basis line without overlapping it.
NON_DEPLOYABLE_SHORT = "NON-DEPLOYABLE BENCHMARK RUN (immediate proceeds reuse): not a cash-account result"


def _traded_sessions(summary: dict, fills: pd.DataFrame | None) -> int:
    """Sessions that executed at least one rebalance fill (not merely where the rule fired)."""
    act = summary["activity"]
    if "rebalance_sessions_traded" in act:
        return int(act["rebalance_sessions_traded"])
    if fills is None or fills.empty:  # run written before the key existed
        return 0
    return int(fills.loc[fills["Reason"] == "rebalance", "Date"].nunique())


def _series_order(daily: pd.DataFrame) -> list:
    return list(daily.columns)


def _style_axis(ax, title):
    T = config.THEME
    ax.set_title(title, loc="left", fontsize=9.5, color=T["primary"], fontweight="bold")
    ax.grid(alpha=0.35, color=T["grid"])
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(labelsize=7.5)


def _header(fig, title, subtitle):
    from ._pdf_pages import _house_navy_bar
    _house_navy_bar(fig, [0.0, 0.905, 1.0, 0.095], title, title_size=15, subtitle=subtitle)


def _footer(fig, name, page, pages):
    T = config.THEME
    fig.text(0.5, 0.012, f"{name}   ·   {datetime.now():%Y-%m-%d}   ·   Page {page} of {pages}",
             ha="center", va="bottom", fontsize=6.5, color=T["text_muted"])


# ---------------------------------------------------------------------------
# Charts (each returns a Figure so it can go to the PDF and the Markdown)
# ---------------------------------------------------------------------------

def plot_growth(daily: pd.DataFrame, ax=None):
    fig = None
    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 4), dpi=130)
    for i, col in enumerate(_series_order(daily)):
        growth = (1 + daily[col]).cumprod()
        lw = 1.8 if col == "Strategy" else 1.0
        ls = "--" if "settlement" in col else "-"
        ax.plot(growth.index, growth, lw=lw, ls=ls, color=_SERIES_COLORS[i % len(_SERIES_COLORS)],
                label="Strategy portfolio NAV" if col == "Strategy" else col)
    ax.axhline(1.0, color="#9e9e9e", lw=0.6)
    ax.set_ylabel("Growth of $1", fontsize=8)
    ax.legend(fontsize=7, loc="upper left", frameon=False)
    _style_axis(ax, "Portfolio NAV vs benchmarks (growth of $1, same sessions)")
    return fig or ax.figure


def plot_drawdowns(daily: pd.DataFrame, ax=None):
    fig = None
    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 3), dpi=130)
    T = config.THEME
    for i, col in enumerate(_series_order(daily)):
        if "settlement" in col:
            continue
        wealth = (1 + daily[col]).cumprod()
        dd = wealth / wealth.cummax().clip(lower=1) - 1
        if col == "Strategy":
            ax.fill_between(dd.index, dd * 100, 0, color=T["dd_fill"], alpha=0.8)
            ax.plot(dd.index, dd * 100, color=T["negative"], lw=1.0, label="Strategy portfolio")
        else:
            ax.plot(dd.index, dd * 100, lw=0.9, color=_SERIES_COLORS[i % len(_SERIES_COLORS)], label=col)
    ax.set_ylabel("Drawdown (%)", fontsize=8)
    ax.legend(fontsize=7, loc="lower left", frameon=False)
    _style_axis(ax, "Drawdown from running peak (NAV basis)")
    return fig or ax.figure


def plot_holdings(ledger: pd.DataFrame, symbols: list, cash_symbol: str, ax=None):
    fig = None
    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 3), dpi=130)
    layers, labels, colors = [], [], []
    for i, s in enumerate(symbols):
        layers.append(ledger[f"{s}_weight"] * 100)
        labels.append(s)
        colors.append(_PRODUCT_COLORS[i % len(_PRODUCT_COLORS)])
    layers.append(ledger[f"{cash_symbol}_weight"] * 100)
    labels.append(f"{cash_symbol} (cash sleeve)")
    colors.append(_CASH_COLOR)
    layers.append(ledger["unsettled_weight"] * 100)
    labels.append("Unsettled receivables")
    colors.append(_UNSETTLED_COLOR)
    cash_w = ledger["cash"] / ledger["nav"] * 100
    if cash_w.abs().max() > 1e-9:
        layers.append(cash_w)
        labels.append("Settled cash")
        colors.append("#e0e0e0")
    ax.stackplot(ledger.index, *layers, labels=labels, colors=colors, linewidth=0)
    ax.set_ylim(0, 100)
    ax.set_ylabel("% of NAV (close)", fontsize=8)
    ax.legend(fontsize=7, loc="lower right", bbox_to_anchor=(1.0, 1.0), ncol=len(labels), frameon=False)
    _style_axis(ax, "Holdings at each close (no borrowing, no short positions)")
    return fig or ax.figure


def plot_exposure(ledger: pd.DataFrame, band: float, ax=None, signed: bool = True):
    fig = None
    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 3), dpi=130)
    T = config.THEME
    ax.step(ledger.index, ledger["target"] * 100, where="post", color=T["accent"], lw=1.1,
            label="Target (prior close)")
    ax.plot(ledger.index, ledger["exposure_close"] * 100, color=T["primary"], lw=0.8,
            label="Held at close")
    unfilled = ledger.index[ledger["target_unfilled_at_open"].astype(bool)]
    if len(unfilled):
        ax.scatter(unfilled, ledger.loc[unfilled, "target"] * 100, s=6, color=T["negative"], zorder=3,
                   label=f"Target not reached at open (> {_band_pp(band)} band; settling cash)")
    ax.axhline(0, color="#9e9e9e", lw=0.6)
    ax.set_ylabel("Signed exposure (%)" if signed else "Risk weight (%)", fontsize=8)
    ax.legend(fontsize=7, loc="lower right", bbox_to_anchor=(1.0, 1.0), frameon=False, ncol=3)
    _style_axis(ax, "Signed underlying exposure: target vs executed" if signed
                else "Total risk weight: target vs executed")
    return fig or ax.figure


def plot_signals(signals: pd.DataFrame, sessions: pd.DatetimeIndex, symbols: list, ax=None):
    fig = None
    if ax is None:
        fig, ax = plt.subplots(figsize=(10, 3), dpi=130)
    sig = signals.reindex(sessions)
    numeric = [c for c in sig.columns
               if c not in symbols and c != "target_exposure" and pd.api.types.is_numeric_dtype(sig[c])]
    for i, c in enumerate(numeric[:4]):
        ax.plot(sig.index, sig[c], lw=0.8, color=_SERIES_COLORS[i % len(_SERIES_COLORS)], label=c)
    if "state" in sig.columns:
        states = [s for s in pd.unique(sig["state"].dropna())]
        shades = ["#ffcdd2", "#c8e6c9", "#bbdefb", "#fff9c4", "#e1bee7", "#ffe0b2", "#b2dfdb", "#d7ccc8"]
        palette = {s: shades[k % len(shades)] for k, s in enumerate(sorted(states))}
        codes = sig["state"].fillna("n/a")
        runs = (codes != codes.shift()).cumsum()
        idx = sig.index
        for _, seg in codes.groupby(runs):
            pos = idx.get_loc(seg.index[-1])
            end = idx[pos + 1] if pos + 1 < len(idx) else seg.index[-1]
            ax.axvspan(seg.index[0], end, color=palette.get(seg.iloc[0], "#eeeeee"), alpha=0.45, lw=0)
        from matplotlib.patches import Patch
        handles, labels = ax.get_legend_handles_labels()
        handles += [Patch(color=palette[s], alpha=0.6) for s in sorted(states)]
        labels += [f"state: {s}" for s in sorted(states)]
        ax.legend(handles, labels, fontsize=6.5, loc="upper left", frameon=True, ncol=4)
    elif numeric:
        ax.legend(fontsize=7, loc="upper left", frameon=False)
    ax.axhline(0, color="#9e9e9e", lw=0.6)
    _style_axis(ax, "Signal inputs and state at each close (acted on next open)")
    return fig or ax.figure


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def period_table(summary: dict) -> pd.DataFrame:
    rows = []
    cash = summary["cash_symbol"]
    own = f"{cash} (cash sleeve)"
    for period, by_series in summary["periods"].items():
        for name, m in by_series.items():
            # The cash sleeve measured against itself differs only by its one-off
            # entry fee, so a ratio of that to ~zero excess volatility is not a
            # performance figure. metrics.json keeps the raw value.
            sharpe = "—" if name == own else _num(m.get("sharpe_cash_reference"), 3)
            rows.append({"Period": period, "Series": name,
                         "Start": m.get("start"), "End": m.get("end"),
                         "Total return": _pct(m.get("total_return")), "CAGR": _pct(m.get("cagr")),
                         "Max DD": _pct(m.get("max_drawdown")), "Volatility": _pct(m.get("volatility")),
                         f"Sharpe vs {cash}": sharpe,
                         "Sharpe rf=2%": _num(m.get("sharpe_rf2"), 3)})
    return pd.DataFrame(rows)


def annual_table(annual: pd.DataFrame) -> pd.DataFrame:
    out = annual.copy()
    out.index = out.index.astype(str)
    out.columns = [c.replace(" settlement)", ")") for c in out.columns]
    return out.apply(lambda col: col.map(lambda v: _pct(v, 1, signed=True)))


def cost_table(summary: dict) -> pd.DataFrame:
    costs = summary["costs"]
    rows = []
    for s, c in costs["by_symbol"].items():
        rows.append({"Symbol": s, "Cost (bps)": _num(summary["cost_bps"].get(s, 0.0), 1),
                     "Traded notional": _money(costs["traded_notional_by_symbol"].get(s, 0.0)),
                     "Cost paid": _money(c)})
    rows.append({"Symbol": "Total", "Cost (bps)": "", "Traded notional":
                 _money(sum(costs["traded_notional_by_symbol"].values())),
                 "Cost paid": _money(costs["total"])})
    return pd.DataFrame(rows)


def recent_fills(fills: pd.DataFrame, n: int = 12) -> pd.DataFrame:
    if fills.empty:
        return fills
    f = fills[fills["Reason"] == "rebalance"].tail(n).copy()
    return pd.DataFrame({"Date": f["Date"].dt.strftime("%Y-%m-%d"), "Symbol": f["Symbol"],
                         "Side": f["Side"], "Notional": f["Notional"].map(_money),
                         "Price": f["Price"].map(lambda v: f"{v:,.2f}"),
                         "Cost": f["Cost"].map(lambda v: f"${v:,.2f}"),
                         "Settles": f["SettlementDate"].dt.strftime("%Y-%m-%d")})


def activity_lines(summary: dict, fills: pd.DataFrame | None = None) -> list:
    act, cash = summary["activity"], summary["cash_symbol"]
    traded = _traded_sessions(summary, fills)
    return [
        f"Rebalance rule fired on {act['rebalance_sessions']} sessions; {traded} executed rebalance fills "
        f"(the rest had nothing executable, e.g. the first session or proceeds still unsettled)   ·   "
        f"fills: {act['fills']} (rebalance {act['rebalance_fills']}, the rest park settled cash in {cash})   ·   "
        f"sessions where the target was not reached at the open: {act['unfilled_target_days']}",
        "Signal state (sessions): " + ", ".join(f"{k} {v}" for k, v in act["signal_state_sessions"].items()),
    ]


def notes(summary: dict) -> list:
    v = summary["validation"]
    cash = summary["cash_symbol"]
    products = ", ".join(summary["symbols"])
    bench = summary.get("benchmark")
    basis = "signed exposure" if summary.get("exposure") is not None else "each risk product's weight"
    if _is_immediate(summary):
        first = NON_DEPLOYABLE + " The settled-cash path is the comparison series."
        settle = (f"Settlement: immediate. Sale proceeds are reused at the same open and no receivables are "
                  f"carried. The settled-cash comparison uses rules {summary['settlement_rules']}. "
                  f"Calendar: {v['settlement_calendar']}.")
    else:
        first = "Immediate proceeds reuse is a non-deployable benchmark for the settled-cash account."
        settle = (f"Settlement: {summary['settlement']} (rules {summary['settlement_rules']}). Sale proceeds are "
                  f"receivables until settled; only settled cash buys. Calendar: {v['settlement_calendar']}.")
    costs = f"Costs {summary['cost_bps']} bps per traded notional, including the initial {cash} purchase."
    if bench:
        costs += f" Benchmark {bench}: buy at first open with {summary['benchmark_cost_bps']:g} bps, then hold."
    else:
        costs += " No buy-and-hold benchmark is configured."
    lines = [
        first,
        f"Returns are the NAV of the whole funded basket ({products} + {cash} cash sleeve + unsettled "
        f"receivables). No single ticker's return is the strategy's return; fills are rebalances, not "
        f"round-trip trades.",
        f"Signals use completed sessions only: target decided at close t-1, executed at open t. Rebalance "
        f"band {_band_pp(summary['band'])} on {basis}; held products are exited when their target is zero.",
        settle,
        f"No borrowing or share shorting; minimum cash {v['min_cash']:.6g}, minimum shares {v['min_shares']:.6g}, "
        f"minimum receivable {v['min_unsettled']:.6g}; self-financing checked every session.",
        costs,
        f"Distributions: {v['distribution_treatment']}. No cash interest is added beyond the {cash} price.",
        "Not evaluated: " + ", ".join(summary.get("not_evaluated", [])) + ". Historical results only.",
    ]
    return lines


def _draw_table(ax, df: pd.DataFrame, title: str, font=6.8, col_widths=None):
    """Render *df* as a table filling *ax* exactly (no overflow into neighbours)."""
    T = config.THEME
    ax.axis("off")
    ax.set_title(title, loc="left", fontsize=9.5, color=T["primary"], fontweight="bold")
    if df.empty:
        ax.text(0, 0.5, "None", fontsize=8)
        return
    tbl = ax.table(cellText=df.astype(str).values, colLabels=list(df.columns),
                   cellLoc="center", colWidths=col_widths, bbox=[0, 0, 1, 1])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(font)
    for (r, _c), cell in tbl.get_celld().items():
        cell.set_edgecolor(T["grid"])
        if r == 0:
            cell.set_facecolor(T["primary"])
            cell.set_text_props(color="white", fontweight="bold")
        elif r % 2 == 0:
            cell.set_facecolor("#f7f9fc")


def _text_block(fig, lines, x, y, width_chars=175, size=7.0, step=0.022):
    import textwrap
    for line in lines:
        wrapped = textwrap.wrap(line, width_chars) or [""]
        for k, part in enumerate(wrapped):
            fig.text(x, y, ("• " if k == 0 else "   ") + part, fontsize=size, va="top",
                     color=config.THEME["text"])
            y -= step
        y -= step * 0.3
    return y


def kpi_tiles(summary: dict, fills: pd.DataFrame | None = None) -> list:
    """``(label, value, sub-label, positive)`` for the headline row."""
    full = summary["periods"]["Full period"]
    s = full["Strategy"]
    cash = summary["cash_symbol"]
    bench = summary.get("benchmark")
    b = full.get(bench, {}) if bench else {}
    c = full.get(f"{cash} (cash sleeve)", {})
    cagr_sub = " · ".join(([f"{bench} {_pct(b.get('cagr'))}"] if bench else [])
                          + [f"{cash} {_pct(c.get('cagr'))}"])
    dd_sub = (f"{bench} {_pct(b.get('max_drawdown'))}" if bench
              else f"{cash} {_pct(c.get('max_drawdown'))}")
    return [
        ("Total return", _pct(s["total_return"]), f"{s['start']} → {s['end']}", s["total_return"] > 0),
        ("CAGR", _pct(s["cagr"]), cagr_sub, None),
        ("Max drawdown", _pct(s["max_drawdown"]), dd_sub, False),
        (f"Sharpe vs {cash}", _num(s.get("sharpe_cash_reference"), 3), f"rf=2%: {_num(s.get('sharpe_rf2'), 3)}", None),
        ("Volatility", _pct(s["volatility"]), f"{s['observations']} sessions", None),
        ("Costs paid", _money(summary["costs"]["total"]),
         f"{_traded_sessions(summary, fills)} sessions rebalanced", None),
    ]


def _kpis(fig, summary, fills=None, rect_y=0.80, h=0.085):
    from ._pdf_v3 import _draw_kpi_tile
    tiles = kpi_tiles(summary, fills)
    w = 1.0 / len(tiles)
    for i, (label, value, sub, pos) in enumerate(tiles):
        ax = fig.add_axes([0.02 + i * w * 0.98, rect_y, w * 0.96, h])
        _draw_kpi_tile(ax, label, value, sub, positive=pos)


def build_pages(art: dict, name: str) -> list:
    summary, ledger, daily = art["summary"], art["ledger"], art["daily"]
    symbols, cash = summary["symbols"], summary["cash_symbol"]
    subtitle = (f"TARGET-WEIGHT PORTFOLIO · {', '.join(symbols)} + {cash} · "
                f"{summary['settlement']} · {ledger.index[0]:%Y-%m-%d} → {ledger.index[-1]:%Y-%m-%d}")
    pages = []

    fig = plt.figure(figsize=config.FIG_FULL)
    _header(fig, summary["strategy"], subtitle)
    fig.text(0.02, 0.89, "All figures are portfolio-NAV based: the strategy is the funded basket, "
             "not any single ticker.", fontsize=7.5, color=config.THEME["text_muted"], va="top")
    if _is_immediate(summary):
        fig.text(0.98, 0.89, NON_DEPLOYABLE_SHORT, fontsize=7.5, color=config.THEME["negative"],
                 fontweight="bold", va="top", ha="right")
    _kpis(fig, summary, art["fills"])
    plot_growth(daily, fig.add_axes([0.06, 0.42, 0.90, 0.34]))
    plot_drawdowns(daily, fig.add_axes([0.06, 0.06, 0.90, 0.29]))
    pages.append(fig)

    fig = plt.figure(figsize=config.FIG_FULL)
    _header(fig, "Holdings, exposure & signal activity", subtitle)
    plot_holdings(ledger, symbols, cash, fig.add_axes([0.06, 0.63, 0.90, 0.24]))
    plot_exposure(ledger, summary["band"], fig.add_axes([0.06, 0.35, 0.90, 0.22]),
                  signed=summary.get("exposure") is not None)
    plot_signals(art["signals"], ledger.index, symbols, fig.add_axes([0.06, 0.06, 0.90, 0.23]))
    pages.append(fig)

    fig = plt.figure(figsize=config.FIG_FULL)
    _header(fig, "Performance by period, calendar years & costs", subtitle)
    pt = period_table(summary)
    widths = [0.09, 0.19, 0.08, 0.08, 0.09, 0.07, 0.08, 0.08, 0.09, 0.09]
    _draw_table(fig.add_axes([0.02, 0.40, 0.96, 0.46]), pt,
                "Performance by period (identical sessions, NAV basis)", font=6.6, col_widths=widths)
    annual = annual_table(art["annual"]).reset_index()
    annual = annual.rename(columns={annual.columns[0]: "Year"})
    _draw_table(fig.add_axes([0.02, 0.05, 0.56, 0.28]), annual, "Calendar-year returns", font=6.6)
    _draw_table(fig.add_axes([0.62, 0.17, 0.36, 0.16]), cost_table(summary),
                "Transaction costs (per traded notional)", font=6.6)
    pages.append(fig)

    fig = plt.figure(figsize=config.FIG_FULL)
    _header(fig, "Rebalance activity, validation & assumptions", subtitle)
    fig.text(0.02, 0.875, "ACTIVITY", fontsize=9.5, color=config.THEME["primary"], fontweight="bold")
    y = _text_block(fig, activity_lines(summary, art["fills"]), 0.02, 0.85)
    fills_ax = fig.add_axes([0.02, y - 0.36, 0.96, 0.33])
    _draw_table(fills_ax, recent_fills(art["fills"]), "Most recent rebalance fills", font=6.6)
    y = y - 0.42
    fig.text(0.02, y, "ASSUMPTIONS, VALIDATION & LIMITATIONS", fontsize=9.5,
             color=config.THEME["primary"], fontweight="bold")
    _text_block(fig, notes(summary), 0.02, y - 0.03)
    pages.append(fig)

    for i, f in enumerate(pages, start=1):
        _footer(f, name, i, len(pages))
    return pages


def _md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_None_\n"
    cols = [str(c) for c in df.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for row in df.astype(str).values:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines) + "\n"


def write_markdown(art: dict, md_path: str, image_dir: str) -> None:
    summary, ledger, daily = art["summary"], art["ledger"], art["daily"]
    os.makedirs(image_dir, exist_ok=True)
    rel = os.path.basename(image_dir)
    charts = [
        ("portfolio_nav.png", "Portfolio NAV vs benchmarks", plot_growth(daily)),
        ("drawdown.png", "Drawdown", plot_drawdowns(daily)),
        ("holdings.png", "Holdings", plot_holdings(ledger, summary["symbols"], summary["cash_symbol"])),
        ("exposure.png", "Signed exposure",
         plot_exposure(ledger, summary["band"], signed=summary.get("exposure") is not None)),
        ("signals.png", "Signal activity", plot_signals(art["signals"], ledger.index, summary["symbols"])),
    ]
    for fname, _t, fig in charts:
        fig.tight_layout()
        fig.savefig(os.path.join(image_dir, fname), dpi=110)
        plt.close(fig)
    full = summary["periods"]["Full period"]["Strategy"]
    parts = [
        f"# {summary['strategy']} — target-weight portfolio tearsheet\n",
        f"Run `{summary.get('run_id')}` · portfolio `{summary['portfolio']}` · "
        f"{full['start']} → {full['end']} ({full['observations']} sessions) · settlement "
        f"`{summary['settlement']}` · initial capital {_money(summary['initial_capital'])} → final NAV "
        f"{_money(summary['final_nav'])}\n",
        "> All figures are portfolio-NAV based: the strategy is the funded basket "
        f"({', '.join(summary['symbols'])} + {summary['cash_symbol']}), not any single ticker.\n",
        *([f"> **{NON_DEPLOYABLE}**\n"] if _is_immediate(summary) else []),
        f"{summary.get('description', '')}\n",
        "## Performance by period\n", _md_table(period_table(summary)),
        f"![Portfolio NAV]({rel}/portfolio_nav.png)\n", f"![Drawdown]({rel}/drawdown.png)\n",
        "## Holdings, exposure and signal activity\n",
        f"![Holdings]({rel}/holdings.png)\n", f"![Exposure]({rel}/exposure.png)\n",
        f"![Signals]({rel}/signals.png)\n",
        "## Calendar-year returns\n", _md_table(annual_table(art["annual"]).reset_index()),
        "## Transaction costs\n", _md_table(cost_table(summary)),
        "## Activity\n",
        f"- Rebalance rule fired on {summary['activity']['rebalance_sessions']} sessions; "
        f"{_traded_sessions(summary, art['fills'])} executed rebalance fills\n"
        f"- Fills: {summary['activity']['fills']} (rebalance {summary['activity']['rebalance_fills']})\n"
        f"- Unfilled target days: {summary['activity']['unfilled_target_days']}\n"
        f"- Signal-state sessions: {summary['activity']['signal_state_sessions']}\n",
        "### Most recent rebalance fills\n", _md_table(recent_fills(art["fills"])),
        "## Assumptions and limitations\n", "".join(f"- {line}\n" for line in notes(summary)),
    ]
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))


def generate_portfolio_report(csv_path, output_dir: str, report_name: str) -> dict:
    """Write the PDF and Markdown tearsheet for a target-weight run."""
    art = load_artifacts(csv_path)
    out_dir = os.path.join(output_dir, report_name)
    os.makedirs(out_dir, exist_ok=True)
    pdf_path = os.path.join(out_dir, f"{report_name}.pdf")
    md_path = os.path.join(out_dir, f"{report_name}.md")
    image_dir = os.path.join(out_dir, getattr(config, "MARKDOWN_IMAGE_SUBDIR", "images"))
    pages = build_pages(art, report_name)
    with PdfPages(pdf_path) as pdf:
        for fig in pages:
            pdf.savefig(fig)
            plt.close(fig)
        info = pdf.infodict()
        info["Title"] = f"{art['summary']['strategy']} — target-weight portfolio tearsheet"
        info["Subject"] = "July Backtester portfolio NAV report (issue #487)"
    write_markdown(art, md_path, image_dir)
    print(f"Portfolio tearsheet: {pdf_path}")
    print(f"Portfolio markdown : {md_path}")
    return {"pdf": pdf_path, "md": md_path, "pages": len(pages)}
