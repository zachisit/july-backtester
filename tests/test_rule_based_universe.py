# tests/test_rule_based_universe.py
"""
Tests for the rule-based point-in-time universe (zachisit/july-backtester-private-strategies#70).

Built on a synthetic corpus written to ``tmp_path`` — no dependency on the real
36k-security Parquet submodule, so these run anywhere.

The properties that matter are causality (only bars <= as_of are read),
survivorship (dead names present until they die, gone after), and security-level
identity (ticker reuse must never collapse two companies into one).
"""

import numpy as np
import pandas as pd
import pytest

from helpers.rule_based_universe import (
    COMMON_ETFS,
    ETF_TICKERS,
    etf_report,
    DEFAULTS,
    build_span_index,
    is_rule_spec,
    is_tradeable,
    parse_rule_spec,
    parse_security,
    resolve_universe,
)


# ---------------------------------------------------------------------------
# Synthetic corpus
# ---------------------------------------------------------------------------

def _write(tmp_path, name, start, end, price=50.0, volume=1_000_000, tz=None):
    idx = pd.date_range(start, end, freq="B", tz=tz)
    df = pd.DataFrame(
        {"Open": price, "High": price * 1.01, "Low": price * 0.99,
         "Close": float(price), "Volume": float(volume)},
        index=idx,
    )
    df.index.name = "Datetime"
    df.to_parquet(tmp_path / f"{name}.parquet")
    return df


@pytest.fixture
def corpus(tmp_path):
    """A miniature corpus exercising every case the real one contains."""
    # Long-lived, liquid.
    _write(tmp_path, "AAA", "2000-01-03", "2024-12-31", price=100, volume=5_000_000)
    _write(tmp_path, "BBB", "2000-01-03", "2024-12-31", price=80, volume=3_000_000)
    # Delisted mid-history — the survivorship case.
    _write(tmp_path, "DEAD-200806", "2000-01-03", "2008-06-30", price=60, volume=4_000_000)
    # Late IPO — must not appear before it exists.
    _write(tmp_path, "NEW", "2020-01-02", "2024-12-31", price=40, volume=2_000_000)
    # Penny stock — fails the price screen.
    _write(tmp_path, "PENNY", "2000-01-03", "2024-12-31", price=1.5, volume=9_000_000)
    # Illiquid — fails the dollar-volume screen.
    _write(tmp_path, "THIN", "2000-01-03", "2024-12-31", price=50, volume=100)
    # Ticker reuse: same bare ticker, two different companies.
    _write(tmp_path, "RU-200506", "2000-01-03", "2005-06-30", price=30, volume=3_000_000)
    _write(tmp_path, "RU", "2014-01-02", "2024-12-31", price=70, volume=3_000_000)
    # Non-investable index / breadth series, deliberately very "liquid".
    _write(tmp_path, "$IDX", "2000-01-03", "2024-12-31", price=4000, volume=90_000_000)
    _write(tmp_path, "#BREADTH", "2000-01-03", "2024-12-31", price=3000, volume=90_000_000)
    # tz-aware file — the corpus is not uniform.
    _write(tmp_path, "TZAWARE", "2000-01-03", "2024-12-31",
           price=55, volume=3_000_000, tz="UTC")
    return tmp_path


def _cfg(corpus, **over):
    cfg = {"parquet_data_dir": str(corpus), "universe_min_bars": 100}
    cfg.update(over)
    return cfg


# ---------------------------------------------------------------------------

class TestSecurityIdentity:

    @pytest.mark.parametrize("stem,ticker,delisted", [
        ("AAPL", "AAPL", None),
        ("BSC-200805", "BSC", "200805"),
        ("LEHMQ-201203", "LEHMQ", "201203"),
        ("BRK-A", "BRK-A", None),       # share class, not a delisting stamp
        ("MER-K", "MER-K", None),
        ("MER-200812", "MER", "200812"),
    ])
    def test_parse_security(self, stem, ticker, delisted):
        assert parse_security(stem) == (ticker, delisted)

    def test_share_class_is_not_mistaken_for_delisting(self):
        """Only a 6-digit suffix is a delisting stamp — BRK-A is alive."""
        assert parse_security("BRK-A")[1] is None
        assert parse_security("BRK-199001")[1] == "199001"

    def test_is_tradeable_rejects_index_and_breadth(self):
        assert not is_tradeable("$NYA")
        assert not is_tradeable("#NYSEAD")
        assert is_tradeable("AAPL")
        assert is_tradeable("BSC-200805")


class TestSpanIndex:

    def test_covers_every_security(self, corpus):
        idx = build_span_index(str(corpus))
        assert len(idx) == 11
        assert {"ticker", "delisted", "first_bar", "last_bar", "n_bars"} <= set(idx.columns)

    def test_spans_are_real_dates_not_1970(self, corpus):
        """The zachisit/july-backtester-private-strategies#68 trap: Datetime is not column 0, so locating it by position
        reads float OHLC as nanosecond timestamps and silently yields 1970."""
        idx = build_span_index(str(corpus))
        assert idx["first_bar"].min().year >= 2000
        assert idx.loc["DEAD-200806", "last_bar"].year == 2008

    def test_tz_aware_and_naive_coexist(self, corpus):
        """Mixed tz files must not make the index uncomparable."""
        idx = build_span_index(str(corpus))
        assert idx["first_bar"].dt.tz is None
        _ = idx["first_bar"] <= pd.Timestamp("2010-01-01")  # must not raise

    def test_cache_round_trips(self, corpus, tmp_path):
        cache = tmp_path / "cache" / "span.parquet"
        a = build_span_index(str(corpus), cache_path=str(cache))
        assert cache.exists()
        b = build_span_index(str(corpus), cache_path=str(cache))
        pd.testing.assert_frame_equal(a, b)

    def test_missing_corpus_raises_actionable_error(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="submodule"):
            build_span_index(str(tmp_path / "nope"))


class TestResolveUniverse:

    def test_excludes_index_and_breadth_series(self, corpus):
        """They out-rank everything on notional dollar volume if not removed."""
        u = resolve_universe("2015-06-30", _cfg(corpus))
        assert "$IDX" not in u and "#BREADTH" not in u

    def test_survivorship_dead_name_present_then_absent(self, corpus):
        before = resolve_universe("2007-06-29", _cfg(corpus))
        after = resolve_universe("2010-06-30", _cfg(corpus))
        assert "DEAD-200806" in before, "a company that was trading must be investable"
        assert "DEAD-200806" not in after, "a delisted company must drop out"

    def test_no_look_ahead_late_ipo_absent_before_listing(self, corpus):
        assert "NEW" not in resolve_universe("2015-06-30", _cfg(corpus))
        assert "NEW" in resolve_universe("2023-06-30", _cfg(corpus))

    def test_price_screen(self, corpus):
        assert "PENNY" not in resolve_universe(
            "2015-06-30", _cfg(corpus, universe_min_price=5.0))
        assert "PENNY" in resolve_universe(
            "2015-06-30", _cfg(corpus, universe_min_price=1.0))

    def test_dollar_volume_screen(self, corpus):
        assert "THIN" not in resolve_universe(
            "2015-06-30", _cfg(corpus, universe_min_dollar_volume=1_000_000))
        assert "THIN" in resolve_universe(
            "2015-06-30", _cfg(corpus, universe_min_dollar_volume=1_000))

    def test_min_bars_screen(self, corpus):
        """A name listed only weeks ago has no history to rank on."""
        soon = resolve_universe("2020-02-03", _cfg(corpus, universe_min_bars=252))
        assert "NEW" not in soon

    def test_ticker_reuse_resolves_to_the_right_company(self, corpus):
        """RU is one company until 2005 and a different one from 2014.

        Collapsing them by bare ticker would make a 2015 backtest trade 2004
        prices, or hold a company that no longer exists.
        """
        early = resolve_universe("2004-06-30", _cfg(corpus))
        late = resolve_universe("2016-06-30", _cfg(corpus))
        assert "RU-200506" in early and "RU" not in early
        assert "RU" in late and "RU-200506" not in late

    def test_top_n_caps_and_orders_by_dollar_volume(self, corpus):
        u = resolve_universe("2015-06-30", _cfg(corpus, universe_top_n=2))
        assert len(u) == 2
        assert u[0] == "AAA"  # highest dollar volume in the fixture

    def test_explicit_symbol_exclusion(self, corpus):
        assert "AAA" not in resolve_universe(
            "2015-06-30", _cfg(corpus, universe_exclude_symbols=["AAA"]))

    def test_symbol_exclusion_matches_delisted_variants(self, corpus):
        """Excluding 'RU' must also exclude 'RU-200506' — same company name."""
        u = resolve_universe("2004-06-30", _cfg(corpus, universe_exclude_symbols=["RU"]))
        assert "RU-200506" not in u

    def test_tz_aware_security_is_resolvable(self, corpus):
        assert "TZAWARE" in resolve_universe("2015-06-30", _cfg(corpus))

    def test_result_is_deterministic(self, corpus):
        a = resolve_universe("2015-06-30", _cfg(corpus))
        b = resolve_universe("2015-06-30", _cfg(corpus))
        assert a == b


class TestSpecParsing:

    def test_is_rule_spec(self):
        assert is_rule_spec("rule:us_liquid_1000")
        assert is_rule_spec("RULE:top100")
        assert not is_rule_spec("pit:sp500")
        assert not is_rule_spec("nasdaq_100.json")
        assert not is_rule_spec(["AAPL"])

    def test_presets(self):
        assert parse_rule_spec("rule:us_liquid_1000") == {"universe_top_n": 1000}
        assert parse_rule_spec("rule:us_all") == {"universe_top_n": None}

    def test_inline_top_n(self):
        assert parse_rule_spec("rule:top250") == {"universe_top_n": 250}

    def test_unknown_spec_raises(self):
        with pytest.raises(ValueError, match="Unknown rule universe"):
            parse_rule_spec("rule:nonsense")


class TestDefaults:

    def test_defaults_present(self):
        for key in ("universe_min_price", "universe_min_dollar_volume",
                    "universe_min_bars", "universe_top_n", "universe_adv_window"):
            assert key in DEFAULTS

    def test_etfs_excluded_by_default(self):
        """'Run stocks' is the common intent, and an unfiltered liquidity-ranked
        universe measured 13-19% ETFs (top-500) / 21-26% (top-100) post-2010."""
        assert DEFAULTS["universe_exclude_etfs"] is True
        assert DEFAULTS["universe_exclude_symbols"] == ()

    def test_etf_list_spans_categories(self):
        """A broad-market-only list misses the ETFs that actually pollute:
        commodity, currency, bond, leveraged and inverse products all rank."""
        for sym in ("SPY", "QQQ", "GLD", "TLT", "UUP", "TQQQ", "SQQQ",
                    "SH", "EWJ", "XLF", "HYG", "ARKK", "UVXY"):
            assert sym in ETF_TICKERS, f"{sym} missing from ETF_TICKERS"
        assert len(ETF_TICKERS) > 200


class TestEtfHandling:

    def test_etf_is_excluded_by_default(self, corpus):
        _write(corpus, "SPY", "2000-01-03", "2024-12-31", price=200, volume=80_000_000)
        assert "SPY" not in resolve_universe("2015-06-30", _cfg(corpus))

    def test_etf_kept_when_disabled(self, corpus):
        _write(corpus, "SPY", "2000-01-03", "2024-12-31", price=200, volume=80_000_000)
        u = resolve_universe("2015-06-30", _cfg(corpus, universe_exclude_etfs=False))
        assert "SPY" in u

    def test_etf_would_otherwise_dominate_top_n(self, corpus):
        """Without the filter SPY out-ranks every stock in the fixture — which is
        exactly what happens on the real corpus."""
        _write(corpus, "SPY", "2000-01-03", "2024-12-31", price=200, volume=80_000_000)
        with_etf = resolve_universe(
            "2015-06-30", _cfg(corpus, universe_top_n=1, universe_exclude_etfs=False))
        without = resolve_universe("2015-06-30", _cfg(corpus, universe_top_n=1))
        assert with_etf == ["SPY"]
        assert without == ["AAA"]

    def test_delisted_etf_variant_also_excluded(self, corpus):
        """Matching is on the bare ticker, so a closed ETF is excluded too."""
        _write(corpus, "TVIX-202007", "2010-01-04", "2020-07-01",
               price=100, volume=50_000_000)
        assert "TVIX-202007" not in resolve_universe("2015-06-30", _cfg(corpus))

    def test_etf_report_counts_and_percentages(self, corpus):
        rep = etf_report(["AAPL", "SPY", "MSFT", "QQQ", "GLD"])
        assert rep["n_etfs"] == 3 and rep["n_total"] == 5
        assert rep["etfs"] == ["GLD", "QQQ", "SPY"]
        assert rep["pct"] == pytest.approx(60.0)

    def test_etf_report_handles_delisted_ids_and_empty(self):
        assert etf_report(["TVIX-202007", "AAPL"])["n_etfs"] == 1
        assert etf_report([]) == {"etfs": [], "n_etfs": 0, "n_total": 0, "pct": 0.0}


# ---------------------------------------------------------------------------
# Periodic re-basing — @shardul0701's review finding on PR #292
# ---------------------------------------------------------------------------

from helpers.rule_based_universe import (  # noqa: E402
    REBASE_FREQUENCIES,
    build_rule_schedule,
    rebase_dates,
)


class TestRebaseDates:

    def test_annual_over_twenty_years_is_21_calls_not_5000(self):
        """The whole reason for periodic re-basing: per-bar is ~5,000 resolutions
        at ~10s each (~14h just to build the schedule). Annual is tractable."""
        d = rebase_dates("2004-01-02", "2024-01-02", "annual")
        assert len(d) == 21
        assert d[0] == "2004-01-02"
        assert d[-1] == "2024-01-02"

    def test_quarterly_is_denser(self):
        assert len(rebase_dates("2004-01-02", "2024-01-02", "quarterly")) == 81

    def test_start_date_is_always_included(self):
        for freq in list(REBASE_FREQUENCIES) + ["none"]:
            assert rebase_dates("2010-03-15", "2012-03-15", freq)[0] == "2010-03-15"

    def test_none_reproduces_the_frozen_behaviour(self):
        """The pre-fix behaviour must remain reachable, and must be exactly one
        resolution at start_date - not an approximation of it."""
        assert rebase_dates("2004-01-02", "2024-01-02", "none") == ["2004-01-02"]

    def test_dates_never_exceed_end_date(self):
        for d in rebase_dates("2004-01-02", "2007-06-01", "quarterly"):
            assert d <= "2007-06-01"

    def test_same_start_and_end_yields_one_date(self):
        assert rebase_dates("2020-01-02", "2020-01-02", "annual") == ["2020-01-02"]

    def test_reversed_window_raises(self):
        with pytest.raises(ValueError, match="precedes start_date"):
            rebase_dates("2024-01-02", "2004-01-02", "annual")

    def test_unknown_frequency_raises(self):
        with pytest.raises(ValueError, match="unknown universe_rebase"):
            rebase_dates("2004-01-02", "2024-01-02", "weekly")


class TestBuildRuleScheduleClosesTheStartDateBias:
    """THE invariant. Resolving once at start_date and freezing the result is a
    selection bias of the same shape as the survivorship bug this module exists
    to remove, pointing the other way: the universe can only shrink, so a name
    that becomes investable later can never be traded.

    @shardul0701's reproduction, as a test: OLDCO trades from 2004; NEWCO IPOs
    in 2015. A frozen universe never sees NEWCO. On the real corpus that is
    most mega-caps - NVDA, TSLA, META and GOOGL were not 2004 top-500-liquidity
    names.
    """

    @staticmethod
    def _fake_resolver(monkeypatch, membership_by_year):
        """Patch resolve_universe so the test drives the schedule logic, not I/O."""
        import helpers.rule_based_universe as rbu

        monkeypatch.setattr(rbu, "build_span_index", lambda *a, **k: None)

        def fake(as_of, config=None, span_index=None):
            year = int(str(as_of)[:4])
            return list(membership_by_year(year))
        monkeypatch.setattr(rbu, "resolve_universe", fake)

    def test_union_includes_a_security_that_qualifies_later(self, monkeypatch):
        self._fake_resolver(
            monkeypatch,
            lambda y: ["OLDCO"] if y < 2015 else ["NEWCO", "OLDCO"])
        union, _ = build_rule_schedule(
            "rule:top10", "2004-01-02", "2020-01-02", {}, frequency="annual")
        assert "NEWCO" in union, "a later-qualifying security must be fetchable"
        assert "OLDCO" in union

    def test_frozen_resolution_would_have_missed_it(self, monkeypatch):
        """Pins the bug itself, so the fix cannot silently regress."""
        self._fake_resolver(
            monkeypatch,
            lambda y: ["OLDCO"] if y < 2015 else ["NEWCO", "OLDCO"])
        frozen, _ = build_rule_schedule(
            "rule:top10", "2004-01-02", "2020-01-02", {}, frequency="none")
        assert frozen == ["OLDCO"]          # the old behaviour, reproduced
        rebased, _ = build_rule_schedule(
            "rule:top10", "2004-01-02", "2020-01-02", {}, frequency="annual")
        assert set(rebased) - set(frozen) == {"NEWCO"}

    def test_schedule_gates_the_security_before_it_qualifies(self, monkeypatch):
        """Union alone is not enough - fetching NEWCO from 2004 would let a
        strategy trade it years before it was investable. The schedule is what
        keeps the union causal."""
        from helpers.point_in_time import pit_members_on
        self._fake_resolver(
            monkeypatch,
            lambda y: ["OLDCO"] if y < 2015 else ["NEWCO", "OLDCO"])
        _, schedule = build_rule_schedule(
            "rule:top10", "2004-01-02", "2020-01-02", {}, frequency="annual")
        assert "NEWCO" not in pit_members_on(schedule, "2008-06-01")
        assert "NEWCO" in pit_members_on(schedule, "2018-06-01")
        assert "OLDCO" in pit_members_on(schedule, "2008-06-01")

    def test_schedule_shape_matches_the_pit_producer(self, monkeypatch):
        """It must be consumable by the existing pit_members_on() masking with
        no engine change - that is what makes this a wiring fix, not a rewrite."""
        self._fake_resolver(monkeypatch, lambda y: ["AAA", "BBB"])
        _, schedule = build_rule_schedule(
            "rule:top10", "2004-01-02", "2010-01-02", {}, frequency="annual")
        assert isinstance(schedule, list)
        for entry in schedule:
            assert isinstance(entry, tuple) and len(entry) == 2
            date_str, members = entry
            assert isinstance(date_str, str) and len(date_str) == 10
            assert isinstance(members, frozenset)
        assert schedule[0][0] == "2004-01-02"
        assert [e[0] for e in schedule] == sorted(e[0] for e in schedule)

    def test_identical_consecutive_snapshots_are_collapsed(self, monkeypatch):
        """A stable universe should not produce 21 duplicate entries."""
        self._fake_resolver(monkeypatch, lambda y: ["AAA", "BBB"])
        _, schedule = build_rule_schedule(
            "rule:top10", "2004-01-02", "2024-01-02", {}, frequency="annual")
        assert len(schedule) == 1

    def test_delisting_removes_a_security_from_later_snapshots(self, monkeypatch):
        self._fake_resolver(
            monkeypatch,
            lambda y: ["AAA", "DEADCO"] if y < 2009 else ["AAA"])
        from helpers.point_in_time import pit_members_on
        union, schedule = build_rule_schedule(
            "rule:top10", "2004-01-02", "2014-01-02", {}, frequency="annual")
        assert "DEADCO" in union                       # still needs fetching
        assert "DEADCO" in pit_members_on(schedule, "2006-01-01")
        assert "DEADCO" not in pit_members_on(schedule, "2012-01-01")

    def test_frequency_defaults_to_config_then_annual(self, monkeypatch):
        calls = []
        import helpers.rule_based_universe as rbu
        monkeypatch.setattr(rbu, "build_span_index", lambda *a, **k: None)

        def fake(as_of, config=None, span_index=None):
            calls.append(str(as_of))
            return ["AAA"]
        monkeypatch.setattr(rbu, "resolve_universe", fake)

        build_rule_schedule("rule:top10", "2004-01-02", "2008-01-02", {})
        assert len(calls) == 5                     # annual default

        calls.clear()
        build_rule_schedule("rule:top10", "2004-01-02", "2008-01-02",
                            {"universe_rebase": "none"})
        assert len(calls) == 1

    def test_span_index_is_built_once_not_per_rebase_date(self, monkeypatch):
        """Building it per date would multiply the expensive part by len(dates)."""
        import helpers.rule_based_universe as rbu
        builds = []
        monkeypatch.setattr(rbu, "build_span_index",
                            lambda *a, **k: builds.append(1))
        monkeypatch.setattr(rbu, "resolve_universe",
                            lambda as_of, config=None, span_index=None: ["AAA"])
        build_rule_schedule("rule:top10", "2004-01-02", "2024-01-02", {},
                            frequency="annual")
        assert len(builds) == 1

    def test_empty_corpus_still_returns_a_valid_shape(self, monkeypatch):
        self._fake_resolver(monkeypatch, lambda y: [])
        union, schedule = build_rule_schedule(
            "rule:top10", "2004-01-02", "2010-01-02", {}, frequency="annual")
        assert union == []
        assert schedule and schedule[0][1] == frozenset()


class TestUniverseRebaseValueHandling:
    """@shardul0701's two findings on the #292 approval.

    Both are the same shape: a value that LOOKS handled and isn't, failing in
    the case where the user most needs to be told.
    """

    def test_case_variants_all_freeze_the_universe(self):
        """`rebase_dates` lowercases, so "None"/"NONE" already freeze. The
        dispatch in main.py compared verbatim, so those spellings froze the
        universe while SKIPPING the warning - and left the membership mask built
        from the frozen snapshot rather than disabled."""
        for spelling in ("none", "None", "NONE", "nOnE"):
            assert rebase_dates("2004-01-02", "2024-01-02", spelling) == \
                ["2004-01-02"], spelling

    def test_case_variants_of_a_real_frequency_also_work(self):
        for spelling in ("annual", "Annual", "ANNUAL"):
            assert len(rebase_dates("2004-01-02", "2024-01-02", spelling)) == 21

    def test_main_dispatch_lowercases_before_comparing(self):
        """Source pin: the warning and the mask-disable both hang off this
        comparison, so a verbatim compare silently mishandles "None"."""
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "main.py"), encoding="utf-8").read()
        assert '_rebase = str(CONFIG.get("universe_rebase", "annual") or "annual").lower()' in src, (
            "main.py must lowercase universe_rebase before comparing it to "
            '"none" - otherwise "None" freezes the universe with no warning'
        )

    @pytest.mark.parametrize("bad", ["yearly", "ANNUALLY", "weekly", "1y", ""])
    def test_an_invalid_frequency_is_caught_at_config_validation(self, bad):
        """It was in KNOWN_KEYS but its DOMAIN was unregistered, so a typo passed
        validation and then raised inside build_rule_schedule - which main.py's
        `except Exception: continue` turned into one ERROR line and a silently
        dropped portfolio. Now it fails at startup, where it is attributable."""
        from helpers.config_validator import validate_config
        w = validate_config({"universe_rebase": bad})
        assert any("universe_rebase" in m for m in w), (
            f"{bad!r} passed config validation; it will drop the portfolio at "
            f"run time instead"
        )

    @pytest.mark.parametrize("good", ["none", "None", "annual", "QUARTERLY", "monthly"])
    def test_valid_frequencies_pass_validation(self, good):
        from helpers.config_validator import validate_config
        w = validate_config({"universe_rebase": good})
        assert not any("universe_rebase" in m for m in w), (
            f"{good!r} is valid but was flagged"
        )

    def test_absent_key_is_not_flagged(self):
        from helpers.config_validator import validate_config
        assert not any("universe_rebase" in m for m in validate_config({}))

    def test_the_validator_and_the_resolver_agree_on_the_domain(self):
        """THE invariant: anything validation accepts, rebase_dates must handle,
        and vice versa. Two independently-maintained lists is how this gap
        appeared in the first place."""
        from helpers.config_validator import validate_config
        from helpers.rule_based_universe import REBASE_FREQUENCIES
        domain = {"none", *REBASE_FREQUENCIES.keys()}
        for value in domain:
            assert not any("universe_rebase" in m
                           for m in validate_config({"universe_rebase": value}))
            rebase_dates("2020-01-01", "2021-01-01", value)   # must not raise
