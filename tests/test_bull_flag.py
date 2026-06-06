# tests/test_bull_flag.py
"""Tests for the Bull Flag Breakout strategy plugin.

Uses synthetic daily OHLCV data with a manufactured base -> pole -> flag ->
breakout sequence so every rule (entry trigger, volume gates, depth gate,
target exit, time stop) can be asserted deterministically.
"""

import numpy as np
import pandas as pd
import pytest

from custom_strategies.bull_flag import bull_flag_breakout

# Default params mirrored from the @register_strategy registration (daily).
PARAMS = dict(
    pole_min_gain=0.18,
    pole_max_bars=12,
    flag_min_bars=3,
    flag_max_bars=15,
    flag_max_retrace=0.40,
    flag_vol_contraction=0.75,
    breakout_vol_mult=1.5,
    vol_ma_bars=20,
    trend_ma_bars=50,
    time_stop_bars=20,
    min_price=5.0,
    min_dollar_volume=5_000_000.0,
)

BASE_BARS = 60
POLE_BARS = 8
FLAG_BARS = 6
# Bar index of the breakout bar in the synthetic series:
BREAKOUT_POS = BASE_BARS + POLE_BARS + FLAG_BARS  # = 74


def make_df(
    breakout_close=126.0,
    breakout_volume=3_000_000,
    flag_drift_to=121.0,
    after="target",
):
    """Build a synthetic series: flat base -> +25% pole -> shallow flag ->
    breakout bar -> aftermath.

    after="target"   : price climbs to ~155 so the measured-move target hits.
    after="sideways" : price chops at ~130 so only the time stop can fire.
    """
    closes, volumes = [], []

    closes += [100.0] * BASE_BARS                       # base
    volumes += [1_000_000] * BASE_BARS

    closes += list(np.linspace(103, 125, POLE_BARS))    # pole: ~+25%
    volumes += [2_000_000] * POLE_BARS

    closes += list(np.linspace(124, flag_drift_to, FLAG_BARS))  # flag
    volumes += [600_000] * FLAG_BARS

    closes.append(breakout_close)                       # breakout bar
    volumes.append(breakout_volume)

    if after == "target":
        closes += list(np.linspace(128, 155, 12))
        volumes += [1_500_000] * 12
    else:
        closes += [130.0] * 30
        volumes += [1_500_000] * 30

    closes = np.array(closes, dtype=float)
    volumes = np.array(volumes, dtype=float)
    n = len(closes)

    df = pd.DataFrame(
        {
            "Open": closes,  # opens are irrelevant to the logic
            "High": closes + 0.5,
            "Low": closes - 0.5,
            "Close": closes,
            "Volume": volumes,
        },
        index=pd.bdate_range("2024-01-02", periods=n),
    )
    return df


def test_enters_on_valid_breakout():
    df = bull_flag_breakout(make_df(), **PARAMS)
    assert df["Signal"].iloc[BREAKOUT_POS] == 1, (
        "Strategy should be long on the breakout bar"
    )
    # No position before the breakout bar.
    assert (df["Signal"].iloc[:BREAKOUT_POS] == 1).sum() == 0


def test_no_entry_without_breakout_volume():
    # Same structure, but the breakout bar prints weak volume.
    df = bull_flag_breakout(make_df(breakout_volume=1_000_000), **PARAMS)
    assert df["Signal"].iloc[BREAKOUT_POS] != 1
    assert (df["Signal"] == 1).sum() == 0


def test_no_entry_when_flag_too_deep():
    # Flag retraces far more than 40% of the pole — not a flag anymore.
    df = bull_flag_breakout(make_df(flag_drift_to=108.0), **PARAMS)
    assert (df["Signal"] == 1).sum() == 0


def test_exits_at_measured_move_target():
    df = bull_flag_breakout(make_df(after="target"), **PARAMS)
    sig = df["Signal"].to_numpy()
    assert sig[BREAKOUT_POS] == 1
    exit_positions = np.where(sig == -1)[0]
    assert len(exit_positions) > 0, "Target should trigger an exit"
    first_exit = exit_positions[0]
    # Exit must come after entry and before the very end of the data.
    assert BREAKOUT_POS < first_exit < len(df) - 1
    # At the first exit bar the close should be at/above the measured-move
    # target (flag high + pole height), i.e. exit was the target, not time.
    assert first_exit - BREAKOUT_POS < PARAMS["time_stop_bars"]


def test_time_stop_caps_holding_period():
    df = bull_flag_breakout(make_df(after="sideways"), **PARAMS)
    sig = df["Signal"].to_numpy()
    assert sig[BREAKOUT_POS] == 1
    exit_positions = np.where(sig == -1)[0]
    assert len(exit_positions) > 0, "Time stop should force an exit"
    first_exit = exit_positions[0]
    assert first_exit - BREAKOUT_POS <= PARAMS["time_stop_bars"]


def test_registry_registration():
    from helpers.registry import REGISTRY

    assert "Bull Flag Breakout" in REGISTRY
    entry = REGISTRY["Bull Flag Breakout"]
    assert entry["logic"] is bull_flag_breakout
    assert entry["params"]["flag_max_bars"] == 15
