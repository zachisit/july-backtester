# tests/test_stop_gap_fill.py
"""
Issue #425: coarse (non-intrabar) stop fills must be gap-aware.

  TestCoarseStopFillHelper — pure helper / _prearm_decision behaviour
  TestEngineGapFill        — engine long/short, no-gap, NaN Open, "level" legacy mode
"""

import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.portfolio_simulations import (  # noqa: E402
    _coarse_stop_fill, _prearm_decision, run_portfolio_simulation,
)

SLIP = 0.0005
BASE_CFG = {
    "slippage_pct": SLIP, "commission_per_share": 0.0, "execution_time": "close",
    "risk_free_rate": 0.05, "htb_rate_annual": 0.0, "volume_impact_coeff": 0.0,
    "max_pct_adv": 0.0, "position_sizing_method": "fixed", "target_risk_per_trade": 0.02,
    "max_portfolio_heat": 1.0, "entry_priority": "alphabetical",
    "exclude_open_positions": False, "include_delisted": False,
    "intrabar_resolution": False,
    "instruments": {"default_asset_class": "equity", "overrides": {}},
}


class TestCoarseStopFillHelper:
    def test_long_gap_fills_at_open(self):
        assert _coarse_stop_fill(95.0, 80.0, "long", "open") == 80.0

    def test_long_no_gap_fills_at_stop(self):
        assert _coarse_stop_fill(95.0, 99.0, "long", "open") == 95.0

    def test_short_gap_fills_at_open(self):
        assert _coarse_stop_fill(105.0, 120.0, "short", "open") == 120.0

    def test_short_no_gap_fills_at_stop(self):
        assert _coarse_stop_fill(105.0, 101.0, "short", "open") == 105.0

    def test_nan_or_none_open_falls_back(self):
        assert _coarse_stop_fill(95.0, np.nan, "long", "open") == 95.0
        assert _coarse_stop_fill(95.0, None, "long", "open") == 95.0

    def test_level_mode_is_legacy(self):
        assert _coarse_stop_fill(95.0, 80.0, "long", "level") == 95.0
        assert _coarse_stop_fill(105.0, 120.0, "short", "level") == 105.0

    def test_prearm_stop_only_gap(self):
        d = _prearm_decision(high=90, low=78, stop_level=95.0, target=130.0,
                             window_bars=None, side="long", bar_open=80.0, gap_mode="open")
        assert d == ("stop", 80.0)
        d = _prearm_decision(high=90, low=78, stop_level=95.0, target=130.0,
                             window_bars=None, side="long", bar_open=80.0, gap_mode="level")
        assert d == ("stop", 95.0)

    def test_prearm_short_stop_only_gap(self):
        d = _prearm_decision(high=125, low=110, stop_level=105.0, target=70.0,
                             window_bars=None, side="short", bar_open=120.0, gap_mode="open")
        assert d == ("stop", 120.0)


def _frame(opens, highs, lows, closes):
    idx = pd.bdate_range("2024-01-02", periods=len(closes))
    idx.name = "Datetime"
    return pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes,
                         "Volume": [1e6] * len(closes)}, index=idx)


def _run(df, signal_vals, stop_cfg, cfg_over=None):
    sig = pd.Series(signal_vals, index=df.index)
    cfg = {**BASE_CFG, **(cfg_over or {})}
    with patch.dict("config.CONFIG", cfg, clear=False):
        return run_portfolio_simulation(
            portfolio_data={"AAA": df}, signals={"AAA": sig},
            initial_capital=100_000.0, allocation_pct=0.10,
            spy_df=None, vix_df=None, tnx_df=None, stop_config=stop_cfg)["trade_log"]


PCT = {"type": "percentage", "value": 0.05}


class TestEngineGapFill:
    # Enter at bar1 close (100). Stop = entry*(0.95) ~ 94.9. Bar2 is the stop bar.
    def _long_df(self, bar2):
        o, h, l, c = bar2
        return _frame([100, 100, o], [101, 101, h], [99, 99, l], [100, 100, c])

    def test_long_gap_down_fills_at_open(self):
        t = _run(self._long_df((80, 82, 78, 81)), [0, 1, 0], PCT)[0]
        assert t["ExitReason"].startswith("Stop Loss")
        assert t["ExitPrice"] == pytest.approx(80.0 * (1 - SLIP), abs=1e-6)

    def test_long_trade_through_without_gap_fills_at_stop(self):
        # Opens above the stop, trades through it.
        t = _run(self._long_df((99, 100, 90, 92)), [0, 1, 0], PCT)[0]
        assert t["ExitReason"].startswith("Stop Loss")
        stop = 100 * (1 + SLIP) * 0.95
        assert t["ExitPrice"] == pytest.approx(stop * (1 - SLIP), abs=1e-6)

    def test_long_nan_open_falls_back_to_stop(self):
        t = _run(self._long_df((np.nan, 82, 78, 81)), [0, 1, 0], PCT)[0]
        stop = 100 * (1 + SLIP) * 0.95
        assert t["ExitPrice"] == pytest.approx(stop * (1 - SLIP), abs=1e-6)

    def test_long_level_mode_reproduces_legacy(self):
        t = _run(self._long_df((80, 82, 78, 81)), [0, 1, 0], PCT,
                 {"stop_gap_fill": "level"})[0]
        stop = 100 * (1 + SLIP) * 0.95
        assert t["ExitPrice"] == pytest.approx(stop * (1 - SLIP), abs=1e-6)

    def test_short_gap_up_covers_at_open(self):
        df = _frame([100, 100, 120], [101, 101, 125], [99, 99, 118], [100, 100, 122])
        t = _run(df, [0, -2, 0], PCT)[0]
        assert t["ExitReason"] == "Stop Loss (percentage)" or t["ExitReason"].startswith("Stop Loss")
        assert t["ExitPrice"] == pytest.approx(120.0 * (1 + SLIP), abs=1e-6)

    def test_short_trade_through_without_gap_covers_at_stop(self):
        df = _frame([100, 100, 101], [101, 101, 115], [99, 99, 100], [100, 100, 110])
        t = _run(df, [0, -2, 0], PCT)[0]
        stop = 100 * 1.05  # short stops anchor to the raw entry price
        assert t["ExitPrice"] == pytest.approx(stop * (1 + SLIP), abs=1e-6)

    def test_short_level_mode_reproduces_legacy(self):
        df = _frame([100, 100, 120], [101, 101, 125], [99, 99, 118], [100, 100, 122])
        t = _run(df, [0, -2, 0], PCT, {"stop_gap_fill": "level"})[0]
        stop = 100 * 1.05  # short stops anchor to the raw entry price
        assert t["ExitPrice"] == pytest.approx(stop * (1 + SLIP), abs=1e-6)
