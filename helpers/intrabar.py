"""helpers/intrabar.py

Sub-bar (intraday) resolution for the daily execution engine (Phase 5 of the
instrument-metadata rewrite, issue #229).

A single daily OHLC bar can't say *when* within the day a level was hit, so the
daily engine makes an optimistic assumption: a stop fills exactly at the stop level
whenever ``Low <= stop``. That is wrong on a gap — if price opened *below* the stop,
the real fill is the (worse) open, and if both a stop and a profit target sit inside
one bar, the daily bar can't say which came first.

These pure helpers resolve that ambiguity by walking a finer-resolution series
(e.g. 1-minute bars) for the session. They are opt-in: the engine only calls them
when ``intrabar_resolution`` is enabled AND finer data is supplied, so default
behaviour is unchanged.

No I/O, no globals.
"""

from __future__ import annotations

import pandas as pd


def session_bars(intraday_df: pd.DataFrame, day) -> pd.DataFrame | None:
    """Return the finer-resolution bars belonging to the calendar day of ``day``.

    Matches on the normalized (date) part of the index, tolerant of tz-aware and
    tz-naive indices. Returns ``None`` when there is no data for that day.
    """
    if intraday_df is None or len(intraday_df) == 0:
        return None
    target = pd.Timestamp(day)
    if target.tzinfo is not None:
        target = target.tz_localize(None)
    idx = intraday_df.index
    idx_naive = idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx
    mask = idx_naive.normalize() == target.normalize()
    day_bars = intraday_df[mask]
    return day_bars if len(day_bars) else None


def window_bars(intraday_df: pd.DataFrame, start, end) -> pd.DataFrame | None:
    """Return the finer-resolution bars whose timestamp falls in ``[start, end)``.

    Unlike :func:`session_bars` (which matches a whole calendar day), this resolves
    the finer bars belonging to ONE coarse bar's span — needed for intraday coarse
    bars (e.g. 45-minute), where a single coarse row covers a sub-day window rather
    than the full session. For a daily coarse bar normalized to midnight the span
    ``[date, next_date)`` is exactly that calendar day, so daily behaviour is
    unchanged.

    Tolerant of tz-aware / tz-naive mismatch between the coarse timestamps and the
    finer index (compares in the finer index's own tz-naive frame). ``end`` may be
    ``None``/``NaT`` (last coarse bar) — then all bars at/after ``start`` are taken.
    Returns ``None`` when the window is empty.
    """
    if intraday_df is None or len(intraday_df) == 0:
        return None
    idx = intraday_df.index
    idx_naive = idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx
    s = pd.Timestamp(start)
    if s.tzinfo is not None:
        s = s.tz_localize(None)
    mask = idx_naive >= s
    if end is not None and not pd.isna(end):
        e = pd.Timestamp(end)
        if e.tzinfo is not None:
            e = e.tz_localize(None)
        mask = mask & (idx_naive < e)
    win = intraday_df[mask]
    return win if len(win) else None


def resolve_stop_fill(intraday_bars: pd.DataFrame, stop_level: float, side: str = "long"):
    """First sub-bar that touches ``stop_level``; returns ``(fill_price, timestamp)``.

    Gap-aware: if a sub-bar *opens* beyond the stop, the fill is that open (worse
    than the stop), not the stop itself. Otherwise the fill is the stop level.

    - ``long``:  stop is below entry — triggered when ``low <= stop`` (gap: ``open <= stop``)
    - ``short``: stop is above entry — triggered when ``high >= stop`` (gap: ``open >= stop``)

    Returns ``(None, None)`` if the stop is never touched in the session.
    """
    if intraday_bars is None or len(intraday_bars) == 0:
        return None, None
    for ts, bar in intraday_bars.iterrows():
        o, h, l = float(bar["Open"]), float(bar["High"]), float(bar["Low"])
        if side == "long":
            if o <= stop_level:
                return o, ts               # gapped through the stop -> fill at open
            if l <= stop_level:
                return float(stop_level), ts
        else:
            if o >= stop_level:
                return o, ts
            if h >= stop_level:
                return float(stop_level), ts
    return None, None


def resolve_order_precedence(intraday_bars: pd.DataFrame, stop_level: float,
                             target_level: float, side: str = "long"):
    """Decide whether the stop or the profit target triggers first within a bar.

    Walks the sub-bars in order and returns ``(which, fill_price, timestamp)`` where
    ``which`` is ``"stop"``, ``"target"`` or ``None``. When a single sub-bar touches
    both levels the STOP is assumed first (conservative — the pessimistic outcome).

    Fills are gap-aware for both levels (open beyond the level -> fill at open).
    """
    if intraday_bars is None or len(intraday_bars) == 0:
        return None, None, None
    for ts, bar in intraday_bars.iterrows():
        o, h, l = float(bar["Open"]), float(bar["High"]), float(bar["Low"])
        if side == "long":
            stop_hit = l <= stop_level
            target_hit = h >= target_level
            if stop_hit:  # conservative: stop takes precedence within the same sub-bar
                return "stop", (o if o <= stop_level else float(stop_level)), ts
            if target_hit:
                return "target", (o if o >= target_level else float(target_level)), ts
        else:
            stop_hit = h >= stop_level
            target_hit = l <= target_level
            if stop_hit:
                return "stop", (o if o >= stop_level else float(stop_level)), ts
            if target_hit:
                return "target", (o if o <= target_level else float(target_level)), ts
    return None, None, None
