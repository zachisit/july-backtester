"""helpers/continuous_contract.py

Build a back-adjusted **continuous** futures series from individual contract-month
frames, and validate pre-built continuous series (from CSV/Parquet).

Polygon's futures API (and most raw vendors) return per-contract data — there is no
native continuous series. Multi-year backtests need one price stream, so consecutive
contracts are stitched at roll points and back-adjusted to remove the price gap
between the expiring front month and the next contract.

Two adjustment conventions:
  - **Panama (additive)**: shift historical prices by the cumulative roll gap
    (``next_open - front_close``). Preserves absolute point moves — the right choice
    for $/point P&L, so it is the default.
  - **Ratio (proportional)**: scale historical prices by the cumulative roll ratio.
    Preserves percentage returns.

Pure, stateless, no I/O.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

PANAMA = "panama"
RATIO = "ratio"

_OHLC = ["Open", "High", "Low", "Close"]


def infer_roll_dates_by_volume(frames: list[pd.DataFrame]) -> list[pd.Timestamp]:
    """Roll from contract *i* to *i+1* on the first overlapping date where the next
    contract's Volume exceeds the front contract's (volume crossover). Falls back to
    the front contract's last date when there is no overlap or no crossover.

    ``frames`` must be time-ordered (front month first). Returns one roll date per
    adjacent pair (``len(frames) - 1`` dates).
    """
    roll_dates: list[pd.Timestamp] = []
    for front, back in zip(frames[:-1], frames[1:]):
        overlap = front.index.intersection(back.index)
        roll = None
        if len(overlap) and "Volume" in front.columns and "Volume" in back.columns:
            crossover = overlap[back.loc[overlap, "Volume"] > front.loc[overlap, "Volume"]]
            if len(crossover):
                roll = crossover[0]
        if roll is None:
            roll = front.index[-1]
        roll_dates.append(roll)
    return roll_dates


def _gap_at_roll(front: pd.DataFrame, back: pd.DataFrame, roll_date: pd.Timestamp,
                 method: str) -> float:
    """Price gap between contracts at the roll, using the close on/just before the
    roll date. Additive difference for panama, ratio for proportional."""
    f_idx = front.index[front.index <= roll_date]
    b_idx = back.index[back.index <= roll_date]
    if not len(f_idx) or not len(b_idx):
        return 0.0 if method == PANAMA else 1.0
    f_close = float(front.loc[f_idx[-1], "Close"])
    b_close = float(back.loc[b_idx[-1], "Close"])
    if method == RATIO:
        return b_close / f_close if f_close else 1.0
    return b_close - f_close


def build_continuous(frames: list[pd.DataFrame], method: str = PANAMA,
                     roll_dates: list[pd.Timestamp] | None = None) -> pd.DataFrame:
    """Stitch time-ordered per-contract ``frames`` into one back-adjusted series.

    Each frame needs a DatetimeIndex and OHLC(V) columns. For each contract, only
    bars strictly before its roll date are taken (the last frame keeps all its bars).
    Historical bars are then back-adjusted by the cumulative roll gap so the seam is
    continuous. Returns a single OHLCV DataFrame.
    """
    if not frames:
        return pd.DataFrame()
    if len(frames) == 1:
        return frames[0].copy()

    if roll_dates is None:
        roll_dates = infer_roll_dates_by_volume(frames)
    if len(roll_dates) != len(frames) - 1:
        raise ValueError("roll_dates must have exactly len(frames)-1 entries")

    # 1) Slice each contract to the window it is the "active" front month.
    segments: list[pd.DataFrame] = []
    prev_roll = None
    for i, frame in enumerate(frames):
        if i < len(frames) - 1:
            end = roll_dates[i]
            seg = frame[frame.index < end]
        else:
            seg = frame  # last contract keeps everything to the end
        if prev_roll is not None:
            seg = seg[seg.index >= prev_roll]
        segments.append(seg)
        if i < len(frames) - 1:
            prev_roll = roll_dates[i]

    # 2) Cumulative back-adjustment. Work from the most recent contract backwards so
    #    the newest segment is unadjusted (real prices) and older ones are shifted.
    cum_add = 0.0
    cum_ratio = 1.0
    adjusted: list[pd.DataFrame] = [None] * len(frames)  # type: ignore
    adjusted[-1] = segments[-1].copy()
    for i in range(len(frames) - 2, -1, -1):
        gap = _gap_at_roll(frames[i], frames[i + 1], roll_dates[i], method)
        seg = segments[i].copy()
        if method == RATIO:
            cum_ratio *= gap
            for c in _OHLC:
                if c in seg.columns:
                    seg[c] = seg[c] * cum_ratio
        else:  # panama additive
            cum_add += gap
            for c in _OHLC:
                if c in seg.columns:
                    seg[c] = seg[c] + cum_add
        adjusted[i] = seg

    out = pd.concat(adjusted).sort_index()
    out = out.loc[~out.index.duplicated(keep="last")]
    return out


def validate_continuous(df: pd.DataFrame, jump_threshold: float = 0.20) -> tuple[bool, list[str]]:
    """Sanity-check a (possibly pre-built) continuous series.

    Flags issues that indicate a bad stitch or unadjusted rolls:
      - empty / missing OHLC columns
      - non-monotonic or duplicated index
      - non-positive prices
      - large close-to-close jumps (> ``jump_threshold``) — a likely unadjusted roll

    Returns ``(ok, issues)`` where ``ok`` is True when no issues are found.
    """
    issues: list[str] = []
    if df is None or df.empty:
        return False, ["continuous series is empty"]
    missing = [c for c in _OHLC if c not in df.columns]
    if missing:
        issues.append(f"missing OHLC columns: {missing}")
        return False, issues
    if not df.index.is_monotonic_increasing:
        issues.append("index is not monotonically increasing")
    if df.index.duplicated().any():
        issues.append(f"duplicate timestamps: {int(df.index.duplicated().sum())}")
    nonpos = int((df[_OHLC] <= 0).any(axis=1).sum())
    if nonpos:
        issues.append(f"non-positive prices: {nonpos} bars")
    ret = df["Close"].pct_change().abs()
    jumps = ret[ret > jump_threshold]
    if len(jumps):
        issues.append(f"large close-to-close jumps (>{jump_threshold:.0%}): {len(jumps)} "
                      "— possible unadjusted roll")
    return (len(issues) == 0), issues


def rolls_spanned(entry_date, exit_date, roll_dates) -> list:
    """Roll dates strictly inside the ``(entry_date, exit_date)`` hold window.

    A back-adjusted continuous series is built for **signal continuity**, not for a
    real position physically held across a roll: the synthetic series has no gap at
    the seam, but a live position would actually roll (close the expiring contract,
    open the next) and realise the roll spread. For short-hold strategies (hours to
    days) a position never spans a roll and this is a non-issue; for longer-horizon
    futures strategies it can silently misstate P&L across the seam.

    Callers can use this to warn/flag such trades:

        spanned = rolls_spanned(pos_entry, pos_exit, roll_dates)
        if spanned:
            logger.warning("position %s held across %d roll(s): %s", sym, len(spanned), spanned)

    Returns the list of roll timestamps ``t`` with ``entry_date < t < exit_date``.

    tz-safe: mixed tz-aware / tz-naive inputs are normalized to naive before
    comparison (avoids the ``TypeError`` class seen in the VIX tz bug).
    """
    def _naive(x):
        t = pd.Timestamp(x)
        return t.tz_localize(None) if t.tzinfo is not None else t
    lo, hi = _naive(entry_date), _naive(exit_date)
    return [_naive(x) for x in roll_dates if lo < _naive(x) < hi]
