"""tests/test_data_quality_sentinel.py

Issue #350: the merged corpus carries closes of EXACTLY 1e-06 sitting next to
normal bars, and stitched/recycled tickers wearing one symbol.

The sentinel is a fabricated round-trip — collapse to the floor, bounce back on
the next bar — measured at 23,695+ bars across 782+ series. They are not
sub-penny stocks, which is what makes it a defect rather than tick noise: FMNJ,
NEOM and RINO have median closes of $10.00, $8.70 and $8.50 against a 1e-06
minimum.

The bar that mattered: an affected series scored **92/100 and passed** the
existing checks. Every other check here is proportional to how much data is
affected; this one must not be, because ONE sentinel bar is a fake round-trip
that a mean-reversion strategy will trade.
"""

import numpy as np
import pandas as pd
import pytest

from helpers.data_quality import (
    _DENSITY_MIN_BARS_PER_YEAR,
    _GAP_DEMERITS,
    _GAP_MAX_DAYS,
    _SENTINEL_CLOSE,
    _SENTINEL_DEMERITS,
    validate_ohlcv,
)

_IDX = pd.bdate_range("2020-01-01", periods=600)


def _frame(closes, index=None):
    idx = index if index is not None else _IDX[:len(closes)]
    return pd.DataFrame(
        {"Open": closes,
         "High": [c * 1.01 for c in closes],
         "Low": [c * 0.99 for c in closes],
         "Close": closes,
         "Volume": [1_000_000] * len(closes)},
        index=idx)


def _clean(n=500):
    return [10.0 + (i % 5) * 0.1 for i in range(n)]


class TestSentinelCloses:
    def test_clean_series_scores_100(self):
        """The control. Without it, a check that always demerits would pass
        every test below."""
        score, issues = validate_ohlcv(_frame(_clean()), "CLEAN", "D")
        assert score == 100.0, issues
        assert not issues

    def test_a_single_sentinel_bar_is_blocking(self):
        """ONE bar. The whole point: proportional scoring let an affected
        series through at 92/100."""
        closes = _clean()
        closes[250] = _SENTINEL_CLOSE
        score, issues = validate_ohlcv(_frame(closes), "FMNJ", "D")
        assert any("Sentinel prices" in i for i in issues), issues
        assert score < 80.0, (
            f"a fabricated round-trip scored {score} — high enough to pass a "
            f"quality gate, which is exactly how #350 went unnoticed")

    def test_sentinel_is_reported_with_its_count(self):
        closes = _clean()
        for i in (100, 200, 300):
            closes[i] = _SENTINEL_CLOSE
        _, issues = validate_ohlcv(_frame(closes), "NEOM", "D")
        hit = [i for i in issues if "Sentinel prices" in i]
        assert hit and "3 bars" in hit[0], issues

    def test_matches_only_the_exact_sentinel_not_small_prices(self):
        """A genuine sub-penny stock must NOT be flagged — the defect is the
        exact value 1e-06 next to normal bars, not smallness."""
        score, issues = validate_ohlcv(
            _frame([0.0004 + (i % 3) * 0.00001 for i in range(500)]),
            "PENNY", "D")
        assert not any("Sentinel prices" in i for i in issues), issues

    def test_near_miss_values_are_not_flagged(self):
        closes = _clean()
        closes[250] = 1e-05          # an order of magnitude away
        _, issues = validate_ohlcv(_frame(closes), "NEAR", "D")
        assert not any("Sentinel prices" in i for i in issues), issues

    def test_survives_nan_and_inf_closes(self):
        """The sentinel check coerces and compares elementwise, so NaN/inf in
        the column must neither raise nor be counted as sentinels.

        Scoped deliberately: a *string* in Close breaks an earlier check in
        validate_ohlcv that predates this work, so asserting on that here would
        be testing someone else's contract.
        """
        closes = _clean(50)
        closes[5] = float("nan")
        closes[6] = float("inf")
        score, issues = validate_ohlcv(_frame(closes), "ODD", "D")
        assert 0.0 <= score <= 100.0
        assert not any("Sentinel prices" in i for i in issues), issues


    def test_sentinel_on_low_is_caught(self):
        """The shape that actually TRADES.

        Every daily-bar stop in this engine fills off `Low`, so a fabricated
        wick to the floor is worse than a fabricated close — and a Close-only
        scan scored exactly this bar 100/100 with zero issues.
        """
        closes = _clean()
        lows = [c * 0.99 for c in closes]
        lows[250] = _SENTINEL_CLOSE
        df = _frame(closes)
        df["Low"] = lows
        score, issues = validate_ohlcv(df, "WICK", "D")
        assert any("Sentinel prices" in i for i in issues), issues
        assert score < 80.0

    def test_sentinel_in_a_lowercase_close_column_is_caught(self):
        """The merged store writes LOWERCASE ohlcv — the corpus this check
        exists for. Looking only for "Close" made a raw audit of it a no-op."""
        closes = _clean()
        closes[250] = _SENTINEL_CLOSE
        df = _frame(closes)
        df.columns = [c.lower() for c in df.columns]
        score, issues = validate_ohlcv(df, "LOWER", "D")
        assert any("Sentinel prices" in i for i in issues), issues
        assert score < 80.0

    def test_a_bar_with_several_sentinel_columns_counts_once(self):
        """Counted in BARS, not cells — otherwise one bad bar with O/H/L/C all
        at the floor would report as four."""
        closes = _clean()
        closes[250] = _SENTINEL_CLOSE
        df = _frame(closes)
        for col in ("Open", "High", "Low"):
            df.iloc[250, df.columns.get_loc(col)] = _SENTINEL_CLOSE
        _, issues = validate_ohlcv(df, "ALLFOUR", "D")
        hit = [i for i in issues if "Sentinel prices" in i]
        assert hit and "1 bars" in hit[0], issues

    def test_a_float32_stored_sentinel_is_still_caught(self):
        """Pins the tolerance from BELOW. Every other test probes it from
        above (sub-penny, near-miss), so `atol=0.0` — exact equality only —
        survived mutation. float32 round-trip error is ~2.5e-15."""
        closes = _clean()
        closes[250] = _SENTINEL_CLOSE
        df = _frame(closes)
        # EVERY price column cast — casting only Close left the exact 1e-06
        # sitting in Open, so the assertion passed via a column that had not
        # been through float32 at all and `atol=0.0` survived mutation. The
        # test has to remove every other route to the answer.
        for col in ("Open", "High", "Low", "Close"):
            df[col] = df[col].astype("float32")
        stored = float(np.float32(_SENTINEL_CLOSE))
        assert stored != _SENTINEL_CLOSE, (
            "float32 round-trips 1e-06 exactly on this platform, so this test "
            "cannot pin the tolerance — pick a different dtype")
        _, issues = validate_ohlcv(df, "F32", "D")
        assert any("Sentinel prices" in i for i in issues), issues


class TestBarDensity:
    def test_sparse_long_span_is_flagged(self):
        """A listed equity trades ~252 days/yr. 10/yr over a decade is a
        stitched or recycled ticker wearing one symbol."""
        idx = pd.to_datetime(
            [f"{y}-01-{d:02d}" for y in range(2015, 2025) for d in range(1, 11)])
        df = pd.DataFrame(
            {"Open": 10.0, "High": 10.1, "Low": 9.9, "Close": 10.0,
             "Volume": 1_000_000},
            index=idx)
        score, issues = validate_ohlcv(df, "FER", "D")
        assert any("Sparse history" in i for i in issues), issues

    def test_a_normal_short_series_is_not_flagged(self):
        """No false positive on a young listing — the span guard exists so a
        legitimately short history is not called sparse."""
        _, issues = validate_ohlcv(_frame(_clean(200)), "IPO", "D")
        assert not any("Sparse history" in i for i in issues), issues

    def test_a_dense_long_series_is_not_flagged(self):
        _, issues = validate_ohlcv(_frame(_clean(600)), "AAPL", "D")
        assert not any("Sparse history" in i for i in issues), issues

    def test_a_dense_gap_dense_series_is_flagged(self):
        """The canonical RECYCLED-TICKER shape — and the check could not catch
        the thing it is named for.

        Two dense eras with a 13-year hole. Years with no bars contribute no
        group, so a median over *trading* years read 261 bars/yr — perfectly
        dense — and the series scored exactly 80.0, passing a strict `< 80`
        gate. Measuring bars/SPAN makes the hole count, which is the point.
        """
        a = pd.bdate_range("2000-01-01", "2001-12-31")
        b = pd.bdate_range("2015-01-01", "2016-12-31")
        df = pd.DataFrame(
            {"Open": 10.0, "High": 10.1, "Low": 9.9, "Close": 10.0,
             "Volume": 1_000_000},
            index=a.append(b))
        score, issues = validate_ohlcv(df, "RECYCLED", "D")
        assert any("Sparse history" in i for i in issues), issues
        assert score < 80.0, (
            f"scored {score} — a recycled ticker passing the gate is the "
            f"failure this check exists to prevent")

    def test_density_actually_costs_score(self):
        """Without this, setting the demerits to 0 survives mutation — the
        flag would be cosmetic."""
        idx = pd.to_datetime(
            [f"{y}-01-{d:02d}" for y in range(2015, 2025) for d in range(1, 11)])
        df = pd.DataFrame(
            {"Open": 10.0, "High": 10.1, "Low": 9.9, "Close": 10.0,
             "Volume": 1_000_000},
            index=idx)
        score, _ = validate_ohlcv(df, "FER", "D")
        assert score <= 75.0, score

    def test_density_is_skipped_for_non_daily_timeframes(self):
        """A weekly series is ~52 bars/yr by construction. Without this,
        running the check on every timeframe survives mutation."""
        idx = pd.date_range("2015-01-01", periods=520, freq="W")
        df = pd.DataFrame(
            {"Open": 10.0, "High": 10.1, "Low": 9.9, "Close": 10.0,
             "Volume": 1_000_000},
            index=idx)
        _, issues = validate_ohlcv(df, "WEEKLY", "W")
        assert not any("Sparse history" in i for i in issues), issues

    def test_threshold_is_the_documented_one(self):
        """Pin the constant, so a future loosening is deliberate."""
        assert _DENSITY_MIN_BARS_PER_YEAR == 150


# --- QA round 2 (adversarial audit of the checks above) -----------------------
# Every test below reproduces a hole found by attacking the first cut. Each one
# fails against the pre-fix implementation.


class TestIndexOrderIndependence:
    """A newest-first index must not buy a series a free pass.

    `index[-1] - index[0]` goes NEGATIVE on a descending index, fails the
    `> _DENSITY_MIN_YEARS` gate, and skips CHECK 8 entirely. Not hypothetical:
    services/csv_service.py never sorts its index (the other three providers
    do), and the Nasdaq.com export format it supports is newest-first.
    """

    @staticmethod
    def _sparse_index():
        return pd.to_datetime(
            [f"{y}-01-{d:02d}" for y in range(2015, 2025) for d in range(1, 11)])

    def _frame_for(self, idx):
        return pd.DataFrame(
            {"Open": 10.0, "High": 10.1, "Low": 9.9, "Close": 10.0,
             "Volume": 1_000_000},
            index=idx)

    def test_descending_index_still_flags_sparse_history(self):
        idx = self._sparse_index()[::-1]
        _, issues = validate_ohlcv(self._frame_for(idx), "FER", "D")
        assert any("Sparse history" in i for i in issues), issues

    def test_descending_index_scores_the_same_as_ascending(self):
        """The score must be a property of the data, not of row order."""
        asc = self._sparse_index()
        asc_score, _ = validate_ohlcv(self._frame_for(asc), "FER", "D")
        desc_score, _ = validate_ohlcv(self._frame_for(asc[::-1]), "FER", "D")
        assert desc_score == asc_score, (
            f"ascending {asc_score} vs descending {desc_score} — row order "
            f"must not change the verdict")


class TestInternalHistoryGap:
    """bars/span cannot separate "uniformly thin" from "two dense eras with a
    hole in between" — only the gap itself can.

    A ratio only trips once >40% of the span is missing, so the real recycled
    shapes were passing: a 5-year hole in a 20-year span scored 87.0, and the
    sub-3-year variant landed on exactly 80.0 — not below it — sliding under
    the strict `< 80` gate this PR exists to close.
    """

    @staticmethod
    def _two_eras(a_start, a_bars, b_start, b_bars):
        a = pd.bdate_range(a_start, periods=a_bars)
        b = pd.bdate_range(b_start, periods=b_bars)
        return pd.DataFrame(
            {"Open": 10.0, "High": 10.1, "Low": 9.9, "Close": 10.0,
             "Volume": 1_000_000},
            index=a.append(b))

    def test_multi_year_hole_in_a_long_span_is_flagged(self):
        """7 dense years, a 5-year hole, 8 dense years — 196 bars/yr, which
        sails past a 150 floor. Scored 87.0 and passed."""
        df = self._two_eras("2005-01-03", 252 * 7, "2017-01-02", 252 * 8)
        score, issues = validate_ohlcv(df, "SSCC", "D")
        assert any("History gap" in i for i in issues), issues
        assert score < 80.0, f"scored {score} — passes the default gate"

    def test_sub_three_year_recycled_shape_is_flagged(self):
        """The razor's edge: 6mo, a 2-year hole, 6mo, all inside a 2.89-year
        span. CHECK 8 is off below 3 years and CHECK 6's demerit is capped at
        20, so this landed on EXACTLY 80.0 and passed a `< 80` gate."""
        df = self._two_eras("2020-01-01", 126, "2022-06-01", 126)
        score, issues = validate_ohlcv(df, "RECYCLED2", "D")
        assert any("History gap" in i for i in issues), issues
        assert score < 80.0, f"scored {score} — passes the default gate"

    def test_a_dense_continuous_series_has_no_gap_flag(self):
        """The control. Weekends and holidays are not gaps."""
        _, issues = validate_ohlcv(_frame(_clean(600)), "AAPL", "D")
        assert not any("History gap" in i for i in issues), issues

    def test_a_thin_but_continuous_series_has_no_gap_flag(self):
        """Separates the two checks: uniformly thin trips density, NOT gap.
        Without this, the gap check could just duplicate the density check."""
        idx = pd.to_datetime(
            [f"{y}-{m:02d}-01" for y in range(2015, 2025) for m in range(1, 13)])
        df = pd.DataFrame(
            {"Open": 10.0, "High": 10.1, "Low": 9.9, "Close": 10.0,
             "Volume": 1_000_000},
            index=idx)
        _, issues = validate_ohlcv(df, "THIN", "D")
        assert any("Sparse history" in i for i in issues), issues
        assert not any("History gap" in i for i in issues), issues

    def test_gap_actually_costs_score(self):
        """Without this, setting the demerits to 0 survives mutation."""
        df = self._two_eras("2005-01-03", 252 * 7, "2017-01-02", 252 * 8)
        score, _ = validate_ohlcv(df, "SSCC", "D")
        assert score <= 100.0 - _GAP_DEMERITS, score

    def test_gap_check_is_skipped_for_non_daily_timeframes(self):
        """A monthly series has ~30-day steps by construction; a sparse
        monthly history must not be read as a recycled ticker."""
        idx = pd.date_range("2010-01-01", periods=180, freq="MS")
        df = pd.DataFrame(
            {"Open": 10.0, "High": 10.1, "Low": 9.9, "Close": 10.0,
             "Volume": 1_000_000},
            index=idx)
        _, issues = validate_ohlcv(df, "MONTHLY", "M")
        assert not any("History gap" in i for i in issues), issues

    def test_gap_threshold_is_the_documented_one(self):
        """Pin the constant, so a future loosening is deliberate."""
        assert _GAP_MAX_DAYS == 365


class TestSentinelColumnResolution:
    """`{c.lower(): c for c in df.columns}` keeps only the LAST column per
    lowercased name. With both `close` (sentinel) and `Close` (clean) present,
    the sentinel column was never scanned — on a check that exists precisely
    because that corpus has casing problems."""

    def test_every_matching_column_is_scanned_not_just_the_last(self):
        n = 500
        px = [10.0] * n
        dirty = list(px)
        dirty[10] = _SENTINEL_CLOSE
        df = pd.DataFrame(
            {"close": dirty, "Open": px, "High": [p * 1.01 for p in px],
             "Low": [p * 0.99 for p in px], "Close": px,
             "Volume": [1_000_000] * n},
            index=_IDX[:n])
        score, issues = validate_ohlcv(df, "DUPCASE", "D")
        assert any("Sentinel prices" in i for i in issues), issues
        assert score <= 100.0 - _SENTINEL_DEMERITS, score


class TestIssueMessagesDoNotOverclaim:
    """An issue string asserting a cause the check cannot distinguish sends
    whoever reads it down the wrong path. "Recycled ticker" is a claim only
    the gap check can evidence."""

    def test_thin_continuous_series_is_not_called_recycled(self):
        idx = pd.to_datetime(
            [f"{y}-{m:02d}-01" for y in range(2015, 2025) for m in range(1, 13)])
        df = pd.DataFrame(
            {"Open": 10.0, "High": 10.1, "Low": 9.9, "Close": 10.0,
             "Volume": 1_000_000},
            index=idx)
        _, issues = validate_ohlcv(df, "THIN", "D")
        assert any("Sparse history" in i for i in issues), issues
        assert not any("recycled" in i.lower() for i in issues), (
            f"no gap in this series — nothing evidences recycling: {issues}")

    def test_a_real_gap_may_name_the_cause(self):
        a = pd.bdate_range("2000-01-01", "2001-12-31")
        b = pd.bdate_range("2015-01-01", "2016-12-31")
        df = pd.DataFrame(
            {"Open": 10.0, "High": 10.1, "Low": 9.9, "Close": 10.0,
             "Volume": 1_000_000},
            index=a.append(b))
        _, issues = validate_ohlcv(df, "RECYCLED", "D")
        assert any("recycled" in i.lower() for i in issues), issues
