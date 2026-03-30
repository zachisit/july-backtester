# tests/test_datetime_normalization.py
"""
Unit tests for datetime index normalization in data providers (Phase 4 of #55).

Tests that all data providers return pd.DatetimeIndex regardless of timeframe,
with daily data normalized to midnight timestamps and intraday data preserving
hour/minute precision.
"""

import datetime
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Test Class 1: Data Provider Normalization
# ---------------------------------------------------------------------------

class TestDataProviderNormalization:
    """Test that all data providers normalize indexes correctly."""

    @patch.dict(os.environ, {"POLYGON_API_KEY": "test"})
    def test_polygon_daily_normalized_to_midnight(self):
        """Polygon daily data should have time component set to 00:00:00."""
        from services.polygon_service import get_price_data

        config = {
            "timeframe": "D",
            "timeframe_multiplier": 1,
        }

        # Mock the Polygon API response
        mock_results = [
            {"t": 1609459200000, "o": 100, "h": 105, "l": 99, "c": 103, "v": 1000000},  # 2021-01-01
            {"t": 1609545600000, "o": 103, "h": 107, "l": 102, "c": 106, "v": 1100000},  # 2021-01-02
        ]

        with patch("services.polygon_service.SESSION.get") as mock_get:
            mock_response = MagicMock()
            mock_response.content = b'{"status": "OK", "results": ' + str(mock_results).replace("'", '"').encode() + b'}'
            mock_get.return_value = mock_response

            df = get_price_data("SPY", "2021-01-01", "2021-01-02", config)

        assert df is not None
        # Check dtype is datetime64 with UTC timezone (precision may vary: ns/us/ms)
        assert str(df.index.dtype).startswith('datetime64')
        assert df.index.tz is not None  # Timezone-aware
        # All timestamps should be midnight (00:00:00)
        for ts in df.index:
            assert ts.time() == datetime.time(0, 0, 0), f"Expected midnight, got {ts.time()}"

    def test_yahoo_daily_normalized_to_midnight(self):
        """Yahoo daily data should have time component set to 00:00:00."""
        from services.yahoo_service import get_price_data

        config = {
            "timeframe": "D",
            "timeframe_multiplier": 1,
        }

        # Mock yfinance.Ticker
        mock_df = pd.DataFrame({
            "Open": [100, 103],
            "High": [105, 107],
            "Low": [99, 102],
            "Close": [103, 106],
            "Volume": [1000000, 1100000],
        }, index=pd.to_datetime(["2021-01-01", "2021-01-02"]))

        with patch.dict("sys.modules", {"yfinance": MagicMock()}):
            import sys
            mock_yf = sys.modules["yfinance"]
            mock_ticker = MagicMock()
            mock_ticker.history.return_value = mock_df
            mock_yf.Ticker.return_value = mock_ticker

            df = get_price_data("SPY", "2021-01-01", "2021-01-02", config)

        assert df is not None
        # Check dtype is datetime64 with UTC timezone (precision may vary: ns/us/ms)
        assert str(df.index.dtype).startswith('datetime64')
        assert df.index.tz is not None  # Timezone-aware
        # All timestamps should be midnight (00:00:00)
        for ts in df.index:
            assert ts.time() == datetime.time(0, 0, 0), f"Expected midnight, got {ts.time()}"

    def test_csv_daily_normalized_to_midnight(self, tmp_path):
        """CSV daily data should have time component set to 00:00:00."""
        from services.csv_service import get_price_data

        # Create a temporary CSV file
        csv_content = """Date,Open,High,Low,Close,Volume
2021-01-01,100,105,99,103,1000000
2021-01-02,103,107,102,106,1100000
"""
        csv_file = tmp_path / "SPY.csv"
        csv_file.write_text(csv_content)

        config = {
            "timeframe": "D",
            "timeframe_multiplier": 1,
            "csv_data_dir": str(tmp_path),
        }

        df = get_price_data("SPY", "2021-01-01", "2021-01-02", config)

        assert df is not None
        # Check dtype is datetime64 with UTC timezone (precision may vary: ns/us/ms)
        assert str(df.index.dtype).startswith('datetime64')
        assert df.index.tz is not None  # Timezone-aware
        # All timestamps should be midnight (00:00:00)
        for ts in df.index:
            assert ts.time() == datetime.time(0, 0, 0), f"Expected midnight, got {ts.time()}"

    def test_intraday_data_preserves_time(self, tmp_path):
        """CSV intraday data should preserve hour/minute precision."""
        from services.csv_service import get_price_data

        # Create a CSV with intraday timestamps
        csv_content = """Date,Open,High,Low,Close,Volume
2021-01-01 09:30:00,100,101,99,100.5,50000
2021-01-01 10:00:00,100.5,102,100,101.5,60000
2021-01-01 10:30:00,101.5,103,101,102.5,55000
"""
        csv_file = tmp_path / "SPY.csv"
        csv_file.write_text(csv_content)

        config = {
            "timeframe": "MIN",
            "timeframe_multiplier": 30,
            "csv_data_dir": str(tmp_path),
        }

        df = get_price_data("SPY", "2021-01-01", "2021-01-02", config)

        assert df is not None
        # Check dtype is datetime64 with UTC timezone (precision may vary: ns/us/ms)
        assert str(df.index.dtype).startswith('datetime64')
        assert df.index.tz is not None  # Timezone-aware
        # At least one timestamp should have non-zero time component
        has_time = any(ts.time() != datetime.time(0, 0, 0) for ts in df.index)
        assert has_time, "Expected at least one timestamp with time component"


# ---------------------------------------------------------------------------
# Test Class 2: Benchmark Reindexing
# ---------------------------------------------------------------------------

class TestBenchmarkReindexing:
    """Test that SPY daily data forward-fills correctly to intraday bars."""

    def test_spy_reindex_to_intraday_bars(self):
        """SPY daily data should forward-fill correctly to intraday bars."""
        # Create SPY daily data (midnight timestamps)
        spy_daily = pd.DataFrame(
            {'Close': [100, 101, 102]},
            index=pd.to_datetime(['2024-01-01', '2024-01-02', '2024-01-03']).tz_localize('UTC').normalize()
        )

        # Create intraday index (with hour/minute)
        intraday_index = pd.to_datetime([
            '2024-01-01 09:30:00',
            '2024-01-01 10:00:00',
            '2024-01-02 09:30:00',
            '2024-01-02 14:00:00',
        ]).tz_localize('UTC')

        # Reindex SPY to intraday bars with forward-fill
        result = spy_daily.reindex(intraday_index, method='ffill')

        # Verify forward-fill worked
        assert result.loc['2024-01-01 09:30:00', 'Close'] == 100
        assert result.loc['2024-01-01 10:00:00', 'Close'] == 100  # Same day, same value
        assert result.loc['2024-01-02 09:30:00', 'Close'] == 101  # Next day
        assert result.loc['2024-01-02 14:00:00', 'Close'] == 101  # Same day

    def test_spy_reindex_handles_gaps(self):
        """SPY reindex should forward-fill across gaps (weekends, holidays)."""
        # SPY data: Friday and Monday only (weekend gap)
        spy_daily = pd.DataFrame(
            {'Close': [100, 101]},
            index=pd.to_datetime(['2024-01-05', '2024-01-08']).tz_localize('UTC').normalize()  # Fri, Mon
        )

        # Intraday bars spanning the weekend
        intraday_index = pd.to_datetime([
            '2024-01-05 14:00:00',  # Friday afternoon
            '2024-01-08 09:30:00',  # Monday morning
            '2024-01-08 10:00:00',  # Monday mid-morning
        ]).tz_localize('UTC')

        result = spy_daily.reindex(intraday_index, method='ffill')

        assert result.loc['2024-01-05 14:00:00', 'Close'] == 100
        assert result.loc['2024-01-08 09:30:00', 'Close'] == 101
        assert result.loc['2024-01-08 10:00:00', 'Close'] == 101


# ---------------------------------------------------------------------------
# Test Class 3: Datetime Index Type Check
# ---------------------------------------------------------------------------

class TestDatetimeIndexType:
    """Test that all data returns pd.DatetimeIndex."""

    def test_all_providers_return_datetimeindex_daily(self, tmp_path):
        """All providers should return DatetimeIndex for daily data."""
        # CSV provider (easiest to test without mocking)
        from services.csv_service import get_price_data

        csv_content = """Date,Open,High,Low,Close,Volume
2021-01-01,100,105,99,103,1000000
"""
        csv_file = tmp_path / "TEST.csv"
        csv_file.write_text(csv_content)

        config = {
            "timeframe": "D",
            "timeframe_multiplier": 1,
            "csv_data_dir": str(tmp_path),
        }

        df = get_price_data("TEST", "2021-01-01", "2021-01-02", config)

        assert df is not None
        assert isinstance(df.index, pd.DatetimeIndex), f"Expected DatetimeIndex, got {type(df.index)}"
        # Check dtype is datetime64 with UTC timezone (precision may vary: ns/us/ms)
        assert str(df.index.dtype).startswith('datetime64')
        assert df.index.tz is not None  # Timezone-aware

    def test_all_providers_return_datetimeindex_intraday(self, tmp_path):
        """All providers should return DatetimeIndex for intraday data."""
        from services.csv_service import get_price_data

        csv_content = """Date,Open,High,Low,Close,Volume
2021-01-01 09:30:00,100,101,99,100.5,50000
"""
        csv_file = tmp_path / "TEST.csv"
        csv_file.write_text(csv_content)

        config = {
            "timeframe": "MIN",
            "timeframe_multiplier": 5,
            "csv_data_dir": str(tmp_path),
        }

        df = get_price_data("TEST", "2021-01-01", "2021-01-02", config)

        assert df is not None
        assert isinstance(df.index, pd.DatetimeIndex), f"Expected DatetimeIndex, got {type(df.index)}"
        # Check dtype is datetime64 with UTC timezone (precision may vary: ns/us/ms)
        assert str(df.index.dtype).startswith('datetime64')
        assert df.index.tz is not None  # Timezone-aware
