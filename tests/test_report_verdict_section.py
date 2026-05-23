"""Tests for trade_analyzer.report_generator.generate_strategy_verdict_summary
and the report.py helpers that load/match llm_verdict entries to per-strategy
CSV files.
"""
import json
import sys
from pathlib import Path

import pytest

# report.py lives at the project root, not under a package
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

import report as report_cli  # noqa: E402
from trade_analyzer import report_generator  # noqa: E402


SAMPLE_VERDICT = {
    "strategy": "EC-VIX-27: WR70 SMA120 minimal-entry-25 vix-95th VIX-pct",
    "portfolio": "NDX+Energy+Defense",
    "verdict": "BEATS SPY by +2522.16pp",
    "mc_verdict": "DD Understated, High Tail Risk",
    "mc_score": -1,
    "wfa_verdict": "Pass",
    "wfa_rolling_verdict": "Pass (5/5)",
    "curve_smoothness": {
        "smooth_verdict": "ACCEPTABLE",
        "smooth_notes": ["plateau: 21 consecutive months without new high"],
    },
}


class TestGenerateStrategyVerdictSummary:
    def test_returns_title_and_text(self):
        title, text = report_generator.generate_strategy_verdict_summary(SAMPLE_VERDICT)
        assert title == "Strategy Verdict"
        assert isinstance(text, str) and text

    def test_text_contains_all_verdicts(self):
        _, text = report_generator.generate_strategy_verdict_summary(SAMPLE_VERDICT)
        assert "BEATS SPY by +2522.16pp" in text
        assert "DD Understated, High Tail Risk" in text
        assert "Pass" in text
        assert "Pass (5/5)" in text
        assert "ACCEPTABLE" in text
        assert "plateau:" in text

    def test_none_returns_placeholder(self):
        title, text = report_generator.generate_strategy_verdict_summary(None)
        assert title == "Strategy Verdict"
        assert "No strategy verdict" in text

    def test_empty_dict_returns_placeholder(self):
        title, text = report_generator.generate_strategy_verdict_summary({})
        assert title == "Strategy Verdict"
        assert "No strategy verdict" in text

    def test_partial_verdict_renders_what_it_has(self):
        partial = {"strategy": "S1", "verdict": "BEATS SPY by +10pp"}
        _, text = report_generator.generate_strategy_verdict_summary(partial)
        assert "S1" in text
        assert "BEATS SPY by +10pp" in text

    def test_no_smoothness_notes(self):
        v = dict(SAMPLE_VERDICT)
        v["curve_smoothness"] = {"smooth_verdict": "SMOOTH", "smooth_notes": []}
        _, text = report_generator.generate_strategy_verdict_summary(v)
        assert "SMOOTH" in text
        assert "plateau" not in text


class TestSanitizeForFilename:
    def test_replaces_spaces(self):
        assert report_cli._sanitize_for_filename("EC VIX 27") == "EC_VIX_27"

    def test_drops_parens(self):
        assert report_cli._sanitize_for_filename("Foo (Bar)") == "Foo_Bar"

    def test_drops_colons(self):
        assert report_cli._sanitize_for_filename("EC-VIX-27: WR70") == "EC-VIX-27_WR70"

    def test_handles_empty_and_none(self):
        assert report_cli._sanitize_for_filename("") == ""
        assert report_cli._sanitize_for_filename(None) == ""


class TestLoadStrategyVerdicts:
    def test_missing_file_returns_empty_list(self, tmp_path):
        assert report_cli._load_strategy_verdicts(tmp_path) == []

    def test_loads_strategies_list(self, tmp_path):
        payload = {"strategies": [SAMPLE_VERDICT]}
        (tmp_path / "llm_verdict.json").write_text(json.dumps(payload))
        out = report_cli._load_strategy_verdicts(tmp_path)
        assert len(out) == 1
        assert out[0]["strategy"] == SAMPLE_VERDICT["strategy"]

    def test_malformed_json_returns_empty_list(self, tmp_path):
        (tmp_path / "llm_verdict.json").write_text("{not valid json")
        assert report_cli._load_strategy_verdicts(tmp_path) == []

    def test_missing_strategies_key_returns_empty(self, tmp_path):
        (tmp_path / "llm_verdict.json").write_text("{}")
        assert report_cli._load_strategy_verdicts(tmp_path) == []


class TestMatchStrategyVerdict:
    def test_exact_match_on_strategy_and_portfolio(self):
        sanitized_strat = report_cli._sanitize_for_filename(SAMPLE_VERDICT["strategy"])
        sanitized_port = report_cli._sanitize_for_filename(SAMPLE_VERDICT["portfolio"])
        match = report_cli._match_strategy_verdict([SAMPLE_VERDICT], sanitized_strat, sanitized_port)
        assert match is not None
        assert match["strategy"] == SAMPLE_VERDICT["strategy"]

    def test_no_match_returns_none(self):
        assert report_cli._match_strategy_verdict([SAMPLE_VERDICT], "nope", "wrong") is None

    def test_fallback_match_on_strategy_only(self):
        sanitized_strat = report_cli._sanitize_for_filename(SAMPLE_VERDICT["strategy"])
        # Portfolio mismatch — fallback path should still match by strategy name alone
        match = report_cli._match_strategy_verdict([SAMPLE_VERDICT], sanitized_strat, "Different_Port")
        assert match is not None
        assert match["strategy"] == SAMPLE_VERDICT["strategy"]

    def test_empty_verdicts_returns_none(self):
        assert report_cli._match_strategy_verdict([], "anything", "anything") is None


# ---------------------------------------------------------------------------
# Test Class: Modern tearsheet PDF Strategy Verdict page (TDD)
# ---------------------------------------------------------------------------
# The modern PDF generator (trade_analyzer._pdf_pages.generate_tearsheet_pdf)
# builds pages from a separate report_data dict, NOT from the legacy
# report_sections list. The Strategy Verdict section must be rendered as its
# own page in this modern flow.

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _collect_text(fig) -> str:
    """Return concatenated text content of all text artists in a Figure."""
    pieces = []
    for ax in fig.get_axes():
        for t in ax.texts:
            pieces.append(t.get_text())
    for t in fig.texts:
        pieces.append(t.get_text())
    return "\n".join(pieces)


class TestBuildStrategyVerdictPage:
    def test_returns_figure_when_verdict_provided(self):
        from trade_analyzer._pdf_pages import build_strategy_verdict_page
        fig = build_strategy_verdict_page(SAMPLE_VERDICT)
        assert fig is not None
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_returns_none_when_verdict_missing(self):
        from trade_analyzer._pdf_pages import build_strategy_verdict_page
        assert build_strategy_verdict_page(None) is None

    def test_returns_none_when_verdict_empty(self):
        from trade_analyzer._pdf_pages import build_strategy_verdict_page
        assert build_strategy_verdict_page({}) is None

    def test_figure_contains_benchmark_verdict(self):
        from trade_analyzer._pdf_pages import build_strategy_verdict_page
        fig = build_strategy_verdict_page(SAMPLE_VERDICT)
        text = _collect_text(fig)
        assert "BEATS SPY by +2522.16pp" in text
        plt.close(fig)

    def test_figure_contains_mc_verdict(self):
        from trade_analyzer._pdf_pages import build_strategy_verdict_page
        fig = build_strategy_verdict_page(SAMPLE_VERDICT)
        text = _collect_text(fig)
        assert "DD Understated, High Tail Risk" in text
        plt.close(fig)

    def test_figure_contains_smoothness_and_notes(self):
        from trade_analyzer._pdf_pages import build_strategy_verdict_page
        fig = build_strategy_verdict_page(SAMPLE_VERDICT)
        text = _collect_text(fig)
        assert "ACCEPTABLE" in text
        assert "plateau:" in text
        plt.close(fig)

    def test_figure_contains_page_title(self):
        from trade_analyzer._pdf_pages import build_strategy_verdict_page
        fig = build_strategy_verdict_page(SAMPLE_VERDICT)
        text = _collect_text(fig)
        assert "Strategy Verdict" in text
        plt.close(fig)


class TestGenerateTearsheetPdfIncludesVerdict:
    def test_strategy_verdict_page_present_in_pdf(self, tmp_path, monkeypatch):
        """When report_data carries 'strategy_verdict', generate_tearsheet_pdf
        must add a 'Strategy Verdict' entry to its internal pages list."""
        from trade_analyzer import _pdf_pages

        captured = []

        class _RecordingPdfPages:
            def __init__(self, path):
                self.path = path
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def savefig(self, fig, **kwargs):
                # Record the page title from any axes that contain a likely title text
                title = ""
                for ax in fig.get_axes():
                    for t in ax.texts:
                        s = t.get_text() or ""
                        if "Strategy Verdict" in s or "Executive Summary" in s or "Walk-Forward" in s:
                            title = s
                            break
                    if title:
                        break
                captured.append(title)

        monkeypatch.setattr(_pdf_pages, "PdfPages", _RecordingPdfPages)

        import pandas as _pd
        trades_df = _pd.DataFrame({
            "Date": _pd.to_datetime(["2020-01-02", "2020-06-01"]),
            "Ex. date": _pd.to_datetime(["2020-03-01", "2020-09-01"]),
            "Profit": [100.0, -50.0],
        })
        report_data = {
            "name": "TestStrat",
            "run_date": "20260522_120000",
            "trades_df": trades_df,
            "initial_equity": 100_000,
            "daily_equity": _pd.Series([100_000, 110_000], index=trades_df["Date"]),
            "daily_returns": _pd.Series([0.0, 0.1], index=trades_df["Date"]),
            "benchmark_df": None,
            "benchmark_ticker": "SPY",
            "monthly_perf": _pd.DataFrame(),
            "symbol_perf": _pd.DataFrame(),
            "mc_results": {},
            "wfa_result": {},
            "core_metrics": {"total_profit": 50.0, "sharpe": 1.0, "profit_factor": 2.0, "total_trades": 2},
            "risk_free_rate": 0.05,
            "rolling_window": 50,
            "cleaning_summary": "",
            "overall_metrics_text": "",
            "top_n_trades": 10,
            "strategy_verdict": SAMPLE_VERDICT,
        }
        output_path = tmp_path / "out.pdf"
        _pdf_pages.generate_tearsheet_pdf(report_data, str(output_path))

        # At least one captured page must be the Strategy Verdict page
        assert any("Strategy Verdict" in c for c in captured), \
            f"expected a Strategy Verdict page; captured titles: {captured}"
