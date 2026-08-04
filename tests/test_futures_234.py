# tests/test_futures_234.py
"""
Tests for the #234 futures gaps (v1.11.0):
  1. trailing_atr stop — arm-on-target, ATR locked at breakout, breakeven floor
  2. ATR stop point_cap — min(atr*mult, cap)
  3. maintenance margin / margin call — forced futures liquidation
  4. dynamic Polygon futures resolution — 5m/15m/45m/2h native
  5. rolls_spanned — detect a hold window crossing a roll
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers import instruments as I
from helpers.portfolio_simulations import run_portfolio_simulation, _update_trailing_atr_stop
from helpers import continuous_contract as cc
from services import futures_service as fs

_CFG = {
    "slippage_pct": 0.0, "commission_per_share": 0.0, "execution_time": "close",
    "risk_free_rate": 0.05, "htb_rate_annual": 0.0, "volume_impact_coeff": 0.0,
    "max_pct_adv": 0.0, "position_sizing_method": "fixed", "target_risk_per_trade": 0.02,
    "max_portfolio_heat": 1.0, "entry_priority": "alphabetical",
    "exclude_open_positions": False, "include_delisted": False, "maintenance_margin_pct": 0.0,
    "instruments": {"default_asset_class": "equity",
                    "futures_initial_margin_pct": 0.10,
                    "futures_commission_per_contract": 0.0,
                    "futures_slippage_ticks": 0.0, "overrides": {}},
}


def _df(rows, start="2023-01-02"):
    """rows: list of (open, high, low, close, atr)."""
    idx = pd.bdate_range(start=start, periods=len(rows))
    idx.name = "Datetime"
    return pd.DataFrame({
        "Open": [r[0] for r in rows], "High": [r[1] for r in rows],
        "Low": [r[2] for r in rows], "Close": [r[3] for r in rows],
        "Volume": [1e6] * len(rows), "ATR_14": [r[4] for r in rows],
    }, index=idx)


def _sig(df, pairs):
    s = pd.Series(0, index=df.index, dtype=int)
    for i, v in pairs.items():
        s.iloc[i] = v
    return s


def _run(pdata, signals, stop_config, cfg_over=None, cap=100_000.0, alloc=1.0):
    from unittest.mock import patch
    with patch.dict("config.CONFIG", {**_CFG, **(cfg_over or {})}, clear=False):
        return run_portfolio_simulation(
            portfolio_data=pdata, signals=signals, initial_capital=cap, allocation_pct=alloc,
            spy_df=None, vix_df=None, tnx_df=None, stop_config=stop_config)


# ---------------------------------------------------------------------------
# 1. trailing_atr — direct helper (precise mechanic)
# ---------------------------------------------------------------------------
class TestTrailingAtrHelper:
    def _bar(self, high, close):
        df = pd.DataFrame({"High": [high], "Close": [close], "Low": [close], "Open": [close],
                           "ATR_14": [99.0]},  # live ATR huge -> must be IGNORED
                          index=pd.to_datetime(["2023-01-05"]))
        return df, df.index[0]

    def test_arms_on_target_and_uses_locked_atr(self):
        df, d = self._bar(high=103, close=103)
        pos = {"entry_price": 100.0, "trail_armed": False, "trail_target": 102.0,
               "atr_locked": 2.0, "stop_loss_level": 98.0}
        _update_trailing_atr_stop(pos, df, d, {"trail_mult": 0.5, "floor": "breakeven"})
        assert pos["trail_armed"] is True
        # 103 - 0.5*2(locked) = 102 ; live ATR 99 would give 53.5 -> proves lock. floor(100) ok.
        assert pos["stop_loss_level"] == pytest.approx(102.0)

    def test_not_armed_before_target(self):
        df, d = self._bar(high=101, close=101)   # below target 102
        pos = {"entry_price": 100.0, "trail_armed": False, "trail_target": 102.0,
               "atr_locked": 2.0, "stop_loss_level": 98.0}
        _update_trailing_atr_stop(pos, df, d, {"trail_mult": 0.5, "floor": "breakeven"})
        assert pos["trail_armed"] is False
        assert pos["stop_loss_level"] == 98.0     # untouched

    def test_breakeven_floor_clamps(self):
        # Trail rides HIGH now, so arming (high>=target) always keeps candidate>entry.
        # Pre-arm and use a low High so the High-based candidate is still below entry.
        df, d = self._bar(high=100.5, close=100.4)  # candidate = 100.5 - 1 = 99.5 < entry
        pos = {"entry_price": 100.0, "trail_armed": True, "trail_target": 102.0,
               "atr_locked": 2.0, "stop_loss_level": 98.0}
        _update_trailing_atr_stop(pos, df, d, {"trail_mult": 0.5, "floor": "breakeven"})
        assert pos["stop_loss_level"] == pytest.approx(100.0)   # clamped to entry, not 99.5

    def test_ratchet_never_loosens(self):
        df, d = self._bar(high=101, close=100.5)  # candidate = 101 - 1 = 100 < prev 101.5
        pos = {"entry_price": 100.0, "trail_armed": True, "trail_target": 102.0,
               "atr_locked": 2.0, "stop_loss_level": 101.5}  # already higher
        _update_trailing_atr_stop(pos, df, d, {"trail_mult": 0.5, "floor": "breakeven"})
        assert pos["stop_loss_level"] == 101.5    # never moves down

    def test_numeric_floor_clamps(self):
        # A numeric floor (not "breakeven") clamps the trail candidate to that price.
        # Pre-armed; candidate = 100.5 - 0.5*2 = 99.5 ; floor 99.8 -> clamped up to 99.8.
        df, d = self._bar(high=100.5, close=100.4)
        pos = {"entry_price": 100.0, "trail_armed": True, "trail_target": 102.0,
               "atr_locked": 2.0, "stop_loss_level": 98.0}
        _update_trailing_atr_stop(pos, df, d, {"trail_mult": 0.5, "floor": 99.8})
        assert pos["stop_loss_level"] == pytest.approx(99.8)


class TestTrailingAtrEngine:
    def test_trailing_exit_reason_and_target_derivation(self):
        # ATR=2 locked; stop_mult=1 -> stop 2 below; t1_mult=1 -> target = eff_stop_dist = 2 above.
        rows = [(100, 100, 100, 100, 2.0),   # bar0 (signal-day source for locked ATR)
                (100, 100, 100, 100, 2.0),   # bar1 enter @100 (stop 98, target 102)
                (100, 103, 100, 102, 2.0),   # bar2 High 103 >= target 102 -> arm; trail=103(High)-2=101
                (100, 100, 99.5, 99.5, 2.0)]  # bar3 Low 99.5 <= 101 stop -> exit @101 (>= breakeven)
        df = _df(rows)
        res = _run({"AAA": df}, {"AAA": _sig(df, {1: 1})},
                   {"type": "trailing_atr", "stop_mult": 1.0, "trail_mult": 1.0,
                    "t1_mult": 1.0, "floor": "breakeven"})
        assert res is not None and res["trade_log"]
        t = res["trade_log"][0]
        assert t["ExitReason"] == "Stop Loss (trailing_atr)"
        assert t["ExitPrice"] >= t["EntryPrice"]    # breakeven floor held -> not a loss

    def test_atr_locked_at_breakout_bar_not_fill_bar(self):
        # Shardul's clarification: a = atr[breakout_i] = the bar BEFORE the fill bar
        # (the signal/confirmation candle), not the fill bar. execution_time="open" so
        # signal on bar1 -> fill at bar2 open; ATR must come from bar1 (=2), not bar2 (=99).
        rows = [(100, 100, 100, 100, 5.0),    # bar0
                (100, 100, 100, 100, 2.0),    # bar1 signal (breakout_i) -> ATR 2
                (100, 100, 100, 100, 99.0),   # bar2 fill @open 100 -> ATR 99 must be IGNORED
                (100, 100, 97, 97, 99.0)]     # bar3 Low 97 <= stop 98 -> stop out
        df = _df(rows)
        res = _run({"AAA": df}, {"AAA": _sig(df, {1: 1})},
                   {"type": "trailing_atr", "stop_mult": 1.0, "trail_mult": 0.5,
                    "t1_mult": 1.0, "floor": "breakeven"},
                   cfg_over={"execution_time": "open"})
        assert res is not None and res["trade_log"]
        t = res["trade_log"][0]
        # InitialRisk = eff_stop_dist = stop_mult*atr_locked = 1*2 = 2 (not 99).
        assert t["InitialRisk"] == pytest.approx(2.0)

    def test_target_and_stop_derive_off_capped_distance(self):
        # point_cap propagates into BOTH the initial stop AND the arm target:
        #   atr=2, stop_mult=1 -> uncapped eff_stop_dist=2, but point_cap=1 -> eff=1
        #   stop = entry - 1 = 99 ;  target = entry + eff*(t1_mult/stop_mult) = 100 + 1 = 101
        # If the cap were ignored, eff=2 -> stop 98 and target 102. We arm at High 101
        # (< 102): reaching the target at 101 proves the target used the CAPPED distance;
        # InitialRisk == 1 proves the initial stop used the CAPPED distance.
        rows = [(100, 100, 100, 100, 2.0),    # bar0 signal-day source for locked ATR
                (100, 100, 100, 100, 2.0),    # bar1 enter @100 (stop 99, target 101)
                (100, 101, 100, 101, 2.0),    # bar2 High 101 >= capped target 101 -> arm;
                                              #   trail = 101 - 0.5*2 = 100, floored @entry -> 100
                (100, 100, 99.5, 99.5, 2.0)]  # bar3 Low 99.5 <= ratcheted stop 100 -> exit @100
        df = _df(rows)
        res = _run({"AAA": df}, {"AAA": _sig(df, {1: 1})},
                   {"type": "trailing_atr", "stop_mult": 1.0, "trail_mult": 0.5,
                    "t1_mult": 1.0, "point_cap": 1.0, "floor": "breakeven"})
        assert res is not None and res["trade_log"]
        t = res["trade_log"][0]
        assert t["InitialRisk"] == pytest.approx(1.0)   # capped eff_stop_dist, not 2
        assert t["ExitReason"] == "Stop Loss (trailing_atr)"
        # Armed at the capped target 101 (would NOT arm at 101 if target were 102),
        # then ratcheted to the breakeven floor 100.
        assert t["ExitPrice"] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 2. ATR point_cap
# ---------------------------------------------------------------------------
class TestPointCap:
    def test_helper_caps_distance(self):
        assert I.atr_stop_level(100.0, 10.0, 5.0, "long") == pytest.approx(50.0)          # 100-50
        assert I.atr_stop_level(100.0, 10.0, 5.0, "long", point_cap=20.0) == pytest.approx(80.0)  # cap 20
        assert I.atr_stop_level(100.0, 10.0, 5.0, "short", point_cap=20.0) == pytest.approx(120.0)

    def test_engine_initial_atr_stop_capped(self):
        # atr=10, mult=5 -> uncapped stop 50 below; cap 15 -> stop 15 below (entry-15).
        rows = [(100, 100, 100, 100, 10.0), (100, 100, 100, 100, 10.0),
                (100, 100, 80, 88, 10.0)]   # bar2 Low 80 triggers a capped stop @85, not 50-wide @50
        df = _df(rows)
        res = _run({"AAA": df}, {"AAA": _sig(df, {1: 1})},
                   {"type": "atr", "multiplier": 5.0, "point_cap": 15.0})
        t = res["trade_log"][0]
        assert t["ExitReason"] == "Stop Loss (atr)"
        assert t["ExitPrice"] == pytest.approx(85.0)   # entry100 - cap15

    def test_engine_trailing_atr_stop_capped(self):
        # The 'atr' type trailing-update must honour point_cap too:
        #   entry 100, initial capped stop 85 (100-15). On bar2 close 120:
        #   capped trail = 120-15 = 105 ; uncapped would be 120-50 = 70 (< 85, no ratchet).
        #   So a ratchet to 105 proves the cap propagated into the trailing update.
        rows = [(100, 100, 100, 100, 10.0),   # bar0
                (100, 100, 100, 100, 10.0),   # bar1 enter @100 (initial capped stop 85)
                (100, 120, 100, 120, 10.0),   # bar2 close 120 -> capped trail 105 (uncapped 70)
                (100, 106, 104, 104, 10.0)]   # bar3 Low 104 <= 105 -> stop out @105
        df = _df(rows)
        res = _run({"AAA": df}, {"AAA": _sig(df, {1: 1})},
                   {"type": "atr", "multiplier": 5.0, "point_cap": 15.0})
        assert res is not None and res["trade_log"]
        t = res["trade_log"][0]
        assert t["ExitReason"] == "Stop Loss (atr)"
        assert t["ExitPrice"] == pytest.approx(105.0)  # ratcheted to capped trail, not 85


# ---------------------------------------------------------------------------
# 3. Maintenance margin / margin call
# ---------------------------------------------------------------------------
class TestMarginCall:
    def test_force_liquidation_on_breach(self):
        # MES $5/pt, initial 10%, maintenance 5% -> breach when close < entry*0.95.
        rows = [(4000, 4000, 4000, 4000, 5.0), (4000, 4000, 4000, 4000, 5.0),
                (4000, 4000, 3600, 3600, 5.0)]  # -10% drop -> margin call
        df = _df(rows)
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1})},
                   {"type": "none"}, cfg_over={"maintenance_margin_pct": 0.05})
        assert res is not None and res["trade_log"]
        assert res["trade_log"][0]["ExitReason"] == "Margin Call"

    def test_disabled_by_default_no_call(self):
        rows = [(4000, 4000, 4000, 4000, 5.0), (4000, 4000, 4000, 4000, 5.0),
                (4000, 4000, 3600, 3600, 5.0)]
        df = _df(rows)
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1})}, {"type": "none"})  # mm=0.0
        reasons = [t["ExitReason"] for t in res["trade_log"]]
        assert "Margin Call" not in reasons

    def test_equity_never_margin_called_even_with_mm_set(self):
        # The margin-call block is guarded by margin_mode == INITIAL_MARGIN. An equity
        # (cash_full) symbol with maintenance_margin_pct set and a huge drawdown must
        # NEVER margin-call — only futures do. Regression pin for the equity guard.
        rows = [(100, 100, 100, 100, 5.0), (100, 100, 100, 100, 5.0),
                (100, 100, 10, 10, 5.0)]  # -90% drop
        df = _df(rows)
        res = _run({"AAA": df}, {"AAA": _sig(df, {1: 1})},
                   {"type": "none"}, cfg_over={"maintenance_margin_pct": 0.05})
        reasons = [t["ExitReason"] for t in res["trade_log"]]
        assert "Margin Call" not in reasons


# ---------------------------------------------------------------------------
# 4. Dynamic futures resolution
# ---------------------------------------------------------------------------
class TestDynamicResolution:
    @pytest.mark.parametrize("tf,mult,expected", [
        ("D", 1, "1session"), ("D", 7, "1session"),
        ("MIN", 1, "1min"), ("MIN", 5, "5min"), ("MIN", 15, "15min"), ("MIN", 45, "45min"),
        ("H", 1, "1hour"), ("H", 2, "2hour"), ("H", 4, "4hour"),
    ])
    def test_resolution(self, tf, mult, expected):
        assert fs._resolution({"timeframe": tf, "timeframe_multiplier": mult}) == expected


# ---------------------------------------------------------------------------
# 5. rolls_spanned
# ---------------------------------------------------------------------------
class TestRollsSpanned:
    def test_detects_rolls_inside_window(self):
        rolls = ["2023-03-17", "2023-06-15", "2023-09-15"]
        spanned = cc.rolls_spanned("2023-05-01", "2023-07-01", rolls)
        assert [str(s.date()) for s in spanned] == ["2023-06-15"]

    def test_short_hold_spans_nothing(self):
        rolls = ["2023-03-17", "2023-06-15"]
        assert cc.rolls_spanned("2023-06-16", "2023-06-20", rolls) == []
