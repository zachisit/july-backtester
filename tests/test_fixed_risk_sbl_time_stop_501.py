# tests/test_fixed_risk_sbl_time_stop_501.py
"""
Issue #501: fixed-risk sizing with a notional cap, the signal_bar_low stop
(raw prices, optional ATR trail), and the session-count time stop.

  TestFixedRiskFormula   -- the sizing function on its own
  TestFixedRiskEngine    -- shares in the engine match the formula; the notional
                            cap binds on tight stops; no stop -> no trade
  TestSizingEquity       -- under execution_time="open", sizing reads the
                            start-of-bar equity (#490 dependency, see note)
  TestSignalBarLow       -- raw-low stop on a split-adjusted series, offset in
                            raw dollars rounded to cents, gap-on-entry skip
  TestTrail              -- ratchets up only, next-bar activation, uses ATR and
                            highs through the PRIOR bar
  TestTimeStop           -- next_open / close semantics, an earlier stop wins,
                            sessions not calendar days
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

from helpers.position_sizing import calculate_position_size  # noqa: E402
from helpers.portfolio_simulations import (  # noqa: E402
    TIME_STOP_REASON, _simple_atr, _time_stop_cfg, run_portfolio_simulation,
)

BASE_CFG = {
    "slippage_pct": 0.0, "commission_per_share": 0.0, "execution_time": "open",
    "risk_free_rate": 0.0, "htb_rate_annual": 0.0, "volume_impact_coeff": 0.0,
    "max_pct_adv": 0.0, "position_sizing_method": "fixed_risk",
    "risk_per_trade": 0.005, "max_position_pct": 0.05,
    "target_risk_per_trade": 0.02, "max_portfolio_heat": 1.0,
    "entry_priority": "alphabetical", "exclude_open_positions": False,
    "include_delisted": False, "intrabar_resolution": False,
    "stop_gap_fill": "open", "entry_bar_stop_check": True,
    "gap_below_stop_on_entry": "skip", "time_stop": None,
    "instruments": {"default_asset_class": "equity", "overrides": {}},
}
SBL = {"type": "signal_bar_low", "offset": 0.01}


def _frame(rows, start="2024-01-02"):
    idx = pd.bdate_range(start, periods=len(rows))
    idx.name = "Datetime"
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c,
                         "Volume": [1e6] * len(rows)}, index=idx, dtype=float)


def _run(data, sigs, stop_cfg, cfg_over=None, aux=None, capital=100_000.0):
    if isinstance(data, pd.DataFrame):
        data, sigs = {"AAA": data}, {"AAA": sigs}
        aux = {"AAA": aux} if aux is not None else None
    signals = {k: pd.Series(v, index=data[k].index, dtype=float) for k, v in sigs.items()}
    cfg = {**BASE_CFG, **(cfg_over or {})}
    with patch.dict("config.CONFIG", cfg, clear=False):
        return run_portfolio_simulation(
            portfolio_data=data, signals=signals, initial_capital=capital,
            allocation_pct=0.10, spy_df=None, vix_df=None, tnx_df=None,
            stop_config=stop_cfg, signal_aux=aux)


def _flat(n, px=100.0):
    return [(px, px + 1, px - 1, px)] * n


# ---------------------------------------------------------------------------
class TestFixedRiskFormula:
    def test_risk_binds(self):
        # 0.5% of 100k = 500 risk; stop distance 10 -> 50 shares; cap 5% / 100 = 50 -> tie
        cfg = {"risk_per_trade": 0.005, "max_position_pct": 0.10}
        n = calculate_position_size("fixed_risk", 100_000, 100.0, None, cfg,
                                    stop_distance_points=10.0)
        assert n == 50

    def test_cap_binds_on_tight_stop(self):
        cfg = {"risk_per_trade": 0.005, "max_position_pct": 0.05}
        n = calculate_position_size("fixed_risk", 100_000, 100.0, None, cfg,
                                    stop_distance_points=0.5)   # risk says 1000 sh
        assert n == 50                                          # 5% of 100k / $100

    def test_floor(self):
        cfg = {"risk_per_trade": 0.005, "max_position_pct": 1.0}
        n = calculate_position_size("fixed_risk", 100_000, 100.0, None, cfg,
                                    stop_distance_points=3.0)
        assert n == 166                                         # floor(166.67)

    @pytest.mark.parametrize("d", [None, 0.0, -1.0])
    def test_no_or_negative_distance_no_trade(self, d):
        assert calculate_position_size("fixed_risk", 100_000, 100.0, None,
                                       {"risk_per_trade": 0.005}, stop_distance_points=d) == 0


class TestFixedRiskEngine:
    def test_shares_match_formula_percentage_stop(self):
        # entry at bar1 open 100, pct stop 4% -> distance 4 -> 125 sh by risk; cap 5% -> 50.
        df = _frame(_flat(5))
        r = _run(df, [1, 1, 1, 1, 1], {"type": "percentage", "value": 0.04},
                 {"max_position_pct": 1.0})
        assert r["trade_log"][0]["Shares"] == 125
        r = _run(df, [1, 1, 1, 1, 1], {"type": "percentage", "value": 0.04})
        assert r["trade_log"][0]["Shares"] == 50                # cap binds

    def test_no_stop_takes_no_trade(self):
        df = _frame(_flat(5))
        assert _run(df, [1, 1, 1, 1, 1], {"type": "none"}) is None

    def test_sbl_shares_from_the_real_stop(self):
        # signal bar0 low 95 -> stop 94.99; entry open 100 -> distance 5.01 -> floor(99.8)=99
        df = _frame([(100, 101, 95, 100)] + _flat(5))
        r = _run(df, [1, 0, 0, 0, 0, 0], SBL, {"max_position_pct": 1.0})
        t = r["trade_log"][0]
        assert t["Shares"] == 99
        assert t["InitialRisk"] == pytest.approx(5.01)


class TestSizingEquity:
    def test_second_entry_sized_from_start_of_bar_equity(self):
        """AAA held; BBB enters at the open of a bar on which AAA's CLOSE moves.
        BBB's share count must not depend on that same-bar close.

        Depends on #490 (PR #494): on a base without it the engine marks held
        positions at the same-bar close when sizing an open entry, and this
        test fails. Skipped here unless the #494 helper is present."""
        import helpers.portfolio_simulations as ps
        import inspect
        if "_mtm_open" not in inspect.getsource(ps.run_portfolio_simulation):
            pytest.skip("needs #490 / PR #494 (open-marked sizing equity)")
        counts = []
        for aaa_close in (50.0, 100.0, 150.0):
            a = _frame([(100, 101, 99, 100), (100, 101, 99, 100), (100, 160, 40, aaa_close),
                        (100, 101, 99, 100)])
            b = _frame([(100, 101, 99, 100), (100, 101, 99, 100), (100, 101, 99, 100),
                        (100, 101, 99, 100)])
            r = _run({"AAA": a, "BBB": b}, {"AAA": [1, 0, 0, 0], "BBB": [0, 1, 0, 0]},
                     {"type": "percentage", "value": 0.5}, {"max_position_pct": 1.0,
                                                           "risk_per_trade": 0.01})
            counts.append([t for t in r["trade_log"] if t["Symbol"] == "BBB"][0]["Shares"])
        assert counts[0] == counts[1] == counts[2]


# ---------------------------------------------------------------------------
class TestSignalBarLow:
    def _split_series(self):
        # Raw prices ~200 before a 2:1 split on bar 4, ~100 after. The engine's
        # bars are split-ADJUSTED (all ~100). raw_low on the signal bar is 190.00.
        rows = [(100, 101, 95, 100)] + _flat(6)
        return _frame(rows)

    def test_raw_low_on_split_adjusted_series(self):
        df = self._split_series()
        aux = pd.DataFrame({"raw_low": [190.0] + [np.nan] * 6}, index=df.index)
        r = _run(df, [1, 0, 0, 0, 0, 0, 0], SBL, {"max_position_pct": 1.0}, aux=aux)
        t = r["trade_log"][0]
        # stop_raw = 189.99 -> adjusted = 189.99 * (95/190) = 94.995
        assert t["InitialRisk"] == pytest.approx(100 - 94.995)

    def test_offset_without_raw_is_in_adjusted_dollars(self):
        df = self._split_series()
        r = _run(df, [1, 0, 0, 0, 0, 0, 0], SBL, {"max_position_pct": 1.0})
        assert r["trade_log"][0]["InitialRisk"] == pytest.approx(100 - 94.99)

    def test_price_frame_raw_column_is_used(self):
        df = self._split_series()
        df["Low_raw"] = df["Low"] * 2
        r = _run(df, [1, 0, 0, 0, 0, 0, 0], SBL, {"max_position_pct": 1.0})
        assert r["trade_log"][0]["InitialRisk"] == pytest.approx(100 - 94.995)

    def test_rounds_to_cents_in_raw(self):
        df = _frame([(100, 101, 95.004, 100)] + _flat(4))
        r = _run(df, [1, 0, 0, 0, 0], SBL, {"max_position_pct": 1.0})
        # 95.004 - 0.01 = 94.994 -> 94.99
        assert r["trade_log"][0]["InitialRisk"] == pytest.approx(100 - 94.99)

    def test_stop_hit_fills_at_stop_and_gap_fills_at_open(self):
        df = _frame([(100, 101, 95, 100), (100, 101, 99, 100), (97, 98, 90, 92), (92, 93, 91, 92)])
        t = _run(df, [1, 0, 0, 0], SBL)["trade_log"][0]
        assert t["ExitPrice"] == pytest.approx(94.99) and t["ExitReason"] == "Stop Loss (signal_bar_low)"
        df = _frame([(100, 101, 95, 100), (100, 101, 99, 100), (90, 92, 88, 91), (91, 92, 90, 91)])
        t = _run(df, [1, 0, 0, 0], SBL)["trade_log"][0]
        assert t["ExitPrice"] == pytest.approx(90.0) and t["ExitReason"] == "Stop Loss (gap)"

    def test_entry_open_below_stop_is_skipped(self):
        df = _frame([(100, 101, 95, 100), (94, 95, 93, 94), (94, 95, 93, 94)])
        assert _run(df, [1, 0, 0], SBL) is None


class TestTrail:
    TRAIL = {"type": "signal_bar_low", "offset": 0.01, "trail_atr": 3.0, "atr_period": 10}

    def _rows(self):
        # bar0 signal (low 95); entry bar1 open 100; then a rally and a decline.
        return [(100, 101, 95, 100), (100, 102, 99, 101), (101, 110, 100, 109),
                (109, 120, 108, 119), (119, 121, 117, 118), (118, 119, 112, 113),
                (113, 114, 100, 101), (101, 102, 99, 100)]

    def _expected_stops(self, df):
        atr = _simple_atr(df, 10)
        stop = 94.99
        max_h = 100.0          # entry fill
        out = {}
        for j in range(1, len(df)):
            out[j] = stop      # active stop on bar j
            if df["Low"].iloc[j] <= stop:
                break
            cand = max_h - 3.0 * atr.iloc[j - 1]
            stop = max(stop, cand)
            max_h = max(max_h, df["High"].iloc[j])
        return out

    def test_trail_matches_reference_recursion_and_never_moves_down(self):
        df = _frame(self._rows())
        r = _run(df, [1] + [0] * 7, self.TRAIL, {"max_position_pct": 1.0})
        t = r["trade_log"][0]
        exp = self._expected_stops(df)
        exit_j = list(df.index).index(pd.Timestamp(t["ExitDate"]))
        assert t["ExitReason"].startswith("Stop Loss")
        assert t["ExitPrice"] == pytest.approx(min(exp[exit_j], df["Open"].iloc[exit_j]))
        seq = [exp[k] for k in sorted(exp)]
        assert all(b >= a for a, b in zip(seq, seq[1:]))

    def test_simple_atr_definition(self):
        df = _frame([(10, 12, 9, 11), (11, 13, 10, 12), (12, 12, 8, 9)])
        a = _simple_atr(df, 2)
        assert a.iloc[0] == pytest.approx(3.0)                  # H-L on the first bar
        assert a.iloc[1] == pytest.approx((3.0 + 3.0) / 2)
        assert a.iloc[2] == pytest.approx((3.0 + 4.0) / 2)

    def test_trail_not_raised_by_same_bar_high(self):
        # Bar 2's High spikes to 200. That spike may only raise the stop for bar 4
        # (it enters the running max after bar 2's check, and bar 3's candidate
        # uses highs through bar 2). A same-bar read would stop out on bar 3.
        rows = [(100, 101, 95, 100), (100, 101, 99.5, 100), (100, 200, 99.5, 100),
                (101, 102, 100.7, 101), (101, 102, 100.7, 101), (101, 102, 100.7, 101)]
        df = _frame(rows)
        r = _run(df, [1, 0, 0, 0, 0, 0], {**self.TRAIL, "trail_atr": 0.1}, {"max_position_pct": 1.0})
        t = r["trade_log"][0]
        assert pd.Timestamp(t["ExitDate"]) == df.index[4]
        assert t["ExitReason"] == "Stop Loss (gap)"            # opened 101 under ~196


# ---------------------------------------------------------------------------
class TestTimeStop:
    def test_cfg_resolution(self):
        assert _time_stop_cfg({"type": "none", "time_stop": {"sessions": 5}}) == (5, "next_open")
        assert _time_stop_cfg({"type": "none", "time_stop": {"sessions": 5, "exit": "close"}}) == (5, "close")
        assert _time_stop_cfg({"type": "none"}) is None
        assert _time_stop_cfg({"type": "none", "time_stop": {"sessions": 0}}) is None

    def test_next_open_exits_on_entry_plus_n_at_open(self):
        df = _frame([(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(30)])
        stop = {**SBL, "time_stop": {"sessions": 20, "exit": "next_open"}}
        t = _run(df, [1] + [0] * 29, stop, {"max_position_pct": 1.0})["trade_log"][0]
        assert pd.Timestamp(t["EntryDate"]) == df.index[1]
        assert pd.Timestamp(t["ExitDate"]) == df.index[1 + 20]
        assert t["ExitPrice"] == pytest.approx(df["Open"].iloc[21])
        assert t["ExitReason"] == TIME_STOP_REASON

    def test_close_exits_at_close_of_session_n(self):
        df = _frame([(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(30)])
        stop = {**SBL, "time_stop": {"sessions": 20, "exit": "close"}}
        t = _run(df, [1] + [0] * 29, stop, {"max_position_pct": 1.0})["trade_log"][0]
        assert pd.Timestamp(t["ExitDate"]) == df.index[1 + 19]
        assert t["ExitPrice"] == pytest.approx(df["Close"].iloc[20])

    def test_one_session_close_exits_on_entry_bar(self):
        df = _frame([(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(5)])
        stop = {**SBL, "time_stop": {"sessions": 1, "exit": "close"}}
        t = _run(df, [1, 0, 0, 0, 0], stop, {"max_position_pct": 1.0})["trade_log"][0]
        assert t["EntryDate"] == t["ExitDate"]
        assert t["ExitPrice"] == pytest.approx(df["Close"].iloc[1])

    def test_earlier_stop_wins(self):
        rows = [(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(30)]
        rows[6] = (105, 106, 80, 82)           # entry+5 breaks the 98.99 stop
        df = _frame(rows)
        stop = {**SBL, "time_stop": {"sessions": 20, "exit": "next_open"}}
        t = _run(df, [1] + [0] * 29, stop, {"max_position_pct": 1.0})["trade_log"][0]
        assert pd.Timestamp(t["ExitDate"]) == df.index[6]
        assert t["ExitReason"].startswith("Stop Loss")

    def test_counts_sessions_not_calendar_days(self):
        # Index with a 10-day holiday hole: 20 sessions still means 20 bars.
        idx = list(pd.bdate_range("2024-01-02", periods=10)) + \
            list(pd.bdate_range("2024-02-01", periods=20))
        rows = [(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(30)]
        df = _frame(rows)
        df.index = pd.DatetimeIndex(idx, name="Datetime")
        stop = {**SBL, "time_stop": {"sessions": 20, "exit": "next_open"}}
        t = _run(df, [1] + [0] * 29, stop, {"max_position_pct": 1.0})["trade_log"][0]
        assert pd.Timestamp(t["ExitDate"]) == df.index[21]

    def test_global_time_stop_key(self):
        df = _frame([(100 + i, 101 + i, 99 + i, 100.5 + i) for i in range(10)])
        t = _run(df, [1] + [0] * 9, SBL, {"max_position_pct": 1.0,
                                          "time_stop": {"sessions": 3, "exit": "next_open"}})["trade_log"][0]
        assert pd.Timestamp(t["ExitDate"]) == df.index[4]
