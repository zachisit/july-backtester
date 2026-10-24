"""Tests for helpers/mc_scoring.py (issue #429)."""
import numpy as np

from helpers.mc_scoring import (
    analyze_mc_results_v2, bootstrap_mean_pvalue, closed_trade_drawdown,
)
from helpers.monte_carlo import analyze_mc_results


def _mc(pnl, initial=100_000.0, sims=500, seed=0):
    rng = np.random.default_rng(seed)
    arr = np.asarray(pnl, float)
    from helpers.monte_carlo import _equity_and_drawdown
    fe, dd = zip(*[_equity_and_drawdown(rng.choice(arr, len(arr)), initial) for _ in range(sims)])
    return {"final_equities": np.array(fe), "max_drawdowns": np.array(dd)}


class TestEdgeTest:
    def test_zero_edge_fails_at_least_90pct(self):
        fails = 0
        for seed in range(100):
            rng = np.random.default_rng(seed)
            pnl = rng.normal(0, 1000, 100)
            res = analyze_mc_results_v2(
                {"initial_capital": 100_000.0}, _mc(pnl, seed=seed), list(pnl),
                rng=np.random.default_rng(seed + 1000),
            )
            fails += "No Significant Edge" in res["mc_verdict"]
        assert fails >= 90

    def test_legacy_passes_zero_edge_by_construction(self):
        passes = 0
        for seed in range(50):
            pnl = np.random.default_rng(seed).normal(0, 1000, 100)
            r = {"initial_capital": 100_000.0, "pnl_percent": pnl.sum() / 100_000.0,
                 "max_drawdown": 0.0}
            passes += "Perf. Outlier" not in analyze_mc_results(r, _mc(pnl, seed=seed))["mc_verdict"]
        assert passes >= 40  # documents the bug v2 fixes

    def test_strong_edge_passes(self):
        pnl = np.random.default_rng(1).normal(800, 1000, 100)
        res = analyze_mc_results_v2({"initial_capital": 100_000.0}, _mc(pnl), list(pnl),
                                    rng=np.random.default_rng(2))
        assert "No Significant Edge" not in res["mc_verdict"]
        assert res["mc_edge_pvalue"] < 0.05

    def test_pvalue_deterministic_with_seeded_rng(self):
        pnl = list(np.random.default_rng(3).normal(100, 1000, 60))
        a = bootstrap_mean_pvalue(pnl, rng=np.random.default_rng(7))
        b = bootstrap_mean_pvalue(pnl, rng=np.random.default_rng(7))
        assert a == b

    def test_default_rng_none_works(self):
        assert 0 < bootstrap_mean_pvalue([1.0, -2.0, 3.0, 0.5, -1.0]) <= 1


class TestDrawdownRealism:
    def test_closed_trade_dd_is_chronological(self):
        # +10k,-20k,+5k : peak 110k -> trough 90k = 18.18%
        assert abs(closed_trade_drawdown([10_000, -20_000, 5_000], 100_000) - 20_000 / 110_000) < 1e-9
        # Different order, different drawdown
        assert closed_trade_drawdown([-20_000, 10_000, 5_000], 100_000) == 0.2

    def test_mtm_drawdown_in_result_is_ignored(self):
        pnl = [1000, -500, 800, -300, 600, -200]
        mc = _mc(pnl)
        base = analyze_mc_results_v2({"initial_capital": 100_000.0, "max_drawdown": 0.99},
                                     mc, pnl, rng=np.random.default_rng(0))
        other = analyze_mc_results_v2({"initial_capital": 100_000.0, "max_drawdown": 0.0},
                                      mc, pnl, rng=np.random.default_rng(0))
        assert base == other

    def test_dd_understated_flag_uses_closed_trade_dd(self):
        # Monotonic wins: historical closed DD = 0 < MC median (shuffles of
        # identical-sign... use mixed pnl in lucky order: losses last-to-first)
        pnl = [500] * 20 + [-400] * 5 + [500] * 20  # lucky ordering
        mc = {"final_equities": np.full(10, 1.0), "max_drawdowns": np.full(10, 0.05)}
        res = analyze_mc_results_v2({"initial_capital": 100_000.0}, mc, pnl)
        hist = closed_trade_drawdown(pnl, 100_000.0)
        assert ("DD Understated" in res["mc_verdict"]) == (hist < 0.05)


class TestCompat:
    def test_none_mc_returns_na(self):
        assert analyze_mc_results_v2({"initial_capital": 1.0}, None, [])["mc_score"] == 0

    def test_score_range(self):
        for seed in range(20):
            pnl = np.random.default_rng(seed).normal(0, 1000, 50)
            s = analyze_mc_results_v2({"initial_capital": 100_000.0}, _mc(pnl), list(pnl))["mc_score"]
            assert -4 <= s <= 5
