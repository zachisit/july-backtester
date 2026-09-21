"""
Regression test for issue #316 — ``chaikin_money_flow_with_stop_loss_logic``
could only ever take one trade.

The wrapper derived entry events from ``df_base['Signal'].diff() == 1``. But
``df_base['Signal']`` is the base strategy's already-ffilled state (…,1,1,-1,-1,
1,1,…), so after the first ``0 -> 1`` every re-entry is a ``-1 -> 1`` transition
with diff ``2`` — never equal to 1. Only the first entry ever fired; every
subsequent CMF buy was silently dropped.

Fix: detect entries/exits as state transitions, not fixed diff magnitudes.
"""

import numpy as np
import pandas as pd
import pytest

import helpers.indicators as ind


@pytest.fixture
def patched_base(monkeypatch):
    # Base state with TWO long episodes: bars 2-3 and bars 6-7.
    state = [0, 0, 1, 1, -1, -1, 1, 1, -1, -1]

    def _fake_base(df, *a, **k):
        df = df.copy()
        df["Signal"] = np.array(state, dtype=float)
        return df
    monkeypatch.setattr(ind, "chaikin_money_flow_logic", _fake_base)
    return state


def _price_df(n=10, close=100.0):
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,  # Low 99 > 97 stop
         "Close": close, "Volume": 1e6},
        index=idx,
    )


def _long_entries(signal):
    s = signal.astype(int)
    return int(((s == 1) & (s.shift(1) != 1)).sum())


class TestCmfStopReentry:
    def test_reentry_after_exit_is_detected(self, patched_base):
        out = ind.chaikin_money_flow_with_stop_loss_logic(_price_df())
        # Both long episodes must produce an entry (the old code caught only 1).
        assert _long_entries(out["Signal"]) == 2

    def test_second_long_episode_present_in_signal(self, patched_base):
        sig = ind.chaikin_money_flow_with_stop_loss_logic(_price_df())["Signal"].tolist()
        # bars 6-7 must be long (1) again, not stuck flat/-1 from the first exit.
        assert sig[6] == 1 and sig[7] == 1

    def test_stop_loss_fires_on_the_crash_bar(self, monkeypatch, patched_base):
        # Entry bar 2 (Close 100); crash at bar 3 below the 3% stop (97). The CMF
        # exit isn't until bar 4, so a -1 AT bar 3 can only come from the stop.
        df = _price_df()
        df.loc[df.index[3], "Low"] = 90.0   # 90 < 100*(1-0.03)=97 -> stop
        out = ind.chaikin_money_flow_with_stop_loss_logic(df)
        assert out["Signal"].iloc[2] == 1     # entered first
        assert out["Signal"].iloc[3] == -1    # stop exit on the crash bar

    def test_continuous_long_run_is_exactly_one_entry(self, monkeypatch):
        # A single uninterrupted long run must produce exactly ONE entry — guards
        # against a regression to level-based (s==1) instead of transition-based.
        state = [0, 1, 1, 1, 1, 1]
        monkeypatch.setattr(ind, "chaikin_money_flow_logic",
                            lambda df, *a, **k: df.assign(Signal=np.array(state, float)))
        out = ind.chaikin_money_flow_with_stop_loss_logic(_price_df(6))
        assert _long_entries(out["Signal"]) == 1

    def test_base_starting_with_sell_has_no_leading_short(self, monkeypatch):
        # First base event is a sell (0->-1); while flat that must be a no-op, and
        # the first entry fires on the -1->1 bar. No -1 before the first entry.
        state = [0, 0, -1, -1, 1, 1, -1, -1]
        monkeypatch.setattr(ind, "chaikin_money_flow_logic",
                            lambda df, *a, **k: df.assign(Signal=np.array(state, float)))
        sig = ind.chaikin_money_flow_with_stop_loss_logic(_price_df(8))["Signal"].tolist()
        first_entry = sig.index(1)
        assert -1 not in sig[:first_entry]     # no leading short while flat
        assert sig[4] == 1                     # entry on the -1->1 transition

    def test_no_reentry_after_stop_until_base_cycles(self, monkeypatch):
        # Long run bars 1..6; stop crashes bar 3. Must stay flat through bars 3-7
        # (base still ==1, no fresh crossover) and only re-enter at bar 8 (-1->1).
        state = [0, 1, 1, 1, 1, 1, 1, -1, 1, 1]
        monkeypatch.setattr(ind, "chaikin_money_flow_logic",
                            lambda df, *a, **k: df.assign(Signal=np.array(state, float)))
        df = _price_df(10)
        df.loc[df.index[3], "Low"] = 90.0   # stop at bar 3
        sig = ind.chaikin_money_flow_with_stop_loss_logic(df)["Signal"].tolist()
        assert sig[3] == -1
        assert all(s == -1 for s in sig[3:8]), f"re-entered before base cycled: {sig}"
        assert sig[8] == 1                    # fresh -1->1 crossover re-enters


class TestCmfStopRealBase:
    def test_two_crossovers_produce_two_entries_end_to_end(self):
        # Real (unpatched) base with length=2: Close alternates High/Low so CMF
        # swings across the +/-0.05 thresholds twice -> two entries.
        mfm = [-1, -1, 1, 1, 1, -1, -1, -1, 1, 1, 1]  # +1 when Close=High, -1 when Close=Low
        close = [101.0 if m > 0 else 99.0 for m in mfm]
        idx = pd.bdate_range("2024-01-02", periods=len(mfm))
        df = pd.DataFrame({"Open": close, "High": 101.0, "Low": 99.0,
                           "Close": close, "Volume": 1e6}, index=idx)
        out = ind.chaikin_money_flow_with_stop_loss_logic(df, length=2)
        assert _long_entries(out["Signal"]) >= 2
