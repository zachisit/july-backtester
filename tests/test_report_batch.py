"""
tests/test_report_batch.py

Unit tests for report.py batch mode (--all RUN_DIR).

Strategy: call report.main() directly (not via subprocess) because report.py
has no global side-effects (no logging.basicConfig, no os.makedirs at module
level), so it is safe to patch sys.argv + generate_trade_report and call
main() inline. This is faster and gives richer introspection than subprocess.

Patches applied in every test:
  - sys.argv                     — simulate CLI arguments
  - report.generate_trade_report — prevent actual PDF/Markdown generation
"""

import os
import sys

import pytest
from unittest.mock import patch, call

# Ensure the project root is on sys.path so `import report` works from tests/
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import report  # noqa: E402  (imported after sys.path manipulation)

MOCK_TARGET = "report.generate_trade_report"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_csv(path, content="Symbol,PnL\nAAPL,100\n"):
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# TestBatchModeHappyPath
# ---------------------------------------------------------------------------

class TestBatchModeHappyPath:
    """--all with a valid run dir containing CSVs generates one report per CSV."""

    def test_calls_generate_for_each_csv(self, tmp_path):
        csvs_dir = tmp_path / "analyzer_csvs" / "Nasdaq_100"
        csvs_dir.mkdir(parents=True)
        _make_csv(csvs_dir / "EMA_Regime.csv")
        _make_csv(csvs_dir / "ATR_Stop.csv")
        _make_csv(csvs_dir / "RSI_Filter.csv")

        with patch(MOCK_TARGET) as mock_gen, \
             patch.object(sys, "argv", ["report.py", "--all", str(tmp_path)]):
            report.main()

        assert mock_gen.call_count == 3

    def test_report_name_is_csv_stem(self, tmp_path):
        csvs_dir = tmp_path / "analyzer_csvs"
        csvs_dir.mkdir()
        _make_csv(csvs_dir / "My_Strategy.csv")

        with patch(MOCK_TARGET) as mock_gen, \
             patch.object(sys, "argv", ["report.py", "--all", str(tmp_path)]):
            report.main()

        _, _, report_name, _ = mock_gen.call_args[0]
        assert report_name == "My_Strategy"

    def test_output_goes_to_detailed_reports(self, tmp_path):
        csvs_dir = tmp_path / "analyzer_csvs"
        csvs_dir.mkdir()
        _make_csv(csvs_dir / "Strat.csv")

        expected_output_dir = str(tmp_path / "detailed_reports")

        with patch(MOCK_TARGET) as mock_gen, \
             patch.object(sys, "argv", ["report.py", "--all", str(tmp_path)]):
            report.main()

        _, output_dir, _, _ = mock_gen.call_args[0]
        assert output_dir == expected_output_dir

    def test_config_base_output_directory_matches_output_dir(self, tmp_path):
        csvs_dir = tmp_path / "analyzer_csvs"
        csvs_dir.mkdir()
        _make_csv(csvs_dir / "Strat.csv")

        with patch(MOCK_TARGET) as mock_gen, \
             patch.object(sys, "argv", ["report.py", "--all", str(tmp_path)]):
            report.main()

        _, output_dir, _, config_params = mock_gen.call_args[0]
        assert config_params["BASE_OUTPUT_DIRECTORY"] == output_dir

    def test_finds_csvs_in_nested_subdirs(self, tmp_path):
        """rglob must descend into portfolio subdirectories."""
        (tmp_path / "analyzer_csvs" / "Nasdaq_100").mkdir(parents=True)
        (tmp_path / "analyzer_csvs" / "SP_500").mkdir(parents=True)
        _make_csv(tmp_path / "analyzer_csvs" / "Nasdaq_100" / "Strat_A.csv")
        _make_csv(tmp_path / "analyzer_csvs" / "SP_500" / "Strat_B.csv")

        with patch(MOCK_TARGET) as mock_gen, \
             patch.object(sys, "argv", ["report.py", "--all", str(tmp_path)]):
            report.main()

        assert mock_gen.call_count == 2

    def test_prints_summary_with_count(self, tmp_path, capsys):
        csvs_dir = tmp_path / "analyzer_csvs"
        csvs_dir.mkdir()
        _make_csv(csvs_dir / "A.csv")
        _make_csv(csvs_dir / "B.csv")

        with patch(MOCK_TARGET), \
             patch.object(sys, "argv", ["report.py", "--all", str(tmp_path)]):
            report.main()

        out = capsys.readouterr().out
        assert "Generated 2 reports" in out

    def test_summary_mentions_detailed_reports_dir(self, tmp_path, capsys):
        csvs_dir = tmp_path / "analyzer_csvs"
        csvs_dir.mkdir()
        _make_csv(csvs_dir / "A.csv")

        with patch(MOCK_TARGET), \
             patch.object(sys, "argv", ["report.py", "--all", str(tmp_path)]):
            report.main()

        out = capsys.readouterr().out
        assert "detailed_reports" in out


# ---------------------------------------------------------------------------
# TestBatchModeErrorPaths
# ---------------------------------------------------------------------------

class TestBatchModeErrorPaths:
    """--all exits 1 when the directory structure is invalid."""

    def test_exits_one_when_no_analyzer_csvs_dir(self, tmp_path):
        """run_dir exists but has no analyzer_csvs/ subfolder."""
        with patch(MOCK_TARGET), \
             patch.object(sys, "argv", ["report.py", "--all", str(tmp_path)]):
            with pytest.raises(SystemExit) as exc_info:
                report.main()
        assert exc_info.value.code == 1

    def test_exits_one_when_run_dir_does_not_exist(self, tmp_path):
        nonexistent = str(tmp_path / "ghost_run")
        with patch(MOCK_TARGET), \
             patch.object(sys, "argv", ["report.py", "--all", nonexistent]):
            with pytest.raises(SystemExit) as exc_info:
                report.main()
        assert exc_info.value.code == 1

    def test_exits_one_when_no_csvs_found(self, tmp_path):
        """analyzer_csvs/ exists but contains no CSV files."""
        (tmp_path / "analyzer_csvs").mkdir()

        with patch(MOCK_TARGET), \
             patch.object(sys, "argv", ["report.py", "--all", str(tmp_path)]):
            with pytest.raises(SystemExit) as exc_info:
                report.main()
        assert exc_info.value.code == 1

    def test_generate_not_called_on_error(self, tmp_path):
        """No reports should be generated when the directory is invalid."""
        with patch(MOCK_TARGET) as mock_gen, \
             patch.object(sys, "argv", ["report.py", "--all", str(tmp_path)]):
            with pytest.raises(SystemExit):
                report.main()
        mock_gen.assert_not_called()

    def test_error_message_mentions_path(self, tmp_path, capsys):
        with patch(MOCK_TARGET), \
             patch.object(sys, "argv", ["report.py", "--all", str(tmp_path)]):
            with pytest.raises(SystemExit):
                report.main()
        out = capsys.readouterr().out
        assert str(tmp_path) in out


# ---------------------------------------------------------------------------
# TestSingleFileModeUnchanged
# ---------------------------------------------------------------------------

class TestSingleFileModeUnchanged:
    """Existing single-file behaviour must be unaffected by the new --all flag."""

    def test_single_file_calls_generate_once(self, tmp_path):
        csv_file = tmp_path / "trades.csv"
        _make_csv(csv_file)

        with patch(MOCK_TARGET) as mock_gen, \
             patch.object(sys, "argv", ["report.py", str(csv_file)]):
            report.main()

        assert mock_gen.call_count == 1

    def test_single_file_exits_one_when_not_found(self, tmp_path):
        missing = str(tmp_path / "missing.csv")
        with patch(MOCK_TARGET), \
             patch.object(sys, "argv", ["report.py", missing]):
            with pytest.raises(SystemExit) as exc_info:
                report.main()
        assert exc_info.value.code == 1

    def test_single_file_and_all_are_mutually_exclusive(self, tmp_path):
        csv_file = tmp_path / "trades.csv"
        _make_csv(csv_file)

        with patch(MOCK_TARGET), \
             patch.object(sys, "argv", ["report.py", str(csv_file), "--all", str(tmp_path)]):
            with pytest.raises(SystemExit) as exc_info:
                report.main()
        # argparse exits 2 for usage errors
        assert exc_info.value.code == 2
