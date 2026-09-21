"""
Regression tests for issue #315 — the cache read path discarded any entry whose
first bar lagged the *requested* start by > 30 days.

The cache is keyed by the requested start (it is in the filename), so a fixed
request always maps to the same file. A first bar later than the requested start
means EITHER the symbol listed after `start` (an IPO — re-fetching returns the
identical first bar) OR provider plan-capping — indistinguishable from the cache
alone. The old heuristic discarded both, so every late-listed symbol was
re-fetched from the API on EVERY run (a broad 2004 PIT universe re-fetches all of
its post-2004 listings each time). A genuine plan upgrade is recovered by the 24h
TTL, so the request-lag invalidation is removed.
"""

import numpy as np
import pandas as pd
import pytest

import helpers.caching as caching


@pytest.fixture
def tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(caching, "CACHE_DIR", str(tmp_path))
    return tmp_path


def _df(start_index, n=250):
    idx = pd.date_range(start_index, periods=n, freq="D", tz="UTC")
    close = np.linspace(100.0, 120.0, n)
    return pd.DataFrame(
        {"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1e6},
        index=idx,
    )


def test_late_listed_symbol_is_not_discarded(tmp_cache):
    # Requested 2004; symbol's data starts 2020 (listed 2020). The cache must be
    # SERVED, not discarded — re-fetching would return the same 2020 first bar.
    df = _df("2020-01-01")
    caching.set_cached_data(df, "ABNB", "2004-01-01", "2024-01-01", "day", 1)
    out = caching.get_cached_data("ABNB", "2004-01-01", "2024-01-01", "day", 1)
    assert out is not None, "late-listed symbol was wrongly discarded (issue #315)"
    assert out.index.min() == pd.Timestamp("2020-01-01", tz="UTC")


def test_data_covering_the_request_is_served(tmp_cache):
    df = _df("2004-01-05")  # within a few days of the request
    caching.set_cached_data(df, "SPY", "2004-01-01", "2024-01-01", "day", 1)
    out = caching.get_cached_data("SPY", "2004-01-01", "2024-01-01", "day", 1)
    assert out is not None
    assert len(out) == len(df)


def test_missing_file_is_a_cache_miss(tmp_cache):
    assert caching.get_cached_data("NONE", "2004-01-01", "2024-01-01", "day", 1) is None


def test_expired_ttl_is_a_cache_miss(tmp_cache, monkeypatch):
    df = _df("2020-01-01")
    caching.set_cached_data(df, "ABNB", "2004-01-01", "2024-01-01", "day", 1)
    # Force the file's mtime to > TTL ago.
    import os
    from datetime import datetime, timedelta
    fp = os.path.join(str(tmp_cache), "ABNB_2004-01-01_2024-01-01_day_1.parquet")
    old = (datetime.now() - timedelta(hours=caching.CACHE_TTL_HOURS + 1)).timestamp()
    os.utime(fp, (old, old))
    assert caching.get_cached_data("ABNB", "2004-01-01", "2024-01-01", "day", 1) is None


def test_tz_naive_cache_index_is_served(tmp_cache):
    idx = pd.date_range("2020-01-01", periods=100, freq="D")  # tz-naive
    df = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0,
                       "Volume": 1e6}, index=idx)
    caching.set_cached_data(df, "TZN", "2004-01-01", "2024-01-01", "day", 1)
    out = caching.get_cached_data("TZN", "2004-01-01", "2024-01-01", "day", 1)
    assert out is not None and len(out) == 100


def test_non_datetime_index_is_discarded(tmp_cache):
    # A parquet with a RangeIndex (e.g. dropped in by hand) must be treated as a
    # miss, not served into the engine (would break prev_trading_dates etc.).
    df = pd.DataFrame({"Close": [1.0, 2.0, 3.0]})  # default RangeIndex
    import os
    fp = os.path.join(str(tmp_cache), "BAD_2004-01-01_2024-01-01_day_1.parquet")
    df.to_parquet(fp)
    assert caching.get_cached_data("BAD", "2004-01-01", "2024-01-01", "day", 1) is None


def test_corrupt_file_is_a_cache_miss(tmp_cache):
    import os
    fp = os.path.join(str(tmp_cache), "JUNK_2004-01-01_2024-01-01_day_1.parquet")
    with open(fp, "wb") as fh:
        fh.write(b"not a parquet file")
    assert caching.get_cached_data("JUNK", "2004-01-01", "2024-01-01", "day", 1) is None


def test_large_lag_logs_info_not_warning(tmp_cache, caplog):
    import logging
    df = _df("2020-01-01")
    caching.set_cached_data(df, "ABNB", "2004-01-01", "2024-01-01", "day", 1)
    with caplog.at_level(logging.INFO, logger="helpers.caching"):
        out = caching.get_cached_data("ABNB", "2004-01-01", "2024-01-01", "day", 1)
    assert out is not None
    msgs = [r for r in caplog.records if "days after requested" in r.message]
    assert msgs and all(r.levelno == logging.INFO for r in msgs)
    # The old code discarded with a WARNING; make sure that's gone.
    assert not any("STALE" in r.message for r in caplog.records)


class TestCachedFetcherWriteInvariants:
    """The safety argument for removing the invalidation rests on set_cached_data
    running ONLY on a miss (so a plan-capped file's mtime never resets)."""

    def _fetcher(self, monkeypatch, cache_returns, stub):
        import services.services as svc
        monkeypatch.setitem(svc.CONFIG, "data_provider", "csv")  # importable provider
        monkeypatch.setattr(svc, "get_cached_data", lambda *a, **k: cache_returns)
        writes = {"n": 0, "df": None}

        def _set(df, *a, **k):
            writes["n"] += 1; writes["df"] = df
        monkeypatch.setattr(svc, "set_cached_data", _set)
        # Replace the real provider import with the stub.
        import services.csv_service as csvsvc
        monkeypatch.setattr(csvsvc, "get_price_data", stub)
        return svc.get_data_service(), writes

    def test_no_write_on_cache_hit(self, monkeypatch):
        hit = _df("2020-01-01")
        stub = lambda *a, **k: (_ for _ in ()).throw(AssertionError("fetcher called on hit"))
        fetcher, writes = self._fetcher(monkeypatch, cache_returns=hit, stub=stub)
        out = fetcher("SPY", "2004-01-01", "2024-01-01", {"timeframe": "D", "timeframe_multiplier": 1})
        assert out is hit
        assert writes["n"] == 0, "set_cached_data must not run on a cache hit"

    def test_write_on_cache_miss(self, monkeypatch):
        fetched = _df("2004-01-05")
        fetcher, writes = self._fetcher(
            monkeypatch, cache_returns=None, stub=lambda *a, **k: fetched)
        out = fetcher("SPY", "2004-01-01", "2024-01-01", {"timeframe": "D", "timeframe_multiplier": 1})
        assert out is fetched
        assert writes["n"] == 1 and writes["df"] is fetched
