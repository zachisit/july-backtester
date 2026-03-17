# helpers/regime.py
"""
VIX-regime heatmap: classify trades by market regime and print a year × bucket P&L table.

Public API
----------
classify_vix_regime(vix_series, date) -> str
build_regime_heatmap(trade_log, vix_df, initial_capital) -> pd.DataFrame | None
print_regime_heatmap(heatmap, strategy_name) -> None
"""

from __future__ import annotations

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VIX_LOW_THRESHOLD  = 15.0
VIX_HIGH_THRESHOLD = 25.0

REGIME_LOW = "Low (<15)"
REGIME_MID = "Mid (15-25)"
REGIME_HIGH = "High (>25)"
REGIME_UNK  = "Unknown"

ALL_REGIMES = [REGIME_LOW, REGIME_MID, REGIME_HIGH]


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def classify_vix_regime(vix_series, date) -> str:
    """Classify a single date into a VIX regime bucket.

    The series is forward-filled before lookup so that weekends / holidays
    inherit the most recent prior closing VIX.

    Parameters
    ----------
    vix_series : pd.Series or None
        VIX close prices with a DatetimeIndex.
    date : date-like
        The date to classify.

    Returns
    -------
    str  — one of REGIME_LOW, REGIME_MID, REGIME_HIGH, or REGIME_UNK.
    """
    if vix_series is None or vix_series.empty:
        return REGIME_UNK

    try:
        ts = pd.Timestamp(date)
        # Normalize: strip timezone from both sides so tz-aware Yahoo Finance
        # data aligns correctly with tz-naive trade log dates.
        if vix_series.index.tz is not None:
            vix_series = vix_series.copy()
            vix_series.index = vix_series.index.tz_localize(None)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        # Add the lookup date to the index (as NaN) so ffill can propagate to it
        if ts not in vix_series.index:
            vix_series = pd.concat([vix_series, pd.Series([float("nan")], index=[ts])])
        filled = vix_series.sort_index().ffill()
        val = filled.get(ts)
        if val is None or pd.isna(val):
            return REGIME_UNK
        val = float(val)
    except Exception:
        return REGIME_UNK

    if val < VIX_LOW_THRESHOLD:
        return REGIME_LOW
    if val <= VIX_HIGH_THRESHOLD:
        return REGIME_MID
    return REGIME_HIGH


def build_regime_heatmap(
    trade_log: list[dict],
    vix_df,
    initial_capital: float,
) -> pd.DataFrame | None:
    """Build a year × VIX-regime P&L matrix from a strategy's trade log.

    Parameters
    ----------
    trade_log       : list of trade dicts — each must contain ``"EntryDate"`` and ``"Profit"``.
    vix_df          : pd.DataFrame with a VIX ``"Close"`` column (or first column as fallback).
    initial_capital : float — used to express P&L as a fraction of starting capital.

    Returns
    -------
    pd.DataFrame (index=year, columns=ALL_REGIMES, values=fractional P&L)
    or ``None`` when inputs are insufficient.
    """
    if not trade_log or vix_df is None or vix_df.empty or initial_capital <= 0:
        return None

    # Resolve VIX close series
    if "Close" in vix_df.columns:
        vix_series = vix_df["Close"].dropna()
    else:
        vix_series = vix_df.iloc[:, 0].dropna()

    rows = []
    for trade in trade_log:
        entry_date_raw = trade.get("EntryDate")
        profit = trade.get("Profit")
        if entry_date_raw is None or profit is None:
            continue
        try:
            entry_ts = pd.Timestamp(entry_date_raw)
        except Exception:
            continue
        regime = classify_vix_regime(vix_series, entry_ts)
        rows.append({"year": entry_ts.year, "regime": regime, "profit": float(profit)})

    if not rows:
        return None

    df = pd.DataFrame(rows)
    heatmap = df.pivot_table(
        values="profit",
        index="year",
        columns="regime",
        aggfunc="sum",
        fill_value=0.0,
    )

    # Divide by initial capital → fractional P&L
    heatmap = heatmap / initial_capital

    # Ensure all three regime columns are present, in canonical order
    for col in ALL_REGIMES:
        if col not in heatmap.columns:
            heatmap[col] = 0.0
    heatmap = heatmap[ALL_REGIMES]

    return heatmap


def print_regime_heatmap(heatmap: pd.DataFrame | None, strategy_name: str) -> None:
    """Print the year × VIX-regime heatmap to stdout.

    Silently returns when ``heatmap`` is None or empty.

    Parameters
    ----------
    heatmap       : output of :func:`build_regime_heatmap`.
    strategy_name : strategy name used in the header line.
    """
    if heatmap is None or heatmap.empty:
        return

    col_w = 14
    sep = "-" * (10 + col_w * len(ALL_REGIMES))

    print(f"\n--- REGIME HEATMAP: {strategy_name} ---")
    header = f"  {'Year':<8}" + "".join(f"{c:>{col_w}}" for c in ALL_REGIMES)
    print(header)
    print(sep)

    for year, row in heatmap.iterrows():
        line = f"  {year:<8}" + "".join(f"{row.get(c, 0.0):>{col_w}.1%}" for c in ALL_REGIMES)
        print(line)

    print(sep)
    totals = heatmap.sum()
    total_line = f"  {'TOTAL':<8}" + "".join(f"{totals.get(c, 0.0):>{col_w}.1%}" for c in ALL_REGIMES)
    print(total_line)
