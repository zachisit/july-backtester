# tests/test_init_wizard.py
"""
Unit tests for helpers/init_wizard.py.

Covers:
  TestBuildConfig     — _build_config output: valid Python, required keys,
                        provider/capital/date presence, mode branching
  TestColourHelpers   — bold/green/yellow/cyan/red return strings,
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
