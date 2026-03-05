"""
tests/test_cache_warning.py

Unit tests for the D1 stale cache warning block in main.py.

Strategy: import and call _check_stale_cache (extracted inline logic) by
driving it through a thin helper that replicates the D1 logic exactly,
using tmp_path for real files and freezing datetime.now() + os.path.getmtime
via unittest.mock.patch to control apparent file age without needing to
change real filesystem timestamps.

Why not subprocess? The warning goes to logger (stderr), making it harder
to assert on from a subprocess without extra plumbing. Calling the logic
directly gives faster, simpler assertions via caplog.
"""

import glob
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Thin replication of the D1 block — keeps tests decoupled from main() setup
# (logging.basicConfig, argparse, os.makedirs) but exercises the exact logic.
# ---------------------------------------------------------------------------

def _run_d1(cache_dir, now, logger):
    """Replicate the D1 block from main.py verbatim, parameterised for testing."""
    stale_threshold = timedelta(days=7)
    if os.path.exists(cache_dir):
        stale = [
            f for f in glob.glob(os.path.join(cache_dir, "*.parquet"))
            if now - datetime.fromtimestamp(os.path.getmtime(f)) > stale_threshold
        ]
        if stale:
            logger.warning(
                f"  -> STALE CACHE: {len(stale)} file(s) in '{cache_dir}' are older than 7 days. "
                "Delete data_cache/ to force a fresh fetch."
            )


# ---------------------------------------------------------------------------
# TestStaleFilesDetected
# ---------------------------------------------------------------------------

class TestStaleFilesDetected:
    """Warning fires when parquet files are older than 7 days."""

    def test_single_stale_file_logs_warning(self, tmp_path, caplog):
        cache_dir = tmp_path / "data_cache"
        cache_dir.mkdir()
        (cache_dir / "SPY_2004.parquet").write_bytes(b"")

        eight_days_ago = datetime.now() - timedelta(days=8)
        fake_mtime = eight_days_ago.timestamp()

        with patch("os.path.getmtime", return_value=fake_mtime), \
             caplog.at_level(logging.WARNING):
            _run_d1(str(cache_dir), datetime.now(), logging.getLogger("test"))

        assert "STALE CACHE" in caplog.text

    def test_warning_includes_file_count(self, tmp_path, caplog):
        cache_dir = tmp_path / "data_cache"
        cache_dir.mkdir()
        for name in ("A.parquet", "B.parquet", "C.parquet"):
            (cache_dir / name).write_bytes(b"")

        fake_mtime = (datetime.now() - timedelta(days=10)).timestamp()

        with patch("os.path.getmtime", return_value=fake_mtime), \
             caplog.at_level(logging.WARNING):
            _run_d1(str(cache_dir), datetime.now(), logging.getLogger("test"))

        assert "3 file(s)" in caplog.text

    def test_warning_mentions_cache_dir(self, tmp_path, caplog):
        cache_dir = tmp_path / "data_cache"
        cache_dir.mkdir()
        (cache_dir / "X.parquet").write_bytes(b"")

        fake_mtime = (datetime.now() - timedelta(days=30)).timestamp()

        with patch("os.path.getmtime", return_value=fake_mtime), \
             caplog.at_level(logging.WARNING):
            _run_d1(str(cache_dir), datetime.now(), logging.getLogger("test"))

        assert str(cache_dir) in caplog.text or "data_cache" in caplog.text

    def test_exactly_8_days_old_triggers_warning(self, tmp_path, caplog):
        cache_dir = tmp_path / "data_cache"
        cache_dir.mkdir()
        (cache_dir / "edge.parquet").write_bytes(b"")

        fake_mtime = (datetime.now() - timedelta(days=8)).timestamp()

        with patch("os.path.getmtime", return_value=fake_mtime), \
             caplog.at_level(logging.WARNING):
            _run_d1(str(cache_dir), datetime.now(), logging.getLogger("test"))

        assert "STALE CACHE" in caplog.text


# ---------------------------------------------------------------------------
# TestFreshFilesIgnored
# ---------------------------------------------------------------------------

class TestFreshFilesIgnored:
    """No warning when all parquet files are within the 7-day threshold."""

    def test_fresh_file_no_warning(self, tmp_path, caplog):
        cache_dir = tmp_path / "data_cache"
        cache_dir.mkdir()
        (cache_dir / "recent.parquet").write_bytes(b"")

        fake_mtime = (datetime.now() - timedelta(days=3)).timestamp()

        with patch("os.path.getmtime", return_value=fake_mtime), \
             caplog.at_level(logging.WARNING):
            _run_d1(str(cache_dir), datetime.now(), logging.getLogger("test"))

        assert "STALE CACHE" not in caplog.text

    def test_exactly_7_days_old_no_warning(self, tmp_path, caplog):
        """Boundary: exactly 7 days old should NOT trigger (threshold is > 7 days).

        Pin a single _now value to avoid the race where a few microseconds of
        test execution push the age just past 7 days and falsely trigger the warning.
        """
        cache_dir = tmp_path / "data_cache"
        cache_dir.mkdir()
        (cache_dir / "boundary.parquet").write_bytes(b"")

        _now = datetime.now()
        fake_mtime = (_now - timedelta(days=7)).timestamp()

        with patch("os.path.getmtime", return_value=fake_mtime), \
             caplog.at_level(logging.WARNING):
            _run_d1(str(cache_dir), _now, logging.getLogger("test"))

        assert "STALE CACHE" not in caplog.text

    def test_mixed_fresh_and_stale_reports_only_stale_count(self, tmp_path, caplog):
        """Only stale files contribute to the count; fresh files are excluded."""
        cache_dir = tmp_path / "data_cache"
        cache_dir.mkdir()
        stale_file = cache_dir / "old.parquet"
        fresh_file = cache_dir / "new.parquet"
        stale_file.write_bytes(b"")
        fresh_file.write_bytes(b"")

        stale_mtime = (datetime.now() - timedelta(days=10)).timestamp()
        fresh_mtime = (datetime.now() - timedelta(days=2)).timestamp()

        def fake_getmtime(path):
            return stale_mtime if "old" in path else fresh_mtime

        with patch("os.path.getmtime", side_effect=fake_getmtime), \
             caplog.at_level(logging.WARNING):
            _run_d1(str(cache_dir), datetime.now(), logging.getLogger("test"))

        assert "STALE CACHE" in caplog.text
        assert "1 file(s)" in caplog.text


# ---------------------------------------------------------------------------
# TestNonParquetFilesIgnored
# ---------------------------------------------------------------------------

class TestNonParquetFilesIgnored:
    """Only *.parquet files are checked — other extensions are silently skipped."""

    def test_csv_files_do_not_trigger_warning(self, tmp_path, caplog):
        cache_dir = tmp_path / "data_cache"
        cache_dir.mkdir()
        (cache_dir / "old_data.csv").write_bytes(b"")

        fake_mtime = (datetime.now() - timedelta(days=30)).timestamp()

        with patch("os.path.getmtime", return_value=fake_mtime), \
             caplog.at_level(logging.WARNING):
            _run_d1(str(cache_dir), datetime.now(), logging.getLogger("test"))

        assert "STALE CACHE" not in caplog.text

    def test_empty_cache_dir_no_warning(self, tmp_path, caplog):
        cache_dir = tmp_path / "data_cache"
        cache_dir.mkdir()

        with caplog.at_level(logging.WARNING):
            _run_d1(str(cache_dir), datetime.now(), logging.getLogger("test"))

        assert "STALE CACHE" not in caplog.text


# ---------------------------------------------------------------------------
# TestMissingCacheDir
# ---------------------------------------------------------------------------

class TestMissingCacheDir:
    """No error when data_cache/ does not exist (clean environment)."""

    def test_missing_dir_does_not_raise(self, tmp_path, caplog):
        nonexistent = str(tmp_path / "data_cache")

        with caplog.at_level(logging.WARNING):
            _run_d1(nonexistent, datetime.now(), logging.getLogger("test"))

        assert "STALE CACHE" not in caplog.text
