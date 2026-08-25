# tests/test_rule_based_universe.py
"""
Tests for the rule-based point-in-time universe (issue #70).

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
        """The #68 trap: Datetime is not column 0, so locating it by position
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

    def test_etf_list_is_advisory_not_default(self):
        """ETFs are investable — excluding them must be an explicit choice."""
        assert DEFAULTS["universe_exclude_symbols"] == ()
        assert "SPY" in COMMON_ETFS
