"""tests/test_rotation_idle_cash.py

Idle cash earns a return in the rotation engine (issue #516):
``rotation.cash_rate_annual`` (fixed rate, per trading day) and
``rotation.cash_sweep_symbol`` (idle cash follows an instrument's
close-to-close return).

Pure, deterministic, synthetic data, no network.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

from helpers import rotation
from helpers import registry as _registry
from helpers.registry import register_rotation

C0 = 100_000.0
DAILY_5PCT = 1.05 ** (1.0 / 252) - 1.0


# ---------------------------------------------------------------------------
# Synthetic helpers
# ---------------------------------------------------------------------------
def _make_df(closes, start="2020-01-01", opens=None, index=None):
    idx = index if index is not None else pd.date_range(start, periods=len(closes), freq="D")
    c = np.asarray(closes, dtype=float)
    o = np.asarray(opens, dtype=float) if opens is not None else c
    return pd.DataFrame(
        {"Open": o, "High": np.maximum(o, c) * 1.01, "Low": np.minimum(o, c) * 0.99,
         "Close": c, "Volume": 1e6},
        index=idx,
    )


def _cfg(initial_capital=C0, commission=0.0, slippage=0.0, alloc=0.10, **rot):
    r = {"enabled": True, "top_n": 1, "rebalance_days": 10, "weighting": "equal",
         "sell_buffer_rank": 0, "drift_trim_pct": 0.0}
    r.update(rot)
    return {
        "initial_capital": initial_capital,
        "allocation_per_trade": alloc,
        "max_position_pct": 1.0,
        "commission_per_share": commission,
        "slippage_pct": slippage,
        "rotation": r,
        "instruments": {"default_asset_class": "equity"},
    }


def _two_fund_universe(n=60):
    t = np.arange(n, dtype=float)
    return {
        "A": _make_df(100 + t * 0.5, opens=100 + t * 0.5 - 0.2),
        "B": _make_df(50 + t * 0.1, opens=50 + t * 0.1 + 0.05),
    }


def _rank_from(first_date, syms=("A",)):
    """Rank nothing (stay in cash) before *first_date*, then always *syms*."""
    def rank(data, rebalance_date, **kw):
        if rebalance_date < first_date:
            return {}
        return {s: float(len(syms) - i) for i, s in enumerate(syms) if s in data}
    return rank


def _always(syms=("A",)):
    return _rank_from(pd.Timestamp("1900-01-01"), syms)


def _golden_universe(n=90):
    """Noisy deterministic universe exercising rank drops, trims, adds and the
    regime gate (for the byte-for-byte default test)."""
    t = np.arange(n, dtype=float)
    out = {}
    for k, (drift, amp, ph) in {"P": (0.4, 3.0, 0.0), "Q": (0.25, 5.0, 1.3),
                                "R": (0.1, 2.0, 2.1), "S": (-0.05, 4.0, 0.7)}.items():
        c = 80 + drift * t + amp * np.sin(t / 4.0 + ph)
        out[k] = _make_df(c, opens=c + 0.3 * np.cos(t / 3.0 + ph))
    return out


def _golden_rank(data, rebalance_date, lookback=8, **kw):
    scores = {}
    for s, df in data.items():
        w = df.loc[:rebalance_date]
        if len(w) > lookback:
            scores[s] = float(w["Close"].iloc[-1] / w["Close"].iloc[-lookback - 1] - 1)
    return scores


def _golden_gate(data, rebalance_date):
    d = rebalance_date - pd.Timestamp("2020-01-01")
    return not (35 <= d.days < 55)


def _golden_cfg(**extra):
    return _cfg(commission=0.005, slippage=0.001, top_n=2, rebalance_days=7,
                sell_buffer_rank=1, drift_trim_pct=0.02, **extra)


# Pinned from origin/main BEFORE #516 (helpers/rotation.py at e76c7fc) on the
# golden scenario above — proves the default path is byte-for-byte unchanged.
# The scenario hits every exit path: Rank Drop, Rebalance Trim, Regime Off and
# End of Backtest.
GOLDEN_PNL_PERCENT = -0.0164925283132783
GOLDEN_TIMELINE_SUM = 9125814.604032326
GOLDEN_PROFITS = [
    1350.2598754339567, 1370.3659043834189, -1495.3493195387844, 1046.256638299038,
    -4533.620750429753, -31.229984066811767, 1755.1591390125259, 69.67686137913779,
    -2786.1914775688306, 159.94329231215852, 3726.055738345482, -2384.4463798590505,
]


# ---------------------------------------------------------------------------
# Default unchanged
# ---------------------------------------------------------------------------
class TestDefaultUnchanged:
    def _run(self, **extra):
        return rotation.run_rotation(_golden_universe(), _golden_rank, _golden_cfg(**extra),
                                     regime_gate=_golden_gate)

    def test_matches_pre_change_golden_master(self):
        res = self._run()
        assert res["pnl_percent"] == GOLDEN_PNL_PERCENT
        assert float(res["portfolio_timeline"].sum()) == GOLDEN_TIMELINE_SUM
        assert [t["Profit"] for t in res["trade_log"]] == GOLDEN_PROFITS

    @pytest.mark.parametrize("extra", [
        {"cash_rate_annual": 0.0},
        {"cash_sweep_symbol": None},
        {"cash_rate_annual": 0.0, "cash_sweep_symbol": None},
        {"cash_rate_annual": None, "cash_sweep_symbol": ""},
    ])
    def test_explicit_off_identical_to_absent(self, extra):
        base, off = self._run(), self._run(**extra)
        pd.testing.assert_series_equal(base["portfolio_timeline"], off["portfolio_timeline"],
                                       check_exact=True)
        assert base["trade_log"] == off["trade_log"]
        assert base["pnl_percent"] == off["pnl_percent"]
        assert "cash_interest_total" not in off
        assert "cash_yield_mode" not in off


# ---------------------------------------------------------------------------
# Fixed-rate accrual
# ---------------------------------------------------------------------------
class TestFixedRate:
    def _late_buy(self, rate):
        data = _two_fund_universe()
        first = data["A"].index[30]   # rebalance at idx 30 -> fill idx 31
        return data, rotation.run_rotation(data, _rank_from(first),
                                           _cfg(cash_rate_annual=rate))

    def test_exact_compounding_on_all_cash_account(self):
        _, res = self._late_buy(0.05)
        tl = res["portfolio_timeline"].to_numpy()
        for i in range(31):
            assert tl[i] == pytest.approx(C0 * (1 + DAILY_5PCT) ** i, rel=1e-12)
        assert res["cash_yield_mode"] == "fixed"

    def test_accrual_funds_later_buys(self):
        data, res = self._late_buy(0.05)
        _, base = self._late_buy(0.0)
        buy = res["trade_log"][0]
        assert buy["EntryDate"] == data["A"].index[31].isoformat()
        open31 = data["A"]["Open"].iloc[31]
        # Interest through the prior close (30 accrual days) funds the fill.
        assert buy["Shares"] == pytest.approx(C0 * (1 + DAILY_5PCT) ** 30 / open31, rel=1e-12)
        assert buy["Shares"] > base["trade_log"][0]["Shares"]

    def test_equity_rises_every_day_not_only_at_rebalances(self):
        _, res = self._late_buy(0.05)
        tl = res["portfolio_timeline"].to_numpy()[:31]
        assert np.all(np.diff(tl) > 0)
        # Rebalances are every 10 bars; days strictly between them still move.
        assert tl[5] > tl[4] > tl[3]

    def test_interest_only_on_idle_portion(self):
        data = _two_fund_universe()
        cfg = _cfg(cash_rate_annual=0.05, weighting="fixed_alloc", alloc=0.4,
                   rebalance_days=1000)
        res = rotation.run_rotation(data, _always(), cfg)
        (trade,) = res["trade_log"]          # single buy at idx 1, held to the end
        shares = trade["Shares"]
        closes = data["A"]["Close"].to_numpy()
        tl = res["portfolio_timeline"].to_numpy()
        for i in range(2, len(tl)):
            idle_prev = tl[i - 1] - shares * closes[i - 1]
            assert tl[i] - shares * closes[i] == pytest.approx(idle_prev * (1 + DAILY_5PCT),
                                                               rel=1e-12)
        idle_after_buy = tl[1] - shares * closes[1]
        assert idle_after_buy == pytest.approx(0.6 * C0 * (1 + DAILY_5PCT), rel=1e-9)

    def test_interest_not_in_trade_profit(self):
        data = _two_fund_universe(80)
        cutoff = data["A"].index[40]
        gate = lambda d, date: date < cutoff      # liquidate at idx 41's open
        cfg = _cfg(cash_rate_annual=0.08, commission=0.01, slippage=0.002,
                   rebalance_days=20, drift_trim_pct=10.0)
        res = rotation.run_rotation(data, _always(), cfg, regime_gate=gate)
        profits = [t["Profit"] for t in res["trade_log"]]
        assert res["trade_pnl_list"] == profits
        assert all(t["ExitReason"] != "End of Backtest" for t in res["trade_log"])
        final = res["portfolio_timeline"].iloc[-1]
        assert final == pytest.approx(C0 + sum(profits) + res["cash_interest_total"],
                                      rel=1e-12)
        assert res["cash_interest_total"] > 0

    def test_scale_invariant(self):
        data = _two_fund_universe()
        a = rotation.run_rotation(data, _always(), _cfg(cash_rate_annual=0.05,
                                                        weighting="fixed_alloc", alloc=0.5))
        b = rotation.run_rotation(data, _always(), _cfg(1_000_000.0, cash_rate_annual=0.05,
                                                        weighting="fixed_alloc", alloc=0.5))
        assert a["pnl_percent"] == pytest.approx(b["pnl_percent"], rel=1e-9)
        assert b["cash_interest_total"] == pytest.approx(a["cash_interest_total"] * 10, rel=1e-9)


# ---------------------------------------------------------------------------
# Sweep instrument
# ---------------------------------------------------------------------------
def _sweep_df(n=60, start="2020-01-01", index=None):
    t = np.arange(n, dtype=float)
    c = 100.0 * np.cumprod(1 + 0.0002 + 0.0001 * np.sin(t))
    return _make_df(c, start=start, index=index)


class TestSweep:
    def test_follows_sweep_returns_when_fully_in_cash(self):
        data = _two_fund_universe()
        data["SWEEP"] = _sweep_df()
        first = data["A"].index[30]
        res = rotation.run_rotation(data, _rank_from(first), _cfg(cash_sweep_symbol="SWEEP"))
        tl = res["portfolio_timeline"].to_numpy()
        s = data["SWEEP"]["Close"].to_numpy()
        for i in range(31):
            assert tl[i] == pytest.approx(C0 * s[i] / s[0], rel=1e-12)
        assert res["cash_yield_mode"] == "sweep"

    def test_sweep_never_traded_ranked_or_on_calendar(self):
        data = _two_fund_universe()
        # The sweep has EXTRA dates before and after the funds.
        data["SWEEP"] = _sweep_df(80, start="2019-12-22")
        seen = []

        def rank(d, date, **kw):
            seen.append(set(d))
            return {"SWEEP": 99.0, "A": 1.0}   # tries to rank the sweep first

        res = rotation.run_rotation(data, rank, _cfg(cash_sweep_symbol="SWEEP"))
        assert all("SWEEP" not in s for s in seen)
        assert {t["Symbol"] for t in res["trade_log"]} == {"A"}
        pd.testing.assert_index_equal(res["portfolio_timeline"].index, data["A"].index)

    def test_missing_bar_earns_zero_then_catches_up(self):
        data = _two_fund_universe()
        sw = _sweep_df()
        full = sw["Close"].to_numpy()
        data["SWEEP"] = sw.drop(sw.index[10])
        first = data["A"].index[30]
        res = rotation.run_rotation(data, _rank_from(first), _cfg(cash_sweep_symbol="SWEEP"))
        tl = res["portfolio_timeline"].to_numpy()
        assert tl[10] == tl[9]                                   # 0 on the gap
        assert tl[11] == pytest.approx(C0 * full[11] / full[0], rel=1e-12)  # caught up

    def test_cash_flow_inside_gap_is_attributed_per_day(self):
        """codex r1: a buy on a gap day must not forfeit the return the cash
        earned on the gap days BEFORE it (nor may a post-flow balance collect
        the whole span return). Sweep bars 29-31 missing, buy fills at idx 31."""
        data = _two_fund_universe()
        sw = _sweep_df()
        s = sw["Close"].to_numpy()
        data["SWEEP"] = sw.drop(sw.index[29:32])
        first = data["A"].index[30]
        # drift_trim_pct=10 -> no later drift adds; the idx-31 buy is the only fill.
        res = rotation.run_rotation(data, _rank_from(first),
                                    _cfg(cash_sweep_symbol="SWEEP", drift_trim_pct=10.0))
        tl = res["portfolio_timeline"].to_numpy()
        (trade,) = res["trade_log"]
        closes = data["A"]["Close"].to_numpy()
        B = tl[28]
        assert B == pytest.approx(C0 * s[28] / s[0], rel=1e-12)
        assert tl[29] == tl[30] == B                       # gap days: 0 on the day
        r31 = tl[31] - trade["Shares"] * closes[31]         # cash left after the buy
        g = (s[32] / s[28]) ** (1 / 4) - 1
        pending = 0.0
        for b in (B, B, r31, r31):
            pending += (b + pending) * g
        cash32 = tl[32] - trade["Shares"] * closes[32]
        assert cash32 == pytest.approx(r31 + pending, rel=1e-12)
        # The pre-buy gap days' return is kept (≈ B * 2 days of sweep return).
        assert pending > 0.9 * B * ((1 + g) ** 2 - 1)

    def test_late_start_earns_zero_before_and_warns_once(self, caplog):
        data = _two_fund_universe()
        idx = data["A"].index[10:]
        data["SWEEP"] = _sweep_df(len(idx), index=idx)
        s = data["SWEEP"]["Close"].to_numpy()
        first = data["A"].index[30]
        with caplog.at_level(logging.WARNING, logger="helpers.rotation"):
            res = rotation.run_rotation(data, _rank_from(first),
                                        _cfg(cash_sweep_symbol="SWEEP"))
        tl = res["portfolio_timeline"].to_numpy()
        assert np.all(tl[:11] == C0)
        assert tl[15] == pytest.approx(C0 * s[5] / s[0], rel=1e-12)
        warns = [r for r in caplog.records if "SWEEP" in r.getMessage() and "starts on" in r.getMessage()]
        assert len(warns) == 1

    def test_sweep_missing_from_data_raises(self):
        with pytest.raises(ValueError, match="not present in data"):
            rotation.run_rotation(_two_fund_universe(), _always(),
                                  _cfg(cash_sweep_symbol="NOPE"))


# ---------------------------------------------------------------------------
# Config handling
# ---------------------------------------------------------------------------
class TestConfig:
    def test_both_set_raises(self):
        data = _two_fund_universe()
        data["SWEEP"] = _sweep_df()
        with pytest.raises(ValueError, match="mutually exclusive"):
            rotation.run_rotation(data, _always(),
                                  _cfg(cash_rate_annual=0.05, cash_sweep_symbol="SWEEP"))

    @pytest.mark.parametrize("bad", ["abc", float("nan"), -1.0, -2.0])
    def test_bad_rate_raises(self, bad):
        with pytest.raises(ValueError):
            rotation.run_rotation(_two_fund_universe(), _always(), _cfg(cash_rate_annual=bad))

    def test_defaults_declared(self):
        from config import CONFIG
        assert rotation._DEFAULT_ROTATION["cash_rate_annual"] == 0.0
        assert rotation._DEFAULT_ROTATION["cash_sweep_symbol"] is None
        assert CONFIG["rotation"]["cash_rate_annual"] == 0.0
        assert CONFIG["rotation"]["cash_sweep_symbol"] is None

    def test_config_entry_point_wiring(self):
        name = "test-idle-cash-cfg-rot"

        @register_rotation(name=name, params={})
        def _r(data, rebalance_date, **kw):
            return {"A": 1.0}

        try:
            data = _two_fund_universe()
            data["SWEEP"] = _sweep_df()
            cfg = _cfg(cash_sweep_symbol="SWEEP", weighting="fixed_alloc", alloc=0.5)
            cfg["rotation"]["rank_strategy"] = name
            res = rotation.run_rotation_from_config(data, cfg)
            assert res["cash_yield_mode"] == "sweep"
            assert res["cash_interest_total"] > 0

            cfg2 = _cfg(cash_rate_annual=0.05, weighting="fixed_alloc", alloc=0.5)
            cfg2["rotation"]["rank_strategy"] = name
            res2 = rotation.run_rotation_from_config(_two_fund_universe(), cfg2)
            assert res2["cash_yield_mode"] == "fixed"
            assert res2["cash_interest_total"] > 0
        finally:
            _registry._REGISTRY.pop(name, None)
