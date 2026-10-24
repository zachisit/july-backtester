from pathlib import Path

import pandas as pd
import pytest

from helpers import pit_enforcement
from helpers import point_in_time


def _write_year(root: Path, index: str, year: int, tickers: list[str]):
    sub = "sp500_ticker_history" if index == "sp500" else "nasdaq_100_ticker_history"
    prefix = "sp500-ticker-changes" if index == "sp500" else "n100-ticker-changes"
    directory = root / "src" / sub
    directory.mkdir(parents=True, exist_ok=True)
    quoted = "\n".join(f"  - '{ticker}'" for ticker in tickers)
    (directory / f"{prefix}-{year}.yaml").write_text(
        f"tickers_on_Jan_1:\n{quoted}\nchanges: {{}}\n", encoding="utf-8"
    )


def test_year_loader_discovers_s3_roster_beside_parquet_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("SP500_DATA_ROOT", raising=False)
    price_dir = tmp_path / "parquet_data" / "data"
    roster = tmp_path / "parquet_data" / "pit" / "sp500"
    _write_year(roster, "sp500", 2026, ["SKYD"])
    path = point_in_time._find_year_yaml(
        "sp500", 2026, {"parquet_data_dir": str(price_dir)}
    )
    assert path.is_file()
    assert roster in path.parents


def test_daily_enforcement_discovers_s3_roster_without_env(tmp_path, monkeypatch):
    monkeypatch.delenv("NQ100_DATA_ROOT", raising=False)
    price_dir = tmp_path / "parquet_data" / "data"
    roster = tmp_path / "parquet_data" / "pit" / "nq100"
    _write_year(roster, "nq100", 2004, ["AAPL"])
    intervals = pit_enforcement.membership_intervals(
        "pit:nq100",
        {"start_date": "2004-01-02", "end_date": "2004-01-30", "parquet_data_dir": str(price_dir)},
    )
    assert "AAPL" in intervals


@pytest.mark.parametrize("index", ["sp500", "nq100"])
@pytest.mark.parametrize("missing_year", [2005, 2006])
def test_daily_enforcement_skips_partial_mirror_and_preserves_removal(
    tmp_path, monkeypatch, caplog, index, missing_year,
):
    monkeypatch.delenv("SP500_DATA_ROOT", raising=False)
    monkeypatch.delenv("NQ100_DATA_ROOT", raising=False)
    partial = tmp_path / "pit" / index
    complete = tmp_path / "complete" / index
    for year in range(2004, 2007):
        _write_year(complete, index, year, ["XOM"])
        if year != missing_year:
            _write_year(partial, index, year, ["XOM"])
    sub = "sp500_ticker_history" if index == "sp500" else "nasdaq_100_ticker_history"
    prefix = "sp500-ticker-changes" if index == "sp500" else "n100-ticker-changes"
    (complete / "src" / sub / f"{prefix}-2005.yaml").write_text(
        "tickers_on_Jan_1: ['XOM']\nchanges:\n"
        "  '2005-06-01':\n    union: []\n    difference: ['XOM']\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        point_in_time, "_candidate_roots", lambda *_: [partial, complete],
    )

    intervals = pit_enforcement.membership_intervals(
        f"pit:{index}", {"start_date": "2004-01-02", "end_date": "2006-12-29"},
    )

    assert intervals["XOM"] == [(pd.Timestamp("2004-01-02"), pd.Timestamp("2005-06-01"))]
    assert f"missing year {missing_year}" in caplog.text
    assert str(partial) in caplog.text
    assert "Re-sync" in caplog.text
    forced = pit_enforcement.build_forced_exit_mask(
        pd.DatetimeIndex(["2005-05-31", "2005-06-01"]),
        intervals["XOM"], "2006-12-29",
    )
    assert forced.iloc[-1]


def test_auto_discovery_requires_only_years_through_run_end(tmp_path, monkeypatch):
    monkeypatch.delenv("SP500_DATA_ROOT", raising=False)
    root = tmp_path / "pit" / "sp500"
    for year in (2004, 2005):
        _write_year(root, "sp500", year, ["XOM"])
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [root])

    intervals = pit_enforcement.membership_intervals(
        "pit:sp500", {"start_date": "2005-01-03", "end_date": "2005-12-30"},
    )

    assert intervals["XOM"] == [(pd.Timestamp("2005-01-03"), pd.Timestamp("2005-12-30"))]


def test_explicit_incomplete_roster_warns_about_missing_year(tmp_path, caplog):
    _write_year(tmp_path, "sp500", 2004, ["XOM"])

    pit_enforcement.membership_intervals(
        "pit:sp500",
        {"start_date": "2004-01-02", "end_date": "2005-12-30", "sp500_pit_path": str(tmp_path)},
    )

    assert "PIT membership history is incomplete" in caplog.text
    assert "sp500-ticker-changes-2005.yaml" in caplog.text
    assert "Re-sync" in caplog.text


def test_daily_enforcement_skips_empty_s3_mirror(tmp_path, monkeypatch):
    monkeypatch.delenv("SP500_DATA_ROOT", raising=False)
    empty_mirror = tmp_path / "pit" / "sp500"
    empty_mirror.mkdir(parents=True)
    valid_repo = tmp_path / "valid_sp500"
    _write_year(valid_repo, "sp500", 2004, ["AAPL"])
    monkeypatch.setattr(
        point_in_time, "_candidate_roots",
        lambda index, config: [empty_mirror, valid_repo],
    )

    intervals = pit_enforcement.membership_intervals(
        "pit:sp500",
        {"start_date": "2004-01-02", "end_date": "2004-01-30"},
    )

    assert "AAPL" in intervals


# ---------------------------------------------------------------------------
# #422 review: one roster, one completeness rule, for every reader
# ---------------------------------------------------------------------------

def _xom_roster(root: Path, index: str, years=(2004, 2005, 2006), sub=None):
    """XOM a member from 2004, removed 2005-06-01; AAPL a member throughout."""
    sub = sub or ("sp500_ticker_history" if index == "sp500" else "nasdaq_100_ticker_history")
    prefix = "sp500-ticker-changes" if index == "sp500" else "n100-ticker-changes"
    d = root / "src" / sub
    d.mkdir(parents=True, exist_ok=True)
    for year in years:
        body = ("tickers_on_Jan_1: ['AAPL', 'XOM']\nchanges: {}\n" if year == 2004 else
                "tickers_on_Jan_1: ['AAPL', 'XOM']\nchanges:\n"
                "  '2005-06-01':\n    union: []\n    difference: ['XOM']\n" if year == 2005 else
                "tickers_on_Jan_1: ['AAPL']\nchanges: {}\n")
        (d / f"{prefix}-{year}.yaml").write_text(body, encoding="utf-8")


@pytest.fixture
def _no_env(monkeypatch):
    monkeypatch.delenv("SP500_DATA_ROOT", raising=False)
    monkeypatch.delenv("NQ100_DATA_ROOT", raising=False)


@pytest.mark.parametrize("provider", ["yahoo", "parquet"])
@pytest.mark.parametrize("index", ["sp500", "nq100"])
def test_partial_mirror_as_only_root_aborts_every_reader(tmp_path, monkeypatch, _no_env,
                                                         index, provider):
    # The owner's repro: the partial S3 mirror is the ONLY roster on disk.
    # Before the fix the schedule kept XOM a member to the end of the run and
    # enforcement returned {} -- no forced exit, one warning line.
    partial = tmp_path / "pit" / index
    _xom_roster(partial, index, years=(2004, 2006))
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [partial])
    cfg = {"start_date": "2004-01-02", "end_date": "2006-12-29", "data_provider": provider}

    with pytest.raises(point_in_time.PitRosterError, match="missing 2005"):
        point_in_time.build_membership_schedule(index, cfg["start_date"], cfg["end_date"], cfg)
    with pytest.raises(point_in_time.PitRosterError):
        point_in_time.tickers_union_for_period(index, cfg["start_date"], cfg["end_date"], cfg)
    with pytest.raises(point_in_time.PitRosterError):
        pit_enforcement.membership_intervals(f"pit:{index}", cfg)


@pytest.mark.parametrize("index", ["sp500", "nq100"])
def test_schedule_and_intervals_read_the_same_complete_roster(tmp_path, monkeypatch, _no_env, index):
    partial, complete = tmp_path / "pit" / index, tmp_path / "complete" / index
    _xom_roster(partial, index, years=(2004, 2006))
    _xom_roster(complete, index)
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [partial, complete])
    cfg = {"start_date": "2004-01-02", "end_date": "2006-12-29", "data_provider": "yahoo"}

    schedule = point_in_time.build_membership_schedule(index, cfg["start_date"], cfg["end_date"], cfg)
    assert "XOM" in point_in_time.pit_members_on(schedule, "2005-05-31")
    assert "XOM" not in point_in_time.pit_members_on(schedule, "2006-06-01")
    intervals = pit_enforcement.membership_intervals(f"pit:{index}", cfg)
    assert intervals["XOM"] == [(pd.Timestamp("2004-01-02"), pd.Timestamp("2005-06-01"))]


def test_unpublished_current_year_does_not_reject_a_complete_mirror(tmp_path, monkeypatch, _no_env):
    # Early-January run: 2006's roster is not out yet. That must not discard
    # 2004-2005 (and with them XOM's removal).
    root = tmp_path / "pit" / "sp500"
    _xom_roster(root, "sp500", years=(2004, 2005))
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [root])
    monkeypatch.setattr(point_in_time, "_latest_published_year", lambda: 2005)
    cfg = {"start_date": "2004-01-02", "end_date": "2006-01-13", "data_provider": "yahoo"}

    intervals = pit_enforcement.membership_intervals("pit:sp500", cfg)
    assert intervals["XOM"] == [(pd.Timestamp("2004-01-02"), pd.Timestamp("2005-06-01"))]
    schedule = point_in_time.build_membership_schedule("sp500", cfg["start_date"], cfg["end_date"], cfg)
    assert "XOM" not in point_in_time.pit_members_on(schedule, "2006-01-13")


def test_unpublished_year_is_still_required_once_published(tmp_path, monkeypatch, _no_env):
    root = tmp_path / "pit" / "sp500"
    _xom_roster(root, "sp500", years=(2004, 2005))
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [root])
    monkeypatch.setattr(point_in_time, "_latest_published_year", lambda: 2006)
    with pytest.raises(point_in_time.PitRosterError, match="missing 2006"):
        point_in_time.select_roster("sp500", 2006, {})


@pytest.mark.parametrize("source", ["config", "env"])
def test_explicit_root_wins_over_discovered_mirror(tmp_path, monkeypatch, _no_env, source):
    price_dir = tmp_path / "parquet_data" / "data"
    mirror = tmp_path / "parquet_data" / "pit" / "sp500"
    explicit = tmp_path / "explicit"
    _xom_roster(mirror, "sp500")
    _xom_roster(explicit, "sp500")
    cfg = {"parquet_data_dir": str(price_dir)}
    if source == "config":
        cfg["sp500_pit_path"] = str(explicit)
    else:
        monkeypatch.setenv("SP500_DATA_ROOT", str(explicit))
    directory, _ = point_in_time.select_roster("sp500", 2006, cfg)
    assert explicit in directory.parents


def test_discovered_mirror_wins_over_bundled_roster(tmp_path, monkeypatch, _no_env):
    price_dir = tmp_path / "parquet_data" / "data"
    mirror = tmp_path / "parquet_data" / "pit" / "sp500"
    _xom_roster(mirror, "sp500")
    bundled = tmp_path / "bundled"
    _xom_roster(bundled, "sp500")
    monkeypatch.setattr(point_in_time, "ROOT", bundled)
    directory, _ = point_in_time.select_roster("sp500", 2006, {"parquet_data_dir": str(price_dir)})
    assert mirror in directory.parents


def test_nq100_reads_the_layout_that_was_checked(tmp_path, monkeypatch, _no_env):
    # Incomplete first layout + complete second layout under one root: the
    # completeness check and the reader must agree on the second.
    root = tmp_path / "nq"
    _xom_roster(root, "nq100", years=(2004,), sub="nasdaq_100_ticker_history")
    _xom_roster(root, "nq100", sub="nasdaq100_ticker_history")
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [root])
    cfg = {"start_date": "2004-01-02", "end_date": "2006-12-29"}
    intervals = pit_enforcement.membership_intervals("pit:nq100", cfg)
    assert intervals["XOM"] == [(pd.Timestamp("2004-01-02"), pd.Timestamp("2005-06-01"))]


def test_no_roster_at_all_raises_for_schedule_but_keeps_enforcement_fallback(tmp_path, monkeypatch, _no_env):
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [tmp_path / "nothing"])
    cfg = {"start_date": "2004-01-02", "end_date": "2004-12-31", "data_provider": "yahoo"}
    with pytest.raises(point_in_time.PitRosterError, match="No sp500 PIT roster found"):
        point_in_time.build_membership_schedule("sp500", cfg["start_date"], cfg["end_date"], cfg)
    assert pit_enforcement.membership_intervals("pit:sp500", cfg) == {}


def test_run_ending_this_year_accepts_mirror_without_this_years_file(tmp_path, monkeypatch, _no_env):
    # Unpatched clock: a mirror complete through last year is complete for a
    # run whose end_date (config default style) is in the current year.
    import datetime
    this_year = datetime.date.today().year
    root = tmp_path / "pit" / "sp500"
    for year in range(2004, this_year):
        _write_year(root, "sp500", year, ["AAPL"])
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [root])
    directory, _ = point_in_time.select_roster("sp500", this_year, {})
    assert root in directory.parents


@pytest.mark.parametrize("provider", ["yahoo", "parquet"])
@pytest.mark.parametrize("index", ["sp500", "nq100"])
def test_run_starting_in_unpublished_year_keeps_prior_membership(
    tmp_path, monkeypatch, _no_env, index, provider,
):
    root = tmp_path / "pit" / index
    _xom_roster(root, index, years=(2004, 2005))
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [root])
    monkeypatch.setattr(point_in_time, "_latest_published_year", lambda: 2005)
    # Isolate roster replay; security-ID resolution is separately covered.
    if provider == "parquet":
        monkeypatch.setattr(point_in_time, "resolve_schedule_to_securities",
                            lambda schedule, config: schedule)
    cfg = {"start_date": "2006-01-02", "end_date": "2006-01-13",
           "data_provider": provider}
    schedule = point_in_time.build_membership_schedule(
        index, cfg["start_date"], cfg["end_date"], cfg)
    assert schedule == [(cfg["start_date"], frozenset({"AAPL"}))]
    assert "AAPL" in point_in_time.tickers_union_for_period(
        index, cfg["start_date"], cfg["end_date"], cfg)
    intervals = pit_enforcement.membership_intervals(f"pit:{index}", cfg)
    assert "AAPL" in intervals
    assert "XOM" not in intervals


def _year_path(root, index, year):
    sub = "sp500_ticker_history" if index == "sp500" else "nasdaq_100_ticker_history"
    prefix = "sp500-ticker-changes" if index == "sp500" else "n100-ticker-changes"
    return root / "src" / sub / f"{prefix}-{year}.yaml"


@pytest.mark.parametrize("bad_yaml", [
    "", "{}", "[broken", "tickers_on_Jan_1: AAPL\nchanges: {}\n",
    "tickers_on_Jan_1: [AAPL]\nchanges: []\n",
])
@pytest.mark.parametrize("provider", ["yahoo", "parquet"])
@pytest.mark.parametrize("index", ["sp500", "nq100"])
def test_invalid_annual_mirror_falls_back_without_losing_removals(
    tmp_path, monkeypatch, _no_env, caplog, index, provider, bad_yaml,
):
    partial, complete = tmp_path / "partial", tmp_path / "complete"
    for root in (partial, complete):
        _xom_roster(root, index)
    _year_path(partial, index, 2005).write_text(bad_yaml, encoding="utf-8")
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [partial, complete])
    prices = tmp_path / "prices"
    prices.mkdir()
    dates = pd.bdate_range("2004-01-02", "2006-12-29", name="Datetime")
    for symbol in ("AAPL", "XOM"):
        pd.DataFrame({"Open": 100., "High": 101., "Low": 99., "Close": 100.,
                      "Volume": 1e6}, index=dates).to_parquet(prices / f"{symbol}.parquet")
    cfg = {"start_date": "2004-01-02", "end_date": "2006-12-29",
           "data_provider": provider, "parquet_data_dir": str(prices)}
    schedule = point_in_time.build_membership_schedule(
        index, cfg["start_date"], cfg["end_date"], cfg)
    assert "XOM" in point_in_time.pit_members_on(schedule, "2005-05-31")
    assert "XOM" not in point_in_time.pit_members_on(schedule, "2005-06-02")
    assert "Ignoring invalid" in caplog.text
    intervals = pit_enforcement.membership_intervals(f"pit:{index}", cfg)
    assert intervals["XOM"] == [(pd.Timestamp("2004-01-02"), pd.Timestamp("2005-06-01"))]
    if provider == "parquet":
        spells = point_in_time.security_intervals(schedule, cfg["end_date"])
        assert spells["XOM"][0][1] == pd.Timestamp("2005-06-01")


@pytest.mark.parametrize("bad_yaml", ["", "[broken"])
@pytest.mark.parametrize("index", ["sp500", "nq100"])
def test_invalid_only_roster_aborts_every_reader(tmp_path, monkeypatch, _no_env, index, bad_yaml):
    _xom_roster(tmp_path, index)
    _year_path(tmp_path, index, 2005).write_text(bad_yaml, encoding="utf-8")
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [tmp_path])
    cfg = {"start_date": "2004-01-02", "end_date": "2006-12-29"}
    for reader in (point_in_time.build_membership_schedule, point_in_time.tickers_union_for_period):
        with pytest.raises(point_in_time.PitRosterError, match="invalid"):
            reader(index, cfg["start_date"], cfg["end_date"], cfg)
    with pytest.raises(point_in_time.PitRosterError, match="invalid"):
        pit_enforcement.membership_intervals(f"pit:{index}", cfg)


@pytest.mark.parametrize("index", ["sp500", "nq100"])
def test_explicit_invalid_roster_aborts_instead_of_falling_back(tmp_path, monkeypatch, _no_env, index):
    bad, good = tmp_path / "bad", tmp_path / "good"
    for root in (bad, good):
        _xom_roster(root, index)
    _year_path(bad, index, 2005).write_text("{}", encoding="utf-8")
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [bad, good])
    with pytest.raises(point_in_time.PitRosterError, match="invalid"):
        point_in_time.select_roster(index, 2006, {f"{index}_pit_path": str(bad)})


@pytest.mark.parametrize("index", ["sp500", "nq100"])
def test_present_but_invalid_optional_current_year_is_rejected(tmp_path, monkeypatch, _no_env, index):
    _xom_roster(tmp_path, index)
    _year_path(tmp_path, index, 2006).write_text("", encoding="utf-8")
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [tmp_path])
    monkeypatch.setattr(point_in_time, "_latest_published_year", lambda: 2005)
    with pytest.raises(point_in_time.PitRosterError, match="invalid"):
        point_in_time.select_roster(index, 2006)


@pytest.mark.parametrize("index", ["sp500", "nq100"])
def test_unquoted_yaml_change_dates_apply_to_the_schedule(tmp_path, monkeypatch, _no_env, index):
    _xom_roster(tmp_path, index)
    path = _year_path(tmp_path, index, 2005)
    path.write_text(path.read_text().replace("'2005-06-01'", "2005-06-01"), encoding="utf-8")
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [tmp_path])
    schedule = point_in_time.build_membership_schedule(index, "2004-01-02", "2006-12-29")
    assert "XOM" not in point_in_time.pit_members_on(schedule, "2005-06-02")
    late = point_in_time.build_membership_schedule(index, "2005-07-01", "2006-12-29")
    assert "XOM" not in late[0][1]


@pytest.mark.parametrize("change_date", ["20050601", "2005-W22-3", "2005-99-99"])
@pytest.mark.parametrize("index", ["sp500", "nq100"])
def test_noncanonical_change_dates_are_rejected(tmp_path, monkeypatch, _no_env, index, change_date):
    _xom_roster(tmp_path, index)
    path = _year_path(tmp_path, index, 2005)
    path.write_text(path.read_text().replace("'2005-06-01'", repr(change_date)), encoding="utf-8")
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [tmp_path])
    with pytest.raises(point_in_time.PitRosterError, match="YYYY-MM-DD"):
        point_in_time.select_roster(index, 2006)


@pytest.mark.parametrize("index", ["sp500", "nq100"])
def test_mixed_quoted_and_unquoted_dates_agree_across_readers(tmp_path, monkeypatch, _no_env, index):
    _xom_roster(tmp_path, index, years=(2004, 2005))
    path = _year_path(tmp_path, index, 2005)
    path.write_text(path.read_text() +
                    "  2005-09-01:\n    union: ['XOM']\n    difference: []\n", encoding="utf-8")
    monkeypatch.setattr(point_in_time, "_candidate_roots", lambda *_: [tmp_path])
    cfg = {"start_date": "2004-01-02", "end_date": "2005-12-30"}
    schedule = point_in_time.build_membership_schedule(index, cfg["start_date"], cfg["end_date"], cfg)
    assert "XOM" not in point_in_time.pit_members_on(schedule, "2005-07-01")
    assert "XOM" in point_in_time.pit_members_on(schedule, "2005-10-01")
    intervals = pit_enforcement.membership_intervals(f"pit:{index}", cfg)
    assert intervals["XOM"] == [
        (pd.Timestamp("2004-01-02"), pd.Timestamp("2005-06-01")),
        (pd.Timestamp("2005-09-01"), pd.Timestamp("2005-12-30")),
    ]
