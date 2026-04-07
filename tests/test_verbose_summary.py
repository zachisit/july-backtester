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
from helpers.summary import (
    _T3_COLS,
    _VERBOSE_SHORT_NAMES,
    _get_t1_cols,
    _get_t2_cols,
    _build_benchmark_columns,
    generate_per_portfolio_summary,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_benchmark_returns():
    """Standard benchmark returns dict for tests."""
    return {"SPY": 0.12, "QQQ": 0.15}


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
        benchmark_returns = _make_benchmark_returns()
        generate_per_portfolio_summary([_make_result()], "TestPort", benchmark_returns, "run_001")
        out = capsys.readouterr().out
        # Check T1 columns (dynamically generated based on benchmarks)
        benchmark_columns = _build_benchmark_columns(benchmark_returns)
        t1_cols = _get_t1_cols(benchmark_columns)
        for col in t1_cols:
            assert col in out, f"Expected T1 col '{col}' in compact output"

    def test_compact_omits_extended_cols(self, monkeypatch, capsys):
        """Compact mode must NOT show T2/T3-only columns (e.g. Calmar, Roll.Sharpe(avg))."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)
        benchmark_returns = _make_benchmark_returns()
        generate_per_portfolio_summary([_make_result()], "TestPort", benchmark_returns, "run_001")
        out = capsys.readouterr().out
        assert "Calmar" not in out
        assert "Roll.Sharpe(avg)" not in out

    def test_compact_prints_verbose_hint(self, monkeypatch, capsys):
        """Compact mode must print a hint containing '--verbose'."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)
        benchmark_returns = _make_benchmark_returns()
        generate_per_portfolio_summary([_make_result()], "TestPort", benchmark_returns, "run_001")
        out = capsys.readouterr().out
        assert "--verbose" in out

    def test_compact_output_has_divider_lines(self, monkeypatch, capsys):
        """Table 1 must be wrapped with visible divider lines (---)."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)
        benchmark_returns = _make_benchmark_returns()
        generate_per_portfolio_summary([_make_result()], "TestPort", benchmark_returns, "run_001")
        out = capsys.readouterr().out
        assert "---" in out


# ---------------------------------------------------------------------------
# TestVerboseMode
# ---------------------------------------------------------------------------

class TestVerboseMode:

    def test_verbose_shows_extended_metrics_header(self, monkeypatch, capsys):
        """verbose_output=True must print '--- Extended Metrics ---' section header."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", True)
        benchmark_returns = _make_benchmark_returns()
        generate_per_portfolio_summary([_make_result()], "TestPort", benchmark_returns, "run_001")
        out = capsys.readouterr().out
        assert "--- Extended Metrics ---" in out

    def test_verbose_shows_robustness_header(self, monkeypatch, capsys):
        """verbose_output=True must print '--- Robustness ---' section header."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", True)
        benchmark_returns = _make_benchmark_returns()
        generate_per_portfolio_summary([_make_result()], "TestPort", benchmark_returns, "run_001")
        out = capsys.readouterr().out
        assert "--- Robustness ---" in out

    def test_verbose_shows_t2_cols_shortened(self, monkeypatch, capsys):
        """verbose_output=True shows T2 columns with shortened headers (RS(avg) not Roll.Sharpe(avg))."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", True)
        benchmark_returns = _make_benchmark_returns()
        generate_per_portfolio_summary([_make_result()], "TestPort", benchmark_returns, "run_001")
        out = capsys.readouterr().out
        assert "Calmar" in out          # not in short-names map, stays as-is
        assert "RS(avg)" in out         # shortened from Roll.Sharpe(avg)
        assert "Roll.Sharpe(avg)" not in out  # full name must not appear

    def test_verbose_omits_hint(self, monkeypatch, capsys):
        """verbose_output=True must NOT print the '--verbose' hint line."""
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", True)
        benchmark_returns = _make_benchmark_returns()
        generate_per_portfolio_summary([_make_result()], "TestPort", benchmark_returns, "run_001")
        out = capsys.readouterr().out
        assert "--verbose" not in out
