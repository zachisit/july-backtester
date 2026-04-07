"""
tests/test_yahoo_service.py

Unit tests for services/yahoo_service.py.

All tests use unittest.mock — zero live network calls.

Strategy: yfinance is imported *inside* get_price_data() with a plain
``import yfinance as yf``, so Python's import machinery hits sys.modules
each call.  We patch sys.modules["yfinance"] with a MagicMock for the
duration of each test, giving us full control of what yf.Ticker().history()
returns without touching the real library at all.
"""

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_CONFIG = {
    "timeframe": "D",
    "timeframe_multiplier": 1,
    "price_adjustment": "total_return",
}


def _make_yf_df(n: int = 10, tz: str = "America/New_York") -> pd.DataFrame:
    """
    Build a minimal yfinance-style DataFrame.
    yfinance returns a tz-aware DatetimeIndex (exchange local time),
    with Title-Case column names when auto_adjust=True.
    """
    dates = pd.date_range("2023-01-03", periods=n, freq="B", tz=tz)
    data = {
        "Open":   np.linspace(100.0, 110.0, n),
        "High":   np.linspace(105.0, 115.0, n),
        "Low":    np.linspace(95.0,  105.0, n),
        "Close":  np.linspace(102.0, 112.0, n),
        "Volume": np.linspace(1_000_000, 2_000_000, n),
    }
    df = pd.DataFrame(data, index=dates)
    df.index.name = "Date"
    return df


@pytest.fixture()
def mock_yf():
    """
    Replace sys.modules["yfinance"] with a MagicMock for the test.
    Yields the mock so individual tests can configure return values.
    """
    m = MagicMock()
    with patch.dict(sys.modules, {"yfinance": m}):
        yield m


def _configure_ticker(mock_yf_module, df: pd.DataFrame | None):
    """Wire mock_yf.Ticker(symbol).history(...) to return *df*."""
    ticker_mock = MagicMock()
    mock_yf_module.Ticker.return_value = ticker_mock
    ticker_mock.history.return_value = df
    return ticker_mock


# ---------------------------------------------------------------------------
# _build_interval
# ---------------------------------------------------------------------------

class TestBuildInterval:
    """Unit tests for the internal interval-building helper."""

    def _call(self, timeframe, multiplier=1):
        from services.yahoo_service import _build_interval
        return _build_interval({"timeframe": timeframe, "timeframe_multiplier": multiplier})

    def test_daily(self):
        assert self._call("D") == "1d"

    def test_weekly(self):
        assert self._call("W") == "1wk"

    def test_monthly(self):
        assert self._call("M") == "1mo"

    def test_hourly_base(self):
        assert self._call("H") == "1h"

    def test_hourly_with_multiplier(self):
        assert self._call("H", multiplier=4) == "4h"

    def test_minute_base(self):
        assert self._call("MIN") == "1m"

    def test_minute_with_multiplier(self):
        assert self._call("MIN", multiplier=5) == "5m"

    def test_unsupported_timeframe_raises(self):
        from services.yahoo_service import _build_interval
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            _build_interval({"timeframe": "TICK", "timeframe_multiplier": 1})

    def test_daily_with_multiplier_logs_warning(self, caplog):
        """Multiplier > 1 for D/W/M falls back to base interval with a warning."""
        import logging
        from services.yahoo_service import _build_interval
        with caplog.at_level(logging.WARNING, logger="services.yahoo_service"):
            result = _build_interval({"timeframe": "D", "timeframe_multiplier": 5})
        assert result == "1d"
        assert "multiplier" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestGetPriceDataHappyPath:

    def test_returns_dataframe(self, mock_yf):
        _configure_ticker(mock_yf, _make_yf_df())
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert isinstance(result, pd.DataFrame)

    def test_canonical_columns_present(self, mock_yf):
        _configure_ticker(mock_yf, _make_yf_df())
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_index_is_datetime_index(self, mock_yf):
        _configure_ticker(mock_yf, _make_yf_df())
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert isinstance(result.index, pd.DatetimeIndex)

    def test_index_is_utc(self, mock_yf):
        _configure_ticker(mock_yf, _make_yf_df())
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert str(result.index.tz) == "UTC"

    def test_index_named_datetime(self, mock_yf):
        _configure_ticker(mock_yf, _make_yf_df())
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert result.index.name == "Datetime"

    def test_row_count_matches_fixture(self, mock_yf):
        _configure_ticker(mock_yf, _make_yf_df(n=20))
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert len(result) == 20

    def test_ohlcv_values_are_numeric(self, mock_yf):
        _configure_ticker(mock_yf, _make_yf_df())
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        for col in result.columns:
            assert pd.api.types.is_numeric_dtype(result[col]), f"{col} is not numeric"

    def test_auto_adjust_true_when_total_return(self, mock_yf):
        ticker_mock = _configure_ticker(mock_yf, _make_yf_df())
        from services import yahoo_service
        yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        _, kwargs = ticker_mock.history.call_args
        assert kwargs.get("auto_adjust") is True

    def test_auto_adjust_false_when_no_adjustment(self, mock_yf):
        ticker_mock = _configure_ticker(mock_yf, _make_yf_df())
        from services import yahoo_service
        config = {**_BASE_CONFIG, "price_adjustment": "none"}
        yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", config)
        _, kwargs = ticker_mock.history.call_args
        assert kwargs.get("auto_adjust") is False

    def test_correct_symbol_passed_to_ticker(self, mock_yf):
        _configure_ticker(mock_yf, _make_yf_df())
        from services import yahoo_service
        yahoo_service.get_price_data("MSFT", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        mock_yf.Ticker.assert_called_once_with("MSFT")

    def test_timezone_naive_index_converted_to_utc(self, mock_yf):
        """yfinance may return a tz-naive index — must be treated as UTC."""
        df = _make_yf_df()
        df.index = df.index.tz_localize(None)   # strip tz
        _configure_ticker(mock_yf, df)
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert result.index.tz is not None
        assert str(result.index.tz) == "UTC"

    def test_non_utc_timezone_converted_to_utc(self, mock_yf):
        """Any exchange-local tz must be normalised to UTC."""
        df = _make_yf_df(tz="US/Eastern")
        _configure_ticker(mock_yf, df)
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert str(result.index.tz) == "UTC"

    def test_extra_columns_stripped(self, mock_yf):
        """Dividends, Stock Splits and other extras must not appear in result."""
        df = _make_yf_df()
        df["Dividends"] = 0.0
        df["Stock Splits"] = 0.0
        _configure_ticker(mock_yf, df)
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert "Dividends" not in result.columns
        assert "Stock Splits" not in result.columns
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_lowercase_columns_normalised(self, mock_yf):
        """yfinance sometimes returns lower-case column names."""
        df = _make_yf_df()
        df.columns = [c.lower() for c in df.columns]
        _configure_ticker(mock_yf, df)
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_adj_close_mapped_to_close(self, mock_yf):
        """When auto_adjust=False, 'Adj Close' should map to 'Close'."""
        df = _make_yf_df()
        df = df.rename(columns={"Close": "Adj Close"})
        _configure_ticker(mock_yf, df)
        from services import yahoo_service
        config = {**_BASE_CONFIG, "price_adjustment": "none"}
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", config)
        assert "Close" in result.columns
        assert "Adj Close" not in result.columns


# ---------------------------------------------------------------------------
# Edge cases — no data
# ---------------------------------------------------------------------------

class TestGetPriceDataNoData:

    def test_empty_dataframe_returns_none(self, mock_yf):
        _configure_ticker(mock_yf, pd.DataFrame())
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert result is None

    def test_none_return_from_history_returns_none(self, mock_yf):
        _configure_ticker(mock_yf, None)
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert result is None


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestGetPriceDataErrors:

    def test_network_exception_returns_none(self, mock_yf):
        """Any exception from yfinance must be caught and return None."""
        ticker_mock = MagicMock()
        mock_yf.Ticker.return_value = ticker_mock
        ticker_mock.history.side_effect = ConnectionError("timeout")
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert result is None

    def test_rate_limit_exception_returns_none(self, mock_yf):
        ticker_mock = MagicMock()
        mock_yf.Ticker.return_value = ticker_mock
        ticker_mock.history.side_effect = Exception("Too Many Requests")
        from services import yahoo_service
        result = yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert result is None

    def test_error_is_logged(self, mock_yf, caplog):
        import logging
        ticker_mock = MagicMock()
        mock_yf.Ticker.return_value = ticker_mock
        ticker_mock.history.side_effect = RuntimeError("bad ticker")
        from services import yahoo_service
        with caplog.at_level(logging.ERROR, logger="services.yahoo_service"):
            yahoo_service.get_price_data("BADTICKER", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        assert "BADTICKER" in caplog.text

    def test_yfinance_not_installed_raises_import_error(self):
        """If yfinance is absent entirely, must raise ImportError."""
        saved = sys.modules.pop("yfinance", None)
        # Also remove any cached version from services module
        sys.modules.pop("services.yahoo_service", None)
        try:
            with patch.dict(sys.modules, {"yfinance": None}):
                from services import yahoo_service
                with pytest.raises(ImportError, match="yfinance"):
                    yahoo_service.get_price_data("AAPL", "2023-01-01", "2023-12-31", _BASE_CONFIG)
        finally:
            if saved is not None:
                sys.modules["yfinance"] = saved


# ---------------------------------------------------------------------------
# NOTE: Index symbol normalization tests have been moved to
# tests/test_ticker_normalizer.py which provides comprehensive coverage
# for all 4 data providers (yahoo, polygon, norgate, csv).
# ---------------------------------------------------------------------------
