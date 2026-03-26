"""
Tests for services/services.py ImportError except branches.

Each provider (polygon, yahoo, csv, norgate) has a try/except ImportError block
that is only hit when the underlying service module fails to import.
We trigger these by setting the module to None in sys.modules, which causes
Python to raise ImportError when the lazy `from .X_service import ...` executes.
"""
import sys
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_data_service_with_provider(provider):
    """Call services.services.get_data_service with CONFIG patched to provider."""
    import services.services as svc
    with patch("services.services.CONFIG", {"data_provider": provider}):
        return svc.get_data_service()


# ---------------------------------------------------------------------------
# ImportError branches — service module unavailable
# ---------------------------------------------------------------------------

class TestImportErrorBranches:

    def test_polygon_import_error_raises_import_error(self):
        """If polygon_service can't be imported, raises ImportError with message."""
        import services.services as svc
        with patch("services.services.CONFIG", {"data_provider": "polygon"}):
            with patch.dict("sys.modules", {"services.polygon_service": None}):
                with pytest.raises(ImportError, match="polygon"):
                    svc.get_data_service()

    def test_yahoo_import_error_raises_import_error(self):
        """If yahoo_service can't be imported, raises ImportError with message."""
        import services.services as svc
        with patch("services.services.CONFIG", {"data_provider": "yahoo"}):
            with patch.dict("sys.modules", {"services.yahoo_service": None}):
                with pytest.raises(ImportError, match="yahoo"):
                    svc.get_data_service()

    def test_csv_import_error_raises_import_error(self):
        """If csv_service can't be imported, raises ImportError with message."""
        import services.services as svc
        with patch("services.services.CONFIG", {"data_provider": "csv"}):
            with patch.dict("sys.modules", {"services.csv_service": None}):
                with pytest.raises(ImportError, match="csv"):
                    svc.get_data_service()

    def test_norgate_import_error_raises_import_error(self):
        """If norgate_service can't be imported, raises ImportError with message."""
        import services.services as svc
        with patch("services.services.CONFIG", {"data_provider": "norgate"}):
            with patch.dict("sys.modules", {"services.norgate_service": None}):
                with pytest.raises(ImportError, match="norgate"):
                    svc.get_data_service()
