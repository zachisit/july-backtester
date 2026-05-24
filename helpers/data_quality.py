"""helpers/data_quality.py

Pre-flight data quality validation for OHLCV data.

Detects common data issues that silently corrupt backtest results:
1. Missing bars (gaps in expected calendar)
2. Price jumps >20% (potential unadjusted splits)
3. Zero volume days
4. OHLC relationship violations
5. Negative prices
6. Duplicate timestamps
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)

# Price jump threshold (20% daily move flags as potential unadjusted split)
_PRICE_JUMP_THRESHOLD = 0.20


def validate_ohlcv(df: pd.DataFrame, symbol: str, timeframe: str = "D") -> tuple[float, list[str]]:
    """
    Validate OHLCV data and return quality score 0-100 and list of issues.

    Checks performed:
    1. Missing bars (compare against expected calendar)
    2. Price jumps >20% (potential unadjusted split)
    3. Zero volume days
    4. OHLC relationship violations (High < Low, Close outside H/L range)
    5. Negative prices
    6. Duplicate timestamps

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV data with DatetimeIndex. Expected columns: Open, High, Low, Close, Volume
    symbol : str
        Symbol name for error messages
    timeframe : str
        Timeframe code ("D", "H", "MIN", etc.) - used for missing bar detection

    Returns
    -------
    score : float
        Quality score 0-100 (100 = perfect, 0 = severe issues)
    issues : list[str]
        Human-readable issue descriptions

    Examples
    --------
    >>> score, issues = validate_ohlcv(spy_df, "SPY", "D")
    >>> if score < 80:
    ...     print(f"Low quality data: {issues}")
    """
    if df is None or df.empty:
        return 0.0, [f"{symbol}: DataFrame is empty"]

    issues = []
    demerits = 0  # Points deducted from 100
    total_bars = len(df)

    # --- CHECK 1: Duplicate timestamps ---
    duplicates = df.index.duplicated().sum()
    if duplicates > 0:
        issues.append(f"Duplicate timestamps: {duplicates} bars")
        demerits += min(20, duplicates * 2)  # Cap at 20 points

    # --- CHECK 2: Negative prices ---
    for col in ["Open", "High", "Low", "Close"]:
        if col in df.columns:
            negative_count = (df[col] < 0).sum()
            if negative_count > 0:
                issues.append(f"Negative {col} prices: {negative_count} bars")
                demerits += min(30, negative_count * 5)  # Severe issue

    # --- CHECK 3: OHLC relationship violations ---
    if all(c in df.columns for c in ["Open", "High", "Low", "Close"]):
        # High must be >= Low
        hl_violations = (df["High"] < df["Low"]).sum()
        if hl_violations > 0:
            issues.append(f"High < Low violations: {hl_violations} bars")
            demerits += min(25, hl_violations * 3)

        # Close must be within [Low, High]
        close_violations = ((df["Close"] < df["Low"]) | (df["Close"] > df["High"])).sum()
        if close_violations > 0:
            issues.append(f"Close outside H/L range: {close_violations} bars")
            demerits += min(20, close_violations * 2)

        # Open must be within [Low, High]
        open_violations = ((df["Open"] < df["Low"]) | (df["Open"] > df["High"])).sum()
        if open_violations > 0:
            issues.append(f"Open outside H/L range: {open_violations} bars")
            demerits += min(15, open_violations * 2)

    # --- CHECK 4: Price jumps >20% (potential unadjusted splits) ---
    if "Close" in df.columns:
        returns = df["Close"].pct_change().abs()
        large_jumps = returns[returns > _PRICE_JUMP_THRESHOLD]
        if len(large_jumps) > 0:
            # Report first 3 jumps
            jump_dates = large_jumps.head(3).index.strftime("%Y-%m-%d").tolist()
            jump_pcts = large_jumps.head(3).values * 100
            jump_strs = [f"{date} ({pct:.1f}%)" for date, pct in zip(jump_dates, jump_pcts)]
            issues.append(f"Price jumps >{_PRICE_JUMP_THRESHOLD*100:.0f}%: {len(large_jumps)} occurrences, e.g., {', '.join(jump_strs)}")
            demerits += min(15, len(large_jumps) * 2)

    # --- CHECK 5: Zero volume days ---
    if "Volume" in df.columns:
        zero_volume = (df["Volume"] == 0).sum()
        if zero_volume > 0:
            pct = (zero_volume / total_bars) * 100
            issues.append(f"Zero volume: {zero_volume} bars ({pct:.1f}%)")
            demerits += min(10, int(pct))  # 1 point per 1% of bars

    # --- CHECK 6: Missing bars ---
    # Only check for daily data (intraday missing bars are common due to market hours)
    if timeframe.upper() == "D" and total_bars > 1:
        expected_bars = _estimate_expected_bars(df.index[0], df.index[-1], timeframe)
        if expected_bars > total_bars:
            missing = expected_bars - total_bars
            pct = (missing / expected_bars) * 100
            issues.append(f"Missing bars: {missing} gaps ({pct:.1f}% of expected)")
            demerits += min(20, int(pct / 2))  # 1 point per 2% missing

    # --- COMPUTE SCORE ---
    score = max(0.0, 100.0 - demerits)

    return score, issues


def _estimate_expected_bars(start_dt: pd.Timestamp, end_dt: pd.Timestamp, timeframe: str) -> int:
    """
    Estimate expected number of bars for a date range.

    Uses business day frequency for daily data. Returns actual count for
    intraday (missing bar check disabled for intraday).

    Parameters
    ----------
    start_dt : pd.Timestamp
        First bar timestamp
    end_dt : pd.Timestamp
        Last bar timestamp
    timeframe : str
        Timeframe code ("D", "H", "MIN")

    Returns
    -------
    int
        Estimated bar count
    """
    if timeframe.upper() == "D":
        # Business days between start and end (approximate)
        bdays = pd.bdate_range(start=start_dt, end=end_dt, freq="B")
        return len(bdays)
    else:
        # Intraday: missing bars are expected (market hours, holidays)
        # Return 0 to disable the check
        return 0


def quality_report(symbols: list[str], data: dict[str, pd.DataFrame], timeframe: str = "D") -> pd.DataFrame:
    """
    Generate quality report for multiple symbols.

    Parameters
    ----------
    symbols : list[str]
        List of symbol names
    data : dict[str, pd.DataFrame]
        {symbol: OHLCV DataFrame} mapping
    timeframe : str
        Timeframe code for missing bar detection

    Returns
    -------
    pd.DataFrame
        Columns: symbol, score, issues (joined string), bars
        Sorted by score (lowest first)
    """
    rows = []
    for symbol in symbols:
        df = data.get(symbol)
        if df is None:
            rows.append({
                "symbol": symbol,
                "score": 0.0,
                "issues": "No data",
                "bars": 0,
            })
            continue

        score, issues = validate_ohlcv(df, symbol, timeframe)
        rows.append({
            "symbol": symbol,
            "score": score,
            "issues": "; ".join(issues) if issues else "No issues",
            "bars": len(df),
        })

    report_df = pd.DataFrame(rows)
    report_df = report_df.sort_values("score", ascending=True).reset_index(drop=True)
    return report_df
