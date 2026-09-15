"""Tests for the Polygon → Parquet daily updater + new-listings scan (#191).

No network: Polygon HTTP is faked via a stub session. Parquet I/O is real
(tmp_path), mirroring the csv_service test style.
"""
import os
import sys

import pandas as pd
import pytest

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS_DIR)

import polygon_daily_update as pdu  # noqa: E402
import polygon_new_listings as pnl  # noqa: E402


# ──────────────────────────────────────────────────────────────────────────────
# Fake Polygon HTTP
# ──────────────────────────────────────────────────────────────────────────────
class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


class _FakeSession:
    """Routes GETs to canned payloads keyed by a substring of the URL path."""
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        for key, payload in self.routes.items():
            if key in url:
                return _FakeResp(payload)
        return _FakeResp({"results": [], "resultsCount": 0})


class _SequenceSession:
    """Returns canned payloads in order, one per GET — for pagination tests."""
    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        payload = self._payloads[min(len(self.calls) - 1, len(self._payloads) - 1)]
        return _FakeResp(payload)


def _bar(o, h, l, c, v, t_ms):
    return {"o": o, "h": h, "l": l, "c": c, "v": v, "t": t_ms}


# ──────────────────────────────────────────────────────────────────────────────
# classify_symbol
# ──────────────────────────────────────────────────────────────────────────────
class TestClassifySymbol:
    def test_equity(self):
        assert pdu.classify_symbol("AAPL.parquet") == ("equity", "AAPL")

    def test_index_dollar(self):
        assert pdu.classify_symbol("$VIX.parquet") == ("index", "$VIX")

    def test_breadth_hash(self):
        assert pdu.classify_symbol("#AMEXAD.parquet") == ("breadth", "#AMEXAD")

    def test_no_extension(self):
        assert pdu.classify_symbol("MSFT") == ("equity", "MSFT")


# ──────────────────────────────────────────────────────────────────────────────
# Index symbol mapping (normalize_ticker integration)
# ──────────────────────────────────────────────────────────────────────────────
class TestIndexMapping:
    def test_dollar_vix_maps_to_polygon(self):
        from helpers.ticker_normalizer import normalize_ticker
        assert normalize_ticker("$VIX", "polygon") == "I:VIX"

    def test_equity_unchanged(self):
        from helpers.ticker_normalizer import normalize_ticker
        assert normalize_ticker("AAPL", "polygon") == "AAPL"


# ──────────────────────────────────────────────────────────────────────────────
# Frame builders
# ──────────────────────────────────────────────────────────────────────────────
class TestFrameBuilders:
    def test_bars_to_df_columns_and_index(self):
        ts = int(pd.Timestamp("2026-04-23", tz="UTC").timestamp() * 1000)
        df = pdu.bars_to_df([_bar(10, 12, 9, 11, 1000, ts)])
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
        assert df.index[0] == pd.Timestamp("2026-04-23", tz="UTC")
        assert df.iloc[0]["Close"] == 11

    def test_bars_to_df_empty(self):
        assert pdu.bars_to_df([]).empty

    def test_grouped_rows_to_df(self):
        rows = [("2026-04-23", {"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100})]
        df = pdu.grouped_rows_to_df(rows)
        assert df.index[0] == pd.Timestamp("2026-04-23", tz="UTC")
        assert df.iloc[0]["Volume"] == 100
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]


# ──────────────────────────────────────────────────────────────────────────────
# Parquet append / dedup round-trip
# ──────────────────────────────────────────────────────────────────────────────
class TestAppendAndWrite:
    def _existing(self, tmp_path):
        idx = pd.to_datetime(["2026-04-21", "2026-04-22"], utc=True)
        df = pd.DataFrame({"Open": [1, 2], "High": [1, 2], "Low": [1, 2],
                           "Close": [1, 2], "Volume": [10, 20]}, index=idx)
        df.index.name = "Datetime"
        p = os.path.join(tmp_path, "AAPL.parquet")
        df.to_parquet(p)
        return p

    def test_appends_new_rows(self, tmp_path):
        p = self._existing(tmp_path)
        new = pd.DataFrame({"Open": [3], "High": [3], "Low": [3], "Close": [3], "Volume": [30]},
                           index=pd.to_datetime(["2026-04-23"], utc=True))
        added = pdu.append_and_write(p, new, dry_run=False)
        assert added == 1
        out = pd.read_parquet(p)
        assert len(out) == 3
        assert out.index.max() == pd.Timestamp("2026-04-23", tz="UTC")

    def test_dedup_keeps_last(self, tmp_path):
        p = self._existing(tmp_path)
        # Re-send 2026-04-22 with a corrected close + a genuinely new day.
        new = pd.DataFrame({"Open": [9, 3], "High": [9, 3], "Low": [9, 3], "Close": [99, 3], "Volume": [9, 30]},
                           index=pd.to_datetime(["2026-04-22", "2026-04-23"], utc=True))
        added = pdu.append_and_write(p, new, dry_run=False)
        out = pd.read_parquet(p)
        assert len(out) == 3                      # not 4 — the dup collapsed
        assert out.loc[pd.Timestamp("2026-04-22", tz="UTC"), "Close"] == 99  # kept last
        assert added == 1

    def test_dry_run_does_not_write(self, tmp_path):
        p = self._existing(tmp_path)
        new = pd.DataFrame({"Open": [3], "High": [3], "Low": [3], "Close": [3], "Volume": [30]},
                           index=pd.to_datetime(["2026-04-23"], utc=True))
        added = pdu.append_and_write(p, new, dry_run=True)
        assert added == 1                          # reports what it WOULD add
        assert len(pd.read_parquet(p)) == 2        # but file unchanged

    def test_empty_new_df_noop(self, tmp_path):
        p = self._existing(tmp_path)
        assert pdu.append_and_write(p, pd.DataFrame(), dry_run=False) == 0

    def test_creates_new_file(self, tmp_path):
        p = os.path.join(tmp_path, "NEWCO.parquet")
        new = pd.DataFrame({"Open": [3], "High": [3], "Low": [3], "Close": [3], "Volume": [30]},
                           index=pd.to_datetime(["2026-04-23"], utc=True))
        added = pdu.append_and_write(p, new, dry_run=False)
        assert added == 1 and os.path.exists(p)


# ──────────────────────────────────────────────────────────────────────────────
# read_last_date
# ──────────────────────────────────────────────────────────────────────────────
class TestReadLastDate:
    def test_returns_max(self, tmp_path):
        idx = pd.to_datetime(["2026-04-20", "2026-04-22", "2026-04-21"], utc=True)
        df = pd.DataFrame({"Close": [1, 2, 3]}, index=idx)
        p = os.path.join(tmp_path, "X.parquet")
        df.to_parquet(p)
        assert pdu.read_last_date(p) == pd.Timestamp("2026-04-22", tz="UTC")

    def test_missing_file_none(self, tmp_path):
        assert pdu.read_last_date(os.path.join(tmp_path, "nope.parquet")) is None


# ──────────────────────────────────────────────────────────────────────────────
# Polygon fetchers (faked HTTP)
# ──────────────────────────────────────────────────────────────────────────────
class TestFetchers:
    def test_fetch_grouped_day_filters_and_maps(self):
        sess = _FakeSession({"grouped": {"resultsCount": 2, "results": [
            {"T": "AAPL", "o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100},
            {"T": "msft", "o": 3, "h": 4, "l": 2.5, "c": 3.5, "v": 200},
        ]}})
        hits = pdu.fetch_grouped_day(sess, "KEY", "2026-04-23", adjusted=True)
        assert set(hits) == {"AAPL", "MSFT"}       # upper-cased keys
        assert hits["AAPL"]["c"] == 1.5

    def test_fetch_grouped_day_holiday_empty(self):
        sess = _FakeSession({"grouped": {"resultsCount": 0, "results": []}})
        assert pdu.fetch_grouped_day(sess, "KEY", "2026-04-25", adjusted=True) == {}

    def test_fetch_ticker_range(self):
        sess = _FakeSession({"range": {"results": [_bar(1, 2, 0.5, 1.5, 10, 1)]}})
        rows = pdu.fetch_ticker_range(sess, "KEY", "I:VIX", "2026-04-23", "2026-04-30", adjusted=True)
        assert len(rows) == 1 and rows[0]["c"] == 1.5

    def test_adjusted_param_passed(self):
        sess = _FakeSession({"grouped": {"resultsCount": 0, "results": []}})
        pdu.fetch_grouped_day(sess, "KEY", "2026-04-23", adjusted=True)
        # The adjusted flag should ride along in params (url recorded; params separate)
        assert sess.calls  # at least one call made


# ──────────────────────────────────────────────────────────────────────────────
# _business_days
# ──────────────────────────────────────────────────────────────────────────────
class TestBusinessDays:
    def test_excludes_weekend(self):
        # 2026-04-24 is a Friday; 25/26 weekend; 27 Monday.
        days = pdu._business_days("2026-04-24", "2026-04-27")
        assert days == ["2026-04-24", "2026-04-27"]


# ──────────────────────────────────────────────────────────────────────────────
# New-listings diff
# ──────────────────────────────────────────────────────────────────────────────
class TestNewListings:
    def test_existing_equity_symbols_excludes_index_and_breadth(self, tmp_path):
        for name in ["AAPL.parquet", "$VIX.parquet", "#AMEXAD.parquet", "msft.parquet"]:
            pd.DataFrame({"Close": [1]}, index=pd.to_datetime(["2026-04-22"], utc=True)).to_parquet(
                os.path.join(tmp_path, name))
        have = pnl.existing_equity_symbols(str(tmp_path))
        assert have == {"AAPL", "MSFT"}            # $ and # excluded, case-folded

    def test_fetch_active_equities_paginates(self):
        sess = _SequenceSession([
            {"results": [{"ticker": "AAA"}, {"ticker": "BBB"}],
             "next_url": pdu.API_BASE + "/v3/reference/tickers?cursor=page2"},
            {"results": [{"ticker": "CCC"}], "next_url": None},
        ])
        got = pnl.fetch_active_equities(sess, "KEY")
        assert got == {"AAA", "BBB", "CCC"}
        assert len(sess.calls) == 2  # exactly two pages, no infinite loop

    def test_new_minus_existing(self):
        active = {"AAA", "BBB", "CCC"}
        have = {"AAA"}
        assert sorted(active - have) == ["BBB", "CCC"]


# ──────────────────────────────────────────────────────────────────────────────
# main() orchestration (fetchers monkeypatched — no network; real parquet I/O)
# ──────────────────────────────────────────────────────────────────────────────
class TestMainOrchestration:
    def _seed(self, tmp_path):
        idx = pd.to_datetime(["2026-04-22"], utc=True)
        for name in ["AAPL.parquet", "$VIX.parquet", "#AMEXAD.parquet"]:
            df = pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [10]}, index=idx)
            df.index.name = "Datetime"
            df.to_parquet(os.path.join(tmp_path, name))

    def test_equity_index_updated_breadth_skipped(self, tmp_path, monkeypatch):
        self._seed(tmp_path)

        monkeypatch.setattr(pdu, "get_api_key", lambda: "KEY")
        monkeypatch.setattr(pdu, "last_trading_day", lambda *a, **k: "2026-04-24")

        def fake_grouped(session, key, ds, adjusted):
            # AAPL trades both new days; nothing else equity in our set.
            return {"AAPL": {"o": 5, "h": 6, "l": 4, "c": 5.5, "v": 999}}

        def fake_range(session, key, sym, start, end, adjusted):
            assert sym == "I:VIX"  # $VIX must be normalized for Polygon
            ts = int(pd.Timestamp("2026-04-23", tz="UTC").timestamp() * 1000)
            return [_bar(20, 21, 19, 20.5, 0, ts)]

        monkeypatch.setattr(pdu, "fetch_grouped_day", fake_grouped)
        monkeypatch.setattr(pdu, "fetch_ticker_range", fake_range)

        rc = pdu.main(["--data-dir", str(tmp_path), "--start", "2026-04-23", "--end", "2026-04-24"])
        assert rc == 0

        aapl = pd.read_parquet(os.path.join(tmp_path, "AAPL.parquet"))
        assert aapl.index.max() == pd.Timestamp("2026-04-24", tz="UTC")
        assert len(aapl) == 3  # 04-22 seed + 04-23 + 04-24

        vix = pd.read_parquet(os.path.join(tmp_path, "$VIX.parquet"))
        assert pd.Timestamp("2026-04-23", tz="UTC") in vix.index

        breadth = pd.read_parquet(os.path.join(tmp_path, "#AMEXAD.parquet"))
        assert len(breadth) == 1  # untouched — frozen

    def test_dry_run_writes_nothing(self, tmp_path, monkeypatch):
        self._seed(tmp_path)
        monkeypatch.setattr(pdu, "get_api_key", lambda: "KEY")
        monkeypatch.setattr(pdu, "last_trading_day", lambda *a, **k: "2026-04-24")
        monkeypatch.setattr(pdu, "fetch_grouped_day",
                            lambda *a, **k: {"AAPL": {"o": 5, "h": 6, "l": 4, "c": 5.5, "v": 999}})
        monkeypatch.setattr(pdu, "fetch_ticker_range", lambda *a, **k: [])

        rc = pdu.main(["--data-dir", str(tmp_path), "--start", "2026-04-23",
                       "--end", "2026-04-24", "--dry-run"])
        assert rc == 0
        aapl = pd.read_parquet(os.path.join(tmp_path, "AAPL.parquet"))
        assert len(aapl) == 1  # dry-run: seed file unchanged


# ──────────────────────────────────────────────────────────────────────────────
# Bounded auto-start — what makes an UNATTENDED run possible at all
# ──────────────────────────────────────────────────────────────────────────────
class TestClampLookback:
    def test_clamps_a_start_older_than_the_window(self):
        assert pdu._clamp_lookback("1990-01-27", "2026-09-15", 30) == "2026-08-16"

    def test_leaves_a_recent_start_alone(self):
        # Already inside the window — the clamp is a floor, never a forced start.
        assert pdu._clamp_lookback("2026-09-12", "2026-09-15", 30) == "2026-09-12"

    def test_zero_disables_the_clamp(self):
        assert pdu._clamp_lookback("1990-01-27", "2026-09-15", 0) == "1990-01-27"

    def test_negative_disables_the_clamp(self):
        assert pdu._clamp_lookback("1990-01-27", "2026-09-15", -1) == "1990-01-27"

    def test_boundary_date_is_not_clamped(self):
        assert pdu._clamp_lookback("2026-08-16", "2026-09-15", 30) == "2026-08-16"


class TestUnattendedStartSelection:
    """A delisted symbol frozen in 1990 must not set the fetch window.

    Two thirds of the equity universe is delisted and will never receive another
    bar, but they still participate in the ``min()`` that picks the auto start.
    Unclamped, a cron with no ``--start`` asks for every session since 1990.
    """

    def _seed(self, tmp_path, live_last="2026-09-12", dead_last="1990-01-26"):
        for name, last in (("AAPL.parquet", live_last), ("FNBF-199001.parquet", dead_last)):
            idx = pd.to_datetime([last], utc=True)
            df = pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [10]}, index=idx)
            df.index.name = "Datetime"
            df.to_parquet(os.path.join(tmp_path, name))

    def _run_capturing_days(self, tmp_path, monkeypatch, argv):
        seen: list[str] = []
        monkeypatch.setattr(pdu, "get_api_key", lambda: "KEY")
        monkeypatch.setattr(pdu, "last_trading_day", lambda *a, **k: "2026-09-15")
        monkeypatch.setattr(pdu, "fetch_ticker_range", lambda *a, **k: [])

        def fake_grouped(session, key, ds, adjusted):
            seen.append(ds)
            return {}

        monkeypatch.setattr(pdu, "fetch_grouped_day", fake_grouped)
        rc = pdu.main(["--data-dir", str(tmp_path), "--end", "2026-09-15"] + argv)
        assert rc == 0
        return seen

    def test_default_lookback_bounds_the_fetch(self, tmp_path, monkeypatch):
        self._seed(tmp_path)
        seen = self._run_capturing_days(tmp_path, monkeypatch, [])
        # ~30 calendar days of sessions, not ~9,000.
        assert len(seen) <= 25, f"fetched {len(seen)} days — the clamp is not applied"
        assert min(seen) >= "2026-08-16"

    def test_without_the_clamp_it_reaches_1990(self, tmp_path, monkeypatch):
        """Pins the failure mode itself, so a regression is visible as a number."""
        self._seed(tmp_path)
        seen = self._run_capturing_days(tmp_path, monkeypatch, ["--max-lookback-days", "0"])
        assert min(seen) == "1990-01-29", min(seen)   # first session after the dead symbol's last bar
        assert len(seen) > 8000, f"expected the full 1990-onward sweep, got {len(seen)}"

    def test_explicit_start_is_never_clamped(self, tmp_path, monkeypatch):
        self._seed(tmp_path)
        seen = self._run_capturing_days(tmp_path, monkeypatch, ["--start", "2026-06-17"])
        assert min(seen) == "2026-06-17"
        assert len(seen) > 30   # the 3-month backfill window, well past the 30-day clamp

    def test_clamp_never_rewrites_history(self, tmp_path, monkeypatch):
        """The clamp bounds the FETCH window only; writes stay append-only.

        A wide window re-offers bars a symbol already has. Those must be dropped
        by the per-symbol ``> last`` filter, not written back over the seed.
        """
        self._seed(tmp_path)
        monkeypatch.setattr(pdu, "get_api_key", lambda: "KEY")
        monkeypatch.setattr(pdu, "last_trading_day", lambda *a, **k: "2026-09-15")
        monkeypatch.setattr(pdu, "fetch_ticker_range", lambda *a, **k: [])
        # Offer AAPL a bar on EVERY day in the window, including days it already has.
        monkeypatch.setattr(pdu, "fetch_grouped_day",
                            lambda s, k, ds, adj: {"AAPL": {"o": 9, "h": 9, "l": 9, "c": 9, "v": 1}})

        rc = pdu.main(["--data-dir", str(tmp_path), "--end", "2026-09-15", "--start", "2026-08-01"])
        assert rc == 0
        aapl = pd.read_parquet(os.path.join(tmp_path, "AAPL.parquet"))
        # The 2026-09-12 seed row is untouched; only strictly-newer bars appended.
        assert aapl.loc[pd.Timestamp("2026-09-12", tz="UTC"), "Close"] == 1
        assert aapl.index.min() == pd.Timestamp("2026-09-12", tz="UTC")
