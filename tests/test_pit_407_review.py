# tests/test_pit_407_review.py
"""Regression tests for the #407 review of the #158 PIT -> parquet resolver.

Each class pins one finding, measured against the real corpus and rosters
(2004-01-01 .. 2026-09-28) and reproduced here on a synthetic corpus:

* share classes  -- the corpus spells them ``BRK.B.parquet``; every pit:sp500
  run aborted because the resolver only looked for ``BRK-B``;
* alias-then-tenure -- ``SYMC`` was aliased to ``GEN`` first, and the tenure
  rule then picked whoever held ``GEN`` in 2008 (GenOn), a silent swap;
* overrides     -- explicit dated mappings win, but are validated, never trusted;
* date lag      -- index dates can sit a few days outside a security's bars;
* YAML booleans -- an unquoted ``ON`` in the NQ100 rosters parsed as ``True``,
  so ON Semiconductor became the ticker ``TRUE`` (TrueCar);
* forced-exit intervals -- keyed by security, not roster ticker.
"""

from pathlib import Path

import pandas as pd
import pytest

import helpers.point_in_time as pit
from helpers.rule_based_universe import parse_security
from helpers.point_in_time import (
    PitResolutionError,
    SecuritySchedule,
    build_membership_schedule,
    build_ticker_candidate_map,
    load_roster_yaml,
    pit_members_on,
    resolve_security_id,
    security_intervals,
)


def _write_parquet(corpus: Path, name: str, start: str, end: str):
    corpus.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range(start, end, freq="B")
    df = pd.DataFrame({"Open": 50.0, "High": 50.5, "Low": 49.5, "Close": 50.0,
                       "Volume": 1_000_000.0}, index=idx)
    df.index.name = "Datetime"
    df.to_parquet(corpus / f"{name}.parquet")


def _write_nq_yaml(repo: Path, year: int, members, changes: str = "{}", quote=False):
    path = repo / "src" / "nasdaq_100_ticker_history" / f"n100-ticker-changes-{year}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    listed = "\n".join(f"  - '{m}'" if quote else f"  - {m}" for m in members)
    path.write_text(f"year: {year}\ntickers_on_Jan_1:\n{listed}\nchanges: {changes}\n",
                    encoding="utf-8")


def _cfg(tmp_path, start, end, provider="parquet"):
    return {"data_provider": provider, "parquet_data_dir": str(tmp_path / "corpus"),
            "nq100_pit_path": str(tmp_path / "nq_repo"), "start_date": start, "end_date": end}


def _map(rows):
    return build_ticker_candidate_map(pd.DataFrame(
        [{"security": s, "ticker": parse_security(s)[0], "delisted": parse_security(s)[1],
          "first_bar": pd.Timestamp(f), "last_bar": pd.Timestamp(l), "n_bars": 1}
         for s, f, l in rows]).set_index("security"))


class TestShareClasses:
    """The corpus names share classes with a dot; rosters may use either."""

    @pytest.mark.parametrize("roster", ["BRK.B", "BRK-B"])
    def test_dot_named_file_resolves_from_either_spelling(self, tmp_path, roster):
        _write_parquet(tmp_path / "corpus", "BRK.B", "1996-05-09", "2026-09-28")
        _write_nq_yaml(tmp_path / "nq_repo", 2010, [roster], quote=True)
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")
        schedule = build_membership_schedule("nq100", "2010-01-04", "2010-12-31", cfg)
        assert pit_members_on(schedule, "2010-06-01") == frozenset({"BRK.B"})

    def test_a_genuine_hyphenated_ticker_is_not_rewritten(self):
        m = _map([("BRK-A", "1990-01-02", "2026-09-28")])
        assert resolve_security_id("BRK-A", "2010-06-01", m)[0] == "BRK-A"


class TestRawTickerBeforeAlias:
    """SYMC (Symantec) must not become GEN-201212 (GenOn) via the GEN alias."""

    def _m(self):
        return _map([
            ("GEN", "1990-01-02", "2026-09-28"),          # Gen Digital, back-filled with Symantec
            ("GEN-201212", "2006-01-03", "2012-12-14"),   # GenOn Energy held GEN until 2012
        ])

    def test_symc_resolves_to_the_live_back_filled_file(self):
        assert resolve_security_id("SYMC", "2008-06-30", self._m())[0] == "GEN"

    def test_a_raw_gen_in_2008_still_means_genon(self):
        # The roster ticker IS evidence: GEN in 2008 was GenOn.
        assert resolve_security_id("GEN", "2008-06-30", self._m())[0] == "GEN-201212"


class TestOverrides:

    def test_override_beats_the_tenure_heuristic(self):
        # ES 2009-2013: the tenure rule picks EnergySolutions (ES-201305); the
        # roster member was Northeast Utilities, now Eversource (live ES).
        m = _map([("ES", "1990-01-02", "2026-09-28"), ("ES-201305", "2008-11-14", "2013-05-24")])
        assert resolve_security_id("ES", "2011-06-30", m)[0] == "ES"

    def test_override_whose_target_has_no_bars_fails_instead_of_guessing(self, monkeypatch):
        monkeypatch.setitem(pit.PIT_PARQUET_SECURITY_OVERRIDES, "ZZZ",
                            [("2004-01-01", "2026-12-31", "ZZZQ-202001")])
        m = _map([("ZZZ", "1990-01-02", "2026-09-28")])   # a raw match exists...
        assert resolve_security_id("ZZZ", "2010-06-30", m)[0] is None   # ...but is not used

    def test_override_outside_its_window_does_not_apply(self):
        m = _map([("ES", "1990-01-02", "2026-09-28"), ("ES-201305", "2008-11-14", "2013-05-24")])
        # after the window, ordinary resolution: only live ES covers 2020
        assert resolve_security_id("ES", "2020-06-30", m)[0] == "ES"

    def test_every_override_window_is_ordered_and_names_a_security(self):
        for ticker, windows in pit.PIT_PARQUET_SECURITY_OVERRIDES.items():
            for start, end, target in windows:
                assert pd.Timestamp(start) < pd.Timestamp(end), ticker
                assert target and target == target.strip(), ticker


class TestDateLag:

    def test_single_candidate_a_few_days_out_resolves(self):
        m = _map([("NEWCO", "2015-06-08", "2026-09-28")])
        assert resolve_security_id("NEWCO", "2015-06-03", m)[0] == "NEWCO"

    def test_outside_the_window_aborts(self):
        m = _map([("NEWCO", "2015-06-30", "2026-09-28")])
        assert resolve_security_id("NEWCO", "2015-06-03", m)[0] is None

    def test_two_nearby_candidates_abort(self):
        m = _map([("XY-201506", "2010-01-04", "2015-06-01"), ("XY", "2015-06-08", "2026-09-28")])
        assert resolve_security_id("XY", "2015-06-04", m)[0] is None


class TestYamlBooleans:

    def test_unquoted_on_stays_a_ticker(self):
        data = load_roster_yaml("year: 2023\ntickers_on_Jan_1:\n  - ON\n  - T\n  - NO\n  - YES\n"
                                "changes:\n  2023-06-20:\n    union:\n      - ON\n")
        assert data["tickers_on_Jan_1"] == ["ON", "T", "NO", "YES"]
        assert data["year"] == 2023                                  # ints still parse
        assert str(next(iter(data["changes"]))) == "2023-06-20"      # dates still parse

    @pytest.mark.parametrize("provider", ["parquet", "yahoo"])
    def test_on_semiconductor_is_not_true(self, tmp_path, provider):
        pit._load_year_yaml_cached.cache_clear()
        _write_parquet(tmp_path / "corpus", "ON", "2000-05-01", "2026-09-28")
        _write_nq_yaml(tmp_path / "nq_repo", 2023, ["ON"])           # unquoted, as in the real file
        cfg = _cfg(tmp_path, "2023-01-03", "2023-12-29", provider=provider)
        schedule = build_membership_schedule("nq100", "2023-01-03", "2023-12-29", cfg)
        assert pit_members_on(schedule, "2023-06-01") == frozenset({"ON"})


class TestSecurityIntervals:

    def test_one_roster_ticker_two_securities_keep_separate_spells(self):
        # IR is Ingersoll-Rand plc (now TT) until 2020, then the new Ingersoll Rand.
        schedule = SecuritySchedule(
            [("2018-01-02", frozenset({"TT"})),
             ("2020-03-02", frozenset({"IR"})),
             ("2022-06-01", frozenset())],
            {"TT": {"IR"}, "IR": {"IR"}})
        spells = security_intervals(schedule, "2026-09-28")
        assert spells == {
            "TT": [(pd.Timestamp("2018-01-02"), pd.Timestamp("2020-03-02"))],
            "IR": [(pd.Timestamp("2020-03-02"), pd.Timestamp("2022-06-01"))],
        }

    def test_still_a_member_runs_to_the_end_date(self):
        schedule = SecuritySchedule([("2020-01-02", frozenset({"AAPL"}))])
        assert security_intervals(schedule, "2026-09-28") == {
            "AAPL": [(pd.Timestamp("2020-01-02"), pd.Timestamp("2026-09-28"))]}

    def test_parquet_schedule_records_its_roster_tickers(self, tmp_path):
        _write_parquet(tmp_path / "corpus", "GEN", "1990-01-02", "2026-09-28")
        _write_nq_yaml(tmp_path / "nq_repo", 2010, ["SYMC"], quote=True)
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")
        schedule = build_membership_schedule("nq100", "2010-01-04", "2010-12-31", cfg)
        assert isinstance(schedule, SecuritySchedule)
        assert schedule.roster_tickers == {"GEN": {"SYMC"}}


def test_unresolvable_member_still_aborts(tmp_path):
    """Nothing here weakens abort-on-absence."""
    _write_parquet(tmp_path / "corpus", "AAPL", "1990-01-02", "2026-09-28")
    _write_nq_yaml(tmp_path / "nq_repo", 2010, ["AAPL", "GHOST"], quote=True)
    cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")
    with pytest.raises(PitResolutionError) as exc:
        build_membership_schedule("nq100", "2010-01-04", "2010-12-31", cfg)
    assert {f[0] for f in exc.value.failures} == {"GHOST"}


class TestCorpusRenames:
    """The corpus's _renames.json (norgate-data#16/#18) resolves retired tickers."""

    def _renames(self, tmp_path, entries):
        (tmp_path / "corpus").mkdir(parents=True, exist_ok=True)
        (tmp_path / "corpus" / "_renames.json").write_text(__import__("json").dumps(entries))

    def test_renamed_ticker_resolves_historically_to_the_merged_file(self, tmp_path):
        # After the repair BNY.parquet holds BK's whole history and BK.parquet is gone.
        _write_parquet(tmp_path / "corpus", "BNY", "1990-01-02", "2026-09-28")
        self._renames(tmp_path, [{"old": "BK", "new": "BNY", "date": "2026-05-21"}])
        _write_nq_yaml(tmp_path / "nq_repo", 2010, ["BK"], quote=True)
        cfg = _cfg(tmp_path, "2010-01-04", "2010-12-31")
        schedule = build_membership_schedule("nq100", "2010-01-04", "2010-12-31", cfg)
        assert pit_members_on(schedule, "2010-06-01") == frozenset({"BNY"})

    def test_chains_are_followed(self, tmp_path):
        self._renames(tmp_path, [{"old": "A", "new": "B", "date": "2026-05-01"},
                                 {"old": "B", "new": "C", "date": "2026-07-01"}])
        assert pit.load_corpus_renames(_cfg(tmp_path, "2010-01-04", "2010-12-31"))["A"] == "C"

    def test_stale_duplicate_maps_to_its_dated_security(self):
        m = _map([("SEE-202604", "1990-01-02", "2026-04-08")])
        assert resolve_security_id("SEE", "2015-06-30", m,
                                   corpus_renames={"SEE": "SEE-202604"})[0] == "SEE-202604"

    def test_no_file_means_no_renames(self, tmp_path):
        assert pit.load_corpus_renames(_cfg(tmp_path, "2010-01-04", "2010-12-31")) == {}

    def test_raw_ticker_still_wins_when_it_has_its_own_file(self):
        # A retired ticker later reused by a new company: dates the new file covers go to it.
        m = _map([("BK", "2027-01-04", "2027-06-30"), ("BNY", "1990-01-02", "2026-09-28")])
        assert resolve_security_id("BK", "2027-03-01", m, corpus_renames={"BK": "BNY"})[0] == "BK"
        assert resolve_security_id("BK", "2010-03-01", m, corpus_renames={"BK": "BNY"})[0] == "BNY"
