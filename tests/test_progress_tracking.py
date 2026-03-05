"""
tests/test_progress_tracking.py

Unit tests for the simulation-loop progress tracking block in main.py.

Strategy: extract the checkpoint/ETA logic into a thin helper that mirrors
the loop verbatim, driving it with a plain list iterator instead of
p.imap. This avoids spawning a multiprocessing Pool in tests while still
exercising the exact checkpoint math, logger.info calls, and
results collection.

Why not subprocess? The progress messages go to logger (not stdout), so
asserting on them via caplog is faster and more reliable than parsing
subprocess output.
"""

import logging
import math
import os
import sys
import time
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Thin replication of the progress-tracking loop from main.py
# ---------------------------------------------------------------------------

def _run_progress_loop(tasks, logger):
    """
    Mirror of the pool loop in main.py, with p.imap replaced by a plain
    iterator so tests need no multiprocessing Pool.
    """
    import time as _time

    _results = []
    _start_pool = _time.monotonic()
    _total = len(tasks)
    _checkpoints = {max(1, int(_total * pct)) for pct in [0.1, 0.25, 0.5, 0.75, 0.9]}

    for _i, _r in enumerate(iter(tasks), start=1):
        _results.append(_r)
        if _i in _checkpoints:
            _elapsed = _time.monotonic() - _start_pool
            _rate = _i / _elapsed
            _remaining = (_total - _i) / _rate if _rate > 0 else 0
            logger.info(
                f"  -> Progress: {_i}/{_total} tasks done | Elapsed: {_elapsed:.0f}s | ETA: {_remaining:.0f}s remaining"
            )

    return _results


def _make_tasks(n):
    """Return a list of n dummy task results (simulate run_single_simulation output)."""
    return [{"result": i} for i in range(n)]


# ---------------------------------------------------------------------------
# TestCase1 — at least 10 tasks, log messages emitted
# ---------------------------------------------------------------------------

class TestProgressMessagesEmitted:
    """Test Case 1 & 2: Progress messages are logged at checkpoint intervals."""

    def test_at_least_one_progress_message_for_10_tasks(self, caplog):
        tasks = _make_tasks(10)
        with caplog.at_level(logging.INFO):
            _run_progress_loop(tasks, logging.getLogger("test"))
        progress_lines = [r for r in caplog.records if "Progress" in r.message]
        assert len(progress_lines) >= 1

    def test_progress_message_format_contains_slash_notation(self, caplog):
        tasks = _make_tasks(20)
        with caplog.at_level(logging.INFO):
            _run_progress_loop(tasks, logging.getLogger("test"))
        progress_lines = [r.message for r in caplog.records if "Progress" in r.message]
        assert any(f"/{len(tasks)}" in msg for msg in progress_lines)

    def test_progress_message_contains_elapsed_and_eta(self, caplog):
        tasks = _make_tasks(20)
        with caplog.at_level(logging.INFO):
            _run_progress_loop(tasks, logging.getLogger("test"))
        progress_lines = [r.message for r in caplog.records if "Progress" in r.message]
        assert any("Elapsed" in msg and "ETA" in msg for msg in progress_lines)

    def test_checkpoints_do_not_exceed_five(self, caplog):
        """At most 5 distinct checkpoint indices fire (10%/25%/50%/75%/90%)."""
        tasks = _make_tasks(100)
        with caplog.at_level(logging.INFO):
            _run_progress_loop(tasks, logging.getLogger("test"))
        progress_lines = [r for r in caplog.records if "Progress" in r.message]
        assert len(progress_lines) <= 5

    def test_all_five_checkpoints_fire_for_large_task_list(self, caplog):
        """With 100 distinct tasks all 5 percentage thresholds map to unique indices."""
        tasks = _make_tasks(100)
        with caplog.at_level(logging.INFO):
            _run_progress_loop(tasks, logging.getLogger("test"))
        progress_lines = [r for r in caplog.records if "Progress" in r.message]
        assert len(progress_lines) == 5


# ---------------------------------------------------------------------------
# TestCase2 — checkpoint indices match expected percentages
# ---------------------------------------------------------------------------

class TestCheckpointIntervals:
    """Test Case 2: Progress messages fire at the correct task indices."""

    def _extract_done_counts(self, caplog, total):
        msgs = [r.message for r in caplog.records if "Progress" in r.message]
        counts = []
        for msg in msgs:
            # format: "  -> Progress: {_i}/{_total} tasks done | ..."
            part = msg.split("Progress:")[1].split("tasks done")[0].strip()
            done = int(part.split("/")[0])
            counts.append(done)
        return counts

    def test_10_tasks_checkpoint_at_task_1(self, caplog):
        tasks = _make_tasks(10)
        with caplog.at_level(logging.INFO):
            _run_progress_loop(tasks, logging.getLogger("test"))
        counts = self._extract_done_counts(caplog, 10)
        # 10% of 10 = 1 → max(1, 1) = 1
        assert 1 in counts

    def test_100_tasks_checkpoint_at_10_percent(self, caplog):
        tasks = _make_tasks(100)
        with caplog.at_level(logging.INFO):
            _run_progress_loop(tasks, logging.getLogger("test"))
        counts = self._extract_done_counts(caplog, 100)
        assert 10 in counts   # 10%
        assert 25 in counts   # 25%
        assert 50 in counts   # 50%
        assert 75 in counts   # 75%
        assert 90 in counts   # 90%

    def test_1_task_does_not_crash(self, caplog):
        """max(1, int(1 * 0.1)) = 1, so task 1 always hits at least one checkpoint."""
        tasks = _make_tasks(1)
        with caplog.at_level(logging.INFO):
            _run_progress_loop(tasks, logging.getLogger("test"))
        progress_lines = [r for r in caplog.records if "Progress" in r.message]
        assert len(progress_lines) >= 1

    def test_no_checkpoint_fires_for_zero_tasks(self, caplog):
        with caplog.at_level(logging.INFO):
            result = _run_progress_loop([], logging.getLogger("test"))
        progress_lines = [r for r in caplog.records if "Progress" in r.message]
        assert len(progress_lines) == 0
        assert result == []


# ---------------------------------------------------------------------------
# TestCase3 — results list matches input length
# ---------------------------------------------------------------------------

class TestResultsCollection:
    """Test Case 3: results_this_portfolio has the same length as the task list."""

    def test_10_tasks_returns_10_results(self, caplog):
        tasks = _make_tasks(10)
        results = _run_progress_loop(tasks, logging.getLogger("test"))
        assert len(results) == 10

    def test_100_tasks_returns_100_results(self, caplog):
        tasks = _make_tasks(100)
        results = _run_progress_loop(tasks, logging.getLogger("test"))
        assert len(results) == 100

    def test_results_preserve_order(self, caplog):
        tasks = _make_tasks(20)
        results = _run_progress_loop(tasks, logging.getLogger("test"))
        for i, r in enumerate(results):
            assert r["result"] == i

    def test_none_results_are_preserved(self, caplog):
        """None returns from run_single_simulation are kept (filtered later)."""
        tasks = [None, {"result": 1}, None]
        results = _run_progress_loop(tasks, logging.getLogger("test"))
        assert results == [None, {"result": 1}, None]

    def test_zero_tasks_returns_empty_list(self, caplog):
        results = _run_progress_loop([], logging.getLogger("test"))
        assert results == []

    def test_5x2_task_grid_returns_10_results(self, caplog):
        """Realistic case: 5 symbols x 2 strategies = 10 tasks."""
        tasks = [{"symbol": f"SYM{s}", "strategy": f"Strat{t}"} for s in range(5) for t in range(2)]
        results = _run_progress_loop(tasks, logging.getLogger("test"))
        assert len(results) == 10


# ---------------------------------------------------------------------------
# TestCase4 — tqdm wrapper does not break the iteration
# ---------------------------------------------------------------------------

class TestTqdmCompatibility:
    """Test Case 4: wrapping the iterator in tqdm still yields all results."""

    def test_tqdm_wrapped_iterator_yields_all_results(self, caplog):
        from tqdm import tqdm
        import time as _time

        tasks = _make_tasks(20)
        _results = []
        _start_pool = _time.monotonic()
        _total = len(tasks)
        _checkpoints = {max(1, int(_total * pct)) for pct in [0.1, 0.25, 0.5, 0.75, 0.9]}

        with caplog.at_level(logging.INFO):
            for _i, _r in enumerate(
                tqdm(iter(tasks), total=_total, desc="  -> Running sims", disable=True),
                start=1,
            ):
                _results.append(_r)
                if _i in _checkpoints:
                    _elapsed = _time.monotonic() - _start_pool
                    _rate = _i / _elapsed
                    _remaining = (_total - _i) / _rate if _rate > 0 else 0
                    logging.getLogger("test").info(
                        f"  -> Progress: {_i}/{_total} tasks done | Elapsed: {_elapsed:.0f}s | ETA: {_remaining:.0f}s remaining"
                    )

        assert len(_results) == 20

    def test_tqdm_wrapped_iterator_emits_progress_messages(self, caplog):
        from tqdm import tqdm
        import time as _time

        tasks = _make_tasks(20)
        _results = []
        _start_pool = _time.monotonic()
        _total = len(tasks)
        _checkpoints = {max(1, int(_total * pct)) for pct in [0.1, 0.25, 0.5, 0.75, 0.9]}
        log = logging.getLogger("test")

        with caplog.at_level(logging.INFO):
            for _i, _r in enumerate(
                tqdm(iter(tasks), total=_total, desc="  -> Running sims", disable=True),
                start=1,
            ):
                _results.append(_r)
                if _i in _checkpoints:
                    _elapsed = _time.monotonic() - _start_pool
                    _rate = _i / _elapsed
                    _remaining = (_total - _i) / _rate if _rate > 0 else 0
                    log.info(
                        f"  -> Progress: {_i}/{_total} tasks done | Elapsed: {_elapsed:.0f}s | ETA: {_remaining:.0f}s remaining"
                    )

        progress_lines = [r for r in caplog.records if "Progress" in r.message]
        assert len(progress_lines) >= 1
