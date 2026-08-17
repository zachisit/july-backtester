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
    "load_leveraged_inverse_etn_list",
    "is_leveraged_inverse_or_etn",
]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CACHE = os.path.join(_ROOT, "universe_cache", "universe_metrics.parquet")
_DEFAULT_SEC_INDEX = os.path.join(_ROOT, "universe_cache", "sec_operating_company_tickers.json")
_DEFAULT_LEV_INV_ETN_LIST = os.path.join(
    _ROOT, "universe_cache", "leveraged_inverse_etn_tickers.json"
)

#: Threshold defaults. A universe definition is a parameter, not a fact --
#: sweep these rather than asserting them (see the sensitivity note on #70).
DEFAULTS = {
    "universe_min_price": 5.0,            # $ — excludes penny/sub-liquid names
    "universe_min_dollar_volume": 5e6,    # $ 20-day average
    "universe_min_bars": 252,             # ~1y of history before eligibility
    "universe_top_n": None,               # None = uncapped; int = top N by adv20
    "universe_exclude_leveraged_inverse_etn": True,  # see is_leveraged_inverse_or_etn()
    "universe_sec_registrant_path": None,  # None = default committed snapshot
    "universe_leveraged_inverse_etn_path": None,  # None = default committed curated list
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
#: How a future maintainer finds the next one of these: a persistent ticker
#: collision reported by :func:`ticker_collisions`, or a rule-universe ticker
#: that fails to resolve against a live roster/broker feed, is the usual
#: symptom -- check whether Norgate's historical ticker for that slot differs
#: from the ticker the roster/broker uses today before assuming it's a data
#: bug.
RULE_TICKER_ALIASES = {
    "TFCFA": "FOXA",
}


def normalise_universe_ticker(raw: str) -> str:
    """Canonical ticker for a Norgate security stem's base ticker."""
    t = str(raw).strip().upper().replace(".", "-")
    return RULE_TICKER_ALIASES.get(t, t)


# --- instrument-type filter (issue #70 gate defect 1) -----------------------
# The universe is broker-constrained, not index-shaped: Zach's actual
# tradeable set is "US common stock (ADRs included) + any ETF Vanguard
# permits buying long" -- so plain ETFs (SPY, QQQ, IWM, GLD, ...) belong in
# the universe and must NOT be excluded. What actually needs excluding is the
# subset Vanguard will not accept purchases of: leveraged ETFs, inverse ETFs,
# and (per Zach's 2026-08-17 correction) ALL ETNs, not just leveraged/inverse
# ones -- Vanguard's own policy wording groups "leveraged or inverse
# products, ETNs, and Memecoin ETFs" as three coordinate categories, not two.
#
# Round 2 of this filter (commit 224fd9f) matched on the security's SEC-filed
# title. That mechanism does not work on the real target tickers: TQQQ,
# SOXL, FAS, and SQQQ are '40 Act investment companies, not Exchange Act
# registrants, so they never appear in the SEC registrant index at all; ETNs
# like VXX/DJP are titled only by their issuing bank (e.g. "BARCLAYS BANK
# PLC"), which carries no product-derived text to match against. Zach found
# this via his own real-cache measurement against 224fd9f, not via review --
# the filter shipped believing it worked and did not.
#
# Round 3 (this version) replaces title matching with direct membership in a
# curated ticker list, since no authoritative machine-readable Vanguard
# ticker list exists (Vanguard publishes categories, not tickers). See
# universe_cache/leveraged_inverse_etn_tickers.json for the list itself, its
# provenance, and its explicit "approximation, not derived fact" caveat.
# scripts/detect_leveraged_etf_by_beta.py is the intended completeness check
# for gaps in that list.
#
# This is still identification by POSITIVE match only -- never by absence
# from any snapshot or list. A ticker missing from the curated list (whether
# a plain ETF, a common stock, or a delisted security this list's compiler
# simply never enumerated) is NEVER excluded by this filter. That is what
# keeps the Round-1 survivorship failure mode (91.4% of delisted securities
# wrongly stripped because they were absent from a registrant snapshot)
# structurally impossible here: this filter has no absence-based branch at
# all, in either round 2 or round 3.


@lru_cache(maxsize=4)
def _load_lev_inv_etn_set_cached(path: str) -> frozenset | None:
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return frozenset(str(t).upper() for t in raw.get("tickers", []))


def _lev_inv_etn_list_path(config: dict | None) -> str:
    if config and config.get("universe_leveraged_inverse_etn_path"):
        p = os.path.expanduser(
            os.path.expandvars(str(config["universe_leveraged_inverse_etn_path"]))
        )
        return p if os.path.isabs(p) else os.path.join(_ROOT, p)
    return _DEFAULT_LEV_INV_ETN_LIST


def load_leveraged_inverse_etn_list(config: dict | None = None) -> frozenset | None:
    """Load the curated {ticker, ...} exclusion set, or ``None`` if absent.

    See ``universe_cache/leveraged_inverse_etn_tickers.json`` for what this
    is compiled from and its known coverage gaps. This is a hand-maintained
    approximation, not a derived fact -- extend the committed file (and its
    provenance notes) when a gap is found, rather than special-casing tickers
    in code.
    """
    return _load_lev_inv_etn_set_cached(_lev_inv_etn_list_path(config))


def is_leveraged_inverse_or_etn(ticker: str, lev_inv_etn_set: frozenset | None) -> bool:
    """True if *ticker* should be excluded as leveraged, inverse, or an ETN.

    Positive identification only, via direct membership in the curated
    ticker set. ``lev_inv_etn_set`` being ``None``, or *ticker* being absent
    from it, NEVER excludes -- an unknown ticker (including every delisted
    security, and every plain ETF Vanguard permits) simply passes through.
    See the module-level comment above for why this replaced the Round-2
    SEC-title mechanism, and why absence is not used as a signal.
    """
    if lev_inv_etn_set is None:
        return False
    return ticker.upper() in lev_inv_etn_set


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
    """Load the {ticker: SEC-filed title} snapshot, or ``None`` if absent.

    No longer used by the leveraged/inverse/ETN filter (see
    :func:`load_leveraged_inverse_etn_list`) -- retained for symbology and
    ticker-alias work, per Zach's 2026-08-17 comment that "the SEC snapshot
    still earns its place for the symbology and alias work; it just isn't
    the source for this question."
    """
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
    if _cfg(config, "universe_exclude_leveraged_inverse_etn"):
        lev_inv_etn_set = load_leveraged_inverse_etn_list(config)
        if lev_inv_etn_set is not None and not rows.empty:
            exclude = rows["ticker"].apply(
                lambda tk: is_leveraged_inverse_or_etn(tk, lev_inv_etn_set)
            )
            rows = rows[~exclude]
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
