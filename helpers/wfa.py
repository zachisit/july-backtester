# helpers/wfa.py
"""
Walk-Forward Analysis (WFA) helpers.

Splits a strategy's completed trade log into an In-Sample (IS) window and an
Out-of-Sample (OOS) window based on a chronological date split, then evaluates
whether the OOS performance supports or undermines the IS results.

For intraday backtests (hourly, minute timeframes), the split is calculated based
on bar count to ensure accurate IS/OOS ratios (e.g., 80/20 by bar count, not
calendar days which include weekends/holidays).

Public API
----------
get_split_date(actual_start, actual_end, ratio, df=None, config=None) -> str
split_trades(trade_log, split_date)                   -> (is_trades, oos_trades)
evaluate_wfa(is_trades, oos_trades, initial_capital)  -> dict
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
import pandas as pd

# Minimum number of OOS trades required to issue a verdict.
# Fewer than this → "N/A" (insufficient data to draw a conclusion).
_MIN_OOS_TRADES = 5


def get_split_date(
    actual_start: str,
    actual_end: str,
    ratio: float,
    df: Optional[pd.DataFrame] = None,
    config: Optional[dict] = None,
) -> str:
    """Return the ISO date string that marks the IS/OOS boundary.

    For intraday timeframes (H, MIN), splits by bar count when df and config are
    provided. This ensures accurate IS/OOS ratios (e.g., 80% of bars, not 80% of
    calendar days which include weekends/holidays).

    For daily+ timeframes, uses calendar day splitting (existing behavior).

    Parameters
    ----------
    actual_start : str
        ISO date of the first available data bar (e.g. ``"2004-01-02"``).
    actual_end   : str
        ISO date of the last available data bar.
    ratio        : float
        Fraction of the total period allocated to In-Sample (e.g. ``0.80``).
    df : pd.DataFrame, optional
        Dataframe with DatetimeIndex containing all bars. Required for intraday
        bar-count splitting. If None, falls back to calendar day splitting.
    config : dict, optional
        CONFIG dict containing timeframe settings. Required for intraday detection.
        If None, falls back to calendar day splitting.

    Returns
    -------
    str
        ISO date string of the first OOS day (or datetime string for intraday).

    Examples
    --------
    >>> # Daily: calendar day split
    >>> get_split_date("2004-01-01", "2024-01-01", 0.80)
    '2020-01-01'

    >>> # Intraday: bar-count split (requires df and config)
    >>> get_split_date("2020-01-01", "2020-12-31", 0.80, df=hourly_df, config={"timeframe": "H"})
    '2020-10-15'  # 80% of bars, not 80% of calendar days
    """
    # Intraday bar-count split (Phase 2)
    if df is not None and config is not None:
        timeframe = config.get("timeframe", "D").upper()
        if timeframe in ("H", "MIN"):
            # Split by bar count for accurate intraday IS/OOS ratios
            split_idx = int(len(df) * ratio)
            # Clamp to valid range (edge case: ratio=1.0 would cause IndexError)
            split_idx = min(split_idx, len(df) - 1)
            split_timestamp = df.index[split_idx]
            # Return ISO date string (YYYY-MM-DD) for consistency with trade log ExitDate
            return split_timestamp.strftime("%Y-%m-%d")

    # Daily+ calendar day split (existing logic)
    start = date.fromisoformat(actual_start)
    end   = date.fromisoformat(actual_end)
    total_days = (end - start).days
    split_days = int(total_days * ratio)
    return (start + timedelta(days=split_days)).isoformat()


def split_trades(
    trade_log: list[dict],
    split_date: str,
) -> tuple[list[dict], list[dict]]:
    """Partition *trade_log* into IS and OOS buckets by exit date.

    A trade belongs to OOS if its ``ExitDate`` is on or after *split_date*;
    all earlier exits are IS.

    Handles both date-only strings (``"2024-01-15"``) and datetime strings
    (``"2024-01-15T10:30:00"``) by converting to pd.Timestamp for comparison.

    Parameters
    ----------
    trade_log   : list[dict]
        List of trade dicts produced by the simulation engine.
        Each dict must have an ``"ExitDate"`` key (ISO date/datetime string).
    split_date  : str
        ISO date string of the IS/OOS boundary (inclusive start of OOS).

    Returns
    -------
    (is_trades, oos_trades) : tuple[list[dict], list[dict]]
    """
    # Convert split_date string to pd.Timestamp for proper comparison
    split_ts = pd.Timestamp(split_date)
    if split_ts.tzinfo is not None:
        split_ts = split_ts.tz_localize(None)

    is_trades = []
    oos_trades = []

    for t in trade_log:
        # Convert ExitDate string to pd.Timestamp
        exit_ts = pd.Timestamp(t["ExitDate"])
        if exit_ts.tzinfo is not None:
            exit_ts = exit_ts.tz_localize(None)

        if exit_ts < split_ts:
            is_trades.append(t)
        else:
            oos_trades.append(t)

    return is_trades, oos_trades


# ---------------------------------------------------------------------------
# Internal metric helpers
# ---------------------------------------------------------------------------

def _total_pnl_pct(trades: list[dict], initial_capital: float) -> Optional[float]:
    """Sum of Profit / initial_capital (fractional, not percent)."""
    if not trades:
        return None
    return sum(t["Profit"] for t in trades) / initial_capital


def _annualised_return(trades: list[dict], initial_capital: float) -> Optional[float]:
    """Compound annualised return (CAGR) over the calendar span of the trade bucket.

    Uses the earliest and latest ``ExitDate`` in the bucket as the window
    boundaries.  Returns ``None`` when fewer than 2 distinct days exist or
    when the strategy went bust (total equity <= 0).

    Handles both date-only strings (``"2024-01-15"``) and datetime strings
    (``"2024-01-15T10:30:00"``) by converting to pd.Timestamp.
    """
    if not trades:
        return None
    # Convert ExitDate strings to pd.Timestamp for datetime handling
    exit_timestamps = sorted(pd.Timestamp(t["ExitDate"]) for t in trades)
    start_ts = exit_timestamps[0]
    end_ts = exit_timestamps[-1]
    days = (end_ts - start_ts).days
    if days < 1:
        return None
    years          = days / 365.25
    total_pnl_frac = sum(t["Profit"] for t in trades) / initial_capital
    if (1 + total_pnl_frac) <= 0:
        return None  # strategy went bust — CAGR undefined
    return (1 + total_pnl_frac) ** (1 / years) - 1


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def evaluate_wfa(
    is_trades:       list[dict],
    oos_trades:      list[dict],
    initial_capital: float,
) -> dict:
    """Evaluate IS vs OOS performance and return a WFA metrics dict.

    Flagging rules
    --------------
    "Likely Overfitted" is returned when *either* condition is met:

    1. **Sign flip**: IS total P&L is positive but OOS total P&L is negative.
    2. **Severe degradation**: OOS annualised return degrades by more than 75 %
       relative to IS annualised return (only checked when IS annualised > 0).

    "N/A" is returned when OOS has fewer than ``_MIN_OOS_TRADES`` trades
    (insufficient data to judge).

    Parameters
    ----------
    is_trades        : list of trade dicts in the In-Sample window
    oos_trades       : list of trade dicts in the Out-of-Sample window
    initial_capital  : float  starting equity of the simulation

    Returns
    -------
    dict with keys:
        ``oos_pnl_pct``  : float | None  (fractional, e.g. 0.05 = 5 %)
        ``wfa_verdict``  : str           ("Pass" | "Likely Overfitted" | "N/A")
    """
    oos_pnl_pct = _total_pnl_pct(oos_trades, initial_capital)

    # Not enough OOS trades to issue a meaningful verdict
    if not oos_trades or len(oos_trades) < _MIN_OOS_TRADES:
        return {"oos_pnl_pct": oos_pnl_pct, "wfa_verdict": "N/A"}

    is_pnl_pct = _total_pnl_pct(is_trades, initial_capital)

    # --- Condition 1: sign flip ---
    if is_pnl_pct is not None and oos_pnl_pct is not None:
        if is_pnl_pct > 0 and oos_pnl_pct < 0:
            return {"oos_pnl_pct": oos_pnl_pct, "wfa_verdict": "Likely Overfitted"}

    # --- Condition 2: severe annualised degradation ---
    is_ann  = _annualised_return(is_trades,  initial_capital)
    oos_ann = _annualised_return(oos_trades, initial_capital)
    if is_ann is not None and oos_ann is not None and is_ann > 0:
        degradation = (is_ann - oos_ann) / abs(is_ann)
        if degradation > 0.75:
            return {"oos_pnl_pct": oos_pnl_pct, "wfa_verdict": "Likely Overfitted"}

    return {"oos_pnl_pct": oos_pnl_pct, "wfa_verdict": "Pass"}
