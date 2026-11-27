# tests/test_gap_stop_499.py
"""
Issue #499: gap-through stop fills, the "Stop Loss (gap, <type>)" exit reason
(#511 added the type), and the
entry-day gap below a structural stop (gap_below_stop_on_entry).

The fill rule itself (min(stop, Open) long / max(stop, Open) short) shipped in
#425; tests/test_stop_gap_fill.py pins it. This file pins what #499 adds:

  TestGapLabel          -- gap fills are labelled "Stop Loss (gap, <type>)", non-gap fills keep
                           "Stop Loss (<type>)" (long, short, both execution modes)
  TestEntryDayGap       -- a signal_bar / atr stop that the entry open is already
                           through: "skip" (default) vs "exit_at_open", long + short
  TestNeverBetter       -- regression: the gap-aware fill never books more P&L than the
                           legacy at-the-stop fill on any fixture
  TestValidator         -- unknown gap_below_stop_on_entry values warn
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
    _stop_exit_reason, is_gap_stop_reason, run_portfolio_simulation,
)

SLIP = 0.0005
BASE_CFG = {
    "slippage_pct": SLIP, "commission_per_share": 0.0, "execution_time": "open",
    "risk_free_rate": 0.05, "htb_rate_annual": 0.0, "volume_impact_coeff": 0.0,
    "max_pct_adv": 0.0, "position_sizing_method": "fixed", "target_risk_per_trade": 0.02,
    "max_portfolio_heat": 1.0, "entry_priority": "alphabetical",
    "exclude_open_positions": False, "include_delisted": False,
    "intrabar_resolution": False, "stop_gap_fill": "open",
    "entry_bar_stop_check": True, "gap_below_stop_on_entry": "skip",
    "instruments": {"default_asset_class": "equity", "overrides": {}},
}

PCT = {"type": "percentage", "value": 0.05}
GAP_PCT = "Stop Loss (gap, percentage)"
GAP_SIGBAR = "Stop Loss (gap, signal_bar)"
SIGBAR = {"type": "signal_bar", "buffer": 0.0, "bars_back": 0}


def _frame(rows):
    """rows: list of (Open, High, Low, Close)."""
    idx = pd.bdate_range("2024-01-02", periods=len(rows))
    idx.name = "Datetime"
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c,
                         "Volume": [1e6] * len(rows)}, index=idx)


def _run(df, signal_vals, stop_cfg, cfg_over=None, full=False):
    sig = pd.Series(signal_vals, index=df.index, dtype=float)
    cfg = {**BASE_CFG, **(cfg_over or {})}
    with patch.dict("config.CONFIG", cfg, clear=False):
        res = run_portfolio_simulation(
            portfolio_data={"AAA": df}, signals={"AAA": sig},
            initial_capital=100_000.0, allocation_pct=0.10,
            spy_df=None, vix_df=None, tnx_df=None, stop_config=stop_cfg)
    if full:
        return res
    return [] if res is None else res["trade_log"]


# ---------------------------------------------------------------------------
class TestStopExitReasonHelper:
    def test_long(self):
        assert _stop_exit_reason(PCT, 80.0, 95.0, "long") == GAP_PCT
        assert _stop_exit_reason(PCT, 95.0, 95.0, "long") == "Stop Loss (percentage)"

    def test_short(self):
        assert _stop_exit_reason(PCT, 120.0, 105.0, "short") == GAP_PCT
        assert _stop_exit_reason(PCT, 105.0, 105.0, "short") == "Stop Loss (percentage)"

    def test_nan_fill_is_not_a_gap(self):
        assert _stop_exit_reason(PCT, np.nan, 95.0, "long") == "Stop Loss (percentage)"


# ---------------------------------------------------------------------------
class TestGapLabel:
    # Signal on bar0, entry at bar1 open (100); percentage stop = 100*(1+SLIP)*0.95.
    STOP = 100 * (1 + SLIP) * 0.95

    def _long(self, bar2):
        return _frame([(100, 101, 99, 100), (100, 101, 99, 100), bar2, (90, 91, 89, 90)])

    def test_open_below_stop_and_low_below_stop_fills_at_open(self):
        t = _run(self._long((80, 82, 78, 81)), [1, 1, 1, 1], PCT)[0]
        assert t["ExitReason"] == GAP_PCT
        assert t["ExitPrice"] == pytest.approx(80.0 * (1 - SLIP), abs=1e-9)

    def test_open_above_stop_low_below_fills_at_stop_unchanged(self):
        t = _run(self._long((99, 100, 90, 92)), [1, 1, 1, 1], PCT)[0]
        assert t["ExitReason"] == "Stop Loss (percentage)"
        assert t["ExitPrice"] == pytest.approx(self.STOP * (1 - SLIP), abs=1e-9)

    def test_close_execution_also_labels_gap(self):
        t = _run(self._long((80, 82, 78, 81)), [0, 1, 1, 1], PCT,
                 {"execution_time": "close"})[0]
        assert t["ExitReason"] == GAP_PCT

    def test_level_mode_never_labels_gap(self):
        t = _run(self._long((80, 82, 78, 81)), [1, 1, 1, 1], PCT,
                 {"stop_gap_fill": "level"})[0]
        assert t["ExitReason"] == "Stop Loss (percentage)"
        assert t["ExitPrice"] == pytest.approx(self.STOP * (1 - SLIP), abs=1e-9)

    # Shorts: short entry fill = 100*(1-SLIP); stop = ep*1.05 anchored to raw ep (#332).
    def _short(self, bar2):
        return _frame([(100, 101, 99, 100), (100, 101, 99, 100), bar2, (110, 111, 109, 110)])

    def test_short_open_above_stop_fills_at_open(self):
        t = _run(self._short((120, 122, 118, 121)), [-2, -2, -2, -2], PCT)[0]
        assert t["ExitReason"] == GAP_PCT
        assert t["ExitPrice"] == pytest.approx(120.0 * (1 + SLIP), abs=1e-9)

    def test_short_open_below_stop_high_above_fills_at_stop(self):
        t = _run(self._short((101, 110, 100, 108)), [-2, -2, -2, -2], PCT)[0]
        assert t["ExitReason"] == "Stop Loss (percentage)"
        assert t["ExitPrice"] == pytest.approx(105.0 * (1 + SLIP), abs=1e-9)


# ---------------------------------------------------------------------------
class TestEntryDayGap:
    """signal_bar stop = signal-bar Low (long) / High (short). Signal bar is bar1;
    under execution_time='open' the fill is bar2's Open."""

    def _long_gap(self):
        # bar1 low 95 -> stop 95. bar2 opens 90 (already below the stop).
        return _frame([(100, 101, 99, 100), (100, 101, 95, 100), (90, 92, 88, 91),
                       (91, 93, 90, 92), (92, 94, 91, 93)])

    def test_long_skip_is_default_and_takes_no_trade(self):
        res = _run(self._long_gap(), [0, 1, 1, 1, 1], SIGBAR, full=True)
        assert res is None or res["trade_log"] == []

    def test_long_skip_is_counted(self):
        # A later non-gapped signal lets the run return; the gapped one is counted.
        df = _frame([(100, 101, 99, 100), (100, 101, 95, 100), (90, 92, 88, 91),
                     (91, 93, 90, 92), (92, 94, 91, 93), (93, 95, 92, 94),
                     (94, 96, 93, 95), (95, 97, 94, 96)])
        sig = [0, 1, 0, 0, 0, 1, 1, 1]
        res = _run(df, sig, SIGBAR, full=True)
        assert res["sizing_diagnostics"].get("skipped_gap_below_stop") == 1
        assert len(res["trade_log"]) == 1
        assert res["trade_log"][0]["EntryDate"].startswith(str(df.index[6].date()))

    def test_long_exit_at_open_round_trips_at_the_open(self):
        t = _run(self._long_gap(), [0, 1, 1, 1, 1], SIGBAR,
                 {"gap_below_stop_on_entry": "exit_at_open"})
        assert len(t) == 1
        t = t[0]
        assert t["ExitReason"] == GAP_SIGBAR
        assert t["EntryDate"] == t["ExitDate"]
        assert t["EntryPrice"] == pytest.approx(90.0 * (1 + SLIP), abs=1e-9)
        assert t["ExitPrice"] == pytest.approx(90.0 * (1 - SLIP), abs=1e-9)
        assert t["Profit"] < 0

    def test_long_no_gap_unchanged(self):
        # bar2 opens 97 above the stop 95; low 96 holds. Trade stays on.
        df = _frame([(100, 101, 99, 100), (100, 101, 95, 100), (97, 99, 96, 98),
                     (98, 99, 97, 98), (98, 99, 97, 98)])
        t = _run(df, [0, 1, 1, 1, 1], SIGBAR)
        assert len(t) == 1 and t[0]["ExitReason"] == "End of Backtest"

    def test_long_entry_bar_low_checked_against_initial_stop(self):
        # Opens 97 above the stop 95, trades down to 93 on the fill bar -> stop at 95.
        df = _frame([(100, 101, 99, 100), (100, 101, 95, 100), (97, 98, 93, 94),
                     (94, 95, 93, 94)])
        t = _run(df, [0, 1, 1, 1], SIGBAR)[0]
        assert t["EntryDate"] == t["ExitDate"]
        assert t["ExitReason"] == "Stop Loss (signal_bar)"
        assert t["ExitPrice"] == pytest.approx(95.0 * (1 - SLIP), abs=1e-9)

    def test_atr_stop_gap_on_entry_is_skipped(self):
        # atr stop from the signal bar: Close 100 - 3*ATR(2) = 94. Fill opens 90.
        df = self._long_gap()
        df["ATR_14"] = 2.0
        res = _run(df, [0, 1, 1, 1, 1], {"type": "atr", "multiplier": 3.0}, full=True)
        assert res is None or res["trade_log"] == []
        t = _run(df, [0, 1, 1, 1, 1], {"type": "atr", "multiplier": 3.0},
                 {"gap_below_stop_on_entry": "exit_at_open"})
        assert len(t) == 1 and t[0]["ExitReason"] == "Stop Loss (gap, atr)"

    def test_percentage_stop_never_triggers_entry_gap(self):
        t = _run(self._long_gap(), [0, 1, 1, 1, 1], PCT)
        assert len(t) == 1 and not is_gap_stop_reason(t[0]["ExitReason"])

    def _short_gap(self):
        # bar1 high 105 -> short stop 105. bar2 opens 110 (already above).
        return _frame([(100, 101, 99, 100), (100, 105, 99, 100), (110, 112, 108, 111),
                       (111, 112, 110, 111), (111, 112, 110, 111)])

    def test_short_skip(self):
        res = _run(self._short_gap(), [0, -2, -2, -2, -2], SIGBAR, full=True)
        assert res is None or res["trade_log"] == []

    def test_short_exit_at_open(self):
        t = _run(self._short_gap(), [0, -2, -2, -2, -2], SIGBAR,
                 {"gap_below_stop_on_entry": "exit_at_open"})
        assert len(t) == 1
        assert t[0]["ExitReason"] == GAP_SIGBAR
        assert t[0]["EntryDate"] == t[0]["ExitDate"]
        assert t[0]["ExitPrice"] == pytest.approx(110.0 * (1 + SLIP), abs=1e-9)

    def test_unknown_mode_runs_as_skip(self):
        res = _run(self._long_gap(), [0, 1, 1, 1, 1], SIGBAR,
                   {"gap_below_stop_on_entry": "exit-at-open"}, full=True)
        assert res is None or res["trade_log"] == []


# ---------------------------------------------------------------------------
def _random_fixture(seed, n=120):
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, n)))
    gap = rng.normal(0, 0.015, n) + np.where(rng.random(n) < 0.08, rng.normal(-0.05, 0.03, n), 0)
    o = np.r_[c[0], c[:-1] * np.exp(gap[1:])]
    h = np.maximum(o, c) * (1 + rng.uniform(0, 0.02, n))
    l = np.minimum(o, c) * (1 - rng.uniform(0, 0.02, n))
    df = _frame(list(zip(o, h, l, c)))
    sig = np.where(rng.random(n) < 0.15, 1, np.where(rng.random(n) < 0.1, -1, 0))
    return df, sig


class TestNeverBetter:
    """Regression gate: the gap-aware fill can never book MORE than the legacy
    at-the-stop fill. Entries are signal-driven and identical in both arms, so
    every trade's exit price and return must be <= legacy, and so must the total."""

    @pytest.mark.parametrize("seed", range(15))
    @pytest.mark.parametrize("stop", [PCT, {"type": "percentage", "value": 0.02},
                                      {"type": "points", "value": 2.0}])
    @pytest.mark.parametrize("exe", ["open", "close"])
    def test_gap_fill_pnl_le_legacy(self, seed, stop, exe):
        df, sig = _random_fixture(seed)
        cfg = {"execution_time": exe}
        new = _run(df, sig, stop, cfg, full=True)
        old = _run(df, sig, stop, {**cfg, "stop_gap_fill": "level"}, full=True)
        assert (new is None) == (old is None)
        if new is None:
            return
        n_tl, o_tl = new["trade_log"], old["trade_log"]
        assert [t["EntryDate"] for t in n_tl] == [t["EntryDate"] for t in o_tl]
        for a_, b_ in zip(n_tl, o_tl):
            assert a_["ExitDate"] == b_["ExitDate"]
            assert a_["ExitPrice"] <= b_["ExitPrice"] + 1e-9
            assert a_["ProfitPct"] <= b_["ProfitPct"] + 1e-12
        assert sum(t["Profit"] for t in n_tl) <= sum(t["Profit"] for t in o_tl) + 1e-6
        n_gap = sum(is_gap_stop_reason(t["ExitReason"]) for t in n_tl)
        if n_gap:
            assert sum(t["Profit"] for t in n_tl) < sum(t["Profit"] for t in o_tl)

    def test_fixtures_actually_gap(self):
        # Guard against a hollow gate: the random fixtures must produce gap exits.
        n = 0
        for seed in range(15):
            df, sig = _random_fixture(seed)
            res = _run(df, sig, PCT, full=True)
            n += sum(is_gap_stop_reason(t["ExitReason"]) for t in res["trade_log"])
        assert n >= 5


# ---------------------------------------------------------------------------
class TestValidator:
    def test_unknown_mode_warns(self):
        from helpers.config_validator import validate_config
        w = validate_config({"gap_below_stop_on_entry": "bogus"})
        assert any("gap_below_stop_on_entry" in m for m in w)

    @pytest.mark.parametrize("v", ["skip", "exit_at_open", None])
    def test_known_modes_quiet(self, v):
        from helpers.config_validator import validate_config
        w = validate_config({"gap_below_stop_on_entry": v})
        assert not any("gap_below_stop_on_entry" in m for m in w)
