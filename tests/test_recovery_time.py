# tests/test_recovery_time.py
"""
Unit tests for max_recovery_days and avg_recovery_days in helpers/simulations.py.

Covers:
  TestRecoveryTimeCalculation — calculate_advanced_metrics with synthetic equity curves
  TestRecoveryInSummary       — column names appear in printed report output
"""

import io
import os
import sys
from contextlib import redirect_stdout
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.simulations import calculate_advanced_metrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_timeline(values, start="2020-01-01"):
    """Build a pd.Series equity curve with a BusinessDay DatetimeIndex."""
    dates = pd.date_range(start, periods=len(values), freq="B")
    return pd.Series(values, index=dates, dtype=float)


def _run(values):
    """Shortcut: run calculate_advanced_metrics on a synthetic equity curve."""
    tl = _make_timeline(values)
    return calculate_advanced_metrics([100.0], tl, [1])


# ---------------------------------------------------------------------------
# TestRecoveryTimeCalculation
# ---------------------------------------------------------------------------

class TestRecoveryTimeCalculation:

    def test_no_drawdown_returns_none(self):
        """Flat or monotonically rising equity → both metrics must be None."""
        # flat
        result = _run([100_000] * 50)
        assert result["max_recovery_days"] is None
        assert result["avg_recovery_days"] is None

        # strict uptrend
        result = _run(list(range(100_000, 100_200)))
        assert result["max_recovery_days"] is None
        assert result["avg_recovery_days"] is None

    def test_single_drawdown_and_recovery(self):
        """Equity dips then recovers — max_recovery_days must be > 0."""
        # 100 → 110 → 90 → 105 → 120 (expressed over business days)
        result = _run([100_000, 110_000, 90_000, 105_000, 120_000])
        assert result["max_recovery_days"] is not None
        assert result["max_recovery_days"] > 0
        assert result["avg_recovery_days"] is not None
        assert result["avg_recovery_days"] > 0

    def test_open_drawdown_at_end_returns_none(self):
        """Equity never recovers to prior peak → both metrics must be None."""
        # rises to 110k then drops and stays below
        result = _run([100_000, 110_000, 90_000, 95_000, 88_000])
        assert result["max_recovery_days"] is None
        assert result["avg_recovery_days"] is None

    def test_max_greater_or_equal_avg(self):
        """max_recovery_days must always be >= avg_recovery_days."""
        # Two distinct recoveries of different lengths
        # Short dip (2 bars) followed by long dip (4 bars)
        values = (
            [100_000, 110_000,           # peak at index 1
             105_000, 115_000,           # recovery 1 (short)
             110_000,                    # new peak
             100_000, 95_000, 90_000, 115_000]  # deep dip, long recovery
        )
        result = _run(values)
        if result["max_recovery_days"] is not None:
            assert result["max_recovery_days"] >= result["avg_recovery_days"]

    def test_known_value(self):
        """
        Construct an equity curve where recovery from a single drawdown spans
        a known number of calendar days.

        Peak on day 0, dip on day 1, fully recovered on day 10 (business-day index).
        The expected calendar days = (tl.index[10] - tl.index[1]).days, which
        accounts for weekends automatically.
        """
        n = 12
        values = [100_000.0] * n
        values[1] = 90_000.0   # drawdown at index 1
        # indices 2..9 stay below peak (99_999 < 100_000)
        for k in range(2, 10):
            values[k] = 99_999.0
        values[10] = 100_000.0  # recovery at index 10

        tl = _make_timeline(values)
        result = calculate_advanced_metrics([100.0], tl, [1])

        # Expected = actual calendar-day span (accounts for weekends in freq='B')
        expected = (tl.index[10] - tl.index[1]).days
        assert result["max_recovery_days"] == expected
        assert expected > 0


# ---------------------------------------------------------------------------
# TestRecoveryInSummary
# ---------------------------------------------------------------------------

class TestRecoveryInSummary:

    def test_columns_in_report_cols(self, monkeypatch):
        """
        generate_single_asset_summary_report must include 'Max Rcvry (d)' and
        'Avg Rcvry (d)' in the printed output when results carry those keys.
        Recovery columns are in the extended block, so verbose_output=True is required.
        """
        import config as _config_module
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", True)
        from helpers.summary import generate_single_asset_summary_report

        mock_result = {
            "Strategy": "TestStrat",
            "Stop": "none",
            "pnl_percent": 0.20,
            "max_drawdown": 0.10,
            "win_rate": 0.55,
            "calmar_ratio": 2.0,
            "sharpe_ratio": 1.5,
            "profit_factor": 1.8,
            "avg_trade_duration": 5,
            "Trades": 60,
            "mc_verdict": "Robust",
            "mc_score": 4,
            "vs_spy_benchmark": 0.05,
            "vs_qqq_benchmark": 0.03,
            "oos_pnl_pct": 0.10,
            "wfa_verdict": "Pass",
            "expectancy": 0.5,
            "sqn": 2.1,
            "rolling_sharpe_mean": 1.2,
            "rolling_sharpe_min": 0.8,
            "rolling_sharpe_final": 1.1,
            "max_recovery_days": 30,
            "avg_recovery_days": 15.0,
            "initial_capital": 100_000,
        }

        spy_benchmark = {"pnl_percent": 0.15}
        qqq_benchmark = {"pnl_percent": 0.17}

        buf = io.StringIO()
        with redirect_stdout(buf):
            generate_single_asset_summary_report(
                [mock_result],
                spy_benchmark,
                qqq_benchmark,
                "AAPL",
                None,
                "test_run",
            )

        output = buf.getvalue()
        assert "Max Rcvry (d)" in output, "Expected 'Max Rcvry (d)' in summary output"
        assert "Avg Rcvry (d)" in output, "Expected 'Avg Rcvry (d)' in summary output"
