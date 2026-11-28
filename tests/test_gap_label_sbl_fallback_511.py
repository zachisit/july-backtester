# tests/test_gap_label_sbl_fallback_511.py
"""
Issue #511: stop exit labels keep the stop type, and signal_bar_low entries that
fall back to the adjusted Low are counted.

  TestLabelHelper        -- _stop_exit_reason / is_gap_stop_reason on their own
  TestLabelMatrix        -- gap vs at-level label for every structural and anchored
                            stop type, long and short, through the engine
  TestSblTrailLabel      -- a signal_bar_low stop raised by its ATR trail reads
                            "signal_bar_low trail", gapped and at the level; a trail
                            that never moved keeps the plain label
  TestExitAtOpen         -- gap_below_stop_on_entry="exit_at_open" labels
  TestSblFallbackCounter -- sbl_adjusted_fallback in sizing_diagnostics and in the
                            run-summary sizing report
"""

import logging
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
    GAP_STOP_PREFIX, _stop_exit_reason, is_gap_stop_reason, run_portfolio_simulation,
)
from helpers.sizing_diagnostics import COVERAGE_DRIFT, REASONS, SizingDiagnostics  # noqa: E402

BASE_CFG = {
    "slippage_pct": 0.0, "commission_per_share": 0.0, "execution_time": "open",
    "risk_free_rate": 0.0, "htb_rate_annual": 0.0, "volume_impact_coeff": 0.0,
    "max_pct_adv": 0.0, "position_sizing_method": "fixed", "target_risk_per_trade": 0.02,
    "max_portfolio_heat": 1.0, "entry_priority": "alphabetical",
    "exclude_open_positions": False, "include_delisted": False,
    "intrabar_resolution": False, "stop_gap_fill": "open",
    "entry_bar_stop_check": True, "gap_below_stop_on_entry": "skip",
    "time_stop": None, "maintenance_margin_pct": 0.0,
    "instruments": {"default_asset_class": "equity", "overrides": {}},
}

PCT = {"type": "percentage", "value": 0.05}
POINTS = {"type": "points", "value": 2.0}
ATR = {"type": "atr", "multiplier": 3.0}
SIGBAR = {"type": "signal_bar", "buffer": 0.0, "bars_back": 0}
SBL = {"type": "signal_bar_low", "offset": 0.01}
TRAIL_ATR = {"type": "trailing_atr", "stop_mult": 1.0, "trail_mult": 1.0,
             "t1_mult": 1.0, "floor": "breakeven"}


def _frame(rows, atr=2.0):
    idx = pd.bdate_range("2024-01-02", periods=len(rows))
    idx.name = "Datetime"
    o, h, l, c = zip(*rows)
    return pd.DataFrame({"Open": o, "High": h, "Low": l, "Close": c,
                         "Volume": [1e6] * len(rows), "ATR_14": [atr] * len(rows)},
                        index=idx, dtype=float)


def _run(df, sig, stop_cfg, cfg_over=None, aux=None, full=False):
    data = df if isinstance(df, dict) else {"AAA": df}
    sigs = sig if isinstance(sig, dict) else {"AAA": sig}
    signals = {k: pd.Series(v, index=data[k].index, dtype=float) for k, v in sigs.items()}
    if aux is not None and not isinstance(aux, dict):
        aux = {"AAA": aux}
    with patch.dict("config.CONFIG", {**BASE_CFG, **(cfg_over or {})}, clear=False):
        res = run_portfolio_simulation(
            portfolio_data=data, signals=signals, initial_capital=100_000.0,
            allocation_pct=0.10, spy_df=None, vix_df=None, tnx_df=None,
            stop_config=stop_cfg, signal_aux=aux)
    if full:
        return res
    return [] if res is None else res["trade_log"]


# ---------------------------------------------------------------------------
class TestLabelHelper:
    @pytest.mark.parametrize("cfg", [PCT, POINTS, ATR, SIGBAR, SBL, TRAIL_ATR])
    def test_gap_label_carries_the_at_level_type(self, cfg):
        at_level = _stop_exit_reason(cfg, 95.0, 95.0, "long")
        gap = _stop_exit_reason(cfg, 90.0, 95.0, "long")
        assert at_level == f"Stop Loss ({cfg['type']})"
        assert gap == f"Stop Loss (gap, {cfg['type']})"
        assert _stop_exit_reason(cfg, 110.0, 105.0, "short") == gap
        assert _stop_exit_reason(cfg, 105.0, 105.0, "short") == at_level

    def test_trail_raised_signal_bar_low(self):
        pos = {"sbl_trail_raised": True}
        assert _stop_exit_reason(SBL, 95.0, 95.0, "long", pos) == "Stop Loss (signal_bar_low trail)"
        assert _stop_exit_reason(SBL, 90.0, 95.0, "long", pos) == "Stop Loss (gap, signal_bar_low trail)"
        assert _stop_exit_reason(SBL, 95.0, 95.0, "long", {}) == "Stop Loss (signal_bar_low)"

    def test_trail_flag_ignored_for_other_types(self):
        pos = {"sbl_trail_raised": True}
        assert _stop_exit_reason(ATR, 90.0, 95.0, "long", pos) == "Stop Loss (gap, atr)"

    def test_is_gap_stop_reason(self):
        assert GAP_STOP_PREFIX == "Stop Loss (gap, "
        assert is_gap_stop_reason("Stop Loss (gap, atr)")
        assert is_gap_stop_reason("Stop Loss (gap, signal_bar_low trail)")
        assert not is_gap_stop_reason("Stop Loss (atr)")
        assert not is_gap_stop_reason("Stop Loss (gap)")     # the pre-#511 label
        assert not is_gap_stop_reason(None)


# ---------------------------------------------------------------------------
# Signal on bar0 (Low 95, High 105, Close 100, ATR 2); fill at bar1 open 100.
# Long stops: pct 95, points 98, atr 94, signal_bar 95, signal_bar_low 94.99,
# trailing_atr 98 (target 102). Short stops: pct 105, points 102, atr 106,
# signal_bar 105, trailing_atr 102 (target 98).
_BAR0 = (100, 105, 95, 100)
_BAR1 = (100, 101, 99, 100)
_LONG_LEVEL = {"percentage": 95.0, "points": 98.0, "atr": 94.0, "signal_bar": 95.0,
               "signal_bar_low": 94.99, "trailing_atr": 98.0}
_SHORT_LEVEL = {"percentage": 105.0, "points": 102.0, "atr": 106.0, "signal_bar": 105.0,
                "trailing_atr": 102.0}
_LONG_TYPES = [PCT, POINTS, ATR, SIGBAR, SBL, TRAIL_ATR]
_SHORT_TYPES = [PCT, POINTS, ATR, SIGBAR, TRAIL_ATR]   # signal_bar_low is long-only


def _ids(cfgs):
    return [c["type"] for c in cfgs]


class TestLabelMatrix:
    @pytest.mark.parametrize("cfg", _LONG_TYPES, ids=_ids(_LONG_TYPES))
    def test_long_at_level(self, cfg):
        df = _frame([_BAR0, _BAR1, (99, 100, 85, 90), (90, 91, 89, 90)])
        t = _run(df, [1, 0, 0, 0], cfg)[0]
        assert t["ExitReason"] == f"Stop Loss ({cfg['type']})"
        assert t["ExitPrice"] == pytest.approx(_LONG_LEVEL[cfg["type"]])

    @pytest.mark.parametrize("cfg", _LONG_TYPES, ids=_ids(_LONG_TYPES))
    def test_long_gap(self, cfg):
        df = _frame([_BAR0, _BAR1, (90, 91, 85, 88), (88, 89, 87, 88)])
        t = _run(df, [1, 0, 0, 0], cfg)[0]
        assert t["ExitReason"] == f"Stop Loss (gap, {cfg['type']})"
        assert t["ExitPrice"] == pytest.approx(90.0)

    @pytest.mark.parametrize("cfg", _SHORT_TYPES, ids=_ids(_SHORT_TYPES))
    def test_short_at_level(self, cfg):
        df = _frame([_BAR0, _BAR1, (101, 115, 100, 110), (110, 111, 109, 110)])
        t = _run(df, [-2, 0, 0, 0], cfg)[0]
        assert t["ExitReason"] == f"Stop Loss ({cfg['type']})"
        assert t["ExitPrice"] == pytest.approx(_SHORT_LEVEL[cfg["type"]])

    @pytest.mark.parametrize("cfg", _SHORT_TYPES, ids=_ids(_SHORT_TYPES))
    def test_short_gap(self, cfg):
        df = _frame([_BAR0, _BAR1, (110, 115, 109, 112), (112, 113, 111, 112)])
        t = _run(df, [-2, 0, 0, 0], cfg)[0]
        assert t["ExitReason"] == f"Stop Loss (gap, {cfg['type']})"
        assert t["ExitPrice"] == pytest.approx(110.0)

    @pytest.mark.parametrize("cfg", [PCT, ATR, SIGBAR], ids=["percentage", "atr", "signal_bar"])
    def test_fill_bar_check_labels(self, cfg):
        """The entry (fill) bar's own Low is checked against the stop (#426)."""
        df = _frame([_BAR0, (99, 100, 85, 90), (90, 91, 89, 90)])
        t = _run(df, [1, 0, 0], cfg)[0]
        assert t["EntryDate"] == t["ExitDate"]
        assert t["ExitReason"] == f"Stop Loss ({cfg['type']})"


# ---------------------------------------------------------------------------
class TestSblTrailLabel:
    TRAIL = {"type": "signal_bar_low", "offset": 0.01, "trail_atr": 0.1, "atr_period": 10}
    # Bar 2 spikes to 200, so from bar 4 the trail sits near 197 (#501 fixture).
    ROWS = [(100, 101, 95, 100), (100, 101, 99.5, 100), (100, 200, 99.5, 100),
            (101, 102, 100.7, 101)]

    def test_gapped_trail_stop(self):
        df = _frame(self.ROWS + [(101, 102, 100.7, 101), (101, 102, 100.7, 101)])
        t = _run(df, [1, 0, 0, 0, 0, 0], self.TRAIL)[0]
        assert pd.Timestamp(t["ExitDate"]) == df.index[4]
        assert t["ExitPrice"] == pytest.approx(101.0)
        assert t["ExitReason"] == "Stop Loss (gap, signal_bar_low trail)"

    def test_trail_stop_at_level(self):
        df = _frame(self.ROWS + [(199, 199, 150, 160), (160, 161, 159, 160)])
        t = _run(df, [1, 0, 0, 0, 0, 0], self.TRAIL)[0]
        assert pd.Timestamp(t["ExitDate"]) == df.index[4]
        assert 190.0 < t["ExitPrice"] < 199.0          # the trail level, not the open
        assert t["ExitReason"] == "Stop Loss (signal_bar_low trail)"

    def test_trail_that_never_moved_keeps_plain_label(self):
        # trail_atr so wide the candidate never clears the initial 94.99 stop.
        wide = {**self.TRAIL, "trail_atr": 50.0}
        df = _frame([_BAR0, _BAR1, (90, 91, 85, 88), (88, 89, 87, 88)])
        t = _run(df, [1, 0, 0, 0], wide)[0]
        assert t["ExitReason"] == "Stop Loss (gap, signal_bar_low)"
        df = _frame([_BAR0, _BAR1, (99, 100, 85, 90), (90, 91, 89, 90)])
        t = _run(df, [1, 0, 0, 0], wide)[0]
        assert t["ExitReason"] == "Stop Loss (signal_bar_low)"


# ---------------------------------------------------------------------------
class TestExitAtOpen:
    CFG = {"gap_below_stop_on_entry": "exit_at_open"}

    @pytest.mark.parametrize("cfg", [ATR, SIGBAR, SBL], ids=["atr", "signal_bar", "signal_bar_low"])
    def test_long(self, cfg):
        df = _frame([_BAR0, (90, 91, 88, 90), (90, 91, 89, 90)])
        t = _run(df, [1, 0, 0], cfg, self.CFG)
        assert len(t) == 1
        assert t[0]["EntryDate"] == t[0]["ExitDate"]
        assert t[0]["ExitPrice"] == pytest.approx(90.0)
        assert t[0]["ExitReason"] == f"Stop Loss (gap, {cfg['type']})"

    @pytest.mark.parametrize("cfg", [ATR, SIGBAR], ids=["atr", "signal_bar"])
    def test_short(self, cfg):
        df = _frame([_BAR0, (110, 112, 109, 110), (110, 111, 109, 110)])
        t = _run(df, [-2, 0, 0], cfg, self.CFG)
        assert len(t) == 1
        assert t[0]["EntryDate"] == t[0]["ExitDate"]
        assert t[0]["ExitPrice"] == pytest.approx(110.0)
        assert t[0]["ExitReason"] == f"Stop Loss (gap, {cfg['type']})"


# ---------------------------------------------------------------------------
class TestSblFallbackCounter:
    # Two entries on one symbol: signal bar0 -> stop at bar2; signal bar3 -> held.
    ROWS = [(100, 101, 95, 100), (100, 101, 99, 100), (99, 100, 90, 92),
            (92, 93, 91, 92), (92, 93, 91.5, 92), (92, 93, 91.5, 92)]
    SIG = [1, 0, 0, 1, 0, 0]

    def test_reason_is_registered_with_a_hint(self):
        kind, text = REASONS["sbl_adjusted_fallback"]
        assert kind == COVERAGE_DRIFT
        assert "raw_low" in text and "Low_raw" in text

    def test_counted_per_entry_when_only_the_adjusted_low_exists(self, caplog):
        df = _frame(self.ROWS)
        with caplog.at_level(logging.WARNING):
            res = _run(df, self.SIG, SBL, full=True)
        assert len(res["trade_log"]) == 2
        assert res["sizing_diagnostics"].get("sbl_adjusted_fallback") == 2
        # The once-per-symbol warning stays.
        assert caplog.text.count("signal_bar_low: no raw low for AAA") == 1

    def test_counted_per_symbol_entries(self):
        a, b = _frame(self.ROWS), _frame(self.ROWS)
        res = _run({"AAA": a, "BBB": b}, {"AAA": self.SIG, "BBB": [1, 0, 0, 0, 0, 0]},
                   SBL, full=True)
        assert res["sizing_diagnostics"].get("sbl_adjusted_fallback") == 3

    def test_not_counted_with_signal_aux_raw_low(self):
        df = _frame(self.ROWS)
        aux = pd.DataFrame({"raw_low": df["Low"]}, index=df.index)
        res = _run(df, self.SIG, SBL, aux=aux, full=True)
        assert len(res["trade_log"]) == 2
        assert "sbl_adjusted_fallback" not in res["sizing_diagnostics"]

    def test_not_counted_with_low_raw_column(self):
        df = _frame(self.ROWS)
        df["Low_raw"] = df["Low"]
        res = _run(df, self.SIG, SBL, full=True)
        assert len(res["trade_log"]) == 2
        assert "sbl_adjusted_fallback" not in res["sizing_diagnostics"]

    def test_stop_levels_unchanged_by_the_counter(self):
        """Same inputs with and without a raw low equal to the adjusted Low:
        identical trades; only the counter differs."""
        df = _frame(self.ROWS)
        plain = _run(df, self.SIG, SBL)
        df2 = df.copy()
        df2["Low_raw"] = df2["Low"]
        with_raw = _run(df2, self.SIG, SBL)
        assert plain == with_raw

    def test_not_counted_for_other_stop_types(self):
        res = _run(_frame(self.ROWS), self.SIG, SIGBAR, full=True)
        assert "sbl_adjusted_fallback" not in res["sizing_diagnostics"]

    def test_present_in_the_run_summary_report(self, caplog):
        df = _frame(self.ROWS)
        with caplog.at_level(logging.WARNING, logger="helpers.sizing_diagnostics"):
            _run(df, self.SIG, SBL)
        report = [r.getMessage() for r in caplog.records
                  if r.name == "helpers.sizing_diagnostics"]
        assert len(report) == 1, report
        assert report[0].startswith("Position sizing: 2 conditions recorded")
        assert "return raw_low" in report[0] and "Low_raw" in report[0]
        assert "e.g. AAA" in report[0]

    def test_format_report_line(self):
        d = SizingDiagnostics()
        d.record("sbl_adjusted_fallback", "AAA")
        out = d.format_report()
        assert "Position sizing: 1 condition recorded" in out
        assert COVERAGE_DRIFT in out and "Low_raw" in out


# ---------------------------------------------------------------------------
class TestSblFallbackCountsOnlyArmedStops:
    """#513: an entry whose signal_bar_low level was discarded by the protective
    guard (gap_below_stop_on_entry="ignore") has no stop, so it is not counted.
    Probe from the #512 review: signal bar Low 95, no raw low, next open 94."""
    ROWS = [(100, 101, 95, 100), (94, 96, 93, 95), (95, 96, 94, 95)]
    SIG = [1, 0, 0]

    def _res(self, mode):
        return _run(_frame(self.ROWS), self.SIG, SBL,
                    cfg_over={"gap_below_stop_on_entry": mode}, full=True)

    def test_ignore_mode_discarded_stop_is_not_counted(self):
        res = self._res("ignore")
        assert len(res["trade_log"]) == 1
        assert res["trade_log"][0]["ExitReason"] == "End of Backtest"
        assert "sbl_adjusted_fallback" not in res["sizing_diagnostics"]

    def test_exit_at_open_level_decides_the_exit_and_is_counted(self):
        res = self._res("exit_at_open")
        assert len(res["trade_log"]) == 1
        assert res["trade_log"][0]["ExitReason"] == "Stop Loss (gap, signal_bar_low)"
        assert res["sizing_diagnostics"].get("sbl_adjusted_fallback") == 1

    def test_skip_mode_declines_and_does_not_count(self):
        res = self._res("skip")
        assert res is None or len(res["trade_log"]) == 0
        if res is not None:
            assert "sbl_adjusted_fallback" not in res["sizing_diagnostics"]
            assert res["sizing_diagnostics"].get("skipped_gap_below_stop") == 1

    def test_ignore_mode_armed_stop_is_still_counted(self):
        """A level below the fill survives the guard under "ignore" and counts."""
        rows = [(100, 101, 95, 100), (99, 100, 97, 98), (98, 99, 97, 98)]
        res = _run(_frame(rows), self.SIG, SBL,
                   cfg_over={"gap_below_stop_on_entry": "ignore"}, full=True)
        assert len(res["trade_log"]) == 1
        assert res["sizing_diagnostics"].get("sbl_adjusted_fallback") == 1
