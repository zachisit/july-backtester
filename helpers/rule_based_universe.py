"""Rule-based point-in-time universe (issue #70).

A survivorship-bias-free investable universe defined by a *rule* rather than by
index membership. Mirrors the public shape of :mod:`helpers.point_in_time` so a
``rule:`` portfolio drops into the existing resolution path with no engine
change: it returns both a full-period union and a membership schedule that
``pit_members_on``-style lookups can query per bar.

Motivation
----------
Every survivorship-free universe attempt so far has been blocked on index
membership history, which is the expensive, vendor-locked part. But most
systematic strategies do not need literal index membership -- they need a
defensible, point-in-time *investable* set. That can be defined directly:

    universe(D) = { s : s traded on D
                    and close(s, D)   >= min_price
                    and adv20(s, D)   >= min_dollar_volume
                    and bars(s, <= D) >= min_bars }

optionally capped to the top N by 20-day dollar volume so the universe has a
stable size across dates.

This is survivorship-free *by construction*: the Norgate corpus this reads
carries ~20.9k delisted securities with their real last trade dates, so a
company that failed is present until the day it failed and absent after. It is
also look-ahead-free by construction: every input is a bar at or before D.

What it is NOT
--------------
This is not the Russell or the S&P 500. There are no reconstitution effects, no
float or banding rules, and no index-inclusion signal. A strategy whose thesis
depends on index membership itself needs real membership data, and results
produced on a ``rule:`` universe must say which universe they used.

Ticker reuse
------------
Resolution is by **security**, never by bare ticker string. Norgate names
delisted securities ``TICKER-YYYYMM``, so one ticker maps to several distinct
securities over time -- ``WB`` is Wachovia until 2008 and Weibo from 2014,
``V`` was Vivendi before Visa. Comparing ticker strings would let a modern
company's history satisfy a historical universe slot.

The engine keys positions by ticker, so :func:`resolve_rule_universe` emits
plain tickers. Where two securities share a ticker in the same month the more
liquid one wins, and the collision is reported by
:func:`ticker_collisions` rather than being silently resolved.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache

import pandas as pd

__all__ = [
    "DEFAULTS",
    "load_cache",
    "universe_on",
    "tickers_union_for_period",
    "build_membership_schedule",
    "members_on",
    "resolve_rule_portfolio",
    "ticker_collisions",
    "normalise_universe_ticker",
    "load_sec_registrant_index",
    "is_operating_company",
]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CACHE = os.path.join(_ROOT, "universe_cache", "universe_metrics.parquet")
_DEFAULT_SEC_INDEX = os.path.join(_ROOT, "universe_cache", "sec_operating_company_tickers.json")

#: Threshold defaults. A universe definition is a parameter, not a fact --
#: sweep these rather than asserting them (see the sensitivity note on #70).
DEFAULTS = {
    "universe_min_price": 5.0,            # $ — excludes penny/sub-liquid names
    "universe_min_dollar_volume": 5e6,    # $ 20-day average
    "universe_min_bars": 252,             # ~1y of history before eligibility
    "universe_top_n": None,               # None = uncapped; int = top N by adv20
    "universe_exclude_non_operating_companies": True,  # see is_operating_company()
    "universe_sec_registrant_path": None,  # None = default committed snapshot
}

# --- ticker normalisation ---------------------------------------------------
# Norgate uses '.' for share classes (BRK.B); this project's PIT rosters and
# price providers use '-' (BRK-B, matching helpers.point_in_time's own
# normalisation and, empirically, SEC EDGAR's own convention). A handful of
# names also changed ticker across a corporate action that is NOT a pure
# share-class rename -- e.g. Norgate stores the pre-2019 21st Century Fox
# entity under its historical ticker TFCFA, while PIT rosters record that same
# membership slot under the surviving Fox Corp ticker FOXA. Those need an
# explicit alias, the same way helpers.point_in_time.PIT_TICKER_NORMALISATION
# aliases old->current tickers (UTX->RTX etc.) for the index PIT paths.
RULE_TICKER_ALIASES = {
    "TFCFA": "FOXA",
}


def normalise_universe_ticker(raw: str) -> str:
    """Canonical ticker for a Norgate security stem's base ticker."""
    t = str(raw).strip().upper().replace(".", "-")
    return RULE_TICKER_ALIASES.get(t, t)


# --- instrument-type filter (issue #70 gate defect 1) -----------------------
# The Norgate bar corpus has no security-type field, so "is this a stock" has
# to be answered indirectly. Absence from SEC's own Exchange-Act registrant
# index is the primary signal: '40 Act ETFs (iShares, sector SPDRs, ARK funds
# -- IWM, XLF, TLT, ARKK, EFA, HYG, EWZ, FXI, XLE, XLK, IVV, EEM among the
# names the #70 gate actually surfaced) file as investment companies, not
# Exchange Act reporting companies, and never appear in the registrant index
# at all. A handful of older structures DO have an Exchange Act CIK and would
# slip through that check alone -- legacy index unit-investment-trusts (SPY,
# QQQ, DIA), precious-metal/commodity grantor trusts (GLD, SLV, USO, ...), and
# bank-issued ETNs (VXX, VXZ, DJP, filed under the issuing bank's own name) --
# so a registrant that IS present gets a second check against its own
# SEC-filed title. "TRUST" and "FUND" alone are deliberately NOT used as
# markers: real S&P 500 REITs (Digital Realty TRUST, Federal Realty
# Investment TRUST, Vornado Realty TRUST) and MLPs legitimately carry those
# words, and a blind match would silently exclude large, liquid, legitimate
# equities -- worse than the bug this is fixing.
_FUND_TITLE_MARKERS = ("ETF", "PROSHARES", "TEUCRIUM")
_ETN_ISSUER_TITLES = {
    "BARCLAYS BANK PLC", "CREDIT SUISSE AG", "UBS AG",
    "JPMORGAN CHASE FINANCIAL CO LLC", "GS FINANCE CORP",
    "CITIGROUP GLOBAL MARKETS HOLDINGS INC", "MORGAN STANLEY FINANCE LLC",
    "DEUTSCHE BANK AG",
    # NOT "BANK OF MONTREAL" or "ROYAL BANK OF CANADA": those banks' own
    # common stock (BMO, RY) files under those near-identical titles too
    # ("BANK OF MONTREAL /CAN/", "ROYAL BANK OF CANADA" exactly for RY) --
    # verified empirically that neither bank currently backs any ETN ticker
    # under the bare form in SEC's data, so excluding the bare title would
    # only have wrongly dropped RY, a real, liquid bank stock, for no gain.
}
_COMMODITY_WORDS = ("GOLD", "SILVER", "PLATINUM", "PALLADIUM", "OIL", "GAS",
                    "GASOLINE", "COMMODITY", "AGRICULTURE", "METAL", "METALS",
                    "GSCI")
# Legacy 1990s-era equity-index Unit Investment Trusts. SPY/DIA/MDY's own SEC
# titles already contain "ETF" ("SPDR S&P 500 ETF TRUST" etc.); QQQ's does not
# ("INVESCO QQQ TRUST, SERIES 1"), so it needs an explicit entry rather than a
# generic "ticker appears in its own title" rule -- that generic rule was
# tried first and wrongly excluded real REITs that are literally named after
# their own ticker (LXP Industrial Trust, RLJ Lodging Trust).
_LEGACY_INDEX_UIT_TICKERS = {"QQQ"}


def _contains_word(title_upper: str, word: str) -> bool:
    """Whole-word match, not substring -- "ETF" must not fire on NETFLIX,
    and "GOLD" must not fire on GOLDMAN SACHS."""
    return re.search(rf"\b{re.escape(word)}\b", title_upper) is not None


def _looks_like_fund_or_trust(ticker: str, title: str) -> bool:
    t = title.upper()
    if ticker.upper() in _LEGACY_INDEX_UIT_TICKERS:
        return True
    if any(_contains_word(t, marker) for marker in _FUND_TITLE_MARKERS):
        return True
    if t in _ETN_ISSUER_TITLES:
        return True
    if (_contains_word(t, "TRUST") or _contains_word(t, "FUND")) and any(
        _contains_word(t, w) for w in _COMMODITY_WORDS
    ):
        return True
    return False


def is_operating_company(ticker: str, sec_index: dict | None) -> bool:
    """True if *ticker* is a real reporting company, not an ETF/ETN/fund.

    ``sec_index`` is ``None`` when no registrant snapshot is configured; the
    filter no-ops (returns True) in that case rather than excluding
    everything, so callers without the snapshot fall back to threshold-only
    behaviour. Note ADRs and other non-US-domiciled operating companies (e.g.
    BABA, JD) currently pass this check -- domicile filtering is a separate,
    still-open concern from the instrument-type problem this addresses.
    """
    if sec_index is None:
        return True
    title = sec_index.get(ticker.upper())
    if title is None:
        return False
    return not _looks_like_fund_or_trust(ticker, title)


@lru_cache(maxsize=4)
def _load_sec_index_cached(path: str) -> dict | None:
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return {str(k).upper(): str(v) for k, v in raw.get("tickers", {}).items()}


def _sec_index_path(config: dict | None) -> str:
    if config and config.get("universe_sec_registrant_path"):
        p = os.path.expanduser(os.path.expandvars(str(config["universe_sec_registrant_path"])))
        return p if os.path.isabs(p) else os.path.join(_ROOT, p)
    return _DEFAULT_SEC_INDEX


def load_sec_registrant_index(config: dict | None = None) -> dict | None:
    """Load the {ticker: SEC-filed title} snapshot, or ``None`` if absent."""
    return _load_sec_index_cached(_sec_index_path(config))


def _cfg(config: dict | None, key: str):
    if config and key in config and config[key] is not None:
        return config[key]
    return DEFAULTS[key]


@lru_cache(maxsize=4)
def _load_cache_cached(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Universe cache not found: {path}\n"
            f"Build it with: python scripts/build_universe_cache.py"
        )
    df = pd.read_parquet(path)
    # 'month' is "YYYY-MM"; keep it sortable as a string and add an ordinal for
    # fast range filtering.
    df["month"] = df["month"].astype(str)
    return df.sort_values(["month", "security"]).reset_index(drop=True)


def load_cache(config: dict | None = None) -> pd.DataFrame:
    """Load the prebuilt (security, month) metrics cache."""
    return _load_cache_cached(str(_cfg_path(config)))


def _cfg_path(config: dict | None) -> str:
    if config and config.get("universe_cache_path"):
        p = os.path.expanduser(os.path.expandvars(str(config["universe_cache_path"])))
        return p if os.path.isabs(p) else os.path.join(_ROOT, p)
    return _DEFAULT_CACHE


def _month_of(date: str) -> str:
    return str(date)[:7]


def _eligible_rows(cache: pd.DataFrame, month: str, config: dict | None) -> pd.DataFrame:
    """Rows for *month* passing every threshold, most liquid first."""
    rows = cache[cache["month"] == month]
    if rows.empty:
        return rows
    rows = rows[
        (rows["last_close"] >= float(_cfg(config, "universe_min_price")))
        & (rows["adv20"] >= float(_cfg(config, "universe_min_dollar_volume")))
        & (rows["bars_to_date"] >= int(_cfg(config, "universe_min_bars")))
    ]
    if _cfg(config, "universe_exclude_non_operating_companies"):
        sec_index = load_sec_registrant_index(config)
        if sec_index is not None and not rows.empty:
            keep = rows["ticker"].map(lambda t: is_operating_company(t, sec_index))
            rows = rows[keep]
    return rows.sort_values("adv20", ascending=False)


def universe_on(date: str, config: dict | None = None) -> list[str]:
    """Tickers investable as of *date* (ISO ``YYYY-MM-DD``).

    Uses the most recent completed month at or before *date*, so the answer
    depends only on bars that had already printed.
    """
    cache = load_cache(config)
    rows = _eligible_rows(cache, _month_of(date), config)
    if rows.empty:
        return []
    top_n = _cfg(config, "universe_top_n")
    # Deduplicate ticker collisions by keeping the more liquid security. rows is
    # already sorted by adv20 descending, so 'first' is the liquid one.
    rows = rows.drop_duplicates(subset="ticker", keep="first")
    if top_n:
        rows = rows.head(int(top_n))
    return sorted(rows["ticker"].tolist())


def _months_between(start_date: str, end_date: str, cache: pd.DataFrame) -> list[str]:
    s, e = _month_of(start_date), _month_of(end_date)
    months = cache["month"].drop_duplicates()
    return sorted(m for m in months if s <= m <= e)


def tickers_union_for_period(
    start_date: str,
    end_date: str,
    config: dict | None = None,
) -> list[str]:
    """Every ticker investable at any point in ``[start_date, end_date]``.

    Mirrors :func:`helpers.point_in_time.tickers_union_for_period`. This is the
    fetch list; per-bar membership is enforced separately via the schedule.
    """
    cache = load_cache(config)
    union: set[str] = set()
    for month in _months_between(start_date, end_date, cache):
        rows = _eligible_rows(cache, month, config)
        if rows.empty:
            continue
        rows = rows.drop_duplicates(subset="ticker", keep="first")
        top_n = _cfg(config, "universe_top_n")
        if top_n:
            rows = rows.head(int(top_n))
        union.update(rows["ticker"].tolist())
    return sorted(union)


def build_membership_schedule(
    start_date: str,
    end_date: str,
    config: dict | None = None,
) -> list[tuple[str, frozenset]]:
    """``[(effective_date, members), ...]``, one entry per month with a change.

    Mirrors :func:`helpers.point_in_time.build_membership_schedule`: the first
    entry is always ``start_date`` and represents membership at the opening of
    the backtest. Query with :func:`members_on`.
    """
    cache = load_cache(config)
    months = _months_between(start_date, end_date, cache)
    schedule: list[tuple[str, frozenset]] = []
    prev: frozenset | None = None
    for i, month in enumerate(months):
        rows = _eligible_rows(cache, month, config)
        rows = rows.drop_duplicates(subset="ticker", keep="first")
        top_n = _cfg(config, "universe_top_n")
        if top_n:
            rows = rows.head(int(top_n))
        members = frozenset(rows["ticker"].tolist())
        if i == 0:
            schedule.append((str(start_date), members))
        elif members != prev:
            schedule.append((f"{month}-01", members))
        prev = members
    if not schedule:
        schedule = [(str(start_date), frozenset())]
    return schedule


def members_on(schedule: list[tuple[str, frozenset]], date: str) -> frozenset:
    """Membership in effect on *date*. Mirrors ``pit_members_on``."""
    out: frozenset = frozenset()
    d = str(date)
    for eff, members in schedule:
        if eff <= d:
            out = members
        else:
            break
    return out


def resolve_rule_portfolio(value: str, config: dict) -> list[str] | None:
    """Resolve a ``rule:<name>`` portfolio value; return ``None`` otherwise.

    The name after the colon is a label only -- thresholds come from config, so
    ``rule:us_liquid_1000`` and ``rule:anything`` resolve identically. Keeping
    the label free-form lets a run be self-describing in reports without
    inventing a second config surface.
    """
    if not isinstance(value, str) or not value.startswith("rule:"):
        return None
    return tickers_union_for_period(config["start_date"], config["end_date"], config)


def ticker_collisions(
    start_date: str,
    end_date: str,
    config: dict | None = None,
) -> pd.DataFrame:
    """Months where two eligible securities shared one ticker.

    Reported rather than silently resolved. ``universe_on`` keeps the more
    liquid security; this surfaces every case so the choice can be audited.
    """
    cache = load_cache(config)
    out = []
    for month in _months_between(start_date, end_date, cache):
        rows = _eligible_rows(cache, month, config)
        if rows.empty:
            continue
        dupes = rows[rows.duplicated(subset="ticker", keep=False)]
        for ticker, grp in dupes.groupby("ticker"):
            out.append({
                "month": month,
                "ticker": ticker,
                "securities": ", ".join(grp["security"].tolist()),
                "kept": grp.iloc[0]["security"],
            })
    return pd.DataFrame(out, columns=["month", "ticker", "securities", "kept"])
