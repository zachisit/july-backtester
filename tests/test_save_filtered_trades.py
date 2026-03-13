# tests/test_save_filtered_trades.py
"""
Regression test for save_only_filtered_trades correctness.

Before the fix, Step 4b in generate_per_portfolio_summary() rebuilt display_df
from the raw portfolio_results instead of using the already-filtered set from
Step 2, so save_only_filtered_trades=True saved ALL strategies regardless of
whether they passed the display filters.
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import patch

from config import CONFIG
from helpers.summary import generate_per_portfolio_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(strategy_name, pnl_percent, with_trades=True):
    """Build a minimal portfolio result dict suitable for generate_per_portfolio_summary."""
    trade_log = [
        {
            "EntryDate": "2024-01-02",
            "ExitDate": "2024-01-05",
            "EntryPrice": 100.0,
            "ExitPrice": 105.0,
            "Profit": 50.0,
            "ProfitPct": 0.05,
            "is_win": True,
            "HoldDuration": 3,
            "Shares": 10,
            "MAE_pct": 0.01,
            "MFE_pct": 0.06,
            "Symbol": "AAPL",
            "ExitReason": "Signal",
        }
    ] if with_trades else []

    return {
        "Strategy": strategy_name,
        "Trades": len(trade_log),
        "pnl_percent": pnl_percent,
        "max_drawdown": 0.10,
        "mc_score": 50.0,
        "mc_verdict": "Robust",
        "calmar_ratio": 1.0,
        "sharpe_ratio": 1.0,
        "win_rate": 0.6,
        "profit_factor": 1.5,
        "vs_spy_benchmark": 0.05,
        "vs_qqq_benchmark": 0.03,
        "avg_trade_duration": 3.0,
        "oos_pnl_pct": 0.02,
        "wfa_verdict": "Pass",
        "expectancy": 0.5,
        "sqn": 1.2,
        "Portfolio": "Test Portfolio",
        "Asset": "MULTI",
        "trade_log": trade_log,
    }


class TestSaveOnlyFilteredTrades:
    """save_only_filtered_trades=True must honour the Step-2 display filter."""

    def _run(self, portfolio_results, config_overrides):
        """
        Call generate_per_portfolio_summary with patched I/O and return the
        mock object for save_trades_to_csv so callers can assert on it.
        """
        saved_config = {}
        for k, v in config_overrides.items():
            saved_config[k] = CONFIG.get(k)
            CONFIG[k] = v

        try:
            with (
                patch("helpers.summary.save_trades_to_csv") as mock_save,
                patch("helpers.summary.os.makedirs"),
                patch.object(pd.DataFrame, "to_csv"),
            ):
                generate_per_portfolio_summary(
                    portfolio_results=portfolio_results,
                    portfolio_name="Test Portfolio",
                    spy_return=0.10,
                    qqq_return=0.12,
                    run_id="test-run-001",
                )
                return mock_save
        finally:
            for k, orig in saved_config.items():
                if orig is None:
                    CONFIG.pop(k, None)
                else:
                    CONFIG[k] = orig

    def test_save_only_filtered_calls_save_exactly_once(self):
        """Only the strategy that passes min_pnl should be saved."""
        passing = _make_result("Good Strategy", pnl_percent=0.5)
        failing = _make_result("Bad Strategy", pnl_percent=-0.5)  # -50% < threshold

        mock_save = self._run(
            portfolio_results=[passing, failing],
            config_overrides={
                "save_individual_trades": True,
                "save_only_filtered_trades": True,
                "min_pandl_to_show_in_summary": -0.1,  # pnl_percent * 100 >= -0.1
            },
        )

        assert mock_save.call_count == 1, (
            f"Expected save_trades_to_csv to be called once, got {mock_save.call_count}"
        )

    def test_save_only_filtered_saves_the_passing_strategy(self):
        """The saved result must be the one that cleared the filter."""
        passing = _make_result("Good Strategy", pnl_percent=0.5)
        failing = _make_result("Bad Strategy", pnl_percent=-0.5)

        mock_save = self._run(
            portfolio_results=[passing, failing],
            config_overrides={
                "save_individual_trades": True,
                "save_only_filtered_trades": True,
                "min_pandl_to_show_in_summary": -0.1,
            },
        )

        saved_strategy = mock_save.call_args[0][0]["Strategy"]
        assert saved_strategy == "Good Strategy"

    def test_save_all_trades_calls_save_twice_when_flag_is_false(self):
        """When save_only_filtered_trades=False, both strategies are saved."""
        passing = _make_result("Good Strategy", pnl_percent=0.5)
        failing = _make_result("Bad Strategy", pnl_percent=-0.5)

        mock_save = self._run(
            portfolio_results=[passing, failing],
            config_overrides={
                "save_individual_trades": True,
                "save_only_filtered_trades": False,
                "min_pandl_to_show_in_summary": -0.1,
            },
        )

        assert mock_save.call_count == 2
