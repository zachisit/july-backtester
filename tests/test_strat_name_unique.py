"""Unique strategy names across stop configs (#434).

``_build_strat_name`` used to suffix only ``percentage`` / ``atr`` stops, so
``none`` / ``points`` / ``signal_bar`` / ``trailing_atr`` configs collided on
the bare name and their trade CSVs / correlation columns merged or overwrote
each other. Now every non-``none`` type has a distinct suffix and the parent
guarantees ``(portfolio, name)`` uniqueness with `` #2`` / `` #3`` suffixes.
"""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from config import CONFIG
from helpers.summary import generate_per_portfolio_summary
from main import _assign_unique_names, _build_strat_name, _stop_label

ALL_STOPS = [
    {"type": "none"},
    {"type": "percentage", "value": 0.05},
    {"type": "atr", "multiplier": 2.0},
    {"type": "points", "value": 10},
    {"type": "signal_bar", "bars_back": 1, "buffer": 0.5},
    {"type": "trailing_atr", "stop_mult": 1.5, "t1_mult": 2.0, "trail_mult": 1.0},
]


class TestSuffixes:
    def test_every_stop_type_gets_a_distinct_name(self):
        names = [_build_strat_name("S", sc) for sc in ALL_STOPS]
        assert len(set(names)) == len(ALL_STOPS)

    def test_none_keeps_bare_name(self):
        assert _build_strat_name("S", {"type": "none"}) == "S"
        assert _build_strat_name("S", {}) == "S"

    def test_exact_suffixes(self):
        assert _build_strat_name("S", {"type": "points", "value": 10}) == "S w/ 10pt SL"
        assert _build_strat_name("S", {"type": "signal_bar", "bars_back": 1, "buffer": 0.5}) \
            == "S w/ SigBar(b1,buf0.5) SL"
        assert _build_strat_name(
            "S", {"type": "trailing_atr", "stop_mult": 1.5, "t1_mult": 2.0, "trail_mult": 1.0}
        ) == "S w/ TrailATR(1.5x,T2.0,tr1.0) SL"

    def test_engine_defaults_for_missing_keys(self):
        assert _build_strat_name("S", {"type": "points"}) == "S w/ 0.0pt SL"
        assert _build_strat_name("S", {"type": "signal_bar"}) == "S w/ SigBar(b0,buf0.0) SL"
        assert _build_strat_name("S", {"type": "trailing_atr"}) == "S w/ TrailATR(1.0x,T0.0,tr1.0) SL"

    def test_same_type_different_values_differ(self):
        assert _build_strat_name("S", {"type": "points", "value": 5}) != \
            _build_strat_name("S", {"type": "points", "value": 10})

    @pytest.mark.parametrize("cfg", [
        {"type": "points", "value": None},
        {"type": "percentage", "value": None},
        {"type": "percentage", "value": "x"},
        {"type": "signal_bar", "bars_back": None, "buffer": None},
        {"type": "trailing_atr", "stop_mult": None},
        {"type": "mystery"},
    ])
    def test_never_raises(self, cfg):
        assert isinstance(_build_strat_name("S", cfg), str)

    def test_stop_label_empty_for_none(self):
        assert _stop_label({"type": "none"}) == ""


class TestAssignUniqueNames:
    def test_identical_configs_get_numbered(self):
        out = _assign_unique_names([("P", "S"), ("P", "S"), ("P", "S")])
        assert out == ["S", "S #2", "S #3"]

    def test_unique_names_untouched(self):
        assert _assign_unique_names([("P", "A"), ("P", "B")]) == ["A", "B"]

    def test_uniqueness_is_per_portfolio(self):
        assert _assign_unique_names([("P1", "S"), ("P2", "S")]) == ["S", "S"]

    def test_literal_hash_name_does_not_collide(self):
        out = _assign_unique_names([("P", "S"), ("P", "S #2"), ("P", "S")])
        assert len(set(out)) == 3


def _log():
    return [{"EntryDate": "2024-01-02", "ExitDate": "2024-01-05", "EntryPrice": 100.0,
             "ExitPrice": 105.0, "Profit": 50.0, "ProfitPct": 0.05, "is_win": True,
             "HoldDuration": 3, "Shares": 10, "MAE_pct": 0.01, "MFE_pct": 0.06,
             "Symbol": "AAPL", "ExitReason": "Signal"}]


def _result(name):
    return {"Strategy": name, "Trades": 1, "pnl_percent": 0.2, "max_drawdown": 0.1,
            "mc_score": 50.0, "mc_verdict": "Robust", "calmar_ratio": 1.0,
            "sharpe_ratio": 1.0, "win_rate": 0.6, "profit_factor": 1.5,
            "vs_spy_benchmark": 0.05, "vs_qqq_benchmark": 0.03,
            "avg_trade_duration": 3.0, "oos_pnl_pct": 0.02, "wfa_verdict": "Pass",
            "expectancy": 0.5, "sqn": 1.2, "Portfolio": "Test Portfolio",
            "Asset": "MULTI", "trade_log": _log()}


def test_colliding_configs_save_two_distinct_trade_csvs(tmp_path, monkeypatch):
    """Two identical stop configs -> parent-assigned unique names -> two CSVs."""
    monkeypatch.chdir(tmp_path)
    names = _assign_unique_names(
        [("Test Portfolio", _build_strat_name("S", {"type": "points", "value": 10}))] * 2)
    assert len(set(names)) == 2
    saved = {"save_individual_trades": True, "save_only_filtered_trades": False}
    orig = {k: CONFIG.get(k) for k in saved}
    CONFIG.update(saved)
    try:
        generate_per_portfolio_summary(
            [_result(n) for n in names], "Test Portfolio",
            {"SPY": 0.10, "QQQ": 0.12}, "run-434")
    finally:
        for k, v in orig.items():
            CONFIG.pop(k, None) if v is None else CONFIG.__setitem__(k, v)
    raw = list((tmp_path / "output" / "runs" / "run-434" / "raw_trades").rglob("*_trade_log.csv"))
    assert len(raw) == 2, [p.name for p in raw]


class TestTaskNamingMetadata:
    @staticmethod
    def _setup(monkeypatch, rps):
        idx = pd.bdate_range("2023-01-02", periods=6)
        df = pd.DataFrame({"Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.0,
                           "Volume": 1e6}, index=idx)
        for k, v in (("comparison_dfs_global", {}), ("benchmark_returns_global", {}),
                     ("dependency_map_global", {}), ("portfolio_data_global", {"AAA": df}),
                     ("delisting_dates_global", {}), ("pit_member_masks_global", None),
                     ("intrabar_data_global", None)):
            monkeypatch.setattr(main, k, v, raising=False)
        monkeypatch.setattr(main, "run_portfolio_simulation", rps)

    @staticmethod
    def _logic(d, **kw):
        d = d.copy(); d["Signal"] = 0; return d

    NAMING = {"strat_name": "Base [fast=16] w/ 10pt SL #2", "base_strategy": "Base",
              "param_label": "fast=16", "stop_label": "w/ 10pt SL"}

    def _task(self, naming=True):
        t = ("P", "Base [fast=16]", self._logic, [], {"type": "points", "value": 10},
             {}, None, None, None)
        return t + (dict(self.NAMING),) if naming else t

    def _check(self, r):
        assert r["Strategy"] == "Base [fast=16] w/ 10pt SL #2"
        assert (r["base_strategy"], r["param_label"], r["stop_label"]) == \
            ("Base", "fast=16", "w/ 10pt SL")

    def test_stub_no_trades_uses_parent_name_and_metadata(self, monkeypatch):
        self._setup(monkeypatch, lambda *a, **k: None)
        r = main.run_single_simulation(self._task())
        assert r["status"] == "no_trades"
        self._check(r)

    def test_real_result_carries_metadata(self, monkeypatch):
        self._setup(monkeypatch, lambda *a, **k: {
            "trade_pnl_list": [0.0], "Trades": 0, "initial_capital": 1e5,
            "portfolio_timeline": None, "trade_log": [], "pnl_percent": 0.0})
        self._check(main.run_single_simulation(self._task()))

    def test_error_stub_carries_metadata(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("x")
        self._setup(monkeypatch, boom)
        r = main.run_single_simulation(self._task())
        assert r["status"] == "error"
        self._check(r)

    def test_legacy_nine_element_tuple_derives_metadata(self, monkeypatch):
        self._setup(monkeypatch, lambda *a, **k: None)
        r = main.run_single_simulation(self._task(naming=False))
        assert r["Strategy"] == "Base [fast=16] w/ 10pt SL"
        assert (r["base_strategy"], r["param_label"], r["stop_label"]) == \
            ("Base [fast=16]", "(base)", "w/ 10pt SL")
