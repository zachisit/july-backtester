"""
tests/test_report_command_hint.py

Tests for the copy-paste report command hint printed at the end of every run.

Covers:
    - Correct command string format
    - Correct run path embedded in command
    - Visual separator lines present and consistent
    - Works for typical run IDs (timestamped and named)
    - logger.info called the expected number of times
"""

import os
from unittest.mock import call, patch

import pytest

from main import _print_report_hint


class TestPrintReportHint:

    def _captured_calls(self, run_folder_name: str) -> list[str]:
        """Run _print_report_hint and return the list of strings passed to logger.info."""
        with patch("main.logger") as mock_logger:
            _print_report_hint(run_folder_name)
            return [c.args[0] for c in mock_logger.info.call_args_list]

    def test_logs_three_lines(self):
        lines = self._captured_calls("2026-04-05_21-01-37")
        assert len(lines) == 3

    def test_command_contains_report_py(self):
        lines = self._captured_calls("2026-04-05_21-01-37")
        assert any("report.py" in l for l in lines)

    def test_command_contains_all_flag(self):
        lines = self._captured_calls("2026-04-05_21-01-37")
        assert any("--all" in l for l in lines)

    def test_command_contains_run_folder_name(self):
        run_id = "2026-04-05_21-01-37"
        lines = self._captured_calls(run_id)
        assert any(run_id in l for l in lines)

    def test_command_contains_correct_path(self):
        run_id = "2026-04-05_21-01-37"
        expected_path = f"output/runs/{run_id}"
        lines = self._captured_calls(run_id)
        assert any(expected_path in l for l in lines)

    def test_command_is_copy_pasteable(self):
        """Command line must start with 'python report.py --all'."""
        run_id = "myrun_2026-04-05_21-01-37"
        lines = self._captured_calls(run_id)
        cmd_line = next(l for l in lines if "report.py" in l)
        assert "python report.py --all" in cmd_line

    def test_separator_lines_match_command_length(self):
        """Both separator bars must be the same length as the command string."""
        run_id = "2026-04-05_21-01-37"
        lines = self._captured_calls(run_id)
        bar, cmd_line, bar2 = lines
        # The command is indented in the middle line; bar width = raw cmd length
        raw_cmd = f"python report.py --all {os.path.join('output', 'runs', run_id)}"
        assert len(bar) == len(raw_cmd)
        assert bar == bar2

    def test_named_run_id_included(self):
        """Named runs (with --name prefix) must appear correctly."""
        run_id = "mybacktest_2026-04-05_21-01-37"
        lines = self._captured_calls(run_id)
        assert any(run_id in l for l in lines)

    def test_separator_uses_heavy_bar_character(self):
        """Separator must use ━ (U+2501 BOX DRAWINGS HEAVY HORIZONTAL)."""
        lines = self._captured_calls("2026-04-05_21-01-37")
        bar = lines[0]
        assert all(c == "━" for c in bar)
