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


class TestInstrumentTypeFilter:
    """issue #70 defect 1, revised scope: the universe is broker-constrained,
    not index-shaped (requirement change, 2026-08-16) -- Zach's tradeable set
    is "US common stock (ADRs included) + any ETF Vanguard permits buying
    long", so plain ETFs stay IN and only leveraged/inverse ETFs and ETNs
    (Vanguard's January 2019 no-buy list) are excluded. This supersedes the
    earlier "exclude every non-operating-company" version of this filter,
    whose absence-based mechanism also caused the PR #281 survivorship
    defect (91.4% of delisted securities wrongly excluded) -- that mechanism
    is gone now, not patched, since positive identification never uses
    absence at all.
    """

    def _idx(self, **tickers):
        return {t.upper(): title for t, title in tickers.items()}

    def test_no_index_configured_is_a_no_op(self):
        assert rbu.is_leveraged_inverse_or_etn("ANYTHING", None) is False

    def test_absent_from_index_never_excluded(self):
        # Core behavioural change: absence used to exclude (old filter) or
        # exclude-only-if-live (PR #281 interim); now it never excludes
        # anyone -- an unknown ticker could be a plain ETF (which belongs) or
        # a delisted operating company (which must be kept), and this filter
        # can't tell them apart, so it doesn't try.
        idx = self._idx(AAPL="Apple Inc.")
        assert rbu.is_leveraged_inverse_or_etn("IWM", idx) is False
        assert rbu.is_leveraged_inverse_or_etn("LEH", idx) is False

    def test_real_operating_company_not_excluded(self):
        assert rbu.is_leveraged_inverse_or_etn("AAPL", self._idx(AAPL="Apple Inc.")) is False

    def test_plain_index_etf_not_excluded(self):
        # SPY/IWM/GLD-style plain ETFs are the whole point of the requirement
        # change -- they must pass even when their real SEC title is known
        # and contains "ETF"/"TRUST".
        idx = self._idx(
            SPY="SPDR S&P 500 ETF TRUST",
            QQQ="INVESCO QQQ TRUST, SERIES 1",
            IWM="ISHARES RUSSELL 2000 ETF",
            GLD="SPDR GOLD TRUST",
        )
        assert rbu.is_leveraged_inverse_or_etn("SPY", idx) is False
        assert rbu.is_leveraged_inverse_or_etn("QQQ", idx) is False
        assert rbu.is_leveraged_inverse_or_etn("IWM", idx) is False
        assert rbu.is_leveraged_inverse_or_etn("GLD", idx) is False

    def test_proshares_ultrapro_leveraged_excluded(self):
        idx = self._idx(TQQQ="PROSHARES ULTRAPRO QQQ")
        assert rbu.is_leveraged_inverse_or_etn("TQQQ", idx) is True

    def test_proshares_ultra_leveraged_excluded(self):
        idx = self._idx(SSO="PROSHARES ULTRA S&P500")
        assert rbu.is_leveraged_inverse_or_etn("SSO", idx) is True

    def test_proshares_ultrashort_inverse_excluded(self):
        idx = self._idx(SDS="PROSHARES ULTRASHORT S&P500")
        assert rbu.is_leveraged_inverse_or_etn("SDS", idx) is True

    def test_proshares_short_inverse_excluded(self):
        idx = self._idx(SH="PROSHARES SHORT S&P500")
        assert rbu.is_leveraged_inverse_or_etn("SH", idx) is True

    def test_direxion_bull_leveraged_excluded(self):
        idx = self._idx(SOXL="DIREXION DAILY SEMICONDUCTOR BULL 3X SHARES")
        assert rbu.is_leveraged_inverse_or_etn("SOXL", idx) is True

    def test_direxion_bear_inverse_excluded(self):
        idx = self._idx(TZA="DIREXION DAILY SMALL CAP BEAR 3X SHARES")
        assert rbu.is_leveraged_inverse_or_etn("TZA", idx) is True

    def test_etn_excluded_regardless_of_issuer(self):
        idx = self._idx(
            VXX="IPATH SERIES B S&P 500 VIX SHORT-TERM FUTURES ETN",
            DJP="IPATH SERIES B BLOOMBERG COMMODITY INDEX TOTAL RETURN ETN",
        )
        assert rbu.is_leveraged_inverse_or_etn("VXX", idx) is True
        assert rbu.is_leveraged_inverse_or_etn("DJP", idx) is True

    def test_generic_multiplier_and_direction_fallback_excludes_new_issuers(self):
        # Newer single-stock leveraged ETFs (GraniteShares, MicroSectors, ...)
        # don't use the ProShares/Direxion house style but do state the
        # multiplier and direction explicitly in their own filed title.
        idx = self._idx(CONL="GRANITESHARES 2X LONG COIN DAILY ETF")
        assert rbu.is_leveraged_inverse_or_etn("CONL", idx) is True

    def test_reit_with_trust_in_title_not_excluded(self):
        idx = self._idx(DLR="DIGITAL REALTY TRUST, INC.")
        assert rbu.is_leveraged_inverse_or_etn("DLR", idx) is False

    def test_reit_named_after_its_own_ticker_not_excluded(self):
        assert rbu.is_leveraged_inverse_or_etn("LXP", self._idx(LXP="LXP Industrial Trust")) is False
        assert rbu.is_leveraged_inverse_or_etn("RLJ", self._idx(RLJ="RLJ Lodging Trust")) is False

    def test_company_named_aetna_does_not_substring_match_etn(self):
        # "AETNA" contains the letters "ETN" but not as a whole word -- the
        # marker match must be whole-word, not substring.
        idx = self._idx(AET="AETNA INC")
        assert rbu.is_leveraged_inverse_or_etn("AET", idx) is False

    def test_direction_word_alone_without_multiplier_not_excluded(self):
        # "LONG"/"BULL"/"BEAR"/"SHORT" alone (no "2X"/"3X", no ProShares/
        # Direxion issuer word) must not trip the generic fallback -- real
        # company names can legitimately contain these as standalone words.
        idx = self._idx(LTEA="LONG ISLAND ICED TEA CORP")
        assert rbu.is_leveraged_inverse_or_etn("LTEA", idx) is False

    def test_bank_equity_sharing_word_with_etn_issuers_not_excluded(self):
        # A bank's own common stock (e.g. Royal Bank of Canada, RY) must not
        # be excluded just because other banks issue ETNs -- this filter no
        # longer keys off issuer identity at all, only the security's own
        # title, so this is safe by construction.
        idx = self._idx(RY="ROYAL BANK OF CANADA")
        assert rbu.is_leveraged_inverse_or_etn("RY", idx) is False

    def test_eligible_rows_keeps_plain_etf_and_delisted_company_absent_from_index(self, tmp_path):
        # End-to-end reproduction of the requirement change: a plain ETF
        # (IWM) and a delisted operating company absent from the SEC
        # snapshot (modeled on Lehman Brothers) are both now kept.
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
        assert rbu.universe_on("2008-06-15", cfg) == ["IWM", "LEH"]

    def test_eligible_rows_excludes_leveraged_etf_when_configured(self, tmp_path):
        rows = [
            ["REALCO", "REALCO", "2020-01", 50.0, 5e7, 3000, 21],
            ["LEVCO", "LEVCO", "2020-01", 50.0, 5e7, 3000, 21],
        ]
        cache_p = tmp_path / "cache.parquet"
        _cache(rows).to_parquet(cache_p, index=False)
        sec_p = tmp_path / "sec.json"
        sec_p.write_text(
            '{"tickers": {"REALCO": "Real Operating Co Inc.", '
            '"LEVCO": "PROSHARES ULTRAPRO SOME INDEX"}}',
            encoding="utf-8",
        )
        rbu._load_cache_cached.cache_clear()
        rbu._load_sec_index_cached.cache_clear()
        cfg = {"universe_cache_path": str(cache_p), "universe_sec_registrant_path": str(sec_p)}
        assert rbu.universe_on("2020-01-15", cfg) == ["REALCO"]

    def test_filter_disabled_by_config_keeps_everything(self, tmp_path):
        rows = [["LEVCO", "LEVCO", "2020-01", 50.0, 5e7, 3000, 21]]
        cache_p = tmp_path / "cache.parquet"
        _cache(rows).to_parquet(cache_p, index=False)
        sec_p = tmp_path / "sec.json"
        sec_p.write_text('{"tickers": {"LEVCO": "PROSHARES ULTRAPRO SOME INDEX"}}', encoding="utf-8")
        rbu._load_cache_cached.cache_clear()
        rbu._load_sec_index_cached.cache_clear()
        cfg = {
            "universe_cache_path": str(cache_p),
            "universe_sec_registrant_path": str(sec_p),
            "universe_exclude_leveraged_inverse_etn": False,
        }
        assert rbu.universe_on("2020-01-15", cfg) == ["LEVCO"]
