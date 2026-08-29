"""tests/test_data_quality_sentinel.py

Issue #350: the merged corpus carries closes of EXACTLY 1e-06, and stitched or
recycled tickers wearing one symbol.

25,730 bars across 813 series. `1e-06` is the bottom of the provider's fixed
absolute tick grid, NOT an injected sentinel — 99.34% of closes in that decade
sit exactly on it against 0.26% at $100, one bar in 74.9M is below it, and none
of the affected bars have zero volume.

Two claims that were made on #350 and then retracted there are deliberately NOT
repeated here, because a comment outlives the correction:

* "They are not sub-penny stocks." They are. The $10.00/$8.70/$8.50 medians
  quoted for FMNJ/NEOM/RINO are whole-file, over 29-36 years; over the years
  the 1e-06 prints occur they are $0.0005/$0.0001/$0.0001, and 639 of the 813
  affected series are under a cent in that era.
* "An affected series scored 92/100 and passed." Not on this corpus — the 813
  score min 50 / median 67 / max 84 at base.

What earns the check its place is narrower and survives both: a close of 1e-06
against a neighbour at 1e-04 is a true -99% followed by a true +9,900%, and
returns/ATR/vol/sizing computed off it are garbage whether or not the quote is
honest. Tradeability, not truthfulness.
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

    def test_a_single_floor_bar_demotes_the_series(self):
        """ONE bar, because the damage saturates at one bar: a single floor
        print in an otherwise-clean series manufactures a ~+2e8% one-bar
        return, which wrecks a Sharpe/vol/MC over that window as thoroughly as
        644 of them would. Proportional scoring is what let 115 of the 813
        affected corpus series score >= 80 at base and pass the gate — and
        main.py prints only sub-threshold rows, so their existing CHECK 4
        issue string was never displayed."""
        closes = _clean()
        closes[250] = _SENTINEL_CLOSE
        score, issues = validate_ohlcv(_frame(closes), "FMNJ", "D")
        assert any("Tick-floor prices" in i for i in issues), issues
        assert score < 80.0, (
            f"scored {score} — high enough to pass a quality gate, which is "
            f"exactly how #350 went unnoticed")

    def test_sentinel_is_reported_with_its_count(self):
        closes = _clean()
        for i in (100, 200, 300):
            closes[i] = _SENTINEL_CLOSE
        _, issues = validate_ohlcv(_frame(closes), "NEOM", "D")
        hit = [i for i in issues if "Tick-floor prices" in i]
        assert hit and "3 bars" in hit[0], issues

    def test_prices_above_the_floor_are_not_flagged(self):
        """0.0004 is 400x the floor, so this fixture never visits the bottom
        tick. It pins "the check keys on one value, not on smallness" — which
        is all it can pin. It was previously titled as a sub-penny control and
        asserted that a genuine sub-penny stock is NOT flagged; the fixture
        could not fail for that reason, and the claim was false. See
        test_a_sub_penny_series_on_the_tick_grid_IS_flagged for what actually
        happens."""
        score, issues = validate_ohlcv(
            _frame([0.0004 + (i % 3) * 0.00001 for i in range(500)]),
            "PENNY", "D")
        assert not any("Tick-floor prices" in i for i in issues), issues

    def test_a_sub_penny_series_on_the_tick_grid_IS_flagged(self):
        """The honest version of the control above.

        `1e-06` is the bottom of the provider's fixed absolute tick grid, not
        an injected value, so a stock that walks down onto the floor prints it
        legitimately — HMNY prints it on 61/61 bars in 2026, on real volume.
        This check flags that series. That is a deliberate choice (a shell
        sitting on the tick floor is not something to backtest), but it must be
        asserted rather than denied."""
        grid = [1e-06, 2e-06, 3e-06, 5e-06, 1e-05, 2e-05]
        closes = [grid[i % len(grid)] for i in range(500)]
        score, issues = validate_ohlcv(_frame(closes), "HMNY", "D")
        assert any("Tick-floor prices" in i for i in issues), issues
        assert score < 80.0, score

    def test_near_miss_values_are_not_flagged(self):
        closes = _clean()
        closes[250] = 1e-05          # an order of magnitude away
        _, issues = validate_ohlcv(_frame(closes), "NEAR", "D")
        assert not any("Tick-floor prices" in i for i in issues), issues

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
        assert not any("Tick-floor prices" in i for i in issues), issues


    def test_sentinel_on_low_is_caught(self):
        """The shape that actually TRADES.

        Every daily-bar stop in this engine fills off `Low`, so a wick to the
        tick floor is worse than a close at it — and a Close-only scan scored
        exactly this bar 100/100 with zero issues.
        """
        closes = _clean()
        lows = [c * 0.99 for c in closes]
        lows[250] = _SENTINEL_CLOSE
        df = _frame(closes)
        df["Low"] = lows
        score, issues = validate_ohlcv(df, "WICK", "D")
        assert any("Tick-floor prices" in i for i in issues), issues
        assert score < 80.0

    def test_sentinel_in_a_lowercase_close_column_is_caught(self):
        """The merged store writes LOWERCASE ohlcv — the corpus this check
        exists for. Looking only for "Close" made a raw audit of it a no-op."""
        closes = _clean()
        closes[250] = _SENTINEL_CLOSE
        df = _frame(closes)
        df.columns = [c.lower() for c in df.columns]
        score, issues = validate_ohlcv(df, "LOWER", "D")
        assert any("Tick-floor prices" in i for i in issues), issues
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
        hit = [i for i in issues if "Tick-floor prices" in i]
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
        assert any("Tick-floor prices" in i for i in issues), issues


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

    def test_a_dense_series_with_a_hole_is_reported_but_not_demoted(self):
        """7 dense years, a 5-year hole, 8 dense years — 196 bars/yr on both
        sides of the hole.

        This shape is a corporate event, not a stitch: NBIS (Yandex suspended
        Feb 2022, relisted as Nebius Oct 2024) is 207 bars/yr and trades
        $1.4bn/day; OLED and RDNT are the same shape. Charging them the full
        gap demerit crossed the 80 gate on all three. The gap is real and worth
        reporting; the accusation and the demotion are not earned when the
        series is dense on both sides."""
        df = self._two_eras("2005-01-03", 252 * 7, "2017-01-02", 252 * 8)
        score, issues = validate_ohlcv(df, "NBIS", "D")
        assert any("History gap" in i for i in issues), issues
        assert not any("recycled" in i.lower() for i in issues), issues
        assert score >= 80.0, (
            f"scored {score} — a dense series with a real corporate gap must "
            f"not be demoted below the gate")

    def test_a_sparse_series_with_a_hole_is_demoted(self):
        """The shape the demerit is FOR: sparse on both sides of the hole, the
        SSCC/FER wrong-file signature."""
        a = pd.bdate_range("2000-01-01", "2001-12-31")
        b = pd.bdate_range("2015-01-01", "2016-12-31")
        df = pd.DataFrame(
            {"Open": 10.0, "High": 10.1, "Low": 9.9, "Close": 10.0,
             "Volume": 1_000_000},
            index=a.append(b))
        score, issues = validate_ohlcv(df, "SSCC", "D")
        assert any("History gap" in i for i in issues), issues
        assert any("recycled" in i.lower() for i in issues), issues
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

    def test_gap_actually_costs_score_on_a_sparse_series(self):
        """Without this, setting the demerits to 0 survives mutation. Measured
        on the sparse shape, since the dense shape is deliberately free."""
        a = pd.bdate_range("2000-01-01", "2001-12-31")
        b = pd.bdate_range("2015-01-01", "2016-12-31")
        df = pd.DataFrame(
            {"Open": 10.0, "High": 10.1, "Low": 9.9, "Close": 10.0,
             "Volume": 1_000_000},
            index=a.append(b))
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
        assert any("Tick-floor prices" in i for i in issues), issues
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

    def test_a_dense_series_with_a_gap_is_not_called_recycled(self):
        """The mirror case. A hole alone is not evidence of a stitch — the
        sparse density is. NBIS is dense on both sides of a real suspension."""
        a = pd.bdate_range("2005-01-03", periods=252 * 7)
        b = pd.bdate_range("2017-01-02", periods=252 * 8)
        df = pd.DataFrame(
            {"Open": 10.0, "High": 10.1, "Low": 9.9, "Close": 10.0,
             "Volume": 1_000_000},
            index=a.append(b))
        _, issues = validate_ohlcv(df, "NBIS", "D")
        assert any("History gap" in i for i in issues), issues
        assert not any("recycled" in i.lower() for i in issues), issues


class TestColumnNameCaseInsensitivity:
    """The merged store writes lowercase `ohlcv`. CHECK 7 was made
    case-insensitive for exactly that reason — but CHECKS 2-5 still matched
    "Close"/"Open"/"High"/"Low"/"Volume" literally, so against the corpus this
    module exists to audit they did not fail loudly, they skipped. A frame with
    a High<Low violation, a 400% jump and 30 zero-volume bars scored 100/100.
    """

    @staticmethod
    def _broken(lower=False):
        n = 300
        px = [10.0] * n
        high = [10.1] * n
        low = [9.9] * n
        close = list(px)
        vol = [1_000_000.0] * n
        high[5], low[5] = 9.0, 10.5          # High < Low
        close[20] = 50.0                     # 400% jump
        for i in range(100, 130):
            vol[i] = 0.0                     # zero volume
        cols = {"Open": px, "High": high, "Low": low, "Close": close,
                "Volume": vol}
        if lower:
            cols = {k.lower(): v for k, v in cols.items()}
        return pd.DataFrame(cols, index=_IDX[:n])

    def test_lowercase_columns_score_the_same_as_capitalised(self):
        upper_score, upper_issues = validate_ohlcv(self._broken(), "UP", "D")
        lower_score, lower_issues = validate_ohlcv(
            self._broken(lower=True), "LOW", "D")
        assert upper_score < 100.0, "fixture is not actually broken"
        assert lower_score == upper_score, (
            f"capitalised {upper_score} vs lowercase {lower_score} — column "
            f"casing must not change the verdict")
        assert len(lower_issues) == len(upper_issues), (
            f"{lower_issues} vs {upper_issues}")

    def test_lowercase_ohlc_violation_is_caught(self):
        _, issues = validate_ohlcv(self._broken(lower=True), "LOW", "D")
        assert any("High < Low" in i for i in issues), issues

    def test_lowercase_price_jump_is_caught(self):
        _, issues = validate_ohlcv(self._broken(lower=True), "LOW", "D")
        assert any("Price jumps" in i for i in issues), issues

    def test_lowercase_zero_volume_is_caught(self):
        _, issues = validate_ohlcv(self._broken(lower=True), "LOW", "D")
        assert any("Zero volume" in i for i in issues), issues

    def test_lowercase_negative_prices_are_caught(self):
        n = 300
        df = pd.DataFrame(
            {"open": [10.0] * n, "high": [10.1] * n,
             "low": [-1.0] + [9.9] * (n - 1), "close": [10.0] * n,
             "volume": [1_000_000.0] * n},
            index=_IDX[:n])
        _, issues = validate_ohlcv(df, "NEG", "D")
        assert any("Negative" in i for i in issues), issues

    def test_uppercase_columns_also_work(self):
        n = 300
        df = pd.DataFrame(
            {"OPEN": [10.0] * n, "HIGH": [9.0] * n,
             "LOW": [10.5] * n, "CLOSE": [10.0] * n,
             "VOLUME": [1_000_000.0] * n},
            index=_IDX[:n])
        _, issues = validate_ohlcv(df, "SHOUT", "D")
        assert any("High < Low" in i for i in issues), issues
