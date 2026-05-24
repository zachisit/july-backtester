"""Blind-design cutoff guard.

Wraps every data-loading code path so that any attempt to load data with a
timestamp on or after BLIND_DESIGN_CUTOFF raises BlindDesignViolation. This
operationalises the blind-design protocol documented in
BLIND_DESIGN_PROTOCOL.md: research and parameter selection must happen on the
pre-cutoff window only, and the post-cutoff held-out era is unlocked exactly
once for a one-shot verification at the end of the round.

Usage:

    from helpers import blind_design_guard

    @blind_design_guard.enforce
    def get_price_data(symbol, start_date, end_date, config):
        ...

The guard inspects the returned DataFrame's index. If any timestamp is at or
past the cutoff and BLIND_DESIGN_UNLOCK is False, it raises
BlindDesignViolation. The guard is a no-op when BLIND_DESIGN_CUTOFF is None
(default) or when BLIND_DESIGN_UNLOCK is True.
"""

from __future__ import annotations

import functools
import logging

import pandas as pd

logger = logging.getLogger(__name__)


class BlindDesignViolation(RuntimeError):
    """Raised when a data load returns timestamps at or past the blind cutoff."""


def _get_cutoff_and_unlock():
    from config import CONFIG

    cutoff_raw = CONFIG.get("BLIND_DESIGN_CUTOFF")
    unlock = bool(CONFIG.get("BLIND_DESIGN_UNLOCK", False))
    if cutoff_raw is None:
        return None, unlock
    return pd.Timestamp(cutoff_raw, tz="UTC"), unlock


def _violates(df, cutoff) -> pd.Timestamp | None:
    if df is None or not hasattr(df, "index") or len(df) == 0:
        return None
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        return None
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    bad = idx[idx >= cutoff]
    if len(bad):
        return bad[0]
    return None


def check(df, source: str = "data load") -> None:
    """Raise BlindDesignViolation if df has any timestamp at or past the cutoff.

    No-op when cutoff is unset or unlock is True.
    """
    cutoff, unlock = _get_cutoff_and_unlock()
    if cutoff is None or unlock:
        return
    violator = _violates(df, cutoff)
    if violator is not None:
        raise BlindDesignViolation(
            f"{source}: returned data crosses blind cutoff "
            f"{cutoff.date()} (saw {violator}). Set BLIND_DESIGN_UNLOCK=True "
            f"in config.py only for the one-shot verification."
        )


def enforce(fetcher):
    """Decorator: enforce cutoff on the DataFrame returned by *fetcher*.

    The wrapped fetcher must return a DataFrame with a DatetimeIndex (or
    None). The blind cutoff is read at call time so config changes take
    effect without re-importing.
    """

    @functools.wraps(fetcher)
    def wrapped(*args, **kwargs):
        df = fetcher(*args, **kwargs)
        symbol = args[0] if args else kwargs.get("symbol", "?")
        check(df, source=f"{fetcher.__module__}.{fetcher.__name__}({symbol})")
        return df

    return wrapped
