"""Regime-aware kill-switch overlay.

Takes a backtest equity curve and VIX series and computes a modified curve
where defined triggers reduce equity exposure or force a flight to cash.

This is a POST-HOC OVERLAY — it does not modify the simulation engine. It
answers the question "what would this strategy have looked like if it had
the following safety net active?" without changing how trades were placed.

Triggers (all configurable):
    DD trigger:        drawdown > dd_threshold → multiply remaining equity
                       returns by `dd_reduce_factor` (default 0.5 = halve
                       exposure) until equity recovers above peak * (1-dd/2).
    Plateau trigger:   plateau_months > plateau_threshold → flag for manual
                       review (no automatic action; just record).
    VIX panic trigger: VIX > vix_panic_threshold → flatten to cash (return=0)
                       until VIX drops back below threshold.

Returned series describe what action the kill switch took on each bar:
    0 = no action (full exposure)
    1 = dd-reduced exposure
    2 = vix-panic flat to cash
    3 = both (intersection — should be rare)

Usage in script form: see scripts/apply_kill_switch.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Trigger code constants
KS_NONE   = 0
KS_DD     = 1
KS_VIX    = 2
KS_BOTH   = 3


def compute_drawdown(equity: pd.Series) -> pd.Series:
    """Drawdown as a positive fraction at each bar (0.0 = at high, 0.30 = 30% below high)."""
    peak = equity.cummax()
    return (peak - equity) / peak


def compute_plateau_days(equity: pd.Series) -> pd.Series:
    """Days since the most recent new high, at each bar."""
    is_new_high = equity == equity.cummax()
    # Days since last True in is_new_high
    days_since = pd.Series(0, index=equity.index, dtype=int)
    last_high_idx = equity.index[0]
    for i, dt in enumerate(equity.index):
        if is_new_high.iat[i]:
            last_high_idx = dt
            days_since.iat[i] = 0
        else:
            days_since.iat[i] = (dt - last_high_idx).days
    return days_since


def detect_triggers(
    equity: pd.Series,
    vix: pd.Series,
    dd_threshold: float = 0.30,
    vix_panic_threshold: float = 60.0,
) -> pd.Series:
    """Per-bar trigger code series. Drawdown threshold and VIX threshold
    are checked independently; their codes are OR'd into KS_BOTH if both fire.

    Plateau trigger is reported separately by `plateau_alerts()` since it
    only flags (no automatic action).
    """
    dd = compute_drawdown(equity)
    vix_aligned = vix.reindex(equity.index, method="ffill").fillna(0.0)
    dd_fire = (dd > dd_threshold)
    vix_fire = (vix_aligned > vix_panic_threshold)
    codes = pd.Series(KS_NONE, index=equity.index, dtype=int)
    codes[dd_fire & ~vix_fire] = KS_DD
    codes[~dd_fire & vix_fire] = KS_VIX
    codes[dd_fire & vix_fire]  = KS_BOTH
    return codes


def plateau_alerts(equity: pd.Series, plateau_threshold_months: int = 18) -> pd.Series:
    """Boolean series — True where plateau (days since high) exceeds threshold."""
    days = compute_plateau_days(equity)
    months = days / 30.44
    return months >= plateau_threshold_months


def apply_overlay(
    equity: pd.Series,
    triggers: pd.Series,
    dd_reduce_factor: float = 0.5,
    vix_cash_factor: float = 0.0,
) -> pd.Series:
    """Apply trigger actions to the equity curve.

    On each bar, look up the trigger code:
      KS_NONE → daily return unchanged
      KS_DD   → daily return multiplied by `dd_reduce_factor`
      KS_VIX  → daily return multiplied by `vix_cash_factor` (0 = flat)
      KS_BOTH → use the smaller of the two factors

    Returns the modified equity curve, starting at the same initial value
    as the input.
    """
    daily_ret = equity.pct_change().fillna(0.0)
    triggers = triggers.reindex(equity.index, method="ffill").fillna(KS_NONE).astype(int)
    factor = pd.Series(1.0, index=equity.index)
    factor[triggers == KS_DD]  = dd_reduce_factor
    factor[triggers == KS_VIX] = vix_cash_factor
    factor[triggers == KS_BOTH] = min(dd_reduce_factor, vix_cash_factor)
    modified_ret = daily_ret * factor
    initial = equity.iloc[0]
    modified_equity = (1 + modified_ret).cumprod() * initial
    return modified_equity


def summarize_triggers(triggers: pd.Series, plateau_flags: pd.Series) -> dict:
    """Aggregate counters describing how often each trigger fired."""
    return {
        "dd_bars":      int((triggers == KS_DD).sum()),
        "vix_bars":     int((triggers == KS_VIX).sum()),
        "both_bars":    int((triggers == KS_BOTH).sum()),
        "plateau_bars": int(plateau_flags.sum()),
        "total_bars":   int(len(triggers)),
        "dd_pct":       float((triggers == KS_DD).sum() / len(triggers) * 100),
        "vix_pct":      float((triggers == KS_VIX).sum() / len(triggers) * 100),
        "plateau_pct":  float(plateau_flags.sum() / len(plateau_flags) * 100),
    }
