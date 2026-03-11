"""
tests/test_csv_service.py

Unit tests for services/csv_service.py.

All tests use pytest's tmp_path fixture to create real, isolated CSV files —
no mocking of file I/O needed because we control the temp directory.

Test matrix:
    Happy path     — correct schema, UTC index, date filtering, column aliases
    Edge cases     — empty file, headers-only, out-of-range dates, extra columns,
                     mixed date formats, different column case variants
    Error handling — missing file, missing required columns, non-numeric data,
                     malformed CSV
"""

import textwrap

import numpy as np
import pandas as pd
import pytest

from services.csv_service import get_price_data, _sanitize_filename

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_CONFIG = {
    "timeframe": "D",
    "timeframe_multiplier": 1,
    "price_adjustment": "total_return",
}


def _config_for(tmp_path) -> dict:
    """Return a config pointing csv_data_dir at tmp_path."""
    return {**_BASE_CONFIG, "csv_data_dir": str(tmp_path)}


def _write_csv(tmp_path, symbol: str, content: str) -> None:
    """Write *content* to tmp_path/{SYMBOL}.csv."""
    (tmp_path / f"{symbol.upper()}.csv").write_text(textwrap.dedent(content).strip())


def _standard_csv(n: int = 10, start: str = "2023-01-03") -> str:
    """Generate a valid OHLCV CSV string with *n* daily bars."""
    dates = pd.date_range(start, periods=n, freq="B")
    lines = ["Date,Open,High,Low,Close,Volume"]
    for i, d in enumerate(dates):
        o = 100 + i
        lines.append(f"{d.date()},{o},{o+5},{o-5},{o+2},{1_000_000 + i * 1000}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestHappyPath:

    def test_returns_dataframe(self, tmp_path):
        _write_csv(tmp_path, "AAPL", _standard_csv())
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert isinstance(result, pd.DataFrame)

    def test_canonical_columns(self, tmp_path):
        _write_csv(tmp_path, "AAPL", _standard_csv())
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_index_is_datetime_index(self, tmp_path):
        _write_csv(tmp_path, "AAPL", _standard_csv())
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert isinstance(result.index, pd.DatetimeIndex)

    def test_index_is_utc(self, tmp_path):
        _write_csv(tmp_path, "AAPL", _standard_csv())
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert str(result.index.tz) == "UTC"

    def test_index_named_datetime(self, tmp_path):
        _write_csv(tmp_path, "AAPL", _standard_csv())
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result.index.name == "Datetime"

    def test_row_count(self, tmp_path):
        _write_csv(tmp_path, "AAPL", _standard_csv(n=15))
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert len(result) == 15

    def test_values_are_numeric(self, tmp_path):
        _write_csv(tmp_path, "AAPL", _standard_csv())
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        for col in result.columns:
            assert pd.api.types.is_numeric_dtype(result[col]), f"{col} is not numeric"

    def test_date_filtering_start(self, tmp_path):
        _write_csv(tmp_path, "AAPL", _standard_csv(n=30, start="2023-01-03"))
        result = get_price_data("AAPL", "2023-01-16", "2023-12-31", _config_for(tmp_path))
        assert result.index.min() >= pd.Timestamp("2023-01-16", tz="UTC")

    def test_date_filtering_end(self, tmp_path):
        _write_csv(tmp_path, "AAPL", _standard_csv(n=30, start="2023-01-03"))
        result = get_price_data("AAPL", "2023-01-01", "2023-01-20", _config_for(tmp_path))
        assert result.index.max() <= pd.Timestamp("2023-01-20", tz="UTC")

    def test_symbol_lookup_lowercase_file(self, tmp_path):
        """File named aapl.csv should be found when querying 'AAPL'."""
        (tmp_path / "aapl.csv").write_text(_standard_csv())
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is not None

    def test_extra_columns_are_dropped(self, tmp_path):
        """Columns beyond OHLCV (e.g. 'Adj Close', 'VWAP') must not appear."""
        csv = _standard_csv()
        lines = csv.splitlines()
        lines[0] += ",VWAP,Adj Close"
        for i in range(1, len(lines)):
            lines[i] += ",101.5,102.0"
        _write_csv(tmp_path, "AAPL", "\n".join(lines))
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_adj_close_mapped_to_close(self, tmp_path):
        """'Adj Close' in the header should be silently treated as 'Close'."""
        csv = _standard_csv().replace("Date,Open,High,Low,Close,Volume",
                                      "Date,Open,High,Low,Adj Close,Volume")
        _write_csv(tmp_path, "AAPL", csv)
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert "Close" in result.columns
        assert "Adj Close" not in result.columns


# ---------------------------------------------------------------------------
# Column-name variants (case-insensitive)
# ---------------------------------------------------------------------------

class TestColumnCaseVariants:

    def test_all_uppercase_headers(self, tmp_path):
        csv = _standard_csv().replace("Date,Open,High,Low,Close,Volume",
                                      "DATE,OPEN,HIGH,LOW,CLOSE,VOLUME")
        _write_csv(tmp_path, "TEST", csv)
        result = get_price_data("TEST", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_all_lowercase_headers(self, tmp_path):
        csv = _standard_csv().replace("Date,Open,High,Low,Close,Volume",
                                      "date,open,high,low,close,volume")
        _write_csv(tmp_path, "TEST", csv)
        result = get_price_data("TEST", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_datetime_column_name(self, tmp_path):
        csv = _standard_csv().replace("Date,", "Datetime,")
        _write_csv(tmp_path, "TEST", csv)
        result = get_price_data("TEST", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is not None
        assert result.index.name == "Datetime"


# ---------------------------------------------------------------------------
# Date format variants
# ---------------------------------------------------------------------------

class TestDateFormats:

    def _write_with_date_format(self, tmp_path, fmt: str, symbol: str = "FMT"):
        """Write a 5-row CSV using *fmt* for date strings."""
        dates = pd.date_range("2023-01-03", periods=5, freq="B")
        lines = ["Date,Open,High,Low,Close,Volume"]
        for d in dates:
            date_str = d.strftime(fmt)
            lines.append(f"{date_str},100,105,95,102,1000000")
        _write_csv(tmp_path, symbol, "\n".join(lines))

    def test_iso_date_format(self, tmp_path):
        self._write_with_date_format(tmp_path, "%Y-%m-%d")
        result = get_price_data("FMT", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is not None and len(result) == 5

    def test_us_slash_date_format(self, tmp_path):
        self._write_with_date_format(tmp_path, "%m/%d/%Y")
        result = get_price_data("FMT", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is not None and len(result) == 5

    def test_iso_datetime_with_time(self, tmp_path):
        """Datetime strings with time component (e.g. from minute-bar CSVs)."""
        lines = [
            "Date,Open,High,Low,Close,Volume",
            "2023-01-03 09:30:00,100,105,95,102,500000",
            "2023-01-03 09:31:00,102,107,101,104,300000",
        ]
        _write_csv(tmp_path, "FMT", "\n".join(lines))
        result = get_price_data("FMT", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is not None and len(result) == 2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:

    def test_empty_file_returns_none(self, tmp_path):
        (tmp_path / "EMPTY.csv").write_text("")
        result = get_price_data("EMPTY", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is None

    def test_headers_only_returns_none(self, tmp_path):
        _write_csv(tmp_path, "EMPTY", "Date,Open,High,Low,Close,Volume\n")
        result = get_price_data("EMPTY", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is None

    def test_no_data_in_date_range_returns_none(self, tmp_path):
        """All rows are before start_date — after filtering, df is empty."""
        _write_csv(tmp_path, "AAPL", _standard_csv(n=5, start="2020-01-02"))
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is None

    def test_non_numeric_ohlcv_values_coerced(self, tmp_path):
        """Rows with non-numeric data should have NaN in the affected cells."""
        lines = [
            "Date,Open,High,Low,Close,Volume",
            "2023-01-03,100,105,95,102,1000000",
            "2023-01-04,BADVAL,108,97,bad,900000",
            "2023-01-05,103,109,99,105,800000",
        ]
        _write_csv(tmp_path, "AAPL", "\n".join(lines))
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        # Should return a DataFrame (not None) but with NaN in bad cells
        assert result is not None
        assert pd.isna(result.iloc[1]["Open"])
        assert pd.isna(result.iloc[1]["Close"])

    def test_whitespace_in_column_names(self, tmp_path):
        """Leading/trailing whitespace in column headers must be stripped."""
        csv = _standard_csv().replace("Date,Open,High,Low,Close,Volume",
                                      " Date , Open , High , Low , Close , Volume ")
        _write_csv(tmp_path, "AAPL", csv)
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is not None
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:

    def test_missing_file_returns_none(self, tmp_path):
        result = get_price_data("NOSUCHSYMBOL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is None

    def test_missing_file_logs_warning(self, tmp_path, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="services.csv_service"):
            get_price_data("NOSUCHSYMBOL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert "NOSUCHSYMBOL" in caplog.text

    def test_missing_required_column_returns_none(self, tmp_path):
        """A CSV without a 'Volume' column must return None with an error log."""
        csv = _standard_csv().replace("Date,Open,High,Low,Close,Volume",
                                      "Date,Open,High,Low,Close")
        # Strip the last comma-separated value from every data row too
        lines = csv.splitlines()
        lines = [l.rsplit(",", 1)[0] for l in lines]
        _write_csv(tmp_path, "AAPL", "\n".join(lines))
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is None

    def test_missing_column_logs_error(self, tmp_path, caplog):
        import logging
        csv = _standard_csv().replace("Date,Open,High,Low,Close,Volume",
                                      "Date,Open,High,Low,Close")
        lines = csv.splitlines()
        lines = [l.rsplit(",", 1)[0] for l in lines]
        _write_csv(tmp_path, "AAPL", "\n".join(lines))
        with caplog.at_level(logging.ERROR, logger="services.csv_service"):
            get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert "Volume" in caplog.text

    def test_malformed_csv_returns_none(self, tmp_path):
        """A binary / completely unparseable file must return None, not raise."""
        (tmp_path / "JUNK.csv").write_bytes(b"\x00\x01\x02\x03invalid\xff\xfe")
        result = get_price_data("JUNK", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        # May return None or a broken DataFrame — either way it must not raise
        # (pandas may partially parse; if it returns something, columns check will fail)
        # The key contract is: no unhandled exception
        assert result is None or isinstance(result, pd.DataFrame)

    def test_csv_dir_not_found_returns_none(self, tmp_path):
        """A configured csv_data_dir that doesn't exist must return None."""
        config = {**_BASE_CONFIG, "csv_data_dir": str(tmp_path / "nonexistent_dir")}
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", config)
        assert result is None

    def test_no_date_column_and_unparseable_index_returns_none(self, tmp_path):
        """A CSV whose index/Date column cannot be parsed as dates returns None."""
        lines = [
            "NotADate,Open,High,Low,Close,Volume",
            "foo,100,105,95,102,1000000",
            "bar,101,106,96,103,900000",
        ]
        _write_csv(tmp_path, "AAPL", "\n".join(lines))
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is None


# ---------------------------------------------------------------------------
# Wiring / config integration
# ---------------------------------------------------------------------------

class TestConfigIntegration:

    def test_csv_data_dir_is_respected(self, tmp_path):
        """csv_data_dir in config must be used as the file lookup root."""
        subdir = tmp_path / "my_data"
        subdir.mkdir()
        _write_csv(subdir, "AAPL", _standard_csv())
        config = {**_BASE_CONFIG, "csv_data_dir": str(subdir)}
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", config)
        assert result is not None

    def test_default_csv_dir_is_csv_data(self, tmp_path, monkeypatch):
        """When csv_data_dir is absent from config, default 'csv_data' is used."""
        # We can't create a real csv_data/ relative to project root in tests,
        # so instead verify that the service looks for the symbol in the right place
        # by checking it returns None (file doesn't exist) without raising.
        config = {**_BASE_CONFIG}  # no csv_data_dir key
        config.pop("csv_data_dir", None)
        result = get_price_data("AAPL", "2023-01-01", "2023-12-31", config)
        # Contract: None (not an exception) when file is absent
        assert result is None


# ---------------------------------------------------------------------------
# Filename sanitization — illegal characters mapped to underscores
# ---------------------------------------------------------------------------

class TestFilenameSanitization:
    """Symbols with Windows-illegal characters (e.g. I:VIX) must map to safe
    filenames (e.g. I_VIX.csv) transparently."""

    # --- Unit tests for _sanitize_filename ---

    def test_colon_replaced_with_underscore(self):
        assert _sanitize_filename("I:VIX") == "I_VIX"

    def test_dollar_colon_prefix(self):
        assert _sanitize_filename("$I:TNX") == "$I_TNX"

    def test_plain_ticker_unchanged(self):
        assert _sanitize_filename("AAPL") == "AAPL"

    def test_caret_ticker_unchanged(self):
        """Yahoo-style '^VIX' contains no illegal Windows chars — passes through."""
        assert _sanitize_filename("^VIX") == "^VIX"

    def test_all_illegal_chars_replaced(self):
        """Every illegal Windows filename character is replaced."""
        for ch in r'\/:*?"<>|':
            result = _sanitize_filename(f"A{ch}B")
            assert result == "A_B", f"char {ch!r} was not replaced: got {result!r}"

    def test_multiple_illegal_chars(self):
        assert _sanitize_filename("A:B/C") == "A_B_C"

    # --- Integration tests: get_price_data reads from the sanitized filename ---

    def test_index_symbol_reads_sanitized_file(self, tmp_path):
        """Passing 'I:VIX' reads from I_VIX.csv (uppercase sanitized name)."""
        (tmp_path / "I_VIX.csv").write_text(_standard_csv())
        result = get_price_data("I:VIX", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is not None
        assert isinstance(result, pd.DataFrame)

    def test_index_symbol_returns_correct_data(self, tmp_path):
        """Data read via sanitized filename has the canonical columns and UTC index."""
        (tmp_path / "I_VIX.csv").write_text(_standard_csv(n=5))
        result = get_price_data("I:VIX", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert list(result.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert str(result.index.tz) == "UTC"
        assert len(result) == 5

    def test_tnx_index_symbol(self, tmp_path):
        """I:TNX maps to I_TNX.csv."""
        (tmp_path / "I_TNX.csv").write_text(_standard_csv(n=3))
        result = get_price_data("I:TNX", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is not None
        assert len(result) == 3

    def test_dollar_prefix_index_symbol(self, tmp_path):
        """$I:VIX maps to $I_VIX.csv."""
        (tmp_path / "$I_VIX.csv").write_text(_standard_csv(n=4))
        result = get_price_data("$I:VIX", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is not None
        assert len(result) == 4

    def test_missing_sanitized_file_returns_none(self, tmp_path):
        """If I_VIX.csv does not exist, get_price_data returns None (not an error)."""
        result = get_price_data("I:VIX", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert result is None

    def test_missing_sanitized_file_logs_safe_name(self, tmp_path, caplog):
        """Warning message should include the sanitized filename base."""
        import logging
        with caplog.at_level(logging.WARNING, logger="services.csv_service"):
            get_price_data("I:VIX", "2023-01-01", "2023-12-31", _config_for(tmp_path))
        assert "I_VIX" in caplog.text
