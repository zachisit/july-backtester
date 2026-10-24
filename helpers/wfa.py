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
evaluate_wfa(is_trades, oos_trades, initial_capital,
             equity_curve=None, is_window=None, oos_window=None) -> dict
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

_EPS = pd.Timedelta(microseconds=1)


def _naive_ts(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def _naive_curve(equity_curve: pd.Series) -> pd.Series:
    curve = equity_curve.dropna().sort_index()
    if getattr(curve.index, "tz", None) is not None:
        curve = curve.copy()
        curve.index = curve.index.tz_localize(None)
    return curve


def _curve_value_before(curve: pd.Series, ts: pd.Timestamp) -> Optional[float]:
    """Equity at the close of the last bar strictly before *ts* (None if none)."""
    if curve.empty:
        return None
    val = curve.asof(ts - _EPS)
    return None if pd.isna(val) else float(val)


def _window_years(window) -> Optional[float]:
    days = (_naive_ts(window[1]) - _naive_ts(window[0])).days
    return days / 365.25 if days >= 1 else None


def _total_pnl_pct(
    trades:          list[dict],
    initial_capital: float,
    base:            Optional[float] = None,
    equity_curve:    Optional[pd.Series] = None,
    window:          Optional[tuple] = None,
) -> Optional[float]:
    """Fractional return of one WFA bucket.

    * ``equity_curve`` + ``window`` given: ``E(window_end) / E(window_start) - 1``
      (boundaries are the closes of the bar before each date; the final window
      ending at/after the last curve bar uses the last value; a start before the
      curve begins uses *initial_capital*).
    * otherwise: ``sum(Profit) / base`` where *base* defaults to
      *initial_capital*; callers pass the realised equity at window start.
    """
    if not trades:
        return None
    if equity_curve is not None and window is not None:
        curve = _naive_curve(equity_curve)
        if not curve.empty:
            start_ts, end_ts = _naive_ts(window[0]), _naive_ts(window[1])
            e0 = _curve_value_before(curve, start_ts)
            if e0 is None:
                e0 = initial_capital
            e1 = (float(curve.iloc[-1]) if end_ts >= curve.index[-1]
                  else _curve_value_before(curve, end_ts))
            if e1 is not None and e0 > 0:
                return e1 / e0 - 1
    denom = initial_capital if base is None else base
    if denom <= 0:
        return None
    return sum(t["Profit"] for t in trades) / denom


def _annualised_return(
    trades:          list[dict],
    initial_capital: float,
    base:            Optional[float] = None,
    equity_curve:    Optional[pd.Series] = None,
    window:          Optional[tuple] = None,
) -> Optional[float]:
    """Compound annualised return (CAGR) of one WFA bucket.

    The return comes from :func:`_total_pnl_pct`.  With a *window* the years are
    the window length; without one (legacy callers) they are the calendar span
    between the first and last ``ExitDate`` in the bucket.  Returns ``None``
    when the period is under 1 day or the strategy went bust (CAGR undefined).
    """
    if not trades:
        return None
    if window is not None:
        years = _window_years(window)
    else:
        ts = sorted(pd.Timestamp(t["ExitDate"]) for t in trades)
        days = (ts[-1] - ts[0]).days
        years = days / 365.25 if days >= 1 else None
    if years is None:
        return None
    total_pnl_frac = _total_pnl_pct(trades, initial_capital, base, equity_curve, window)
    if total_pnl_frac is None or (1 + total_pnl_frac) <= 0:
        return None  # strategy went bust — CAGR undefined
    return (1 + total_pnl_frac) ** (1 / years) - 1


# ---------------------------------------------------------------------------
# Main evaluation function
# ---------------------------------------------------------------------------

def evaluate_wfa(
    is_trades:       list[dict],
    oos_trades:      list[dict],
    initial_capital: float,
    equity_curve:    Optional[pd.Series] = None,
    is_window:       Optional[tuple] = None,
    oos_window:      Optional[tuple] = None,
) -> dict:
    """Evaluate IS vs OOS performance and return a WFA metrics dict.

    Both buckets are measured on the same basis -- return on the equity the
    account actually held at the start of each window -- so compounding growth
    does not inflate OOS relative to IS:

    * With ``equity_curve`` (the ``portfolio_timeline`` Series) and a window,
      return = ``E(end) / E(start) - 1``.
    * Without a curve (e.g. the PDF analyzer working from a CSV), each bucket's
      profit is divided by the realised equity at its start:
      ``initial_capital + sum(Profit of the IS trades)`` for OOS, and
      ``initial_capital`` for IS.
    * With ``is_window`` / ``oos_window`` (``(start, end)`` date-likes) the
      annualisation period is the window length; without, it falls back to the
      calendar span of the bucket's exit dates (legacy behaviour).

    Flagging rules
    --------------
    "Likely Overfitted" is returned when *either* condition is met:

    1. **Sign flip**: IS return is positive but OOS return is negative.
    2. **Severe degradation**: OOS annualised return degrades by more than 75 %
       relative to IS annualised return (only checked when IS annualised > 0).

    "N/A" is returned when either side has fewer than ``_MIN_OOS_TRADES``
    trades: a verdict needs a real in-sample history to compare against (an
    empty IS would otherwise skip both rules and auto-pass).

    Returns
    -------
    dict with keys:
        ``oos_pnl_pct``  : float | None  OOS window equity return (0.05 = 5 %)
        ``wfa_verdict``  : str           ("Pass" | "Likely Overfitted" | "N/A")
    """
    is_base  = initial_capital
    oos_base = initial_capital + sum(t["Profit"] for t in is_trades)

    oos_pnl_pct = _total_pnl_pct(oos_trades, initial_capital, oos_base, equity_curve, oos_window)

    # Not enough OOS or IS trades to issue a meaningful verdict
    if len(oos_trades) < _MIN_OOS_TRADES or len(is_trades) < _MIN_OOS_TRADES:
        return {"oos_pnl_pct": oos_pnl_pct, "wfa_verdict": "N/A"}

    is_pnl_pct = _total_pnl_pct(is_trades, initial_capital, is_base, equity_curve, is_window)

    # --- Condition 1: sign flip ---
    if is_pnl_pct is not None and oos_pnl_pct is not None:
        if is_pnl_pct > 0 and oos_pnl_pct < 0:
            return {"oos_pnl_pct": oos_pnl_pct, "wfa_verdict": "Likely Overfitted"}

    # --- Condition 2: severe annualised degradation ---
    is_ann  = _annualised_return(is_trades,  initial_capital, is_base,  equity_curve, is_window)
    oos_ann = _annualised_return(oos_trades, initial_capital, oos_base, equity_curve, oos_window)
    if is_ann is not None and oos_ann is not None and is_ann > 0:
        degradation = (is_ann - oos_ann) / abs(is_ann)
        if degradation > 0.75:
            return {"oos_pnl_pct": oos_pnl_pct, "wfa_verdict": "Likely Overfitted"}

    return {"oos_pnl_pct": oos_pnl_pct, "wfa_verdict": "Pass"}
