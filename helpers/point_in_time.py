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

Parquet security-ID resolution (issue #158)
-------------------------------------------
``pit:`` membership is expressed in *bare tickers*. The Norgate Parquet corpus
keys delisted securities as ``TICKER-YYYYMM``, so a bare ticker is not a stable
identifier there: ``CB`` is Chubb Corp until 2016 (``CB-201601``) and ACE/Chubb
Ltd afterwards (``CB``). Handing the loader a bare ticker therefore either
silently serves the wrong company (a live bare file masks the delisted one) or
drops the member entirely (several dated files, no bare file -> the loader
refuses to guess). Both failures remove or swap *dead* companies, which is
exactly what a point-in-time universe exists to include.

When ``config["data_provider"] == "parquet"``, ``tickers_union_for_period`` and
``build_membership_schedule`` therefore return **security IDs** rather than bare
tickers, resolved per membership date against the span index built by
``helpers.rule_based_universe.build_span_index``. Every other provider is
untouched and keeps bare tickers.

A member that cannot be mapped to exactly one security raises
:class:`PitResolutionError` — the run aborts rather than silently reintroducing
survivorship bias. There is deliberately no opt-out flag.
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
    # Maps a historical PIT-membership ticker -> the ticker the merged/ price
    # store actually carries (Norgate back-fills the *current* ticker, so a name
    # that was "UTX" in 2015 lives in the store as "RTX"). Every target below was
    # verified to exist in merged/ (exact file or date-suffixed delisted file).
    # This lifts PIT->price coverage to ~99% S&P / ~99% NQ100.
    #
    # GOOG / GOOGL note: post-split NQ100 YAML files list BOTH as distinct members.
    # Mapping GOOG -> GOOGL would silently collapse them; both pass through unchanged.
    "PCLN": "BKNG", "HANS": "MNST",
    # --- S&P 500 renames / mergers (old -> surviving ticker) ---
    "ABC": "COR", "ADS": "BFH", "ANTM": "ELV", "BHGE": "BKR", "BLL": "BALL",
    "CCE": "CCEP", "CDAY": "DAY", "CHK": "EXE", "COG": "CTRA", "CTL": "LUMN",
    "DDR": "SITC", "DISCA": "WBD", "DNR": "DEN", "DWDP": "DD", "ESV": "VAL",
    "FBHS": "FBIN", "FII": "FHI", "FLT": "CPAY", "GPS": "GAP", "HFC": "DINO",
    "HRS": "LHX", "JEC": "J", "KORS": "CPRI", "MYL": "VTRS", "NLOK": "GEN",
    "PKI": "RVTY", "RE": "EG", "SYMC": "GEN", "TMK": "GL", "UTX": "RTX",
    "WFT": "WFRD", "WLTW": "WTW", "WYND": "TNL", "FB": "META",
    # --- Nasdaq-100 renames / mergers ---
    "AEOS": "AEO", "IVGN": "LIFE", "JDSU": "VIAV", "KFT": "MDLZ", "UAUA": "UAL",
    "VIP": "VEON", "YHOO": "AABA",
    # --- Added from the #107 roster look-ahead audit ---
    # These roster tickers resolved to NO price series before the alias, i.e.
    # they were silently dropped from PIT backtests. Each target was verified to
    # carry the security's full history in the corpus:
    #   SIVB  -> SIVBQ (SVB Financial; corpus keys the collapse "Q" ticker, hist. from 1990)
    #   CTRP  -> TCOM  (Ctrip -> Trip.com, renamed 2019; corpus TCOM from 2003)
    #   RIMM  -> BB    (Research In Motion -> BlackBerry, renamed 2013; corpus BB from 1999)
    "SIVB": "SIVBQ", "CTRP": "TCOM", "RIMM": "BB",
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
        Sorted list of unique tickers, or — when
        ``config["data_provider"] == "parquet"`` — of parquet **security IDs**
        (see the module docstring and issue #158).

    Raises
    ------
    PitResolutionError
        Parquet provider only: one or more members could not be mapped to a
        single security. Every offender is listed.
    """
    # Parquet: derive the union FROM the schedule rather than resolving the raw
    # YAML union. A union entry carries no date, and the whole point of #158 is
    # that a bare ticker means nothing without one. Deriving it from the
    # schedule also makes the two agree by construction — a union of security
    # IDs masked against a schedule of bare tickers (or vice versa) would mask
    # every symbol out on every bar, which is the regression this fix must not
    # introduce.
    if _is_parquet_provider(config):
        schedule = build_membership_schedule(index, start_date, end_date, config)
        union_ids: set[str] = set()
        for _, members in schedule:
            union_ids |= set(members)
        return sorted(union_ids)

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
        Sorted ``[(date_str, frozenset_of_tickers), ...]``. Under
        ``config["data_provider"] == "parquet"`` the frozensets hold parquet
        **security IDs** resolved as of each snapshot's own date, so a ticker
        that changed hands resolves to the company that actually held it then
        (see the module docstring and issue #158).

    Raises
    ------
    PitResolutionError
        Parquet provider only: one or more members could not be mapped to a
        single security. Every offender is listed.
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

    # Parquet only: bare tickers are not identifiers in the delisted-inclusive
    # corpus. Resolve each snapshot against its own date. Raises once, with
    # every unresolvable member.
    if _is_parquet_provider(config):
        return resolve_schedule_to_securities(schedule, config)

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


# ---------------------------------------------------------------------------
# Parquet security-ID resolution (issue #158)
# ---------------------------------------------------------------------------
#
# WHY THIS LIVES HERE AND NOT IN THE LOADER
# -----------------------------------------
# ``services/parquet_service._find_parquet(symbol, parquet_dir)`` takes no date.
# It cannot pick between ``CB`` and ``CB-201601`` because nothing in its inputs
# says *when*. It is correct as it stands: it refuses to merge distinct
# securities and warns when a live file masks delisted history. The missing
# piece is upstream — the membership year is discarded before the loader is
# called. So resolution belongs at the universe layer, exactly where ``rule:``
# already does it (``helpers.rule_based_universe`` returns security IDs, which
# is why ``rule:`` universes were never affected by this bug).
#
# THE RESOLUTION RULE
# -------------------
# Candidates for bare ticker ``T`` are every security in the span index whose
# bare ticker is ``T`` — that is ``T`` itself when a live file exists, plus
# every ``T-YYYYMM``. Keep the ones whose ``[first_bar, last_bar]`` window
# covers the membership date.
#
#   * exactly one survivor  -> that security ID
#   * zero survivors        -> unresolvable (abort)
#   * several survivors     -> ticker-tenure tie-break, below
#
# The tie-break is required by the masking case and is NOT cosmetic. Norgate
# back-fills the *current* ticker onto a security's whole history, so the live
# ``CB.parquet`` carries ACE Ltd from 1993 even though ACE traded as ``ACE``
# until January 2016. Its span therefore overlaps ``CB-201601`` (Chubb Corp,
# 1990 -> 2016-01) for twenty-three years, and a pure span test finds two
# survivors for a 2010 membership date even though the answer is unambiguous:
# in 2010 the *ticker* CB belonged to Chubb Corp.
#
# What disambiguates is the stamp's meaning: ``T-YYYYMM`` says "this security
# held ticker T until YYYYMM". So among the covering candidates, the ticker on
# date D belongs to the one with the EARLIEST tenure end at or after D — the
# bare live file having an open-ended tenure. If that still does not single one
# out (a corpus inconsistency: every covering candidate stamped before D), the
# member is unresolvable and the run aborts.
#
# NO OPT-OUT
# ----------
# An opt-out flag was considered and declined. It would be set once, forgotten,
# and this particular failure silently reintroduces survivorship bias — the one
# thing a point-in-time universe exists to remove. If ``pit:`` + parquet cannot
# run until the corpus gaps are closed, that is the honest state.


class PitResolutionError(RuntimeError):
    """A PIT member could not be mapped to exactly one parquet security.

    Carries every offending member, not just the first: an operator fixing 46
    ambiguous tickers should see all 46 in one run, not one per run.

    Attributes
    ----------
    failures : list[tuple[str, str, list[str]]]
        ``(bare_ticker, membership_date, candidate_descriptions)`` triples.
    """

    def __init__(self, failures, message: str | None = None):
        self.failures = list(failures)
        super().__init__(message or _format_pit_failures(self.failures))


def _format_pit_failures(failures) -> str:
    """Render every unresolvable member, grouped by ticker, with its candidates."""
    by_ticker: dict[str, list] = {}
    for ticker, date, candidates in failures:
        by_ticker.setdefault(ticker, []).append((date, candidates))

    lines = [
        f"{len(by_ticker)} point-in-time member(s) could not be resolved to a "
        f"single parquet security. The run is aborted rather than dropping or "
        f"substituting them, because both silently reintroduce survivorship "
        f"bias (issue #158).",
        "",
    ]
    for ticker in sorted(by_ticker):
        events = sorted(by_ticker[ticker])
        first_date, candidates = events[0]
        extra = (f" (and {len(events) - 1} other membership date(s), "
                 f"through {events[-1][0]})") if len(events) > 1 else ""
        lines.append(f"  {ticker} @ {first_date}{extra}")
        if candidates:
            lines.append("      candidates considered:")
            for desc in candidates:
                lines.append(f"        - {desc}")
            lines.append("      none of them covers that date unambiguously.")
        else:
            lines.append("      no security with this bare ticker exists in the "
                         "parquet corpus at all.")
    lines += [
        "",
        "A security ID can be requested directly (e.g. 'CB-201601' instead of "
        "'CB') — the same remedy the parquet loader's own masking warning "
        "advises. Otherwise extend the corpus, or run this portfolio on a "
        "provider that keys by bare ticker.",
    ]
    return "\n".join(lines)


def _is_parquet_provider(config: dict | None) -> bool:
    """True only for the local parquet corpus.

    Load-bearing: ``CB-201601`` is a meaningless symbol to Yahoo, Polygon or a
    CSV directory. Every other provider keeps bare tickers and behaves exactly
    as before.
    """
    return str((config or {}).get("data_provider", "")).strip().lower() == "parquet"


def _parquet_corpus_dir(config: dict | None) -> str:
    """Absolute corpus directory, resolved the way the rest of the repo does it.

    Mirrors ``services.parquet_service._resolve_dir`` and
    ``helpers.rule_based_universe.resolve_universe``: ``parquet_data_dir``,
    default ``parquet_data/data``, relative paths taken from the project root.
    """
    raw = (config or {}).get("parquet_data_dir") or "parquet_data/data"
    return str(raw) if os.path.isabs(str(raw)) else str(ROOT / str(raw))


def _load_span_index(config: dict | None):
    """The ``security -> [first_bar, last_bar]`` index for the configured corpus.

    Delegates to ``helpers.rule_based_universe.build_span_index`` — including
    its on-disk cache, because scanning 36k parquet footers takes tens of
    seconds and this is called once per portfolio.
    """
    from helpers.rule_based_universe import build_span_index, default_cache_path

    data_dir = _parquet_corpus_dir(config)
    cache = (config or {}).get("universe_span_cache") or default_cache_path(data_dir)
    return build_span_index(data_dir, cache_path=cache)


def _tenure_end(security: str):
    """When this security stopped owning its bare ticker.

    ``"CB-201601" -> 2016-01-31``; a live bare file owns the ticker open-endedly.
    """
    import pandas as pd

    from helpers.rule_based_universe import parse_security

    _, stamp = parse_security(str(security))
    if stamp is None:
        return pd.Timestamp.max
    year, month = int(stamp[:4]), int(stamp[4:6])
    if not 1 <= month <= 12:                      # not a real month -> not a stamp
        return pd.Timestamp.max
    return pd.Timestamp(year=year, month=month, day=1) + pd.offsets.MonthEnd(0)


def build_ticker_candidate_map(span_index) -> dict[str, list[tuple]]:
    """``{BARE_TICKER: [(security_id, first_bar, last_bar, tenure_end), ...]}``.

    Built once per resolution pass. Re-filtering a 36k-row frame per member per
    schedule snapshot would be hundreds of millions of row comparisons.
    """
    import pandas as pd

    out: dict[str, list[tuple]] = {}
    for security, row in span_index.iterrows():
        bare = str(row["ticker"]).strip().upper()
        out.setdefault(bare, []).append((
            str(security),
            pd.Timestamp(row["first_bar"]),
            pd.Timestamp(row["last_bar"]),
            _tenure_end(security),
        ))
    return out


def resolve_security_id(ticker: str, date, candidate_map: dict) -> tuple[str | None, list[str]]:
    """Map a bare ticker + membership date to one security ID.

    Returns ``(security_id, candidate_descriptions)``. ``security_id`` is
    ``None`` when the member is unresolvable; the descriptions exist so the
    error message can show the operator *why* it was ambiguous.

    See the module-level note above for the rule and why the tenure tie-break
    is necessary.
    """
    import pandas as pd

    from helpers.rule_based_universe import parse_security

    when = pd.Timestamp(str(date)[:10])
    # parse_security, not a fresh regex: only a 6-digit suffix is a delisting
    # stamp, so share classes (BRK-A, MER-K) survive intact.
    bare = parse_security(str(ticker).strip().upper())[0]
    candidates = candidate_map.get(bare, [])
    if not candidates:
        return None, []

    described = [
        f"{sec} [{first.date()} .. {last.date()}]"
        for sec, first, last, _ in sorted(candidates)
    ]

    covering = [c for c in candidates if c[1] <= when <= c[2]]
    if len(covering) == 1:
        return covering[0][0], described
    if not covering:
        return None, described

    # Several spans cover the date — decide by ticker tenure.
    eligible = [c for c in covering if c[3] >= when]
    if not eligible:
        return None, described
    earliest = min(c[3] for c in eligible)
    winners = [c[0] for c in eligible if c[3] == earliest]
    if len(winners) == 1:
        return winners[0], described
    return None, described


def resolve_members_to_securities(members, date, candidate_map: dict, failures: list):
    """Resolve one membership snapshot; append unresolvable members to *failures*.

    Does not raise — the caller collects across the whole schedule and raises
    once, so an operator sees every offender in a single run.
    """
    resolved = set()
    for ticker in sorted(members):
        security, candidates = resolve_security_id(ticker, date, candidate_map)
        if security is None:
            failures.append((str(ticker), str(date)[:10], candidates))
        else:
            resolved.add(security)
    return frozenset(resolved)


def resolve_schedule_to_securities(schedule, config: dict | None):
    """Rewrite a bare-ticker membership schedule into parquet security IDs.

    Raises :class:`PitResolutionError` once, listing every unresolvable member
    across every snapshot.
    """
    candidate_map = build_ticker_candidate_map(_load_span_index(config))
    failures: list = []
    out = [
        (date, resolve_members_to_securities(members, date, candidate_map, failures))
        for date, members in schedule
    ]
    if failures:
        raise PitResolutionError(failures)
    return out
