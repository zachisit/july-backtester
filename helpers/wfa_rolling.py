# helpers/wfa_rolling.py
"""
Walk-Forward Analysis — Rolling Multi-Fold extension (SECTION 11).

Divides the backtest period into k equal-width Out-of-Sample (OOS) windows.
For fold i, In-Sample (IS) = all trades with ExitDate before that OOS window.

A fold is *scorable* when its OOS trade count >= min_fold_trades.
At least 2 scorable folds are required to issue a verdict.

Overall verdict:
  "Pass"  — >= 60 % of scorable folds individually pass evaluate_wfa()
  "Fail"  — < 60 % of scorable folds pass
  "N/A"   — fewer than 2 scorable folds

Public API
----------
get_fold_dates(actual_start, actual_end, k)                             -> list[tuple[str, str]]
evaluate_rolling_wfa(trade_log, fold_dates, initial_capital,
                     min_fold_trades=5)                                 -> dict
"""

from __future__ import annotations

from datetime import date, timedelta

from helpers.wfa import evaluate_wfa as _evaluate_wfa

_PASS_THRESHOLD = 0.60  # fraction of scorable folds that must individually pass


def get_fold_dates(
    actual_start: str,
    actual_end:   str,
    k:            int,
) -> list[tuple[str, str]]:
    """Return *k* equal-width ``(oos_start, oos_end)`` tuples covering the full period.

    Parameters
    ----------
    actual_start : ISO date of the first available data bar (e.g. ``"2004-01-02"``).
    actual_end   : ISO date of the last available data bar.
    k            : number of folds (must be >= 2).

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
    fold_days  = total_days // k

    folds = []
    for i in range(k):
        oos_start = start + timedelta(days=i * fold_days)
        oos_end   = end if i == k - 1 else start + timedelta(days=(i + 1) * fold_days)
        folds.append((oos_start.isoformat(), oos_end.isoformat()))
    return folds


def evaluate_rolling_wfa(
    trade_log:       list[dict],
    fold_dates:      list[tuple[str, str]],
    initial_capital: float,
    min_fold_trades: int = 5,
) -> dict:
    """Evaluate rolling multi-fold WFA on a completed trade log.

    For each ``(oos_start, oos_end)`` fold:

    * IS  = trades with ``ExitDate <  oos_start``
    * OOS = trades with ``oos_start <= ExitDate < oos_end``

    A fold is *scorable* when ``len(oos_trades) >= min_fold_trades``.
    Folds with fewer OOS trades are skipped silently.

    Parameters
    ----------
    trade_log        : list of trade dicts (must contain ``ExitDate`` and ``Profit``).
    fold_dates       : output of :func:`get_fold_dates`.
    initial_capital  : starting equity used to normalise P&L.
    min_fold_trades  : minimum OOS trades to score a fold (default 5).

    Returns
    -------
    dict with key ``wfa_rolling_verdict`` : ``"Pass"`` | ``"Fail"`` | ``"N/A"``
    """
    if not trade_log or not fold_dates:
        return {"wfa_rolling_verdict": "N/A"}

    pass_count   = 0
    scored_count = 0

    for oos_start, oos_end in fold_dates:
        is_trades  = [t for t in trade_log if t["ExitDate"] <  oos_start]
        oos_trades = [t for t in trade_log
                      if oos_start <= t["ExitDate"] < oos_end]

        if len(oos_trades) < min_fold_trades:
            continue  # insufficient data — skip this fold

        scored_count += 1
        fold_result = _evaluate_wfa(is_trades, oos_trades, initial_capital)
        if fold_result.get("wfa_verdict") == "Pass":
            pass_count += 1

    if scored_count < 2:
        return {"wfa_rolling_verdict": "N/A"}

    verdict = "Pass" if (pass_count / scored_count) >= _PASS_THRESHOLD else "Fail"
    return {"wfa_rolling_verdict": verdict}
