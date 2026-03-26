"""
Tests for helpers/caching.py — local Parquet cache with 24h TTL.

Uses tmp_path to write real files; no mocking of I/O.
The TTL and sanitization logic are the core business rules under test.
"""

import os
import sys
import time
import pytest
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# We import the module-level helpers so we can test _sanitize_filename directly.
import helpers.caching as caching_module
from helpers.caching import _sanitize_filename, get_cached_data, set_cached_data


# ---------------------------------------------------------------------------
# _sanitize_filename
# ---------------------------------------------------------------------------

class TestSanitizeFilename:

    def test_plain_symbol_unchanged(self):
        assert _sanitize_filename("AAPL") == "AAPL"

    def test_colon_replaced(self):
        """I:VIX contains a colon that is invalid in Windows filenames."""
        assert _sanitize_filename("I:VIX") == "I_VIX"

    def test_dollar_sign_replaced(self):
        assert _sanitize_filename("$I:VIX") == "_I_VIX"

    def test_caret_replaced(self):
        assert _sanitize_filename("^VIX") == "_VIX"

    def test_dot_replaced(self):
        assert _sanitize_filename("BRK.B") == "BRK_B"

    def test_hyphen_and_underscore_preserved(self):
        assert _sanitize_filename("SYM-A_B") == "SYM-A_B"

    def test_digits_preserved(self):
        assert _sanitize_filename("ABC123") == "ABC123"


# ---------------------------------------------------------------------------
# get_cached_data / set_cached_data (round-trip with real files)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_cache_dir(tmp_path, monkeypatch):
    """Redirect CACHE_DIR to a per-test temp directory."""
    monkeypatch.setattr(caching_module, "CACHE_DIR", str(tmp_path))
    return tmp_path


def _make_df():
    return pd.DataFrame({"Close": [100.0, 101.0, 102.0]})


class TestCacheRoundTrip:

    def test_cache_miss_returns_none(self):
        result = get_cached_data("AAPL", "2020-01-01", "2021-01-01", "D", 1)
        assert result is None

    def test_set_then_get_returns_same_data(self):
        df = _make_df()
        set_cached_data(df, "AAPL", "2020-01-01", "2021-01-01", "D", 1)
        result = get_cached_data("AAPL", "2020-01-01", "2021-01-01", "D", 1)
        assert result is not None
        pd.testing.assert_frame_equal(result, df)

    def test_different_symbol_is_cache_miss(self):
        df = _make_df()
        set_cached_data(df, "AAPL", "2020-01-01", "2021-01-01", "D", 1)
        result = get_cached_data("MSFT", "2020-01-01", "2021-01-01", "D", 1)
        assert result is None

    def test_different_timeframe_is_cache_miss(self):
        df = _make_df()
        set_cached_data(df, "AAPL", "2020-01-01", "2021-01-01", "D", 1)
        result = get_cached_data("AAPL", "2020-01-01", "2021-01-01", "H", 1)
        assert result is None

    def test_different_multiplier_is_cache_miss(self):
        df = _make_df()
        set_cached_data(df, "AAPL", "2020-01-01", "2021-01-01", "MIN", 5)
        result = get_cached_data("AAPL", "2020-01-01", "2021-01-01", "MIN", 1)
        assert result is None

    def test_special_symbol_stored_and_retrieved(self):
        """Symbols like I:VIX must be sanitized but still round-trip correctly."""
        df = _make_df()
        set_cached_data(df, "I:VIX", "2020-01-01", "2021-01-01", "D", 1)
        result = get_cached_data("I:VIX", "2020-01-01", "2021-01-01", "D", 1)
        assert result is not None
        pd.testing.assert_frame_equal(result, df)

    def test_expired_cache_returns_none(self, tmp_path, monkeypatch):
        """A file older than TTL must not be returned."""
        # Set TTL to 0 hours so any file is expired
        monkeypatch.setattr(caching_module, "CACHE_TTL_HOURS", 0)
        df = _make_df()
        set_cached_data(df, "AAPL", "2020-01-01", "2021-01-01", "D", 1)
        result = get_cached_data("AAPL", "2020-01-01", "2021-01-01", "D", 1)
        assert result is None

    def test_corrupt_parquet_returns_none(self, tmp_path):
        """A corrupt cache file must be handled gracefully and return None."""
        # Write a valid file first so we know the path
        df = _make_df()
        set_cached_data(df, "AAPL", "2020-01-01", "2021-01-01", "D", 1)
        # Corrupt all .parquet files in the temp dir
        for f in tmp_path.iterdir():
            if f.suffix == ".parquet":
                f.write_bytes(b"not a valid parquet file")
        result = get_cached_data("AAPL", "2020-01-01", "2021-01-01", "D", 1)
        assert result is None
