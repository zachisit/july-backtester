"""
tests/test_main_cli.py

CLI integration tests for main.py.

We use subprocess.run rather than calling main() directly because:
  - main() calls sys.exit(), which would kill the pytest process if not caught
  - logging.basicConfig() and os.makedirs() mutate global state across calls
  - subprocess gives true isolation: each test gets a fresh Python process
    with its own env, argv, and working directory

Stream conventions in main.py:
  - print()       -> stdout  (S1 / S2 error messages)
  - logger.info() -> stderr  (logging.StreamHandler defaults to sys.stderr)
"""

import os
import subprocess
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIN = os.path.join(PROJECT_ROOT, "main.py")


def _run(*args, extra_env=None):
    """Run main.py as a subprocess from the project root, return CompletedProcess."""
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [sys.executable, MAIN, *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=PROJECT_ROOT,
    )


def _run_with_config_patch(tmp_path, patches: dict, cli_args=("--dry-run",), extra_env=None):
    """
    Wrapper-script approach: mutates CONFIG keys then calls main.main().
    Mirrors the identical helper in test_startup_validation.py.
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
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [sys.executable, str(wrapper)],
        capture_output=True, text=True,
        env=env, cwd=PROJECT_ROOT,
    )


# ---------------------------------------------------------------------------
# TestDryRun
# ---------------------------------------------------------------------------

class TestDryRun:
    """--dry-run exits 0 after the run summary, without fetching any data."""

    def test_exits_zero(self):
        result = _run("--dry-run", extra_env={"POLYGON_API_KEY": "test-key"})
        assert result.returncode == 0

    def test_prints_run_summary_header(self):
        result = _run("--dry-run", extra_env={"POLYGON_API_KEY": "test-key"})
        assert "RUN SUMMARY" in result.stderr

    def test_prints_dry_run_exit_message(self):
        result = _run("--dry-run", extra_env={"POLYGON_API_KEY": "test-key"})
        assert "[DRY RUN]" in result.stderr

    def test_does_not_fetch_data(self):
        """Data fetcher init logs 'Using Polygon.io Data Service' — must not appear."""
        result = _run("--dry-run", extra_env={"POLYGON_API_KEY": "test-key"})
        combined = result.stdout + result.stderr
        assert "Using Polygon.io Data Service" not in combined

    def test_name_prefix_appears_in_run_id(self):
        result = _run("--dry-run", "--name", "ci-test", extra_env={"POLYGON_API_KEY": "test-key"})
        assert result.returncode == 0
        assert "ci-test_" in result.stderr


# ---------------------------------------------------------------------------
# TestMissingApiKey
# ---------------------------------------------------------------------------

class TestMissingApiKey:
    """S1 guard: missing POLYGON_API_KEY exits 1 before argparse or dry-run gate."""

    # These tests force data_provider='polygon' so S1 fires regardless of the
    # current config.py setting (user may have switched to 'yahoo' or 'csv').

    def test_exits_one(self, tmp_path):
        result = _run_with_config_patch(
            tmp_path,
            patches={"data_provider": "polygon"},
            extra_env={"POLYGON_API_KEY": ""},
        )
        assert result.returncode == 1

    def test_prints_error_message(self, tmp_path):
        result = _run_with_config_patch(
            tmp_path,
            patches={"data_provider": "polygon"},
            extra_env={"POLYGON_API_KEY": ""},
        )
        assert "POLYGON_API_KEY is not set" in result.stdout

    def test_dry_run_message_not_printed(self, tmp_path):
        """S1 fires before the dry-run gate — [DRY RUN] must never appear."""
        result = _run_with_config_patch(
            tmp_path,
            patches={"data_provider": "polygon"},
            extra_env={"POLYGON_API_KEY": ""},
        )
        combined = result.stdout + result.stderr
        assert "[DRY RUN]" not in combined

    def test_run_summary_not_printed(self, tmp_path):
        """S1 fires before the run summary block — RUN SUMMARY must not appear."""
        result = _run_with_config_patch(
            tmp_path,
            patches={"data_provider": "polygon"},
            extra_env={"POLYGON_API_KEY": ""},
        )
        combined = result.stdout + result.stderr
        assert "RUN SUMMARY" not in combined


# ---------------------------------------------------------------------------
# TestHelpFlag
# ---------------------------------------------------------------------------

class TestHelpFlag:
    """--help is processed by argparse (after S1 passes), exits 0."""

    def test_exits_zero(self):
        result = _run("--help", extra_env={"POLYGON_API_KEY": "test-key"})
        assert result.returncode == 0

    def test_documents_dry_run_flag(self):
        result = _run("--help", extra_env={"POLYGON_API_KEY": "test-key"})
        # argparse writes help to stdout
        assert "--dry-run" in result.stdout + result.stderr

    def test_documents_name_flag(self):
        result = _run("--help", extra_env={"POLYGON_API_KEY": "test-key"})
        assert "--name" in result.stdout + result.stderr
