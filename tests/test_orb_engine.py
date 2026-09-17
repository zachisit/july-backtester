"""
Hand-computed fill-mechanics tests for the ORB engine.

Every expected number here is derived by hand from the synthetic bars, never copied from
engine output. Each test is designed to FAIL if the mechanic it protects is broken -- see
tests/test_orb_engine_mutations.py for the mutation proofs.
"""
from __future__ import annotations

import os
import sys
from datetime import time

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

from orb_engine import Costs, OrbParams, run_orb, trades_frame  # noqa: E402

NY = "America/New_York"
COSTS = Costs(tick_size=0.25, point_value=50.0, slippage_ticks=1.0, commission_rt=2.50)
SLIP = 0.25


def session(day: str, bars: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    """bars = [(HH:MM, open, high, low, close), ...]"""
    idx = pd.to_datetime([f"{day} {t}" for t, *_ in bars]).tz_localize(NY)
    data = [b[1:] for b in bars]
    return pd.DataFrame(data, index=idx, columns=["open", "high", "low", "close"]).assign(volume=100)


def flat_or(day: str, hi: float = 101.0, lo: float = 100.0) -> list[tuple]:
    """15 one-minute OR bars spanning exactly [lo, hi]."""
    out = []
    for i in range(15):
        mid = (hi + lo) / 2
        out.append((f"09:{30 + i:02d}", mid, hi if i == 0 else mid, lo if i == 1 else mid, mid))
    return out


def tail_to_close(start_min: int, px: float) -> list[tuple]:
    """Filler bars from 09:30+start_min through 15:59 sitting flat at px."""
    out = []
    for m in range(9 * 60 + 30 + start_min, 16 * 60):
        out.append((f"{m // 60:02d}:{m % 60:02d}", px, px, px, px))
    return out


def test_clean_long_target_fill_is_hand_computable():
    """OR 100-101. Trigger 101.0, no gap. Entry 101.25, stop 100.0, risk 1.25, 1R target 102.50."""
    bars = flat_or("2025-01-02")
    bars += [("09:45", 100.5, 101.5, 100.4, 101.4)]
    bars += [("09:46", 101.4, 102.6, 101.3, 102.5)]
    bars += tail_to_close(17, 102.5)
    df = session("2025-01-02", bars)

    res = run_orb(df, OrbParams(or_minutes=15, target_r=1.0), COSTS)
    t = trades_frame(res)
    assert len(t) == 1
    r = t.iloc[0]
    assert r["side"] == 1
    assert r["entry_px"] == pytest.approx(101.25)      # 101.00 trigger + 1 tick slip
    assert r["stop"] == pytest.approx(100.0)           # opposite OR extreme
    assert r["risk_pts"] == pytest.approx(1.25)
    assert r["target"] == pytest.approx(102.50)        # 101.25 + 1.0 * 1.25
    assert r["exit_reason"] == "target"
    assert r["exit_px"] == pytest.approx(102.25)       # 102.50 limit - 1 tick slip
    assert r["points"] == pytest.approx(1.00)          # 102.25 - 101.25
    assert r["gross_usd"] == pytest.approx(50.0)       # 1.00 * $50
    assert r["net_usd"] == pytest.approx(47.50)        # - $2.50 commission
    assert bool(r["entry_gapped"]) is False


def test_entry_gap_through_trigger_fills_at_bar_open_not_trigger():
    """Bar opens 102.00, a full point ABOVE the 101.00 trigger: a stop fills at the reopen."""
    bars = flat_or("2025-01-02")
    bars += [("09:45", 102.0, 102.5, 101.9, 102.4)]
    bars += tail_to_close(16, 102.4)
    df = session("2025-01-02", bars)

    honest = trades_frame(run_orb(df, OrbParams(or_minutes=15), COSTS, gap_aware=True)).iloc[0]
    fantasy = trades_frame(run_orb(df, OrbParams(or_minutes=15), COSTS, gap_aware=False)).iloc[0]

    assert honest["entry_px"] == pytest.approx(102.25)   # max(101.00, 102.00) + slip
    assert bool(honest["entry_gapped"]) is True
    assert fantasy["entry_px"] == pytest.approx(101.25)  # the un-gettable fill
    # The artifact is worth exactly one point = $50 on ES.
    assert honest["net_usd"] == pytest.approx(fantasy["net_usd"] - 50.0)


def test_stop_gap_through_level_fills_at_bar_open_not_stop():
    """After a clean entry, price gaps to 99.00 -- below the 100.00 stop. Fill is 99.00."""
    bars = flat_or("2025-01-02")
    bars += [("09:45", 100.5, 101.5, 100.4, 101.4)]
    bars += [("09:46", 99.0, 99.1, 98.9, 99.0)]
    bars += tail_to_close(17, 99.0)
    df = session("2025-01-02", bars)

    honest = trades_frame(run_orb(df, OrbParams(or_minutes=15), COSTS, gap_aware=True)).iloc[0]
    fantasy = trades_frame(run_orb(df, OrbParams(or_minutes=15), COSTS, gap_aware=False)).iloc[0]

    assert honest["exit_reason"] == "stop"
    assert honest["exit_px"] == pytest.approx(98.75)     # min(100.00, 99.00) - slip
    assert fantasy["exit_px"] == pytest.approx(99.75)    # 100.00 - slip, never available
    assert honest["net_usd"] == pytest.approx(fantasy["net_usd"] - 50.0)


def test_bar_spanning_stop_and_target_takes_the_stop():
    """One bar covers both 100.00 stop and 102.50 target; the pessimistic branch must win."""
    bars = flat_or("2025-01-02")
    bars += [("09:45", 100.5, 101.5, 100.4, 101.4)]
    bars += [("09:46", 101.4, 103.0, 99.5, 101.0)]
    bars += tail_to_close(17, 101.0)
    df = session("2025-01-02", bars)

    t = trades_frame(run_orb(df, OrbParams(or_minutes=15, target_r=1.0), COSTS)).iloc[0]
    assert t["exit_reason"] == "stop"
    assert t["net_usd"] < 0


def test_entry_bar_stop_hit_is_enforced_same_bar():
    """No protection-free window: the entry bar itself can stop the trade out."""
    bars = flat_or("2025-01-02")
    # Triggers long at 101.00, then collapses through the 100.00 stop inside the same bar.
    bars += [("09:45", 100.9, 101.4, 99.0, 99.2)]
    bars += tail_to_close(16, 99.2)
    df = session("2025-01-02", bars)

    t = trades_frame(run_orb(df, OrbParams(or_minutes=15, target_r=5.0), COSTS))
    assert len(t) == 1
    assert t.iloc[0]["exit_reason"] == "stop"
    assert t.iloc[0]["entry_ts"] == t.iloc[0]["exit_ts"]   # same bar in and out


def test_no_breakout_means_no_trade():
    bars = flat_or("2025-01-02")
    bars += tail_to_close(15, 100.5)          # never leaves the OR
    df = session("2025-01-02", bars)
    assert trades_frame(run_orb(df, OrbParams(or_minutes=15), COSTS)).empty


def test_breakout_after_cutoff_is_not_taken():
    bars = flat_or("2025-01-02")
    for m in range(9 * 60 + 45, 11 * 60 + 1):           # flat inside OR until 11:00
        bars.append((f"{m // 60:02d}:{m % 60:02d}", 100.5, 100.6, 100.4, 100.5))
    bars.append(("11:01", 100.5, 105.0, 100.4, 104.9))   # breakout one minute too late
    bars += tail_to_close(92, 104.9)
    df = session("2025-01-02", bars)
    assert trades_frame(run_orb(df, OrbParams(or_minutes=15, entry_cutoff=time(11, 0)), COSTS)).empty


def test_time_exit_uses_close_of_time_exit_bar():
    bars = flat_or("2025-01-02")
    bars += [("09:45", 100.5, 101.5, 100.4, 101.4)]
    bars += tail_to_close(16, 101.4)[:-1]
    bars += [("15:59", 101.4, 101.4, 101.4, 103.0)]      # distinctive close
    df = session("2025-01-02", bars)

    t = trades_frame(run_orb(df, OrbParams(or_minutes=15, target_r=None), COSTS)).iloc[0]
    assert t["exit_reason"] == "time"
    assert t["exit_px"] == pytest.approx(103.0 - SLIP)
    assert t["exit_ts"].strftime("%H:%M") == "15:59"


def test_short_side_mirrors_long_exactly():
    """Mirror of the clean-long case reflected about 100.5."""
    bars = flat_or("2025-01-02")
    bars += [("09:45", 100.5, 100.6, 99.5, 99.6)]        # breaks 100.00 low
    bars += [("09:46", 99.6, 99.7, 98.4, 98.5)]          # runs to the 1R target
    bars += tail_to_close(17, 98.5)
    df = session("2025-01-02", bars)

    t = trades_frame(run_orb(df, OrbParams(or_minutes=15, target_r=1.0), COSTS)).iloc[0]
    assert t["side"] == -1
    assert t["entry_px"] == pytest.approx(99.75)         # 100.00 trigger - 1 tick slip
    assert t["stop"] == pytest.approx(101.0)             # opposite OR extreme
    assert t["risk_pts"] == pytest.approx(1.25)
    assert t["target"] == pytest.approx(98.50)           # 99.75 - 1.25
    assert t["exit_reason"] == "target"
    assert t["points"] == pytest.approx(1.00)            # (99.75 - 98.75)
    assert t["net_usd"] == pytest.approx(47.50)


def test_one_trade_per_session_by_default():
    bars = flat_or("2025-01-02")
    bars += [("09:45", 100.5, 101.5, 100.4, 101.4)]      # long entry
    bars += [("09:46", 101.4, 101.5, 99.5, 99.6)]        # stopped out
    bars += [("09:47", 99.6, 99.7, 98.0, 98.1)]          # would re-trigger short
    bars += tail_to_close(18, 98.1)
    df = session("2025-01-02", bars)

    assert len(trades_frame(run_orb(df, OrbParams(or_minutes=15), COSTS))) == 1
    two = trades_frame(run_orb(df, OrbParams(or_minutes=15, allow_reentry=True), COSTS))
    assert len(two) == 2


def test_or_window_length_changes_the_levels():
    """A 30-minute OR must see the wider range built between 09:45 and 10:00."""
    bars = flat_or("2025-01-02")
    bars += [("09:45", 100.5, 101.5, 100.4, 101.0)]      # extends the 30m OR high to 101.5
    for m in range(9 * 60 + 46, 10 * 60):
        bars.append((f"{m // 60:02d}:{m % 60:02d}", 101.0, 101.0, 101.0, 101.0))
    bars += [("10:00", 101.0, 101.2, 100.9, 101.1)]      # would break a 15m OR, not a 30m OR
    bars += tail_to_close(31, 101.1)
    df = session("2025-01-02", bars)

    t15 = trades_frame(run_orb(df, OrbParams(or_minutes=15), COSTS))
    t30 = trades_frame(run_orb(df, OrbParams(or_minutes=30), COSTS))
    assert len(t15) == 1 and t15.iloc[0]["or_high"] == pytest.approx(101.0)
    assert t30.empty          # 101.2 never exceeds the 101.5 thirty-minute high


def test_fade_is_the_matched_mirror_of_follow():
    """The placebo: same bar, same price level, opposite direction, identical geometry.

    Uses stop_mode='frac' so both sides risk exactly one OR width -- otherwise 'opposite'
    would hand the two directions different risk and the comparison would not be matched.
    """
    bars = flat_or("2025-01-02")
    bars += [("09:45", 100.5, 101.5, 100.4, 101.4)]     # breaks the 101.00 high
    bars += tail_to_close(16, 101.4)
    df = session("2025-01-02", bars)

    kw = dict(or_minutes=15, target_r=None, stop_mode="frac", stop_frac=1.0)
    follow = trades_frame(run_orb(df, OrbParams(**kw), COSTS)).iloc[0]
    fade = trades_frame(run_orb(df, OrbParams(fade=True, **kw), COSTS)).iloc[0]

    # Same bar, same trigger level, opposite sides.
    assert follow["entry_ts"] == fade["entry_ts"]
    assert follow["raw_trigger"] == pytest.approx(fade["raw_trigger"]) == pytest.approx(101.0)
    assert follow["side"] == 1 and fade["side"] == -1
    # Matched risk: one OR width each.
    assert follow["risk_pts"] == pytest.approx(1.0)
    assert fade["risk_pts"] == pytest.approx(1.0)
    # Entry prices differ only by the slippage sign (101.00 +/- one tick).
    assert follow["entry_px"] == pytest.approx(101.25)
    assert fade["entry_px"] == pytest.approx(100.75)


def test_fade_loses_when_follow_wins_on_a_trend_day():
    bars = flat_or("2025-01-02")
    bars += [("09:45", 100.5, 101.5, 100.4, 101.4)]
    bars += tail_to_close(16, 108.0)                    # strong trend up into the close
    df = session("2025-01-02", bars)
    kw = dict(or_minutes=15, target_r=None, stop_mode="frac", stop_frac=1.0)
    follow = trades_frame(run_orb(df, OrbParams(**kw), COSTS)).iloc[0]
    fade = trades_frame(run_orb(df, OrbParams(fade=True, **kw), COSTS)).iloc[0]
    assert follow["net_usd"] > 0
    assert fade["exit_reason"] == "stop"                # fade is stopped out by the trend
    assert fade["net_usd"] < 0
