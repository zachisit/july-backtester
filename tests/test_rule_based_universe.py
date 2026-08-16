"""Tests for helpers/rule_based_universe.py (issue #70).

Built on a synthetic cache rather than the 2.7 GB Norgate corpus, so the suite
stays fast and runs without the submodule initialised.

The properties that matter here are the ones whose violation is silent:
no look-ahead, delisted names disappearing on their real last date, and ticker
reuse resolving to the right security per era. A universe that gets any of
those wrong still produces plausible-looking backtests.
"""
from __future__ import annotations

import pandas as pd
import pytest

from helpers import rule_based_universe as rbu


def _cache(rows) -> pd.DataFrame:
    return pd.DataFrame(
        rows, columns=["security", "ticker", "month", "last_close", "adv20",
                       "bars_to_date", "bars_in_month"]
    )


@pytest.fixture
def cache_path(tmp_path):
    """A small cache with the interesting cases baked in.

    LIVE   — investable throughout
    THIN   — fails the dollar-volume floor
    CHEAP  — fails the price floor
    YOUNG  — fails the history floor early, passes later
    WB     — ticker reuse: Wachovia (delisted 2008-12) then Weibo (2014-04+)
    """
    rows = []
    for m in ("2008-01", "2008-06", "2008-12", "2014-04", "2014-05"):
        rows.append(["LIVE", "LIVE", m, 50.0, 5e7, 3000, 21])
        rows.append(["THIN", "THIN", m, 50.0, 1e5, 3000, 21])
        rows.append(["CHEAP", "CHEAP", m, 1.5, 5e7, 3000, 21])
    rows.append(["YOUNG", "YOUNG", "2008-01", 50.0, 5e7, 10, 21])
    rows.append(["YOUNG", "YOUNG", "2008-06", 50.0, 5e7, 120, 21])
    rows.append(["YOUNG", "YOUNG", "2008-12", 50.0, 5e7, 400, 21])
    # Wachovia: present through its delisting month, gone after.
    for m in ("2008-01", "2008-06", "2008-12"):
        rows.append(["WB-200812", "WB", m, 30.0, 9e7, 4000, 21])
    # Weibo: only from 2014.
    for m in ("2014-04", "2014-05"):
        rows.append(["WB", "WB", m, 20.0, 4e7, 300, 21])

    p = tmp_path / "universe_metrics.parquet"
    _cache(rows).to_parquet(p, index=False)
    rbu._load_cache_cached.cache_clear()
    return {"universe_cache_path": str(p)}


class TestThresholds:
    def test_liquid_name_included(self, cache_path):
        assert "LIVE" in rbu.universe_on("2008-06-15", cache_path)

    def test_illiquid_excluded(self, cache_path):
        assert "THIN" not in rbu.universe_on("2008-06-15", cache_path)

    def test_sub_price_floor_excluded(self, cache_path):
        assert "CHEAP" not in rbu.universe_on("2008-06-15", cache_path)

    def test_insufficient_history_excluded_then_included(self, cache_path):
        assert "YOUNG" not in rbu.universe_on("2008-01-15", cache_path)
        assert "YOUNG" in rbu.universe_on("2008-12-15", cache_path)

    def test_thresholds_are_configurable(self, cache_path):
        loose = dict(cache_path, universe_min_dollar_volume=1e4)
        assert "THIN" in rbu.universe_on("2008-06-15", loose)

    def test_top_n_caps_by_liquidity(self, cache_path):
        cfg = dict(cache_path, universe_top_n=1)
        # WB-200812 has adv20 9e7, LIVE has 5e7 -> WB wins the single slot.
        assert rbu.universe_on("2008-06-15", cfg) == ["WB"]


class TestSurvivorship:
    def test_delisted_name_present_before_and_absent_after(self, cache_path):
        assert "WB" in rbu.universe_on("2008-12-15", cache_path)
        # Wachovia is gone by 2014; the ticker only returns as a different
        # security, which is the next test.
        pre = rbu._eligible_rows(rbu.load_cache(cache_path), "2008-12", cache_path)
        assert "WB-200812" in set(pre["security"])

    def test_ticker_reuse_resolves_to_the_right_security(self, cache_path):
        cache = rbu.load_cache(cache_path)
        in_2008 = set(rbu._eligible_rows(cache, "2008-06", cache_path)["security"])
        in_2014 = set(rbu._eligible_rows(cache, "2014-04", cache_path)["security"])
        assert "WB-200812" in in_2008 and "WB" not in in_2008
        assert "WB" in in_2014 and "WB-200812" not in in_2014

    def test_union_spans_both_eras_without_duplicating_the_ticker(self, cache_path):
        union = rbu.tickers_union_for_period("2008-01-01", "2014-12-31", cache_path)
        assert union.count("WB") == 1


class TestNoLookAhead:
    def test_universe_ignores_later_months(self, cache_path, tmp_path):
        """Appending a future month must not change an earlier answer."""
        before = rbu.universe_on("2008-06-15", cache_path)
        cache = pd.read_parquet(cache_path["universe_cache_path"])
        extra = _cache([["NEWCO", "NEWCO", "2009-01", 99.0, 9e9, 5000, 21]])
        p2 = tmp_path / "cache2.parquet"
        pd.concat([cache, extra], ignore_index=True).to_parquet(p2, index=False)
        rbu._load_cache_cached.cache_clear()
        after = rbu.universe_on("2008-06-15", {"universe_cache_path": str(p2)})
        assert before == after
        assert "NEWCO" not in after

    def test_month_resolution_does_not_peek_forward(self, cache_path):
        """A date resolves against its own month, not a later one."""
        assert "YOUNG" not in rbu.universe_on("2008-01-31", cache_path)


class TestSchedule:
    def test_first_entry_is_start_date(self, cache_path):
        sched = rbu.build_membership_schedule("2008-01-01", "2014-12-31", cache_path)
        assert sched[0][0] == "2008-01-01"

    def test_members_on_returns_effective_snapshot(self, cache_path):
        sched = rbu.build_membership_schedule("2008-01-01", "2014-12-31", cache_path)
        assert "YOUNG" not in rbu.members_on(sched, "2008-01-15")
        assert "YOUNG" in rbu.members_on(sched, "2008-12-15")

    def test_schedule_only_records_changes(self, cache_path):
        sched = rbu.build_membership_schedule("2008-01-01", "2014-12-31", cache_path)
        sets = [m for _, m in sched]
        assert all(a != b for a, b in zip(sets, sets[1:])), "consecutive duplicates"

    def test_members_before_first_effective_date_is_empty(self, cache_path):
        sched = rbu.build_membership_schedule("2008-01-01", "2014-12-31", cache_path)
        assert rbu.members_on(sched, "2007-01-01") == frozenset()


class TestDeterminism:
    def test_repeated_calls_match(self, cache_path):
        a = rbu.universe_on("2008-06-15", cache_path)
        b = rbu.universe_on("2008-06-15", cache_path)
        assert a == b

    def test_union_is_sorted_and_unique(self, cache_path):
        u = rbu.tickers_union_for_period("2008-01-01", "2014-12-31", cache_path)
        assert u == sorted(set(u))


class TestPortfolioResolution:
    def test_rule_prefix_resolves(self, cache_path):
        cfg = dict(cache_path, start_date="2008-01-01", end_date="2014-12-31")
        out = rbu.resolve_rule_portfolio("rule:us_liquid", cfg)
        assert out and "LIVE" in out

    def test_non_rule_value_returns_none(self, cache_path):
        cfg = dict(cache_path, start_date="2008-01-01", end_date="2014-12-31")
        assert rbu.resolve_rule_portfolio("pit:sp500", cfg) is None
        assert rbu.resolve_rule_portfolio("nasdaq_100.json", cfg) is None
        assert rbu.resolve_rule_portfolio(["AAPL"], cfg) is None


class TestCollisionReporting:
    def test_collision_is_reported_not_hidden(self, tmp_path):
        rows = [
            ["DUP-201005", "DUP", "2010-01", 40.0, 8e7, 3000, 21],
            ["DUP", "DUP", "2010-01", 40.0, 9e7, 3000, 21],
        ]
        p = tmp_path / "c.parquet"
        _cache(rows).to_parquet(p, index=False)
        rbu._load_cache_cached.cache_clear()
        cfg = {"universe_cache_path": str(p)}
        assert rbu.universe_on("2010-01-15", cfg) == ["DUP"]      # deduped
        coll = rbu.ticker_collisions("2010-01-01", "2010-12-31", cfg)
        assert len(coll) == 1
        assert coll.iloc[0]["kept"] == "DUP"                      # more liquid wins


class TestMissingCache:
    def test_helpful_error_when_cache_absent(self, tmp_path):
        rbu._load_cache_cached.cache_clear()
        with pytest.raises(FileNotFoundError, match="build_universe_cache"):
            rbu.universe_on("2010-01-01", {"universe_cache_path": str(tmp_path / "nope.parquet")})
