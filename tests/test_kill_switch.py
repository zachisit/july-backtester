"""Tests for helpers/kill_switch — the regime-aware kill-switch overlay.

Focus: pure-function behaviour on synthetic curves with hand-computed
expected values. No I/O, no network, no randomness.
"""

import numpy as np
import pandas as pd
import pytest

from helpers.kill_switch import (
    KS_NONE, KS_DD, KS_VIX, KS_BOTH,
    compute_drawdown,
    compute_plateau_days,
    detect_triggers,
    plateau_alerts,
    apply_overlay,
    summarize_triggers,
)


def _make_dates(n, start="2010-01-04"):
    return pd.bdate_range(start=start, periods=n)


def test_drawdown_at_high_is_zero():
    eq = pd.Series([100, 110, 120, 130], index=_make_dates(4))
    dd = compute_drawdown(eq)
    # All bars are new highs → DD = 0
    np.testing.assert_array_almost_equal(dd.values, [0, 0, 0, 0])


def test_drawdown_after_fall():
    eq = pd.Series([100, 200, 150, 100, 50], index=_make_dates(5))
    dd = compute_drawdown(eq)
    # Peaks: 100, 200, 200, 200, 200. DDs: 0, 0, 0.25, 0.50, 0.75
    np.testing.assert_array_almost_equal(dd.values, [0, 0, 0.25, 0.5, 0.75])


def test_plateau_days_resets_on_new_high():
    idx = pd.to_datetime(["2010-01-04", "2010-01-05", "2010-01-06", "2010-01-07"])
    eq = pd.Series([100, 90, 80, 110], index=idx)
    days = compute_plateau_days(eq)
    # bar 0: new high, days=0
    # bar 1: down, 1 day since high
    # bar 2: down, 2 days since high
    # bar 3: NEW high, days=0
    assert list(days.values) == [0, 1, 2, 0]


def test_detect_triggers_dd_only():
    eq = pd.Series([100, 200, 100, 150], index=_make_dates(4))
    vix = pd.Series([15, 20, 25, 18], index=_make_dates(4))
    triggers = detect_triggers(eq, vix, dd_threshold=0.30, vix_panic_threshold=60.0)
    # DDs: 0, 0, 0.5, 0.25. Threshold 0.30 → bar 2 fires DD trigger.
    # No VIX above 60.
    assert triggers.iat[2] == KS_DD
    assert triggers.iat[0] == KS_NONE
    assert triggers.iat[3] == KS_NONE


def test_detect_triggers_vix_only():
    eq = pd.Series([100, 100, 100, 100], index=_make_dates(4))
    vix = pd.Series([15, 30, 70, 45], index=_make_dates(4))
    triggers = detect_triggers(eq, vix, dd_threshold=0.30, vix_panic_threshold=60.0)
    # No DD; VIX > 60 only at bar 2
    assert triggers.iat[2] == KS_VIX
    assert triggers.iat[0] == KS_NONE
    assert triggers.iat[3] == KS_NONE


def test_detect_triggers_both():
    eq = pd.Series([100, 200, 100, 100], index=_make_dates(4))
    vix = pd.Series([15, 20, 70, 80], index=_make_dates(4))
    triggers = detect_triggers(eq, vix, dd_threshold=0.30, vix_panic_threshold=60.0)
    # Bar 2: DD=0.5 AND VIX=70 → BOTH
    # Bar 3: DD=0.5 AND VIX=80 → BOTH
    assert triggers.iat[2] == KS_BOTH
    assert triggers.iat[3] == KS_BOTH


def test_plateau_alerts_threshold():
    idx = pd.bdate_range(start="2010-01-04", periods=300)  # ~14 months
    # Flat then declining: never sets new high after bar 0
    eq = pd.Series(np.r_[100, np.linspace(99, 50, 299)], index=idx)
    flags = plateau_alerts(eq, plateau_threshold_months=12)
    # After 12 months × 30.44 days = 365 calendar days, plateau exceeds threshold.
    # 300 trading days ~ 420 calendar days, so the back half should be flagged.
    assert flags.iat[-1] == True
    assert flags.iat[0] == False


def test_overlay_no_triggers_preserves_curve():
    eq = pd.Series([100, 110, 120, 130], index=_make_dates(4))
    triggers = pd.Series([KS_NONE]*4, index=eq.index)
    out = apply_overlay(eq, triggers)
    # No triggers → identical curve
    np.testing.assert_array_almost_equal(out.values, eq.values)


def test_overlay_vix_panic_freezes_returns():
    eq = pd.Series([100, 110, 121, 133.1], index=_make_dates(4))
    triggers = pd.Series([KS_NONE, KS_VIX, KS_VIX, KS_NONE], index=eq.index)
    out = apply_overlay(eq, triggers, vix_cash_factor=0.0)
    # Daily returns: 0, 0.10, 0.10, 0.10
    # With VIX panic at bars 1+2: factor=0, so bars 1+2 return = 0
    # Resulting equity: 100, 100, 100, 100 * 1.10 = 110
    np.testing.assert_array_almost_equal(out.values, [100, 100, 100, 110])


def test_overlay_dd_reduces_exposure():
    eq = pd.Series([100, 200, 100, 110], index=_make_dates(4))
    triggers = pd.Series([KS_NONE, KS_NONE, KS_DD, KS_DD], index=eq.index)
    out = apply_overlay(eq, triggers, dd_reduce_factor=0.5)
    # Daily returns: 0, 1.0, -0.5, 0.10
    # Bars 2+3: factor=0.5 → returns become -0.25 and 0.05
    # Resulting equity: 100, 200, 200 * 0.75 = 150, 150 * 1.05 = 157.5
    np.testing.assert_array_almost_equal(out.values, [100, 200, 150, 157.5])


def test_summarize_triggers_counts():
    idx = _make_dates(10)
    triggers = pd.Series([0, 0, 1, 1, 2, 2, 2, 3, 0, 0], index=idx)
    plateau = pd.Series([False]*5 + [True]*5, index=idx)
    summary = summarize_triggers(triggers, plateau)
    assert summary["dd_bars"] == 2
    assert summary["vix_bars"] == 3
    assert summary["both_bars"] == 1
    assert summary["plateau_bars"] == 5
    assert summary["total_bars"] == 10
    assert summary["dd_pct"] == 20.0
    assert summary["vix_pct"] == 30.0
    assert summary["plateau_pct"] == 50.0


def test_overlay_initial_equity_preserved():
    eq = pd.Series([100, 90, 80, 70, 60], index=_make_dates(5))
    triggers = pd.Series([KS_NONE, KS_VIX, KS_VIX, KS_VIX, KS_VIX], index=eq.index)
    out = apply_overlay(eq, triggers, vix_cash_factor=0.0)
    # Bar 0 is the starting equity (always preserved)
    assert out.iat[0] == 100
