# tests/test_verbose_summary.py
"""
Unit tests for verbose summary table toggle (SECTION 21).

Covers:
  TestCompactMode  — default compact display shows only _DEFAULT_COLS
  TestVerboseMode  — --verbose shows the full extended table
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config as _config_module
from helpers.summary import _DEFAULT_COLS, generate_per_portfolio_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(strategy="TestStrat", n_trades=5):
    """Minimal result dict that passes all default display filters."""
    return {
        "Strategy": strategy,
        "Asset": "SPY",
        "pnl_percent": 0.15,
        "max_drawdown": 0.08,
        "win_rate": 0.55,
        "calmar_ratio": 1.2,
        "sharpe_ratio": 1.5,
        "profit_factor": 1.8,
        "avg_trade_duration": 12.0,
        "mc_verdict": "Pass",
        "mc_score": 72,
        "vs_spy_benchmark": 0.05,
        "vs_qqq_benchmark": 0.02,
        "oos_pnl_pct": 0.10,
        "wfa_verdict": "Pass",
        "wfa_rolling_verdict": "Pass (3/3)",
        "avg_corr": 0.3,
        "expectancy": 0.8,
        "sqn": 2.5,
        "rolling_sharpe_mean": 1.4,
        "rolling_sharpe_min": 0.9,
        "rolling_sharpe_final": 1.6,
        "max_recovery_days": 45,
        "avg_recovery_days": 20.0,
        "Trades": n_trades,
        "Portfolio": "TestPort",
        "trade_log": [],
    }


# ---------------------------------------------------------------------------
# TestCompactMode
# ---------------------------------------------------------------------------

class TestCompactMode:

    def test_compact_shows_default_cols(self, monkeypatch, capsys):
        """Default (verbose_output=False) prints only _DEFAULT_COLS headers."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)
        generate_per_portfolio_summary([_make_result()], "TestPort", 0.12, 0.15, "run_001")
        out = capsys.readouterr().out
        for col in _DEFAULT_COLS:
            assert col in out, f"Expected default col '{col}' in compact output"

    def test_compact_omits_extended_cols(self, monkeypatch, capsys):
        """Compact mode must NOT show columns outside _DEFAULT_COLS (e.g. Calmar)."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)
        generate_per_portfolio_summary([_make_result()], "TestPort", 0.12, 0.15, "run_001")
        out = capsys.readouterr().out
        assert "Calmar" not in out
        assert "Roll.Sharpe(avg)" not in out

    def test_compact_prints_verbose_hint(self, monkeypatch, capsys):
        """Compact mode must append a line containing '--verbose'."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)
        generate_per_portfolio_summary([_make_result()], "TestPort", 0.12, 0.15, "run_001")
        out = capsys.readouterr().out
        assert "--verbose" in out


# ---------------------------------------------------------------------------
# TestVerboseMode
# ---------------------------------------------------------------------------

class TestVerboseMode:

    def test_verbose_shows_extended_cols(self, monkeypatch, capsys):
        """verbose_output=True must include columns beyond _DEFAULT_COLS."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", True)
        generate_per_portfolio_summary([_make_result()], "TestPort", 0.12, 0.15, "run_001")
        out = capsys.readouterr().out
        assert "Calmar" in out
        assert "Roll.Sharpe(avg)" in out

    def test_verbose_omits_hint(self, monkeypatch, capsys):
        """verbose_output=True must NOT print the '--verbose' hint line."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", True)
        generate_per_portfolio_summary([_make_result()], "TestPort", 0.12, 0.15, "run_001")
        out = capsys.readouterr().out
        assert "--verbose" not in out
