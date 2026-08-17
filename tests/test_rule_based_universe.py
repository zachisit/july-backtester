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
    # Threshold/schedule/collision tests are orthogonal to the instrument-type
    # filter and use synthetic tickers (LIVE, THIN, WB, ...) that aren't real
    # SEC registrants. Point at a path that doesn't exist so the filter is a
    # documented no-op here rather than silently excluding everything --
    # TestInstrumentTypeFilter below exercises the filter itself.
    return {
        "universe_cache_path": str(p),
        "universe_sec_registrant_path": str(tmp_path / "no_sec_index_here.json"),
    }


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
        cfg = {
            "universe_cache_path": str(p),
            "universe_sec_registrant_path": str(tmp_path / "no_sec_index_here.json"),
        }
        assert rbu.universe_on("2010-01-15", cfg) == ["DUP"]      # deduped
        coll = rbu.ticker_collisions("2010-01-01", "2010-12-31", cfg)
        assert len(coll) == 1
        assert coll.iloc[0]["kept"] == "DUP"                      # more liquid wins


class TestMissingCache:
    def test_helpful_error_when_cache_absent(self, tmp_path):
        rbu._load_cache_cached.cache_clear()
        with pytest.raises(FileNotFoundError, match="build_universe_cache"):
            rbu.universe_on("2010-01-01", {"universe_cache_path": str(tmp_path / "nope.parquet")})


class TestTickerNormalisation:
    def test_dot_becomes_hyphen(self):
        assert rbu.normalise_universe_ticker("BRK.B") == "BRK-B"

    def test_already_hyphenated_is_unchanged(self):
        assert rbu.normalise_universe_ticker("BRK-B") == "BRK-B"

    def test_lowercase_is_upcased(self):
        assert rbu.normalise_universe_ticker("aapl") == "AAPL"

    def test_explicit_alias_applied(self):
        # Norgate stores the pre-2019 21st Century Fox entity as TFCFA; PIT
        # rosters record the same membership slot as FOXA (issue #70 defect 2).
        assert rbu.normalise_universe_ticker("TFCFA") == "FOXA"

    def test_unaliased_ticker_passes_through(self):
        assert rbu.normalise_universe_ticker("MSFT") == "MSFT"


class TestIsDelistedSecurity:
    def test_delisted_suffix_detected(self):
        assert rbu._is_delisted_security("WB-200812") is True

    def test_bare_ticker_is_not_delisted(self):
        assert rbu._is_delisted_security("WB") is False

    def test_suffix_must_be_six_digits_at_end(self):
        # A ticker that legitimately contains a hyphen+digits elsewhere (or a
        # short/malformed suffix) must not false-positive as delisted.
        assert rbu._is_delisted_security("BRK-B") is False
        assert rbu._is_delisted_security("FOO-1234") is False


class TestInstrumentTypeFilter:
    """issue #70 defect 1: no instrument-type filter meant ETFs/ETNs leaked
    into the rule-based universe (>=51/185 rule-only names in Zach's gate
    run). Every case here was found by actually running the filter against
    the real SEC registrant snapshot, not guessed -- including three false
    positives a first-draft keyword rule produced (NETFLIX INC matching a bare
    "ETF" substring, LXP/RLJ being real REITs literally named after their own
    ticker, and RY/Royal Bank of Canada's real equity sharing an ETN issuer's
    exact title) before being fixed.
    """

    def _idx(self, **tickers):
        return {t.upper(): title for t, title in tickers.items()}

    def test_absent_from_sec_index_is_excluded(self):
        # The majority case: '40 Act ETFs (IWM, XLF, EFA, ...) never file as
        # Exchange Act registrants at all.
        assert rbu.is_operating_company("IWM", self._idx(AAPL="Apple Inc.")) is False

    def test_real_company_in_index_is_included(self):
        assert rbu.is_operating_company("AAPL", self._idx(AAPL="Apple Inc.")) is True

    def test_no_index_configured_is_a_no_op(self):
        assert rbu.is_operating_company("ANYTHING", None) is True

    def test_legacy_uit_with_etf_in_title_excluded(self):
        idx = self._idx(SPY="SPDR S&P 500 ETF TRUST")
        assert rbu.is_operating_company("SPY", idx) is False

    def test_legacy_uit_without_etf_in_title_excluded(self):
        idx = self._idx(QQQ="INVESCO QQQ TRUST, SERIES 1")
        assert rbu.is_operating_company("QQQ", idx) is False

    def test_commodity_trust_excluded(self):
        idx = self._idx(GLD="SPDR GOLD TRUST")
        assert rbu.is_operating_company("GLD", idx) is False

    def test_bank_issued_etn_excluded(self):
        idx = self._idx(VXX="BARCLAYS BANK PLC")
        assert rbu.is_operating_company("VXX", idx) is False

    def test_reit_with_trust_in_title_not_excluded(self):
        # The bare "TRUST" keyword a first draft used would wrongly exclude
        # real S&P 500 REITs that are legally structured as trusts.
        idx = self._idx(DLR="DIGITAL REALTY TRUST, INC.")
        assert rbu.is_operating_company("DLR", idx) is True

    def test_mlp_with_lp_in_title_not_excluded(self):
        idx = self._idx(EPD="ENTERPRISE PRODUCTS PARTNERS L.P.")
        assert rbu.is_operating_company("EPD", idx) is True

    def test_reit_named_after_its_own_ticker_not_excluded(self):
        # LXP Industrial Trust and RLJ Lodging Trust are real REITs, not UITs
        # -- a naive "ticker appears in its own filed title" rule would wrongly
        # exclude them the same way it correctly flags "INVESCO QQQ TRUST".
        assert rbu.is_operating_company("LXP", self._idx(LXP="LXP Industrial Trust")) is True
        assert rbu.is_operating_company("RLJ", self._idx(RLJ="RLJ Lodging Trust")) is True

    def test_word_containing_etf_as_substring_not_excluded(self):
        # "NETFLIX" contains the literal substring "ETF" (n-ETF-lix); the
        # marker match must be whole-word, not substring.
        assert rbu.is_operating_company("NFLX", self._idx(NFLX="NETFLIX INC")) is True

    def test_word_containing_gold_as_substring_not_excluded(self):
        # "Goldman Sachs" contains the substring "GOLD"; combined with a
        # "Trust" title that must not trigger the commodity-trust rule.
        idx = self._idx(GJS="STRATS(SM) Trust for Goldman Sachs Group Securities, Series 2006-2")
        assert rbu.is_operating_company("GJS", idx) is True

    def test_bank_equity_sharing_etn_issuer_title_not_excluded(self):
        # Royal Bank of Canada's own common stock (RY) files under the exact
        # same title text ("ROYAL BANK OF CANADA") that would otherwise be
        # used to detect RBC-issued ETNs -- title alone can't disambiguate,
        # so that bank was dropped from the ETN issuer set entirely.
        idx = self._idx(RY="ROYAL BANK OF CANADA")
        assert rbu.is_operating_company("RY", idx) is True

    def test_delisted_and_absent_from_index_is_kept(self):
        # PR #281 review finding: a blanket absence rule wrongly treats "not
        # currently registered" as "was always a fund". Lehman Brothers (LEH,
        # delisted 2008) is absent from a snapshot taken today for the same
        # reason any failed company is -- it no longer exists to register --
        # not because it was ever a fund. Measured: 91.4% of the corpus's
        # delisted securities were absent and would have been wrongly
        # excluded under the pre-fix blanket rule.
        idx = self._idx(AAPL="Apple Inc.")
        assert rbu.is_operating_company("LEH", idx, is_delisted=True) is True

    def test_live_and_absent_from_index_is_still_excluded(self):
        # The default (is_delisted=False) is unchanged by this fix: a name
        # still trading today that's absent from the registrant index is
        # still presumed a fund/ETF, same as before.
        idx = self._idx(AAPL="Apple Inc.")
        assert rbu.is_operating_company("IWM", idx) is False
        assert rbu.is_operating_company("IWM", idx, is_delisted=False) is False

    def test_delisted_fund_present_in_index_still_excluded_by_title(self):
        # is_delisted only widens the absence case; positive title detection
        # still applies unconditionally -- a delisted fund sponsor that DID
        # register with the SEC stays excluded either way.
        idx = self._idx(TVIX="CREDIT SUISSE AG")
        assert rbu.is_operating_company("TVIX", idx, is_delisted=True) is False

    def test_eligible_rows_keeps_delisted_company_absent_from_index(self, tmp_path):
        # End-to-end reproduction of Zach's PR #281 finding: a real, delisted
        # operating company (modeled on Lehman Brothers -- Norgate security
        # "LEH-200809", ticker "LEH") absent from the SEC snapshot must
        # survive the filter, while a live name (IWM) absent from that same
        # snapshot must still be excluded.
        rows = [
            ["LEH-200809", "LEH", "2008-06", 60.0, 5e7, 3000, 21],
            ["IWM", "IWM", "2008-06", 60.0, 5e7, 3000, 21],
        ]
        cache_p = tmp_path / "cache.parquet"
        _cache(rows).to_parquet(cache_p, index=False)
        sec_p = tmp_path / "sec.json"
        sec_p.write_text('{"tickers": {"AAPL": "Apple Inc."}}', encoding="utf-8")
        rbu._load_cache_cached.cache_clear()
        rbu._load_sec_index_cached.cache_clear()
        cfg = {"universe_cache_path": str(cache_p), "universe_sec_registrant_path": str(sec_p)}
        assert rbu.universe_on("2008-06-15", cfg) == ["LEH"]

    def test_eligible_rows_applies_filter_when_configured(self, tmp_path):
        rows = [
            ["REALCO", "REALCO", "2020-01", 50.0, 5e7, 3000, 21],
            ["ETFCO", "ETFCO", "2020-01", 50.0, 5e7, 3000, 21],
        ]
        cache_p = tmp_path / "cache.parquet"
        _cache(rows).to_parquet(cache_p, index=False)
        sec_p = tmp_path / "sec.json"
        sec_p.write_text(
            '{"tickers": {"REALCO": "Real Operating Co Inc.", '
            '"ETFCO": "Some Sponsor ETF Trust"}}',
            encoding="utf-8",
        )
        rbu._load_cache_cached.cache_clear()
        rbu._load_sec_index_cached.cache_clear()
        cfg = {"universe_cache_path": str(cache_p), "universe_sec_registrant_path": str(sec_p)}
        assert rbu.universe_on("2020-01-15", cfg) == ["REALCO"]

    def test_filter_disabled_by_config_keeps_everything(self, tmp_path):
        rows = [["ETFCO", "ETFCO", "2020-01", 50.0, 5e7, 3000, 21]]
        cache_p = tmp_path / "cache.parquet"
        _cache(rows).to_parquet(cache_p, index=False)
        sec_p = tmp_path / "sec.json"
        sec_p.write_text('{"tickers": {"ETFCO": "Some Sponsor ETF Trust"}}', encoding="utf-8")
        rbu._load_cache_cached.cache_clear()
        rbu._load_sec_index_cached.cache_clear()
        cfg = {
            "universe_cache_path": str(cache_p),
            "universe_sec_registrant_path": str(sec_p),
            "universe_exclude_non_operating_companies": False,
        }
        assert rbu.universe_on("2020-01-15", cfg) == ["ETFCO"]
