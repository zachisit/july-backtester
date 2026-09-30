# tests/test_pit_security_resolution_158.py
"""PIT membership must resolve to parquet SECURITY IDs, not bare tickers (#158).

Background
----------
``pit:`` universes express membership as bare tickers. The Norgate parquet
corpus keys delisted securities as ``TICKER-YYYYMM``, so a bare ticker is not an
identifier there. Two failure modes existed before this fix:

* **masking** — a live bare ``CB.parquet`` wins the loader's exact-match branch,
  so the delisted ``CB-201601`` (Chubb Corp, the actual 2004-2015 member) is
  never considered and the run silently gets ACE Ltd's history instead;
* **collision** — no bare file plus several dated files makes the loader refuse
  to guess, and the member is dropped from the run entirely.

Both remove or swap *dead* companies, which is precisely what a point-in-time
universe exists to include.

Fixture idiom follows ``tests/test_point_in_time.py`` (YAML written to
``tmp_path``) and ``tests/test_rule_based_universe.py`` (a tiny synthetic
parquet corpus), so nothing here depends on the real 36k-security submodule.
"""

from pathlib import Path

import pandas as pd
import pytest

from helpers.point_in_time import (
    PitResolutionError,
    build_membership_schedule,
    build_ticker_candidate_map,
    pit_members_on,
    resolve_security_id,
    tickers_union_for_period,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_parquet(corpus: Path, name: str, start: str, end: str,
                   price: float = 50.0, volume: float = 1_000_000.0):
    """One synthetic security file, ``{name}.parquet``, spanning [start, end]."""
    corpus.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range(start, end, freq="B")
    df = pd.DataFrame(
        {"Open": price, "High": price * 1.01, "Low": price * 0.99,
         "Close": float(price), "Volume": float(volume)},
        index=idx,
    )
    df.index.name = "Datetime"
    df.to_parquet(corpus / f"{name}.parquet")


def _write_nq_yaml(repo: Path, year: int, members, changes: str = "{}"):
    """An n100 change-event YAML for *year* with ``tickers_on_Jan_1 = members``."""
    path = repo / "src" / "nasdaq_100_ticker_history" / f"n100-ticker-changes-{year}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    listed = "\n".join(f"  - {m}" for m in members)
    path.write_text(
        f"year: {year}\ntickers_on_Jan_1:\n{listed}\nchanges: {changes}\n",
        encoding="utf-8",
    )


def _cfg(tmp_path, start, end, provider="parquet", **over):
    cfg = {
        "data_provider": provider,
        "parquet_data_dir": str(tmp_path / "corpus"),
        "nq100_pit_path": str(tmp_path / "nq_repo"),
        "start_date": start,
        "end_date": end,
    }
    cfg.update(over)
    return cfg


# ---------------------------------------------------------------------------
# The masking case — the headline regression (fails on main)
# ---------------------------------------------------------------------------

class TestMaskingCase:
    """``CB``: a live bare file masks the delisted security that was the member."""

    @staticmethod
    def _corpus(tmp_path):
        corpus = tmp_path / "corpus"
        # ACE Ltd, back-filled under its CURRENT ticker CB (Norgate convention).
        _write_parquet(corpus, "CB", "1993-01-04", "2024-12-31")
        # Chubb Corp — the company that actually traded as CB until Jan 2016.
        _write_parquet(corpus, "CB-201601", "1990-01-02", "2016-01-14")
        return corpus

    def test_2010_membership_resolves_to_the_delisted_security(self, tmp_path):
        self._corpus(tmp_path)
        _write_nq_yaml(tmp_path / "nq_repo", 2010, ["CB"])
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")

        schedule = build_membership_schedule("nq100", "2010-01-04", "2010-12-31", cfg)

        # On main this is frozenset({"CB"}) — ACE Ltd's history, not Chubb Corp's.
        assert pit_members_on(schedule, "2010-06-01") == frozenset({"CB-201601"})

    def test_union_matches_the_schedule(self, tmp_path):
        self._corpus(tmp_path)
        _write_nq_yaml(tmp_path / "nq_repo", 2010, ["CB"])
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")

        assert tickers_union_for_period(
            "nq100", "2010-01-04", "2010-12-31", cfg) == ["CB-201601"]

    def test_after_the_stamp_the_live_file_wins(self, tmp_path):
        """2020 membership is ACE/Chubb Ltd — the bare file — not the dead one."""
        self._corpus(tmp_path)
        _write_nq_yaml(tmp_path / "nq_repo", 2020, ["CB"])
        cfg = _cfg(tmp_path, "2020-01-02", "2020-12-31")

        schedule = build_membership_schedule("nq100", "2020-01-02", "2020-12-31", cfg)
        assert pit_members_on(schedule, "2020-06-01") == frozenset({"CB"})


# ---------------------------------------------------------------------------
# The collision case
# ---------------------------------------------------------------------------

class TestCollisionCase:
    """``AGN``: no bare file, two dated files — the loader drops it on main."""

    @staticmethod
    def _corpus(tmp_path):
        corpus = tmp_path / "corpus"
        _write_parquet(corpus, "AGN-201503", "1990-01-02", "2015-03-16")
        _write_parquet(corpus, "AGN-202005", "2015-04-01", "2020-05-08")
        return corpus

    def test_2010_resolves_to_the_first_security(self, tmp_path):
        self._corpus(tmp_path)
        _write_nq_yaml(tmp_path / "nq_repo", 2010, ["AGN"])
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")

        schedule = build_membership_schedule("nq100", "2010-01-04", "2010-12-31", cfg)
        assert pit_members_on(schedule, "2010-06-01") == frozenset({"AGN-201503"})

    def test_2018_resolves_to_the_second_security(self, tmp_path):
        self._corpus(tmp_path)
        _write_nq_yaml(tmp_path / "nq_repo", 2018, ["AGN"])
        cfg = _cfg(tmp_path, "2018-01-02", "2018-12-31")

        schedule = build_membership_schedule("nq100", "2018-01-02", "2018-12-31", cfg)
        assert pit_members_on(schedule, "2018-06-01") == frozenset({"AGN-202005"})

    def test_date_covered_by_neither_aborts(self, tmp_path):
        self._corpus(tmp_path)
        _write_nq_yaml(tmp_path / "nq_repo", 2023, ["AGN"])
        cfg = _cfg(tmp_path, "2023-01-02", "2023-12-31")

        with pytest.raises(PitResolutionError) as exc:
            build_membership_schedule("nq100", "2023-01-02", "2023-12-31", cfg)
        text = str(exc.value)
        assert "AGN" in text
        # The operator must see WHY it was unresolvable.
        assert "AGN-201503" in text and "AGN-202005" in text
        assert "2023-01-02" in text

    def test_overlapping_spans_that_tenure_cannot_decide_abort(self, tmp_path):
        """Two stamps both BEFORE the date, both spans covering it.

        A corpus inconsistency rather than a real ticker hand-over: nothing
        says which security owned the ticker then, so the run refuses.
        """
        corpus = tmp_path / "corpus"
        _write_parquet(corpus, "ZZZ-200301", "1995-01-02", "2005-12-30")
        _write_parquet(corpus, "ZZZ-200406", "1998-01-02", "2005-12-30")
        _write_nq_yaml(tmp_path / "nq_repo", 2005, ["ZZZ"])
        cfg = _cfg(tmp_path, "2005-06-01", "2005-12-30")

        with pytest.raises(PitResolutionError, match="ZZZ"):
            build_membership_schedule("nq100", "2005-06-01", "2005-12-30", cfg)


# ---------------------------------------------------------------------------
# Abort semantics
# ---------------------------------------------------------------------------

class TestAbortOnUnresolvable:

    def test_every_offender_is_named_in_one_error(self, tmp_path):
        """Not first-failure abort: 46 collisions must not need 46 runs to find."""
        corpus = tmp_path / "corpus"
        _write_parquet(corpus, "GOOD", "1995-01-02", "2024-12-31")
        # BAD1: exists, but no security covers the membership date.
        _write_parquet(corpus, "BAD1-199012", "1985-01-02", "1990-12-14")
        # BAD2: not in the corpus at all.
        _write_nq_yaml(tmp_path / "nq_repo", 2010, ["GOOD", "BAD1", "BAD2"])
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")

        with pytest.raises(PitResolutionError) as exc:
            build_membership_schedule("nq100", "2010-01-04", "2010-12-31", cfg)

        text = str(exc.value)
        assert "BAD1" in text, "first failure reported but not the second"
        assert "BAD2" in text, "second failure swallowed by a first-failure abort"
        assert len({t for t, _, _ in exc.value.failures}) == 2
        # The remedy the parquet loader's own masking warning advises.
        assert "security ID" in text

    def test_union_aborts_too(self, tmp_path):
        """Both entry points must refuse — the union feeds the actual fetch."""
        corpus = tmp_path / "corpus"
        _write_parquet(corpus, "GOOD", "1995-01-02", "2024-12-31")
        _write_nq_yaml(tmp_path / "nq_repo", 2010, ["GOOD", "NOPE"])
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")

        with pytest.raises(PitResolutionError, match="NOPE"):
            tickers_union_for_period("nq100", "2010-01-04", "2010-12-31", cfg)

    def test_missing_member_names_no_candidates(self, tmp_path):
        corpus = tmp_path / "corpus"
        _write_parquet(corpus, "GOOD", "1995-01-02", "2024-12-31")
        _write_nq_yaml(tmp_path / "nq_repo", 2010, ["GOOD", "NOPE"])
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")

        with pytest.raises(PitResolutionError) as exc:
            build_membership_schedule("nq100", "2010-01-04", "2010-12-31", cfg)
        assert "does not exist" in str(exc.value) or "at all" in str(exc.value)


# ---------------------------------------------------------------------------
# Every other provider is untouched
# ---------------------------------------------------------------------------

class TestNonParquetProvidersUnchanged:
    """``CB-201601`` is a meaningless symbol to Yahoo. Bare tickers must survive."""

    @staticmethod
    def _setup(tmp_path):
        corpus = tmp_path / "corpus"
        _write_parquet(corpus, "CB", "1993-01-04", "2024-12-31")
        _write_parquet(corpus, "CB-201601", "1990-01-02", "2016-01-14")
        _write_nq_yaml(tmp_path / "nq_repo", 2010, ["CB", "MSFT"])

    @pytest.mark.parametrize("provider", ["yahoo", "polygon", "csv", "norgate"])
    def test_schedule_keeps_bare_tickers(self, tmp_path, provider):
        self._setup(tmp_path)
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31", provider=provider)

        schedule = build_membership_schedule("nq100", "2010-01-04", "2010-12-31", cfg)
        assert pit_members_on(schedule, "2010-06-01") == frozenset({"CB", "MSFT"})

    @pytest.mark.parametrize("provider", ["yahoo", "polygon", "csv", "norgate"])
    def test_union_keeps_bare_tickers(self, tmp_path, provider):
        self._setup(tmp_path)
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31", provider=provider)

        assert tickers_union_for_period(
            "nq100", "2010-01-04", "2010-12-31", cfg) == ["CB", "MSFT"]

    def test_identical_to_a_config_with_no_provider_key(self, tmp_path):
        """Byte-identical to pre-fix behaviour, which had no provider branch."""
        self._setup(tmp_path)
        yahoo = _cfg(tmp_path, "2010-01-04", "2010-12-31", provider="yahoo")
        legacy = {k: v for k, v in yahoo.items() if k != "data_provider"}

        assert (build_membership_schedule("nq100", "2010-01-04", "2010-12-31", yahoo)
                == build_membership_schedule("nq100", "2010-01-04", "2010-12-31", legacy))
        assert (tickers_union_for_period("nq100", "2010-01-04", "2010-12-31", yahoo)
                == tickers_union_for_period("nq100", "2010-01-04", "2010-12-31", legacy))

    def test_missing_member_does_not_abort_for_yahoo(self, tmp_path):
        """No corpus lookup happens at all off parquet — nothing to abort on."""
        _write_nq_yaml(tmp_path / "nq_repo", 2010, ["NOPE"])
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31", provider="yahoo")

        assert tickers_union_for_period(
            "nq100", "2010-01-04", "2010-12-31", cfg) == ["NOPE"]


# ---------------------------------------------------------------------------
# Namespace consistency — the masking-regression guard
# ---------------------------------------------------------------------------

class TestScheduleAndUnionAgree:
    """A schedule of security IDs masked against bare tickers masks EVERYTHING out.

    main.py builds the per-bar ``_pit_member`` mask by testing
    ``symbol in pit_members_on(schedule, date)``, where ``symbol`` is a key of
    ``portfolio_data`` — i.e. it came from the union. If the two namespaces
    diverge, every mask is all-False, every entry is blocked and the run reports
    zero trades with no error.
    """

    @staticmethod
    def _setup(tmp_path):
        corpus = tmp_path / "corpus"
        _write_parquet(corpus, "CB", "1993-01-04", "2024-12-31")
        _write_parquet(corpus, "CB-201601", "1990-01-02", "2016-01-14")
        _write_parquet(corpus, "AGN-201503", "1990-01-02", "2015-03-16")
        _write_parquet(corpus, "AGN-202005", "2015-04-01", "2020-05-08")
        _write_parquet(corpus, "AAPL", "1990-01-02", "2024-12-31")
        _write_nq_yaml(
            tmp_path / "nq_repo", 2010, ["AAPL", "CB", "AGN"],
            changes="\n  '2010-07-01':\n    difference:\n      - AGN\n    union: []",
        )

    def test_every_member_of_every_snapshot_is_in_the_union(self, tmp_path):
        self._setup(tmp_path)
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")

        union = set(tickers_union_for_period("nq100", "2010-01-04", "2010-12-31", cfg))
        schedule = build_membership_schedule("nq100", "2010-01-04", "2010-12-31", cfg)

        for date, members in schedule:
            assert members <= union, f"snapshot {date} has members outside the union"

    def test_every_union_symbol_is_a_member_on_some_bar(self, tmp_path):
        self._setup(tmp_path)
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")

        union = tickers_union_for_period("nq100", "2010-01-04", "2010-12-31", cfg)
        schedule = build_membership_schedule("nq100", "2010-01-04", "2010-12-31", cfg)

        # This is the mask main.py actually builds.
        for symbol in union:
            assert any(symbol in members for _, members in schedule), (
                f"'{symbol}' would be fetched but masked out on every bar"
            )

    def test_the_union_is_security_ids_not_bare_tickers(self, tmp_path):
        self._setup(tmp_path)
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")

        assert set(tickers_union_for_period(
            "nq100", "2010-01-04", "2010-12-31", cfg)) == {
                "AAPL", "CB-201601", "AGN-201503"}


# ---------------------------------------------------------------------------
# Cases that must NOT change
# ---------------------------------------------------------------------------

class TestNoRegressionOnOrdinaryTickers:

    def test_live_only_ticker_resolves_to_itself(self, tmp_path):
        """The common case: one file, no dated siblings."""
        _write_parquet(tmp_path / "corpus", "AAPL", "1990-01-02", "2024-12-31")
        _write_nq_yaml(tmp_path / "nq_repo", 2010, ["AAPL"])
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")

        schedule = build_membership_schedule("nq100", "2010-01-04", "2010-12-31", cfg)
        assert pit_members_on(schedule, "2010-06-01") == frozenset({"AAPL"})
        assert tickers_union_for_period(
            "nq100", "2010-01-04", "2010-12-31", cfg) == ["AAPL"]

    def test_share_class_is_not_a_delisting_stamp(self, tmp_path):
        """``BRK-A`` is a share class; only a 6-digit suffix marks a delisting."""
        corpus = tmp_path / "corpus"
        _write_parquet(corpus, "BRK-A", "1990-01-02", "2024-12-31")
        _write_nq_yaml(tmp_path / "nq_repo", 2010, ["BRK.A"])   # YAML uses a dot
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")

        schedule = build_membership_schedule("nq100", "2010-01-04", "2010-12-31", cfg)
        assert pit_members_on(schedule, "2010-06-01") == frozenset({"BRK-A"})

    def test_share_class_with_a_delisted_sibling(self, tmp_path):
        corpus = tmp_path / "corpus"
        _write_parquet(corpus, "MER-K", "1990-01-02", "2008-12-31")
        _write_nq_yaml(tmp_path / "nq_repo", 2005, ["MER.K"])
        cfg = _cfg(tmp_path, "2005-01-03", "2005-12-30")

        schedule = build_membership_schedule("nq100", "2005-01-03", "2005-12-30", cfg)
        assert pit_members_on(schedule, "2005-06-01") == frozenset({"MER-K"})


# ---------------------------------------------------------------------------
# The resolver itself
# ---------------------------------------------------------------------------

class TestResolveSecurityIdUnit:

    @staticmethod
    def _map():
        return build_ticker_candidate_map(pd.DataFrame(
            [
                {"security": "CB", "ticker": "CB", "delisted": None,
                 "first_bar": pd.Timestamp("1993-01-04"),
                 "last_bar": pd.Timestamp("2024-12-31"), "n_bars": 1},
                {"security": "CB-201601", "ticker": "CB", "delisted": "201601",
                 "first_bar": pd.Timestamp("1990-01-02"),
                 "last_bar": pd.Timestamp("2016-01-14"), "n_bars": 1},
                {"security": "BRK-A", "ticker": "BRK-A", "delisted": None,
                 "first_bar": pd.Timestamp("1990-01-02"),
                 "last_bar": pd.Timestamp("2024-12-31"), "n_bars": 1},
            ]
        ).set_index("security"))

    @pytest.mark.parametrize("date,expected", [
        ("1995-06-01", "CB-201601"),
        ("2010-06-01", "CB-201601"),
        ("2016-01-10", "CB-201601"),   # still its ticker in the stamp month
        ("2016-06-01", "CB"),          # after the hand-over
        ("2024-06-01", "CB"),
    ])
    def test_cb_tenure_boundaries(self, date, expected):
        assert resolve_security_id("CB", date, self._map())[0] == expected

    def test_before_any_history_is_unresolvable(self):
        assert resolve_security_id("CB", "1980-01-02", self._map())[0] is None

    def test_unknown_ticker_has_no_candidates(self):
        security, candidates = resolve_security_id("NOPE", "2010-01-04", self._map())
        assert security is None and candidates == []

    def test_candidates_are_described_with_their_spans(self):
        _, candidates = resolve_security_id("CB", "1980-01-02", self._map())
        assert candidates == [
            "CB [1993-01-04 .. 2024-12-31]",
            "CB-201601 [1990-01-02 .. 2016-01-14]",
        ]

    def test_share_class_is_not_split_on_its_hyphen(self):
        assert resolve_security_id("BRK-A", "2010-06-01", self._map())[0] == "BRK-A"
