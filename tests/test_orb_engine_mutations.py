"""
Mutation proofs for the ORB engine's fill mechanics.

A check that has never been made to fail is not known to be a check. For each execution
mechanic the engine claims to model, this file breaks that mechanic in a copy of the source
and asserts the hand-computed suite CATCHES it. A mutation that survives is a hole in the
tests, and this file fails when that happens.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# (id, description, needle, replacement)
MUTATIONS = [
    ("entry_gap",
     "entry stop fills at the theoretical trigger even when the bar gapped through it",
     "fill = max(trig, o) if brk == 1 else min(trig, o)",
     "fill = trig"),
    ("stop_gap",
     "stop exit fills at the theoretical level even when the bar gapped through it",
     "return (min(stop, o) if side == 1 else max(stop, o)), \"stop\"",
     "return stop, \"stop\""),
    ("target_before_stop",
     "target is resolved before the stop when one bar spans both (optimistic path)",
     "            if hit_stop:",
     "            if hit_tgt and False:\n                pass\n            if hit_tgt:\n                return tgt, \"target\"\n            if hit_stop:"),
    ("no_entry_bar_protection",
     "the entry bar is left unprotected -- stop only enforced from the next bar",
     "                            got = manage(i, open_trade, same_bar=True)",
     "                            got = None if True else manage(i, open_trade, same_bar=True)"),
    ("ignore_cutoff",
     "entries are taken after the 11:00 cutoff",
     "if open_trade is None and m <= cutoff and i != last_exit_bar:",
     "if open_trade is None and i != last_exit_bar:"),
    ("no_slippage",
     "slippage is dropped from every fill",
     "    slip = costs.slip()",
     "    slip = 0.0"),
    ("no_commission",
     "commission is dropped from net P&L",
     "    net_usd = gross_usd - costs.commission_rt",
     "    net_usd = gross_usd"),
    ("same_bar_reentry",
     "a new position is opened on the very bar the previous one closed on",
     "if open_trade is None and m <= cutoff and i != last_exit_bar:",
     "if open_trade is None and m <= cutoff:"),
    ("or_length_ignored",
     "the opening range is hardcoded to 15 minutes, ignoring or_minutes",
     "    or_end_minutes = 9 * 60 + 30 + params.or_minutes",
     "    or_end_minutes = 9 * 60 + 45"),
    ("fade_ignored",
     "the fade flag is ignored, so the placebo silently re-runs the real strategy",
     "            side = -brk if params.fade else brk",
     "            side = brk"),
    ("stop_side_flipped",
     "the initial stop is placed on the wrong side of the opening range",
     "            stop = or_low if side == 1 else or_high",
     "            stop = or_high if side == 1 else or_low"),
]


def _run_suite(workdir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_orb_engine.py", "-q", "-p", "no:warnings"],
        cwd=workdir, capture_output=True, text=True, timeout=300,
    )


@pytest.fixture(scope="module")
def baseline_green() -> None:
    """The unmutated suite must be green, or every mutation result is meaningless."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(
            "es_minute_cache", "output", "__pycache__", ".git", ".pytest_cache"))
        proc = _run_suite(work)
        assert proc.returncode == 0, f"baseline suite is NOT green:\n{proc.stdout[-3000:]}"


@pytest.mark.parametrize("mid,desc,needle,repl", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_mutation_is_caught(baseline_green, mid, desc, needle, repl):
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "work"
        shutil.copytree(ROOT, work, ignore=shutil.ignore_patterns(
            "es_minute_cache", "output", "__pycache__", ".git", ".pytest_cache"))
        target = work / "scripts" / "orb_engine.py"
        src = target.read_text()
        assert needle in src, f"mutation {mid}: needle not found -- mutation list is stale"
        target.write_text(src.replace(needle, repl, 1))

        proc = _run_suite(work)
        assert proc.returncode != 0, (
            f"MUTATION SURVIVED ({mid}): {desc}\n"
            f"No test failed when this mechanic was broken -- the suite does not guard it.\n"
            f"{proc.stdout[-2000:]}"
        )
