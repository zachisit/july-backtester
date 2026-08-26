"""tests/test_rotation.py

Tests for the cross-sectional rotation mechanism (issue #294) and the QA
findings F1-F7 raised on PR #296.

Covers:
- registry: kind="rotation" registration + register_rotation sugar + backward
  compatibility of the classic signal path;
- portfolio construction (top-N selection, equal weighting);
- rebalance / rank-drop / regime mechanics;
- F1 no same-bar look-ahead (decide on signal bar, fill at next bar's Open);
- F2 no zero-duration same-bar buy+sell round trips;
- F4 coherent weighting over exactly-held names;
- F5 drift add/top-up of under-weight holdings;
- F6 a real (non-tautological) sell-buffer churn assertion;
- F7 config-driven entry point honoring rotation.enabled / rank_strategy;
- config-key validation;
- CRITICAL: scale-invariance regression — 100k vs 1M produce identical %
  returns and proportional share counts (the #293 lesson).

Pure, deterministic, no network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from helpers import rotation
from helpers.registry import (
    register_strategy,
    register_rotation,
    REGISTRY,
    SIGNAL,
    ROTATION,
)


# ---------------------------------------------------------------------------
# Deterministic synthetic universe
# ---------------------------------------------------------------------------
def _make_df(prices, start="2020-01-01", opens=None):
    idx = pd.date_range(start, periods=len(prices), freq="D")
    p = np.asarray(prices, dtype=float)
    o = np.asarray(opens, dtype=float) if opens is not None else p
    return pd.DataFrame(
        {"Open": o, "High": np.maximum(o, p) * 1.01, "Low": np.minimum(o, p) * 0.99,
         "Close": p, "Volume": 1e6},
        index=idx,
    )


def _linear_universe(n_days=120):
    """Four symbols with strictly ordered, monotonic uptrends so the momentum
    ranking is deterministic: STRONG > MID > WEAK > FLAT every day."""
    base = np.arange(n_days, dtype=float)
    return {
        "STRONG": _make_df(100 + base * 2.0),
        "MID": _make_df(100 + base * 1.0),
        "WEAK": _make_df(100 + base * 0.3),
        "FLAT": _make_df(100 + base * 0.0 + 100.0),  # constant 200
    }


def _momentum_rank(lookback=20):
    def rank(data, rebalance_date, **kwargs):
        scores = {}
        for sym, df in data.items():
            w = df.loc[:rebalance_date]
            if len(w) <= lookback:
                continue
            past = w["Close"].iloc[-lookback - 1]
            now = w["Close"].iloc[-1]
            if past > 0:
                scores[sym] = float(now / past - 1.0)
        return scores
    return rank


def _base_config(initial_capital=100_000.0, **rotation_overrides):
    rot = {
        "enabled": True,
        "top_n": 2,
        "rebalance_days": 21,
        "weighting": "equal",
        "sell_buffer_rank": 0,
        "drift_trim_pct": 0.0,
    }
    rot.update(rotation_overrides)
    return {
        "initial_capital": initial_capital,
        "allocation_per_trade": 0.10,
        "max_position_pct": 1.0,
        "commission_per_share": 0.0,
        "slippage_pct": 0.0,
        "rotation": rot,
        "instruments": {"default_asset_class": "equity"},
    }


# ---------------------------------------------------------------------------
# Registry: kind + backward compat
# ---------------------------------------------------------------------------
class TestRegistryKind:
    def test_register_rotation_sets_kind(self):
        name = "test-rot-plugin-xyz"

        @register_rotation(name=name, params={"lookback": 10})
        def _r(data, rebalance_date, **kwargs):
            return list(data.keys())

        entry = REGISTRY[name]
        assert entry["kind"] == ROTATION
        assert entry["logic"] is _r
        assert entry["params"] == {"lookback": 10}
        assert entry["regime_gate"] is None

    def test_register_strategy_defaults_to_signal_kind(self):
        name = "test-sig-plugin-xyz"

        @register_strategy(name=name)
        def _s(df, **kwargs):
            return df

        entry = REGISTRY[name]
        assert entry["kind"] == SIGNAL
        assert set(["logic", "dependencies", "params"]).issubset(entry.keys())

    def test_get_active_strategies_excludes_rotation(self, monkeypatch):
        from helpers import registry

        name_rot = "test-active-rot"
        name_sig = "test-active-sig"

        @register_rotation(name=name_rot)
        def _r(data, rebalance_date, **kwargs):
            return []

        @register_strategy(name=name_sig)
        def _s(df, **kwargs):
            return df

        import config as _cfg
        monkeypatch.setitem(_cfg.CONFIG, "strategies", "all")

        active = registry.get_active_strategies(directory="does_not_exist_dir")
        assert name_sig in active
        assert name_rot not in active

    def test_get_rotation_strategies_returns_only_rotation(self):
        from helpers import registry

        name_rot = "test-getrot-rot"

        @register_rotation(name=name_rot)
        def _r(data, rebalance_date, **kwargs):
            return []

        rots = registry.get_rotation_strategies(directory="does_not_exist_dir")
        assert name_rot in rots
        assert all(e["kind"] == ROTATION for e in rots.values())


# ---------------------------------------------------------------------------
# Rebalance calendar + ranking normalisation
# ---------------------------------------------------------------------------
class TestHelpers:
    def test_build_rebalance_dates_stride_and_last(self):
        data = _linear_universe(n_days=100)
        dates = rotation.build_rebalance_dates(data, rebalance_days=21)
        all_dates = sorted(set(data["STRONG"].index))
        assert dates[0] == all_dates[0]
        assert dates[-1] == all_dates[-1]
        assert dates[1] == all_dates[21]

    def test_normalise_ranking_dict_sorts_desc(self):
        out = rotation._normalise_ranking({"A": 0.1, "B": 0.9, "C": 0.5})
        assert out == ["B", "C", "A"]

    def test_normalise_ranking_list_passthrough(self):
        assert rotation._normalise_ranking(["X", "Y"]) == ["X", "Y"]

    def test_normalise_ranking_none_empty(self):
        assert rotation._normalise_ranking(None) == []

    def test_carry_forward_close_fills_gap(self):
        df = _make_df([10, 11, 12], start="2020-01-01")
        # A date between bars carries the last known close forward.
        gap = pd.Timestamp("2020-01-02T12:00:00")
        assert rotation._carry_forward_close(df, gap) == 11.0
        # A date before the first bar -> NaN.
        assert np.isnan(rotation._carry_forward_close(df, pd.Timestamp("2019-12-01")))


# ---------------------------------------------------------------------------
# Portfolio construction
# ---------------------------------------------------------------------------
class TestConstruction:
    def test_top_n_selection_holds_strongest(self):
        data = _linear_universe()
        cfg = _base_config(top_n=2)
        res = rotation.run_rotation(data, _momentum_rank(), cfg)
        assert res is not None
        held = {t["Symbol"] for t in res["trade_log"]}
        assert held == {"STRONG", "MID"}

    def test_equal_weight_two_positions_half_each(self):
        # Suppress drift churn (drift_trim_pct high) so each symbol has exactly one
        # closing trade whose entry notional is the original equal-weight sizing.
        data = _linear_universe()
        cfg = _base_config(top_n=2, rebalance_days=21, drift_trim_pct=99.0)
        res = rotation.run_rotation(data, _momentum_rank(), cfg)
        assert res is not None
        entries = {t["Symbol"]: t["EntryPrice"] * t["Shares"] for t in res["trade_log"]}
        assert set(entries) == {"STRONG", "MID"}
        # Equity is 100% cash at the first buy -> 50% each, exact with fractional
        # shares and zero commission/slippage.
        for notional in entries.values():
            assert notional == pytest.approx(50_000.0, rel=1e-9)

    def test_result_shape_matches_pipeline(self):
        data = _linear_universe()
        res = rotation.run_rotation(data, _momentum_rank(), _base_config())
        for key in ("trade_log", "portfolio_timeline", "trade_pnl_list",
                    "initial_capital", "pnl_percent", "Trades",
                    "max_drawdown", "sharpe_ratio", "win_rate"):
            assert key in res
        assert isinstance(res["portfolio_timeline"], pd.Series)
        t0 = res["trade_log"][0]
        for key in ("Symbol", "EntryDate", "ExitDate", "EntryPrice", "ExitPrice",
                    "Shares", "Profit", "ProfitPct", "HoldDuration", "ExitReason",
                    "InitialRisk", "RMultiple", "is_win"):
            assert key in t0

    def test_empty_data_returns_none(self):
        assert rotation.run_rotation({}, _momentum_rank(), _base_config()) is None


# ---------------------------------------------------------------------------
# F1: no same-bar look-ahead — decide on signal bar, fill at NEXT bar Open
# ---------------------------------------------------------------------------
class TestNoLookAhead:
    def _spike_universe(self):
        # A rises steadily; C is worthless until a one-bar spike on d3.
        # Open == Close for a clean fill-price assertion.
        A = _make_df([10, 11, 12, 13, 14, 15, 16, 17])
        B = _make_df([9, 9, 9, 9, 9, 9, 9, 9])
        C = _make_df([1, 1, 1, 100, 1, 1, 1, 1])
        return {"A": A, "B": B, "C": C}

    def _close_ranker(self):
        # Ranks purely by the Close ON the rebalance date (no history needed).
        def rank(data, rebalance_date, **kwargs):
            return {s: rotation._price(df, rebalance_date, "Close")
                    for s, df in data.items()
                    if rebalance_date in df.index}
        return rank

    def test_execution_bar_not_visible_to_ranking(self):
        data = self._spike_universe()
        cfg = _base_config(top_n=1, rebalance_days=1, drift_trim_pct=99.0)
        res = rotation.run_rotation(data, self._close_ranker(), cfg)
        assert res is not None
        d3 = pd.Timestamp("2020-01-04").isoformat()  # the spike bar
        # If the ranking could see the execution bar (d3), the d2->d3 rebalance
        # would rank C highest and buy it. With correct next-bar execution the
        # decision uses d2 (C worthless) so C is NEVER entered on the spike bar.
        c_entries_on_spike = [t for t in res["trade_log"]
                              if t["Symbol"] == "C" and t["EntryDate"] == d3]
        assert c_entries_on_spike == []

    def test_fill_is_next_bar_open_not_signal_bar(self):
        # Distinct Open != Close so we can tell which bar the fill used.
        opens = [10, 20, 30, 40, 50, 60]
        closes = [11, 21, 31, 41, 51, 61]
        data = {"ONLY": _make_df(closes, opens=opens),
                "CASH": _make_df([5, 5, 5, 5, 5, 5], opens=[5, 5, 5, 5, 5, 5])}

        def rank(data_, rebalance_date, **kwargs):
            # ONLY always wins; decision is made on the signal bar.
            return {"ONLY": 1.0, "CASH": 0.0} if rebalance_date in data_["ONLY"].index else {}

        cfg = _base_config(top_n=1, rebalance_days=1, drift_trim_pct=99.0)
        res = rotation.run_rotation(data, rank, cfg)
        assert res is not None
        first = min(res["trade_log"], key=lambda t: t["EntryDate"])
        # First rebalance signals on d0 and MUST fill at d1's Open (20), never d0's.
        assert first["Symbol"] == "ONLY"
        assert first["EntryPrice"] == pytest.approx(20.0)
        assert first["EntryDate"] == pd.Timestamp("2020-01-02").isoformat()


# ---------------------------------------------------------------------------
# F2: no zero-duration same-bar buy+sell round trips
# ---------------------------------------------------------------------------
class TestNoZeroDurationRoundTrip:
    def test_no_trade_has_same_entry_and_exit_date(self):
        data = _linear_universe()
        res = rotation.run_rotation(data, _momentum_rank(), _base_config(top_n=2))
        assert res is not None
        for t in res["trade_log"]:
            assert t["EntryDate"] != t["ExitDate"], (
                f"same-bar round trip: {t}")
            assert t["HoldDuration"] >= 1

    def test_terminal_close_is_end_of_backtest_mtm(self):
        data = _linear_universe()
        res = rotation.run_rotation(data, _momentum_rank(), _base_config(top_n=2))
        # Open positions are closed via an EoB mark, not a buy+sell friction trade.
        assert any(t["ExitReason"] == "End of Backtest" for t in res["trade_log"])


# ---------------------------------------------------------------------------
# F4 / F5 / mechanics: rank-drop, regime, drift add & trim, buffer
# ---------------------------------------------------------------------------
class TestMechanics:
    def test_rank_drop_triggers_sell(self):
        n = 80
        base = np.arange(n, dtype=float)
        up_then_flat = np.concatenate([100 + base[:40] * 3.0, np.full(40, 100 + 39 * 3.0)])
        flat_then_up = np.concatenate([np.full(40, 100.0), 100 + base[:40] * 5.0])
        data = {
            "EARLY": _make_df(up_then_flat),
            "LATE": _make_df(flat_then_up),
            "NOISE": _make_df(100 + base * 0.1),
        }
        cfg = _base_config(top_n=1, rebalance_days=10, sell_buffer_rank=0)
        res = rotation.run_rotation(data, _momentum_rank(lookback=10), cfg)
        assert res is not None
        reasons = {t["ExitReason"] for t in res["trade_log"]}
        assert "Rank Drop" in reasons
        symbols = {t["Symbol"] for t in res["trade_log"]}
        assert "EARLY" in symbols and "LATE" in symbols

    def test_regime_gate_off_liquidates(self):
        data = _linear_universe()

        def gate(_data, date):
            return pd.Timestamp(date) < pd.Timestamp("2020-02-10")

        cfg = _base_config(top_n=2, rebalance_days=10)
        res = rotation.run_rotation(data, _momentum_rank(), cfg, regime_gate=gate)
        assert res is not None
        reasons = [t["ExitReason"] for t in res["trade_log"]]
        assert "Regime Off" in reasons
        tl = res["portfolio_timeline"]
        # After liquidation the book is pure cash -> the tail is flat.
        assert tl.iloc[-1] == pytest.approx(tl.iloc[-5], rel=1e-9)

    def test_drift_add_tops_up_underweight_holding(self):
        # A declines after entry so its value drifts BELOW target; with drift
        # rebalancing on it must be topped up (more shares accumulated) vs a run
        # where rebalancing is suppressed. B is flat to provide the second slot.
        decline = np.concatenate([np.linspace(100, 100, 10),
                                   np.linspace(100, 40, 70)])
        flat = np.full(80, 100.0)
        data = {"A": _make_df(decline), "B": _make_df(flat)}

        def rank(data_, rebalance_date, **kwargs):
            # Fixed ranking: A then B, both always eligible after some history.
            out = {}
            for s in ("A", "B"):
                if rebalance_date in data_[s].index:
                    out[s] = 2.0 if s == "A" else 1.0
            return out

        cfg_add = _base_config(top_n=2, rebalance_days=10, drift_trim_pct=0.0)
        cfg_none = _base_config(top_n=2, rebalance_days=10, drift_trim_pct=99.0)
        res_add = rotation.run_rotation(data, rank, cfg_add)
        res_none = rotation.run_rotation(data, rank, cfg_none)
        assert res_add is not None and res_none is not None

        def a_shares(res):
            a_trades = [t for t in res["trade_log"] if t["Symbol"] == "A"]
            # total shares that eventually exited A (trims + final close)
            return sum(t["Shares"] for t in a_trades)

        # With top-ups the accumulated A share count strictly exceeds the
        # no-rebalance baseline (which only ever holds the initial buy).
        assert a_shares(res_add) > a_shares(res_none)

    def test_sell_buffer_reduces_churn(self):
        # Two anti-phase oscillators: without a buffer the top_n=1 leader flips
        # every phase and churns; a buffer keeps the incumbent while it stays
        # within the band, strictly cutting the trade count.
        n = 120
        t = np.arange(n, dtype=float)
        wave = np.sin(2 * np.pi * t / 40.0)
        A = _make_df(100 + 8 * wave)
        B = _make_df(100 - 8 * wave)
        data = {"A": A, "B": B}
        cfg_nb = _base_config(top_n=1, rebalance_days=5, sell_buffer_rank=0,
                              drift_trim_pct=99.0)
        cfg_b = _base_config(top_n=1, rebalance_days=5, sell_buffer_rank=1,
                             drift_trim_pct=99.0)
        res_nb = rotation.run_rotation(data, _momentum_rank(lookback=10), cfg_nb)
        res_b = rotation.run_rotation(data, _momentum_rank(lookback=10), cfg_b)
        assert res_nb is not None and res_b is not None
        # Real assertion (F6): the buffer STRICTLY reduces the number of trades.
        assert res_b["Trades"] < res_nb["Trades"]

    def test_weights_never_exceed_one_with_fixed_alloc(self):
        # fixed_alloc with alloc 0.5 on top_n=3 would sum to 1.5 pre-normalisation;
        # the framework must normalise so the book never over-commits (F4).
        data = _linear_universe()
        # drift_trim_pct pinned high so no later drift-add/trim can fold
        # into a name's position before the backtest ends — the trade_log
        # row for each name then reflects *only* the very first buy, with
        # nothing else blended into its EntryPrice/Shares.
        cfg = _base_config(top_n=3, rebalance_days=21, weighting="fixed_alloc",
                            drift_trim_pct=99.0)
        cfg["allocation_per_trade"] = 0.5
        res = rotation.run_rotation(data, _momentum_rank(), cfg)
        assert res is not None

        # Equity curve must never require negative cash.
        tl = res["portfolio_timeline"]
        assert (tl > 0).all()

        # Real check on the normalisation itself, not a positivity proxy: at
        # the very first rebalance (no existing positions, so every fill is a
        # fresh buy against known starting equity), each name's entry notional
        # must reflect the normalised (not raw) weight — 0.5 / 1.5 = 1/3 each,
        # not 0.5 each — and the three together must not exceed capital. A
        # disabled `total_w > 1.0` normalisation still passes the positivity
        # check above (buys are clamped by `_over_budget`, not rejected) but
        # produces unequal, order-dependent notionals here: the first name(s)
        # processed get their full raw (uncapped) weight, and whichever name
        # is processed last is starved of whatever cash remains.
        first_date = min(t["EntryDate"] for t in res["trade_log"])
        first_trades = [t for t in res["trade_log"] if t["EntryDate"] == first_date]
        symbols_entered = {t["Symbol"] for t in first_trades}
        assert symbols_entered == {"STRONG", "MID", "WEAK"}

        notional_by_symbol = {}
        for t in first_trades:
            notional_by_symbol[t["Symbol"]] = (
                notional_by_symbol.get(t["Symbol"], 0.0) + t["Shares"] * t["EntryPrice"]
            )

        assert sum(notional_by_symbol.values()) <= cfg["initial_capital"] * (1 + 1e-6)

        expected_each = cfg["initial_capital"] * (0.5 / 1.5)
        for notional in notional_by_symbol.values():
            assert notional == pytest.approx(expected_each, rel=0.05)


# ---------------------------------------------------------------------------
# F7: config-driven entry point honoring rotation.enabled / rank_strategy
# ---------------------------------------------------------------------------
class TestConfigDriven:
    def test_disabled_returns_none(self):
        data = _linear_universe()
        cfg = _base_config()
        cfg["rotation"]["enabled"] = False
        assert rotation.run_rotation_from_config(data, cfg) is None

    def test_missing_rank_strategy_returns_none(self):
        data = _linear_universe()
        cfg = _base_config()
        cfg["rotation"]["rank_strategy"] = None
        assert rotation.run_rotation_from_config(data, cfg) is None

    def test_runs_named_registered_plugin(self):
        name = "test-cfg-driven-rot"

        @register_rotation(name=name, params={})
        def _r(data, rebalance_date, **kwargs):
            # rank by close level on the rebalance date
            return {s: rotation._price(df, rebalance_date, "Close")
                    for s, df in data.items() if rebalance_date in df.index}

        data = _linear_universe()
        cfg = _base_config(top_n=2)
        cfg["rotation"]["rank_strategy"] = name
        res = rotation.run_rotation_from_config(data, cfg)
        assert res is not None
        assert res["Trades"] > 0


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------
class TestConfigValidation:
    def test_rotation_keys_recognised(self):
        from helpers.config_validator import validate_config, KNOWN_KEYS
        assert "rotation" in KNOWN_KEYS
        assert "max_position_pct" in KNOWN_KEYS
        cfg = {"rotation": {"enabled": True}, "max_position_pct": 0.25}
        warnings = validate_config(cfg)
        assert not any("rotation" in w or "max_position_pct" in w for w in warnings)

    def test_config_py_has_rotation_disabled_by_default(self):
        from config import CONFIG
        assert CONFIG["rotation"]["enabled"] is False
        assert CONFIG["max_position_pct"] == 1.0


# ---------------------------------------------------------------------------
# CRITICAL: scale invariance (issue #293)
# ---------------------------------------------------------------------------
class TestScaleInvariance:
    def test_returns_identical_across_capital_scales(self):
        data = _linear_universe()
        rank = _momentum_rank()

        res_100k = rotation.run_rotation(data, rank, _base_config(100_000.0, top_n=2))
        res_1m = rotation.run_rotation(data, rank, _base_config(1_000_000.0, top_n=2))

        assert res_100k["pnl_percent"] == pytest.approx(res_1m["pnl_percent"], rel=1e-9)
        assert res_100k["max_drawdown"] == pytest.approx(res_1m["max_drawdown"], rel=1e-9)
        assert res_100k["Trades"] == res_1m["Trades"]

        # Same deterministic order in both runs -> pair by index; shares & profit
        # scale by exactly 10x.
        for a, b in zip(res_100k["trade_log"], res_1m["trade_log"]):
            assert a["Symbol"] == b["Symbol"]
            assert a["EntryDate"] == b["EntryDate"]
            assert b["Shares"] == pytest.approx(a["Shares"] * 10.0, rel=1e-9)
            assert b["Profit"] == pytest.approx(a["Profit"] * 10.0, rel=1e-9)

    def test_equity_curve_scales_proportionally(self):
        data = _linear_universe()
        rank = _momentum_rank()
        res_100k = rotation.run_rotation(data, rank, _base_config(100_000.0, top_n=2))
        res_1m = rotation.run_rotation(data, rank, _base_config(1_000_000.0, top_n=2))
        a = res_100k["portfolio_timeline"]
        b = res_1m["portfolio_timeline"]
        assert list(a.index) == list(b.index)
        ratio = (b / a).dropna()
        assert np.allclose(ratio.values, 10.0, rtol=1e-9)


# ---------------------------------------------------------------------------
# Regression: drift-loop trims must run before adds, so an add's fill cannot
# depend on the arbitrary order rank_fn returns names in (the single-pass ->
# two-pass restructuring of the drift-control loop, MED-1 in the second
# adversarial review).
# ---------------------------------------------------------------------------
class TestDriftLoopOrderIndependence:
    @staticmethod
    def _crash_rally_universe(n_days=80):
        # A crashes 50%, B rallies 2x, over the same middle stretch. With
        # top_n=2 BOTH names are held in BOTH runs below — only the order
        # rank_fn returns them in differs. B's trim (over-weight, since it
        # rallied) frees cash that A's add (under-weight, since it crashed)
        # needs in the same cycle.
        a = np.concatenate([np.full(20, 100.0), np.linspace(100, 50, 40), np.full(20, 50.0)])
        b = np.concatenate([np.full(20, 100.0), np.linspace(100, 200, 40), np.full(20, 200.0)])
        return {"A": _make_df(a), "B": _make_df(b)}

    def test_final_equity_independent_of_rank_return_order(self):
        data = self._crash_rally_universe()

        def rank_a_first(data_, rebalance_date, **kwargs):
            return {"A": 2.0, "B": 1.0}

        def rank_b_first(data_, rebalance_date, **kwargs):
            return {"B": 2.0, "A": 1.0}

        cfg = _base_config(top_n=2, rebalance_days=5, sell_buffer_rank=0,
                            drift_trim_pct=0.0, weighting="equal")

        res_a_first = rotation.run_rotation(data, rank_a_first, cfg)
        res_b_first = rotation.run_rotation(data, rank_b_first, cfg)
        assert res_a_first is not None and res_b_first is not None

        assert res_a_first["portfolio_timeline"].iloc[-1] == pytest.approx(
            res_b_first["portfolio_timeline"].iloc[-1], abs=1e-6
        )
        assert res_a_first["Trades"] == res_b_first["Trades"]


# ---------------------------------------------------------------------------
# Regression: zombie position when a symbol's data ends mid-backtest (the
# `_do_sell` carry-forward fallback added on top of the F1/F2 patch)
# ---------------------------------------------------------------------------
class TestDelistedSymbolLiquidation:
    def test_delisted_symbol_liquidates_not_zombies(self):
        # ENDS's data stops well before the backtest's terminal date; STAY
        # spans the full window and only outranks ENDS once ENDS's history is
        # exhausted. Regression for `_do_sell`'s carry-forward fallback: the
        # unpatched code silently no-op'd (`return`) when `exec_date` had no
        # bar for the symbol being sold (e.g. a delisting/provider dropout),
        # which left the position in `positions` forever. With top_n=1 that
        # permanently occupies the only slot, so the newly top-ranked name
        # (STAY) could never actually be bought.
        ends = _make_df(100 + np.arange(40, dtype=float))
        stay = _make_df(100 + np.arange(120, dtype=float) * 0.1)
        data = {"ENDS": ends, "STAY": stay}
        ends_last = ends.index[-1]

        def rank(data_, rebalance_date, **kwargs):
            if rebalance_date <= ends_last:
                return {"ENDS": 2.0}
            return {"STAY": 2.0}

        cfg = _base_config(top_n=1, rebalance_days=10, sell_buffer_rank=0,
                            drift_trim_pct=99.0)
        res = rotation.run_rotation(data, rank, cfg)
        assert res is not None

        ends_exits = [t for t in res["trade_log"] if t["Symbol"] == "ENDS"]
        assert len(ends_exits) == 1
        # Actively rank-dropped (via the carry-forward fallback), not left
        # open until a forced End of Backtest close.
        assert ends_exits[0]["ExitReason"] == "Rank Drop"

        # The freed top_n=1 slot must actually go to STAY once ENDS is
        # dropped -- the sharp regression check. Pre-fix, ENDS never leaves
        # `positions`, so `slots` stays 0 forever and this trade never exists.
        stay_entries = [t for t in res["trade_log"] if t["Symbol"] == "STAY"]
        assert len(stay_entries) >= 1


# ---------------------------------------------------------------------------
# Regression: drift-add must not fire on the terminal bar (the `allow_new`
# gate added to the drift-control loop's add branch on top of F2)
# ---------------------------------------------------------------------------
class TestTerminalBarAddIsBlocked:
    """An under-weight holding must not receive a drift ADD on the terminal
    rebalance -- that capital would be committed on the very last bar and
    immediately unwound by the End of Backtest close, hiding a same-day
    buy+sell inside what looks like a longer-duration trade."""

    @staticmethod
    def _decline_universe(n_days=41):
        # Single-symbol universe on fixed_alloc weighting (50% of equity) so
        # the other 50% sits idle as cash from the very first buy -- the
        # drift-add is never cash-starved, isolating `allow_new` as the only
        # thing that can block it.
        decline = np.linspace(100.0, 50.0, n_days)
        return {"A": _make_df(decline)}

    @staticmethod
    def _fixed_rank(data_, rebalance_date, **kwargs):
        return {"A": 1.0}

    def _config(self, rebalance_days):
        # allocation_per_trade is a top-level config key (fixed_alloc weighting
        # reads it from there), not a rotation sub-key -- set it after
        # construction, same pattern as test_weights_never_exceed_one_with_fixed_alloc.
        cfg = _base_config(top_n=1, rebalance_days=rebalance_days,
                            weighting="fixed_alloc", drift_trim_pct=0.0)
        cfg["allocation_per_trade"] = 0.5
        return cfg

    def test_add_blocked_when_exec_date_is_terminal(self):
        data = self._decline_universe()
        # rebalance_days=39 -> rebalance dates land on [day0, day39, day40]
        # (41-day universe, terminal = day40). day39's exec_date is day40,
        # the terminal bar itself, so its drift-add on A (declining,
        # underweight by then) must be skipped.
        res_terminal = rotation.run_rotation(data, self._fixed_rank, self._config(39))
        assert res_terminal is not None

        # rebalance_days=38 -> rebalance dates land on [day0, day38, day40].
        # day38's exec_date is day39, NOT terminal, so the identical drift
        # condition (A is underweight by day38 too) is allowed to add.
        res_control = rotation.run_rotation(data, self._fixed_rank, self._config(38))
        assert res_control is not None

        def a_shares(res):
            a_trades = [t for t in res["trade_log"] if t["Symbol"] == "A"]
            return sum(t["Shares"] for t in a_trades)

        # The control run's add actually fires (more capital committed to A
        # one day before the terminal bar); the terminal run's identical
        # drift signal must be blocked by `allow_new`, so it ends up having
        # closed out strictly fewer A shares in total.
        assert a_shares(res_terminal) < a_shares(res_control)

        # And directly confirm no zero-duration same-day round trip was
        # created on the terminal bar itself: no trade both entered and
        # exited on the terminal date.
        terminal_date = max(d for df in data.values() for d in df.index)
        for t in res_terminal["trade_log"]:
            assert not (pd.Timestamp(t["EntryDate"]) == terminal_date
                        and pd.Timestamp(t["ExitDate"]) == terminal_date)
