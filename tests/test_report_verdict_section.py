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
