"""Tests for scripts/build_research_index.py — the cross-run research index.

Covers:
  _extract_strategies_from_file — @register_strategy block parsing
  build_strategy_lookup         — recursive scan of custom_strategies/
  load_llm_verdicts             — llm_verdict.json ingest + dual keying
  _normalise_row                — header-variant mapping onto OUTPUT_COLS
  collect_csv_rows              — run summary collection + --runs-only filter
  main                          — end-to-end CSV output and enrichment join

No network, no randomness. All file I/O is real, against tmp_path.

The module resolves its paths into module-level constants at import time, so
every test rebinds PROJECT_ROOT / STRATEGY_DIR / RUNS_DIR / OUTPUT_PATH onto a
throwaway tree via the `proj` fixture.
"""
import csv
import json
import os
import sys

import pytest

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import build_research_index as bri  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

STRAT_ONE = '''
from helpers.registry import register_strategy


@register_strategy(
    name="Alpha Strategy",
    dependencies=[],
    params={
        "fast": 20,
        "slow": 50,
    },
)
def alpha(df, **kwargs):
    return df
'''

STRAT_TWO = '''
from helpers.registry import register_strategy


@register_strategy(name="Beta Strategy", params={"length": 14})
def beta(df, **kwargs):
    return df


@register_strategy(name="Gamma Strategy")
def gamma(df, **kwargs):
    return df
'''

# A decorated function with no name= must be skipped, not crash the parse.
STRAT_NAMELESS = '''
from helpers.registry import register_strategy


@register_strategy(params={"x": 1})
def anon(df, **kwargs):
    return df
'''


@pytest.fixture
def proj(tmp_path, monkeypatch):
    """Build a throwaway project tree and point the module's globals at it."""
    strategies = tmp_path / "custom_strategies"
    (strategies / "private" / "promotions" / "DB").mkdir(parents=True)
    runs = tmp_path / "output" / "runs"
    runs.mkdir(parents=True)

    monkeypatch.setattr(bri, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(bri, "STRATEGY_DIR", strategies)
    monkeypatch.setattr(bri, "RUNS_DIR", runs)
    monkeypatch.setattr(bri, "OUTPUT_PATH", tmp_path / "output" / "research_index.csv")
    return tmp_path


def _write_run(root, run_id, rows, verdicts=None, header=None):
    """Create output/runs/<run_id>/ with a summary CSV and optional verdict JSON."""
    d = root / "output" / "runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    header = header or list(rows[0].keys())
    with open(d / "overall_portfolio_summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header)
        w.writeheader()
        w.writerows(rows)
    if verdicts is not None:
        (d / "llm_verdict.json").write_text(json.dumps(verdicts), encoding="utf-8")
    return d


# ──────────────────────────────────────────────────────────────────────────────
# _extract_strategies_from_file
# ──────────────────────────────────────────────────────────────────────────────
class TestExtractStrategies:

    def test_parses_name_and_counts_params(self, proj):
        p = proj / "custom_strategies" / "one.py"
        p.write_text(STRAT_ONE, encoding="utf-8")
        out = bri._extract_strategies_from_file(p)
        assert set(out) == {"Alpha Strategy"}
        assert out["Alpha Strategy"]["param_count"] == 2

    def test_code_file_is_relative_to_project_root(self, proj):
        p = proj / "custom_strategies" / "one.py"
        p.write_text(STRAT_ONE, encoding="utf-8")
        out = bri._extract_strategies_from_file(p)
        assert out["Alpha Strategy"]["code_file"] == os.path.join("custom_strategies", "one.py")
        assert not os.path.isabs(out["Alpha Strategy"]["code_file"])

    def test_multiple_strategies_in_one_file(self, proj):
        p = proj / "custom_strategies" / "two.py"
        p.write_text(STRAT_TWO, encoding="utf-8")
        out = bri._extract_strategies_from_file(p)
        assert set(out) == {"Beta Strategy", "Gamma Strategy"}
        assert out["Beta Strategy"]["param_count"] == 1

    def test_strategy_without_params_counts_zero(self, proj):
        p = proj / "custom_strategies" / "two.py"
        p.write_text(STRAT_TWO, encoding="utf-8")
        out = bri._extract_strategies_from_file(p)
        assert out["Gamma Strategy"]["param_count"] == 0

    def test_block_without_name_is_skipped(self, proj):
        p = proj / "custom_strategies" / "anon.py"
        p.write_text(STRAT_NAMELESS, encoding="utf-8")
        assert bri._extract_strategies_from_file(p) == {}

    def test_file_with_no_decorators_yields_nothing(self, proj):
        p = proj / "custom_strategies" / "plain.py"
        p.write_text("def helper():\n    return 1\n", encoding="utf-8")
        assert bri._extract_strategies_from_file(p) == {}


# ──────────────────────────────────────────────────────────────────────────────
# build_strategy_lookup — the recursive-scan behaviour this script depends on
# ──────────────────────────────────────────────────────────────────────────────
class TestBuildStrategyLookup:

    def test_finds_top_level_bundled_plugins(self, proj):
        (proj / "custom_strategies" / "one.py").write_text(STRAT_ONE, encoding="utf-8")
        assert "Alpha Strategy" in bri.build_strategy_lookup()

    def test_finds_strategies_in_nested_subdirectories(self, proj):
        """Regression: a flat *.py glob missed both the private submodule and
        anything nested inside it."""
        nested = proj / "custom_strategies" / "private" / "promotions" / "DB" / "nested.py"
        nested.write_text(STRAT_TWO, encoding="utf-8")
        lookup = bri.build_strategy_lookup()
        assert "Beta Strategy" in lookup
        assert lookup["Beta Strategy"]["code_file"].endswith("nested.py")

    def test_merges_across_top_level_and_nested(self, proj):
        (proj / "custom_strategies" / "one.py").write_text(STRAT_ONE, encoding="utf-8")
        (proj / "custom_strategies" / "private" / "priv.py").write_text(STRAT_TWO, encoding="utf-8")
        lookup = bri.build_strategy_lookup()
        assert {"Alpha Strategy", "Beta Strategy", "Gamma Strategy"} <= set(lookup)

    def test_skips_template_file(self, proj):
        tpl = proj / "custom_strategies" / "private" / "_TEMPLATE_strategy.py"
        tpl.write_text(STRAT_ONE, encoding="utf-8")
        assert bri.build_strategy_lookup() == {}

    def test_skips_dunder_files(self, proj):
        (proj / "custom_strategies" / "__init__.py").write_text(STRAT_ONE, encoding="utf-8")
        assert bri.build_strategy_lookup() == {}

    def test_unreadable_file_does_not_abort_the_scan(self, proj, monkeypatch):
        good = proj / "custom_strategies" / "good.py"
        good.write_text(STRAT_ONE, encoding="utf-8")
        bad = proj / "custom_strategies" / "bad.py"
        bad.write_text(STRAT_TWO, encoding="utf-8")

        real = bri._extract_strategies_from_file

        def boom(path):
            if path.name == "bad.py":
                raise OSError("unreadable")
            return real(path)

        monkeypatch.setattr(bri, "_extract_strategies_from_file", boom)
        lookup = bri.build_strategy_lookup()
        assert "Alpha Strategy" in lookup      # good file still parsed
        assert "Beta Strategy" not in lookup   # bad file skipped, not fatal

    def test_missing_strategy_dir_yields_empty_lookup(self, proj, monkeypatch):
        monkeypatch.setattr(bri, "STRATEGY_DIR", proj / "does_not_exist")
        assert bri.build_strategy_lookup() == {}


# ──────────────────────────────────────────────────────────────────────────────
# load_llm_verdicts
# ──────────────────────────────────────────────────────────────────────────────
class TestLoadLlmVerdicts:

    def _verdict(self, run_id="run1"):
        return {
            "run_id": run_id,
            "strategies": [{
                "strategy": "Alpha Strategy",
                "portfolio": "Nasdaq 100",
                "beats_spy": True,
                "curve_smoothness": {
                    "smooth_verdict": "SMOOTH",
                    "longest_flat_streak_months": 4,
                    "smoothness_r2": 0.93,
                },
            }],
        }

    def test_fields_are_extracted(self, proj):
        _write_run(proj, "run1", [{"Strategy": "Alpha Strategy"}], self._verdict())
        v = bri.load_llm_verdicts()
        entry = v[("run1", "Alpha Strategy", "Nasdaq 100")]
        assert entry["llm_beats_spy"] is True
        assert entry["llm_smooth_verdict"] == "SMOOTH"
        assert entry["llm_longest_flat_months"] == 4
        assert entry["llm_smoothness_r2"] == 0.93

    def test_indexed_under_both_full_and_fallback_keys(self, proj):
        _write_run(proj, "run1", [{"Strategy": "Alpha Strategy"}], self._verdict())
        v = bri.load_llm_verdicts()
        assert ("run1", "Alpha Strategy", "Nasdaq 100") in v
        assert ("run1", "Alpha Strategy") in v

    def test_missing_curve_smoothness_does_not_crash(self, proj):
        payload = {"run_id": "run1", "strategies": [
            {"strategy": "Alpha Strategy", "portfolio": "P", "beats_spy": False}
        ]}
        _write_run(proj, "run1", [{"Strategy": "Alpha Strategy"}], payload)
        entry = bri.load_llm_verdicts()[("run1", "Alpha Strategy")]
        assert entry["llm_beats_spy"] is False
        assert entry["llm_smooth_verdict"] is None

    def test_run_id_falls_back_to_directory_name(self, proj):
        payload = {"strategies": [{"strategy": "Alpha Strategy", "portfolio": "P"}]}
        _write_run(proj, "dir-named-run", [{"Strategy": "Alpha Strategy"}], payload)
        assert ("dir-named-run", "Alpha Strategy") in bri.load_llm_verdicts()

    def test_malformed_json_is_skipped_and_others_still_load(self, proj):
        _write_run(proj, "good", [{"Strategy": "Alpha Strategy"}], self._verdict("good"))
        bad_dir = proj / "output" / "runs" / "bad"
        bad_dir.mkdir(parents=True)
        (bad_dir / "llm_verdict.json").write_text("{not json", encoding="utf-8")
        v = bri.load_llm_verdicts()
        assert ("good", "Alpha Strategy") in v

    def test_no_verdict_files_yields_empty(self, proj):
        assert bri.load_llm_verdicts() == {}


# ──────────────────────────────────────────────────────────────────────────────
# _normalise_row
# ──────────────────────────────────────────────────────────────────────────────
class TestNormaliseRow:

    def test_known_columns_are_copied(self):
        row = {"Strategy": "S", "Calmar": "1.2"}
        out = bri._normalise_row(row, list(row))
        assert out["Strategy"] == "S"
        assert out["Calmar"] == "1.2"

    def test_unknown_columns_are_dropped(self):
        row = {"Strategy": "S", "Some Retired Column": "x"}
        out = bri._normalise_row(row, list(row))
        assert "Some Retired Column" not in out

    def test_all_output_cols_present_even_when_absent_from_input(self):
        out = bri._normalise_row({"Strategy": "S"}, ["Strategy"])
        assert set(out) == set(bri.OUTPUT_COLS)
        assert out["Sharpe"] == ""

    def test_spaceless_spy_benchmark_alias_is_mapped(self):
        row = {"Strategy": "S", "vs. SPY(B&H)": "+12.0%"}
        out = bri._normalise_row(row, list(row))
        assert out["vs. SPY (B&H)"] == "+12.0%"

    def test_canonical_spy_column_wins_over_alias(self):
        row = {"Strategy": "S", "vs. SPY (B&H)": "+1.0%", "vs. SPY(B&H)": "+9.9%"}
        out = bri._normalise_row(row, list(row))
        assert out["vs. SPY (B&H)"] == "+1.0%"


# ──────────────────────────────────────────────────────────────────────────────
# collect_csv_rows
# ──────────────────────────────────────────────────────────────────────────────
class TestCollectCsvRows:

    def test_collects_across_multiple_runs(self, proj):
        _write_run(proj, "run1", [{"Strategy": "A", "Portfolio": "P"}])
        _write_run(proj, "run2", [{"Strategy": "B", "Portfolio": "P"}])
        assert len(bri.collect_csv_rows()) == 2

    def test_prefix_filter_restricts_runs(self, proj):
        _write_run(proj, "keep-me", [{"Strategy": "A", "Portfolio": "P"}])
        _write_run(proj, "drop-me", [{"Strategy": "B", "Portfolio": "P"}])
        rows = bri.collect_csv_rows(["keep"])
        assert [r["Strategy"] for r in rows] == ["A"]

    def test_prefix_filter_accepts_multiple_prefixes(self, proj):
        _write_run(proj, "aaa", [{"Strategy": "A", "Portfolio": "P"}])
        _write_run(proj, "bbb", [{"Strategy": "B", "Portfolio": "P"}])
        _write_run(proj, "ccc", [{"Strategy": "C", "Portfolio": "P"}])
        rows = bri.collect_csv_rows(["aaa", "ccc"])
        assert sorted(r["Strategy"] for r in rows) == ["A", "C"]

    def test_no_runs_yields_empty_list(self, proj):
        assert bri.collect_csv_rows() == []

    def test_run_id_column_is_used_when_present(self, proj):
        """Real summary CSVs carry run_id as their first column."""
        _write_run(proj, "dir-name", [
            {"run_id": "id-from-column", "Strategy": "A", "Portfolio": "P"}])
        assert bri.collect_csv_rows()[0]["run_id"] == "id-from-column"

    def test_run_id_falls_back_to_directory_name_when_column_absent(self, proj):
        """Without this fallback a CSV lacking the column silently loses every
        enrichment field, since the verdict join is keyed on run_id."""
        _write_run(proj, "dir-name", [{"Strategy": "A", "Portfolio": "P"}])
        assert bri.collect_csv_rows()[0]["run_id"] == "dir-name"


# ──────────────────────────────────────────────────────────────────────────────
# main — end to end
# ──────────────────────────────────────────────────────────────────────────────
class TestMainEndToEnd:

    def _setup(self, proj):
        (proj / "custom_strategies" / "one.py").write_text(STRAT_ONE, encoding="utf-8")
        _write_run(
            proj, "run1",
            [{"Strategy": "Alpha Strategy", "Portfolio": "Nasdaq 100",
              "Calmar": "1.25", "WFA Verdict": "Pass"}],
            {"run_id": "run1", "strategies": [{
                "strategy": "Alpha Strategy", "portfolio": "Nasdaq 100",
                "beats_spy": True,
                "curve_smoothness": {"smooth_verdict": "SMOOTH",
                                     "longest_flat_streak_months": 3,
                                     "smoothness_r2": 0.95},
            }]},
        )

    def _read_output(self, proj):
        with open(proj / "output" / "research_index.csv", newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    def test_writes_csv_with_canonical_header(self, proj, monkeypatch):
        self._setup(proj)
        monkeypatch.setattr(sys, "argv", ["build_research_index.py"])
        bri.main()
        with open(proj / "output" / "research_index.csv", newline="", encoding="utf-8") as fh:
            assert next(csv.reader(fh)) == bri.OUTPUT_COLS

    def test_joins_llm_verdict_onto_the_row(self, proj, monkeypatch):
        self._setup(proj)
        monkeypatch.setattr(sys, "argv", ["build_research_index.py"])
        bri.main()
        row = self._read_output(proj)[0]
        assert row["llm_beats_spy"] == "True"
        assert row["llm_smooth_verdict"] == "SMOOTH"
        assert row["llm_longest_flat_months"] == "3"

    def test_verdict_join_works_when_csv_carries_run_id_column(self, proj, monkeypatch):
        """The shape real runs actually produce — run_id as a CSV column."""
        (proj / "custom_strategies" / "one.py").write_text(STRAT_ONE, encoding="utf-8")
        _write_run(
            proj, "run1",
            [{"run_id": "run1", "Strategy": "Alpha Strategy", "Portfolio": "Nasdaq 100"}],
            {"run_id": "run1", "strategies": [{
                "strategy": "Alpha Strategy", "portfolio": "Nasdaq 100",
                "beats_spy": True,
                "curve_smoothness": {"smooth_verdict": "ACCEPTABLE",
                                     "longest_flat_streak_months": 7,
                                     "smoothness_r2": 0.81},
            }]},
        )
        monkeypatch.setattr(sys, "argv", ["build_research_index.py"])
        bri.main()
        row = self._read_output(proj)[0]
        assert row["llm_smooth_verdict"] == "ACCEPTABLE"
        assert row["code_file"].endswith("one.py")

    def test_verdict_join_falls_back_to_portfolio_agnostic_key(self, proj, monkeypatch):
        """Verdict recorded under a different portfolio label still joins via
        the (run_id, strategy) fallback key."""
        _write_run(
            proj, "run1",
            [{"run_id": "run1", "Strategy": "Alpha Strategy", "Portfolio": "Renamed"}],
            {"run_id": "run1", "strategies": [{
                "strategy": "Alpha Strategy", "portfolio": "Original",
                "beats_spy": True,
                "curve_smoothness": {"smooth_verdict": "ROUGH",
                                     "longest_flat_streak_months": 19,
                                     "smoothness_r2": 0.42},
            }]},
        )
        monkeypatch.setattr(sys, "argv", ["build_research_index.py"])
        bri.main()
        assert self._read_output(proj)[0]["llm_smooth_verdict"] == "ROUGH"

    def test_joins_code_file_and_param_count_onto_the_row(self, proj, monkeypatch):
        self._setup(proj)
        monkeypatch.setattr(sys, "argv", ["build_research_index.py"])
        bri.main()
        row = self._read_output(proj)[0]
        assert row["code_file"].endswith("one.py")
        assert row["param_count"] == "2"

    def test_preserves_summary_columns(self, proj, monkeypatch):
        self._setup(proj)
        monkeypatch.setattr(sys, "argv", ["build_research_index.py"])
        bri.main()
        row = self._read_output(proj)[0]
        assert row["Calmar"] == "1.25"
        assert row["WFA Verdict"] == "Pass"

    def test_unmatched_strategy_leaves_enrichment_blank(self, proj, monkeypatch):
        _write_run(proj, "run1", [{"Strategy": "Unknown Strategy", "Portfolio": "P"}])
        monkeypatch.setattr(sys, "argv", ["build_research_index.py"])
        bri.main()
        row = self._read_output(proj)[0]
        assert row["code_file"] == ""
        assert row["param_count"] == ""
        assert row["llm_smooth_verdict"] == ""
        assert row["Strategy"] == "Unknown Strategy"   # row still written

    def test_runs_only_flag_filters_output(self, proj, monkeypatch):
        self._setup(proj)
        _write_run(proj, "other", [{"Strategy": "Alpha Strategy", "Portfolio": "P"}])
        monkeypatch.setattr(sys, "argv", ["build_research_index.py", "--runs-only", "run1"])
        bri.main()
        assert len(self._read_output(proj)) == 1

    def test_creates_output_directory_when_absent(self, proj, monkeypatch):
        self._setup(proj)
        target = proj / "fresh" / "research_index.csv"
        monkeypatch.setattr(bri, "OUTPUT_PATH", target)
        monkeypatch.setattr(sys, "argv", ["build_research_index.py"])
        bri.main()
        assert target.exists()

    def test_empty_project_still_writes_header_only_csv(self, proj, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["build_research_index.py"])
        bri.main()
        assert self._read_output(proj) == []
        assert (proj / "output" / "research_index.csv").exists()
