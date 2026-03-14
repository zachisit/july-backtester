# tests/test_regime_heatmap.py
"""
Unit tests for helpers/regime.py — VIX Regime Heatmap.

Covers:
  TestClassifyVixRegime   — boundary values, forward-fill, edge cases
  TestBuildRegimeHeatmap  — None guards, DataFrame shape, value assertions
  TestPrintRegimeHeatmap  — stdout content, None-silent
"""

import io
import os
import sys
from contextlib import redirect_stdout

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.regime import (
    ALL_REGIMES,
    REGIME_HIGH,
    REGIME_LOW,
    REGIME_MID,
    REGIME_UNK,
    build_regime_heatmap,
    classify_vix_regime,
    print_regime_heatmap,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vix_series(*pairs):
    """Build a VIX pd.Series from (date_str, value) pairs."""
    dates = [pd.Timestamp(d) for d, _ in pairs]
    values = [v for _, v in pairs]
    return pd.Series(values, index=dates, dtype=float)


def _vix_df(series):
    """Wrap a VIX series in a DataFrame with a 'Close' column."""
    return pd.DataFrame({"Close": series})


def _trade(entry_date, profit):
    return {"EntryDate": entry_date, "Profit": profit}


# ---------------------------------------------------------------------------
# TestClassifyVixRegime
# ---------------------------------------------------------------------------

class TestClassifyVixRegime:

    def test_low_vix(self):
        """VIX = 12.5 → REGIME_LOW"""
        s = _vix_series(("2023-01-03", 12.5))
        assert classify_vix_regime(s, "2023-01-03") == REGIME_LOW

    def test_mid_lower_boundary(self):
        """VIX = 15.0 (exactly at lower boundary) → REGIME_MID"""
        s = _vix_series(("2023-01-03", 15.0))
        assert classify_vix_regime(s, "2023-01-03") == REGIME_MID

    def test_mid_upper_boundary(self):
        """VIX = 25.0 (exactly at upper boundary) → REGIME_MID"""
        s = _vix_series(("2023-01-03", 25.0))
        assert classify_vix_regime(s, "2023-01-03") == REGIME_MID

    def test_high_vix(self):
        """VIX = 35.0 → REGIME_HIGH"""
        s = _vix_series(("2023-01-03", 35.0))
        assert classify_vix_regime(s, "2023-01-03") == REGIME_HIGH

    def test_forward_fill_weekend(self):
        """Friday's VIX value must forward-fill to Saturday."""
        s = _vix_series(("2023-01-06", 12.0))  # Friday
        result = classify_vix_regime(s, "2023-01-07")  # Saturday
        assert result == REGIME_LOW

    def test_none_series_returns_unknown(self):
        """None vix_series → REGIME_UNK"""
        assert classify_vix_regime(None, "2023-01-03") == REGIME_UNK

    def test_date_before_all_data_returns_unknown(self):
        """Date before the earliest data point has no prior value to ffill → REGIME_UNK"""
        s = _vix_series(("2023-06-01", 20.0))
        result = classify_vix_regime(s, "2023-01-01")
        assert result == REGIME_UNK


# ---------------------------------------------------------------------------
# TestBuildRegimeHeatmap
# ---------------------------------------------------------------------------

class TestBuildRegimeHeatmap:

    def test_returns_none_empty_trade_log(self):
        vix = _vix_df(_vix_series(("2023-01-03", 20.0)))
        assert build_regime_heatmap([], vix, 100_000) is None

    def test_returns_none_none_vix(self):
        trades = [_trade("2023-01-03", 500.0)]
        assert build_regime_heatmap(trades, None, 100_000) is None

    def test_returns_dataframe(self):
        vix = _vix_df(_vix_series(("2023-01-03", 20.0)))
        trades = [_trade("2023-01-03", 500.0)]
        result = build_regime_heatmap(trades, vix, 100_000)
        assert isinstance(result, pd.DataFrame)

    def test_all_three_columns_present(self):
        """All three regime columns must always be present even when no trades fall there."""
        vix = _vix_df(_vix_series(("2023-01-03", 20.0)))
        trades = [_trade("2023-01-03", 500.0)]
        result = build_regime_heatmap(trades, vix, 100_000)
        for col in ALL_REGIMES:
            assert col in result.columns, f"Missing column: {col}"

    def test_values_as_fraction_of_capital(self):
        """$1000 profit / $100k capital = 0.01 in the correct regime cell."""
        vix = _vix_df(_vix_series(("2023-01-03", 20.0)))  # → MID
        trades = [_trade("2023-01-03", 1_000.0)]
        result = build_regime_heatmap(trades, vix, 100_000)
        assert result.loc[2023, REGIME_MID] == pytest.approx(0.01)
        assert result.loc[2023, REGIME_LOW]  == pytest.approx(0.0)
        assert result.loc[2023, REGIME_HIGH] == pytest.approx(0.0)

    def test_multiple_years(self):
        """Trades across two years produce two index rows."""
        vix = _vix_df(_vix_series(
            ("2022-01-03", 20.0),
            ("2023-01-03", 20.0),
        ))
        trades = [
            _trade("2022-01-03", 500.0),
            _trade("2023-01-03", 750.0),
        ]
        result = build_regime_heatmap(trades, vix, 100_000)
        assert set(result.index) == {2022, 2023}

    def test_correct_regime_bucketing(self):
        """VIX=30 → value in REGIME_HIGH, zero in LOW and MID."""
        vix = _vix_df(_vix_series(("2023-01-03", 30.0)))
        trades = [_trade("2023-01-03", 2_000.0)]
        result = build_regime_heatmap(trades, vix, 100_000)
        assert result.loc[2023, REGIME_HIGH] == pytest.approx(0.02)
        assert result.loc[2023, REGIME_LOW]  == pytest.approx(0.0)
        assert result.loc[2023, REGIME_MID]  == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# TestPrintRegimeHeatmap
# ---------------------------------------------------------------------------

class TestPrintRegimeHeatmap:

    def _build_simple_heatmap(self):
        vix = _vix_df(_vix_series(("2023-01-03", 20.0)))
        trades = [_trade("2023-01-03", 1_000.0)]
        return build_regime_heatmap(trades, vix, 100_000)

    def test_produces_output(self):
        """Output must contain 'REGIME HEATMAP', the strategy name, and 'TOTAL'."""
        heatmap = self._build_simple_heatmap()
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_regime_heatmap(heatmap, "My Strategy")
        output = buf.getvalue()
        assert "REGIME HEATMAP" in output
        assert "My Strategy" in output
        assert "TOTAL" in output

    def test_none_heatmap_silent(self):
        """None heatmap must produce no output."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            print_regime_heatmap(None, "My Strategy")
        assert buf.getvalue() == ""
