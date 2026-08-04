# tests/test_futures_service.py
"""
Unit tests for services/futures_service.py — the Polygon /futures/v1 fetcher.

All network calls are mocked. Verifies the SignalDeck-derived gotchas:
  - resolution mapping (timeframe/multiplier -> Polygon resolution string)
  - window_start parsed as a NANOSECOND epoch
  - settlement_price preferred over close, but <= 0 falls back to close
  - next_url pagination re-attaches the apiKey
  - duplicate / out-of-order bars deduped and sorted
  - missing API key raises; empty results -> None
"""

import os
import sys
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from services import futures_service as fs


def _ns(date_str):
    return int(pd.Timestamp(date_str, tz="UTC").value)  # nanosecond epoch


def _resp(results, next_url=None, status="OK"):
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = {"status": status, "results": results, "next_url": next_url}
    return r


_CFG = {"timeframe": "D", "timeframe_multiplier": 1}


class TestResolution:
    @pytest.mark.parametrize("tf,mult,expected", [
        ("D", 1, "1session"), ("H", 1, "1hour"), ("H", 4, "4hour"), ("MIN", 1, "1min"),
    ])
    def test_resolution_map(self, tf, mult, expected):
        assert fs._resolution({"timeframe": tf, "timeframe_multiplier": mult}) == expected

    def test_unknown_multiplier_falls_back_to_base(self):
        assert fs._resolution({"timeframe": "D", "timeframe_multiplier": 7}) == "1session"


class TestApiKey:
    def test_missing_key_raises(self, monkeypatch):
        monkeypatch.delenv("POLYGON_API_KEY", raising=False)
        with pytest.raises(ValueError):
            fs.get_price_data("ESM6", "2023-01-01", "2023-02-01", _CFG)


class TestParsing:
    def test_nanosecond_epoch_and_settlement_price(self, monkeypatch):
        monkeypatch.setenv("POLYGON_API_KEY", "k")
        rows = [
            {"window_start": _ns("2023-01-03"), "open": 5000, "high": 5010, "low": 4990,
             "close": 5005, "settlement_price": 5006, "volume": 100},
            {"window_start": _ns("2023-01-04"), "open": 5006, "high": 5020, "low": 5000,
             "close": 5015, "settlement_price": 0, "volume": 120},  # settle<=0 -> use close
        ]
        with patch("services.futures_service.requests.get", return_value=_resp(rows)):
            df = fs.get_price_data("ESM6", "2023-01-01", "2023-02-01", _CFG)
        assert df is not None
        assert list(df.index) == [pd.Timestamp("2023-01-03", tz="UTC"),
                                  pd.Timestamp("2023-01-04", tz="UTC")]
        assert df.loc[pd.Timestamp("2023-01-03", tz="UTC"), "Close"] == 5006  # settlement preferred
        assert df.loc[pd.Timestamp("2023-01-04", tz="UTC"), "Close"] == 5015  # fell back to close

    def test_dedupe_and_sort(self, monkeypatch):
        monkeypatch.setenv("POLYGON_API_KEY", "k")
        rows = [
            {"window_start": _ns("2023-01-05"), "open": 1, "high": 1, "low": 1, "close": 20, "volume": 1},
            {"window_start": _ns("2023-01-03"), "open": 1, "high": 1, "low": 1, "close": 10, "volume": 1},
            {"window_start": _ns("2023-01-05"), "open": 1, "high": 1, "low": 1, "close": 99, "volume": 1},  # dup, keep last
        ]
        with patch("services.futures_service.requests.get", return_value=_resp(rows)):
            df = fs.get_price_data("ESM6", "2023-01-01", "2023-02-01", _CFG)
        assert df.index.is_monotonic_increasing
        assert not df.index.duplicated().any()
        assert df.loc[pd.Timestamp("2023-01-05", tz="UTC"), "Close"] == 99

    def test_empty_results_returns_none(self, monkeypatch):
        monkeypatch.setenv("POLYGON_API_KEY", "k")
        with patch("services.futures_service.requests.get", return_value=_resp([])):
            df = fs.get_price_data("ESM6", "2023-01-01", "2023-02-01", _CFG)
        assert df is None


class TestPagination:
    def test_next_url_reattaches_apikey(self, monkeypatch):
        monkeypatch.setenv("POLYGON_API_KEY", "SECRET")
        page1 = _resp([{"window_start": _ns("2023-01-03"), "open": 1, "high": 1, "low": 1,
                        "close": 10, "volume": 1}], next_url="https://api.polygon.io/futures/v1/aggs/ESM6?cursor=abc")
        page2 = _resp([{"window_start": _ns("2023-01-04"), "open": 1, "high": 1, "low": 1,
                        "close": 11, "volume": 1}], next_url=None)
        with patch("services.futures_service.requests.get", side_effect=[page1, page2]) as mock_get:
            df = fs.get_price_data("ESM6", "2023-01-01", "2023-02-01", _CFG)
        assert len(df) == 2
        assert mock_get.call_count == 2
        # Second (cursor) call must carry the apiKey even though next_url dropped it.
        _, kwargs = mock_get.call_args_list[1]
        assert kwargs["params"].get("apiKey") == "SECRET"
