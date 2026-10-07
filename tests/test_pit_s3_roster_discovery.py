from pathlib import Path

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
