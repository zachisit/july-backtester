"""
tests/test_parquet_share_class_485.py

Issue #485: dashed share-class spellings (``BRK-B``) must resolve to the
parquet corpus's dotted files (``BRK.B.parquet``).

``helpers.point_in_time.normalise_pit_ticker`` deliberately emits ``BRK-B`` (the
spelling Yahoo uses), while the parquet corpus stores share classes dotted. A
PIT member therefore reached the parquet loader as ``BRK-B``, matched no file,
and dropped out of the universe with nothing but a "Parquet file not found"
warning.

The fix lives in ``services.parquet_service._find_parquet``: the given spelling
is resolved first, in full (exact, case-insensitive, date-suffixed); only when
that finds nothing is the dotted share-class spelling tried. These tests pin
both the fix and that every pre-existing lookup behaves exactly as before.

All fixtures are synthetic files under ``tmp_path`` - no network, no real data.
"""

import os
from pathlib import Path

import pandas as pd
import pytest

from helpers.point_in_time import resolve_pit_portfolio, tickers_as_of
from services.parquet_service import _find_parquet, get_price_data


def _ohlcv(start="2020-01-02", n=15):
    idx = pd.date_range(start, periods=n, freq="B")
    idx.name = "Datetime"
    return pd.DataFrame(
        {
            "Open": [100.0 + i for i in range(n)],
            "High": [101.0 + i for i in range(n)],
            "Low": [99.0 + i for i in range(n)],
            "Close": [100.5 + i for i in range(n)],
            "Volume": [1e6] * n,
        },
        index=idx,
    )


def _write(dir_: Path, stem: str, start="2020-01-02", n=15) -> Path:
    dir_.mkdir(parents=True, exist_ok=True)
    path = dir_ / f"{stem}.parquet"
    _ohlcv(start, n).to_parquet(path)
    return path


def _write_roster(root: Path) -> None:
    path = root / "src" / "sp500_ticker_history" / "sp500-ticker-changes-2020.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "year: 2020\n"
        "tickers_on_Jan_1:\n"
        "  - AAPL\n"
        "  - BRK.B\n"
        "  - BF.B\n"
        "changes: {}\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Regression: PIT member with a dotted share class, end to end
# ---------------------------------------------------------------------------

class TestPitShareClassReachesParquet:

    def test_pit_members_with_share_classes_load_from_parquet(self, tmp_path):
        """Roster BRK.B / BF.B -> PIT spelling -> non-None parquet load.

        Failed before #485: the PIT spelling is BRK-B / BF-B, and the parquet
        loader only looked for BRK-B.parquet / BF-B.parquet.
        """
        roster = tmp_path / "roster"
        data = tmp_path / "data"
        _write_roster(roster)
        for stem in ("AAPL", "BRK.B", "BF.B"):
            _write(data, stem)

        config = {
            "sp500_pit_path": str(roster),
            "parquet_data_dir": str(data),
            "data_provider": "parquet",
            "start_date": "2020-01-02",
        }
        members = resolve_pit_portfolio("pit:sp500", config)
        # The PIT output itself is unchanged (still the hyphen form).
        assert members == ["AAPL", "BF-B", "BRK-B"]

        for sym in members:
            df = get_price_data(sym, "2020-01-01", "2020-02-01", config)
            assert df is not None, f"{sym} dropped: no parquet file resolved"
            assert len(df) == 15

    def test_tickers_as_of_share_class_resolves_to_dotted_file(self, tmp_path):
        roster = tmp_path / "roster"
        data = tmp_path / "data"
        _write_roster(roster)
        expected = _write(data, "BRK.B")
        members = tickers_as_of("sp500", "2020-01-15", {"sp500_pit_path": str(roster)})
        assert "BRK-B" in members
        assert _find_parquet("BRK-B", str(data)) == str(expected)


# ---------------------------------------------------------------------------
# The share-class spelling rule
# ---------------------------------------------------------------------------

def _dotted_share_class(symbol):
    # Imported lazily so the end-to-end regression tests above still collect
    # (and fail on their assertions) against a parquet_service without it.
    from services.parquet_service import _dotted_share_class as fn
    return fn(symbol)


class TestDottedShareClass:

    @pytest.mark.parametrize("given, dotted", [
        ("BRK-B", "BRK.B"),
        ("BF-B", "BF.B"),
        ("brk-b", "brk.b"),
        ("APTV-WI", "APTV.WI"),
        ("MOG-A", "MOG.A"),
    ])
    def test_dashed_share_class_maps_to_dotted(self, given, dotted):
        assert _dotted_share_class(given) == dotted

    @pytest.mark.parametrize("given", [
        "BRK",            # no suffix
        "BRK.B",          # already dotted
        "CB-201601",      # Norgate delisted date stamp, never a share class
        "BRKB-199602",
        "ABC-2016",       # any digit suffix
        "ABC-B1",
        "ABC-ABCD",       # suffix too long to be a class
        "A-B-C",          # more than one hyphen
        "I:VIX",
        "",
    ])
    def test_non_share_class_spellings_are_left_alone(self, given):
        assert _dotted_share_class(given) is None


# ---------------------------------------------------------------------------
# Lookup behaviour: fix applies, nothing else moves
# ---------------------------------------------------------------------------

class TestFindParquetShareClass:

    def test_dashed_request_finds_dotted_file(self, tmp_path):
        expected = _write(tmp_path, "BRK.B")
        assert _find_parquet("BRK-B", str(tmp_path)) == str(expected)

    def test_lowercase_dashed_request_finds_dotted_file(self, tmp_path):
        expected = _write(tmp_path, "BRK.B")
        found = _find_parquet("brk-b", str(tmp_path))
        # samefile: on a case-insensitive filesystem the exact-case probe
        # "brk.b.parquet" already hits, so the returned spelling may differ.
        assert found is not None and os.path.samefile(found, expected)

    def test_dotted_request_unchanged(self, tmp_path):
        expected = _write(tmp_path, "BRK.B")
        assert _find_parquet("BRK.B", str(tmp_path)) == str(expected)

    def test_existing_dashed_file_wins_over_dotted(self, tmp_path):
        """A real dashed file (preferred shares, e.g. ALL-B) keeps resolving to itself."""
        dashed = _write(tmp_path, "ALL-B")
        _write(tmp_path, "ALL.B")
        assert _find_parquet("ALL-B", str(tmp_path)) == str(dashed)

    def test_bare_ticker_never_matches_share_class(self, tmp_path):
        _write(tmp_path, "BRK.B")
        _write(tmp_path, "BRK.A")
        assert _find_parquet("BRK", str(tmp_path)) is None

    def test_missing_share_class_still_none(self, tmp_path):
        _write(tmp_path, "AAPL")
        assert _find_parquet("BRK-B", str(tmp_path)) is None

    def test_get_price_data_dashed_request(self, tmp_path):
        _write(tmp_path, "BF.B")
        df = get_price_data("BF-B", "2020-01-01", "2020-02-01",
                            {"parquet_data_dir": str(tmp_path)})
        assert df is not None and len(df) == 15

    def test_dashed_request_reaches_dotted_delisted_file(self, tmp_path):
        """Dotted share classes also exist only as dated delisted files (ACM.B-199504)."""
        expected = _write(tmp_path, "ACM.B-199504", start="1994-01-03")
        assert _find_parquet("ACM-B", str(tmp_path)) == str(expected)

    def test_dashed_request_ambiguous_dotted_delisted_still_refused(self, tmp_path):
        _write(tmp_path, "XYZ.B-199504", start="1994-01-03")
        _write(tmp_path, "XYZ.B-200801", start="2007-01-02")
        found = _find_parquet("XYZ-B", str(tmp_path))
        assert found is not None and found.startswith("_multi_|")
        assert get_price_data("XYZ-B", "1994-01-01", "2008-01-31",
                              {"parquet_data_dir": str(tmp_path)}) is None


class TestDateSuffixLookupsUnchanged:
    """The Norgate TICKER-YYYYMM conventions must behave exactly as before."""

    def test_single_dated_file_for_bare_ticker(self, tmp_path):
        expected = _write(tmp_path, "ALTR-201512", start="2015-01-02")
        assert _find_parquet("ALTR", str(tmp_path)) == str(expected)

    def test_dated_security_id_requested_directly(self, tmp_path):
        expected = _write(tmp_path, "BRKB-199602", start="1995-01-03")
        _write(tmp_path, "BRK.B")
        assert _find_parquet("BRKB-199602", str(tmp_path)) == str(expected)

    def test_missing_dated_security_id_not_turned_into_share_class(self, tmp_path):
        _write(tmp_path, "CB.201601")   # would only match if digits were treated as a class
        assert _find_parquet("CB-201601", str(tmp_path)) is None

    def test_multi_period_bare_ticker_still_sentinel(self, tmp_path):
        _write(tmp_path, "CB-201601", start="2015-01-02")
        _write(tmp_path, "CB-199901", start="1998-01-02")
        found = _find_parquet("CB", str(tmp_path))
        assert found == "_multi_|" + str(tmp_path) + "|CB"
        assert get_price_data("CB", "1998-01-01", "2016-01-31",
                              {"parquet_data_dir": str(tmp_path)}) is None

    def test_live_file_masking_dated_still_returns_live(self, tmp_path, caplog):
        live = _write(tmp_path, "CB")
        _write(tmp_path, "CB-201601", start="2015-01-02")
        with caplog.at_level("WARNING"):
            assert _find_parquet("CB", str(tmp_path)) == str(live)
        assert "CB-201601" in caplog.text

    def test_bare_brkb_resolves_to_its_dated_file_not_share_class(self, tmp_path):
        """BRKB (no hyphen) is the delisted dated security, never BRK.B."""
        expected = _write(tmp_path, "BRKB-199602", start="1995-01-03")
        _write(tmp_path, "BRK.B")
        assert _find_parquet("BRKB", str(tmp_path)) == str(expected)
