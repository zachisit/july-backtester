# tests/test_ml_export.py
"""
Unit tests for ML trade feature export (SECTION 20).

Covers:
  TestExportTradeFeatures — row count, column presence, Parquet I/O, CSV fallback
  TestConfigDefaults      — export_ml_features disabled by default
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import CONFIG
from helpers.ml_export import export_trade_features


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trade(symbol="AAPL", profit=100.0, is_win=1, idx=1):
    """Return a minimal trade dict matching the portfolio_simulations schema."""
    return {
        "Symbol": symbol,
        "Trade": f"Long {idx}",          # internal counter — must be dropped
        "EntryDate": "2020-01-02",
        "ExitDate":  "2020-01-15",
        "HoldDuration": 13,
        "EntryPrice": 150.0,
        "ExitPrice":  160.0 if is_win else 140.0,
        "Profit": profit,
        "ProfitPct": 0.067 if is_win else -0.067,
        "Shares": 10,
        "is_win": is_win,
        "RMultiple": 1.0 if is_win else -1.0,
        "MAE_pct": -0.01,
        "MFE_pct": 0.08,
        "ExitReason": "Signal",
        "InitialRisk": 1.50,
        "VolumeImpact_bps": 0.0,
        "entry_RSI_14": 55.3,
        "entry_SMA200_dist_pct": 0.04,
    }


def _make_result(strategy="TestStrat", portfolio="TestPort", n_trades=3):
    return {
        "Strategy":  strategy,
        "Portfolio": portfolio,
        "trade_log": [_make_trade(idx=i + 1) for i in range(n_trades)],
    }


# ---------------------------------------------------------------------------
# TestConfigDefaults
# ---------------------------------------------------------------------------

class TestConfigDefaults:

    def test_export_ml_features_default_false(self):
        """export_ml_features must be False by default — no file written in normal runs."""
        assert CONFIG["export_ml_features"] is False


# ---------------------------------------------------------------------------
# TestExportTradeFeatures
# ---------------------------------------------------------------------------

class TestExportTradeFeatures:

    def test_returns_zero_for_empty_results(self, tmp_path):
        """export_trade_features([]) must return 0 and write no file."""
        out = tmp_path / "ml_features.parquet"
        n = export_trade_features([], out)
        assert n == 0
        assert not out.exists()

    def test_row_count_matches_total_trades(self, tmp_path):
        """2 results × 3 trades each → 6 rows in the output file."""
        results = [_make_result("StratA", n_trades=3), _make_result("StratB", n_trades=3)]
        out = tmp_path / "ml_features.parquet"
        n = export_trade_features(results, out)
        assert n == 6
        df = pd.read_parquet(out)
        assert len(df) == 6

    def test_is_win_column_present(self, tmp_path):
        """is_win must be present in the output DataFrame."""
        out = tmp_path / "ml_features.parquet"
        export_trade_features([_make_result()], out)
        df = pd.read_parquet(out)
        assert "is_win" in df.columns

    def test_strategy_portfolio_columns_present(self, tmp_path):
        """Strategy and Portfolio must be injected from the result dict."""
        out = tmp_path / "ml_features.parquet"
        export_trade_features([_make_result("MyStrat", "MyPort")], out)
        df = pd.read_parquet(out)
        assert "Strategy" in df.columns
        assert "Portfolio" in df.columns
        assert (df["Strategy"] == "MyStrat").all()
        assert (df["Portfolio"] == "MyPort").all()

    def test_output_is_readable_parquet(self, tmp_path):
        """The written file must be a valid Parquet readable by pd.read_parquet."""
        out = tmp_path / "ml_features.parquet"
        export_trade_features([_make_result(n_trades=5)], out)
        assert out.exists()
        df = pd.read_parquet(out)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 5

    def test_no_trade_column_in_output(self, tmp_path):
        """The internal 'Trade' counter column must be dropped from the output."""
        out = tmp_path / "ml_features.parquet"
        export_trade_features([_make_result()], out)
        df = pd.read_parquet(out)
        assert "Trade" not in df.columns

    def test_csv_fallback_when_no_pyarrow(self, tmp_path):
        """When to_parquet raises ImportError, a .csv fallback must be written."""
        out = tmp_path / "ml_features.parquet"
        csv_out = tmp_path / "ml_features.csv"

        with patch.object(pd.DataFrame, "to_parquet", side_effect=ImportError("no pyarrow")):
            n = export_trade_features([_make_result(n_trades=4)], out)

        assert n == 4
        assert not out.exists(), "Parquet file must NOT be written on ImportError"
        assert csv_out.exists(), "CSV fallback must be written when Parquet fails"
        df = pd.read_csv(csv_out)
        assert len(df) == 4
