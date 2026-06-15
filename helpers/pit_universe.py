# helpers/pit_universe.py
"""
Point-in-time universe loader for survivorship-bias-free backtesting.

Supports two indices:
  - S&P 500  : reads per-year YAML files from the SP500-Survivorship-bias-data repo
  - Nasdaq-100: reads data/nq100_membership.parquet (bundled in the backtester repo)

Public API
----------
get_sp500_tickers_in_period(start_date, end_date, repo_path) -> list[str]
    All S&P 500 tickers active at any point during [start_date, end_date].

get_nq100_tickers_in_period(start_date, end_date, parquet_path) -> list[str]
    All NQ100 tickers active at any point during [start_date, end_date].

Both functions return a sorted deduplicated list — the UNION of all historical
members during the period. This is the standard survivorship-bias-free approach:
every ticker that ever belonged to the index gets tested; only tickers that were
never in the index during the period are excluded.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# YAML 1.1 booleans that match real S&P 500 tickers (T=AT&T, ON=ON Semi, etc.)
# We store these as quoted strings in the YAML, so yaml.safe_load returns them
# as str — but keep this mapping handy for raw-text fallback parsing.
_YAML_BOOL_TICKERS = {"true": "T", "false": "F", "on": "ON", "off": "OFF",
                      "yes": "Y", "no": "N"}

_YAML_SUFFIX_RE = re.compile(r"-\d{6}$")


def _normalise(tickers: set) -> list:
    """Map historical membership tickers -> the ticker merged/ actually carries
    (e.g. UTX->RTX), then sort+dedup. Shares the single alias source of truth in
    helpers/point_in_time.py. Falls back to identity if that module is unavailable."""
    try:
        from helpers.point_in_time import normalise_pit_ticker as _n
    except Exception:
        return sorted({str(t).strip().upper() for t in tickers})
    return sorted({_n(t) for t in tickers})


# ---------------------------------------------------------------------------
# S&P 500 — YAML-based
# ---------------------------------------------------------------------------

def _load_sp500_yaml(path: Path) -> dict:
    """Load a single sp500-ticker-changes-YYYY.yaml file safely."""
    try:
        import yaml
        with open(path, encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:
        logger.warning(f"[pit_universe] Could not load {path.name}: {exc}")
        return {}


def _apply_year_changes(members: set, data: dict) -> set:
    """Apply all change entries from a year's YAML data to a membership set."""
    changes = data.get("changes") or {}
    for date_str in sorted(changes.keys()):
        entry = changes[date_str]
        removed = {str(t) for t in (entry.get("difference") or [])}
        added = {str(t) for t in (entry.get("union") or [])}
        members = (members - removed) | added
    return members


def build_sp500_pit_snapshots(
    dates: "list[str]",
    repo_path: str,
) -> "dict[str, frozenset]":
    """
    Given a sorted list of date strings (YYYY-MM-DD), return
    {date_str: frozenset_of_sp500_members} for each date.

    Efficient: walks YAML changes once in chronological order,
    recording membership at each requested date.
    """
    if not dates:
        return {}

    yaml_dir    = Path(repo_path) / "src" / "sp500_ticker_history"
    start_year  = int(dates[0][:4])
    end_year    = int(dates[-1][:4])

    # build a flat sorted list of (date_str, added, removed) change events
    all_changes: list = []  # (date_str, added_set, removed_set)
    members_at_start: set = set()

    for year in range(2004, end_year + 1):   # walk from 2004 so membership is seeded
        yaml_path = yaml_dir / f"sp500-ticker-changes-{year}.yaml"
        if not yaml_path.exists():
            continue
        data = _load_sp500_yaml(yaml_path)
        if not data:
            continue
        jan1 = {str(t) for t in (data.get("tickers_on_Jan_1") or [])}
        if year == 2004:
            members_at_start = jan1
        changes = data.get("changes") or {}
        for date_str in sorted(changes.keys()):
            entry   = changes[date_str]
            removed = {str(t) for t in (entry.get("difference") or [])}
            added   = {str(t) for t in (entry.get("union")      or [])}
            all_changes.append((date_str, added, removed))

    # walk forward: at each requested date, record the current membership
    current   = set(members_at_start)
    change_i  = 0
    result    = {}
    sorted_dates = sorted(dates)

    for qdate in sorted_dates:
        # apply all changes up to and including qdate
        while change_i < len(all_changes) and all_changes[change_i][0] <= qdate:
            _, added, removed = all_changes[change_i]
            current = (current - removed) | added
            change_i += 1
        result[qdate] = frozenset(current)

    return result


def get_sp500_tickers_in_period(
    start_date: str,
    end_date: str,
    repo_path: str,
) -> list[str]:
    """
    Return the UNION of all S&P 500 tickers that were members at any point
    during [start_date, end_date].

    Parameters
    ----------
    start_date : "YYYY-MM-DD"
    end_date   : "YYYY-MM-DD"
    repo_path  : absolute path to the SP500-Survivorship-bias-data repo root
                 (the folder that contains src/sp500_ticker_history/)

    Returns
    -------
    Sorted list of unique ticker strings.
    """
    yaml_dir = Path(repo_path) / "src" / "sp500_ticker_history"
    if not yaml_dir.is_dir():
        logger.error(
            f"[pit_universe] SP500 YAML directory not found: {yaml_dir}\n"
            "  Set SP500_DATA_ROOT in .env to the repo root path."
        )
        return []

    start_year = int(start_date[:4])
    end_year = int(end_date[:4])

    all_tickers: set[str] = set()
    current_members: set[str] = set()

    for year in range(start_year, end_year + 1):
        yaml_path = yaml_dir / f"sp500-ticker-changes-{year}.yaml"
        if not yaml_path.exists():
            logger.warning(f"[pit_universe] Missing YAML for {year}: {yaml_path.name}")
            continue

        data = _load_sp500_yaml(yaml_path)
        if not data:
            continue

        jan1 = {str(t) for t in (data.get("tickers_on_Jan_1") or [])}

        if year == start_year:
            # Seed: membership at Jan 1 of the start year is already the
            # universe as of the closest known date before start_date.
            current_members = jan1

        # All Jan-1 members for this year are candidates
        all_tickers |= jan1

        # Apply changes and collect every ticker touched
        changes = data.get("changes") or {}
        for date_str in sorted(changes.keys()):
            if date_str > end_date:
                break
            entry = changes[date_str]
            added = {str(t) for t in (entry.get("union") or [])}
            removed = {str(t) for t in (entry.get("difference") or [])}
            if date_str >= start_date:
                all_tickers |= added  # tickers added during the period
            current_members = (current_members - removed) | added

    n = len(all_tickers)
    logger.info(
        f"[pit_universe] S&P 500 PIT universe {start_date}→{end_date}: "
        f"{n} unique tickers (union of all members in period)"
    )
    return _normalise(all_tickers)


# ---------------------------------------------------------------------------
# Nasdaq-100 — parquet-based
# ---------------------------------------------------------------------------

def get_nq100_tickers_in_period(
    start_date: str,
    end_date: str,
    parquet_path: str | None = None,
) -> list[str]:
    """
    Return the UNION of all NQ100 tickers that were members at any point
    during [start_date, end_date].

    Parameters
    ----------
    start_date    : "YYYY-MM-DD"
    end_date      : "YYYY-MM-DD"
    parquet_path  : path to nq100_membership.parquet
                    Defaults to <repo_root>/data/nq100_membership.parquet

    Returns
    -------
    Sorted list of unique ticker strings.
    """
    if parquet_path is None:
        parquet_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "nq100_membership.parquet",
        )

    if not os.path.isfile(parquet_path):
        logger.error(
            f"[pit_universe] NQ100 membership parquet not found: {parquet_path}"
        )
        return []

    try:
        import pandas as pd
        df = pd.read_parquet(parquet_path)
    except Exception as exc:
        logger.error(f"[pit_universe] Could not read nq100_membership.parquet: {exc}")
        return []

    # Filter to the requested date range
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    mask = (df["date"] >= start_date) & (df["date"] <= end_date)
    df_period = df[mask]

    if df_period.empty:
        logger.warning(
            f"[pit_universe] No NQ100 membership data in range "
            f"{start_date}→{end_date}"
        )
        return []

    all_tickers: set[str] = set()
    for tickers_json in df_period["tickers_json"]:
        try:
            tickers = json.loads(tickers_json)
            all_tickers.update(str(t) for t in tickers)
        except Exception:
            pass

    n = len(all_tickers)
    logger.info(
        f"[pit_universe] NQ100 PIT universe {start_date}→{end_date}: "
        f"{n} unique tickers (union of all members in period)"
    )
    return _normalise(all_tickers)
