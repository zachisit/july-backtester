"""Regression tests for issue #479: report.py must not overwrite tearsheets.

When the same strategy name appears in two portfolios of one run, ``report.py
--all`` used to write both reports to ``detailed_reports/<strategy>/``, so the
second portfolio's PDF and Markdown replaced the first. Reports now mirror
``analyzer_csvs/<Portfolio>/``: ``detailed_reports/<Portfolio>/<strategy>/``.

No network: the benchmark download is stubbed.
"""

import json
import os
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

import report  # noqa: E402

STRATEGY_STEM = "SMA_Crossover_20d_50d"


def _trades(symbol, profit_sign, n=12):
    """Analyzer-format trades for one portfolio; P&L sign differs per portfolio."""
    rows = []
    for i in range(n):
        entry = pd.Timestamp("2020-01-02") + pd.Timedelta(days=30 * i)
        exit_ = entry + pd.Timedelta(days=10)
        profit = profit_sign * (500.0 + 37.0 * i)
        rows.append({
            "Symbol": symbol,
            "Trade": "Long",
            "Date": entry.strftime("%Y-%m-%d"),
            "Ex. date": exit_.strftime("%Y-%m-%d"),
            "Price": 100.0,
            "Ex. Price": 100.0 + profit / 100.0,
            "Shares": 100,
            "Profit": profit,
            "% Profit": profit / 100.0,
            "# bars": 10,
        })
    return pd.DataFrame(rows)


def _two_portfolio_run(tmp_path):
    """A run folder where two portfolios share one strategy name."""
    run_dir = tmp_path / "run"
    for portfolio, symbol, sign in (("Portfolio_A", "AAA", 1), ("Portfolio_B", "BBB", -1)):
        csv_dir = run_dir / "analyzer_csvs" / portfolio
        csv_dir.mkdir(parents=True)
        _trades(symbol, sign).to_csv(csv_dir / f"{STRATEGY_STEM}.csv", index=False)
    return run_dir


def _capture(monkeypatch, argv):
    """Run report.main() with the analyzer stubbed; return (out_dir, name, cfg) calls."""
    calls = []
    monkeypatch.setattr(report, "generate_trade_report",
                        lambda df, out, name, cfg: calls.append((out, name, cfg)))
    monkeypatch.setattr(sys, "argv", ["report.py", *argv])
    report.main()
    return calls


class TestBatchReportsDoNotCollide:
    def test_shared_strategy_name_keeps_both_reports(self, tmp_path, monkeypatch):
        """End-to-end: both portfolios' PDF + Markdown exist and differ."""
        from trade_analyzer import data_handler

        run_dir = _two_portfolio_run(tmp_path)
        monkeypatch.setattr(data_handler, "download_benchmark_data", lambda *a, **k: None)
        monkeypatch.setattr(report, "MC_SIMULATIONS", 50)
        monkeypatch.setattr(sys, "argv", ["report.py", "--all", str(run_dir)])
        report.main()
        plt.close("all")

        reports = run_dir / "detailed_reports"
        outputs = {}
        for portfolio in ("Portfolio_A", "Portfolio_B"):
            folder = reports / portfolio / STRATEGY_STEM
            pdf = folder / f"{STRATEGY_STEM}.pdf"
            md = folder / f"{STRATEGY_STEM}.md"
            assert pdf.is_file() and pdf.stat().st_size > 0, f"missing {pdf}"
            assert md.is_file() and md.stat().st_size > 0, f"missing {md}"
            outputs[portfolio] = (pdf.read_bytes(), md.read_text())

        assert outputs["Portfolio_A"][0] != outputs["Portfolio_B"][0]
        md_a, md_b = outputs["Portfolio_A"][1], outputs["Portfolio_B"][1]
        assert md_a != md_b
        # Each report holds its own portfolio's trades, not the other's.
        assert "AAA" in md_a and "BBB" not in md_a
        assert "BBB" in md_b and "AAA" not in md_b
        # Nothing is written to the old, shared strategy-only folder.
        assert not (reports / STRATEGY_STEM).exists()

    def test_all_routes_each_portfolio_to_its_own_folder(self, tmp_path, monkeypatch):
        run_dir = _two_portfolio_run(tmp_path)
        calls = _capture(monkeypatch, ["--all", str(run_dir)])

        out_dirs = sorted(out for out, _, _ in calls)
        assert out_dirs == [str(run_dir / "detailed_reports" / "Portfolio_A"),
                            str(run_dir / "detailed_reports" / "Portfolio_B")]
        for out, name, cfg in calls:
            assert name == STRATEGY_STEM
            assert cfg["BASE_OUTPUT_DIRECTORY"] == out

    def test_flat_analyzer_csvs_layout_unchanged(self, tmp_path, monkeypatch):
        """A CSV directly under analyzer_csvs/ still goes to detailed_reports/."""
        csv_dir = tmp_path / "analyzer_csvs"
        csv_dir.mkdir()
        _trades("AAA", 1).to_csv(csv_dir / "Strat.csv", index=False)
        calls = _capture(monkeypatch, ["--all", str(tmp_path)])

        assert [out for out, _, _ in calls] == [str(tmp_path / "detailed_reports")]

    def test_summary_line_names_report_root(self, tmp_path, monkeypatch, capsys):
        run_dir = _two_portfolio_run(tmp_path)
        _capture(monkeypatch, ["--all", str(run_dir)])
        out = capsys.readouterr().out
        assert f"Generated 2 reports in {run_dir / 'detailed_reports'}" in out


class TestSingleFileMatchesBatchLayout:
    def test_auto_detected_dir_includes_portfolio(self, tmp_path, monkeypatch):
        run_dir = _two_portfolio_run(tmp_path)
        csv = run_dir / "analyzer_csvs" / "Portfolio_B" / f"{STRATEGY_STEM}.csv"
        (out, name, cfg), = _capture(monkeypatch, [str(csv)])

        assert out == str(run_dir / "detailed_reports" / "Portfolio_B")
        assert name == STRATEGY_STEM
        assert cfg["BASE_OUTPUT_DIRECTORY"] == out

    def test_single_file_and_all_agree(self, tmp_path, monkeypatch):
        run_dir = _two_portfolio_run(tmp_path)
        batch = {Path(out).name: out for out, _, _ in
                 _capture(monkeypatch, ["--all", str(run_dir)])}
        for portfolio in ("Portfolio_A", "Portfolio_B"):
            csv = run_dir / "analyzer_csvs" / portfolio / f"{STRATEGY_STEM}.csv"
            (out, _, _), = _capture(monkeypatch, [str(csv)])
            assert out == batch[portfolio]

    def test_explicit_output_dir_is_used_as_given(self, tmp_path, monkeypatch):
        run_dir = _two_portfolio_run(tmp_path)
        csv = run_dir / "analyzer_csvs" / "Portfolio_A" / f"{STRATEGY_STEM}.csv"
        custom = tmp_path / "my_reports"
        (out, _, _), = _capture(monkeypatch, [str(csv), "--output-dir", str(custom)])
        assert out == str(custom)

    def test_csv_outside_a_run_unchanged(self, tmp_path, monkeypatch):
        csv = tmp_path / "trades.csv"
        _trades("AAA", 1).to_csv(csv, index=False)
        (out, _, _), = _capture(monkeypatch, [str(csv)])
        assert out == "detailed_reports"


class TestPortfolioSubdir:
    @pytest.mark.parametrize("path, expected", [
        ("run/analyzer_csvs/Nasdaq_100/Strat.csv", Path("Nasdaq_100")),
        ("run/analyzer_csvs/Strat.csv", Path()),
        ("elsewhere/Strat.csv", Path()),
        ("Strat.csv", Path()),
    ])
    def test_portfolio_subdir(self, path, expected):
        assert report._portfolio_subdir(Path(path)) == expected


class TestRunLayoutDetection:
    """Codex review of #480: normalised paths, last ``analyzer_csvs`` wins."""

    @pytest.mark.parametrize("path, expected", [
        ("run/analyzer_csvs/../analyzer_csvs/P/S.csv", ("run", "P")),
        ("a/analyzer_csvs/run/analyzer_csvs/P/S.csv", ("a/analyzer_csvs/run", "P")),
        ("run/analyzer_csvs/P/./S.csv", ("run", "P")),
        ("run/analyzer_csvs/S.csv", ("run", "")),
        ("elsewhere/analyzer_csvs", (None, "")),
        ("elsewhere/S.csv", (None, "")),
    ])
    def test_run_layout(self, path, expected, tmp_path, monkeypatch):
        """Relative paths resolve against the cwd (no run files on disk here)."""
        monkeypatch.chdir(tmp_path)
        run, sub = expected
        want = (None if run is None else Path(os.path.realpath(tmp_path)) / run, Path(sub))
        assert report._run_layout(Path(path)) == want

    def test_dotdot_path_writes_to_portfolio_folder(self, tmp_path, monkeypatch):
        run_dir = _two_portfolio_run(tmp_path)
        csv = (run_dir / "analyzer_csvs" / ".." / "analyzer_csvs" / "Portfolio_A"
               / f"{STRATEGY_STEM}.csv")
        (out, _, _), = _capture(monkeypatch, [str(csv)])
        assert out == str(run_dir / "detailed_reports" / "Portfolio_A")

    def test_parent_folder_named_analyzer_csvs(self, tmp_path, monkeypatch):
        """Single-file mode finds the same run, folder and inputs as --all."""
        from helpers import wfa

        outer = tmp_path / "analyzer_csvs"
        run_dir = _two_portfolio_run(outer)
        (run_dir / "config_snapshot.json").write_text(
            json.dumps({"initial_capital": 12_345.0, "wfa_split_ratio": 0.8}))
        assert wfa.save_wfa_inputs(str(run_dir), "2020-08-01", "2020-01-02",
                                   "2020-12-31", 0.8, initial_capital=12_345.0)

        batch = {Path(out).name: (out, cfg) for out, _, cfg in
                 _capture(monkeypatch, ["--all", str(run_dir)])}
        csv = run_dir / "analyzer_csvs" / "Portfolio_A" / f"{STRATEGY_STEM}.csv"
        (out, _, cfg), = _capture(monkeypatch, [str(csv)])

        batch_out, batch_cfg = batch["Portfolio_A"]
        assert out == batch_out == str(run_dir / "detailed_reports" / "Portfolio_A")
        assert cfg["INITIAL_EQUITY"] == batch_cfg["INITIAL_EQUITY"] == 12_345.0
        assert cfg["WFA_INPUTS"] is not None
        assert cfg["WFA_INPUTS"] == batch_cfg["WFA_INPUTS"]


def _snapshot_run(run_dir, capital=12_345.0):
    """Write the run-level files main.py leaves at the top of a run folder."""
    from helpers import wfa

    (run_dir / "config_snapshot.json").write_text(
        json.dumps({"initial_capital": capital, "wfa_split_ratio": 0.8}))
    assert wfa.save_wfa_inputs(str(run_dir), "2020-08-01", "2020-01-02",
                               "2020-12-31", 0.8, initial_capital=capital)


class TestAmbiguousRunFolders:
    """Codex review #2 of #480: same-named folders and symlinks."""

    def _assert_matches_all(self, monkeypatch, run_dir, csvs):
        batch = {o: cfg for o, _, cfg in _capture(monkeypatch, ["--all", str(run_dir)])}
        assert len(batch) == 2
        for csv, portfolio in csvs:
            (out, _, cfg), = _capture(monkeypatch, [str(csv)])
            expected = str(run_dir / "detailed_reports" / portfolio)
            assert out == expected
            assert expected in batch
            assert cfg["INITIAL_EQUITY"] == batch[expected]["INITIAL_EQUITY"] == 12_345.0
            assert cfg["WFA_INPUTS"] is not None
            assert cfg["WFA_INPUTS"] == batch[expected]["WFA_INPUTS"]

    def test_portfolio_named_analyzer_csvs_under_parent_named_analyzer_csvs(
            self, tmp_path, monkeypatch):
        """A portfolio called ``analyzer_csvs`` inside a run that itself sits
        under a parent folder called ``analyzer_csvs``: single-file mode must
        find the run (and its config) that --all uses, for every portfolio."""
        run_dir = tmp_path / "analyzer_csvs" / "run"
        for portfolio, symbol in (("analyzer_csvs", "AAA"), ("Portfolio_B", "BBB")):
            csv_dir = run_dir / "analyzer_csvs" / portfolio
            csv_dir.mkdir(parents=True)
            _trades(symbol, 1).to_csv(csv_dir / f"{STRATEGY_STEM}.csv", index=False)
        _snapshot_run(run_dir)

        self._assert_matches_all(monkeypatch, run_dir, [
            (run_dir / "analyzer_csvs" / "analyzer_csvs" / f"{STRATEGY_STEM}.csv",
             "analyzer_csvs"),
            (run_dir / "analyzer_csvs" / "Portfolio_B" / f"{STRATEGY_STEM}.csv",
             "Portfolio_B"),
        ])

    @pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlink support")
    def test_symlink_then_dotdot_follows_the_filesystem(self, tmp_path, monkeypatch):
        """``entry/link/../run`` is ``storage/run`` when ``link -> storage/nested``."""
        storage = tmp_path / "storage"
        (storage / "nested").mkdir(parents=True)
        run_dir = _two_portfolio_run(storage)        # storage/run
        _snapshot_run(run_dir)
        (tmp_path / "entry").mkdir()
        try:
            os.symlink(storage / "nested", tmp_path / "entry" / "link")
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"cannot create symlinks here: {exc}")

        csv = (tmp_path / "entry" / "link" / ".." / "run" / "analyzer_csvs"
               / "Portfolio_A" / f"{STRATEGY_STEM}.csv")
        assert csv.is_file()
        self._assert_matches_all(monkeypatch, run_dir, [(csv, "Portfolio_A")])

    @pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlink support")
    def test_symlinked_analyzer_csvs_folder(self, tmp_path, monkeypatch):
        """``run/analyzer_csvs -> archive/trades``: realpath drops the
        ``analyzer_csvs`` name, so the run must be found from the path as given."""
        archive = _two_portfolio_run(tmp_path / "archive") / "analyzer_csvs"
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        _snapshot_run(run_dir)
        trades = tmp_path / "archive" / "trades"
        archive.rename(trades)
        try:
            os.symlink(trades, run_dir / "analyzer_csvs", target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"cannot create symlinks here: {exc}")

        self._assert_matches_all(monkeypatch, run_dir, [
            (run_dir / "analyzer_csvs" / p / f"{STRATEGY_STEM}.csv", p)
            for p in ("Portfolio_A", "Portfolio_B")
        ])


class TestAllIgnoresOutputDir:
    def test_all_warns_and_ignores_output_dir(self, tmp_path, monkeypatch, capsys):
        run_dir = _two_portfolio_run(tmp_path)
        custom = tmp_path / "my_reports"
        calls = _capture(monkeypatch, ["--all", str(run_dir), "--output-dir", str(custom)])

        out = capsys.readouterr().out
        assert "WARNING: --output-dir is ignored with --all" in out
        assert len(calls) == 2
        assert sorted(o for o, _, _ in calls) == [
            str(run_dir / "detailed_reports" / "Portfolio_A"),
            str(run_dir / "detailed_reports" / "Portfolio_B"),
        ]
        assert all(cfg["BASE_OUTPUT_DIRECTORY"] == o for o, _, cfg in calls)
        assert not custom.exists()

    def test_no_warning_without_output_dir(self, tmp_path, monkeypatch, capsys):
        run_dir = _two_portfolio_run(tmp_path)
        _capture(monkeypatch, ["--all", str(run_dir)])
        assert "--output-dir is ignored" not in capsys.readouterr().out
