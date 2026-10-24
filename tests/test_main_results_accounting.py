"""
tests/test_main_results_accounting.py

Issue #432: zero-trade and crashed strategies used to vanish from the results
(``run_single_simulation`` returned ``None``). They now return stub results
(``status`` = "no_trades" / "error") that every consumer tolerates, that are
never shown as ranked strategies, and that count against sensitivity
robustness.

Deterministic: no network, no randomness.
"""
import io
import os
import sys
from contextlib import redirect_stdout

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import main
from config import CONFIG
from helpers import summary
from helpers.result_status import is_stub, split_results, format_not_shown
from helpers.correlation import run_correlation_analysis
from helpers.ml_export import export_trade_features
from helpers.verdict_format import format_strategy_verdicts_block, print_strategy_verdicts
from helpers.llm_verdict import generate_llm_verdict

BENCH = {"SPY": 0.10}


def _ohlcv(n=60):
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    price = np.linspace(100.0, 110.0, n)
    return pd.DataFrame({"Open": price, "High": price + 1, "Low": price - 1,
                         "Close": price, "Volume": [1_000_000] * n}, index=idx)


def _run(logic_func, benchmarks=None):
    main.init_worker(
        comparison_dfs_dict={}, benchmark_returns_dict=benchmarks or {},
        dependency_map_dict={}, portfolio_data_for_worker={"AAA": _ohlcv()},
        delisting_dates_for_worker=None, pit_member_masks_dict=None,
        intrabar_data_for_worker=None,
    )
    args = ("Port A", "Probe", logic_func, [], {"type": "none"}, {}, None, None, None)
    return main.run_single_simulation(args)


def _real(name="Real", pnl=0.2, portfolio="Port A"):
    log = [{"Symbol": "AAA", "EntryDate": "2020-01-02", "ExitDate": "2020-01-10",
            "Profit": 100.0, "ProfitPct": 0.01, "is_win": 1, "Trade": 1}]
    return {"Strategy": name, "Portfolio": portfolio, "Trades": 20, "pnl_percent": pnl,
            "max_drawdown": 0.1, "calmar_ratio": 1.5, "sharpe_ratio": 1.0,
            "profit_factor": 1.5, "win_rate": 0.5, "avg_trade_duration": 5,
            "mc_verdict": "Robust", "mc_score": 80, "oos_pnl_pct": 0.05,
            "wfa_verdict": "Pass", "wfa_rolling_verdict": "N/A", "initial_capital": 100000.0,
            "vs_spy_benchmark": pnl - 0.10, "trade_log": log, "trade_pnl_list": [100.0],
            "portfolio_timeline": None}


def _stubs():
    from helpers.result_status import make_stub_result
    return [
        make_stub_result("NoTrade", "Port A", "no_trades", benchmark_returns=BENCH),
        make_stub_result("Boom", "Port A", "error", benchmark_returns=BENCH,
                         error="ValueError: bad param"),
    ]


class TestWorkerStubs:
    def test_zero_signal_strategy_returns_no_trades_stub(self):
        r = _run(lambda df, **kw: df.assign(Signal=0), benchmarks=BENCH)
        assert r is not None
        assert r["status"] == "no_trades"
        assert r["Trades"] == 0 and r["pnl_percent"] == 0.0
        assert r["trade_log"] == [] and r["trade_pnl_list"] == []
        assert r["Strategy"] and r["Portfolio"] == "Port A"
        assert r["mc_verdict"] == "N/A (no trades)" and r["mc_score"] == -999
        assert r["wfa_verdict"] == "N/A" and r["wfa_rolling_verdict"] == "N/A"
        assert r["vs_spy_benchmark"] == pytest.approx(-0.10)
        assert is_stub(r)

    def test_raising_strategy_returns_error_stub(self):
        def boom(df, **kw):
            raise ValueError("typo'd param")
        r = _run(boom)
        assert r["status"] == "error"
        assert r["error"] == "ValueError: typo'd param"
        assert r["Trades"] == 0 and r["Strategy"] and r["Portfolio"] == "Port A"
        assert r["trade_log"] == []

    def test_real_result_has_no_stub_status(self):
        def always_long(df, **kw):
            sig = pd.Series(0, index=df.index)
            sig.iloc[1] = 1
            sig.iloc[-2] = -1
            return df.assign(Signal=sig)
        r = _run(always_long)
        assert r is not None and not is_stub(r) and r["Trades"] > 0


class TestHelpers:
    def test_split_results_drops_none_and_separates(self):
        real, stubs = split_results([_real(), None, *_stubs()])
        assert len(real) == 1 and len(stubs) == 2

    def test_format_not_shown(self):
        lines = format_not_shown(_stubs())
        assert lines[0] == "Not shown: 1 with 0 trades, 1 errored"
        assert any("NoTrade" in l for l in lines)
        assert any("Boom" in l and "ValueError: bad param" in l for l in lines)
        assert format_not_shown([]) == []


class TestConsumersTolerateStubs:
    @pytest.fixture(autouse=True)
    def _cfg(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setitem(CONFIG, "save_individual_trades", True)
        monkeypatch.setitem(CONFIG, "sensitivity_sweep_enabled", True)
        monkeypatch.setitem(CONFIG, "min_trades_for_mc", 1)

    def _mixed(self):
        return [_real("Real A"), _real("Real B", pnl=-0.1), *_stubs()]

    def test_per_portfolio_summary_hides_stubs_and_lists_them(self, tmp_path):
        buf = io.StringIO()
        with redirect_stdout(buf):
            summary.generate_per_portfolio_summary(self._mixed(), "Port A", BENCH, "run1")
        out = buf.getvalue()
        assert "Real A" in out
        assert "Not shown: 1 with 0 trades, 1 errored" in out
        assert "ERROR: Boom: ValueError: bad param" in out
        # No empty trade CSVs for stubs
        csvs = [f for _, _, fs in os.walk(tmp_path) for f in fs if f.endswith(".csv")]
        assert not any("NoTrade" in f or "Boom" in f for f in csvs)

    def test_per_portfolio_all_stubs(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            summary.generate_per_portfolio_summary(_stubs(), "Port A", BENCH, "run1")
        assert "Not shown: 1 with 0 trades, 1 errored" in buf.getvalue()

    def test_overall_summary_and_csv_exclude_stubs(self, tmp_path):
        buf = io.StringIO()
        with redirect_stdout(buf):
            summary.generate_portfolio_summary_report(self._mixed(), BENCH, 1.0, "run1")
        csv = (tmp_path / "output" / "runs" / "run1" / "overall_portfolio_summary.csv").read_text()
        assert "Real A" in csv and "NoTrade" not in csv and "Boom" not in csv

    def test_overall_summary_all_stubs(self):
        with redirect_stdout(io.StringIO()):
            summary.generate_portfolio_summary_report(_stubs(), BENCH, 1.0, "run1")

    def test_final_and_single_asset_summaries(self, tmp_path):
        with redirect_stdout(io.StringIO()):
            summary.generate_final_summary(self._mixed(), BENCH)
            summary.generate_single_asset_summary_report(
                self._mixed(), BENCH, "AAA", str(tmp_path), "run1")

    def test_save_trades_to_csv_skips_stub(self, tmp_path):
        summary.save_trades_to_csv(_stubs()[0], str(tmp_path), "run1")
        assert list(tmp_path.iterdir()) == []

    def test_correlation_ml_verdicts_llm(self, tmp_path):
        results = self._mixed()
        run_correlation_analysis(results, str(tmp_path / "corr.csv"))
        assert export_trade_features(results, tmp_path / "ml.parquet") == 2  # two real trades; stubs add none
        block = format_strategy_verdicts_block(results, BENCH)
        assert "NoTrade" not in block and "Boom" not in block
        with redirect_stdout(io.StringIO()):
            print_strategy_verdicts(_stubs(), BENCH)
        generate_llm_verdict(results, BENCH, output_dir=str(tmp_path))
        import json
        txt = (tmp_path / "llm_verdict.json").read_text()
        assert "Real A" in txt and "Boom" not in txt and "NoTrade" not in txt
        json.loads(txt)


class TestSensitivityCountsStubs:
    def test_zero_trade_variants_count_against_robustness(self, monkeypatch):
        monkeypatch.setitem(CONFIG, "sensitivity_sweep_enabled", True)
        from helpers.result_status import make_stub_result
        results = [
            _real("S [(base)]", pnl=0.3),
            make_stub_result("S [fast=8]", "Port A", "no_trades"),
            make_stub_result("S [fast=9]", "Port A", "error", error="X: y"),
            make_stub_result("S [fast=10]", "Port A", "no_trades"),
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            summary.generate_sensitivity_report(results, "run1")
        out = buf.getvalue()
        assert "FRAGILE" in out and "25%" in out  # 1 of 4, not 1 of 1
        assert "[0 trades]" in out and "[ERROR]" in out
