# helpers/ml_export.py
"""
ML-ready trade feature export (SECTION 20).

Consolidates all trades from all strategy results into a single Parquet file
with a clean, stable schema.  The ``is_win`` column (1/0) is the default
classification target.

If pyarrow / fastparquet is not installed, the function falls back to writing
a CSV file at the same path with a ``.csv`` extension.

Public API
----------
export_trade_features(all_results, output_path) -> int
    Writes the file and returns the number of rows written.
    Returns 0 (no file written) when no trades are found.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Union

import pandas as pd

logger = logging.getLogger(__name__)

# Canonical column order — entry_* feature columns are appended after these.
_CANONICAL_COLS = [
    "Strategy",
    "Portfolio",
    "Symbol",
    "EntryDate",
    "ExitDate",
    "HoldDuration",
    "EntryPrice",
    "ExitPrice",
    "Profit",
    "ProfitPct",
    "Shares",
    "is_win",
    "RMultiple",
    "MAE_pct",
    "MFE_pct",
    "ExitReason",
    "InitialRisk",
]

# Columns that are internal-only and must never appear in the export.
_DROP_COLS = {"Trade"}


def export_trade_features(
    all_results: list[dict],
    output_path: Union[str, Path],
) -> int:
    """Consolidate all trade logs and write an ML-ready feature file.

    Parameters
    ----------
    all_results  : list of simulation result dicts, each containing at minimum
                   ``"Strategy"``, ``"Portfolio"``, and ``"trade_log"`` keys.
    output_path  : destination path for the ``.parquet`` file.  On
                   pyarrow/fastparquet absence, a sibling ``.csv`` file is
                   written instead.

    Returns
    -------
    int
        Number of rows written.  ``0`` when ``all_results`` is empty or no
        result contains any trades.
    """
    rows = []
    for result in all_results:
        strategy  = result.get("Strategy", "")
        portfolio = result.get("Portfolio", "")
        for trade in result.get("trade_log", []):
            row = dict(trade)
            row["Strategy"]  = strategy
            row["Portfolio"] = portfolio
            rows.append(row)

    if not rows:
        return 0

    df = pd.DataFrame(rows)

    # Drop internal columns
    df.drop(columns=[c for c in _DROP_COLS if c in df.columns], inplace=True)

    # Cast date columns
    for date_col in ("EntryDate", "ExitDate"):
        if date_col in df.columns:
            df[date_col] = pd.to_datetime(df[date_col], errors="coerce")

    # Cast is_win to int8 (compact ML-friendly label)
    if "is_win" in df.columns:
        df["is_win"] = df["is_win"].astype("int8")

    # Reorder columns: canonical first, then entry_* features, then any remainder
    entry_cols = sorted(c for c in df.columns if c.startswith("entry_"))
    canonical_present = [c for c in _CANONICAL_COLS if c in df.columns]
    remainder = [c for c in df.columns
                 if c not in set(canonical_present) and c not in set(entry_cols)]
    final_cols = canonical_present + entry_cols + remainder
    df = df[final_cols]

    output_path = Path(output_path)
    os.makedirs(output_path.parent, exist_ok=True)

    try:
        df.to_parquet(output_path, index=False)
    except ImportError:
        logger.warning(
            "pyarrow / fastparquet not installed — writing CSV fallback instead of Parquet. "
            "Install with: pip install pyarrow"
        )
        csv_path = output_path.with_suffix(".csv")
        df.to_csv(csv_path, index=False)

    return len(df)
