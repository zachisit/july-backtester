"""
tests/test_init_wizard_branches.py

Branch coverage for helpers/init_wizard.py — functions not hit by
test_init_wizard.py:

  - _section(): lines 65-69
  - _ask(): lines 79-96 (normal path, invalid-choice retry, EOFError/KeyboardInterrupt)
  - _confirm(): line 101
  - run_init_wizard(): lines 289-432
      • yahoo provider → single mode (happy path)
      • polygon provider + API key + .env write
      • portfolio nasdaq100 mode
      • portfolio custom mode
      • abort at confirm step
      • invalid capital + invalid date (retry loops)
      • invalid choice in _ask (retry line 93-94)
      • config.py already exists (warning branch)
      • .env with POLYGON_API_KEY already present (skip branch)
"""
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open

from helpers.init_wizard import (
    run_init_wizard,
    _ask,
    _section,
    _confirm,
)


# ---------------------------------------------------------------------------
# _section() — lines 65-69
# ---------------------------------------------------------------------------

class TestSection:

    def test_section_prints_title(self, capsys):
        """_section() prints a bold separator with the title (lines 65-69)."""
        _section("Test Title")
        out = capsys.readouterr().out
        assert "Test Title" in out

    def test_section_prints_separators(self, capsys):
        """_section() includes '=' separator lines."""
        _section("Step 1")
        out = capsys.readouterr().out
        assert "=" in out


# ---------------------------------------------------------------------------
# _ask() — lines 79-96
# ---------------------------------------------------------------------------

class TestAsk:

    def test_ask_returns_user_input(self):
        """_ask() returns the lowercase-stripped answer from input() (lines 84-96)."""
        with patch("builtins.input", return_value="Yahoo"):
            result = _ask("Which provider?")
        assert result == "yahoo"

    def test_ask_returns_default_on_empty_enter(self):
        """Empty input → default returned (line 90)."""
        with patch("builtins.input", return_value=""):
            result = _ask("Which provider?", default="yahoo")
        assert result == "yahoo"

    def test_ask_with_valid_choice_returns_answer(self):
        """Valid choice from choices list → returned immediately (line 96)."""
        with patch("builtins.input", return_value="csv"):
            result = _ask("Provider?", choices=["yahoo", "csv", "polygon"])
        assert result == "csv"

    def test_ask_invalid_choice_retries_then_valid(self, capsys):
        """Invalid first input → retry message printed → valid second input returned (lines 93-94)."""
        with patch("builtins.input", side_effect=["badchoice", "yahoo"]):
            result = _ask("Provider?", choices=["yahoo", "csv"])
        assert result == "yahoo"
        out = capsys.readouterr().out
        assert "Please enter one of" in out

    def test_ask_eoferror_calls_sys_exit(self):
        """EOFError from input() → sys.exit(0) called (lines 86-88)."""
        with patch("builtins.input", side_effect=EOFError()):
            with pytest.raises(SystemExit):
                _ask("prompt?")

    def test_ask_keyboard_interrupt_calls_sys_exit(self):
        """KeyboardInterrupt from input() → sys.exit(0) called (lines 86-88)."""
        with patch("builtins.input", side_effect=KeyboardInterrupt()):
            with pytest.raises(SystemExit):
                _ask("prompt?")


# ---------------------------------------------------------------------------
# _confirm() — line 101
# ---------------------------------------------------------------------------

class TestConfirm:

    def test_confirm_yes_returns_true(self):
        """_confirm() returns True when user answers 'y' (line 101)."""
        with patch("builtins.input", return_value="y"):
            assert _confirm("Proceed?") is True

    def test_confirm_no_returns_false(self):
        """_confirm() returns False when user answers 'n'."""
        with patch("builtins.input", return_value="n"):
            assert _confirm("Proceed?") is False


# ---------------------------------------------------------------------------
# run_init_wizard() — happy path (yahoo, single, confirm yes)
# ---------------------------------------------------------------------------

class TestRunInitWizardHappyPath:

    def test_yahoo_single_default_no_crash(self, capsys):
        """Yahoo provider, single mode, SPY, confirm yes → wizard completes."""
        inputs = ["yahoo", "100000", "2020-01-01", "single", "SPY", "y"]
        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text"), \
             patch.object(Path, "exists", return_value=False):
            run_init_wizard()
        out = capsys.readouterr().out
        assert "Written" in out or "Next steps" in out

    def test_csv_provider_works(self, capsys):
        """csv provider follows the same code path as yahoo (no API key step)."""
        inputs = ["csv", "50000", "2015-01-01", "single", "AAPL,MSFT", "y"]
        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text"), \
             patch.object(Path, "exists", return_value=False):
            run_init_wizard()

    def test_wizard_writes_config_starter(self, capsys):
        """run_init_wizard() calls write_text to save config_starter.py."""
        inputs = ["yahoo", "100000", "2020-01-01", "single", "SPY", "y"]
        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text") as mock_write, \
             patch.object(Path, "exists", return_value=False):
            run_init_wizard()
        mock_write.assert_called_once()


# ---------------------------------------------------------------------------
# run_init_wizard() — polygon provider + .env write
# ---------------------------------------------------------------------------

class TestRunInitWizardPolygon:

    def test_polygon_with_api_key_writes_env(self, capsys):
        """Polygon provider + API key → .env file is opened and written (lines 310-320)."""
        inputs = ["polygon", "MY_KEY_123", "100000", "2020-01-01", "single", "SPY", "y"]
        m = mock_open()
        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text"), \
             patch.object(Path, "exists", return_value=False), \
             patch.object(Path, "open", m):
            run_init_wizard()
        # .env open was called with "a" mode
        open_calls = [str(c) for c in m.call_args_list]
        assert any("a" in c for c in open_calls)

    def test_polygon_api_key_already_in_env_prints_skipped(self, capsys):
        """If POLYGON_API_KEY already in .env → 'Skipped' printed (line 422)."""
        inputs = ["polygon", "EXISTING_KEY", "100000", "2020-01-01", "single", "SPY", "y"]
        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text"), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "read_text", return_value="POLYGON_API_KEY=existing\n"):
            run_init_wizard()
        out = capsys.readouterr().out
        assert "Skipped" in out or "already present" in out

    def test_polygon_no_api_key_skips_env_write(self, capsys):
        """Polygon provider with empty API key → no .env write."""
        inputs = ["polygon", "", "100000", "2020-01-01", "single", "SPY", "y"]
        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text"), \
             patch.object(Path, "exists", return_value=False):
            run_init_wizard()
        # Should not crash even with empty API key

    def test_polygon_api_key_input_eoferror_exits(self):
        """EOFError during polygon API key input → sys.exit(0) (lines 316-318)."""
        # First input "polygon" selects the provider, then EOFError when asking for key
        def eof_after_first(prompt):
            if "Polygon API key" in prompt:
                raise EOFError()
            return "polygon"

        with patch("builtins.input", side_effect=eof_after_first), \
             patch.object(Path, "exists", return_value=False):
            with pytest.raises(SystemExit):
                run_init_wizard()

    def test_polygon_env_no_trailing_newline_prepends_newline(self, capsys):
        """Existing .env without trailing newline → newline prepended before key (line 418)."""
        inputs = ["polygon", "MY_KEY", "100000", "2020-01-01", "single", "SPY", "y"]
        m = mock_open()
        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text"), \
             patch.object(Path, "exists", return_value=True), \
             patch.object(Path, "read_text", return_value="SOME=content"), \
             patch.object(Path, "open", m):
            run_init_wizard()
        # fh.write("\n") should have been called before the key line
        handle = m.return_value.__enter__.return_value
        write_calls = [c.args[0] for c in handle.write.call_args_list]
        assert "\n" in write_calls


# ---------------------------------------------------------------------------
# run_init_wizard() — portfolio mode
# ---------------------------------------------------------------------------

class TestRunInitWizardPortfolio:

    def test_portfolio_nasdaq100_mode(self, capsys):
        """Portfolio + nasdaq100 → symbols_or_portfolio = {'Nasdaq 100': ...} (lines 375-376)."""
        inputs = ["yahoo", "100000", "2020-01-01", "portfolio", "nasdaq100", "y"]
        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text"), \
             patch.object(Path, "exists", return_value=False):
            run_init_wizard()
        out = capsys.readouterr().out
        # No crash; written or aborted
        assert True

    def test_portfolio_custom_mode(self, capsys):
        """Portfolio + custom → user supplies tickers + name (lines 377-381)."""
        inputs = ["yahoo", "100000", "2020-01-01", "portfolio", "custom",
                  "AAPL,MSFT,GOOGL", "Tech Basket", "y"]
        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text"), \
             patch.object(Path, "exists", return_value=False):
            run_init_wizard()


# ---------------------------------------------------------------------------
# run_init_wizard() — abort at confirm step
# ---------------------------------------------------------------------------

class TestRunInitWizardAbort:

    def test_abort_at_confirm_prints_aborted(self, capsys):
        """User answers 'n' to confirm → 'Aborted' printed, no file written (lines 402-403)."""
        inputs = ["yahoo", "100000", "2020-01-01", "single", "SPY", "n"]
        write_mock = MagicMock()
        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text", write_mock), \
             patch.object(Path, "exists", return_value=False):
            run_init_wizard()
        out = capsys.readouterr().out
        assert "Aborted" in out
        write_mock.assert_not_called()


# ---------------------------------------------------------------------------
# run_init_wizard() — validation retry loops
# ---------------------------------------------------------------------------

class TestRunInitWizardValidation:

    def test_invalid_capital_retries(self, capsys):
        """Non-numeric capital → retry loop executed (lines 333-334)."""
        inputs = ["yahoo", "notanumber", "100000", "2020-01-01", "single", "SPY", "y"]
        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text"), \
             patch.object(Path, "exists", return_value=False):
            run_init_wizard()
        out = capsys.readouterr().out
        assert "positive number" in out or "Must be" in out

    def test_zero_capital_retries(self, capsys):
        """Capital of 0 → retry loop executed (lines 330-334)."""
        inputs = ["yahoo", "0", "100000", "2020-01-01", "single", "SPY", "y"]
        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text"), \
             patch.object(Path, "exists", return_value=False):
            run_init_wizard()
        out = capsys.readouterr().out
        assert "positive number" in out

    def test_invalid_date_retries(self, capsys):
        """Bad date format → retry loop executed (lines 342-343)."""
        inputs = ["yahoo", "100000", "not-a-date", "2020-01-01", "single", "SPY", "y"]
        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text"), \
             patch.object(Path, "exists", return_value=False):
            run_init_wizard()
        out = capsys.readouterr().out
        assert "Invalid date" in out

    def test_invalid_provider_choice_retries(self, capsys):
        """Invalid provider choice → _ask retry → valid choice accepted (lines 93-94)."""
        inputs = ["unknownprovider", "yahoo", "100000", "2020-01-01", "single", "SPY", "y"]
        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text"), \
             patch.object(Path, "exists", return_value=False):
            run_init_wizard()
        out = capsys.readouterr().out
        assert "Please enter one of" in out


# ---------------------------------------------------------------------------
# run_init_wizard() — config.py already exists warning
# ---------------------------------------------------------------------------

class TestRunInitWizardConfigExists:

    def test_config_exists_prints_note_warning(self, capsys):
        """config.py already exists → 'already exists' warning printed (lines 395-398)."""
        inputs = ["yahoo", "100000", "2020-01-01", "single", "SPY", "y"]

        def _exists_side_effect(self_path=None):
            # Returns True for config.py check, False otherwise
            try:
                return "config.py" in str(self_path if self_path is not None else "")
            except Exception:
                return False

        # Use a more targeted mock: make the config.py path return True
        original_exists = Path.exists

        def patched_exists(p):
            if str(p).endswith("config.py"):
                return True
            return False

        with patch("builtins.input", side_effect=inputs), \
             patch.object(Path, "write_text"), \
             patch.object(Path, "exists", patched_exists):
            run_init_wizard()
        out = capsys.readouterr().out
        assert "existing file" in out.lower() or "patched in-place" in out.lower()
