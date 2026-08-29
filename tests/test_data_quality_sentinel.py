"""tests/test_data_quality_sentinel.py

Issue #350: the merged corpus carries closes of EXACTLY 1e-06 sitting next to
normal bars, and stitched/recycled tickers wearing one symbol.

The sentinel is a fabricated round-trip — collapse to the floor, bounce back on
the next bar — measured on the shipped corpus (35,309 files / 74,866,808 bars)
at 25,730 bars across 813 series.

CORRECTED. An earlier version of this docstring said these were "not sub-penny
stocks: FMNJ, NEOM and RINO have median closes of $10.00, $8.70 and $8.50".
Those are medians over the WHOLE FILE. Over the bars that actually print 1e-06
the medians are $0.0005 / $0.0001 / $0.0001. 1e-06 is the bottom of Norgate's
fixed absolute tick grid, so these bars are REAL PRICES and this is a
TRADEABILITY screen, not a corruption screen — a bar on the floor cannot be
traded at its printed size, yet still manufactures a round-trip a mean-reversion
strategy will take. See helpers/data_quality.py CHECK 7 for the measurement.

The "**92/100 and passed**" figure is likewise not reproducible: scored at base,
the 813 affected series run min 50 / median 67 / max 84. What IS true is that
115 of them (14.1%) scored >= 80 and passed the default gate — which is why this
check is flat rather than proportional: ONE sentinel bar is a fake round-trip.
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
        """A genuine sub-penny series must NOT be flagged for smallness.

        The fixture is a real Norgate tick grid one decade ABOVE the floor. The
        earlier version used 0.0004 — four hundred times the sentinel, and two
        whole decades of grid away — so it could not fail for the reason its
        docstring claimed: it passed whether or not the check keyed on the exact
        value. A control whose fixture cannot fail is not a control.
        """
        grid = [1e-05 + (i % 4) * 1e-05 for i in range(500)]   # 1e-05..4e-05
        score, issues = validate_ohlcv(_frame(grid), "PENNY", "D")
        assert not any("Sentinel prices" in i for i in issues), issues

    def test_an_honest_series_touching_the_floor_is_flagged(self):
        """The accepted FALSE POSITIVE, pinned so it cannot be forgotten.

        1e-06 is the bottom of Norgate's absolute tick grid, so an honest
        sub-penny series that trades down to it takes the full demerit on real
        data. That is the cost of keying on the value instead of the shape; the
        narrower fix is a dollar-volume floor at selection. Pinned rather than
        fixed so the trade-off stays visible to whoever revisits CHECK 7.
        """
        grid = [_SENTINEL_CLOSE if i % 7 == 0 else 1e-05 + (i % 3) * 1e-05
                for i in range(500)]
        score, issues = validate_ohlcv(_frame(grid), "HMNY", "D")
        assert any("Sentinel prices" in i for i in issues), issues
        assert score <= 100.0 - _SENTINEL_DEMERITS, (score, issues)

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


class TestEveryCheckReachesALowercaseFrame:
    """CHECKS 2-5 indexed literal capitalised labels, so against the merged
    store's LOWERCASE ohlcv — the corpus #350 is about — they silently no-opped.
    CHECK 7 fixed this for itself only.
    """

    @staticmethod
    def _defective(n=100):
        closes = _clean(n)
        closes[50] = closes[49] * 5                  # a 400% jump for CHECK 4
        df = _frame(closes)
        hi = df.columns.get_loc("High")
        lo = df.columns.get_loc("Low")
        df.iloc[10, hi] = df.iloc[10, lo] - 1.0      # High < Low for CHECK 3
        df.iloc[:30, df.columns.get_loc("Volume")] = 0   # zero vol for CHECK 5
        return df

    def test_lowercase_frame_scores_the_same_as_capitalised(self):
        cap = self._defective()
        low = cap.rename(columns=str.lower)
        s_cap, i_cap = validate_ohlcv(cap, "CAP", "D")
        s_low, i_low = validate_ohlcv(low, "LOW", "D")
        assert s_low == s_cap, (s_cap, i_cap, s_low, i_low)
        assert s_low < 100.0, (s_low, i_low)

    def test_lowercase_frame_reports_the_same_issues(self):
        low = self._defective().rename(columns=str.lower)
        _, issues = validate_ohlcv(low, "LOW", "D")
        assert any("High < Low" in i for i in issues), issues
        assert any("Price jumps" in i for i in issues), issues
        assert any("Zero volume" in i for i in issues), issues

    def test_rename_does_not_mutate_the_callers_frame(self):
        low = _frame(_clean(50)).rename(columns=str.lower)
        before = list(low.columns)
        validate_ohlcv(low, "LOW", "D")
        assert list(low.columns) == before

    def test_a_frame_carrying_both_cases_keeps_todays_behaviour(self):
        """Ambiguous input must not silently swap which column is read."""
        df = _frame(_clean(50))
        df["close"] = [_SENTINEL_CLOSE] * 50
        score, issues = validate_ohlcv(df, "MIXED", "D")
        assert any("Sentinel prices" in i for i in issues), issues


class TestGapWordingIsGatedOnDensity:
    """CHECK 9 named a cause it cannot distinguish. CHECK 8 already refuses to."""

    @staticmethod
    def _holed(left_n, left_start, right_n, right_start):
        idx = pd.bdate_range(left_start, periods=left_n).append(
            pd.bdate_range(right_start, periods=right_n))
        return _frame(_clean(len(idx)), index=idx)

    def test_a_dense_series_with_a_hole_is_not_called_recycled(self):
        """NBIS: $1.44bn/day, a multi-year hole across the Yandex suspension and
        the Nebius relisting. Correct detection, wrong accusation — it was
        demoted 82 -> 57 at every window."""
        df = self._holed(1500, "2015-01-01", 400, "2024-01-01")
        _, issues = validate_ohlcv(df, "NBIS", "D")
        gap = [i for i in issues if "History gap" in i]
        assert gap, issues
        assert not any("Sparse history" in i for i in issues), issues
        assert "recycled" not in gap[0], gap
        assert "dense series" in gap[0], gap

    def test_a_sparse_series_with_a_hole_still_says_recycled(self):
        """SSCC/FER: thin AND holed. Both fire, so the claim is evidenced."""
        df = self._holed(300, "2000-01-01", 300, "2020-01-01")
        _, issues = validate_ohlcv(df, "SSCC", "D")
        gap = [i for i in issues if "History gap" in i]
        assert gap, issues
        assert any("Sparse history" in i for i in issues), issues
        assert "stitched or recycled ticker" in gap[0], gap

    def test_the_gap_is_still_scored_either_way(self):
        dense = self._holed(1500, "2015-01-01", 400, "2024-01-01")
        clean = _frame(_clean(1900),
                       index=pd.bdate_range("2015-01-01", periods=1900))
        s_gap, _ = validate_ohlcv(dense, "NBIS", "D")
        s_ok, _ = validate_ohlcv(clean, "DENSE", "D")
        assert s_ok - s_gap >= _GAP_DEMERITS
