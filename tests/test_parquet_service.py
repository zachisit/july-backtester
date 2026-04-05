"""
tests/test_parquet_service.py

Unit and integration tests for services/parquet_service.py.

Test matrix:
    Unit (tmp_path synthetic parquets):
        TestResolveDir         — absolute / relative / default path resolution
        TestFindParquet        — exact, case-insensitive, missing file, missing dir
        TestNormaliseColumns   — canonical casing, aliases, missing columns, extras
        TestToUtcIndex         — tz-naive → UTC, tz-aware passthrough/convert,
                                  non-DatetimeIndex, index name
        TestGetPriceData       — happy path, date filtering, None guards,
                                  NaN row dropping, missing dir

    Integration (real Norgate fixture in tests/fixtures/parquet_data/):
        TestGetPriceDataRealFixture — AAPL row count, date filter, ABNB IPO date,
                                      pre-IPO request returns None

    Regression:
        TestServiceRegistration — dead-code bug: parquet branch was unreachable
                                   because it was placed after raise ValueError()
"""

import logging
import os

import numpy as np
import pandas as pd
import pytest

from services.parquet_service import (
    _find_parquet,
    _normalise_columns,
    _resolve_dir,
    _to_utc_index,
    get_price_data,
)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_FIXTURE_DIR = os.path.join(_TESTS_DIR, "fixtures", "parquet_data")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv_df(n: int = 10, start: str = "2023-01-03", tz=None) -> pd.DataFrame:
    """Return a minimal synthetic OHLCV DataFrame with a DatetimeIndex."""
    dates = pd.date_range(start, periods=n, freq="B", tz=tz)
    data = {
        "Open":   [100.0 + i for i in range(n)],
        "High":   [105.0 + i for i in range(n)],
        "Low":    [95.0 + i for i in range(n)],
        "Close":  [102.0 + i for i in range(n)],
        "Volume": [1_000_000.0 + i * 1000 for i in range(n)],
    }
    df = pd.DataFrame(data, index=dates)
    df.index.name = "Datetime"
    return df


def _write_parquet(tmp_path, symbol: str, df: pd.DataFrame) -> None:
    """Write df to tmp_path/{SYMBOL}.parquet."""
    df.to_parquet(tmp_path / f"{symbol.upper()}.parquet")


def _config_for(tmp_path) -> dict:
    """Return a config pointing parquet_data_dir at tmp_path."""
    return {"parquet_data_dir": str(tmp_path)}


# ---------------------------------------------------------------------------
# TestResolveDir
# ---------------------------------------------------------------------------

class TestResolveDir:

    def test_default_dir_is_parquet_data(self):
        from services.parquet_service import _PROJECT_ROOT
        result = _resolve_dir({})
        assert result == os.path.join(_PROJECT_ROOT, "parquet_data")

    def test_custom_relative_dir(self):
        from services.parquet_service import _PROJECT_ROOT
        result = _resolve_dir({"parquet_data_dir": "my_data"})
        assert result == os.path.join(_PROJECT_ROOT, "my_data")

    def test_absolute_dir_returned_unchanged(self, tmp_path):
        abs_path = str(tmp_path / "absolute_data")
        assert os.path.isabs(abs_path), "tmp_path must produce an absolute path"
        result = _resolve_dir({"parquet_data_dir": abs_path})
        assert result == abs_path


# ---------------------------------------------------------------------------
# TestFindParquet
# ---------------------------------------------------------------------------

class TestFindParquet:

    def test_finds_exact_match(self, tmp_path):
        (tmp_path / "AAPL.parquet").write_bytes(b"fake")
        assert _find_parquet("AAPL", str(tmp_path)) == str(tmp_path / "AAPL.parquet")

    def test_finds_uppercase_file(self, tmp_path):
        """File on disk is UPPER.parquet, symbol arg is lower-case."""
        (tmp_path / "MSFT.parquet").write_bytes(b"fake")
        result = _find_parquet("msft", str(tmp_path))
        assert result is not None
        assert result.upper().endswith("MSFT.PARQUET")

    def test_finds_lowercase_file(self, tmp_path):
        """File on disk is lower.parquet, symbol arg is upper-case."""
        (tmp_path / "nvda.parquet").write_bytes(b"fake")
        result = _find_parquet("NVDA", str(tmp_path))
        assert result is not None

    def test_missing_symbol_returns_none(self, tmp_path):
        (tmp_path / "AAPL.parquet").write_bytes(b"fake")
        assert _find_parquet("TSLA", str(tmp_path)) is None

    def test_missing_dir_returns_none(self, tmp_path):
        nonexistent = str(tmp_path / "no_such_dir")
        assert _find_parquet("AAPL", nonexistent) is None

    def test_missing_dir_logs_warning(self, tmp_path, caplog):
        nonexistent = str(tmp_path / "no_such_dir")
        with caplog.at_level(logging.WARNING, logger="services.parquet_service"):
            _find_parquet("AAPL", nonexistent)
        assert "no_such_dir" in caplog.text


# ---------------------------------------------------------------------------
# TestNormaliseColumns
# ---------------------------------------------------------------------------

class TestNormaliseColumns:

    def _df(self, col_map: dict) -> pd.DataFrame:
        """Build a 1-row DataFrame with the given column names."""
        return pd.DataFrame({c: [1.0] for c in col_map})

    def test_canonical_columns_unchanged(self):
        df = self._df({"Open": 0, "High": 0, "Low": 0, "Close": 0, "Volume": 0})
        result = _normalise_columns(df)
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_mixed_case_renamed(self):
        df = self._df({"open": 0, "HIGH": 0, "Low": 0, "close": 0, "VOLUME": 0})
        result = _normalise_columns(df)
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_adj_close_alias(self):
        df = self._df({"Open": 0, "High": 0, "Low": 0, "Adj Close": 0, "Volume": 0})
        result = _normalise_columns(df)
        assert "Close" in result.columns
        assert "Adj Close" not in result.columns

    def test_adjusted_close_alias(self):
        df = self._df({"Open": 0, "High": 0, "Low": 0, "Adjusted Close": 0, "Volume": 0})
        result = _normalise_columns(df)
        assert "Close" in result.columns

    def test_extra_columns_dropped(self):
        df = self._df({"Open": 0, "High": 0, "Low": 0, "Close": 0, "Volume": 0, "Extra": 0})
        result = _normalise_columns(df)
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_missing_volume_returns_none(self):
        df = self._df({"Open": 0, "High": 0, "Low": 0, "Close": 0})
        result = _normalise_columns(df)
        assert result is None

    def test_missing_high_returns_none(self):
        df = self._df({"Open": 0, "Low": 0, "Close": 0, "Volume": 0})
        result = _normalise_columns(df)
        assert result is None

    def test_whitespace_in_column_names(self):
        df = pd.DataFrame({" Open ": [1.0], " High ": [2.0], " Low ": [0.5],
                           " Close ": [1.5], " Volume ": [1000.0]})
        result = _normalise_columns(df)
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]


# ---------------------------------------------------------------------------
# TestToUtcIndex
# ---------------------------------------------------------------------------

class TestToUtcIndex:

    def test_tz_naive_index_gets_utc(self):
        df = _make_ohlcv_df(5)
        assert df.index.tz is None
        result = _to_utc_index(df)
        assert result.index.tz is not None
        assert str(result.index.tz) == "UTC"

    def test_tz_aware_utc_unchanged(self):
        df = _make_ohlcv_df(5, tz="UTC")
        result = _to_utc_index(df)
        assert str(result.index.tz) == "UTC"

    def test_tz_aware_non_utc_converted(self):
        df = _make_ohlcv_df(5, tz="US/Eastern")
        result = _to_utc_index(df)
        assert str(result.index.tz) == "UTC"

    def test_non_datetimeindex_converted(self):
        df = _make_ohlcv_df(5)
        df.index = df.index.strftime("%Y-%m-%d")  # string index
        result = _to_utc_index(df)
        assert isinstance(result.index, pd.DatetimeIndex)

    def test_index_name_set_to_datetime(self):
        df = _make_ohlcv_df(5)
        df.index.name = "date"  # wrong name
        result = _to_utc_index(df)
        assert result.index.name == "Datetime"


# ---------------------------------------------------------------------------
# TestGetPriceData  (synthetic tmp_path fixtures)
# ---------------------------------------------------------------------------

class TestGetPriceData:

    def test_returns_dataframe(self, tmp_path):
        _write_parquet(tmp_path, "AAPL", _make_ohlcv_df(10))
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert isinstance(result, pd.DataFrame)

    def test_canonical_columns(self, tmp_path):
        _write_parquet(tmp_path, "AAPL", _make_ohlcv_df(10))
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_index_is_utc_datetimeindex(self, tmp_path):
        _write_parquet(tmp_path, "AAPL", _make_ohlcv_df(10))
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert isinstance(result.index, pd.DatetimeIndex)
        assert str(result.index.tz) == "UTC"

    def test_index_name_is_datetime(self, tmp_path):
        _write_parquet(tmp_path, "AAPL", _make_ohlcv_df(10))
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result.index.name == "Datetime"

    def test_date_filtering_start(self, tmp_path):
        """Rows before start_date must be excluded."""
        df = _make_ohlcv_df(20, start="2023-01-03")
        _write_parquet(tmp_path, "TEST", df)
        result = get_price_data("TEST", "2023-01-10", "2023-12-31", _config_for(tmp_path))
        assert result is not None
        assert result.index.min() >= pd.Timestamp("2023-01-10", tz="UTC")

    def test_date_filtering_end(self, tmp_path):
        """Rows after end_date must be excluded."""
        df = _make_ohlcv_df(20, start="2023-01-03")
        _write_parquet(tmp_path, "TEST", df)
        result = get_price_data("TEST", "2023-01-01", "2023-01-10", _config_for(tmp_path))
        assert result is not None
        assert result.index.max() <= pd.Timestamp("2023-01-10", tz="UTC")

    def test_out_of_range_returns_none(self, tmp_path):
        """All data before start_date — after filtering, result is None."""
        df = _make_ohlcv_df(5, start="2020-01-02")
        _write_parquet(tmp_path, "OLD", df)
        result = get_price_data("OLD", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is None

    def test_missing_symbol_returns_none(self, tmp_path):
        _write_parquet(tmp_path, "AAPL", _make_ohlcv_df(5))
        result = get_price_data("TSLA", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is None

    def test_missing_dir_returns_none(self, tmp_path):
        config = {"parquet_data_dir": str(tmp_path / "nonexistent")}
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", config)
        assert result is None

    def test_missing_column_returns_none(self, tmp_path):
        """Parquet file that lacks Volume must return None."""
        df = _make_ohlcv_df(5).drop(columns=["Volume"])
        df.to_parquet(tmp_path / "NOVEC.parquet")
        result = get_price_data("NOVEC", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is None

    def test_nan_rows_in_ohlc_dropped(self, tmp_path):
        """Rows with NaN in OHLC must be silently dropped."""
        df = _make_ohlcv_df(5)
        df.loc[df.index[2], "Close"] = float("nan")
        df.loc[df.index[3], "Open"] = float("nan")
        _write_parquet(tmp_path, "NANTEST", df)
        result = get_price_data("NANTEST", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is not None
        assert len(result) == 3  # 2 NaN rows dropped, 3 clean rows remain
        assert result["Close"].notna().all()
        assert result["Open"].notna().all()


# ---------------------------------------------------------------------------
# TestGetPriceDataRealFixture  (integration — real Norgate export slices)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.path.isdir(_FIXTURE_DIR),
    reason="Real parquet fixtures not present — run from the project root.",
)
class TestGetPriceDataRealFixture:

    _config = {"parquet_data_dir": _FIXTURE_DIR}

    def test_aapl_returns_dataframe(self):
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", self._config)
        assert isinstance(result, pd.DataFrame)
        assert not result.empty

    def test_aapl_row_count(self):
        """Fixture has 62 trading days in 2023-01-01 → 2023-03-31."""
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", self._config)
        assert len(result) == 62

    def test_aapl_date_filtering(self):
        """Only February 2023 rows returned when dates are narrowed."""
        result = get_price_data("AAPL", "2023-02-01", "2023-02-28", self._config)
        assert result is not None
        assert result.index.min() >= pd.Timestamp("2023-02-01", tz="UTC")
        assert result.index.max() <= pd.Timestamp("2023-02-28", tz="UTC")

    def test_abnb_ipo_date(self):
        """ABNB fixture starts on IPO date 2020-12-10 — no phantom pre-IPO rows."""
        result = get_price_data("ABNB", "2020-01-01", "2021-12-31", self._config)
        assert result is not None
        first_date = result.index.min().date()
        assert str(first_date) == "2020-12-10"

    def test_abnb_pre_ipo_range_returns_none(self):
        """Requesting data before ABNB IPO must return None (no rows)."""
        result = get_price_data("ABNB", "2010-01-01", "2020-01-01", self._config)
        assert result is None


# ---------------------------------------------------------------------------
# TestServiceRegistration  (regression — dead-code bug fix)
# ---------------------------------------------------------------------------

class TestServiceRegistration:
    """
    Regression tests for the bug where the 'parquet' branch in
    services/__init__.py was placed *after* the raise ValueError(),
    making it unreachable dead code.

    Before the fix, get_data_service() with data_provider="parquet"
    always raised ValueError. These tests lock in the correct behaviour.
    """

    def _get_service(self, provider: str):
        """Patch CONFIG and call get_data_service()."""
        import importlib
        import unittest.mock as mock
        import services
        with mock.patch.dict("services.__init__.__dict__", {}):
            with mock.patch("services.CONFIG", {"data_provider": provider}):
                # Re-import to pick up patched CONFIG
                import importlib
                import services as svc_mod
                # Patch at the module level used by get_data_service
                with mock.patch.object(svc_mod, "CONFIG", {"data_provider": provider}):
                    return svc_mod.get_data_service()

    def test_parquet_provider_does_not_raise(self):
        """
        REGRESSION: get_data_service() must not raise ValueError when
        data_provider is 'parquet'. Before fix, parquet branch was dead code.
        """
        import unittest.mock as mock
        import services as svc_mod
        with mock.patch.object(svc_mod, "CONFIG", {"data_provider": "parquet"}):
            try:
                fetcher = svc_mod.get_data_service()
            except ValueError as exc:
                pytest.fail(
                    f"get_data_service() raised ValueError for 'parquet' provider "
                    f"(dead-code regression): {exc}"
                )

    def test_parquet_provider_returns_callable(self):
        """The returned fetcher must be callable."""
        import unittest.mock as mock
        import services as svc_mod
        with mock.patch.object(svc_mod, "CONFIG", {"data_provider": "parquet"}):
            fetcher = svc_mod.get_data_service()
            assert callable(fetcher)

    def test_invalid_provider_still_raises(self):
        """Truly invalid providers must still raise ValueError."""
        import unittest.mock as mock
        import services as svc_mod
        with mock.patch.object(svc_mod, "CONFIG", {"data_provider": "unsupported_xyz"}):
            with pytest.raises(ValueError, match="unsupported_xyz"):
                svc_mod.get_data_service()
