# tests/test_fetch_fx_minute.py
"""
Unit tests for scripts/fetch_fx_minute.py — the cached Polygon 1-min FX fetcher.

All network calls are mocked; the cache is exercised against real files in
tmp_path. Covers:
  - pip_size() per pair family (majors / JPY crosses / XAUUSD)
  - epoch-ms timestamps -> tz-aware America/New_York index
  - next_url pagination, and that the cursor request re-attaches the apiKey
  - duplicate timestamps deduped (first wins) and out-of-order bars sorted
  - empty results -> empty DataFrame, no parquet written
  - HTTP 429 and transient RequestException are retried, then surface
  - load_pair() reads cache without touching the network, writes on miss,
    and concatenates across years
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts import fetch_fx_minute as ffm


def _ms(ts):
    """Polygon returns millisecond epochs."""
    return int(pd.Timestamp(ts, tz="UTC").value // 1_000_000)


def _bar(ts, o=1.0, h=2.0, low=0.5, c=1.5, v=10):
    return {"t": _ms(ts), "o": o, "h": h, "l": low, "c": c, "v": v}


def _resp(results, next_url=None, status_code=200):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = {"results": results, "next_url": next_url}
    r.text = ""
    return r


@pytest.fixture(autouse=True)
def _no_sleep():
    """Retry backoff must not slow the suite."""
    with patch.object(ffm.time, "sleep", return_value=None):
        yield


class TestPipSize:
    @pytest.mark.parametrize("pair,expected", [
        ("C:EURUSD", 0.0001), ("C:GBPUSD", 0.0001), ("C:AUDUSD", 0.0001),
        ("C:EURGBP", 0.0001), ("C:USDCHF", 0.0001),
    ])
    def test_majors_and_non_jpy_crosses(self, pair, expected):
        assert ffm.pip_size(pair) == expected

    @pytest.mark.parametrize("pair", ["C:USDJPY", "C:EURJPY", "C:GBPJPY",
                                      "C:AUDJPY", "C:CHFJPY"])
    def test_jpy_quoted_pairs_are_two_decimal(self, pair):
        assert ffm.pip_size(pair) == 0.01

    def test_gold_is_ten_cents(self):
        assert ffm.pip_size("C:XAUUSD") == 0.10

    def test_prefix_is_optional(self):
        assert ffm.pip_size("EURUSD") == ffm.pip_size("C:EURUSD")
        assert ffm.pip_size("USDJPY") == ffm.pip_size("C:USDJPY")


class TestPairLists:
    def test_all_pairs_is_the_union(self):
        assert ffm.ALL_PAIRS == ffm.MAJORS + ffm.CROSSES + ffm.METALS

    def test_no_duplicates(self):
        assert len(ffm.ALL_PAIRS) == len(set(ffm.ALL_PAIRS))

    def test_every_pair_is_polygon_prefixed(self):
        assert all(p.startswith("C:") for p in ffm.ALL_PAIRS)

    def test_covers_the_seven_majors(self):
        assert len(ffm.MAJORS) == 7
        assert "C:EURUSD" in ffm.MAJORS and "C:NZDUSD" in ffm.MAJORS


class TestFetchYear:
    def test_maps_columns_and_returns_ohlcv(self):
        s = MagicMock()
        s.get.return_value = _resp([_bar("2020-06-01 13:30", o=1.1, h=1.2,
                                         low=1.0, c=1.15, v=42)])
        df = ffm.fetch_year("C:EURUSD", 2020, "KEY", s)

        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df.iloc[0]["open"] == 1.1
        assert df.iloc[0]["high"] == 1.2
        assert df.iloc[0]["low"] == 1.0
        assert df.iloc[0]["close"] == 1.15
        assert df.iloc[0]["volume"] == 42

    def test_index_is_tz_aware_eastern(self):
        s = MagicMock()
        # 13:30 UTC on a summer date == 09:30 ET
        s.get.return_value = _resp([_bar("2020-06-01 13:30")])
        df = ffm.fetch_year("C:EURUSD", 2020, "KEY", s)

        assert df.index.tz is not None
        assert str(df.index.tz) == ffm.ET
        assert df.index[0].hour == 9 and df.index[0].minute == 30

    def test_follows_next_url_pagination(self):
        s = MagicMock()
        s.get.side_effect = [
            _resp([_bar("2020-06-01 13:30")], next_url="https://cursor/page2"),
            _resp([_bar("2020-06-01 13:31")]),
        ]
        df = ffm.fetch_year("C:EURUSD", 2020, "KEY", s)

        assert len(df) == 2
        assert s.get.call_count == 2

    def test_cursor_request_reattaches_api_key(self):
        """next_url carries the query but NOT the key — Polygon 401s without it."""
        s = MagicMock()
        s.get.side_effect = [
            _resp([_bar("2020-06-01 13:30")], next_url="https://cursor/page2"),
            _resp([_bar("2020-06-01 13:31")]),
        ]
        ffm.fetch_year("C:EURUSD", 2020, "SECRET", s)

        second_call = s.get.call_args_list[1]
        assert second_call.args[0] == "https://cursor/page2"
        assert second_call.kwargs["params"]["apiKey"] == "SECRET"

    def test_duplicate_timestamps_keep_first(self):
        s = MagicMock()
        s.get.return_value = _resp([
            _bar("2020-06-01 13:30", c=1.0),
            _bar("2020-06-01 13:30", c=9.9),
        ])
        df = ffm.fetch_year("C:EURUSD", 2020, "KEY", s)

        assert len(df) == 1
        assert df.iloc[0]["close"] == 1.0

    def test_out_of_order_bars_are_sorted(self):
        s = MagicMock()
        s.get.return_value = _resp([
            _bar("2020-06-01 13:32", c=3.0),
            _bar("2020-06-01 13:30", c=1.0),
            _bar("2020-06-01 13:31", c=2.0),
        ])
        df = ffm.fetch_year("C:EURUSD", 2020, "KEY", s)

        assert df.index.is_monotonic_increasing
        assert list(df["close"]) == [1.0, 2.0, 3.0]

    def test_no_results_returns_empty_frame(self):
        s = MagicMock()
        s.get.return_value = _resp([])
        df = ffm.fetch_year("C:XAUUSD", 2012, "KEY", s)

        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_null_results_field_returns_empty_frame(self):
        s = MagicMock()
        s.get.return_value = _resp(None)
        assert ffm.fetch_year("C:XAUUSD", 2012, "KEY", s).empty

    def test_rate_limit_is_retried_then_succeeds(self):
        s = MagicMock()
        s.get.side_effect = [
            _resp([], status_code=429),
            _resp([_bar("2020-06-01 13:30")]),
        ]
        df = ffm.fetch_year("C:EURUSD", 2020, "KEY", s)

        assert len(df) == 1
        assert s.get.call_count == 2

    @pytest.mark.parametrize("status_code", [500, 502, 503, 504])
    def test_transient_5xx_is_retried_then_succeeds(self, status_code):
        s = MagicMock()
        s.get.side_effect = [
            _resp([], status_code=status_code),
            _resp([_bar("2020-06-01 13:30")]),
        ]
        df = ffm.fetch_year("C:EURUSD", 2020, "KEY", s)

        assert len(df) == 1
        assert s.get.call_count == 2

    def test_transient_network_error_is_retried(self):
        s = MagicMock()
        s.get.side_effect = [
            requests.RequestException("connection reset"),
            _resp([_bar("2020-06-01 13:30")]),
        ]
        df = ffm.fetch_year("C:EURUSD", 2020, "KEY", s)

        assert len(df) == 1
        assert s.get.call_count == 2

    def test_persistent_failure_raises(self):
        s = MagicMock()
        s.get.side_effect = requests.RequestException("down")
        with pytest.raises(RuntimeError, match="repeated request failures"):
            ffm.fetch_year("C:EURUSD", 2020, "KEY", s)

    def test_persistent_5xx_raises_with_status_code(self):
        s = MagicMock()
        s.get.return_value = _resp([], status_code=503)
        with pytest.raises(RuntimeError, match="HTTP 503"):
            ffm.fetch_year("C:EURUSD", 2020, "KEY", s)

        assert s.get.call_count == 5

    def test_non_200_raises(self):
        s = MagicMock()
        s.get.return_value = _resp([], status_code=403)
        with pytest.raises(RuntimeError, match="HTTP 403"):
            ffm.fetch_year("C:EURUSD", 2020, "KEY", s)

        assert s.get.call_count == 1


class TestLoadPair:
    def test_writes_parquet_on_miss(self, tmp_path):
        s = MagicMock()
        s.get.return_value = _resp([_bar("2020-06-01 13:30")])
        with patch.object(ffm.requests, "Session", return_value=s):
            df = ffm.load_pair("C:EURUSD", 2020, 2020, str(tmp_path), api_key="KEY")

        assert len(df) == 1
        assert (tmp_path / "C_EURUSD_2020.parquet").exists()

    def test_cache_hit_does_not_hit_the_network(self, tmp_path):
        s = MagicMock()
        s.get.return_value = _resp([_bar("2020-06-01 13:30")])
        with patch.object(ffm.requests, "Session", return_value=s):
            ffm.load_pair("C:EURUSD", 2020, 2020, str(tmp_path), api_key="KEY")
            calls_after_first = s.get.call_count
            df = ffm.load_pair("C:EURUSD", 2020, 2020, str(tmp_path), api_key="KEY")

        assert s.get.call_count == calls_after_first  # no further requests
        assert len(df) == 1

    def test_concatenates_across_years_in_order(self, tmp_path):
        s = MagicMock()
        s.get.side_effect = [
            _resp([_bar("2021-06-01 13:30", c=2.0)]),   # 2020 slot fetched first...
            _resp([_bar("2020-06-01 13:30", c=1.0)]),   # ...but returned out of order
        ]
        with patch.object(ffm.requests, "Session", return_value=s):
            df = ffm.load_pair("C:EURUSD", 2020, 2021, str(tmp_path), api_key="KEY")

        assert len(df) == 2
        assert df.index.is_monotonic_increasing
        assert list(df["close"]) == [1.0, 2.0]

    def test_empty_year_is_skipped_and_not_cached(self, tmp_path):
        """C:XAUUSD genuinely has no 1-min data for 2012."""
        s = MagicMock()
        s.get.side_effect = [
            _resp([]),
            _resp([_bar("2013-06-01 13:30")]),
        ]
        with patch.object(ffm.requests, "Session", return_value=s):
            df = ffm.load_pair("C:XAUUSD", 2012, 2013, str(tmp_path), api_key="KEY")

        assert len(df) == 1
        assert not (tmp_path / "C_XAUUSD_2012.parquet").exists()
        assert (tmp_path / "C_XAUUSD_2013.parquet").exists()

    def test_all_years_empty_returns_empty_frame(self, tmp_path):
        s = MagicMock()
        s.get.return_value = _resp([])
        with patch.object(ffm.requests, "Session", return_value=s):
            df = ffm.load_pair("C:XAUUSD", 2012, 2012, str(tmp_path), api_key="KEY")

        assert df.empty

    def test_creates_cache_dir_if_absent(self, tmp_path):
        target = tmp_path / "nested" / "cache"
        s = MagicMock()
        s.get.return_value = _resp([_bar("2020-06-01 13:30")])
        with patch.object(ffm.requests, "Session", return_value=s):
            ffm.load_pair("C:EURUSD", 2020, 2020, str(target), api_key="KEY")

        assert target.is_dir()

    def test_supplied_api_key_bypasses_secret_lookup(self, tmp_path):
        s = MagicMock()
        s.get.return_value = _resp([_bar("2020-06-01 13:30")])
        with patch.object(ffm.requests, "Session", return_value=s), \
             patch.object(ffm, "get_secret", side_effect=AssertionError("must not resolve")):
            ffm.load_pair("C:EURUSD", 2020, 2020, str(tmp_path), api_key="KEY")

    def test_cached_roundtrip_preserves_tz(self, tmp_path):
        s = MagicMock()
        s.get.return_value = _resp([_bar("2020-06-01 13:30")])
        with patch.object(ffm.requests, "Session", return_value=s):
            ffm.load_pair("C:EURUSD", 2020, 2020, str(tmp_path), api_key="KEY")
            cached = ffm.load_pair("C:EURUSD", 2020, 2020, str(tmp_path), api_key="KEY")

        assert str(cached.index.tz) == ffm.ET
        assert cached.index[0].hour == 9 and cached.index[0].minute == 30
