# tests/test_intrabar.py
"""
Tests for sub-bar resolution (Phase 5 of the instrument-metadata rewrite, #229).

  TestResolveStopFill      — gap-aware stop fills, long & short, untouched
  TestOrderPrecedence      — stop-vs-target precedence within a session
  TestSessionBars          — day slicing (tz-aware/naive)
  TestEngineIntegration    — engine fills a gap-through-stop at the sub-bar open
                             when enabled, and at the stop level when off (default)
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers import intrabar
from helpers.portfolio_simulations import run_portfolio_simulation


def _bars(rows, day="2023-01-04"):
    """rows: list of (minute, open, high, low, close)."""
    idx = [pd.Timestamp(f"{day} {m}") for m, *_ in rows]
    data = {"Open": [r[1] for r in rows], "High": [r[2] for r in rows],
            "Low": [r[3] for r in rows], "Close": [r[4] for r in rows]}
    return pd.DataFrame(data, index=pd.DatetimeIndex(idx))


class TestResolveStopFill:
    def test_long_touched_intrabar_fills_at_stop(self):
        bars = _bars([("09:30", 100, 101, 99.5, 100), ("09:31", 100, 100, 94, 95)])
        fill, ts = intrabar.resolve_stop_fill(bars, 95.0, side="long")
        assert fill == 95.0                       # low pierced the stop -> fill at stop
        assert ts == pd.Timestamp("2023-01-04 09:31")

    def test_long_gap_through_stop_fills_at_open(self):
        bars = _bars([("09:30", 90, 91, 88, 89)])  # opens below the 95 stop
        fill, ts = intrabar.resolve_stop_fill(bars, 95.0, side="long")
        assert fill == 90.0                        # worse-than-stop gap fill

    def test_long_never_touched(self):
        bars = _bars([("09:30", 100, 101, 99, 100), ("09:31", 100, 102, 99.5, 101)])
        fill, ts = intrabar.resolve_stop_fill(bars, 95.0, side="long")
        assert fill is None and ts is None

    def test_short_gap_through_stop_fills_at_open(self):
        bars = _bars([("09:30", 110, 112, 109, 111)])  # opens above the 105 stop
        fill, _ = intrabar.resolve_stop_fill(bars, 105.0, side="short")
        assert fill == 110.0

    def test_empty_returns_none(self):
        assert intrabar.resolve_stop_fill(None, 95.0) == (None, None)


class TestOrderPrecedence:
    def test_stop_first_when_both_in_same_bar(self):
        bars = _bars([("09:30", 100, 106, 94, 100)])  # spans both stop(95) and target(105)
        which, fill, _ = intrabar.resolve_order_precedence(bars, 95.0, 105.0, side="long")
        assert which == "stop" and fill == 95.0

    def test_target_when_only_target(self):
        bars = _bars([("09:30", 100, 106, 99, 105)])
        which, fill, _ = intrabar.resolve_order_precedence(bars, 90.0, 105.0, side="long")
        assert which == "target" and fill == 105.0

    def test_none_when_neither(self):
        bars = _bars([("09:30", 100, 101, 99, 100)])
        which, _, _ = intrabar.resolve_order_precedence(bars, 90.0, 110.0, side="long")
        assert which is None


class TestSessionBars:
    def test_slices_correct_day(self):
        df = pd.concat([_bars([("09:30", 1, 1, 1, 1)], day="2023-01-04"),
                        _bars([("09:30", 2, 2, 2, 2)], day="2023-01-05")])
        day = intrabar.session_bars(df, pd.Timestamp("2023-01-05"))
        assert day is not None and len(day) == 1 and day["Open"].iloc[0] == 2

    def test_missing_day_returns_none(self):
        df = _bars([("09:30", 1, 1, 1, 1)], day="2023-01-04")
        assert intrabar.session_bars(df, pd.Timestamp("2023-01-06")) is None


class TestEngineIntegration:
    @staticmethod
    def _daily():
        # bar3 gaps down through the 5% stop.
        closes = [100, 100, 89, 88]
        idx = pd.bdate_range("2023-01-02", periods=4)
        idx.name = "Datetime"
        df = pd.DataFrame({
            "Open": [100, 100, 90, 88], "High": [101, 101, 91, 89],
            "Low": [99, 99, 88, 87], "Close": closes, "Volume": [1e6] * 4,
        }, index=idx)
        return df

    @staticmethod
    def _run(intrabar_on):
        from unittest.mock import patch
        df = TestEngineIntegration._daily()
        sig = pd.Series([0, 1, 0, 0], index=df.index)  # enter bar1
        # intraday for the gap day: opens at 90, well below the ~95 stop.
        intraday = _bars([("09:30", 90, 90.5, 88, 89)], day=str(df.index[2].date()))
        cfg = {
            "slippage_pct": 0.0005, "commission_per_share": 0.002, "execution_time": "close",
            "risk_free_rate": 0.05, "htb_rate_annual": 0.0, "volume_impact_coeff": 0.0,
            "max_pct_adv": 0.0, "position_sizing_method": "fixed", "target_risk_per_trade": 0.02,
            "max_portfolio_heat": 1.0, "entry_priority": "alphabetical",
            "exclude_open_positions": False, "include_delisted": False,
            "intrabar_resolution": intrabar_on,
            "instruments": {"default_asset_class": "equity", "overrides": {}},
        }
        with patch.dict("config.CONFIG", cfg, clear=False):
            return run_portfolio_simulation(
                portfolio_data={"AAA": df}, signals={"AAA": sig},
                initial_capital=100_000.0, allocation_pct=0.10,
                spy_df=None, vix_df=None, tnx_df=None,
                stop_config={"type": "percentage", "value": 0.05},
                intrabar_data={"AAA": intraday})

    def test_gap_fills_worse_than_stop_when_enabled(self):
        res = self._run(intrabar_on=True)
        t = res["trade_log"][0]
        assert t["ExitReason"].startswith("Stop Loss")
        # Gap open (90) minus sell slippage — strictly worse than the ~95 stop fill.
        assert t["ExitPrice"] == pytest.approx(90.0 * (1 - 0.0005), abs=1e-6)

    def test_default_off_fills_at_stop_level(self):
        res = self._run(intrabar_on=False)
        t = res["trade_log"][0]
        # This is an equity instrument (default_asset_class: "equity"), so the
        # stop level is anchored to the SLIPPED entry_price -- the actual fill --
        # not the raw pre-slippage price. Raw-price anchoring is reserved for
        # margined (futures) instruments only (#238 review item #1: the
        # margin_mode gate in portfolio_simulations.py's stop-setting block).
        stop_level = t["EntryPrice"] * (1 - 0.05)
        assert t["ExitPrice"] == pytest.approx(stop_level * (1 - 0.0005), abs=1e-6)
        # And the enabled fill is strictly worse than the disabled one.
        assert self._run(True)["trade_log"][0]["ExitPrice"] < t["ExitPrice"]
