"""Unit tests for scripts/check_gold_verdict.py — gold-track 3-gate scorer.

Covers:
- Each individual gate (G1 beats SPY, G2 smooth verdict, G3 WFA Pass)
- Combined pass/fail paths
- ACCEPTABLE smooth verdict treated as pass (per gold-track spec)
- Exit codes (0 on any pass, 1 on all fail, 2 on missing file)
- Plateau length and MC Score are NOT gated (printed only)
- Empty strategies list treated as FAIL
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCORER = PROJECT_ROOT / "scripts" / "check_gold_verdict.py"
PYTHON = sys.executable


def _run_scorer(run_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, str(SCORER), str(run_dir)],
        capture_output=True,
        text=True,
        check=False,
    )


def _write_verdict(run_dir: Path, strategies: list[dict], *, summary=None, run_id="test") -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    body = {
        "run_id": run_id,
        "period": {"start": "2005-01-01", "end": "2026-04-22"},
        "benchmarks": {"SPY": 250.0},
        "strategies": strategies,
        "summary": summary or {
            "beats_spy_count": sum(1 for s in strategies if s.get("beats_spy")),
            "total_strategies_with_trades": len(strategies),
        },
    }
    (run_dir / "llm_verdict.json").write_text(json.dumps(body))


def _strategy(
    *,
    name="Test Strategy",
    portfolio="SPY+GLD",
    beats_spy=True,
    smooth_verdict="SMOOTH",
    wfa_verdict="Pass",
    longest_flat_streak_months=8,
    mc_score=4,
    strategy_return_pct=300.0,
) -> dict:
    return {
        "strategy": name,
        "portfolio": portfolio,
        "strategy_return_pct": strategy_return_pct,
        "beats_spy": beats_spy,
        "verdict": "beats SPY by 50pp" if beats_spy else "lags SPY by 50pp",
        "curve_smoothness": {
            "smooth_verdict": smooth_verdict,
            "longest_flat_streak_months": longest_flat_streak_months,
            "smooth_notes": [] if smooth_verdict in ("SMOOTH", "ACCEPTABLE") else ["upthrust"],
        },
        "calmar_ratio": 0.5,
        "mc_score": mc_score,
        "wfa_verdict": wfa_verdict,
    }


# ---------------------------------------------------------------------------
# Exit codes and infrastructure
# ---------------------------------------------------------------------------

class TestExitCodes:
    def test_missing_run_dir_returns_2(self, tmp_path):
        result = _run_scorer(tmp_path / "does_not_exist")
        assert result.returncode == 2
        assert "not found" in result.stdout

    def test_no_args_returns_2(self):
        result = subprocess.run(
            [PYTHON, str(SCORER)], capture_output=True, text=True, check=False
        )
        assert result.returncode == 2
        assert "Usage" in result.stdout

    def test_empty_strategies_list_returns_1(self, tmp_path):
        _write_verdict(tmp_path, [])
        result = _run_scorer(tmp_path)
        assert result.returncode == 1
        assert "No strategies" in result.stdout


# ---------------------------------------------------------------------------
# Individual gates
# ---------------------------------------------------------------------------

class TestGateG1BeatsSpy:
    def test_lags_spy_fails(self, tmp_path):
        _write_verdict(tmp_path, [_strategy(beats_spy=False)])
        result = _run_scorer(tmp_path)
        assert result.returncode == 1
        assert "lags SPY" in result.stdout
        assert "GATE: FAIL" in result.stdout

    def test_beats_spy_alone_isnt_enough(self, tmp_path):
        """Beating SPY but rough curve still fails."""
        _write_verdict(
            tmp_path,
            [_strategy(beats_spy=True, smooth_verdict="ROUGH")],
        )
        result = _run_scorer(tmp_path)
        assert result.returncode == 1


class TestGateG2SmoothVerdict:
    def test_rough_fails(self, tmp_path):
        _write_verdict(tmp_path, [_strategy(smooth_verdict="ROUGH")])
        result = _run_scorer(tmp_path)
        assert result.returncode == 1
        assert "smooth_verdict=ROUGH" in result.stdout

    def test_smooth_passes_g2(self, tmp_path):
        _write_verdict(tmp_path, [_strategy(smooth_verdict="SMOOTH")])
        result = _run_scorer(tmp_path)
        assert result.returncode == 0

    def test_acceptable_passes_g2(self, tmp_path):
        """ACCEPTABLE must pass per gold-track spec (matters — many runs land here)."""
        _write_verdict(tmp_path, [_strategy(smooth_verdict="ACCEPTABLE")])
        result = _run_scorer(tmp_path)
        assert result.returncode == 0
        assert "GATE: PASS" in result.stdout

    def test_unknown_verdict_fails(self, tmp_path):
        _write_verdict(tmp_path, [_strategy(smooth_verdict="UNKNOWN")])
        result = _run_scorer(tmp_path)
        assert result.returncode == 1


class TestGateG3WfaPass:
    def test_likely_overfitted_fails(self, tmp_path):
        _write_verdict(tmp_path, [_strategy(wfa_verdict="Likely Overfitted")])
        result = _run_scorer(tmp_path)
        assert result.returncode == 1
        assert "WFA = Likely Overfitted" in result.stdout

    def test_pass_passes_g3(self, tmp_path):
        _write_verdict(tmp_path, [_strategy(wfa_verdict="Pass")])
        result = _run_scorer(tmp_path)
        assert result.returncode == 0


class TestUngatedMetricsPrinted:
    """Plateau and MC are ungated but must still appear in output for the
    human reviewer to spot borderline cases."""

    def test_long_plateau_doesnt_block_pass(self, tmp_path):
        """22-month plateau (impossible for EC) is fine for gold track."""
        _write_verdict(
            tmp_path,
            [_strategy(longest_flat_streak_months=22)],
        )
        result = _run_scorer(tmp_path)
        assert result.returncode == 0
        assert "flat=22m" in result.stdout

    def test_low_mc_score_doesnt_block_pass(self, tmp_path):
        """MC=2 would fail EC R4 but passes gold track."""
        _write_verdict(tmp_path, [_strategy(mc_score=2)])
        result = _run_scorer(tmp_path)
        assert result.returncode == 0
        assert "MC=2" in result.stdout


# ---------------------------------------------------------------------------
# Multi-strategy runs
# ---------------------------------------------------------------------------

class TestMultiStrategy:
    def test_any_passing_strategy_returns_0(self, tmp_path):
        """Mixed run: one pass + two fail → exit 0 (rule: ANY strategy passes)."""
        _write_verdict(
            tmp_path,
            [
                _strategy(name="A", smooth_verdict="ROUGH"),
                _strategy(name="B"),  # passing
                _strategy(name="C", beats_spy=False),
            ],
        )
        result = _run_scorer(tmp_path)
        assert result.returncode == 0
        assert "GATE: PASS" in result.stdout
        assert "[PASS]  B" in result.stdout
        assert "[FAIL]  A" in result.stdout
        assert "[FAIL]  C" in result.stdout

    def test_all_fail_returns_1(self, tmp_path):
        _write_verdict(
            tmp_path,
            [
                _strategy(name="A", smooth_verdict="ROUGH"),
                _strategy(name="B", wfa_verdict="Likely Overfitted"),
            ],
        )
        result = _run_scorer(tmp_path)
        assert result.returncode == 1
        assert "GATE: FAIL" in result.stdout
