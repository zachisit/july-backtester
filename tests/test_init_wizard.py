# tests/test_init_wizard.py
"""
Unit tests for helpers/init_wizard.py.

Covers:
  TestBuildConfig          — _build_config output: valid Python, required keys,
                             provider/capital/date presence, mode branching
  TestPatchExistingConfig  — _patch_existing_config: in-place key patching,
                             non-destructive behaviour, missing-key tolerance,
                             valid Python output
  TestColourHelpers        — bold/green/yellow/cyan/red return strings,
                             plain text when _USE_COLOR is False
"""

import ast
import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.init_wizard import (
    _build_config,
    _patch_existing_config,
    bold,
    cyan,
    green,
    red,
    yellow,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_END_EXPR = 'datetime.now().strftime("%Y-%m-%d")'

_REQUIRED_KEYS = [
    "data_provider",
    "initial_capital",
    "start_date",
    "end_date",
    "allocation_per_trade",
    "stop_loss_configs",
    "wfa_split_ratio",
    "noise_injection_pct",
    "strategies",
]


def _cfg(provider="yahoo", capital=100_000.0, start="2010-01-01",
         mode="single", symbols=None):
    if symbols is None:
        symbols = ["SPY"]
    return _build_config(provider, capital, start, _END_EXPR, mode, symbols)


# ---------------------------------------------------------------------------
# TestBuildConfig
# ---------------------------------------------------------------------------

class TestBuildConfig:

    def test_valid_python_all_providers(self):
        """_build_config must produce parseable Python for all four providers."""
        for provider in ("yahoo", "csv", "polygon", "norgate"):
            text = _cfg(provider=provider)
            try:
                ast.parse(text)
            except SyntaxError as exc:
                pytest.fail(f"SyntaxError for provider={provider!r}: {exc}")

    def test_provider_in_output(self):
        """The chosen provider string must appear in the output."""
        text = _cfg(provider="yahoo")
        assert '"data_provider": "yahoo"' in text

    def test_capital_in_output(self):
        """The capital value must appear in the output."""
        text = _cfg(capital=250_000.0)
        assert "250000.0" in text

    def test_start_date_in_output(self):
        """The start_date string must appear in the output."""
        text = _cfg(start="2015-06-01")
        assert "2015-06-01" in text

    def test_single_mode_sets_symbols_to_test(self):
        """Single mode must emit a non-empty symbols_to_test list."""
        text = _cfg(mode="single", symbols=["AAPL", "MSFT"])
        assert '"symbols_to_test"' in text
        assert "AAPL" in text
        assert "MSFT" in text

    def test_portfolio_mode_sets_portfolios(self):
        """Portfolio mode must emit the portfolio dict and empty symbols_to_test."""
        portfolio = {"Nasdaq 100": "nasdaq_100.json"}
        text = _build_config("yahoo", 100_000.0, "2010-01-01", _END_EXPR, "portfolio", portfolio)
        assert "nasdaq_100.json" in text
        assert '"symbols_to_test": []' in text

    def test_all_required_keys_present(self):
        """Every required CONFIG key must appear in the generated text."""
        text = _cfg()
        for key in _REQUIRED_KEYS:
            assert f'"{key}"' in text, f"Missing required key: {key!r}"

    def test_noise_injection_default_zero(self):
        """noise_injection_pct must always be 0.0 in the generated config."""
        text = _cfg()
        assert '"noise_injection_pct": 0.0' in text

    def test_strategies_all_by_default(self):
        """strategies must default to "all" in the generated config."""
        text = _cfg()
        assert '"strategies": "all"' in text

    def test_polygon_note_present_for_polygon(self):
        """Polygon-specific .env note must appear when provider is polygon."""
        text = _cfg(provider="polygon")
        assert "POLYGON_API_KEY" in text

    def test_polygon_note_absent_for_yahoo(self):
        """No POLYGON_API_KEY note when provider is yahoo."""
        text = _cfg(provider="yahoo")
        assert "POLYGON_API_KEY" not in text


# ---------------------------------------------------------------------------
# TestPatchExistingConfig
# ---------------------------------------------------------------------------

class TestPatchExistingConfig:
    """Tests for _patch_existing_config — in-place patching of an existing config.py."""

    # Minimal config snippets used across tests
    _FULL_SNIPPET = (
        '    "data_provider": "polygon",\n'
        '    "initial_capital": 100000.0,\n'
        '    "start_date": "2004-01-01",\n'
        '    "symbols_to_test": [\'BITB\'],\n'
        '    "commission_per_share": 0.002,\n'
    )

    def _make(self, tmp_path, content=None):
        p = tmp_path / "config.py"
        p.write_text(content or self._FULL_SNIPPET, encoding="utf-8")
        return p

    # --- individual key patches ---

    def test_patches_data_provider(self, tmp_path):
        p = self._make(tmp_path)
        text, changes = _patch_existing_config(p, "yahoo", 100_000.0, "2004-01-01", "single", ["SPY"])
        assert '"data_provider": "yahoo"' in text
        assert any("data_provider" in c for c in changes)

    def test_patches_initial_capital(self, tmp_path):
        p = self._make(tmp_path)
        text, changes = _patch_existing_config(p, "polygon", 250_000.0, "2004-01-01", "single", ["SPY"])
        assert "250000.0" in text
        assert any("initial_capital" in c for c in changes)

    def test_patches_start_date(self, tmp_path):
        p = self._make(tmp_path)
        text, changes = _patch_existing_config(p, "polygon", 100_000.0, "2015-06-01", "single", ["SPY"])
        assert '"start_date": "2015-06-01"' in text
        assert any("start_date" in c for c in changes)

    def test_patches_symbols_to_test_single_mode(self, tmp_path):
        p = self._make(tmp_path)
        text, changes = _patch_existing_config(p, "polygon", 100_000.0, "2004-01-01", "single", ["AAPL", "MSFT"])
        assert "AAPL" in text
        assert "MSFT" in text
        assert any("symbols_to_test" in c for c in changes)

    def test_patches_portfolios_portfolio_mode(self, tmp_path):
        content = (
            '    "portfolios": {\n'
            '        "Old Portfolio": "old.json",\n'
            '    },\n'
        )
        p = self._make(tmp_path, content)
        portfolio = {"Nasdaq 100": "nasdaq_100.json"}
        text, changes = _patch_existing_config(p, "polygon", 100_000.0, "2004-01-01", "portfolio", portfolio)
        assert "nasdaq_100.json" in text
        assert "Old Portfolio" not in text
        assert any("portfolios" in c for c in changes)

    # --- non-destructive behaviour ---

    def test_unrelated_keys_are_preserved(self, tmp_path):
        """Keys the wizard doesn't ask about must survive unchanged."""
        p = self._make(tmp_path)
        text, _ = _patch_existing_config(p, "yahoo", 100_000.0, "2004-01-01", "single", ["SPY"])
        assert '"commission_per_share": 0.002' in text

    def test_old_provider_value_is_gone_after_patch(self, tmp_path):
        p = self._make(tmp_path)
        text, _ = _patch_existing_config(p, "yahoo", 100_000.0, "2004-01-01", "single", ["SPY"])
        assert '"data_provider": "polygon"' not in text

    def test_all_four_keys_patched_in_one_call(self, tmp_path):
        p = self._make(tmp_path)
        text, changes = _patch_existing_config(p, "yahoo", 50_000.0, "2020-01-01", "single", ["QQQ"])
        assert '"data_provider": "yahoo"' in text
        assert "50000.0" in text
        assert '"start_date": "2020-01-01"' in text
        assert "QQQ" in text
        assert len(changes) == 4

    # --- missing-key tolerance ---

    def test_missing_data_provider_skipped_not_crash(self, tmp_path):
        p = self._make(tmp_path, '    "initial_capital": 100000.0,\n')
        text, changes = _patch_existing_config(p, "yahoo", 100_000.0, "2010-01-01", "single", ["SPY"])
        assert not any("data_provider" in c for c in changes)

    def test_missing_symbols_skipped_not_crash(self, tmp_path):
        p = self._make(tmp_path, '    "data_provider": "polygon",\n')
        text, changes = _patch_existing_config(p, "yahoo", 100_000.0, "2010-01-01", "single", ["AAPL"])
        assert not any("symbols_to_test" in c for c in changes)

    def test_empty_changes_list_when_nothing_matches(self, tmp_path):
        p = self._make(tmp_path, '# nothing here\n')
        _, changes = _patch_existing_config(p, "yahoo", 100_000.0, "2010-01-01", "single", ["SPY"])
        assert changes == []

    # --- output validity ---

    def test_patched_full_config_is_valid_python(self, tmp_path):
        """Patching a full _build_config output must still produce valid Python."""
        base = _build_config(
            "polygon", 100_000.0, "2004-01-01",
            'datetime.now().strftime("%Y-%m-%d")',
            "single", ["SPY"],
        )
        p = self._make(tmp_path, base)
        text, _ = _patch_existing_config(p, "yahoo", 250_000.0, "2015-01-01", "single", ["AAPL"])
        try:
            ast.parse(text)
        except SyntaxError as exc:
            pytest.fail(f"Patched config is not valid Python: {exc}")


# ---------------------------------------------------------------------------
# TestColourHelpers
# ---------------------------------------------------------------------------

class TestColourHelpers:

    def test_all_helpers_return_string_containing_input(self):
        """Each colour helper must return a string that contains the input text."""
        for fn in (bold, green, yellow, cyan, red):
            result = fn("hello")
            assert isinstance(result, str)
            assert "hello" in result

    def test_no_tty_returns_plain_text(self, monkeypatch):
        """When _USE_COLOR is False, bold() must return the input unchanged."""
        import helpers.init_wizard as _wiz
        monkeypatch.setattr(_wiz, "_USE_COLOR", False)
        assert _wiz.bold("abc") == "abc"
        assert _wiz.green("xyz") == "xyz"
        assert _wiz.red("err") == "err"
