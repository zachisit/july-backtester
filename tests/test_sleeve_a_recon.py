# tests/test_sleeve_a_recon.py
"""
Reconciliation tests for @shardul0701's #234 empirical review of v1.11.0.

Includes his two drop-in reproductions (both FAILED on 39f1865, must PASS now):
  - trailing_atr trails off the running-max HIGH, not the close (BLOCKING #1)
  - short positions get a real stop/target/trail (BLOCKING #2)
Plus short-side coverage for #2b (EoB mark-to-market) and #3 (short margin call),
and the symmetric short trail-off-Low + breakeven cap.
"""

import os
import sys

import pandas as pd
import pytest
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.portfolio_simulations import run_portfolio_simulation

_CFG = {
    "slippage_pct": 0.0, "commission_per_share": 0.0, "execution_time": "close",
    "risk_free_rate": 0.05, "htb_rate_annual": 0.0, "volume_impact_coeff": 0.0,
    "max_pct_adv": 0.0, "position_sizing_method": "fixed", "target_risk_per_trade": 0.02,
    "max_portfolio_heat": 1.0, "entry_priority": "alphabetical",
    "exclude_open_positions": False, "include_delisted": False, "maintenance_margin_pct": 0.0,
    "instruments": {"default_asset_class": "equity", "futures_initial_margin_pct": 0.10,
                    "futures_commission_per_contract": 0.0, "futures_slippage_ticks": 0.0,
                    "overrides": {}},
}
_TRAIL = {"type": "trailing_atr", "stop_mult": 1.0, "trail_mult": 1.0, "t1_mult": 1.0, "floor": "breakeven"}


def _df(rows):
    idx = pd.bdate_range("2023-01-02", periods=len(rows)); idx.name = "Datetime"
    return pd.DataFrame({"Open": [r[0] for r in rows], "High": [r[1] for r in rows],
                         "Low": [r[2] for r in rows], "Close": [r[3] for r in rows],
                         "Volume": [1e6] * len(rows), "ATR_14": [r[4] for r in rows]}, index=idx)


def _sig(df, p):
    s = pd.Series(0, index=df.index, dtype=int)
    for i, v in p.items():
        s.iloc[i] = v
    return s


def _run(pd_, sg, sc, cfg_over=None):
    with patch.dict("config.CONFIG", {**_CFG, **(cfg_over or {})}, clear=False):
        return run_portfolio_simulation(portfolio_data=pd_, signals=sg, initial_capital=100_000.0,
                                        allocation_pct=1.0, spy_df=None, vix_df=None, tnx_df=None,
                                        stop_config=sc)


# --- Shardul's two reproductions -------------------------------------------
def test_long_trails_off_high_not_close():
    # arm bar High=110 Close=103 -> trail seeds at 108 (High), not 101 (Close)
    df = _df([(100, 100, 100, 100, 2.0), (100, 100, 100, 100, 2.0), (100, 110, 100, 103, 2.0),
              (103, 104, 102, 102, 2.0), (102, 102, 100.5, 100.5, 2.0)])
    t = _run({"AAA": df}, {"AAA": _sig(df, {1: 1})}, _TRAIL)["trade_log"][0]
    assert t["ExitPrice"] == pytest.approx(108.0), f"trailed off Close not High: {t['ExitPrice']}"


def test_short_gets_a_stop():
    # short @100, rips to 140 -> Sleeve A stop at 102 caps loss; engine must not ride to cover
    df = _df([(100, 100, 100, 100, 2.0), (100, 100, 100, 100, 2.0), (100, 120, 100, 120, 2.0),
              (120, 140, 120, 140, 2.0), (140, 140, 140, 140, 2.0)])
    res = _run({"BBB": df}, {"BBB": _sig(df, {1: -2, 4: -1})}, _TRAIL)
    assert res is not None
    st = [x for x in res["trade_log"] if str(x["Trade"]).startswith("Short")][0]
    assert abs(st["ExitPrice"] - 102) < 1e-6, f"short never stopped: {st['ExitPrice']}"
    assert st["ExitReason"] == "Stop Loss (trailing_atr)"
    assert st["InitialRisk"] == pytest.approx(2.0)   # real risk, not 0.0
    assert st["RMultiple"] is not None               # real R-multiple, not None


# --- short-side coverage ----------------------------------------------------
def test_short_trails_off_low_and_caps_at_breakeven():
    # short @100; drops to arm (target 98), rides down, then a low High keeps stop capped at entry.
    df = _df([(100, 100, 100, 100, 2.0), (100, 100, 100, 100, 2.0),
              (98, 98, 90, 97, 2.0),      # arm: Low 90 <= target 98 -> trail = 90+2 = 92
              (95, 103, 95, 102, 2.0)])   # High 103 >= trailed stop 92 -> cover at 92
    res = _run({"BBB": df}, {"BBB": _sig(df, {1: -2})}, _TRAIL)
    st = [x for x in res["trade_log"] if str(x["Trade"]).startswith("Short")][0]
    assert st["ExitReason"] == "Stop Loss (trailing_atr)"
    assert st["ExitPrice"] == pytest.approx(92.0)    # trailed off running-min Low (90+2)


def test_open_short_marked_at_end_of_backtest():
    # #2b: a short still open at the last bar must be logged, not silently dropped.
    df = _df([(100, 100, 100, 100, 2.0), (100, 100, 100, 100, 2.0),
              (99, 100, 98, 98, 2.0), (97, 98, 96, 97, 2.0)])
    res = _run({"BBB": df}, {"BBB": _sig(df, {1: -2})}, {"type": "none"})
    assert res is not None, "open short vanished -> run returned None (#2b regression)"
    st = [x for x in res["trade_log"] if str(x["Trade"]).startswith("Short")]
    assert len(st) == 1 and st[0]["ExitReason"] == "End of Backtest"
    assert st[0]["Profit"] > 0    # short into a falling market -> profit


def test_short_margin_call():
    # #3: futures short squeezed up through maintenance margin -> forced cover.
    df = _df([(4000, 4000, 4000, 4000, 5.0), (4000, 4000, 4000, 4000, 5.0),
              (4000, 4400, 4000, 4400, 5.0)])   # +10% against the short
    res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: -2})}, {"type": "none"},
               cfg_over={"maintenance_margin_pct": 0.05})
    assert res is not None
    st = [x for x in res["trade_log"] if str(x["Trade"]).startswith("Short")][0]
    assert st["ExitReason"] == "Margin Call"


# --- Opt-in intrabar parity (issue #234 follow-up) ---------------------------
# Reproduces two structural divergences from the frozen reference
# (scan_sleeve_a_full_trail): (a) the reference checks the stop/target starting
# ON the entry bar, while the vanilla engine only starts checking the day after;
# (b) a bar that touches BOTH the pre-arm stop and the arm target is ambiguous
# on daily OHLC alone and was always resolved as "stop" — the reference instead
# consults 1-minute data to see which came first. Both are opt-in: gated behind
# `intrabar_resolution=True` AND `intrabar_data` being supplied. When either is
# missing, `_intrabar_on` is False and every new code path is a no-op — the first
# test below locks in that the un-gated default is unchanged.

def _run_ib(pd_, sg, sc, intrabar_data, cfg_over=None):
    _over = {"intrabar_resolution": True, **(cfg_over or {})}
    with patch.dict("config.CONFIG", {**_CFG, **_over}, clear=False):
        return run_portfolio_simulation(portfolio_data=pd_, signals=sg, initial_capital=100_000.0,
                                        allocation_pct=1.0, spy_df=None, vix_df=None, tnx_df=None,
                                        stop_config=sc, intrabar_data=intrabar_data)


def test_gated_off_default_unchanged_on_ambiguous_bar():
    # intrabar_resolution OFF (no override, no intrabar_data) -> a bar touching BOTH
    # the stop and the arm target must still resolve as a plain stop (the
    # pre-existing pessimistic default), exactly as before this feature existed.
    df = _df([(100, 100, 100, 100, 2.0), (100, 100, 100, 100, 2.0),
              (100, 110, 90, 105, 2.0)])
    t = _run({"AAA": df}, {"AAA": _sig(df, {1: 1})}, _TRAIL)["trade_log"][0]
    assert t["ExitPrice"] == pytest.approx(98.0)           # initial stop (100 entry - 2 ATR); never armed
    assert t["ExitReason"] == "Stop Loss (trailing_atr)"
    assert pd.Timestamp(t["ExitDate"]) == df.index[2]


def test_entry_bar_stop_closes_long_same_bar():
    # Entry bar's own Low already breaches the stop (target untouched) -> the
    # opt-in entry-bar check must close the position immediately, same bar as entry.
    df = _df([(100, 100, 100, 100, 2.0), (95, 95, 90, 95, 2.0)])
    res = _run_ib({"AAA": df}, {"AAA": _sig(df, {1: 1})}, _TRAIL, intrabar_data={})
    tlog = res["trade_log"]
    assert len(tlog) == 1
    t = tlog[0]
    assert t["EntryDate"] == t["ExitDate"] == df.index[1].isoformat()
    assert t["ExitPrice"] == pytest.approx(93.0)           # entry(95) - 2 ATR; no 1-min data -> plain stop level
    assert t["ExitReason"] == "Stop Loss (trailing_atr)"


def test_entry_bar_stop_closes_short_same_bar():
    # Mirror of the above on the short side: entry bar's own High already
    # breaches the (upward) stop.
    df = _df([(100, 100, 100, 100, 2.0), (105, 110, 105, 105, 2.0)])
    res = _run_ib({"BBB": df}, {"BBB": _sig(df, {1: -2})}, _TRAIL, intrabar_data={})
    st = [x for x in res["trade_log"] if str(x["Trade"]).startswith("Short")]
    assert len(st) == 1
    t = st[0]
    assert t["EntryDate"] == t["ExitDate"] == df.index[1].isoformat()
    assert t["ExitPrice"] == pytest.approx(107.0)          # entry(105) + 2 ATR
    assert t["ExitReason"] == "Stop Loss (trailing_atr)"


def test_entry_bar_arm_seeds_trail_same_bar_long():
    # Entry bar's own High already reaches the arm target (Low stays clear of the
    # stop) -> must arm+seed the trail off THIS bar's High immediately rather than
    # exit, and rather than waiting for the following bar to notice the target.
    df = _df([(100, 100, 100, 100, 2.0), (103, 115, 102, 103, 2.0),
              (103, 104, 100, 100, 2.0)])
    res = _run_ib({"AAA": df}, {"AAA": _sig(df, {1: 1})}, _TRAIL, intrabar_data={})
    tlog = res["trade_log"]
    assert len(tlog) == 1
    t = tlog[0]
    assert pd.Timestamp(t["EntryDate"]) == df.index[1]
    assert pd.Timestamp(t["ExitDate"]) == df.index[2]      # NOT the entry bar itself
    assert t["ExitPrice"] == pytest.approx(113.0)           # armed off entry bar's High(115) - 2 ATR
    assert t["ExitReason"] == "Stop Loss (trailing_atr)"


def test_prearm_both_hit_1min_resolves_to_arm_long():
    # Daily bar is ambiguous (touches both the stop and the target); 1-min data
    # shows the target was actually touched FIRST -> must arm, not stop out.
    df = _df([(100, 100, 100, 100, 2.0), (100, 100, 100, 100, 2.0),
              (100, 110, 90, 105, 2.0), (105, 106, 95, 100, 2.0)])
    minute_ts = df.index[2] + pd.Timedelta(hours=10)
    mbars = pd.DataFrame({"Open": [100.0], "High": [103.0], "Low": [99.0], "Close": [101.0]},
                        index=pd.DatetimeIndex([minute_ts]))
    res = _run_ib({"AAA": df}, {"AAA": _sig(df, {1: 1})}, _TRAIL, intrabar_data={"AAA": mbars})
    t = res["trade_log"][0]
    assert pd.Timestamp(t["ExitDate"]) == df.index[3]       # NOT the ambiguous bar -> armed through it
    assert t["ExitPrice"] == pytest.approx(108.0)            # trail seeded off the daily High(110) - 2 ATR
    assert t["ExitReason"] == "Stop Loss (trailing_atr)"


def test_prearm_both_hit_1min_resolves_to_stop_gap_aware_long():
    # Same ambiguous daily bar; 1-min data instead shows a GAP straight through the
    # stop before the target is ever touched -> must stop out, gap-aware fill
    # (worse than the naive stop level), matching resolve_order_precedence.
    df = _df([(100, 100, 100, 100, 2.0), (100, 100, 100, 100, 2.0),
              (100, 110, 90, 105, 2.0), (105, 106, 95, 100, 2.0)])
    minute_ts = df.index[2] + pd.Timedelta(hours=10)
    mbars = pd.DataFrame({"Open": [97.0], "High": [99.0], "Low": [95.0], "Close": [96.0]},
                        index=pd.DatetimeIndex([minute_ts]))
    res = _run_ib({"AAA": df}, {"AAA": _sig(df, {1: 1})}, _TRAIL, intrabar_data={"AAA": mbars})
    t = res["trade_log"][0]
    assert pd.Timestamp(t["ExitDate"]) == df.index[2]
    assert t["ExitPrice"] == pytest.approx(97.0)             # gapped through the stop -> fills at the gap open
    assert t["ExitReason"] == "Stop Loss (trailing_atr)"


def test_armed_trail_stop_ignores_gap_fill_long():
    # Reference parity (issue #234 empirical re-run): once a trailing_atr trail has
    # armed, the reference (Sleeve A leg2 loop) always fills at the EXACT trail
    # level, gap or not -- it never consults sub-bar data for that exit. Feeding
    # 1-minute bars whose own Open gaps through the trail level must NOT change
    # the fill: gap-refinement only applies to the general (non-armed) stop check.
    df = _df([(100, 100, 100, 100, 2.0), (103, 115, 102, 103, 2.0),
              (108, 110, 95, 100, 2.0)])
    minute_ts = df.index[2] + pd.Timedelta(hours=10)
    mbars = pd.DataFrame({"Open": [108.0], "High": [110.0], "Low": [95.0], "Close": [100.0]},
                        index=pd.DatetimeIndex([minute_ts]))
    res = _run_ib({"AAA": df}, {"AAA": _sig(df, {1: 1})}, _TRAIL, intrabar_data={"AAA": mbars})
    t = res["trade_log"][0]
    assert pd.Timestamp(t["ExitDate"]) == df.index[2]
    assert t["ExitPrice"] == pytest.approx(113.0), \
        f"armed trail exit must ignore the 1-min gap and fill at the exact trail level: {t['ExitPrice']}"
    assert t["ExitReason"] == "Stop Loss (trailing_atr)"


def test_armed_trail_stop_ignores_gap_fill_short():
    # Mirror of the long-side test above for shorts.
    df = _df([(100, 100, 100, 100, 2.0), (97, 98, 85, 97, 2.0),
              (92, 105, 90, 100, 2.0)])
    minute_ts = df.index[2] + pd.Timedelta(hours=10)
    mbars = pd.DataFrame({"Open": [92.0], "High": [105.0], "Low": [90.0], "Close": [100.0]},
                        index=pd.DatetimeIndex([minute_ts]))
    res = _run_ib({"BBB": df}, {"BBB": _sig(df, {1: -2})}, _TRAIL, intrabar_data={"BBB": mbars})
    st = [x for x in res["trade_log"] if str(x["Trade"]).startswith("Short")][0]
    assert pd.Timestamp(st["ExitDate"]) == df.index[2]
    assert st["ExitPrice"] == pytest.approx(87.0), \
        f"armed trail exit must ignore the 1-min gap and fill at the exact trail level: {st['ExitPrice']}"
    assert st["ExitReason"] == "Stop Loss (trailing_atr)"


def test_prearm_both_hit_1min_resolves_to_arm_short():
    # Mirror of the long-side arm resolution on the short side.
    df = _df([(100, 100, 100, 100, 2.0), (100, 100, 100, 100, 2.0),
              (100, 110, 90, 95, 2.0), (91, 93, 90, 91, 2.0)])
    minute_ts = df.index[2] + pd.Timedelta(hours=10)
    mbars = pd.DataFrame({"Open": [100.0], "High": [101.0], "Low": [97.0], "Close": [98.0]},
                        index=pd.DatetimeIndex([minute_ts]))
    res = _run_ib({"BBB": df}, {"BBB": _sig(df, {1: -2})}, _TRAIL, intrabar_data={"BBB": mbars})
    st = [x for x in res["trade_log"] if str(x["Trade"]).startswith("Short")][0]
    assert pd.Timestamp(st["ExitDate"]) == df.index[3]
    assert st["ExitPrice"] == pytest.approx(92.0)            # trail seeded off the daily Low(90) + 2 ATR
    assert st["ExitReason"] == "Stop Loss (trailing_atr)"
