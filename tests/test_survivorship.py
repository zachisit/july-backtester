"""tests/test_survivorship.py

Tests for survivorship bias handling (helpers/survivorship.py).
"""

import pytest
import pandas as pd
from helpers.survivorship import (
    get_delisting_dates,
    adjust_for_survivorship,
    apply_delisting_to_timeline,
    _get_delisting_dates_norgate,
    _get_delisting_dates_polygon,
)


# ---------------------------------------------------------------------------
# Test get_delisting_dates
# ---------------------------------------------------------------------------

class TestGetDelistingDates:
    """Test the main get_delisting_dates function."""

    def test_unknown_provider_returns_empty_dict(self):
        """Unknown data provider returns empty dict with warning."""
        result = get_delisting_dates(["AAPL"], "unknown_provider", {})
        assert result == {}

    def test_yahoo_provider_returns_empty_dict(self):
        """Yahoo provider returns empty dict (not supported)."""
        result = get_delisting_dates(["AAPL"], "yahoo", {})
        assert result == {}

    def test_csv_provider_returns_empty_dict(self):
        """CSV provider returns empty dict (not supported)."""
        result = get_delisting_dates(["AAPL"], "csv", {})
        assert result == {}

    def test_norgate_provider_calls_norgate_function(self, monkeypatch):
        """Norgate provider calls _get_delisting_dates_norgate."""
        called = []
        def mock_norgate(symbols, config):
            called.append((symbols, config))
            return {"ENRON": "2001-11-28"}

        monkeypatch.setattr("helpers.survivorship._get_delisting_dates_norgate", mock_norgate)
        result = get_delisting_dates(["ENRON", "AAPL"], "norgate", {})

        assert len(called) == 1
        assert called[0][0] == ["ENRON", "AAPL"]
        assert result == {"ENRON": "2001-11-28"}

    def test_polygon_provider_calls_polygon_function(self, monkeypatch):
        """Polygon provider calls _get_delisting_dates_polygon."""
        called = []
        def mock_polygon(symbols, config):
            called.append((symbols, config))
            return {"LEHMAN": "2008-09-15"}

        monkeypatch.setattr("helpers.survivorship._get_delisting_dates_polygon", mock_polygon)
        result = get_delisting_dates(["LEHMAN"], "polygon", {})

        assert len(called) == 1
        assert result == {"LEHMAN": "2008-09-15"}


# ---------------------------------------------------------------------------
# Test _get_delisting_dates_norgate
# ---------------------------------------------------------------------------

class TestNorgateDelistingDates:
    """Test Norgate-specific delisting date fetcher."""

    def test_norgate_import_error_returns_empty_dict(self, monkeypatch):
        """When norgatedata is not installed, returns empty dict."""
        import sys
        # Remove norgatedata from sys.modules if it exists
        monkeypatch.setitem(sys.modules, "norgatedata", None)
        monkeypatch.delitem(sys.modules, "norgatedata", raising=False)

        result = _get_delisting_dates_norgate(["AAPL"], {})
        assert result == {}

    def test_norgate_delisting_date_conversion(self, monkeypatch):
        """Norgate datetime is converted to ISO string."""
        import sys
        from datetime import datetime

        # Mock norgatedata module
        class MockNorgate:
            @staticmethod
            def delistingdate(symbol):
                if symbol == "ENRON":
                    return datetime(2001, 11, 28)
                return None

        monkeypatch.setitem(sys.modules, "norgatedata", MockNorgate())

        result = _get_delisting_dates_norgate(["ENRON", "AAPL"], {})
        assert result == {"ENRON": "2001-11-28"}

    def test_norgate_handles_exceptions_gracefully(self, monkeypatch):
        """Norgate API errors are caught and symbol is skipped."""
        import sys

        class MockNorgate:
            @staticmethod
            def delistingdate(symbol):
                if symbol == "BAD":
                    raise Exception("API error")
                if symbol == "ENRON":
                    from datetime import datetime
                    return datetime(2001, 11, 28)
                return None

        monkeypatch.setitem(sys.modules, "norgatedata", MockNorgate())

        result = _get_delisting_dates_norgate(["BAD", "ENRON", "AAPL"], {})
        # BAD raises error and is skipped, ENRON succeeds, AAPL returns None
        assert result == {"ENRON": "2001-11-28"}


# ---------------------------------------------------------------------------
# Test _get_delisting_dates_polygon
# ---------------------------------------------------------------------------

class TestPolygonDelistingDates:
    """Test Polygon-specific delisting date fetcher."""

    def test_polygon_no_api_key_returns_empty_dict(self, monkeypatch):
        """When POLYGON_API_KEY is not set, returns empty dict."""
        def mock_get_secret(key):
            return None

        monkeypatch.setattr("helpers.aws_utils.get_secret", mock_get_secret)
        result = _get_delisting_dates_polygon(["AAPL"], {})
        assert result == {}

    def test_polygon_delisting_date_extracted(self, monkeypatch):
        """Polygon API response is parsed correctly."""
        def mock_get_secret(key):
            return "test_key"

        class MockResponse:
            status_code = 200
            def json(self):
                return {
                    "results": {
                        "delisted_utc": "2001-11-28T00:00:00Z"
                    }
                }

        def mock_get(url, params, timeout):
            return MockResponse()

        import requests
        monkeypatch.setattr("helpers.aws_utils.get_secret", mock_get_secret)
        monkeypatch.setattr(requests, "get", mock_get)

        result = _get_delisting_dates_polygon(["ENRON"], {"polygon_api_secret_name": "test"})
        assert result == {"ENRON": "2001-11-28"}

    def test_polygon_active_symbol_not_included(self, monkeypatch):
        """Active symbols (no delisted_utc) are not in result."""
        def mock_get_secret(key):
            return "test_key"

        class MockResponse:
            status_code = 200
            def json(self):
                return {
                    "results": {}  # No delisted_utc field
                }

        def mock_get(url, params, timeout):
            return MockResponse()

        import requests
        monkeypatch.setattr("helpers.aws_utils.get_secret", mock_get_secret)
        monkeypatch.setattr(requests, "get", mock_get)

        result = _get_delisting_dates_polygon(["AAPL"], {"polygon_api_secret_name": "test"})
        assert result == {}

    def test_polygon_rate_limit_stops_early(self, monkeypatch):
        """When rate limited, stops querying remaining symbols."""
        def mock_get_secret(key):
            return "test_key"

        call_count = [0]

        class MockResponse:
            def __init__(self, status_code):
                self.status_code = status_code

            def json(self):
                if self.status_code == 429:
                    return {}
                return {"results": {}}

        def mock_get(url, params, timeout):
            call_count[0] += 1
            if call_count[0] == 2:
                return MockResponse(429)  # Rate limit on second call
            return MockResponse(200)

        import requests
        monkeypatch.setattr("helpers.aws_utils.get_secret", mock_get_secret)
        monkeypatch.setattr(requests, "get", mock_get)

        result = _get_delisting_dates_polygon(["SYM1", "SYM2", "SYM3"], {"polygon_api_secret_name": "test"})
        # Should stop after hitting rate limit on second call
        assert call_count[0] == 2


# ---------------------------------------------------------------------------
# Test adjust_for_survivorship
# ---------------------------------------------------------------------------

class TestAdjustForSurvivorship:
    """Test trade log adjustment for delisting events."""

    def test_empty_trade_log_returns_empty(self):
        """Empty trade log returns empty with zero stats."""
        trade_log, stats = adjust_for_survivorship([], {}, 100000, "last_close")
        assert trade_log == []
        assert stats["positions_delisted"] == 0
        assert stats["total_delisting_loss"] == 0.0
        assert stats["delisting_loss_pct"] == 0.0

    def test_no_delisting_dates_no_changes(self):
        """When no symbols are delisted, trade log is unchanged."""
        trade_log = [
            {"Symbol": "AAPL", "EntryDate": "2020-01-01", "ExitDate": "2020-02-01", "Profit": 100},
        ]
        adjusted_log, stats = adjust_for_survivorship(trade_log, {}, 100000, "last_close")
        assert adjusted_log == trade_log
        assert stats["positions_delisted"] == 0

    def test_open_position_is_force_closed(self):
        """Open position is force-closed on delisting date."""
        trade_log = [
            {
                "Symbol": "ENRON",
                "EntryDate": "2001-01-01",
                "ExitDate": None,  # Still open
                "EntryPrice": 80.0,
                "Shares": 100,
                "Profit": None,
                "ProfitPct": None,
            },
        ]
        delisting_dates = {"ENRON": "2001-11-28"}

        adjusted_log, stats = adjust_for_survivorship(trade_log, delisting_dates, 100000, "last_close")

        assert len(adjusted_log) == 1
        assert adjusted_log[0]["ExitDate"] == "2001-11-28"
        assert adjusted_log[0]["ExitReason"] == "Delisting"
        assert stats["positions_delisted"] == 1

    def test_delisting_price_last_close_uses_actual_last_close(self):
        """last_close looks up the actual last close from portfolio_data."""
        import pandas as pd
        trade_log = [
            {
                "Symbol": "ENRON",
                "EntryDate": "2001-01-01",
                "ExitDate": None,
                "EntryPrice": 80.0,
                "Shares": 100,
            },
        ]
        delisting_dates = {"ENRON": "2001-11-28"}
        # Stock fell from 80 to 40 by the delisting date
        dates = pd.date_range("2001-01-01", "2001-11-28", freq="B")
        closes = [40.0] * len(dates)
        df = pd.DataFrame({"Close": closes}, index=dates)
        portfolio_data = {"ENRON": df}

        adjusted_log, stats = adjust_for_survivorship(
            trade_log, delisting_dates, 100000, "last_close",
            portfolio_data=portfolio_data,
        )

        # exit_price = 40.0 (actual last close), Profit = 100 * (40 - 80) = -4000
        assert adjusted_log[0]["ExitPrice"] == 40.0
        assert adjusted_log[0]["Profit"] == pytest.approx(-4000.0)

    def test_last_close_with_no_portfolio_data_falls_back_to_entry(self):
        """When portfolio_data is None, last_close falls back to entry price."""
        trade_log = [
            {
                "Symbol": "ENRON",
                "EntryDate": "2001-01-01",
                "ExitDate": None,
                "EntryPrice": 80.0,
                "Shares": 100,
            },
        ]
        delisting_dates = {"ENRON": "2001-11-28"}

        adjusted_log, stats = adjust_for_survivorship(
            trade_log, delisting_dates, 100000, "last_close",
            portfolio_data=None,
        )

        assert adjusted_log[0]["ExitPrice"] == 80.0
        assert adjusted_log[0]["Profit"] == pytest.approx(0.0)

    def test_last_close_with_missing_symbol_falls_back_to_entry(self):
        """When portfolio_data doesn't contain the symbol, falls back to entry price."""
        trade_log = [
            {
                "Symbol": "ENRON",
                "EntryDate": "2001-01-01",
                "ExitDate": None,
                "EntryPrice": 80.0,
                "Shares": 100,
            },
        ]
        delisting_dates = {"ENRON": "2001-11-28"}
        portfolio_data = {}  # ENRON not present

        adjusted_log, stats = adjust_for_survivorship(
            trade_log, delisting_dates, 100000, "last_close",
            portfolio_data=portfolio_data,
        )

        assert adjusted_log[0]["ExitPrice"] == 80.0

    def test_last_close_uses_price_before_delisting_date_not_after(self):
        """last_close uses the last close ON OR BEFORE the delisting date, not after."""
        import pandas as pd
        trade_log = [
            {
                "Symbol": "ENRON",
                "EntryDate": "2001-01-01",
                "ExitDate": None,
                "EntryPrice": 80.0,
                "Shares": 100,
            },
        ]
        delisting_dates = {"ENRON": "2001-06-01"}
        # Data before delisting: 40.0; data after: 5.0 (should be ignored)
        dates_before = pd.date_range("2001-01-01", "2001-06-01", freq="B")
        dates_after = pd.date_range("2001-06-02", "2001-11-01", freq="B")
        closes_before = [40.0] * len(dates_before)
        closes_after = [5.0] * len(dates_after)
        all_dates = dates_before.append(dates_after)
        all_closes = closes_before + closes_after
        df = pd.DataFrame({"Close": all_closes}, index=all_dates)
        portfolio_data = {"ENRON": df}

        adjusted_log, stats = adjust_for_survivorship(
            trade_log, delisting_dates, 100000, "last_close",
            portfolio_data=portfolio_data,
        )

        # Should use 40.0 (last close on/before 2001-06-01), not 5.0
        assert adjusted_log[0]["ExitPrice"] == pytest.approx(40.0)

    def test_delisting_price_zero_assumption(self):
        """zero assumption treats position as total loss."""
        trade_log = [
            {
                "Symbol": "ENRON",
                "EntryDate": "2001-01-01",
                "ExitDate": None,
                "EntryPrice": 80.0,
                "Shares": 100,
            },
        ]
        delisting_dates = {"ENRON": "2001-11-28"}

        adjusted_log, stats = adjust_for_survivorship(trade_log, delisting_dates, 100000, "zero")

        # Profit = Shares * (0 - 80) = 100 * (-80) = -8000
        assert adjusted_log[0]["ExitPrice"] == 0.0
        assert adjusted_log[0]["Profit"] == -8000.0
        assert stats["total_delisting_loss"] == -8000.0
        assert stats["delisting_loss_pct"] == -0.08  # -8000 / 100000

    def test_delisting_before_entry_ignored(self):
        """Delisting that happened before entry is ignored."""
        trade_log = [
            {
                "Symbol": "ENRON",
                "EntryDate": "2002-01-01",  # After delisting
                "ExitDate": None,
                "EntryPrice": 80.0,
                "Shares": 100,
            },
        ]
        delisting_dates = {"ENRON": "2001-11-28"}  # Before entry

        adjusted_log, stats = adjust_for_survivorship(trade_log, delisting_dates, 100000, "last_close")

        # Position should NOT be force-closed
        assert adjusted_log[0]["ExitDate"] is None
        assert stats["positions_delisted"] == 0

    def test_closed_position_unchanged(self):
        """Already-closed positions are not modified."""
        trade_log = [
            {
                "Symbol": "ENRON",
                "EntryDate": "2001-01-01",
                "ExitDate": "2001-10-01",  # Already closed
                "EntryPrice": 80.0,
                "ExitPrice": 50.0,
                "Shares": 100,
                "Profit": -3000,
            },
        ]
        delisting_dates = {"ENRON": "2001-11-28"}

        adjusted_log, stats = adjust_for_survivorship(trade_log, delisting_dates, 100000, "last_close")

        # Should pass through unchanged
        assert adjusted_log == trade_log
        assert stats["positions_delisted"] == 0

    def test_multiple_delistings(self):
        """Multiple delisted positions are all force-closed."""
        trade_log = [
            {"Symbol": "ENRON", "EntryDate": "2001-01-01", "ExitDate": None, "EntryPrice": 80.0, "Shares": 100},
            {"Symbol": "LEHMAN", "EntryDate": "2008-01-01", "ExitDate": None, "EntryPrice": 50.0, "Shares": 200},
            {"Symbol": "AAPL", "EntryDate": "2020-01-01", "ExitDate": None, "EntryPrice": 100.0, "Shares": 50},  # Not delisted
        ]
        delisting_dates = {"ENRON": "2001-11-28", "LEHMAN": "2008-09-15"}

        adjusted_log, stats = adjust_for_survivorship(trade_log, delisting_dates, 100000, "zero")

        # 2 positions force-closed
        assert stats["positions_delisted"] == 2
        # Total loss = (100 * 80) + (200 * 50) = 8000 + 10000 = 18000
        assert stats["total_delisting_loss"] == -18000.0
        assert stats["delisting_loss_pct"] == -0.18

    def test_delisting_loss_pct_zero_capital_guard(self):
        """When initial_capital is zero, delisting_loss_pct is zero."""
        trade_log = [
            {"Symbol": "ENRON", "EntryDate": "2001-01-01", "ExitDate": None, "EntryPrice": 80.0, "Shares": 100},
        ]
        delisting_dates = {"ENRON": "2001-11-28"}

        adjusted_log, stats = adjust_for_survivorship(trade_log, delisting_dates, 0, "zero")

        assert stats["delisting_loss_pct"] == 0.0


# ---------------------------------------------------------------------------
# Test apply_delisting_to_timeline
# ---------------------------------------------------------------------------

class TestEquityCurveRecomputation:
    """Verify apply_delisting_to_timeline correctly patches the equity curve."""

    def _make_timeline(self, start="2020-01-01", periods=10, start_value=100_000.0, step=1_000.0):
        dates = pd.date_range(start, periods=periods, freq="B")
        values = [start_value + i * step for i in range(periods)]
        return pd.Series(values, index=dates, dtype=float)

    def test_no_delisting_trades_returns_unchanged(self):
        timeline = self._make_timeline()
        original = timeline.copy()
        trade_log = [
            {"Symbol": "AAPL", "ExitDate": "2020-01-05", "ExitReason": "Rank drop", "Profit": 500.0},
        ]
        result = apply_delisting_to_timeline(timeline, trade_log)
        pd.testing.assert_series_equal(result, original)

    def test_empty_trade_log_returns_unchanged(self):
        timeline = self._make_timeline()
        original = timeline.copy()
        result = apply_delisting_to_timeline(timeline, [])
        pd.testing.assert_series_equal(result, original)

    def test_zero_profit_delisting_returns_unchanged(self):
        timeline = self._make_timeline()
        original = timeline.copy()
        trade_log = [
            {"Symbol": "ENRON", "ExitDate": "2020-01-05", "ExitReason": "Delisting", "Profit": 0.0},
        ]
        result = apply_delisting_to_timeline(timeline, trade_log)
        pd.testing.assert_series_equal(result, original)

    def test_equity_drops_at_delisting_date(self):
        # Timeline: 10 business days starting 2020-01-02, equity = 100k rising by 1k/day
        timeline = self._make_timeline(start="2020-01-02", periods=10)
        delisting_date = timeline.index[4]  # 5th bar

        trade_log = [
            {"Symbol": "ENRON", "ExitDate": str(delisting_date.date()),
             "ExitReason": "Delisting", "Profit": -5_000.0},
        ]
        result = apply_delisting_to_timeline(timeline, trade_log)

        # Before delisting date: unchanged
        pd.testing.assert_series_equal(result.iloc[:4], timeline.iloc[:4])
        # On and after delisting date: shifted down by 5000
        for val_before, val_after in zip(timeline.iloc[4:], result.iloc[4:]):
            assert val_after == pytest.approx(val_before - 5_000.0)

    def test_max_drawdown_increases_after_large_delisting_loss(self):
        # Flat equity at 100k — max drawdown before = 0
        dates = pd.date_range("2020-01-02", periods=20, freq="B")
        timeline = pd.Series([100_000.0] * 20, index=dates, dtype=float)

        # Inject a -20k delisting loss at bar 10
        delisting_date = dates[9]
        trade_log = [
            {"Symbol": "ENRON", "ExitDate": str(delisting_date.date()),
             "ExitReason": "Delisting", "Profit": -20_000.0},
        ]
        result = apply_delisting_to_timeline(timeline, trade_log)

        hwm = result.cummax()
        max_dd = ((result - hwm) / hwm).min()
        assert max_dd < -0.10, f"Expected >10% drawdown after -20k loss, got {max_dd:.2%}"

    def test_original_series_not_mutated(self):
        # apply_delisting_to_timeline must return a copy, not mutate in place
        timeline = self._make_timeline()
        original_values = timeline.values.copy()
        trade_log = [
            {"Symbol": "ENRON", "ExitDate": "2020-01-06",
             "ExitReason": "Delisting", "Profit": -10_000.0},
        ]
        apply_delisting_to_timeline(timeline, trade_log)
        assert list(timeline.values) == list(original_values), "Original series was mutated"

    def test_multiple_delistings_applied_cumulatively(self):
        dates = pd.date_range("2020-01-02", periods=10, freq="B")
        timeline = pd.Series([100_000.0] * 10, index=dates, dtype=float)

        # Two delistings at bars 3 and 7
        trade_log = [
            {"Symbol": "ENRON", "ExitDate": str(dates[2].date()),
             "ExitReason": "Delisting", "Profit": -5_000.0},
            {"Symbol": "LEHMAN", "ExitDate": str(dates[6].date()),
             "ExitReason": "Delisting", "Profit": -8_000.0},
        ]
        result = apply_delisting_to_timeline(timeline, trade_log)

        # Bars 0-1: no change
        assert result.iloc[0] == pytest.approx(100_000.0)
        assert result.iloc[1] == pytest.approx(100_000.0)
        # Bars 2-5: -5k applied
        assert result.iloc[2] == pytest.approx(95_000.0)
        assert result.iloc[5] == pytest.approx(95_000.0)
        # Bars 6-9: both -5k and -8k applied
        assert result.iloc[6] == pytest.approx(87_000.0)
        assert result.iloc[9] == pytest.approx(87_000.0)
