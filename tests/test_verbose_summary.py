# tests/test_verbose_summary.py
"""
Unit tests for verbose summary table toggle (SECTION 21).

Covers:
  TestCompactMode  — default view shows Table 1 only (bordered, ~80 chars)
  TestVerboseMode  — --verbose shows three stacked tables with section headers
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config as _config_module
from helpers.summary import _T1_COLS, _T2_COLS, _T3_COLS, generate_per_portfolio_summary


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

    def test_compact_shows_t1_cols(self, monkeypatch, capsys):
        """Default (verbose_output=False) prints Table 1 column headers."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)
        generate_per_portfolio_summary([_make_result()], "TestPort", 0.12, 0.15, "run_001")
        out = capsys.readouterr().out
        for col in _T1_COLS:
            assert col in out, f"Expected T1 col '{col}' in compact output"

    def test_compact_omits_extended_cols(self, monkeypatch, capsys):
        """Compact mode must NOT show T2/T3-only columns (e.g. Calmar, Roll.Sharpe(avg))."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)
        generate_per_portfolio_summary([_make_result()], "TestPort", 0.12, 0.15, "run_001")
        out = capsys.readouterr().out
        assert "Calmar" not in out
        assert "Roll.Sharpe(avg)" not in out

    def test_compact_prints_verbose_hint(self, monkeypatch, capsys):
        """Compact mode must print a hint containing '--verbose'."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)
        generate_per_portfolio_summary([_make_result()], "TestPort", 0.12, 0.15, "run_001")
        out = capsys.readouterr().out
        assert "--verbose" in out

    def test_compact_output_has_divider_lines(self, monkeypatch, capsys):
        """Table 1 must be wrapped with visible divider lines (---)."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)
        generate_per_portfolio_summary([_make_result()], "TestPort", 0.12, 0.15, "run_001")
        out = capsys.readouterr().out
        assert "---" in out


# ---------------------------------------------------------------------------
# TestVerboseMode
# ---------------------------------------------------------------------------

class TestVerboseMode:

    def test_verbose_shows_extended_metrics_header(self, monkeypatch, capsys):
        """verbose_output=True must print '--- Extended Metrics ---' section header."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", True)
        generate_per_portfolio_summary([_make_result()], "TestPort", 0.12, 0.15, "run_001")
        out = capsys.readouterr().out
        assert "--- Extended Metrics ---" in out

    def test_verbose_shows_robustness_header(self, monkeypatch, capsys):
        """verbose_output=True must print '--- Robustness ---' section header."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", True)
        generate_per_portfolio_summary([_make_result()], "TestPort", 0.12, 0.15, "run_001")
        out = capsys.readouterr().out
        assert "--- Robustness ---" in out

    def test_verbose_shows_t2_cols(self, monkeypatch, capsys):
        """verbose_output=True must include T2 columns (Calmar, Roll.Sharpe(avg))."""
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
