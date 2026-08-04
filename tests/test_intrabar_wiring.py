# tests/test_intrabar_wiring.py
"""
Tests for the main.py wiring of sub-bar (intraday) resolution — making the
`intrabar_resolution` flag actually functional instead of an inert no-op.

  TestBuildIntrabarData  — per-symbol intraday fetch, skips symbols without data
  TestWorkerGlobals      — init_worker propagates the intrabar_data global
  TestCallSite           — run_single_simulation passes intrabar_data (and
                           delisting_dates) to run_portfolio_simulation by keyword
"""

import os
import sys

import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import main


def _min_df():
    idx = pd.to_datetime(["2023-01-03 09:30", "2023-01-03 09:31"])
    return pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0}, index=idx)


class TestBuildIntrabarData:
    def test_uses_intrabar_timeframe_and_skips_missing(self, monkeypatch):
        seen_tf = {}

        def fake_fetcher(symbol, start, end, cfg):
            seen_tf["tf"] = cfg["timeframe"]
            seen_tf["mult"] = cfg["timeframe_multiplier"]
            return _min_df() if symbol == "AAA" else None

        monkeypatch.setattr(main, "get_data_service", lambda: fake_fetcher)
        out = main._build_intrabar_data(
            {"AAA": None, "BBB": None},
            {"start_date": "2023-01-01", "end_date": "2023-12-31",
             "intrabar_timeframe": "MIN", "intrabar_multiplier": 1},
        )
        assert set(out) == {"AAA"}          # BBB had no data -> omitted
        assert seen_tf["tf"] == "MIN" and seen_tf["mult"] == 1

    def test_empty_when_no_symbol_has_data(self, monkeypatch):
        monkeypatch.setattr(main, "get_data_service", lambda: (lambda *a, **k: None))
        out = main._build_intrabar_data({"AAA": None}, {"start_date": "a", "end_date": "b"})
        assert out == {}

    def test_fetch_error_is_swallowed(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("provider down")
        monkeypatch.setattr(main, "get_data_service", lambda: boom)
        out = main._build_intrabar_data({"AAA": None}, {"start_date": "a", "end_date": "b"})
        assert out == {}

    def test_parquet_source_bad_columns_warns_and_returns_empty(self, tmp_path):
        # Wrongly-cased columns ("Open" instead of "open") must not crash with an
        # unhandled KeyError -- the column access now sits inside the same
        # try/except as the read call, so a schema mismatch is treated like any
        # other load failure: warn and return {} (#238 review item #4).
        p = tmp_path / "bad_intrabar.parquet"
        idx = pd.to_datetime(["2023-01-03 09:30", "2023-01-03 09:31"])
        pd.DataFrame({"Open": [1.0, 1.0], "High": [1.0, 1.0], "Low": [1.0, 1.0],
                      "Close": [1.0, 1.0]}, index=idx).to_parquet(p)
        out = main._build_intrabar_data(
            {"AAA": None},
            {"start_date": "a", "end_date": "b", "intrabar_parquet_source": str(p)},
        )
        assert out == {}

    def test_parquet_source_applies_same_file_to_every_symbol(self, tmp_path):
        # intrabar_parquet_source is documented as single-symbol research only;
        # confirm the (correct-schema) happy path still applies the one parquet
        # file to every symbol in a multi-symbol portfolio.
        p = tmp_path / "good_intrabar.parquet"
        idx = pd.to_datetime(["2023-01-03 09:30", "2023-01-03 09:31"])
        pd.DataFrame({"open": [1.0, 1.0], "high": [1.0, 1.0], "low": [1.0, 1.0],
                      "close": [1.0, 1.0]}, index=idx).to_parquet(p)
        out = main._build_intrabar_data(
            {"AAA": None, "BBB": None},
            {"start_date": "a", "end_date": "b", "intrabar_parquet_source": str(p)},
        )
        assert set(out) == {"AAA", "BBB"}
        assert out["AAA"] is out["BBB"]  # same single-symbol DataFrame object reused


class TestWorkerGlobals:
    def test_init_worker_sets_intrabar_global(self):
        sentinel = {"AAA": "idf"}
        main.init_worker({}, {}, {}, {"AAA": None}, None, None, sentinel)
        assert main.intrabar_data_global == sentinel

    def test_intrabar_global_defaults_none(self):
        # Module-level default must exist so workers don't NameError pre-init.
        assert hasattr(main, "intrabar_data_global")


class TestCallSite:
    def test_run_single_simulation_passes_keywords(self, monkeypatch):
        idx = pd.bdate_range("2023-01-02", periods=6)
        df = pd.DataFrame(
            {"Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.0, "Volume": 1e6}, index=idx)

        monkeypatch.setattr(main, "comparison_dfs_global", {}, raising=False)
        monkeypatch.setattr(main, "benchmark_returns_global", {}, raising=False)
        monkeypatch.setattr(main, "dependency_map_global", {}, raising=False)
        monkeypatch.setattr(main, "portfolio_data_global", {"AAA": df}, raising=False)
        monkeypatch.setattr(main, "delisting_dates_global", {"AAA": "2023-01-05"}, raising=False)
        monkeypatch.setattr(main, "pit_member_masks_global", None, raising=False)
        monkeypatch.setattr(main, "intrabar_data_global", {"AAA": df}, raising=False)

        def logic(d, **kwargs):
            d = d.copy(); d["Signal"] = 0; return d

        captured = {}

        def fake_rps(*args, **kwargs):
            captured["args"] = args; captured["kwargs"] = kwargs; return None

        monkeypatch.setattr(main, "run_portfolio_simulation", fake_rps)

        task = ("P", "S", logic, [], {"type": "none"}, {}, None, None, None)
        main.run_single_simulation(task)

        assert captured["kwargs"].get("delisting_dates") == {"AAA": "2023-01-05"}
        assert captured["kwargs"].get("intrabar_data") is not None
        assert len(captured["args"]) == 8          # nothing spills into size_mults
        assert captured["kwargs"].get("size_mults") is None
