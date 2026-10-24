"""
tests/test_random_seed.py

Issue #439: CONFIG["random_seed"] makes the three random sources reproducible:
(a) Monte Carlo resampling, (b) the analyze_mc_results_v2 bootstrap p-value,
(c) inject_price_noise. random_seed=None keeps the legacy unseeded behaviour.

Data is a fixed-seed synthetic random walk; no network.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import main
from config import CONFIG
from helpers.noise import inject_price_noise
from helpers.rng import derive_seed


def _ohlcv(n=600):
    g = np.random.default_rng(123)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    price = 100 * np.exp(np.cumsum(g.normal(0, 0.01, n)))
    return pd.DataFrame({"Open": price, "High": price * 1.01, "Low": price * 0.99,
                         "Close": price, "Volume": [1_000_000] * n}, index=idx)


def _toggle(df, **kw):
    sig = pd.Series(0, index=df.index)
    sig.iloc[1::10] = 1
    sig.iloc[6::10] = -1
    return df.assign(Signal=sig)


@pytest.fixture
def cfg():
    saved = dict(CONFIG)
    CONFIG["min_trades_for_mc"] = 5
    CONFIG["num_mc_simulations"] = 200
    CONFIG["mc_sampling"] = "iid"
    yield CONFIG
    CONFIG.clear()
    CONFIG.update(saved)


def _run(name="Probe", portfolio="Port A"):
    main.init_worker(
        comparison_dfs_dict={}, benchmark_returns_dict={}, dependency_map_dict={},
        portfolio_data_for_worker={"AAA": _ohlcv()}, delisting_dates_for_worker=None,
        pit_member_masks_dict=None, intrabar_data_for_worker=None,
    )
    return main.run_single_simulation(
        (portfolio, name, _toggle, [], {"type": "none"}, {}, None, None, None))


def _capture_mc(monkeypatch):
    captured = {}
    real = main.run_monte_carlo_simulation

    def spy(*a, **k):
        out = real(*a, **k)
        captured["fe"] = out["final_equities"].copy()
        return out
    monkeypatch.setattr(main, "run_monte_carlo_simulation", spy)
    return captured


class TestSeededSimulation:
    def test_same_seed_identical(self, cfg, monkeypatch):
        cfg["random_seed"] = 42
        cap = _capture_mc(monkeypatch)
        r1 = _run(); fe1 = cap["fe"]
        r2 = _run(); fe2 = cap["fe"]
        assert r1["Trades"] >= 5
        assert np.array_equal(fe1, fe2)
        assert r1["mc_score"] == r2["mc_score"]
        assert r1["mc_edge_pvalue"] == r2["mc_edge_pvalue"]

    def test_different_strategy_names_differ(self, cfg, monkeypatch):
        cfg["random_seed"] = 42
        cap = _capture_mc(monkeypatch)
        _run("Alpha"); fe_a = cap["fe"]
        _run("Beta"); fe_b = cap["fe"]
        assert not np.array_equal(fe_a, fe_b)

    def test_separator_in_labels_does_not_share_a_task_rng(self, cfg, monkeypatch):
        cfg["random_seed"] = 42
        cap = _capture_mc(monkeypatch)
        _run(name="C", portfolio="A|B"); first = cap["fe"]
        _run(name="B|C", portfolio="A"); second = cap["fe"]
        assert not np.array_equal(first, second)

    def test_different_seed_differs(self, cfg, monkeypatch):
        cap = _capture_mc(monkeypatch)
        cfg["random_seed"] = 1
        _run(); fe1 = cap["fe"]
        cfg["random_seed"] = 2
        _run(); fe2 = cap["fe"]
        assert not np.array_equal(fe1, fe2)

    def test_global_rng_state_restored(self, cfg):
        cfg["random_seed"] = 42
        np.random.seed(999)
        expected = np.random.get_state()[1].copy()
        _run()
        assert np.array_equal(np.random.get_state()[1], expected)

    def test_unseeded_keeps_legacy_behaviour(self, cfg, monkeypatch):
        cfg["random_seed"] = None
        cap = _capture_mc(monkeypatch)
        _run(); fe1 = cap["fe"]
        _run(); fe2 = cap["fe"]
        assert not np.array_equal(fe1, fe2)
        # Global RNG still drives it: reseeding globally reproduces it.
        np.random.seed(7); _run(); a = cap["fe"]
        np.random.seed(7); _run(); b = cap["fe"]
        assert np.array_equal(a, b)


class TestSeededNoise:
    def test_seeded_noise_identical(self):
        df = _ohlcv(50)
        a = inject_price_noise(df, 0.01, rng=np.random.default_rng(derive_seed(42, "noise", "AAA")))
        b = inject_price_noise(df, 0.01, rng=np.random.default_rng(derive_seed(42, "noise", "AAA")))
        pd.testing.assert_frame_equal(a, b)

    def test_different_symbols_differ(self):
        df = _ohlcv(50)
        a = inject_price_noise(df, 0.01, rng=np.random.default_rng(derive_seed(42, "noise", "AAA")))
        b = inject_price_noise(df, 0.01, rng=np.random.default_rng(derive_seed(42, "noise", "BBB")))
        assert not a["Close"].equals(b["Close"])

    def test_no_rng_uses_global(self):
        df = _ohlcv(50)
        np.random.seed(5); a = inject_price_noise(df, 0.01)
        np.random.seed(5); b = inject_price_noise(df, 0.01)
        pd.testing.assert_frame_equal(a, b)


def test_derive_seed_stable_and_label_sensitive():
    assert derive_seed(42, "P", "S") == derive_seed(42, "P", "S")
    assert derive_seed(42, "P", "S") != derive_seed(42, "P", "T")
    assert derive_seed(42, "P", "S") != derive_seed(43, "P", "S")


def test_seed_label_components_are_unambiguous():
    assert derive_seed(42, "A|B", "C", "mc") != derive_seed(42, "A", "B|C", "mc")
    assert derive_seed(42, "P", "S", "mc") != derive_seed(42, "P", "S|mc")


def test_random_seed_is_known_config_key_and_default_none():
    from helpers.config_validator import KNOWN_KEYS
    assert "random_seed" in KNOWN_KEYS
    assert CONFIG.get("random_seed") is None
