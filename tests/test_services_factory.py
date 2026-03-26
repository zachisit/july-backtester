"""
Tests for services/__init__.py — data service factory functions.

The factory reads CONFIG["data_provider"] and returns the appropriate
callable. We patch CONFIG to control which branch executes.
No real network calls are made.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# We patch the CONFIG dict at the source used inside services/__init__.py
_CONFIG_PATH = "services.CONFIG"


class TestGetDataService:

    def test_polygon_returns_polygon_get_price_data(self):
        import services
        with patch(_CONFIG_PATH, {"data_provider": "polygon"}):
            fetcher = services.get_data_service()
        # The polygon fetcher is imported at module level; verify identity
        from services.polygon_service import get_price_data
        assert fetcher is get_price_data

    def test_yahoo_returns_yahoo_get_price_data(self):
        import services
        with patch(_CONFIG_PATH, {"data_provider": "yahoo"}):
            fetcher = services.get_data_service()
        from services.yahoo_service import get_price_data
        assert fetcher is get_price_data

    def test_csv_returns_csv_get_price_data(self):
        import services
        with patch(_CONFIG_PATH, {"data_provider": "csv"}):
            fetcher = services.get_data_service()
        from services.csv_service import get_price_data
        assert fetcher is get_price_data

    def test_unsupported_provider_raises_value_error(self):
        import services
        with patch(_CONFIG_PATH, {"data_provider": "unknown_provider"}):
            with pytest.raises(ValueError, match="Unsupported"):
                services.get_data_service()

    def test_case_insensitive_provider_name(self):
        """Provider names should be lowercased before comparison."""
        import services
        with patch(_CONFIG_PATH, {"data_provider": "POLYGON"}):
            fetcher = services.get_data_service()
        from services.polygon_service import get_price_data
        assert fetcher is get_price_data

    def test_default_provider_is_polygon(self):
        """If data_provider is missing from CONFIG, polygon is the default."""
        import services
        with patch(_CONFIG_PATH, {}):
            fetcher = services.get_data_service()
        from services.polygon_service import get_price_data
        assert fetcher is get_price_data

    def test_norgate_returns_callable(self):
        """Norgate branch imports from norgate_service — stub it to avoid missing lib."""
        import services
        mock_fetcher = MagicMock()
        with patch(_CONFIG_PATH, {"data_provider": "norgate"}):
            with patch.dict("sys.modules", {
                "services.norgate_service": MagicMock(get_price_data=mock_fetcher)
            }):
                # Re-import the module so the lazy import executes with the stub
                import importlib
                # The factory uses a local import so it will pick up the patched module
                fetcher = services.get_data_service()
        # Just verify it returned something callable
        assert callable(fetcher)


class TestGetPreviousCloseService:

    def test_polygon_returns_polygon_previous_close(self):
        import services
        with patch(_CONFIG_PATH, {"data_provider": "polygon"}):
            fetcher = services.get_previous_close_service()
        from services.polygon_service import get_previous_close_data
        assert fetcher is get_previous_close_data

    def test_non_polygon_provider_raises_value_error(self):
        import services
        with patch(_CONFIG_PATH, {"data_provider": "yahoo"}):
            with pytest.raises(ValueError, match="Unsupported"):
                services.get_previous_close_service()


class TestGetLastNBarsService:

    def test_polygon_returns_last_n_bars(self):
        import services
        with patch(_CONFIG_PATH, {"data_provider": "polygon"}):
            fetcher = services.get_last_n_bars_service()
        from services.polygon_service import get_last_n_bars
        assert fetcher is get_last_n_bars

    def test_non_polygon_provider_raises_value_error(self):
        import services
        with patch(_CONFIG_PATH, {"data_provider": "csv"}):
            with pytest.raises(ValueError, match="Unsupported"):
                services.get_last_n_bars_service()
