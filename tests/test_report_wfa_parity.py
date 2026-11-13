"""Regression tests for issue #477: report.py WFA must match main.py's.

For the same run, ``main.py`` evaluates WFA on SPY's actual data window with the
mark-to-market ``portfolio_timeline``; the PDF analyzer used to re-derive the
split from the trade span and use closed-trade profits only, so the two could
disagree (different OOS P&L, flipped verdict).

The synthetic run here has a long-held trade that straddles the split date,
which is exactly the case where the two measures diverge.  No network.
"""

import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from helpers import wfa  # noqa: E402

INITIAL_CAPITAL = 100_000.0
SPY_START = "2015-01-02"
SPY_END = "2024-12-31"
RATIO = 0.80


# ---------------------------------------------------------------------------
# Synthetic run
# ---------------------------------------------------------------------------

def _synthetic_run():
    """Return ``(trade_log, portfolio_timeline)`` shaped like main.py's result.

    * 10 short IS trades (2016-2021) each +1,000.
    * 6 short OOS trades (2023-2024) each -1,000.
    * one long trade held 2019-01-02 -> 2024-06-03: marked down to -40,000 by
      the split, then recovering to close +5,000 in the OOS window.

    Mark-to-market (main.py) the OOS window gains ~+56% and passes; on closed
    trades alone (the legacy tearsheet) OOS is a net loss and the verdict flips
    to "Likely Overfitted" -- the shape of the disagreement in #477.

    The timeline steps in closed short-trade P&L at exit and marks the long
    trade piecewise-linearly while open.  Index is tz-aware UTC midnight, as
    the daily providers produce.
    """
    trades = []
    for i in range(10):
        entry = pd.Timestamp(f"{2016 + i // 2}-0{2 + (i % 2) * 5}-01")
        exit_ = entry + pd.Timedelta(days=20)
        trades.append((entry, exit_, 1_000.0))
    for i in range(6):
        entry = pd.Timestamp(f"{2023 + i // 3}-0{2 + (i % 3) * 3}-01")
        exit_ = entry + pd.Timedelta(days=15)
        trades.append((entry, exit_, -1_000.0))
    long_entry, long_exit, long_profit = (
        pd.Timestamp("2019-01-02"), pd.Timestamp("2024-06-03"), 5_000.0)
    long_trough_at, long_trough = pd.Timestamp("2022-12-30"), -40_000.0
    trades.append((long_entry, long_exit, long_profit))

    trade_log = [
        {
            "Symbol": "AAA",
            "EntryDate": e.strftime("%Y-%m-%d"),
            "ExitDate": x.strftime("%Y-%m-%d"),
            "EntryPrice": 100.0,
            "ExitPrice": 100.0 + p / 100.0,
            "Shares": 100,
            "Profit": p,
            "ProfitPct": p / 10_000.0,
            "HoldDuration": (x - e).days,
            "ExitReason": "Signal",
        }
        for e, x, p in sorted(trades, key=lambda t: t[1])
    ]

    days = pd.bdate_range(SPY_START, SPY_END)
    equity = []
    for d in days:
        realised = sum(p for e, x, p in trades if x <= d and (e, x, p) != (long_entry, long_exit, long_profit))
        if d >= long_exit:
            open_mtm = long_profit
        elif d >= long_trough_at:
            frac = (d - long_trough_at).days / (long_exit - long_trough_at).days
            open_mtm = long_trough + (long_profit - long_trough) * frac
        elif d >= long_entry:
            open_mtm = long_trough * (d - long_entry).days / (long_trough_at - long_entry).days
        else:
            open_mtm = 0.0
        equity.append(INITIAL_CAPITAL + realised + open_mtm)
    timeline = pd.Series(equity, index=days.tz_localize("UTC"), name="Equity")
    return trade_log, timeline


def _main_reference(trade_log, timeline):
    """main.py's WFA exactly as it was written inline before #477."""
    split = wfa.get_split_date(SPY_START, SPY_END, RATIO)
    is_t, oos_t = wfa.split_trades(trade_log, split)
    res = wfa.evaluate_wfa(
        is_t, oos_t, INITIAL_CAPITAL,
        equity_curve=timeline,
        is_window=(SPY_START, split),
        oos_window=(split, pd.Timestamp(SPY_END) + pd.Timedelta(days=1)),
    )
    return split, res


def _write_run_dir(tmp_path, trade_log, timeline, with_inputs=True):
    """Lay out a run folder the way main.py / helpers.summary write it."""
    from helpers.summary import _safe_strategy_name

    run_dir = tmp_path / "run"
    csv_dir = run_dir / "analyzer_csvs" / "Port"
    csv_dir.mkdir(parents=True)
    (run_dir / "config_snapshot.json").write_text(json.dumps({
        "wfa_split_ratio": RATIO,
        "initial_capital": INITIAL_CAPITAL,
    }))
    if with_inputs:
        split = wfa.get_split_date(SPY_START, SPY_END, RATIO)
        assert wfa.save_wfa_inputs(str(run_dir), split, SPY_START, SPY_END, RATIO)

    # Same mapping + writers as helpers/summary.py Step 4a.
    column_map = {"EntryDate": "Date", "ExitDate": "Ex. date", "EntryPrice": "Price",
                  "ExitPrice": "Ex. Price", "ProfitPct": "% Profit", "HoldDuration": "# bars"}
    stem = _safe_strategy_name("Long Hold")
    mapped = pd.DataFrame(trade_log).rename(columns=column_map)
    mapped["% Profit"] = mapped["% Profit"] * 100.0
    mapped.to_csv(csv_dir / f"{stem}.csv", index=False)
    timeline.rename("Equity").rename_axis("Date").to_csv(csv_dir / f"{stem}_equity.csv")
    return run_dir, csv_dir / f"{stem}.csv"


def _report_config(run_dir, monkeypatch):
    """Run report.py --all with the analyzer stubbed; return the config it built."""
    import report as report_cli

    captured = []
    monkeypatch.setattr(report_cli, "generate_trade_report",
                        lambda df, out, name, cfg: captured.append((df, cfg)))
    monkeypatch.setattr(sys, "argv", ["report.py", "--all", str(run_dir)])
    report_cli.main()
    assert len(captured) == 1
    return captured[0]


def _analyzer_wfa(trades_df_raw, cfg):
    """The analyzer's WFA step with the inputs report.py hands it."""
    from trade_analyzer import analyzer, data_handler

    raw = analyzer._raw_wfa_trades(trades_df_raw)
    cleaned, _ = data_handler.clean_trades_data(trades_df_raw.copy(), cfg["INITIAL_EQUITY"])
    inputs = cfg.get("WFA_INPUTS")
    ratio = inputs["wfa_split_ratio"] if inputs else cfg.get("WFA_SPLIT_RATIO")
    return analyzer._compute_wfa(
        raw, cleaned, cleaned["Date"].min(), cleaned["Ex. date"].max(),
        cfg["INITIAL_EQUITY"], ratio, inputs, cfg.get("PORTFOLIO_TIMELINE"),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMainPathUnchanged:
    def test_evaluate_run_wfa_equals_inline_main_code(self):
        trade_log, timeline = _synthetic_run()
        split, ref = _main_reference(trade_log, timeline)
        got = wfa.evaluate_run_wfa(trade_log, INITIAL_CAPITAL, split,
                                   SPY_START, SPY_END, equity_curve=timeline)
        assert got == ref

    def test_long_trade_straddles_split(self):
        """Guard the fixture: the case only bites if a trade spans the split."""
        trade_log, _ = _synthetic_run()
        split = pd.Timestamp(wfa.get_split_date(SPY_START, SPY_END, RATIO))
        assert any(pd.Timestamp(t["EntryDate"]) < split <= pd.Timestamp(t["ExitDate"])
                   for t in trade_log)


class TestReportMatchesMain:
    def test_split_oos_pnl_and_verdict_match_main(self, tmp_path, monkeypatch):
        trade_log, timeline = _synthetic_run()
        ref_split, ref = _main_reference(trade_log, timeline)
        run_dir, _ = _write_run_dir(tmp_path, trade_log, timeline)

        df, cfg = _report_config(run_dir, monkeypatch)
        assert cfg["WFA_INPUTS"]["wfa_split_date"] == ref_split
        assert cfg["PORTFOLIO_TIMELINE"] is not None

        split, res = _analyzer_wfa(df, cfg)
        assert split == ref_split
        assert res["wfa_verdict"] == ref["wfa_verdict"]
        assert res["oos_pnl_pct"] == pytest.approx(ref["oos_pnl_pct"], abs=1e-12)
        assert res["wfa_basis"] == "run"
        assert res["wfa_basis_note"] is None

    def test_legacy_path_would_have_differed(self, tmp_path, monkeypatch):
        """Without the run's inputs the old trade-span / closed-trade method
        gives a different answer on this fixture -- the bug #477 describes."""
        trade_log, timeline = _synthetic_run()
        ref_split, ref = _main_reference(trade_log, timeline)
        run_dir, _ = _write_run_dir(tmp_path, trade_log, timeline, with_inputs=False)

        df, cfg = _report_config(run_dir, monkeypatch)
        assert cfg["WFA_INPUTS"] is None
        split, res = _analyzer_wfa(df, cfg)
        assert ref["wfa_verdict"] == "Pass" and ref["oos_pnl_pct"] > 0.5
        assert split != ref_split
        assert res["oos_pnl_pct"] < 0
        assert res["wfa_verdict"] == "Likely Overfitted"

    def test_full_analyzer_run_reports_main_numbers(self, tmp_path, monkeypatch):
        """End-to-end through generate_trade_report (benchmark download stubbed)."""
        from trade_analyzer import analyzer, data_handler, report_generator

        trade_log, timeline = _synthetic_run()
        ref_split, ref = _main_reference(trade_log, timeline)
        run_dir, _ = _write_run_dir(tmp_path, trade_log, timeline)
        df, cfg = _report_config(run_dir, monkeypatch)

        seen = {}
        real_summary = report_generator.generate_wfa_summary

        def _spy(wfa_result, split_date, ratio):
            seen.update(result=dict(wfa_result), split=split_date)
            return real_summary(wfa_result, split_date, ratio)

        monkeypatch.setattr(report_generator, "generate_wfa_summary", _spy)
        monkeypatch.setattr(data_handler, "download_benchmark_data", lambda *a, **k: None)
        monkeypatch.setattr(report_generator, "generate_markdown_report", lambda *a, **k: None)
        cfg = {**cfg, "BASE_OUTPUT_DIRECTORY": str(tmp_path / "reports")}
        analyzer.generate_trade_report(df, str(tmp_path / "reports"), "Long_Hold", cfg)
        plt.close("all")

        assert seen["split"] == ref_split
        assert seen["result"]["wfa_verdict"] == ref["wfa_verdict"]
        assert seen["result"]["oos_pnl_pct"] == pytest.approx(ref["oos_pnl_pct"], abs=1e-12)


class TestFallbackIsLabelled:
    def test_no_inputs_is_labelled_approximation(self, tmp_path, monkeypatch, capsys):
        from trade_analyzer.analyzer import WFA_APPROX_LABEL

        trade_log, timeline = _synthetic_run()
        run_dir, _ = _write_run_dir(tmp_path, trade_log, timeline, with_inputs=False)
        df, cfg = _report_config(run_dir, monkeypatch)
        split, res = _analyzer_wfa(df, cfg)

        assert split is not None
        assert res["wfa_basis"] == "approximation"
        assert WFA_APPROX_LABEL in res["wfa_basis_note"]
        assert WFA_APPROX_LABEL in capsys.readouterr().out

    def test_inputs_without_equity_curve_is_labelled(self, tmp_path, monkeypatch):
        from trade_analyzer.analyzer import WFA_APPROX_LABEL

        trade_log, timeline = _synthetic_run()
        run_dir, csv_path = _write_run_dir(tmp_path, trade_log, timeline)
        (csv_path.parent / f"{csv_path.stem}_equity.csv").unlink()
        df, cfg = _report_config(run_dir, monkeypatch)
        split, res = _analyzer_wfa(df, cfg)

        assert split == wfa.get_split_date(SPY_START, SPY_END, RATIO)
        assert res["wfa_basis"] == "approximation"
        assert WFA_APPROX_LABEL in res["wfa_basis_note"]

    def test_label_in_text_section(self):
        from trade_analyzer.report_generator import generate_wfa_summary

        res = {"oos_pnl_pct": 0.05, "wfa_verdict": "Pass", "wfa_basis": "approximation",
               "wfa_basis_note": "closed-trade approximation: test"}
        _, text = generate_wfa_summary(res, "2023-01-01", 0.8)
        assert "closed-trade approximation" in text.lower()

        res_run = {"oos_pnl_pct": 0.05, "wfa_verdict": "Pass", "wfa_basis": "run",
                   "wfa_basis_note": None}
        _, text_run = generate_wfa_summary(res_run, "2023-01-01", 0.8)
        assert "approximation" not in text_run.lower()

    def test_label_on_classic_pdf_wfa_page(self):
        from trade_analyzer._pdf_pages import build_wfa_page

        trades_df = pd.DataFrame({
            "Ex. date": pd.to_datetime(["2022-01-03", "2023-06-01"]),
            "Equity": [101_000.0, 102_000.0],
        })
        res = {"oos_pnl_pct": 0.05, "wfa_verdict": "Pass", "wfa_basis": "approximation",
               "wfa_basis_note": "closed-trade approximation: test"}
        fig = build_wfa_page(res, "2023-01-01", 0.8, trades_df, pd.Series(dtype=float))
        texts = [t.get_text() for t in fig.texts]
        plt.close(fig)
        assert any("closed-trade approximation" in t for t in texts)

    @pytest.mark.parametrize("approx", [True, False])
    def test_label_on_v3_header(self, approx):
        from trade_analyzer._pdf_v3 import build_v3_page1

        fig = build_v3_page1({"name": "S", "oos_date": "2023-01-01", "wfa_approx": approx}, {})
        texts = [t.get_text() for t in fig.texts]
        plt.close(fig)
        split_line = next(t for t in texts if "Walk-forward OOS split" in t)
        assert ("closed-trade approximation" in split_line) is approx


@pytest.mark.slow
class TestEndToEndMainThenReport:
    """A real ``main.py`` run (CSV provider, synthetic prices), then report.py.

    Slow (subprocess + worker pool); run with ``pytest -m slow``.
    """

    def test_report_wfa_equals_main_summary(self, tmp_path, monkeypatch):
        import glob
        import os
        import shutil

        import numpy as np

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import _wrapper_harness as harness

        days = pd.bdate_range("2004-01-02", "2019-12-31")
        rng = np.random.default_rng(477)
        close = 50 * np.exp(np.cumsum(rng.normal(0.0004, 0.015, len(days))))
        data_dir = tmp_path / "csv"
        data_dir.mkdir()
        pd.DataFrame({
            "Date": days.strftime("%Y-%m-%d"), "Open": close, "High": close * 1.01,
            "Low": close * 0.99, "Close": close, "Volume": 1_000_000,
        }).to_csv(data_dir / "ZZZ.csv", index=False)

        run_name = f"wfa477_{os.getpid()}"
        patches = {
            "data_provider": "csv", "csv_data_dir": str(data_dir),
            "comparison_tickers": [], "portfolios": {"P": ["ZZZ"]},
            "start_date": "2004-01-02", "end_date": "2019-12-31",
            "strategies": ["SMA Crossover (20d/50d)"], "min_bars_required": 10,
            "pit_warmup_days": 0, "wfa_split_ratio": RATIO, "wfa_folds": None,
            "export_ml_features": False, "save_individual_trades": False,
            "sensitivity_sweep_enabled": False, "upload_to_s3": False,
        }
        harness.run_wrapper(tmp_path, patches, ["--name", run_name], expect_simulation=True)
        runs = glob.glob(os.path.join(harness.PROJECT_ROOT, "output", "runs", f"{run_name}_*"))
        assert len(runs) == 1, runs
        run_dir = runs[0]
        try:
            inputs = wfa.load_wfa_inputs(run_dir)
            assert inputs is not None, "main.py did not write wfa_inputs.json"
            summary = pd.read_csv(os.path.join(run_dir, "overall_portfolio_summary.csv"),
                                  keep_default_na=False)
            row = summary.iloc[0]

            df, cfg = _report_config(run_dir, monkeypatch)
            split, res = _analyzer_wfa(df, cfg)
            assert split == inputs["wfa_split_date"]
            assert res["wfa_basis"] == "run"
            assert res["wfa_verdict"] != "N/A", "fixture too short for a real verdict"
            assert res["wfa_verdict"] == row["WFA Verdict"]
            assert f"{res['oos_pnl_pct']:+.2%}" == row["OOS P&L (%)"]
        finally:
            shutil.rmtree(run_dir, ignore_errors=True)


class TestWfaInputsFile:
    def test_round_trip(self, tmp_path):
        path = wfa.save_wfa_inputs(str(tmp_path), "2023-01-01", SPY_START, SPY_END, RATIO)
        assert path is not None
        assert wfa.load_wfa_inputs(tmp_path) == {
            "wfa_split_ratio": RATIO, "wfa_split_date": "2023-01-01",
            "actual_start": SPY_START, "actual_end": SPY_END,
        }

    def test_missing_returns_none(self, tmp_path):
        assert wfa.load_wfa_inputs(tmp_path) is None

    @pytest.mark.parametrize("content", [
        "not json",
        "[]",
        json.dumps({"wfa_split_ratio": 0.8}),
        json.dumps({"wfa_split_ratio": 1.5, "wfa_split_date": "2023-01-01",
                    "actual_start": SPY_START, "actual_end": SPY_END}),
        json.dumps({"wfa_split_ratio": 0.8, "wfa_split_date": "garbage",
                    "actual_start": SPY_START, "actual_end": SPY_END}),
    ])
    def test_invalid_returns_none(self, tmp_path, content):
        (tmp_path / wfa.WFA_INPUTS_FILENAME).write_text(content)
        assert wfa.load_wfa_inputs(tmp_path) is None
