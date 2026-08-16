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
]

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_CACHE = os.path.join(_ROOT, "universe_cache", "universe_metrics.parquet")

#: Threshold defaults. A universe definition is a parameter, not a fact --
#: sweep these rather than asserting them (see the sensitivity note on #70).
DEFAULTS = {
    "universe_min_price": 5.0,            # $ — excludes penny/sub-liquid names
    "universe_min_dollar_volume": 5e6,    # $ 20-day average
    "universe_min_bars": 252,             # ~1y of history before eligibility
    "universe_top_n": None,               # None = uncapped; int = top N by adv20
}


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
