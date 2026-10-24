"""
Regression tests for issue #430 -- equity shorts reserved no collateral, so a
book could hold unbounded gross short notional (30 shorts at allocation 0.10 =
~300% of equity). ``short_margin_requirement`` now reserves
``notional * requirement`` per open equity short; new entries (long or short)
only see ``cash - reserved_short_collateral``; every cover path releases it.
"""

import pandas as pd
import pytest

import helpers.portfolio_simulations as ps
from helpers.portfolio_simulations import run_portfolio_simulation

N_SYMS = 30
CAP = 100_000.0


def _frame(n=8, close=100.0, high_mult=1.01):
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.DataFrame(
        {"Open": close, "High": close * high_mult, "Low": close * 0.99,
         "Close": close, "Volume": 1_000_000.0, "ATR_14": 1.0},
        index=idx,
    )


def _patch(monkeypatch, req):
    for k, v in {
        "execution_time": "close", "slippage_pct": 0.0, "commission_per_share": 0.0,
        "exclude_open_positions": False, "position_sizing_method": "fixed",
        "entry_priority": "alphabetical", "volume_impact_coeff": 0.0,
        "max_pct_adv": 0.0, "max_portfolio_heat": 100.0, "htb_rate_annual": 0.0,
        "short_margin_requirement": req,
    }.items():
        monkeypatch.setitem(ps.CONFIG, k, v)


def _run(sig_by_sym, monkeypatch, req, alloc=0.10, frames=None, stop=None):
    _patch(monkeypatch, req)
    frames = frames or {s: _frame() for s in sig_by_sym}
    signals = {}
    for s, m in sig_by_sym.items():
        sig = pd.Series(0, index=frames[s].index)
        for i, v in m.items():
            sig.iloc[i] = v
        signals[s] = sig
    return run_portfolio_simulation(
        portfolio_data=frames, signals=signals, initial_capital=CAP,
        allocation_pct=alloc, spy_df=None, vix_df=None, tnx_df=None,
        stop_config=stop or {"type": "none"},
    )


def _names():
    return [f"S{i:02d}" for i in range(N_SYMS)]


def _shorts(res):
    return [t for t in res["trade_log"] if str(t["Trade"]).startswith("Short")]


class TestShortCollateralCap:
    def test_legacy_requirement_zero_reproduces_unbounded_book(self, monkeypatch):
        res = _run({s: {1: -2} for s in _names()}, monkeypatch, req=0.0)
        shorts = _shorts(res)
        assert len(shorts) == N_SYMS
        assert sum(t["Shares"] * t["EntryPrice"] for t in shorts) == pytest.approx(3 * CAP, rel=1e-6)

    def test_default_requirement_caps_gross_near_two_x(self, monkeypatch):
        res = _run({s: {1: -2} for s in _names()}, monkeypatch, req=0.5)
        shorts = _shorts(res)
        assert 19 <= len(shorts) <= 21
        gross = sum(t["Shares"] * t["EntryPrice"] for t in shorts)
        assert gross <= 2.0 * CAP * (1 + 1e-9)
        assert gross >= 1.8 * CAP

    def test_shipped_default_is_half(self):
        from config import CONFIG
        assert CONFIG["short_margin_requirement"] == 0.5

    @pytest.mark.parametrize("method,expected", [("fixed_contracts", 5.), ("risk_parity", 200.)])
    def test_collateral_keeps_configured_method_and_size_multiplier(
            self, monkeypatch, method, expected):
        _patch(monkeypatch, .5)
        for key, value in {"position_sizing_method": method,
                           "fixed_contracts_per_trade": 10,
                           "target_risk_per_trade": .02}.items():
            monkeypatch.setitem(ps.CONFIG, key, value)
        df = _frame()
        sig = pd.Series(0, index=df.index)
        sig.iloc[1], sig.iloc[3] = -2, -1
        result = run_portfolio_simulation(
            {"A": df}, {"A": sig}, CAP, .1, None, None, None,
            {"type": "percentage", "value": .05},
            size_mults={"A": pd.Series(.5, index=df.index)})
        trade, = result["trade_log"]
        assert trade["Shares"] == pytest.approx(expected)
        assert trade["PosSizeMult"] == .5

    def test_non_fixed_size_is_limited_by_collateral_plus_commission(self, monkeypatch):
        _patch(monkeypatch, .5)
        monkeypatch.setitem(ps.CONFIG, "position_sizing_method", "risk_parity")
        monkeypatch.setitem(ps.CONFIG, "target_risk_per_trade", .5)
        monkeypatch.setitem(ps.CONFIG, "commission_per_share", 1.)
        df = _frame()
        sig = pd.Series(0, index=df.index)
        sig.iloc[1], sig.iloc[3] = -2, -1
        result = run_portfolio_simulation(
            {"A": df}, {"A": sig}, CAP, .1, None, None, None,
            {"type": "percentage", "value": .05})
        trade, = result["trade_log"]
        assert trade["Shares"] == pytest.approx(CAP / (100. * .5 + 1.))
        assert trade["Shares"] * 100. * .5 + trade["Shares"] <= CAP


class TestCollateralRelease:
    def _frames(self):
        return {s: _frame() for s in _names()}

    def test_strategy_cover_releases_collateral(self, monkeypatch):
        # All 30 try to short on bar 1; the first 20 fill. Those 20 cover on
        # bar 3; the remaining 10 re-signal on bar 4 and must now be admitted.
        sigs = {}
        for i, s in enumerate(_names()):
            sigs[s] = {1: -2, 3: -1} if i < 20 else {4: -2}
        res = _run(sigs, monkeypatch, req=0.5)
        late = [t for t in _shorts(res) if t["EntryDate"].startswith("2024-01-08")]
        assert len(late) >= 10   # entered after the covers freed collateral

    def test_no_release_means_blocked(self, monkeypatch):
        # Control: same late entries while the first 20 are still open -> blocked.
        sigs = {}
        for i, s in enumerate(_names()):
            sigs[s] = {1: -2} if i < 20 else {4: -2}
        res = _run(sigs, monkeypatch, req=0.5)
        late = [t for t in _shorts(res) if t["EntryDate"].startswith("2024-01-08")]
        assert late == []

    def test_stop_cover_releases_collateral(self, monkeypatch):
        # First 20 shorts are stopped out on bar 3 (High spikes); late entries admitted.
        frames = {}
        for i, s in enumerate(_names()):
            f = _frame()
            if i < 20:
                f.iloc[3, f.columns.get_loc("High")] = 110.0
            frames[s] = f
        sigs = {s: ({1: -2} if i < 20 else {4: -2}) for i, s in enumerate(_names())}
        res = _run(sigs, monkeypatch, req=0.5, frames=frames,
                   stop={"type": "percentage", "value": 0.05})
        assert any(t["ExitReason"].startswith("Stop Loss") for t in _shorts(res))
        late = [t for t in _shorts(res) if t["EntryDate"].startswith("2024-01-08")]
        assert len(late) >= 10

    def test_fill_bar_stop_cover_releases_collateral(self, monkeypatch):
        # execution_time=open: shorts fill at the next open and are stopped on the
        # SAME bar (#426 _close_short_now path). Collateral must not leak, so all
        # later entries are still admitted afterwards.
        _patch(monkeypatch, 0.5)
        monkeypatch.setitem(ps.CONFIG, "execution_time", "open")
        monkeypatch.setitem(ps.CONFIG, "entry_bar_stop_check", True)
        frames = {}
        for i, s in enumerate(_names()):
            f = _frame()
            if i < 20:
                f.iloc[2, f.columns.get_loc("High")] = 110.0   # fill bar spikes through stop
            frames[s] = f
        sigs = {}
        for i, s in enumerate(_names()):
            sigs[s] = {1: -2} if i < 20 else {4: -2}
        signals = {s: pd.Series([sigs[s].get(j, 0) for j in range(8)], index=frames[s].index)
                   for s in sigs}
        res = run_portfolio_simulation(
            portfolio_data=frames, signals=signals, initial_capital=CAP,
            allocation_pct=0.10, spy_df=None, vix_df=None, tnx_df=None,
            stop_config={"type": "percentage", "value": 0.05})
        stopped = [t for t in _shorts(res) if t["ExitReason"].startswith("Stop Loss")]
        assert len(stopped) == 20
        late = [t for t in _shorts(res) if t["EntryDate"].startswith("2024-01-09")]
        assert len(late) >= 10


class TestLongsRespectCollateral:
    def test_shorts_block_long_entry(self, monkeypatch):
        # 20 shorts consume all buying power; a long on bar 3 is blocked at 0.5
        # but admitted in legacy mode (cash is untouched by shorts).
        sigs = {s: {1: -2} for s in _names()[:20]}
        sigs["LONG"] = {3: 1}
        frames = {s: _frame() for s in sigs}
        res_new = _run(sigs, monkeypatch, req=0.5, frames=frames)
        res_old = _run(sigs, monkeypatch, req=0.0, frames=frames)
        longs = lambda r: [t for t in r["trade_log"] if str(t["Trade"]).startswith("Long")]
        assert longs(res_new) == []
        assert len(longs(res_old)) == 1

    def test_fully_invested_long_book_cannot_add_short(self, monkeypatch):
        # One long at 100% allocation exhausts cash; the later short finds no buying power.
        sigs = {"AAA": {1: 1}, "ZZZ": {3: -2}}
        res = _run(sigs, monkeypatch, req=0.5, alloc=1.0)
        assert _shorts(res) == []

    def test_equity_unchanged_by_reservation(self, monkeypatch):
        # Collateral is a constraint, not a debit: one short that fits under either
        # setting yields an identical equity curve.
        sigs = {"AAA": {1: -2, 4: -1}}
        a = _run(sigs, monkeypatch, req=0.5)
        b = _run(sigs, monkeypatch, req=0.0)
        pd.testing.assert_series_equal(a["portfolio_timeline"], b["portfolio_timeline"])
