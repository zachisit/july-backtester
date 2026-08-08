"""DB_B4 confirmation-run plugins (baseline exit vs 50%@1R scale-out).

Precomputed-signal plugins, following the same pattern as the promoted
`promotions/DB_B4/db_b4_strategy.py`: read a stack parquet of per-ticker events and
emit Signal at snapped bar positions.

Two strategies are registered so a single `main.py` run compares them on identical
capital, concurrency and fill rules:

  "DB_B4 Baseline Exit"   1 at entry, -1 at the production gated-4w_low trail exit
  "DB_B4 Scale-Out 50@1R" 1 at entry, -0.5 when +1R is reached, -1 at the trail exit

The scale-out uses the engine's native fractional-exit support: a signal in
(-1, 0) scales OUT that fraction of the position (helpers/portfolio_simulations.py
lines 415-427). One position, two exits — nothing in the Do-Not-Touch simulation
engine is modified.

Run with stop_loss_configs=[{"type":"none"}] — exits are baked into the signals.
Set DB_B4_CONFIRM_DIR to the directory holding stack_baseline.parquet /
stack_scaleout.parquet.
"""
from __future__ import annotations

import logging
import os

import pandas as pd

from helpers.registry import register_strategy

logger = logging.getLogger(__name__)

_DIR = os.environ.get("DB_B4_CONFIRM_DIR", "")
_MAX_SNAP_LAG_DAYS = 7          # same guard as the promoted plugin


def _load(name: str) -> pd.DataFrame | None:
    if not _DIR:
        logger.warning("DB_B4_CONFIRM_DIR unset — %s will not fire", name)
        return None
    path = os.path.join(_DIR, name)
    if not os.path.exists(path):
        logger.warning("DB_B4 confirm: %s not found — no trades", path)
        return None
    df = pd.read_parquet(path)
    for col in ("entry_date", "exit_date", "scale_date"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col]).dt.normalize()
    return df


_BASE = _load("stack_baseline.parquet")
_SCALE = _load("stack_scaleout.parquet")


def _bar_pos(idx: pd.DatetimeIndex, ts, max_lag_days: int | None = None) -> int | None:
    """Snap ts to the next available bar; None past end / beyond the lag guard."""
    if ts is None or pd.isna(ts):
        return None
    # The csv provider returns a tz-aware (UTC) index while the signal tables are
    # tz-naive; comparing the two raises. Align to whatever the index uses.
    ts = pd.Timestamp(ts)
    if getattr(idx, "tz", None) is not None:
        ts = ts.tz_localize(idx.tz) if ts.tzinfo is None else ts.tz_convert(idx.tz)
    elif ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    pos = idx.searchsorted(ts)
    if pos >= len(idx):
        return None
    if max_lag_days is not None and (idx[pos] - ts).days > max_lag_days:
        return None
    return int(pos)


def _emit(df: pd.DataFrame, table: pd.DataFrame | None, scaled: bool) -> pd.DataFrame:
    sym = str(df.attrs.get("symbol", ""))
    sig = pd.Series(0.0, index=df.index, dtype="float64")
    if table is not None:
        rows = table[table["ticker"] == sym]
        idx = df.index
        for _, ev in rows.iterrows():
            ie = _bar_pos(idx, ev["entry_date"], _MAX_SNAP_LAG_DAYS)
            if ie is None:
                continue
            ix = _bar_pos(idx, ev["exit_date"])
            if ix is None or ix <= ie:
                ix = len(idx) - 1
                if ix <= ie:
                    continue
            sig.iloc[ie] = 1.0
            if scaled and "scale_date" in ev and not pd.isna(ev["scale_date"]):
                isc = _bar_pos(idx, ev["scale_date"])
                # Only a scale that lands strictly between entry and final exit is a
                # real partial; same-bar or post-exit collapses to the full exit.
                if isc is not None and ie < isc < ix:
                    sig.iloc[isc] = -float(ev.get("scale_frac", 0.5))
            sig.iloc[ix] = -1.0
    out = df.copy()
    out["Signal"] = sig.values
    return out


@register_strategy(name="DB_B4 Baseline Exit", dependencies=[], params={})
def db_b4_baseline(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Production gated-4w_low trailing exit, 100% of position."""
    return _emit(df, _BASE, scaled=False)


@register_strategy(name="DB_B4 Scale-Out 50@1R", dependencies=[], params={})
def db_b4_scaleout(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Sell half at +1R (fractional exit), trail the remainder to the same stop."""
    return _emit(df, _SCALE, scaled=True)
