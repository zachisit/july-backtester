# tests/test_entry_bar_stop.py
"""
Issue #426: under execution_time="open" the stop must be live on the fill bar.

Signal on bar0 -> fill at bar1 Open (100). Bar1 trades down (long) / up (short)
through the 5% stop; later bars recover and never retouch it.
"""

import os
import sys
from unittest.mock import patch

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.portfolio_simulations import run_portfolio_simulation  # noqa: E402
from tests.test_stop_gap_fill import BASE_CFG, SLIP  # noqa: E402

PCT = {"type": "percentage", "value": 0.05}
N = 5


def _frame(opens, highs, lows, closes):
    idx = pd.bdate_range("2024-01-02", periods=len(closes))
    idx.name = "Datetime"
    return pd.DataFrame({"Open": opens, "High": highs, "Low": lows, "Close": closes,
                         "Volume": [1e6] * len(closes)}, index=idx)


def _run(df, sig_vals, cfg_over=None, stop=PCT):
    sig = pd.Series(sig_vals, index=df.index)
    cfg = {**BASE_CFG, "execution_time": "open", **(cfg_over or {})}
    with patch.dict("config.CONFIG", cfg, clear=False):
        return run_portfolio_simulation(
            portfolio_data={"AAA": df}, signals={"AAA": sig},
            initial_capital=100_000.0, allocation_pct=0.10,
            spy_df=None, vix_df=None, tnx_df=None, stop_config=stop)["trade_log"]


def _long_df(fill_low):
    return _frame([100, 100, 101, 102, 103], [101, 101, 103, 104, 106],
                  [99, fill_low, 100, 101, 102], [100, 100, 102, 103, 105])


def _short_df(fill_high):
    return _frame([100, 100, 99, 98, 97], [101, fill_high, 100, 99, 98],
                  [99, 99, 97, 96, 95], [100, 100, 98, 97, 96])


class TestLongFillBar:
    def test_low_below_stop_exits_same_bar_at_stop(self):
        t = _run(_long_df(90), [1, 0, 0, 0, 0])
        assert len(t) == 1
        tr = t[0]
        assert tr["EntryDate"] == tr["ExitDate"] == "2024-01-03T00:00:00"
        assert tr["ExitReason"] == "Stop Loss (percentage)"
        stop = 100 * (1 + SLIP) * 0.95
        assert tr["ExitPrice"] == pytest.approx(stop * (1 - SLIP), abs=1e-6)
        assert tr["Profit"] < 0
        assert tr["RMultiple"] is not None and tr["MAE_pct"] < 0

    def test_low_above_stop_keeps_position(self):
        t = _run(_long_df(97), [1, 0, 0, 0, 0])
        assert len(t) == 1
        assert t[0]["ExitReason"] == "End of Backtest"
        assert t[0]["Profit"] > 0

    def test_legacy_toggle_reproduces_old_behaviour(self):
        t = _run(_long_df(90), [1, 0, 0, 0, 0], {"entry_bar_stop_check": False})
        assert t[0]["ExitReason"] == "End of Backtest"

    def test_close_execution_has_no_same_bar_check(self):
        # Close fill: the bar's Low printed before the fill, so it is not compared.
        t = _run(_long_df(90), [0, 1, 0, 0, 0], {"execution_time": "close"})
        assert t[0]["ExitReason"] == "End of Backtest"

    def test_signal_bar_stop_checked_on_fill_bar(self):
        # Structural stop at the signal bar's low (99); fill bar trades down to 95.
        df = _frame([100, 100, 101, 102, 103], [101, 101, 103, 104, 106],
                    [99, 95, 100, 101, 102], [100, 100, 102, 103, 105])
        t = _run(df, [1, 0, 0, 0, 0], stop={"type": "signal_bar"})
        assert t[0]["EntryDate"] == t[0]["ExitDate"]
        assert t[0]["ExitReason"].startswith("Stop Loss")
        assert t[0]["ExitPrice"] == pytest.approx(99 * (1 - SLIP), abs=1e-6)


class TestShortFillBar:
    def test_high_above_stop_covers_same_bar_at_stop(self):
        t = _run(_short_df(110), [-2, 0, 0, 0, 0])
        assert len(t) == 1
        tr = t[0]
        assert tr["EntryDate"] == tr["ExitDate"] == "2024-01-03T00:00:00"
        assert tr["ExitReason"] == "Stop Loss (percentage)"
        assert tr["ExitPrice"] == pytest.approx(100 * 1.05 * (1 + SLIP), abs=1e-6)
        assert tr["Profit"] < 0

    def test_high_below_stop_keeps_position(self):
        t = _run(_short_df(103), [-2, 0, 0, 0, 0])
        assert t[0]["ExitReason"] != "Stop Loss (percentage)" or t[0]["EntryDate"] != t[0]["ExitDate"]
        assert t[0]["EntryDate"] != t[0]["ExitDate"]

    def test_close_execution_has_no_same_bar_check(self):
        t = _run(_short_df(110), [0, -2, 0, 0, 0], {"execution_time": "close"})
        assert t[0]["EntryDate"] != t[0]["ExitDate"] or t[0]["ExitReason"] != "Stop Loss (percentage)"
