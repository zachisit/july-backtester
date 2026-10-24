"""
Regression tests for issue #314 — ``weekday_overnight_logic`` inverted its own
documented behavior under the engine's default ``execution_time="open"`` and did
not stay flat across exchange holidays.

The strategy is meant to hold every weeknight overnight and be flat across every
weekend/holiday gap (avoid gap risk). The old code emitted ``1`` on Mon–Thu and
``-1`` on Fri, which under open execution (signal fills next session's open) held
over every weekend. The fix derives the exit from the actual CALENDAR GAPS in the
index (interval > 2 days = a weekend/holiday gap) and is execution-aware.
"""

import numpy as np
import pandas as pd
import pytest

import config
import helpers.indicators as ind
from helpers.portfolio_simulations import run_portfolio_simulation


def _df(dates, base=100.0):
    idx = pd.DatetimeIndex(dates)
    close = np.linspace(base, base + len(idx) - 1, len(idx))
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": 1e6, "ATR_14": 1.0},
        index=idx,
    )


def _clean_weeks(weeks=2):
    return _df(pd.bdate_range("2024-01-01", periods=weeks * 5))  # Jan 1 2024 = Monday


class TestSignalMapping:
    def test_open_execution_two_clean_weeks(self, monkeypatch):
        monkeypatch.setitem(config.CONFIG, "execution_time", "open")
        sig = ind.weekday_overnight_logic(_clean_weeks(2))["Signal"].tolist()
        # wk1: Mon,Tue,Wed hold; Thu exits (fills Fri open); Fri holds (fills next Mon).
        # wk2: same, but the trailing Fri has no next week -> flattened.
        assert sig == [1, 1, 1, -1, 1, 1, 1, 1, -1, -1]

    def test_close_execution_two_clean_weeks(self, monkeypatch):
        monkeypatch.setitem(config.CONFIG, "execution_time", "close")
        sig = ind.weekday_overnight_logic(_clean_weeks(2))["Signal"].tolist()
        # close fills same session: exit on Friday (last session before the gap).
        assert sig == [1, 1, 1, 1, -1, 1, 1, 1, 1, -1]

    def test_default_config_uses_open_mapping(self, monkeypatch):
        # No execution_time key at all -> defaults to "open".
        monkeypatch.delitem(config.CONFIG, "execution_time", raising=False)
        sig = ind.weekday_overnight_logic(_clean_weeks(2))["Signal"].tolist()
        assert sig == [1, 1, 1, -1, 1, 1, 1, 1, -1, -1]


class TestHolidayWeeks:
    def test_open_friday_holiday_exits_before_the_long_weekend(self, monkeypatch):
        # Good Friday 2024-03-29 missing: Mon-Thu then next Mon. The Thu->Mon gap
        # is 4 days, so the exit must fill at Thursday's open -> -1 on Wednesday.
        monkeypatch.setitem(config.CONFIG, "execution_time", "open")
        dates = ["2024-03-25", "2024-03-26", "2024-03-27", "2024-03-28",  # Mon-Thu
                 "2024-04-01", "2024-04-02", "2024-04-03", "2024-04-04", "2024-04-05"]
        sig = ind.weekday_overnight_logic(_df(dates))["Signal"]
        # Wednesday 03-27 is the exit (its fill bar Thu 03-28 precedes the 4-day gap).
        assert sig.loc["2024-03-27"] == -1
        assert sig.loc["2024-03-28"] == 1   # Thu holds -> fills next Mon

    def test_open_thursday_holiday_stays_flat_over_weekend(self, monkeypatch):
        # Thanksgiving 2024-11-28 (Thu) missing: Mon,Tue,Wed,Fri then next Mon.
        # The exit must fill at Friday 11/29's open so the position is flat across
        # the Fri->Mon weekend. Under open execution that exit is emitted on Wed
        # 11/27 (its fill bar Fri 11/29 precedes the 3-day weekend gap). The
        # mid-week Thu-holiday gap (Wed->Fri = 2 days) is a normal hold, not a
        # weekend, so it is held — the strategy targets weekend risk.
        monkeypatch.setitem(config.CONFIG, "execution_time", "open")
        dates = ["2024-11-25", "2024-11-26", "2024-11-27", "2024-11-29",  # Mon,Tue,Wed,Fri
                 "2024-12-02", "2024-12-03", "2024-12-04", "2024-12-05", "2024-12-06"]
        sig = ind.weekday_overnight_logic(_df(dates))["Signal"]
        assert sig.loc["2024-11-27"] == -1   # Wed exits -> fills Fri 11/29 open
        assert sig.loc["2024-11-29"] == 1    # Fri re-enters (fills next Mon) -> flat weekend


class TestEngineWeekendFlat:
    def test_open_execution_never_spans_a_weekend(self, monkeypatch):
        monkeypatch.setitem(config.CONFIG, "execution_time", "open")
        monkeypatch.setitem(config.CONFIG, "slippage_pct", 0.0)
        monkeypatch.setitem(config.CONFIG, "exclude_open_positions", True)
        monkeypatch.setitem(config.CONFIG, "position_sizing_method", "fixed")
        df = _clean_weeks(4)
        sig = ind.weekday_overnight_logic(df.copy())["Signal"]
        res = run_portfolio_simulation(
            portfolio_data={"SPY": df}, signals={"SPY": sig},
            initial_capital=100_000.0, allocation_pct=0.1,   # deterministic sizing
            spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"},
        )
        trades = res["trade_log"] if res else []
        assert len(trades) >= 3
        for t in trades:
            entry = pd.Timestamp(t["EntryDate"]); exit_ = pd.Timestamp(t["ExitDate"])
            assert exit_.dayofweek == 4, f"exit not Friday (weekend held): {t['ExitDate']}"
            assert (exit_ - entry).days <= 4, f"trade spans a weekend: {t}"
        # After the first trade, entries are Mondays (the first may be Tuesday —
        # bar 0 is a Monday with no prior Friday signal to fill from).
        for t in trades[1:]:
            assert pd.Timestamp(t["EntryDate"]).dayofweek == 0


class TestVixFilterVariant:
    def test_vix_spike_suppresses_the_gated_entry(self, monkeypatch):
        # The registered production strategy. A high VIX must force the signal to
        # -1 (flat) even on a would-be hold day; low VIX leaves the hold intact.
        monkeypatch.setitem(config.CONFIG, "execution_time", "open")
        df = _clean_weeks(2)
        vix_calm = _df(df.index, base=10.0)   # VIX ~10 < 20 threshold
        out_calm = ind.weekday_overnight_with_vix_filter_logic(df.copy(), vix_calm)
        # calm: identical to the base hold signal on hold days.
        base = ind.weekday_overnight_logic(df.copy())["Signal"]
        assert (out_calm["Signal"].to_numpy()[base.to_numpy() == 1] == 1).all()

        vix_spike = _df(df.index, base=50.0)  # VIX ~50 > 20 threshold
        out_spike = ind.weekday_overnight_with_vix_filter_logic(df.copy(), vix_spike)
        assert (out_spike["Signal"] == -1).all()   # every day forced flat
