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
    _SENTINEL_CLOSE,
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
