from pathlib import Path

import pytest

from helpers.point_in_time import (
    normalise_pit_ticker,
    resolve_pit_portfolio,
    tickers_as_of,
    tickers_union_for_period,
    build_membership_schedule,
    pit_members_on,
)


def _write_yaml(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_sp500_tickers_as_of_start_date_with_normalisation(tmp_path):
    root = tmp_path / "sp500_repo"
    _write_yaml(
        root / "src" / "sp500_ticker_history" / "sp500-ticker-changes-2020.yaml",
        """
year: 2020
tickers_on_Jan_1:
  - AAA
  - GOOG
  - PCLN
  - BRK.B
changes:
  '2020-02-01':
    difference:
      - AAA
    union:
      - CCC
  '2020-07-01':
    difference:
      - CCC
    union:
      - DDD
""",
    )

    config = {"sp500_pit_path": str(root)}

    jan_members = tickers_as_of("sp500", "2020-01-15", config)
    assert "BKNG" in jan_members
    assert "GOOG" in jan_members   # GOOG is NOT remapped — both share classes stay distinct
    assert "GOOGL" not in jan_members
    assert "BRK-B" in jan_members
    assert "PCLN" not in jan_members

    june_members = tickers_as_of("s&p500", "2020-06-30", config)
    assert "AAA" not in june_members
    assert "CCC" in june_members
    assert "DDD" not in june_members


def test_nq100_tickers_as_of_uses_n100_yaml_name(tmp_path):
    root = tmp_path / "nq_repo"
    _write_yaml(
        root / "src" / "nasdaq_100_ticker_history" / "n100-ticker-changes-2021.yaml",
        """
year: 2021
tickers_on_Jan_1:
  - AAPL
  - MSFT
changes:
  '2021-03-10':
    difference:
      - MSFT
    union:
      - NVDA
""",
    )

    config = {"nq100_pit_path": str(root)}

    assert tickers_as_of("nq100", "2021-03-09", config) == ["AAPL", "MSFT"]
    assert tickers_as_of("nasdaq-100", "2021-03-10", config) == ["AAPL", "NVDA"]


def test_resolve_pit_portfolio_reads_config_start_date(tmp_path):
    root = tmp_path / "sp500_repo"
    _write_yaml(
        root / "src" / "sp500_ticker_history" / "sp500-ticker-changes-2022.yaml",
        """
year: 2022
tickers_on_Jan_1:
  - AAPL
changes: {}
""",
    )

    config = {"start_date": "2022-04-01", "sp500_pit_path": str(root)}

    assert resolve_pit_portfolio("pit:sp500", config) == ["AAPL"]
    assert resolve_pit_portfolio("sp500_pit", config) is None


def test_missing_pit_yaml_has_friendly_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="No PIT YAML found"):
        tickers_as_of("sp500", "1900-01-01", {"sp500_pit_path": str(tmp_path)})


# ---------------------------------------------------------------------------
# tickers_union_for_period
# ---------------------------------------------------------------------------

_MULTI_YEAR_NQ = """
year: {year}
tickers_on_Jan_1:
  - AAPL
  - MSFT
changes:
  '{year}-06-01':
    difference:
      - MSFT
    union:
      - NVDA_{year}
"""


def _nq_repo_two_years(tmp_path: Path) -> Path:
    root = tmp_path / "nq_repo"
    for yr in (2020, 2021):
        _write_yaml(
            root / "src" / "nasdaq_100_ticker_history" / f"n100-ticker-changes-{yr}.yaml",
            _MULTI_YEAR_NQ.format(year=yr),
        )
    return root


def test_union_includes_all_historical_tickers(tmp_path):
    root = _nq_repo_two_years(tmp_path)
    config = {"nq100_pit_path": str(root)}
    union = tickers_union_for_period("nq100", "2020-01-01", "2021-12-31", config)
    assert "AAPL" in union
    assert "MSFT" in union       # removed during 2020 but WAS in the index
    assert "NVDA_2020" in union  # added during 2020
    assert "NVDA_2021" in union  # added during 2021
    assert union == sorted(set(union))  # result is sorted


def test_union_skips_missing_years_gracefully(tmp_path):
    root = _nq_repo_two_years(tmp_path)
    config = {"nq100_pit_path": str(root)}
    # 2022 YAML does not exist — should not raise, just skip that year
    union = tickers_union_for_period("nq100", "2020-01-01", "2022-12-31", config)
    assert "AAPL" in union  # still returns what's available


def test_union_single_year(tmp_path):
    root = tmp_path / "nq_repo"
    _write_yaml(
        root / "src" / "nasdaq_100_ticker_history" / "n100-ticker-changes-2019.yaml",
        """
year: 2019
tickers_on_Jan_1:
  - AAPL
  - AMZN
changes:
  '2019-09-15':
    difference:
      - AMZN
    union:
      - TSLA
""",
    )
    config = {"nq100_pit_path": str(root)}
    union = tickers_union_for_period("nq100", "2019-01-01", "2019-12-31", config)
    assert set(union) == {"AAPL", "AMZN", "TSLA"}


# ---------------------------------------------------------------------------
# build_membership_schedule and pit_members_on
# ---------------------------------------------------------------------------

_NQ_SCHEDULE_YAML = """
year: 2022
tickers_on_Jan_1:
  - AAPL
  - MSFT
  - GOOG
changes:
  '2022-03-01':
    difference:
      - MSFT
    union:
      - NVDA
  '2022-07-15':
    difference:
      - GOOG
    union:
      - META
"""


def _schedule_config(tmp_path: Path) -> dict:
    root = tmp_path / "nq_repo"
    _write_yaml(
        root / "src" / "nasdaq_100_ticker_history" / "n100-ticker-changes-2022.yaml",
        _NQ_SCHEDULE_YAML,
    )
    return {"nq100_pit_path": str(root)}


def test_schedule_initial_state(tmp_path):
    config = _schedule_config(tmp_path)
    schedule = build_membership_schedule("nq100", "2022-01-01", "2022-12-31", config)
    initial = pit_members_on(schedule, "2022-01-15")
    assert initial == frozenset({"AAPL", "MSFT", "GOOG"})


def test_schedule_after_first_change(tmp_path):
    config = _schedule_config(tmp_path)
    schedule = build_membership_schedule("nq100", "2022-01-01", "2022-12-31", config)
    members = pit_members_on(schedule, "2022-03-01")
    assert "NVDA" in members
    assert "MSFT" not in members
    assert "AAPL" in members


def test_schedule_after_second_change(tmp_path):
    config = _schedule_config(tmp_path)
    schedule = build_membership_schedule("nq100", "2022-01-01", "2022-12-31", config)
    members = pit_members_on(schedule, "2022-08-01")
    assert "META" in members
    assert "GOOG" not in members
    assert "NVDA" in members


def test_schedule_before_first_entry_returns_initial(tmp_path):
    config = _schedule_config(tmp_path)
    schedule = build_membership_schedule("nq100", "2022-01-01", "2022-12-31", config)
    # Query exactly at start_date
    assert pit_members_on(schedule, "2022-01-01") == frozenset({"AAPL", "MSFT", "GOOG"})


def test_schedule_start_date_mid_year(tmp_path):
    """When start_date is mid-year, initial state reflects changes applied up to that date."""
    config = _schedule_config(tmp_path)
    schedule = build_membership_schedule("nq100", "2022-04-01", "2022-12-31", config)
    # 2022-03-01 change should be baked into the initial state
    initial = pit_members_on(schedule, "2022-04-01")
    assert "NVDA" in initial
    assert "MSFT" not in initial
    assert "GOOG" in initial  # second change not yet applied


def test_pit_members_on_before_schedule_returns_empty(tmp_path):
    config = _schedule_config(tmp_path)
    schedule = build_membership_schedule("nq100", "2022-06-01", "2022-12-31", config)
    # Query before the schedule starts
    result = pit_members_on(schedule, "2021-01-01")
    assert result == frozenset()


def test_schedule_spans_multiple_years(tmp_path):
    root = tmp_path / "nq_repo"
    for yr, content in [
        (2021, """
year: 2021
tickers_on_Jan_1:
  - AAPL
changes:
  '2021-06-01':
    difference: []
    union:
      - AMZN
"""),
        (2022, """
year: 2022
tickers_on_Jan_1:
  - AAPL
  - AMZN
changes:
  '2022-03-01':
    union:
      - TSLA
"""),
    ]:
        _write_yaml(
            root / "src" / "nasdaq_100_ticker_history" / f"n100-ticker-changes-{yr}.yaml",
            content,
        )
    config = {"nq100_pit_path": str(root)}
    schedule = build_membership_schedule("nq100", "2021-01-01", "2022-12-31", config)
    assert "AMZN" in pit_members_on(schedule, "2021-07-01")
    assert "TSLA" in pit_members_on(schedule, "2022-04-01")
    assert "TSLA" not in pit_members_on(schedule, "2022-02-01")


def test_normalise_pit_ticker_107_rename_aliases():
    # Added from the #107 roster look-ahead audit: without these aliases the
    # roster ticker resolves to no price series and is silently dropped.
    assert normalise_pit_ticker("SIVB") == "SIVBQ"   # SVB Financial (collapse "Q")
    assert normalise_pit_ticker("CTRP") == "TCOM"    # Ctrip -> Trip.com (2019)
    assert normalise_pit_ticker("RIMM") == "BB"      # Research In Motion -> BlackBerry (2013)


def test_normalise_pit_ticker_passthrough_and_existing():
    # Unmapped tickers pass through (upper-cased, dot->dash); existing aliases hold.
    assert normalise_pit_ticker("aapl") == "AAPL"
    assert normalise_pit_ticker("BRK.B") == "BRK-B"
    assert normalise_pit_ticker("UTX") == "RTX"
    # GOOG/GOOGL must NOT collapse (documented invariant).
    assert normalise_pit_ticker("GOOG") == "GOOG"
    assert normalise_pit_ticker("GOOGL") == "GOOGL"
