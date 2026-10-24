"""tests/test_data_quality_cast_census.py

Pins the corpus-independent parts of scripts/data_quality_cast_census.py (#389):
the un-cast variant is built from the *current* helpers/data_quality.py, it
differs only by the two casts, and the scoring/reporting arithmetic is right on
frames whose answer is known. The census counts themselves depend on the
corpus and are not tested here.
"""

import importlib.util
import os

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPEC = importlib.util.spec_from_file_location(
    "data_quality_cast_census",
    os.path.join(ROOT, "scripts", "data_quality_cast_census.py"))
census = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(census)

MODULE = census.DEFAULT_MODULE


def _frame(n=2000, zero_vol=0):
    idx = pd.bdate_range("2000-01-03", periods=n)
    px = 100 + np.arange(n) * 0.01
    df = pd.DataFrame({"Open": px, "High": px + 1, "Low": px - 1,
                       "Close": px, "Volume": 1e6}, index=idx)
    if zero_vol:
        df.iloc[:zero_vol, 4] = 0
    return df


class TestVariantConstruction:
    def test_substitutions_still_match_the_committed_module(self):
        # Fails loudly (SystemExit) the day data_quality.py's casts change --
        # which is when this script must be updated or retired.
        committed, un_cast, cap = census.build_variant_sources(MODULE, None)
        assert committed == MODULE.read_text(encoding="utf-8")
        assert cap == census.committed_check6_cap(committed)
        assert census.CAST_CHECK5[0] not in un_cast
        assert census.CAST_CHECK6[0].format(cap=cap) not in un_cast

    def test_variant_differs_only_by_the_two_casts(self):
        committed, un_cast, _ = census.build_variant_sources(MODULE, None)
        diff = [(a, b) for a, b in zip(committed.splitlines(),
                                       un_cast.splitlines()) if a != b]
        assert len(committed.splitlines()) == len(un_cast.splitlines())
        assert len(diff) == 2
        assert all("int(" in a and "int(" not in b for a, b in diff)

    def test_cap_override_rewrites_both_copies(self):
        committed, un_cast, cap = census.build_variant_sources(MODULE, 37)
        assert cap == 37
        assert census.committed_check6_cap(committed) == 37
        assert census.CAST_CHECK6[1].format(cap=37) in un_cast

    def test_missing_target_is_fatal(self):
        with pytest.raises(SystemExit):
            census._sub_once("nothing here", "int(pct)", "pct", "x")

    def test_negative_cap_rejected(self, tmp_path):
        with pytest.raises(SystemExit):
            census.main(["--cap", "-5", "--corpus", str(tmp_path)])


class TestScoring:
    @pytest.fixture(autouse=True)
    def _mods(self):
        census._init_worker(str(MODULE), None)
        yield
        census._MODS.clear()

    def test_zero_volume_fraction_is_charged_un_cast(self, tmp_path):
        # 70 / 2000 = 3.5% zero-volume bars: int() charges 3, un-cast 3.5.
        p = tmp_path / "ZV.parquet"
        _frame(zero_vol=70).to_parquet(p)
        row = census._score_one(str(p))
        assert row["score_int"] - row["score_float"] == pytest.approx(0.5)

    def test_clean_series_does_not_move(self, tmp_path):
        p = tmp_path / "CLEAN.parquet"
        _frame().to_parquet(p)
        row = census._score_one(str(p))
        assert row["score_int"] == row["score_float"]

    def test_corrupt_file_is_a_row_not_a_crash(self, tmp_path):
        p = tmp_path / "BAD.parquet"
        p.write_bytes(b"not parquet")
        row = census._score_one(str(p))
        assert set(row) == {"symbol", "error"}


class TestReporting:
    ROWS = [
        {"symbol": "A", "bars": 2000, "score_int": 80.0, "score_float": 79.9},
        {"symbol": "B", "bars": 2000, "score_int": 80.0, "score_float": 80.0},
        {"symbol": "C", "bars": 100, "score_int": 80.4, "score_float": 79.95},
        {"symbol": "D", "bars": 2000, "score_int": 70.0, "score_float": 70.0},
        {"symbol": "E", "error": "OSError: x"},
    ]

    def test_gate_delta_splits_at_gate_from_above(self):
        scored = [r for r in self.ROWS if "error" not in r]
        assert census.gate_delta(scored, 80.0) == (1, 3, 1, 1)

    def test_summarise_counts(self):
        out = census.summarise(self.ROWS, 80.0, 20)
        assert "Series scored        : 4   (1 unreadable)" in out
        assert "demoted below the gate un-cast   : 1" in out
        assert "At 80 the delta splits 1 + 1" in out

    def test_json_rounding_is_writer_only(self):
        r = census._round_row({"symbol": "X", "score_float": 79.99999999})
        assert r["score_float"] == 80.0


@pytest.mark.parametrize("flag,value", [
    ("--workers", "0"), ("--workers", "-1"), ("--limit", "0"),
    ("--limit", "-1"), ("--threshold", "nan"), ("--threshold", "inf"),
])
def test_invalid_cli_values_are_rejected(flag, value, tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        census.main([flag, value, "--corpus", str(tmp_path)])
    assert exc.value.code == 2
    assert flag in capsys.readouterr().err


def test_cli_spawn_workers_agree_on_a_known_corpus(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _frame().to_parquet(corpus_dir / "CLEAN.parquet")
    _frame(zero_vol=70).to_parquet(corpus_dir / "ZERO.parquet")
    (corpus_dir / "CORRUPT.parquet").write_bytes(b"not parquet")
    results = []
    for workers in (1, 2):
        artifact = tmp_path / f"census-{workers}.json"
        result = subprocess.run(
            [sys.executable, str(Path(ROOT) / "scripts" / "data_quality_cast_census.py"),
             "--corpus", str(corpus_dir), "--workers", str(workers), "--json-out", str(artifact)],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Series scored        : 2   (1 unreadable)" in result.stdout
        results.append(json.loads(artifact.read_text(encoding="utf-8")))
    assert results[0] == results[1]
    rows = {r["symbol"]: r for r in results[0]["rows"]}
    assert rows["CLEAN"]["score_int"] == rows["CLEAN"]["score_float"]
    assert rows["ZERO"]["score_int"] - rows["ZERO"]["score_float"] == .5
    assert "error" in rows["CORRUPT"]


@pytest.mark.parametrize("bad_code", [
    "raise RuntimeError('broken initialization')",
    "import census_dependency_that_does_not_exist",
    "this is not valid python !!!",
    "import multiprocessing as _mp\nif _mp.current_process().name != 'MainProcess':\n    raise RuntimeError('worker-only initialization failure')",
])
def test_module_initialization_failure_exits_without_worker_respawn_loop(tmp_path, bad_code):
    import subprocess
    import sys
    from pathlib import Path

    module = tmp_path / "broken_quality.py"
    module.write_text(MODULE.read_text(encoding="utf-8") + "\n" + bad_code + "\n", encoding="utf-8")
    corpus_dir = tmp_path / "corpus"
    corpus_dir.mkdir()
    _frame().to_parquet(corpus_dir / "CLEAN.parquet")
    result = subprocess.run(
        [sys.executable, str(Path(ROOT) / "scripts" / "data_quality_cast_census.py"),
         "--module", str(module), "--corpus", str(corpus_dir), "--workers", "2"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "cannot initialize scoring module" in result.stderr
    assert "SpawnPoolWorker" not in result.stderr
