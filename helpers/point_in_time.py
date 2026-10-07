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


def _raw_pit_ticker(symbol: str, date: str | None = None) -> str:
    """The roster ticker as written, only stripped and upper-cased.

    Used instead of :func:`normalise_pit_ticker` under the parquet provider: the
    security resolver needs the *historical* ticker (``SYMC`` in 2008), because
    aliasing it to today's ticker first (``GEN``) makes the tenure rule pick
    whoever held ``GEN`` back then -- GenOn, not Symantec (issue #158 review).
    Share-class punctuation is also kept, since the corpus spells it ``BRK.B``.
    """
    return str(symbol).strip().upper()


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


def load_roster_yaml(stream) -> dict:
    """Parse a PIT roster YAML without YAML 1.1's boolean coercion.

    ``yaml.safe_load`` turns an unquoted ``ON``, ``YES``, ``NO``, ``OFF``, ``Y``
    or ``N`` into ``True``/``False``, and ``str(True).upper()`` is ``"TRUE"`` --
    so ON Semiconductor, listed unquoted in the Nasdaq-100 rosters for
    2023-2025, silently became the ticker ``TRUE`` (TrueCar) and was never
    traded as itself. Once coerced, the original token is unrecoverable
    (``True`` could have been ``ON``, ``T``, ``YES``...), so the only safe fix is
    not to coerce: every scalar a roster could spell as a ticker stays a string.
    Integers and dates still parse as before.
    """
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required for point-in-time universe loading.") from exc

    class _RosterLoader(yaml.SafeLoader):
        pass

    _RosterLoader.yaml_implicit_resolvers = {
        first: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:bool"]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    return yaml.load(stream, Loader=_RosterLoader) or {}


@lru_cache(maxsize=512)
def _load_year_yaml_cached(path_str: str) -> dict:
    with open(path_str, encoding="utf-8") as fh:
        return load_roster_yaml(fh)


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
    # Parquet resolves raw roster tickers itself (alias only as a fallback);
    # every other provider keeps the established normalisation.
    norm = _raw_pit_ticker if _is_parquet_provider(config) else normalise_pit_ticker

    # --- Step 1: derive initial membership at exactly start_date ---
    members: set[str] = set()
    try:
        path = _find_year_yaml(idx, sy, config)
        data = _load_year_yaml(path)
        members = {norm(t) for t in (data.get("tickers_on_Jan_1") or [])}
        for change_date in sorted(str(d) for d in (data.get("changes") or {}).keys()):
            if change_date > start_date:
                break
            entry = (data.get("changes") or {}).get(change_date) or {}
            members -= {norm(t) for t in (entry.get("difference") or [])}
            members |= {norm(t) for t in (entry.get("union") or [])}
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
            current -= {norm(t) for t in (entry.get("difference") or [])}
            current |= {norm(t) for t in (entry.get("union") or [])}
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


# Explicit, dated roster-ticker -> security overrides for the parquet corpus.
# Checked FIRST. Each window says "between these dates, the index member the
# roster calls TICKER is this security". Every entry was derived from the #407
# review against the real corpus and both rosters (2004-01-01 .. 2026-09-28):
# the target's bars cover the window, and its median dollar volume over it is
# index-member scale. An override whose target does not cover the date FAILS
# rather than being trusted. Keep these here, not in PIT_TICKER_NORMALISATION:
# a dated ID like 'ENDPQ-202405' means nothing to Yahoo, Polygon or CSV.
#
# Three kinds of entry:
#  * bankruptcy / delisting suffix the roster never used (SHLD -> SHLDQ-202210)
#  * renames where Norgate keeps history under today's ticker (LB -> BBWI)
#  * the roster using a CURRENT ticker for an earlier period, where the raw
#    ticker then belonged to an unrelated company. These were silent
#    wrong-company swaps, not aborts:
#      ES   2009-2015 -> Eversource/NU (raw ES = EnergySolutions, $4M/day vs $46M)
#      LB   2004-2011 -> L Brands      (raw LB = LB-201106, $0.4M/day)
#      SAF  2004-2006 -> Safeco        (raw SAF = SAF-200604, $0.2M/day vs $33M)
#      IVGN 2004-2008 -> Invitrogen/Life Tech (alias LIFE picked LIFE-200603)
#      BBT  2004-2019 -> BB&T, now Truist (raw BBT = $1.4M/day)
#      CECO 2004-2005 -> Career Education, now Perdoceo (raw CECO = $0.03M/day)
_ALL = ("2004-01-01", "2026-12-31")
PIT_PARQUET_SECURITY_OVERRIDES: dict[str, list[tuple[str, str, str]]] = {
    # current-ticker-used-retroactively (wrong-company swaps)
    "ES": [("2004-01-01", "2015-02-28", "ES")],
    "LB": [("2004-01-01", "2021-08-02", "BBWI")],
    "SAF": [("2004-01-01", "2008-09-30", "SAF-200809")],
    "IVGN": [("2004-01-01", "2008-11-30", "LIFE-201402")],
    "BBT": [("2004-01-01", "2019-12-31", "TFC")],          # BB&T; raw BBT is a $1.4M/day stock
    "CECO": [("2004-01-01", "2020-12-31", "PRDO")],        # Career Education; raw CECO is $0.03M/day
    # bankruptcies / failures: the corpus keys the post-filing ticker
    "BIG": [(*_ALL, "BIGGQ")],
    "CHK": [("2004-01-01", "2021-02-09", "CHKAQ-202102")],
    "DF": [(*_ALL, "DFODQ-202106")],
    "DNR": [(*_ALL, "DNRCQ-202009")],
    "DO": [("2004-01-01", "2021-04-23", "DOFSQ-202104")],
    "ENDP": [(*_ALL, "ENDPQ-202405")],
    "FRC": [(*_ALL, "FRCB")],
    "FTR": [("2004-01-01", "2021-04-30", "FTRCQ-202104")],
    "MNK": [(*_ALL, "MNKKQ-202206")],
    "NE": [("2004-01-01", "2021-02-08", "NEBLQ-202102")],
    "NIHD": [("2004-01-01", "2015-06-25", "NIHDQ-201506")],
    "SHLD": [(*_ALL, "SHLDQ-202210")],
    "TUP": [(*_ALL, "TUPBQ-202506")],
    "WIN": [(*_ALL, "WINMQ-202009")],
    "JCP": [(*_ALL, "CPPRQ-202102")],                 # J.C. Penney; full history is under bankruptcy ticker
    # renames / successors that keep the history under another ticker
    "ARNC": [("2004-01-01", "2020-04-01", "HWM")],        # Alcoa Inc -> Arconic -> Howmet
    "CBS": [(*_ALL, "PSKY")],                              # CBS -> ViacomCBS -> Paramount
    "VIAC": [(*_ALL, "PSKY")],
    "CR": [("2004-01-01", "2023-04-03", "CXT")],          # Crane Co (pre-split) -> Crane NXT
    "FI": [(*_ALL, "FISV")],
    "HCP": [(*_ALL, "DOC")],                               # HCP -> Healthpeak -> DOC
    "PEAK": [(*_ALL, "DOC")],
    "IR": [("2004-01-01", "2020-03-01", "TT")],           # Ingersoll-Rand plc -> Trane
    "MMC": [(*_ALL, "MRSH")],
    "NCR": [("2004-01-01", "2023-10-16", "VYX")],
    "FOXA": [("2004-01-01", "2019-03-19", "TFCFA-201903")],  # 21st Century Fox, pre-Disney
    "FOX": [("2004-01-01", "2019-03-19", "TFCF-201903")],
    "IACI": [(*_ALL, "IAC")],
    "JOYG": [(*_ALL, "JOY-201704")],
    "MERQE": [(*_ALL, "MERQ-200611")],
    "MICC": [("2004-01-01", "2025-12-01", "TIGO")],       # Millicom
    "NTLI": [(*_ALL, "VMED-201306")],                      # NTL -> Virgin Media
    "QRTEA": [(*_ALL, "QVCGA")],                           # Liberty Interactive -> Qurate -> QVC Group
    "RHAT": [(*_ALL, "RHT-201907")],
    "DISCK": [("2005-07-06", "2008-09-17", "WBD")],       # Discovery Holding, before the C class listed
    "LMCA": [("2012-12-01", "2013-01-31", "LMCA-201604")],  # listed 17 days after the index add
    # BK -> BNY (2026-05-21). Needed while the corpus held the rename as two
    # files (norgate-data#16); once repaired, BNY holds BK's whole history and
    # _renames.json resolves earlier dates too, so this stays correct either way.
    "BK": [("2026-05-21", "2026-12-31", "BNY")],
}

# A membership date may sit a few days outside a security's bars: index changes
# are dated by announcement/effective date while the first/last trade can lag by
# up to a week (HES, RTN, NBL, AMCR, KHC, CTRX in the #407 review). Inside this
# window a SINGLE nearby candidate is accepted; more than one still aborts.
PIT_RESOLUTION_LAG_DAYS = 10


def load_corpus_renames(config: dict | None) -> dict[str, str]:
    """``{retired ticker: security that now holds its history}`` from the corpus.

    The parquet corpus records every ticker it retired in ``_renames.json``
    (zachisit/july-backtester-norgate-data#16, #18): a rename merges the history
    under the new ticker (``BK -> BNY``), and a stale duplicate maps to its dated
    security (``SEE -> SEE-202604``). Chains are followed to the end
    (``A -> B``, ``B -> C`` gives ``A -> C``). Absent or unreadable file -> ``{}``.
    This is a **storage-location map**, not membership data. The dated roster is
    still the sole authority for whether the company belongs to the index on a
    date. Resolving a 2010 ``BK`` row to ``BNY.parquet`` does not put the future
    ticker BNY into the 2010 roster; :class:`SecuritySchedule.roster_tickers`
    retains ``BK`` while the engine uses ``BNY`` only as the security/file ID.
    That distinction also keeps a position continuous across the rename.
    """
    import json

    path = os.path.join(_parquet_corpus_dir(config), "_renames.json")
    try:
        with open(path, encoding="utf-8") as fh:
            entries = json.load(fh)
    except (OSError, ValueError):
        return {}
    direct = {str(e["old"]).upper(): str(e["new"]) for e in sorted(entries, key=lambda e: e.get("date", ""))}
    out = {}
    for old in direct:
        seen, target = {old}, direct[old]
        while target.upper() in direct and target.upper() not in seen:
            seen.add(target.upper())
            target = direct[target.upper()]
        out[old] = target
    return out


def _ticker_spellings(ticker: str) -> list[str]:
    """The roster spelling first, then the other share-class punctuation.

    Rosters write ``BRK.B``; the corpus files are ``BRK.B.parquet``; older code
    normalised to ``BRK-B``. Only a 1-2 letter class suffix is swapped, so a
    genuine hyphenated ticker is never rewritten into something else.
    """
    import re

    out = [ticker]
    m = re.fullmatch(r"(.+)([.-])([A-Z]{1,2})", ticker)
    if m:
        out.append(m.group(1) + ("-" if m.group(2) == "." else ".") + m.group(3))
    return out


def _describe(candidates) -> list[str]:
    return [f"{sec} [{first.date()} .. {last.date()}]" for sec, first, last, _ in sorted(set(candidates))]


def _resolve_bare(bare: str, when, candidate_map: dict, lag_days: int):
    """Resolve one bare ticker on one date. Returns ``(security | None, candidates)``.

    The original #158 rule -- one covering span wins; several covering spans go
    to the ticker-tenure tie-break -- plus the lag window for a lone near-miss.
    """
    import pandas as pd

    candidates = candidate_map.get(bare, [])
    if not candidates:
        return None, []

    covering = [c for c in candidates if c[1] <= when <= c[2]]
    if len(covering) == 1:
        return covering[0][0], candidates
    if covering:
        # Several spans cover the date -- decide by ticker tenure.
        eligible = [c for c in covering if c[3] >= when]
        if not eligible:
            return None, candidates
        earliest = min(c[3] for c in eligible)
        winners = [c[0] for c in eligible if c[3] == earliest]
        return (winners[0] if len(winners) == 1 else None), candidates

    lag = pd.Timedelta(days=lag_days)
    near = [c for c in candidates if c[1] - lag <= when <= c[2] + lag]
    if len(near) == 1:
        return near[0][0], candidates
    return None, candidates


def resolve_security_id(ticker: str, date, candidate_map: dict,
                        lag_days: int = PIT_RESOLUTION_LAG_DAYS,
                        corpus_renames: dict | None = None) -> tuple[str | None, list[str]]:
    """Map a roster ticker + membership date to one security ID.

    Returns ``(security_id, candidate_descriptions)``; ``security_id`` is
    ``None`` when the member is unresolvable, and the descriptions let the error
    message show the operator *why*.

    Order (issue #158 review on #407):

    0. **PIT_PARQUET_SECURITY_OVERRIDES**: an explicit, dated, reviewed mapping.
       The target follows ``_renames.json`` when the corpus later retires that
       storage file. If the resulting target has no bars then, the member fails
       rather than falling through to a guess.
    1. **The raw roster ticker**, in its own spelling and then the other
       share-class punctuation (``BRK.B`` / ``BRK-B``). The ticker the roster
       used *on that date* is the strongest evidence of which security it was.
    2. **The corpus's own storage-location map** (``_renames.json``, see
       :func:`load_corpus_renames`): a ticker the corpus retired resolves to the
       security/file that now holds its history -- the data source's record, so
       it outranks the hand-kept alias table below. The dated roster still
       controls membership; this step never adds a member.
    3. **The PIT_TICKER_NORMALISATION alias, only if (1) and (2) failed**, preferring the
       target's *live bare file*: Norgate back-fills a renamed security's whole
       history under its current ticker, so ``SYMC`` lives in ``GEN.parquet``.
       Going through the tenure rule instead picks whoever held ``GEN`` in 2008
       (GenOn, ``GEN-201212``) -- a silent wrong-company swap.

    Each lookup accepts a single candidate within ``lag_days`` of its bars when
    nothing covers the date exactly.
    """
    import pandas as pd

    from helpers.rule_based_universe import parse_security

    when = pd.Timestamp(str(date)[:10])
    lag = pd.Timedelta(days=lag_days)
    # parse_security, not a fresh regex: only a 6-digit suffix is a delisting
    # stamp, so share classes (BRK-A, MER-K) survive intact.
    raw = parse_security(str(ticker).strip().upper())[0]
    seen: list = []

    # 0. explicit dated override -- validated, never trusted blindly
    for start, end, target in PIT_PARQUET_SECURITY_OVERRIDES.get(raw, ()):
        if pd.Timestamp(start) <= when <= pd.Timestamp(end):
            # Overrides name a security identity, while _renames.json names its
            # current storage file.  A later corpus rename (PSKY -> SKYD,
            # IAC -> PPLI) must not invalidate an older reviewed override.
            storage_target = (corpus_renames or {}).get(target.upper(), target)
            bare = parse_security(storage_target)[0]
            match = [c for c in candidate_map.get(bare, []) if c[0] == storage_target]
            seen += match
            # An override is a reviewed decision, so it gets a wider window than
            # the heuristics: LMCA was added to NQ100 17 days before it listed.
            olag = pd.Timedelta(days=31)
            if match and match[0][1] - olag <= when <= match[0][2] + olag:
                return storage_target, _describe(seen)
            return None, _describe(seen)

    # 1. raw roster ticker, both share-class spellings
    for bare in _ticker_spellings(raw):
        sec, cands = _resolve_bare(bare, when, candidate_map, lag_days)
        seen += cands
        if sec is not None:
            return sec, _describe(seen)

    # 2. the corpus's own record of tickers it retired
    successor = (corpus_renames or {}).get(raw)
    if successor:
        bare = parse_security(successor)[0]
        exact = [c for c in candidate_map.get(bare, []) if c[0] == successor]
        seen += exact
        if exact and exact[0][1] - lag <= when <= exact[0][2] + lag:
            return successor, _describe(seen)

    # 3. the established alias, live bare file first
    target = PIT_TICKER_NORMALISATION.get(raw.replace(".", "-"))
    if target:
        live = [c for c in candidate_map.get(target, []) if c[0] == target]
        seen += live
        if live and live[0][1] - lag <= when <= live[0][2] + lag:
            return target, _describe(seen)
        sec, cands = _resolve_bare(target, when, candidate_map, lag_days)
        seen += cands
        if sec is not None:
            return sec, _describe(seen)

    return None, _describe(seen)


class SecuritySchedule(list):
    """A membership schedule of security IDs that remembers where each came from.

    Behaves exactly like the ``[(date, frozenset), ...]`` list every caller
    already uses. ``roster_tickers`` maps each security ID to the roster
    ticker(s) it was resolved from, so code keyed on roster tickers (e.g.
    ``pit_enforcement.membership_intervals``) can find it even when the
    security's own ticker differs (``SYMC`` -> ``GEN``, ``BRK.B`` vs ``BRK-B``).
    """

    def __init__(self, items=(), roster_tickers: dict | None = None):
        super().__init__(items)
        self.roster_tickers: dict[str, set[str]] = roster_tickers or {}


def security_intervals(schedule, end_date: str) -> dict:
    """``{security_id: [(spell_start, spell_end), ...]}`` from a resolved schedule.

    Same spell semantics as ``pit_enforcement._yaml_change_intervals`` (a spell
    runs from the snapshot that adds the member to the snapshot that removes it,
    or to ``end_date`` if still a member), but keyed by **security** rather than
    roster ticker. Under the parquet provider this is the only correct key: one
    roster ticker can map to different securities over time (``IR`` is
    Ingersoll-Rand plc -> ``TT`` until 2020, then the new Ingersoll Rand), so
    roster-keyed intervals would hand one company's membership to another.
    """
    import pandas as pd

    open_spell: dict[str, pd.Timestamp] = {}
    out: dict[str, list] = {}
    previous: frozenset = frozenset()
    for date, members in schedule:
        when = pd.Timestamp(str(date)[:10])
        for sec in previous - members:
            out.setdefault(sec, []).append((open_spell.pop(sec), when))
        for sec in members - previous:
            open_spell[sec] = when
        previous = members
    end_ts = pd.Timestamp(str(end_date)[:10])
    for sec, start in open_spell.items():
        out.setdefault(sec, []).append((start, end_ts))
    return out


def resolve_members_to_securities(members, date, candidate_map: dict, failures: list,
                                  roster_tickers: dict | None = None, corpus_renames: dict | None = None):
    """Resolve one membership snapshot; append unresolvable members to *failures*.

    Does not raise -- the caller collects across the whole schedule and raises
    once, so an operator sees every offender in a single run.
    """
    resolved = set()
    for ticker in sorted(members):
        security, candidates = resolve_security_id(ticker, date, candidate_map,
                                                   corpus_renames=corpus_renames)
        if security is None:
            failures.append((str(ticker), str(date)[:10], candidates))
        else:
            resolved.add(security)
            if roster_tickers is not None:
                roster_tickers.setdefault(security, set()).add(str(ticker))
    return frozenset(resolved)


def resolve_schedule_to_securities(schedule, config: dict | None):
    """Rewrite a roster-ticker membership schedule into parquet security IDs.

    Returns a :class:`SecuritySchedule`. Raises :class:`PitResolutionError`
    once, listing every unresolvable member across every snapshot.
    """
    candidate_map = build_ticker_candidate_map(_load_span_index(config))
    corpus_renames = load_corpus_renames(config)
    failures: list = []
    roster_tickers: dict[str, set[str]] = {}
    out = SecuritySchedule(
        [(date, resolve_members_to_securities(members, date, candidate_map, failures, roster_tickers,
                                              corpus_renames))
         for date, members in schedule],
        roster_tickers,
    )
    if failures:
        raise PitResolutionError(failures)
    return out
