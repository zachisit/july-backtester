"""
Tests for services/services.py — the caching-wrapper factory.

The key contract: get_data_service() returns a `cached_fetcher` callable that:
  1. Returns cached data immediately on a cache hit.
  2. Calls the original fetcher and stores the result on a cache miss.
  3. Does NOT store None/empty results in the cache.
  4. Raises ValueError for unsupported providers.
"""

import os
import sys
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock, call

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


_CFG_PATH = "services.services.CONFIG"


def _make_df():
    return pd.DataFrame({"Close": [100.0, 101.0]})


class TestGetDataServiceFactory:

    def test_returns_callable(self):
        import services.services as svc
        with patch(_CFG_PATH, {"data_provider": "polygon"}):
            fetcher = svc.get_data_service()
        assert callable(fetcher)

    def test_unsupported_provider_raises_value_error(self):
        import services.services as svc
        with patch(_CFG_PATH, {"data_provider": "fakedb"}):
            with pytest.raises(ValueError, match="Unsupported"):
                svc.get_data_service()

    def test_returns_cached_data_without_calling_fetcher(self):
        """Cache hit: original fetcher should NOT be called."""
        import services.services as svc
        mock_original = MagicMock(return_value=_make_df())
        df_cached = _make_df()

        with patch(_CFG_PATH, {"data_provider": "polygon"}):
            with patch("services.services.get_cached_data", return_value=df_cached) as mock_cache_get:
                with patch("services.services.set_cached_data") as mock_cache_set:
                    with patch("services.polygon_service.get_price_data", mock_original):
                        fetcher = svc.get_data_service()
                        result = fetcher("AAPL", "2020-01-01", "2021-01-01",
                                         {"timeframe": "D", "timeframe_multiplier": 1})

        mock_original.assert_not_called()
        mock_cache_set.assert_not_called()
        pd.testing.assert_frame_equal(result, df_cached)

    def test_cache_miss_calls_fetcher_and_stores_result(self):
        """Cache miss: original fetcher called, result cached."""
        import services.services as svc
        fetched_df = _make_df()
        mock_original = MagicMock(return_value=fetched_df)

        with patch(_CFG_PATH, {"data_provider": "polygon"}):
            with patch("services.services.get_cached_data", return_value=None):
                with patch("services.services.set_cached_data") as mock_cache_set:
                    with patch("services.polygon_service.get_price_data", mock_original):
                        fetcher = svc.get_data_service()
                        result = fetcher("AAPL", "2020-01-01", "2021-01-01",
                                         {"timeframe": "D", "timeframe_multiplier": 1})

        mock_original.assert_called_once()
        mock_cache_set.assert_called_once()
        pd.testing.assert_frame_equal(result, fetched_df)

    def test_cache_miss_none_from_fetcher_not_stored(self):
        """If the API returns None, we must NOT try to cache it."""
        import services.services as svc
        mock_original = MagicMock(return_value=None)

        with patch(_CFG_PATH, {"data_provider": "polygon"}):
            with patch("services.services.get_cached_data", return_value=None):
                with patch("services.services.set_cached_data") as mock_cache_set:
                    with patch("services.polygon_service.get_price_data", mock_original):
                        fetcher = svc.get_data_service()
                        result = fetcher("BADTICKER", "2020-01-01", "2021-01-01",
                                         {"timeframe": "D", "timeframe_multiplier": 1})

        mock_cache_set.assert_not_called()
        assert result is None

    def test_cache_miss_empty_df_from_fetcher_not_stored(self):
        """If the API returns an empty DataFrame, it must NOT be cached."""
        import services.services as svc
        mock_original = MagicMock(return_value=pd.DataFrame())

        with patch(_CFG_PATH, {"data_provider": "polygon"}):
            with patch("services.services.get_cached_data", return_value=None):
                with patch("services.services.set_cached_data") as mock_cache_set:
                    with patch("services.polygon_service.get_price_data", mock_original):
                        fetcher = svc.get_data_service()
                        result = fetcher("AAPL", "2020-01-01", "2021-01-01",
                                         {"timeframe": "D", "timeframe_multiplier": 1})

        mock_cache_set.assert_not_called()

    def test_timeframe_and_multiplier_extracted_from_per_call_config(self):
        """The cached_fetcher must use the per-call config's timeframe, not global."""
        import services.services as svc
        fetched_df = _make_df()
        mock_original = MagicMock(return_value=fetched_df)

        captured_cache_calls = []

        def capture_set(df, sym, start, end, tf, mult):
            captured_cache_calls.append({"timeframe": tf, "multiplier": mult})

        with patch(_CFG_PATH, {"data_provider": "polygon"}):
            with patch("services.services.get_cached_data", return_value=None):
                with patch("services.services.set_cached_data", side_effect=capture_set):
                    with patch("services.polygon_service.get_price_data", mock_original):
                        fetcher = svc.get_data_service()
                        fetcher("AAPL", "2020-01-01", "2021-01-01",
                                {"timeframe": "H", "timeframe_multiplier": 4})

        assert captured_cache_calls[0]["timeframe"] == "H"
        assert captured_cache_calls[0]["multiplier"] == 4
