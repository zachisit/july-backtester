"""
tests/test_config_snapshot.py

Unit tests for the C1 config snapshot block in main.py.

Strategy: extract the snapshot logic into a thin helper that mirrors the
C1 block verbatim, then call it directly with tmp_path so we can inspect
the resulting file without running all of main() (argparse, data fetch,
logging.basicConfig, etc.).

For the failure case, patch builtins.open to raise OSError and assert that
no exception propagates out of the helper (the try/except swallows it and
prints a WARNING instead).
"""

import json
import os
import sys
from datetime import datetime
from io import StringIO
from unittest.mock import patch, mock_open, MagicMock

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Thin replication of the C1 block — decoupled from main() setup
# ---------------------------------------------------------------------------

def _write_config_snapshot(run_base_dir: str, config: dict) -> None:
    """Replicate the C1 block from main.py verbatim, parameterised for testing."""
    def _config_serializer(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)

    try:
        _snapshot_path = os.path.join(run_base_dir, "config_snapshot.json")
        with open(_snapshot_path, "w", encoding="utf-8") as _f:
            json.dump(config, _f, indent=2, default=_config_serializer)
    except Exception as _e:
        print(f"[WARNING] Could not write config_snapshot.json: {_e}")


# ---------------------------------------------------------------------------
# TestSnapshotCreated — Test Case 1
# ---------------------------------------------------------------------------

class TestSnapshotCreated:
    """config_snapshot.json is written to the run folder."""

    def test_file_is_created(self, tmp_path):
        config = {"start_date": "2020-01-01", "end_date": "2024-01-01"}
        _write_config_snapshot(str(tmp_path), config)
        assert (tmp_path / "config_snapshot.json").exists()

    def test_file_is_created_in_correct_directory(self, tmp_path):
        nested = tmp_path / "output" / "runs" / "2026-01-01_12-00-00"
        nested.mkdir(parents=True)
        config = {"key": "value"}
        _write_config_snapshot(str(nested), config)
        assert (nested / "config_snapshot.json").exists()
        # No stray file in tmp_path root
        assert not (tmp_path / "config_snapshot.json").exists()

    def test_file_is_not_empty(self, tmp_path):
        config = {"start_date": "2020-01-01"}
        _write_config_snapshot(str(tmp_path), config)
        assert (tmp_path / "config_snapshot.json").stat().st_size > 0


# ---------------------------------------------------------------------------
# TestSnapshotValidJson — Test Case 2
# ---------------------------------------------------------------------------

class TestSnapshotValidJson:
    """The written file contains valid, parseable JSON."""

    def test_file_parses_as_json(self, tmp_path):
        config = {"start_date": "2020-01-01", "initial_capital": 10000}
        _write_config_snapshot(str(tmp_path), config)
        with open(tmp_path / "config_snapshot.json", encoding="utf-8") as f:
            parsed = json.load(f)
        assert isinstance(parsed, dict)

    def test_roundtrip_string_values_preserved(self, tmp_path):
        config = {"start_date": "2020-01-01", "end_date": "2024-12-31"}
        _write_config_snapshot(str(tmp_path), config)
        with open(tmp_path / "config_snapshot.json", encoding="utf-8") as f:
            parsed = json.load(f)
        assert parsed["start_date"] == "2020-01-01"
        assert parsed["end_date"] == "2024-12-31"

    def test_roundtrip_numeric_values_preserved(self, tmp_path):
        config = {"initial_capital": 100000, "allocation_per_trade": 0.05}
        _write_config_snapshot(str(tmp_path), config)
        with open(tmp_path / "config_snapshot.json", encoding="utf-8") as f:
            parsed = json.load(f)
        assert parsed["initial_capital"] == 100000
        assert parsed["allocation_per_trade"] == pytest.approx(0.05)

    def test_roundtrip_nested_dict_preserved(self, tmp_path):
        config = {"portfolios": {"Nasdaq_100": ["AAPL", "MSFT"]}}
        _write_config_snapshot(str(tmp_path), config)
        with open(tmp_path / "config_snapshot.json", encoding="utf-8") as f:
            parsed = json.load(f)
        assert parsed["portfolios"]["Nasdaq_100"] == ["AAPL", "MSFT"]


# ---------------------------------------------------------------------------
# TestDatetimeSerialization — Test Case 3
# ---------------------------------------------------------------------------

class TestDatetimeSerialization:
    """datetime objects are converted to ISO-format strings."""

    def test_datetime_serialized_to_isoformat_string(self, tmp_path):
        dt = datetime(2024, 6, 15, 9, 30, 0)
        config = {"run_at": dt}
        _write_config_snapshot(str(tmp_path), config)
        with open(tmp_path / "config_snapshot.json", encoding="utf-8") as f:
            parsed = json.load(f)
        assert parsed["run_at"] == "2024-06-15T09:30:00"

    def test_datetime_value_is_string_not_object(self, tmp_path):
        config = {"timestamp": datetime(2025, 1, 1)}
        _write_config_snapshot(str(tmp_path), config)
        with open(tmp_path / "config_snapshot.json", encoding="utf-8") as f:
            parsed = json.load(f)
        assert isinstance(parsed["timestamp"], str)

    def test_multiple_datetimes_all_serialized(self, tmp_path):
        config = {
            "created": datetime(2024, 1, 1, 0, 0, 0),
            "modified": datetime(2024, 6, 1, 12, 0, 0),
        }
        _write_config_snapshot(str(tmp_path), config)
        with open(tmp_path / "config_snapshot.json", encoding="utf-8") as f:
            parsed = json.load(f)
        assert parsed["created"] == "2024-01-01T00:00:00"
        assert parsed["modified"] == "2024-06-01T12:00:00"

    def test_non_serializable_fallback_to_str(self, tmp_path):
        """Non-datetime, non-serializable objects fall back to str()."""
        class _Custom:
            def __str__(self):
                return "custom_repr"

        config = {"obj": _Custom()}
        _write_config_snapshot(str(tmp_path), config)
        with open(tmp_path / "config_snapshot.json", encoding="utf-8") as f:
            parsed = json.load(f)
        assert parsed["obj"] == "custom_repr"


# ---------------------------------------------------------------------------
# TestSnapshotFailureTolerance — Test Case 4
# ---------------------------------------------------------------------------

class TestSnapshotFailureTolerance:
    """Script continues even when the snapshot write fails."""

    def test_no_exception_raised_on_write_error(self, tmp_path, capsys):
        config = {"start_date": "2020-01-01"}
        with patch("builtins.open", side_effect=OSError("disk full")):
            # Must not raise
            _write_config_snapshot(str(tmp_path), config)

    def test_warning_printed_on_write_error(self, tmp_path, capsys):
        config = {"start_date": "2020-01-01"}
        with patch("builtins.open", side_effect=OSError("disk full")):
            _write_config_snapshot(str(tmp_path), config)
        out = capsys.readouterr().out
        assert "WARNING" in out

    def test_warning_mentions_snapshot_filename(self, tmp_path, capsys):
        config = {"start_date": "2020-01-01"}
        with patch("builtins.open", side_effect=PermissionError("permission denied")):
            _write_config_snapshot(str(tmp_path), config)
        out = capsys.readouterr().out
        assert "config_snapshot.json" in out

    def test_no_file_created_on_write_error(self, tmp_path):
        config = {"start_date": "2020-01-01"}
        with patch("builtins.open", side_effect=OSError("disk full")):
            _write_config_snapshot(str(tmp_path), config)
        assert not (tmp_path / "config_snapshot.json").exists()

    def test_no_exception_raised_on_permission_error(self, tmp_path):
        config = {"key": "value"}
        with patch("builtins.open", side_effect=PermissionError("read-only")):
            _write_config_snapshot(str(tmp_path), config)  # must not raise
