"""
Tests for report.py — covers _load_wfa_split_ratio (all branches) and
main() error-exit paths (file not found, no analyzer_csvs/, no CSVs found).
"""
import json
import sys
import pytest
from pathlib import Path
from unittest.mock import patch

from report import _load_wfa_split_ratio


# ---------------------------------------------------------------------------
# _load_wfa_split_ratio
# ---------------------------------------------------------------------------

class TestLoadWfaSplitRatio:

    def test_missing_snapshot_file_returns_none(self, tmp_path):
        result = _load_wfa_split_ratio(tmp_path)
        assert result is None

    def test_valid_ratio_returned_as_float(self, tmp_path):
        (tmp_path / "config_snapshot.json").write_text(
            json.dumps({"wfa_split_ratio": 0.8})
        )
        result = _load_wfa_split_ratio(tmp_path)
        assert result == pytest.approx(0.8)

    def test_ratio_of_zero_returns_none(self, tmp_path):
        """0 is not a valid ratio (must be 0 < ratio < 1)."""
        (tmp_path / "config_snapshot.json").write_text(
            json.dumps({"wfa_split_ratio": 0})
        )
        assert _load_wfa_split_ratio(tmp_path) is None

    def test_ratio_of_one_returns_none(self, tmp_path):
        """1.0 is not a valid ratio (must be strictly less than 1)."""
        (tmp_path / "config_snapshot.json").write_text(
            json.dumps({"wfa_split_ratio": 1.0})
        )
        assert _load_wfa_split_ratio(tmp_path) is None

    def test_ratio_greater_than_one_returns_none(self, tmp_path):
        (tmp_path / "config_snapshot.json").write_text(
            json.dumps({"wfa_split_ratio": 1.5})
        )
        assert _load_wfa_split_ratio(tmp_path) is None

    def test_ratio_absent_from_snapshot_returns_none(self, tmp_path):
        (tmp_path / "config_snapshot.json").write_text(
            json.dumps({"some_other_key": 42})
        )
        assert _load_wfa_split_ratio(tmp_path) is None

    def test_ratio_null_in_json_returns_none(self, tmp_path):
        (tmp_path / "config_snapshot.json").write_text(
            json.dumps({"wfa_split_ratio": None})
        )
        assert _load_wfa_split_ratio(tmp_path) is None

    def test_invalid_json_returns_none(self, tmp_path):
        (tmp_path / "config_snapshot.json").write_text("not valid json {{")
        assert _load_wfa_split_ratio(tmp_path) is None

    def test_non_numeric_ratio_returns_none(self, tmp_path):
        (tmp_path / "config_snapshot.json").write_text(
            json.dumps({"wfa_split_ratio": "high"})
        )
        assert _load_wfa_split_ratio(tmp_path) is None

    def test_ratio_as_string_number_returns_float(self, tmp_path):
        """String "0.75" is coerced to float via float(ratio)."""
        (tmp_path / "config_snapshot.json").write_text(
            json.dumps({"wfa_split_ratio": "0.75"})
        )
        result = _load_wfa_split_ratio(tmp_path)
        assert result == pytest.approx(0.75)

    def test_minimum_valid_ratio(self, tmp_path):
        (tmp_path / "config_snapshot.json").write_text(
            json.dumps({"wfa_split_ratio": 0.01})
        )
        assert _load_wfa_split_ratio(tmp_path) == pytest.approx(0.01)

    def test_maximum_valid_ratio(self, tmp_path):
        (tmp_path / "config_snapshot.json").write_text(
            json.dumps({"wfa_split_ratio": 0.99})
        )
        assert _load_wfa_split_ratio(tmp_path) == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# main() — error-exit paths
# ---------------------------------------------------------------------------

class TestMainErrorExits:

    def test_single_file_not_found_exits_with_1(self, tmp_path):
        missing = str(tmp_path / "nonexistent.csv")
        with patch("sys.argv", ["report.py", missing]):
            with pytest.raises(SystemExit) as exc_info:
                from report import main
                main()
        assert exc_info.value.code == 1

    def test_batch_mode_no_analyzer_csvs_dir_exits_with_1(self, tmp_path):
        # tmp_path exists but has no analyzer_csvs/ subdirectory
        with patch("sys.argv", ["report.py", "--all", str(tmp_path)]):
            with pytest.raises(SystemExit) as exc_info:
                from report import main
                main()
        assert exc_info.value.code == 1

    def test_batch_mode_empty_analyzer_csvs_dir_exits_with_1(self, tmp_path):
        # analyzer_csvs/ exists but contains no CSV files
        (tmp_path / "analyzer_csvs").mkdir()
        with patch("sys.argv", ["report.py", "--all", str(tmp_path)]):
            with pytest.raises(SystemExit) as exc_info:
                from report import main
                main()
        assert exc_info.value.code == 1
