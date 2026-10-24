# helpers/wfa_rolling.py
"""
Walk-Forward Analysis — Rolling Multi-Fold extension (SECTION 11).

Divides the backtest period into k equal-width Out-of-Sample (OOS) windows.
For fold i, In-Sample (IS) = all trades with ExitDate before that OOS window.

A fold is *scorable* when BOTH its IS and OOS trade counts are
>= min_fold_trades (fold 0 of the default layout has no IS history, so it is
never scored).  At least 2 scorable folds are required to issue a verdict.

Overall verdict:
  "Pass"  — >= 60 % of scorable folds individually pass evaluate_wfa()
  "Fail"  — < 60 % of scorable folds pass
  "N/A"   — fewer than 2 scorable folds

Public API
----------
get_fold_dates(actual_start, actual_end, k, anchored=False)             -> list[tuple[str, str]]
evaluate_rolling_wfa(trade_log, fold_dates, initial_capital,
                     min_fold_trades=5, equity_curve=None,
                     actual_start=None)                                 -> dict
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from helpers.wfa import evaluate_wfa as _evaluate_wfa

_PASS_THRESHOLD = 0.60  # fraction of scorable folds that must individually pass


def get_fold_dates(
    actual_start: str,
    actual_end:   str,
    k:            int,
    anchored:     bool = False,
) -> list[tuple[str, str]]:
    """Return *k* equal-width ``(oos_start, oos_end)`` tuples.

    Default layout tiles the whole period into *k* OOS windows (fold 0 starts at
    *actual_start*, so it has no IS history and is never scored).  With
    ``anchored=True`` the first ``1/(k+1)`` of the period is reserved as the
    initial IS window and the k OOS folds follow it, so every fold has IS history.

    Parameters
    ----------
    actual_start : ISO date of the first available data bar (e.g. ``"2004-01-02"``).
    actual_end   : ISO date of the last available data bar.
    k            : number of folds (must be >= 2).
    anchored     : opt-in anchored layout (see above); default keeps the tiling.

    Returns
    -------
    list of ``(oos_start, oos_end)`` tuples (ISO date strings), ordered chronologically.
    The last fold's ``oos_end`` equals *actual_end* so it absorbs any day remainder.

    Raises
    ------
    ValueError if k < 2.
    """
    if k < 2:
        raise ValueError(f"wfa_folds must be >= 2; got {k}")

    start = date.fromisoformat(actual_start)
    end   = date.fromisoformat(actual_end)
    total_days = (end - start).days
    fold_days  = total_days // (k + 1 if anchored else k)
    offset     = 1 if anchored else 0

    folds = []
    for i in range(k):
        oos_start = start + timedelta(days=(i + offset) * fold_days)
        oos_end   = end if i == k - 1 else start + timedelta(days=(i + 1 + offset) * fold_days)
        folds.append((oos_start.isoformat(), oos_end.isoformat()))
    return folds


def evaluate_rolling_wfa(
    trade_log:       list[dict],
    fold_dates:      list[tuple[str, str]],
    initial_capital: float,
    min_fold_trades: int = 5,
    equity_curve:    "pd.Series | None" = None,
    actual_start:    "str | None" = None,
) -> dict:
    """Evaluate rolling multi-fold WFA on a completed trade log.

    For each ``(oos_start, oos_end)`` fold:

    * IS  = trades with ``ExitDate <  oos_start``
    * OOS = trades with ``oos_start <= ExitDate < oos_end``

    A fold is *scorable* when both ``len(is_trades)`` and ``len(oos_trades)`` are
    ``>= min_fold_trades``.  Other folds (including fold 0 of the default layout,
    which has no IS history) are skipped silently.

    Parameters
    ----------
    trade_log        : list of trade dicts (must contain ``ExitDate`` and ``Profit``).
    fold_dates       : output of :func:`get_fold_dates`.
    initial_capital  : starting equity used to normalise P&L.
    min_fold_trades  : minimum IS and OOS trades to score a fold (default 5).
    equity_curve     : optional ``portfolio_timeline`` Series; when given, each
                       fold's IS/OOS returns are window equity returns.
    actual_start     : IS window start (defaults to the first fold's start).
                       IS window = ``(actual_start, oos_start)``, OOS window =
                       ``(oos_start, oos_end)``.

    Returns
    -------
    dict with key ``wfa_rolling_verdict`` : ``"Pass"`` | ``"Fail"`` | ``"N/A"``
    """
    if not trade_log or not fold_dates:
        return {"wfa_rolling_verdict": "N/A"}

    pass_count   = 0
    scored_count = 0
    # An anchored layout begins its first OOS fold after the initial IS period.
    # Recover that history when callers omit actual_start.
    if actual_start is not None:
        is_start = actual_start
    elif equity_curve is not None and not equity_curve.empty:
        is_start = equity_curve.index.min()
    else:
        is_start = min(pd.Timestamp(t["ExitDate"]).tz_localize(None) for t in trade_log)

    for oos_start, oos_end in fold_dates:
        # Convert fold boundary strings to pd.Timestamp for datetime handling
        oos_start_ts = pd.Timestamp(oos_start)
        if oos_start_ts.tzinfo is not None:
            oos_start_ts = oos_start_ts.tz_localize(None)
        oos_end_ts = pd.Timestamp(oos_end)
        if oos_end_ts.tzinfo is not None:
            oos_end_ts = oos_end_ts.tz_localize(None)
        # Internal boundaries are exclusive; actual_end is the inclusive last
        # data day. Include its daily and intraday exits in the final fold.
        if (oos_start, oos_end) == fold_dates[-1]:
            oos_end_ts += pd.Timedelta(days=1)

        # Convert ExitDate strings to pd.Timestamp for comparison
        is_trades = []
        oos_trades = []
        for t in trade_log:
            exit_ts = pd.Timestamp(t["ExitDate"])
            if exit_ts.tzinfo is not None:
                exit_ts = exit_ts.tz_localize(None)
            if exit_ts < oos_start_ts:
                is_trades.append(t)
            elif oos_start_ts <= exit_ts < oos_end_ts:
                oos_trades.append(t)

        if len(oos_trades) < min_fold_trades or len(is_trades) < min_fold_trades:
            continue  # insufficient IS or OOS data — skip this fold

        fold_result = _evaluate_wfa(
            is_trades, oos_trades, initial_capital,
            equity_curve=equity_curve,
            is_window=(is_start, oos_start),
            oos_window=(oos_start, oos_end_ts),
        )
        if fold_result.get("wfa_verdict") == "N/A":
            continue
        scored_count += 1
        if fold_result.get("wfa_verdict") == "Pass":
            pass_count += 1

    if scored_count < 2:
        return {"wfa_rolling_verdict": "N/A"}

    label   = "Pass" if (pass_count / scored_count) >= _PASS_THRESHOLD else "Fail"
    verdict = f"{label} ({pass_count}/{scored_count})"
    return {"wfa_rolling_verdict": verdict}
