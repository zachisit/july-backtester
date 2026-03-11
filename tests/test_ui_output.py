"""
tests/test_ui_output.py

Subprocess-based tests for the U1 "RUN SUMMARY" box in main.py.

Strategy: run main.py with --dry-run (subprocess) and assert on stderr,
where logging.StreamHandler writes.  CONFIG is mutated via the same
wrapper-script technique established in test_startup_validation.py so that
symbol counts and strategy/stop counts are fully controlled.

U1 content tests: verify the box is present and contains the expected labels.
U1 task-count tests: verify the arithmetic (symbols × strategies × stop configs).
"""

import os
import re
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIN = os.path.join(PROJECT_ROOT, "main.py")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_main(*args, extra_env=None):
    """Run main.py directly without patching CONFIG."""
    env = os.environ.copy()
    env.setdefault("POLYGON_API_KEY", "test-key")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, MAIN, *args],
        capture_output=True, text=True,
        env=env, cwd=PROJECT_ROOT,
    )


def _run_with_config_patch(tmp_path, patches: dict, cli_args=("--dry-run",), extra_env=None):
    """
    Generate a wrapper that mutates CONFIG keys then calls main.main().
    Identical pattern to test_startup_validation.py.
    """
    lines = [
        "import sys",
        f"sys.path.insert(0, {repr(PROJECT_ROOT)})",
        "import config",
    ]
    for k, v in patches.items():
        lines.append(f"config.CONFIG[{repr(k)}] = {repr(v)}")
    lines.append(f"sys.argv = {repr(['main.py'] + list(cli_args))}")
    lines.append("import main")
    lines.append("main.main()")

    wrapper = tmp_path / "run_patched.py"
    wrapper.write_text("\n".join(lines), encoding="utf-8")

    env = os.environ.copy()
    env["POLYGON_API_KEY"] = "test-key"
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [sys.executable, str(wrapper)],
        capture_output=True, text=True,
        env=env, cwd=PROJECT_ROOT,
    )


# ---------------------------------------------------------------------------
# U1 — Summary Box Content
# ---------------------------------------------------------------------------

class TestU1SummaryContent:
    """U1: the RUN SUMMARY box is present and contains the required labels."""

    def test_run_summary_header_present(self):
        result = _run_main("--dry-run")
        assert "RUN SUMMARY" in result.stderr

    def test_box_delimiters_present(self):
        """The box is drawn with lines of '=' characters."""
        result = _run_main("--dry-run")
        eq_lines = [l for l in result.stderr.splitlines() if "=" * 10 in l]
        assert len(eq_lines) >= 2

    def test_run_id_label_present(self):
        result = _run_main("--dry-run")
        assert "Run ID" in result.stderr

    def test_data_provider_label_present(self):
        result = _run_main("--dry-run")
        assert "Data provider" in result.stderr

    def test_period_label_present(self):
        """'Period Selected' must appear (also satisfies the old 'Period' substring check)."""
        result = _run_main("--dry-run")
        assert "Period Selected" in result.stderr

    def test_strategies_label_present(self):
        result = _run_main("--dry-run")
        assert "Strategies" in result.stderr

    def test_total_tasks_label_present(self):
        result = _run_main("--dry-run")
        assert "Total tasks" in result.stderr

    def test_period_contains_arrow(self):
        """Period line format: 'start_date -> end_date'."""
        result = _run_main("--dry-run")
        period_lines = [l for l in result.stderr.splitlines() if "Period" in l]
        assert any("->" in l for l in period_lines)

    def test_dry_run_message_follows_summary(self):
        """[DRY RUN] must appear after the summary box."""
        result = _run_main("--dry-run")
        summary_pos = result.stderr.find("RUN SUMMARY")
        dry_run_pos = result.stderr.find("[DRY RUN]")
        assert summary_pos != -1 and dry_run_pos != -1
        assert dry_run_pos > summary_pos

    def test_data_provider_value_matches_config(self, tmp_path):
        result = _run_with_config_patch(tmp_path, {"data_provider": "alpaca"})
        assert "alpaca" in result.stderr

    def test_period_values_match_config(self, tmp_path):
        result = _run_with_config_patch(
            tmp_path,
            {"start_date": "2018-06-01", "end_date": "2022-12-31"},
        )
        assert "2018-06-01" in result.stderr
        assert "2022-12-31" in result.stderr

    def test_period_selected_label_is_exact(self):
        """The startup summary must say 'Period Selected', not the old 'Period'."""
        result = _run_main("--dry-run")
        # The exact label should be present
        assert "Period Selected" in result.stderr
        # And the old bare label should not appear as a standalone label
        # (it may still appear as part of "Period Selected", which is fine)
        lines_with_period = [l for l in result.stderr.splitlines() if "Period" in l]
        # Every line with "Period" must also contain "Selected" (it's always qualified now)
        for line in lines_with_period:
            assert "Selected" in line, (
                f"Found bare 'Period' label (expected 'Period Selected'): {line!r}"
            )


# ---------------------------------------------------------------------------
# U1 — Total Tasks Arithmetic (symbols × strategies × stop configs)
# ---------------------------------------------------------------------------

class TestU1TaskCountArithmetic:
    """U1: 'Total tasks' = symbols × len(STRATEGIES) × len(stop_loss_configs)."""

    def _extract_total_tasks(self, stderr: str):
        """Parse the integer after 'Total tasks   :' from the summary output.

        Uses regex to avoid the log-timestamp colon collision:
        e.g. '2024-01-01 12:45:00,000 [INFO]   Total tasks   : 20  (...)'
        would yield '45' via naive split(":")[1] because the timestamp
        minutes appear before the metric value.
        """
        for line in stderr.splitlines():
            m = re.search(r'Total tasks\s*:\s*(\d+)', line)
            if m:
                return int(m.group(1))
        return None

    def _extract_strategies_count(self, stderr: str):
        for line in stderr.splitlines():
            if "Stop" not in line:
                m = re.search(r'Strategies\s*:\s*(\d+)', line)
                if m:
                    return int(m.group(1))
        return None

    def _extract_stop_configs_count(self, stderr: str):
        for line in stderr.splitlines():
            m = re.search(r'Stop configs\s*:\s*(\d+)', line)
            if m:
                return int(m.group(1))
        return None

    def test_task_count_with_list_portfolio(self, tmp_path):
        """
        2 symbols × N strategies × 1 stop config = 2N tasks.
        We don't hardcode N (strategies count changes as the project grows),
        so we derive the expected value from the other logged numbers.
        """
        result = _run_with_config_patch(
            tmp_path,
            patches={
                "portfolios": {"Test": ["AAPL", "MSFT"]},
                "stop_loss_configs": [{"type": "none"}],
            },
        )
        total_tasks = self._extract_total_tasks(result.stderr)
        n_strategies = self._extract_strategies_count(result.stderr)
        n_stops = self._extract_stop_configs_count(result.stderr)

        assert total_tasks is not None, f"Could not parse Total tasks from:\n{result.stderr}"
        assert total_tasks == 2 * n_strategies * n_stops

    def test_task_count_scales_with_symbol_count(self, tmp_path):
        """Doubling symbols doubles total tasks."""
        def _tasks_for(symbols):
            r = _run_with_config_patch(
                tmp_path,
                patches={
                    "portfolios": {"P": symbols},
                    "stop_loss_configs": [{"type": "none"}],
                },
            )
            return self._extract_total_tasks(r.stderr)

        tasks_2 = _tasks_for(["A", "B"])
        tasks_4 = _tasks_for(["A", "B", "C", "D"])
        assert tasks_2 is not None and tasks_4 is not None
        assert tasks_4 == tasks_2 * 2

    def test_task_count_scales_with_stop_config_count(self, tmp_path):
        """Two stop configs double the total tasks vs one stop config."""
        def _tasks_for(stops):
            r = _run_with_config_patch(
                tmp_path,
                patches={
                    "portfolios": {"P": ["AAPL", "MSFT"]},
                    "stop_loss_configs": stops,
                },
            )
            return self._extract_total_tasks(r.stderr)

        tasks_1_stop = _tasks_for([{"type": "none"}])
        tasks_2_stops = _tasks_for([{"type": "none"}, {"type": "percentage", "value": 0.10}])
        assert tasks_1_stop is not None and tasks_2_stops is not None
        assert tasks_2_stops == tasks_1_stop * 2

    def test_task_count_multi_portfolio_sums_correctly(self, tmp_path):
        """
        Two portfolios with 2 symbols each → 4 symbols total.
        Expected: 4 × strategies × stops.
        """
        result = _run_with_config_patch(
            tmp_path,
            patches={
                "portfolios": {
                    "P1": ["AAPL", "MSFT"],
                    "P2": ["GOOG", "AMZN"],
                },
                "stop_loss_configs": [{"type": "none"}],
            },
        )
        total_tasks = self._extract_total_tasks(result.stderr)
        n_strategies = self._extract_strategies_count(result.stderr)
        n_stops = self._extract_stop_configs_count(result.stderr)
        assert total_tasks == 4 * n_strategies * n_stops

    def test_total_symbols_label_present(self, tmp_path):
        result = _run_with_config_patch(
            tmp_path,
            patches={"portfolios": {"P": ["AAPL", "MSFT", "TSLA"]}},
        )
        assert "Total symbols" in result.stderr

    def test_portfolio_symbol_count_shown_in_summary(self, tmp_path):
        result = _run_with_config_patch(
            tmp_path,
            patches={"portfolios": {"MyPortfolio": ["A", "B", "C"]}},
        )
        # Should log "MyPortfolio (3 symbols)"
        assert "MyPortfolio" in result.stderr
        assert "3 symbols" in result.stderr
