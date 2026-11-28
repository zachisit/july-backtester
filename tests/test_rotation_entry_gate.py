"""tests/test_rotation_entry_gate.py

``run_rotation(..., entry_gate=...)`` (issue #515): a gate that blocks NEW buys
(and drift top-ups) while keeping existing holdings, unlike ``regime_gate``
which liquidates the book. Synthetic data only, no network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from helpers import rotation
from helpers.registry import register_rotation


def _make_df(prices, start="2020-01-01"):
    idx = pd.date_range(start, periods=len(prices), freq="D")
    p = np.asarray(prices, dtype=float)
    return pd.DataFrame(
        {"Open": p, "High": p * 1.01, "Low": p * 0.99, "Close": p, "Volume": 1e6},
        index=idx,
    )


def _linear_universe(n_days=120):
    base = np.arange(n_days, dtype=float)
    return {
        "STRONG": _make_df(100 + base * 2.0),
        "MID": _make_df(100 + base * 1.0),
        "WEAK": _make_df(100 + base * 0.3),
        "FLAT": _make_df(np.full(n_days, 200.0)),
    }


def _momentum_rank(lookback=20):
    def rank(data, rebalance_date, **kwargs):
        scores = {}
        for sym, df in data.items():
            w = df.loc[:rebalance_date]
            if len(w) <= lookback:
                continue
            past = w["Close"].iloc[-lookback - 1]
            if past > 0:
                scores[sym] = float(w["Close"].iloc[-1] / past - 1.0)
        return scores
    return rank


def _scripted_rank(schedule):
    """Ranking from a ``[(start_date, [syms...]), ...]`` schedule (latest start
    at/before the rebalance date wins)."""
    sched = [(pd.Timestamp(d), syms) for d, syms in schedule]

    def rank(data, rebalance_date, **kwargs):
        cur = []
        for d, syms in sched:
            if pd.Timestamp(rebalance_date) >= d:
                cur = syms
        return list(cur)
    return rank


def _cfg(**rot):
    r = {"enabled": True, "top_n": 2, "rebalance_days": 10, "weighting": "equal",
         "sell_buffer_rank": 0, "drift_trim_pct": 0.0}
    r.update(rot)
    return {
        "initial_capital": 100_000.0, "allocation_per_trade": 0.10,
        "max_position_pct": 1.0, "commission_per_share": 0.0, "slippage_pct": 0.0,
        "rotation": r, "instruments": {"default_asset_class": "equity"},
    }


def _entry_dates(res, sym):
    return [pd.Timestamp(t["EntryDate"]) for t in res["trade_log"] if t["Symbol"] == sym]


CUTOFF = pd.Timestamp("2020-02-01")


class TestDefaultUnchanged:
    def test_none_gate_is_byte_identical(self):
        data = _linear_universe()
        a = rotation.run_rotation(data, _momentum_rank(), _cfg())
        b = rotation.run_rotation(data, _momentum_rank(), _cfg(), entry_gate=None)
        assert a.keys() == b.keys()
        assert "entry_gate_blocked_entries" not in a
        assert a["trade_log"] == b["trade_log"]
        pd.testing.assert_series_equal(a["portfolio_timeline"], b["portfolio_timeline"])

    def test_always_open_gate_matches_default(self):
        data = _linear_universe()
        a = rotation.run_rotation(data, _momentum_rank(), _cfg())
        b = rotation.run_rotation(data, _momentum_rank(), _cfg(),
                                  entry_gate=lambda d, dt: True)
        assert a["trade_log"] == b["trade_log"]
        pd.testing.assert_series_equal(a["portfolio_timeline"], b["portfolio_timeline"])
        assert b["entry_gate_closed_rebalances"] == 0
        assert b["entry_gate_blocked_entries"] == 0


class TestGateClosed:
    def test_holdings_kept_no_new_names(self):
        # A,B ranked first; from the cutoff C,D replace B (A stays). The gate
        # closes at the cutoff: B is sold, A is held, C is NOT bought.
        data = {s: _make_df(np.full(90, 100.0)) for s in "ABCD"}
        rank = _scripted_rank([("2020-01-01", ["A", "B"]),
                               ("2020-02-01", ["A", "C", "D"])])
        gate = lambda d, dt: pd.Timestamp(dt) < CUTOFF
        res = rotation.run_rotation(data, rank, _cfg(), entry_gate=gate)
        assert res is not None
        # A held throughout -> one trade closed at end of backtest.
        a_trades = [t for t in res["trade_log"] if t["Symbol"] == "A"]
        assert len(a_trades) == 1 and a_trades[0]["ExitReason"] == "End of Backtest"
        # B sold on rank drop while gated (sells still execute).
        b_trades = [t for t in res["trade_log"] if t["Symbol"] == "B"]
        assert len(b_trades) == 1 and b_trades[0]["ExitReason"] == "Rank Drop"
        # C never bought.
        assert not any(t["Symbol"] in ("C", "D") for t in res["trade_log"])
        assert res["entry_gate_closed_rebalances"] > 0
        assert res["entry_gate_blocked_entries"] > 0

    def test_ungated_run_does_buy_the_new_name(self):
        # Control for the test above: without the gate C IS bought.
        data = {s: _make_df(np.full(90, 100.0)) for s in "ABCD"}
        rank = _scripted_rank([("2020-01-01", ["A", "B"]),
                               ("2020-02-01", ["A", "C", "D"])])
        res = rotation.run_rotation(data, rank, _cfg())
        assert any(t["Symbol"] == "C" for t in res["trade_log"])

    def test_empty_slot_stays_in_cash_and_held_weight_unchanged(self):
        # Flat prices: after B is sold under the gate, A keeps its ~50% weight
        # (no re-spread / top-up to 100%) and the rest sits in cash.
        data = {s: _make_df(np.full(90, 100.0)) for s in "ABC"}
        rank = _scripted_rank([("2020-01-01", ["A", "B"]),
                               ("2020-02-01", ["A", "C"])])
        gate = lambda d, dt: pd.Timestamp(dt) < CUTOFF
        res = rotation.run_rotation(data, rank, _cfg(), entry_gate=gate)
        a = [t for t in res["trade_log"] if t["Symbol"] == "A"]
        assert len(a) == 1
        assert a[0]["Shares"] == pytest.approx(500.0)  # 50k / $100, never topped up

    def test_drift_top_up_blocked_but_trim_allowed(self):
        # top_n=2, A falls (under-weight -> would be topped up), B rises
        # (over-weight -> trimmed). Gate closed after the first rebalance.
        n = 90
        a = np.linspace(100, 50, n)
        b = np.linspace(100, 150, n)
        data = {"A": _make_df(a), "B": _make_df(b)}
        rank = lambda d, dt, **k: ["A", "B"]
        gate = lambda d, dt: pd.Timestamp(dt) < pd.Timestamp("2020-01-05")
        gated = rotation.run_rotation(data, rank, _cfg(), entry_gate=gate)
        free = rotation.run_rotation(data, rank, _cfg())
        a_g = [t for t in gated["trade_log"] if t["Symbol"] == "A"]
        a_f = [t for t in free["trade_log"] if t["Symbol"] == "A"]
        # Ungated A is topped up (more shares at the end); gated A never grows.
        assert sum(t["Shares"] for t in a_f) > sum(t["Shares"] for t in a_g)
        # Initial buy: signal on bar 0, fill at bar 1's open, 50% of equity.
        assert sum(t["Shares"] for t in a_g) == pytest.approx(50_000.0 / a[1])
        # Trims of B still run while gated.
        assert any(t["Symbol"] == "B" and t["ExitReason"] != "End of Backtest"
                   for t in gated["trade_log"])

    def test_reopened_gate_buys_again(self):
        data = {s: _make_df(np.full(90, 100.0)) for s in "ABC"}
        rank = _scripted_rank([("2020-01-01", ["A", "B"]),
                               ("2020-02-01", ["A", "C"])])
        gate = lambda d, dt: not (CUTOFF <= pd.Timestamp(dt) < pd.Timestamp("2020-02-20"))
        res = rotation.run_rotation(data, rank, _cfg(), entry_gate=gate)
        c = _entry_dates(res, "C")
        assert c and min(c) >= pd.Timestamp("2020-02-20")


class TestPrecedenceAndFailure:
    def test_regime_gate_false_liquidates_and_entry_gate_not_called(self):
        data = _linear_universe()
        calls = []

        def egate(d, dt):
            calls.append(pd.Timestamp(dt))
            return True

        rgate = lambda d, dt: pd.Timestamp(dt) < CUTOFF
        res = rotation.run_rotation(data, _momentum_rank(), _cfg(),
                                    regime_gate=rgate, entry_gate=egate)
        assert "Regime Off" in {t["ExitReason"] for t in res["trade_log"]}
        assert calls and max(calls) < CUTOFF

    def test_regime_off_with_entry_gate_closed_still_liquidates(self):
        data = _linear_universe()
        rgate = lambda d, dt: pd.Timestamp(dt) < CUTOFF
        res = rotation.run_rotation(data, _momentum_rank(), _cfg(),
                                    regime_gate=rgate, entry_gate=lambda d, dt: False)
        # The entry gate never opens, so nothing was ever bought ...
        assert res is None

    def test_exception_fails_open(self, caplog):
        data = _linear_universe()

        def bad(d, dt):
            raise RuntimeError("boom")

        base = rotation.run_rotation(data, _momentum_rank(), _cfg())
        with caplog.at_level("WARNING"):
            res = rotation.run_rotation(data, _momentum_rank(), _cfg(), entry_gate=bad)
        assert "entry_gate raised" in caplog.text
        assert res["trade_log"] == base["trade_log"]
        assert res["entry_gate_closed_rebalances"] == 0


class TestNoLookAhead:
    def test_gate_receives_signal_date_and_sees_no_future_bar(self):
        data = _linear_universe()
        seen = []

        def gate(d, dt):
            seen.append(pd.Timestamp(dt))
            return True

        rotation.run_rotation(data, _momentum_rank(), _cfg(), entry_gate=gate)
        rebal = rotation.build_rebalance_dates(data, 10)
        # Called with signal (rebalance) dates, never the next-bar exec date.
        # The terminal rebalance has no exec bar and is skipped before gating.
        assert seen == [pd.Timestamp(d) for d in rebal[:len(seen)]]
        assert set(seen) <= {pd.Timestamp(d) for d in rebal}

    def test_blocked_buy_fill_is_not_on_signal_bar(self):
        # Gate opens on a signal date: the buy fills on the NEXT bar's open.
        data = {s: _make_df(np.full(90, 100.0)) for s in "AB"}
        rank = lambda d, dt, **k: ["A", "B"]
        rebal = rotation.build_rebalance_dates(data, 10)
        open_on = pd.Timestamp(rebal[2])
        gate = lambda d, dt: pd.Timestamp(dt) >= open_on
        res = rotation.run_rotation(data, rank, _cfg(), entry_gate=gate)
        entries = {pd.Timestamp(t["EntryDate"]) for t in res["trade_log"]}
        assert entries == {open_on + pd.Timedelta(days=1)}


class TestConfigEntryWiring:
    def test_register_rotation_stores_entry_gate(self):
        from helpers.registry import REGISTRY
        g = lambda d, dt: True

        @register_rotation(name="test-entry-gate-store", entry_gate=g)
        def _r(data, rebalance_date, **kwargs):
            return []

        assert REGISTRY["test-entry-gate-store"]["entry_gate"] is g

    def test_run_rotation_from_config_passes_entry_gate(self):
        name = "test-entry-gate-cfg"
        calls = []

        def gate(d, dt):
            calls.append(dt)
            return pd.Timestamp(dt) < CUTOFF

        @register_rotation(name=name, entry_gate=gate)
        def _r(data, rebalance_date, **kwargs):
            return _momentum_rank()(data, rebalance_date)

        data = _linear_universe()
        cfg = _cfg()
        cfg["rotation"]["rank_strategy"] = name
        res = rotation.run_rotation_from_config(data, cfg)
        assert calls
        assert "entry_gate_closed_rebalances" in res
        assert res["entry_gate_closed_rebalances"] > 0
