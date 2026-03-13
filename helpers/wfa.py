# helpers/wfa.py
"""
Walk-Forward Analysis (WFA) helpers.

Splits a strategy's completed trade log into an In-Sample (IS) window and an
Out-of-Sample (OOS) window based on a chronological date split, then evaluates
whether the OOS performance supports or undermines the IS results.

Public API
----------
get_split_date(actual_start, actual_end, ratio)       -> str
split_trades(trade_log, split_date)                   -> (is_trades, oos_trades)
evaluate_wfa(is_trades, oos_trades, initial_capital)  -> dict
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

# Minimum number of OOS trades required to issue a verdict.
# Fewer than this → "N/A" (insufficient data to draw a conclusion).
_MIN_OOS_TRADES = 5


def get_split_date(actual_start: str, actual_end: str, ratio: float) -> str:
    """Return the ISO date string that marks the IS/OOS boundary.

    Parameters
    ----------
    actual_start : str
        ISO date of the first available data bar (e.g. ``"2004-01-02"``).
    actual_end   : str
        ISO date of the last available data bar.
    ratio        : float
        Fraction of the total period allocated to In-Sample (e.g. ``0.80``).

    Returns
    -------
    str
        ISO date string of the first OOS day.

    Examples
    --------
    >>> get_split_date("2004-01-01", "2024-01-01", 0.80)
    '2020-01-01'
    """
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

    Parameters
    ----------
    trade_log   : list[dict]
        List of trade dicts produced by the simulation engine.
        Each dict must have an ``"ExitDate"`` key (ISO date string).
    split_date  : str
        ISO date string of the IS/OOS boundary (inclusive start of OOS).

    Returns
    -------
    (is_trades, oos_trades) : tuple[list[dict], list[dict]]
    """
    is_trades  = [t for t in trade_log if t["ExitDate"] <  split_date]
    oos_trades = [t for t in trade_log if t["ExitDate"] >= split_date]
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
    """
    if not trades:
        return None
    dates = sorted(t["ExitDate"] for t in trades)
    start = date.fromisoformat(dates[0])
    end   = date.fromisoformat(dates[-1])
    days  = (end - start).days
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
