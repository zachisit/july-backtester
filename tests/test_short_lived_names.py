"""
tests/test_short_lived_names.py

#433: short-lived securities (early delistings, late listings) must not be
dropped by ``min_bars_required`` in survivorship-aware universes, and
``pit_warmup_days`` must actually fetch pre-start history without letting any
trade or equity point land before ``start_date``.

main() is driven in-process (tmp cwd, fake fetcher, fake Pool that captures the
init args and tasks); the captured tasks are then run through the real
init_worker/run_single_simulation, so nothing here needs real multiprocessing.
"""
import copy
import os
import sys

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import main as main_mod  # noqa: E402
from config import CONFIG  # noqa: E402

START, END = "2021-01-01", "2021-12-31"


def _frame(first, last):
    idx = pd.bdate_range(first, last, tz="UTC")
    n = len(idx)
    close = pd.Series(range(100, 100 + n), index=idx, dtype=float)
    return pd.DataFrame({"Open": close, "High": close + 1, "Low": close - 1,
                         "Close": close, "Volume": 1_000_000.0}, index=idx)


# Life spans of the fake universe (history exists before START for all).
_LIVES = {
    "LONG": ("2019-01-01", "2021-12-31"),
    "DEAD": ("2020-06-01", "2021-05-14"),   # ~92 bars inside the window
}


class _FakePool:
    captured = {}

    def __init__(self, processes=None, initializer=None, initargs=()):
        _FakePool.captured = {"initargs": initargs, "tasks": None}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def imap(self, fn, tasks):
        _FakePool.captured["tasks"] = list(tasks)
        return iter(())


def _always_long(df, **kw):
    out = df.copy()
    out["Signal"] = 1
    return out


@pytest.fixture
def run_main(monkeypatch, tmp_path):
    """Returns f(portfolios, **cfg) -> (fetch_calls, run_dir)."""
    def _run(portfolios, membership=None, **cfg):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["main.py"])
        calls = []

        def fetcher(symbol, start, end, config):
            calls.append((symbol, start, end))
            first, last = _LIVES[symbol]
            f = _frame(max(first, start), min(last, end)) if max(first, start) <= min(last, end) else None
            return f

        patched = copy.deepcopy(CONFIG)
        patched.update({
            "data_provider": "yahoo", "start_date": START, "end_date": END,
            "comparison_tickers": [], "portfolios": portfolios,
            "min_bars_required": 200, "wfa_split_ratio": None, "wfa_folds": None,
            "data_quality_checks": False, "execution_time": "close",
            "stop_loss_configs": [{"type": "none"}], "pit_warmup_days": 400,
            "include_delisted": False, "save_individual_trades": False,
        })
        patched.update(cfg)
        monkeypatch.setattr(main_mod, "CONFIG", patched)
        import helpers.cli_config as cc
        monkeypatch.setattr(cc, "apply_overrides", lambda c, a: c)
        monkeypatch.setattr(main_mod, "get_data_service", lambda: fetcher)
        monkeypatch.setattr(main_mod, "Pool", _FakePool)
        monkeypatch.setattr(main_mod, "get_active_strategies",
                            lambda: {"AlwaysLong": {"logic": _always_long, "dependencies": [], "params": {}}})
        main_mod.main()
        runs = os.path.join(tmp_path, "output", "runs")
        run_dir = os.path.join(runs, os.listdir(runs)[0])
        return calls, run_dir, patched
    return _run


def _simulate(patched):
    """Run the captured tasks through the real worker code; return result dicts."""
    from unittest.mock import patch

    cap = _FakePool.captured
    old = main_mod.CONFIG
    main_mod.CONFIG = patched
    try:
        # The parent harness replaces main.CONFIG with a separate dictionary.
        # Real spawned workers share config.CONFIG with the engine/helpers;
        # apply the captured runtime values there for this in-process replay.
        with patch.dict("config.CONFIG", patched, clear=True):
            main_mod.init_worker(*cap["initargs"])
            return [main_mod.run_single_simulation(t) for t in cap["tasks"]]
    finally:
        main_mod.CONFIG = old


class TestHelpers:
    def test_warmup_fetch_start_value_and_disable(self):
        assert main_mod._warmup_fetch_start("2021-01-01", {"pit_warmup_days": 31}) == "2020-12-01"
        assert main_mod._warmup_fetch_start("2021-01-01", {"pit_warmup_days": 0}) == "2021-01-01"
        assert main_mod._warmup_fetch_start("2021-01-01", {}) == "2021-01-01"

    def test_trim_to_start_tz_aware_and_naive(self):
        for tz in ("UTC", None):
            idx = pd.bdate_range("2020-12-20", "2021-01-15", tz=tz)
            s = pd.Series(1, index=idx)
            t = main_mod._trim_to_start(s, "2021-01-01")
            assert t.index[0] >= pd.Timestamp("2021-01-01", tz=tz)
            assert main_mod._trim_to_start(t, "2021-01-01") is t

    def test_classify(self):
        idx = pd.bdate_range("2021-03-01", "2021-05-14")
        assert main_mod._classify_short_lived(idx, START, END) == [
            "ended_before_end_date", "started_after_start_date"]
        idx = pd.bdate_range("2021-01-01", "2021-05-14")
        assert main_mod._classify_short_lived(idx, START, END) == ["ended_before_end_date"]
        idx = pd.bdate_range("2021-06-01", "2021-12-31")
        assert main_mod._classify_short_lived(idx, START, END) == ["started_after_start_date"]


class TestShortLivedUniverses:
    def test_plain_list_still_drops_short_symbol(self, run_main):
        _, run_dir, patched = run_main({"P": ["LONG", "DEAD"]})
        assert set(_FakePool.captured["initargs"][3]) == {"LONG"}
        df = pd.read_csv(os.path.join(run_dir, "skipped_symbols.csv"))
        row = df.iloc[0]
        assert (row["symbol"], row["action"], row["reason"]) == ("DEAD", "skipped", "ended_before_end_date")
        assert row["bars"] < 200

    def test_include_delisted_keeps_and_trades_short_symbol(self, run_main):
        _, run_dir, patched = run_main({"P": ["LONG", "DEAD"]}, include_delisted=True,
                                       delisted_symbols_file=None, entry_trigger="level")
        assert set(_FakePool.captured["initargs"][3]) == {"LONG", "DEAD"}
        df = pd.read_csv(os.path.join(run_dir, "skipped_symbols.csv"))
        assert df.iloc[0]["action"] == "kept"
        res = _simulate(patched)[0]
        assert "DEAD" in {t["Symbol"] for t in res["trade_log"]}

    def test_pit_style_schedule_keeps_short_symbol(self, run_main, monkeypatch):
        import helpers.point_in_time as pit
        sched = [("2021-01-01", frozenset({"LONG", "DEAD"}))]
        monkeypatch.setattr(pit, "tickers_union_for_period", lambda *a, **k: ["LONG", "DEAD"])
        monkeypatch.setattr(pit, "build_membership_schedule", lambda *a, **k: sched)
        monkeypatch.setattr(pit, "pit_members_on", lambda s, d: s[0][1])
        import helpers.pit_enforcement as pe
        monkeypatch.setattr(pe, "membership_intervals", lambda v, c: {})
        _, run_dir, _ = run_main({"P": "pit:fake"})
        assert set(_FakePool.captured["initargs"][3]) == {"LONG", "DEAD"}

    def test_skipped_csv_has_both_categories(self, run_main, monkeypatch):
        _LIVES["LATE"] = ("2021-09-01", "2021-12-31")
        try:
            _, run_dir, _ = run_main({"P": ["LONG", "DEAD", "LATE"]})
        finally:
            del _LIVES["LATE"]
        df = pd.read_csv(os.path.join(run_dir, "skipped_symbols.csv")).set_index("symbol")
        assert df.loc["DEAD", "reason"] == "ended_before_end_date"
        assert df.loc["LATE", "reason"] == "started_after_start_date"


class TestWarmup:
    def test_fetch_start_uses_pit_warmup_days(self, run_main):
        calls, _, _ = run_main({"P": ["LONG"]}, pit_warmup_days=100)
        starts = [s for sym, s, e in calls if sym == "LONG"]
        assert starts == ["2020-09-23"]   # 2021-01-01 minus 100 calendar days

    def test_warmup_disabled_fetches_from_start(self, run_main):
        calls, _, _ = run_main({"P": ["LONG"]}, pit_warmup_days=0)
        assert [s for sym, s, e in calls if sym == "LONG"] == [START]

    def test_no_trade_or_equity_point_before_start(self, run_main):
        # AlwaysLong is already held before the window. Level mode isolates the
        # history/execution boundary; edge mode's intentional refusal is below.
        _, _, patched = run_main({"P": ["LONG"]}, pit_warmup_days=100,
                                 entry_trigger="level")
        frame = _FakePool.captured["initargs"][3]["LONG"]
        assert frame.index.min() < pd.Timestamp(START, tz="UTC")   # warm-up WAS fetched
        res = _simulate(patched)[0]
        floor = pd.Timestamp(START)
        first_entry = min(pd.Timestamp(t["EntryDate"]).tz_localize(None) for t in res["trade_log"])
        assert first_entry >= floor
        tl = res["portfolio_timeline"]
        assert len(tl) and pd.Timestamp(tl.index.min()).tz_localize(None) >= floor

    def test_edge_mode_does_not_reenter_a_pre_window_hold(self, run_main):
        _, _, patched = run_main({"P": ["LONG"]}, pit_warmup_days=100,
                                 entry_trigger="edge")
        result = _simulate(patched)[0]
        assert result["status"] == "no_trades"
        assert result["trade_log"] == []
