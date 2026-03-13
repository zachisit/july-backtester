# helpers/correlation.py
"""
Strategy correlation analysis.

Builds a daily P&L time-series for each strategy from its completed trade log,
computes pairwise Pearson correlations, identifies highly correlated pairs, and
saves the matrix to a CSV file.

Public API
----------
run_correlation_analysis(strategy_results, output_path, threshold) -> (matrix, pairs)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


# Default threshold above which two strategies are considered highly correlated.
DEFAULT_THRESHOLD = 0.70


def _build_daily_pnl_series(trade_log: list[dict]) -> pd.Series:
    """Aggregate a strategy's trade log into a daily P&L Series.

    Trades are grouped by ``ExitDate`` and their ``Profit`` values summed.
    The result is a ``pd.Series`` with a ``datetime64[ns]`` index and float values.

    Parameters
    ----------
    trade_log : list[dict]
        Each dict must contain ``"ExitDate"`` (ISO date string) and ``"Profit"``
        (float, dollars).

    Returns
    -------
    pd.Series  (may be empty if trade_log is empty or has no valid rows)
    """
    if not trade_log:
        return pd.Series(dtype=float)

    rows = [
        {"date": t["ExitDate"], "profit": t["Profit"]}
        for t in trade_log
        if t.get("ExitDate") and t.get("Profit") is not None
    ]
    if not rows:
        return pd.Series(dtype=float)

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    daily = df.groupby("date")["profit"].sum()
    daily.name = None
    return daily


def build_daily_pnl_matrix(strategy_results: list[dict]) -> pd.DataFrame:
    """Build a date × strategy matrix of daily realised P&L.

    Parameters
    ----------
    strategy_results : list[dict]
        Each dict is one simulation result; must contain ``"Strategy"`` (str) and
        ``"trade_log"`` (list[dict]).

    Returns
    -------
    pd.DataFrame
        Index: all trading dates that appear in any strategy's trade log.
        Columns: strategy names (unique; duplicates are suffixed ``_2``, ``_3``, …).
        Values: daily P&L in dollars; missing dates for a strategy are filled with 0.
        Returns an empty DataFrame when fewer than 2 strategies have trade data.
    """
    series_map: dict[str, pd.Series] = {}
    for res in strategy_results:
        strat_name = res.get("Strategy", "Unknown")
        trade_log  = res.get("trade_log") or []
        s = _build_daily_pnl_series(trade_log)
        if s.empty:
            continue
        # Deduplicate column names
        key = strat_name
        suffix = 2
        while key in series_map:
            key = f"{strat_name}_{suffix}"
            suffix += 1
        series_map[key] = s

    if len(series_map) < 2:
        return pd.DataFrame()

    matrix = pd.DataFrame(series_map).fillna(0.0).sort_index()
    return matrix


def compute_correlation_matrix(daily_pnl_df: pd.DataFrame) -> pd.DataFrame:
    """Compute the Pearson correlation matrix from a daily P&L DataFrame.

    Parameters
    ----------
    daily_pnl_df : pd.DataFrame
        Output of :func:`build_daily_pnl_matrix`.

    Returns
    -------
    pd.DataFrame  (correlation matrix), or empty DataFrame if input is empty.
    """
    if daily_pnl_df.empty or daily_pnl_df.shape[1] < 2:
        return pd.DataFrame()
    return daily_pnl_df.corr(method="pearson")


def find_high_correlation_pairs(
    corr_matrix: pd.DataFrame,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[tuple[str, str, float]]:
    """Return pairs of strategies whose Pearson correlation exceeds ``threshold``.

    Only the upper triangle of the matrix is checked (no self-pairs, no duplicates).

    Parameters
    ----------
    corr_matrix : pd.DataFrame
        Output of :func:`compute_correlation_matrix`.
    threshold   : float
        Absolute correlation value above which a pair is flagged. Default 0.85.

    Returns
    -------
    list of ``(strategy_a, strategy_b, correlation)`` tuples, sorted descending by
    correlation.  Empty list when nothing exceeds the threshold or input is empty.
    """
    if corr_matrix.empty:
        return []

    pairs: list[tuple[str, str, float]] = []
    cols = list(corr_matrix.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            val = corr_matrix.iloc[i, j]
            if pd.notna(val) and abs(val) > threshold:
                pairs.append((cols[i], cols[j], round(float(val), 4)))

    pairs.sort(key=lambda x: abs(x[2]), reverse=True)
    return pairs


def compute_avg_correlations(corr_matrix: pd.DataFrame) -> dict[str, float]:
    """Return each strategy's mean absolute Pearson correlation against all others.

    Only off-diagonal values are included (a strategy's correlation with itself is
    always 1.0 and is excluded from the average).

    Parameters
    ----------
    corr_matrix : pd.DataFrame
        Output of :func:`compute_correlation_matrix`.

    Returns
    -------
    dict mapping strategy name -> mean absolute off-diagonal correlation (float).
    Returns an empty dict when ``corr_matrix`` is empty or has fewer than 2 columns.
    """
    if corr_matrix.empty or corr_matrix.shape[1] < 2:
        return {}

    result: dict[str, float] = {}
    cols = list(corr_matrix.columns)
    for col in cols:
        off_diag = [
            abs(corr_matrix.loc[col, other])
            for other in cols
            if other != col and pd.notna(corr_matrix.loc[col, other])
        ]
        result[col] = float(sum(off_diag) / len(off_diag)) if off_diag else float("nan")
    return result


def save_correlation_csv(corr_matrix: pd.DataFrame, output_path: str) -> None:
    """Write ``corr_matrix`` to ``output_path`` as CSV (values rounded to 4 d.p.).

    Creates parent directories as needed. Does nothing when ``corr_matrix`` is empty.
    """
    if corr_matrix.empty:
        return
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    corr_matrix.round(4).to_csv(output_path)


def run_correlation_analysis(
    strategy_results: list[dict],
    output_path: str,
    threshold: float = DEFAULT_THRESHOLD,
) -> tuple[pd.DataFrame, list[tuple[str, str, float]]]:
    """End-to-end correlation analysis for a single portfolio's results.

    1. Builds the daily P&L matrix from all strategy trade logs.
    2. Computes the Pearson correlation matrix.
    3. Saves it to ``output_path`` as CSV.
    4. Identifies and returns any highly correlated strategy pairs.

    Parameters
    ----------
    strategy_results : list[dict]
        All simulation result dicts for one portfolio (with ``"Strategy"`` and
        ``"trade_log"`` keys).
    output_path      : str
        Destination CSV path.  Parent directories are created automatically.
    threshold        : float
        Correlation threshold for flagging pairs.  Default 0.85.

    Returns
    -------
    (corr_matrix, high_pairs)
        ``corr_matrix`` : pd.DataFrame — the full Pearson correlation matrix
                          (empty when fewer than 2 strategies have trade data).
        ``high_pairs``  : list of ``(strategy_a, strategy_b, correlation)`` tuples
                          for pairs exceeding ``threshold``.

    Notes
    -----
    **Measurement limitation**: Correlation is computed on exit-date P&L only,
    not daily mark-to-market.  Two strategies holding the same stock
    simultaneously will appear uncorrelated (or even negatively correlated) if
    they exit on different days.  Treat this matrix as a lower bound on true
    correlation — it will systematically *understate* how related two strategies
    are when they trade the same underlying at overlapping times.
    """
    logger.warning(
        "NOTE: Correlation is computed on exit-date P&L only, not daily "
        "mark-to-market. Two strategies holding the same stock simultaneously "
        "will appear uncorrelated if they exit on different days. Treat this "
        "matrix as a lower bound on true correlation."
    )
    daily_pnl_df = build_daily_pnl_matrix(strategy_results)
    corr_matrix  = compute_correlation_matrix(daily_pnl_df)
    save_correlation_csv(corr_matrix, output_path)
    high_pairs   = find_high_correlation_pairs(corr_matrix, threshold)
    return corr_matrix, high_pairs
