"""Point-in-time index membership helpers.

This module is the small public API used by the main backtester for
survivorship-bias-free portfolio definitions such as ``pit:nq100`` and
``pit:sp500``. It intentionally keeps static JSON portfolios unchanged.

Public API
----------
tickers_union_for_period(index, start_date, end_date, config)
    Returns all tickers that were ever in the index between start_date and
    end_date.  Use this to build a survivorship-bias-free ticker universe
    that includes delisted / removed constituents.

build_membership_schedule(index, start_date, end_date, config)
    Returns a sorted list of (effective_date, frozenset_of_members) snapshots
    covering [start_date, end_date].  Precompute once per portfolio; query
    cheaply per date with pit_members_on().

pit_members_on(schedule, date)
    Binary-search the schedule for membership on an ISO date string.
"""

from __future__ import annotations

import bisect
import os
from functools import lru_cache
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]

INDEX_ALIASES = {
    "nq100": "nq100",
    "nasdaq100": "nq100",
    "nasdaq-100": "nq100",
    "ndx": "nq100",
    "sp500": "sp500",
    "s&p500": "sp500",
    "s&p-500": "sp500",
    "s&p_500": "sp500",
}

INDEX_DIR_NAMES = {
    "nq100": ["nq100", "nasdaq100", "nasdaq_100"],
    "sp500": ["sp500", "sp-500", "s-and-p-500"],
}

INDEX_FILE_PREFIXES = {
    "nq100": ["n100-ticker-changes", "nasdaq100-ticker-changes"],
    "sp500": ["sp500-ticker-changes"],
}

PIT_TICKER_NORMALISATION = {
    # Common historical/modern symbol aliases seen in the public PIT repos and
    # price-provider stores. These are deliberately conservative; provider-level
    # ticker mapping remains a separate concern for deeper Norgate work.
    #
    # GOOG / GOOGL note: Google split into two share classes in April 2014.
    # Post-split NQ100 YAML files list BOTH GOOG (Class C) and GOOGL (Class A)
    # as distinct members. Mapping GOOG -> GOOGL would silently collapse them,
    # dropping one position with no warning. The mapping is intentionally absent
    # here; both symbols pass through unchanged.
    "PCLN": "BKNG",
    "HANS": "MNST",
}


def _canonical_index(index: str) -> str:
    key = str(index).strip().lower()
    if key not in INDEX_ALIASES:
        raise ValueError(f"Unknown PIT index '{index}'. Expected one of: nq100, sp500")
    return INDEX_ALIASES[key]


def normalise_pit_ticker(symbol: str, date: str | None = None) -> str:
    """Return the ticker format expected by local price providers.

    ``date`` is accepted for future date-aware mappings; current mappings are
    stable aliases used by the available PIT repositories.
    """
    sym = str(symbol).strip().upper().replace(".", "-")
    return PIT_TICKER_NORMALISATION.get(sym, sym)


def _candidate_roots(index: str, config: dict | None = None) -> list[Path]:
    config = config or {}
    roots: list[Path] = []

    if index == "sp500":
        for key in ("sp500_pit_path", "sp500_data_root"):
            if config.get(key):
                roots.append(Path(config[key]))
        if os.environ.get("SP500_DATA_ROOT"):
            roots.append(Path(os.environ["SP500_DATA_ROOT"]))
    else:
        for key in ("nq100_pit_path", "nq100_data_root"):
            if config.get(key):
                roots.append(Path(config[key]))
        if os.environ.get("NQ100_DATA_ROOT"):
            roots.append(Path(os.environ["NQ100_DATA_ROOT"]))

    pit_base = ROOT / "tickers_to_scan" / "point_in_time"
    for name in INDEX_DIR_NAMES[index]:
        roots.append(pit_base / name)

    roots.append(ROOT)

    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        resolved = root.expanduser()
        if resolved not in seen:
            out.append(resolved)
            seen.add(resolved)
    return out


def _yaml_dirs_for_root(root: Path, index: str) -> Iterable[Path]:
    yield root
    if index == "sp500":
        yield root / "src" / "sp500_ticker_history"
    else:
        yield root / "src" / "nasdaq_100_ticker_history"
        yield root / "src" / "nasdaq100_ticker_history"


def _find_year_yaml(index: str, year: int, config: dict | None = None) -> Path:
    prefixes = INDEX_FILE_PREFIXES[index]
    for root in _candidate_roots(index, config):
        for directory in _yaml_dirs_for_root(root, index):
            if not directory.is_dir():
                continue
            for prefix in prefixes:
                path = directory / f"{prefix}-{year}.yaml"
                if path.exists():
                    return path
    raise FileNotFoundError(
        f"No PIT YAML found for {index} {year}. Configure "
        f"{'SP500_DATA_ROOT' if index == 'sp500' else 'NQ100_DATA_ROOT'} "
        "or place files under tickers_to_scan/point_in_time/."
    )


@lru_cache(maxsize=512)
def _load_year_yaml_cached(path_str: str) -> dict:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required for point-in-time universe loading.") from exc

    with open(path_str, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _load_year_yaml(path: Path) -> dict:
    return _load_year_yaml_cached(str(path.resolve()))


def tickers_as_of(index: str, date: str, config: dict | None = None) -> list[str]:
    """Return the PIT members of ``index`` on ``date``.

    Parameters
    ----------
    index:
        ``"nq100"`` or ``"sp500"``.
    date:
        ISO date string. The membership includes changes effective on that date.
    config:
        Optional backtester config. Recognised path keys:
        ``sp500_pit_path`` and ``nq100_pit_path``.
    """
    idx = _canonical_index(index)
    qdate = str(date)[:10]
    year = int(qdate[:4])
    path = _find_year_yaml(idx, year, config)
    data = _load_year_yaml(path)

    members = {normalise_pit_ticker(t, qdate) for t in (data.get("tickers_on_Jan_1") or [])}
    changes = data.get("changes") or {}
    for change_date in sorted(str(d) for d in changes.keys()):
        if change_date > qdate:
            break
        entry = changes[change_date] or {}
        removed = {normalise_pit_ticker(t, change_date) for t in (entry.get("difference") or [])}
        added = {normalise_pit_ticker(t, change_date) for t in (entry.get("union") or [])}
        members = (members - removed) | added

    return sorted(members)


def resolve_pit_portfolio(value: str, config: dict) -> list[str] | None:
    """Resolve ``pit:<index>`` portfolio values; return ``None`` otherwise."""
    if not isinstance(value, str) or not value.startswith("pit:"):
        return None
    index = value.split(":", 1)[1]
    return tickers_as_of(index, config["start_date"], config)


# ---------------------------------------------------------------------------
# Full-history union and membership schedule (survivorship-bias-free engine)
# ---------------------------------------------------------------------------

def tickers_union_for_period(
    index: str,
    start_date: str,
    end_date: str,
    config: dict | None = None,
) -> list[str]:
    """Return every ticker that was ever in *index* between *start_date* and *end_date*.

    This builds a survivorship-bias-free universe: it includes companies that
    were later removed, delisted, or acquired, as long as they were members of
    the index at some point during the requested period.

    Parameters
    ----------
    index       : ``"nq100"`` or ``"sp500"``
    start_date  : ISO date string (``"2004-01-01"``)
    end_date    : ISO date string (``"2026-01-01"``)
    config      : Optional backtester config.  Recognised path keys:
                  ``nq100_pit_path`` and ``sp500_pit_path``.

    Returns
    -------
    list[str]
        Sorted list of unique tickers.
    """
    idx = _canonical_index(index)
    sy = int(start_date[:4])
    ey = int(end_date[:4])
    union: set[str] = set()
    for year in range(sy, ey + 1):
        try:
            path = _find_year_yaml(idx, year, config)
            data = _load_year_yaml(path)
        except FileNotFoundError:
            continue
        union.update(normalise_pit_ticker(t) for t in (data.get("tickers_on_Jan_1") or []))
        for entry in ((data.get("changes") or {}).values()):
            if entry:
                union.update(normalise_pit_ticker(t) for t in (entry.get("union") or []))
    return sorted(union)


def build_membership_schedule(
    index: str,
    start_date: str,
    end_date: str,
    config: dict | None = None,
) -> list[tuple[str, frozenset]]:
    """Build a sorted list of (effective_date, member_frozenset) snapshots.

    The first entry always has ``date == start_date`` and represents the index
    membership at the *opening* of the backtest.  Each subsequent entry records
    a membership change event within ``(start_date, end_date]``.

    Query membership on any date with ``pit_members_on(schedule, date)``.

    Parameters
    ----------
    index       : ``"nq100"`` or ``"sp500"``
    start_date  : ISO date string
    end_date    : ISO date string
    config      : Optional backtester config (see ``tickers_union_for_period``).

    Returns
    -------
    list[tuple[str, frozenset]]
        Sorted ``[(date_str, frozenset_of_tickers), ...]``.
    """
    idx = _canonical_index(index)
    sy = int(start_date[:4])
    ey = int(end_date[:4])

    # --- Step 1: derive initial membership at exactly start_date ---
    members: set[str] = set()
    try:
        path = _find_year_yaml(idx, sy, config)
        data = _load_year_yaml(path)
        members = {normalise_pit_ticker(t) for t in (data.get("tickers_on_Jan_1") or [])}
        for change_date in sorted(str(d) for d in (data.get("changes") or {}).keys()):
            if change_date > start_date:
                break
            entry = (data.get("changes") or {}).get(change_date) or {}
            members -= {normalise_pit_ticker(t) for t in (entry.get("difference") or [])}
            members |= {normalise_pit_ticker(t) for t in (entry.get("union") or [])}
    except FileNotFoundError:
        pass

    schedule: list[tuple[str, frozenset]] = [(start_date, frozenset(members))]

    # --- Step 2: record every change event strictly after start_date ---
    for year in range(sy, ey + 1):
        try:
            path = _find_year_yaml(idx, year, config)
            data = _load_year_yaml(path)
        except FileNotFoundError:
            continue
        for change_date in sorted(str(d) for d in (data.get("changes") or {}).keys()):
            if change_date <= start_date or change_date > end_date:
                continue
            entry = (data.get("changes") or {}).get(change_date) or {}
            current = set(schedule[-1][1])
            current -= {normalise_pit_ticker(t) for t in (entry.get("difference") or [])}
            current |= {normalise_pit_ticker(t) for t in (entry.get("union") or [])}
            schedule.append((change_date, frozenset(current)))

    return schedule


def pit_members_on(schedule: list[tuple[str, frozenset]], date: str) -> frozenset:
    """Return the PIT member frozenset on *date* using a prebuilt schedule.

    Uses binary search — O(log k) where k is the number of change events.

    Parameters
    ----------
    schedule : output of ``build_membership_schedule``
    date     : ISO date string (``"2010-05-15"``)

    Returns
    -------
    frozenset[str]
        The set of index members on that date.  Empty frozenset if *date* is
        before the first schedule entry.
    """
    dates = [s[0] for s in schedule]
    idx = bisect.bisect_right(dates, date) - 1
    if idx < 0:
        return frozenset()
    return schedule[idx][1]
