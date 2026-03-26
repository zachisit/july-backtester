"""
tests/test_regime_heatmap_branches.py

Branch coverage for helpers/regime.py — lines not hit by test_regime_heatmap.py:

  - classify_vix_regime: tz-aware vix series index (lines 59-61)
  - classify_vix_regime: tz-aware lookup timestamp (line 63)
  - classify_vix_regime: exception in try block → REGIME_UNK (line 72-73)
  - build_regime_heatmap: vix_df without 'Close' column uses first col (line 107)
  - build_regime_heatmap: trade with None entry_date skipped (line 113-114)
  - build_regime_heatmap: trade with bad entry_date (exception → continue) (117-118)
  - build_regime_heatmap: all trades skipped → rows empty → None (line 123)
"""
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch

from helpers.regime import (
    classify_vix_regime,
    build_regime_heatmap,
    REGIME_LOW, REGIME_MID, REGIME_HIGH, REGIME_UNK,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _vix_series_naive(*pairs):
    """VIX series with tz-naive DatetimeIndex."""
    dates = [pd.Timestamp(d) for d, _ in pairs]
    return pd.Series([v for _, v in pairs], index=dates, dtype=float)


def _vix_series_tz(*pairs, tz="UTC"):
    """VIX series with tz-aware DatetimeIndex."""
    dates = pd.to_datetime([d for d, _ in pairs]).tz_localize(tz)
    return pd.Series([v for _, v in pairs], index=dates, dtype=float)


def _trade(entry_date, profit):
    return {"EntryDate": entry_date, "Profit": profit}


# ---------------------------------------------------------------------------
# classify_vix_regime — tz-aware vix index (lines 59-61)
# ---------------------------------------------------------------------------

class TestClassifyVixRegimeTzAware:

    def test_tz_aware_vix_series_returns_correct_regime(self):
        """vix_series with tz-aware index → strip tz → correct regime lookup."""
        s = _vix_series_tz(("2023-01-03", 12.0))  # VIX = 12 → LOW
        result = classify_vix_regime(s, "2023-01-03")
        assert result == REGIME_LOW

    def test_tz_aware_index_mid_regime(self):
        s = _vix_series_tz(("2023-06-01", 20.0))
        result = classify_vix_regime(s, "2023-06-01")
        assert result == REGIME_MID

    def test_tz_aware_index_high_regime(self):
        s = _vix_series_tz(("2023-06-01", 30.0))
        result = classify_vix_regime(s, "2023-06-01")
        assert result == REGIME_HIGH

    def test_tz_aware_vix_with_tz_aware_date(self):
        """Both series index and date are tz-aware — both stripped."""
        s = _vix_series_tz(("2023-01-03", 8.0))
        ts = pd.Timestamp("2023-01-03", tz="UTC")
        result = classify_vix_regime(s, ts)
        assert result == REGIME_LOW

    def test_tz_aware_forward_fill_still_works(self):
        """ffill works correctly after tz-stripping."""
        s = _vix_series_tz(("2023-01-06", 30.0))  # Friday
        result = classify_vix_regime(s, "2023-01-07")  # Saturday → ffilled
        assert result == REGIME_HIGH


# ---------------------------------------------------------------------------
# classify_vix_regime — exception → REGIME_UNK (lines 72-73)
# ---------------------------------------------------------------------------

class TestClassifyVixRegimeException:

    def test_exception_in_try_returns_unknown(self):
        """Patching pd.Timestamp to raise → REGIME_UNK."""
        s = _vix_series_naive(("2023-01-03", 20.0))
        with patch("helpers.regime.pd.Timestamp", side_effect=ValueError("bad date")):
            result = classify_vix_regime(s, "2023-01-03")
        assert result == REGIME_UNK

    def test_empty_series_returns_unknown(self):
        """Empty series → early return REGIME_UNK."""
        s = pd.Series(dtype=float)
        result = classify_vix_regime(s, "2023-01-03")
        assert result == REGIME_UNK


# ---------------------------------------------------------------------------
# build_regime_heatmap — vix_df without 'Close' column (line 107)
# ---------------------------------------------------------------------------

class TestBuildRegimeHeatmapFirstColumn:

    def test_vix_df_without_close_uses_first_column(self):
        """When 'Close' not in vix_df.columns → uses first column (line 107)."""
        idx = pd.to_datetime(["2023-01-03"])
        vix_df = pd.DataFrame({"VIX": [20.0]}, index=idx)
        trades = [_trade("2023-01-03", 500.0)]
        result = build_regime_heatmap(trades, vix_df, 100_000)
        assert result is not None
        assert isinstance(result, pd.DataFrame)


# ---------------------------------------------------------------------------
# build_regime_heatmap — trade filtering branches (lines 113-118)
# ---------------------------------------------------------------------------

class TestBuildRegimeHeatmapTradeFiltering:

    def _vix_df(self, value=20.0):
        idx = pd.to_datetime(["2023-01-03", "2023-06-01"])
        return pd.DataFrame({"Close": [value, value]}, index=idx)

    def test_trade_with_none_entry_date_skipped(self):
        """EntryDate=None → skipped via `if entry_date_raw is None` (line 113-114)."""
        trades = [
            {"EntryDate": None, "Profit": 100.0},
            _trade("2023-01-03", 200.0),  # valid trade
        ]
        result = build_regime_heatmap(trades, self._vix_df(), 100_000)
        assert result is not None  # valid trade still processed

    def test_trade_with_none_profit_skipped(self):
        """Profit=None → skipped via `if ... profit is None` (line 113-114)."""
        trades = [
            {"EntryDate": "2023-01-03", "Profit": None},
            _trade("2023-06-01", 200.0),  # valid trade
        ]
        result = build_regime_heatmap(trades, self._vix_df(), 100_000)
        assert result is not None

    def test_trade_with_invalid_entry_date_skipped(self):
        """pd.Timestamp raises for unparseable date → except block hit (lines 117-118)."""
        trades = [
            {"EntryDate": "not-a-date", "Profit": 100.0},
            _trade("2023-01-03", 200.0),
        ]
        result = build_regime_heatmap(trades, self._vix_df(), 100_000)
        # Invalid trade skipped; valid trade still produces a result
        assert result is not None

    def test_all_trades_invalid_returns_none(self):
        """All trades skipped → rows is empty → returns None (line 123)."""
        trades = [
            {"EntryDate": None, "Profit": 100.0},
            {"EntryDate": "2023-01-03", "Profit": None},
        ]
        result = build_regime_heatmap(trades, self._vix_df(), 100_000)
        assert result is None

    def test_zero_initial_capital_returns_none(self):
        """initial_capital=0 → early guard returns None (line 100-101)."""
        trades = [_trade("2023-01-03", 100.0)]
        result = build_regime_heatmap(trades, self._vix_df(), 0)
        assert result is None
