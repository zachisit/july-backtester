"""
tests/test_data_prep.py

Unit tests for S3 (minimum bars filter) and S4 (feature engineering) in main.py.

Strategy: the data-prep loop lives inside main() and is not easily extracted,
so we replicate the exact logic verbatim in thin helpers and drive those with
controlled DataFrames.  This keeps tests fast and deterministic without
spawning processes or touching the real config.

S3 tests: verify that symbols with too few bars end up in skipped_symbols and
are excluded from portfolio_data.

S4 tests: provide a known OHLCV DataFrame and verify that the four derived
columns (RSI_14, ATR_14_pct, SMA200_dist_pct, Volume_Spike) are present,
correctly calculated on the final rows, and computed without look-ahead bias.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Thin replications of the main.py data-prep loop logic
# ---------------------------------------------------------------------------

MIN_BARS_DEFAULT = 250


def _run_s3_filter(symbol: str, df, min_bars: int = MIN_BARS_DEFAULT):
    """
    Replicate the S3 min-bars filter block from main.py.
    Returns (skipped_symbols, portfolio_data).
    """
    skipped_symbols = []
    portfolio_data = {}

    if df is not None and not df.empty:
        if len(df) < min_bars:
            skipped_symbols.append((symbol, len(df)))
        else:
            portfolio_data[symbol] = df

    return skipped_symbols, portfolio_data


def _apply_feature_engineering(df: pd.DataFrame) -> pd.DataFrame:
    """
    Replicate the S4 feature-engineering block from main.py verbatim.
    Operates on a copy of df and returns the enriched copy.
    """
    df = df.copy()

    # RSI (14-period) — identical to main.py
    _delta = df['Close'].diff()
    _gain = _delta.where(_delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
    _loss = (-_delta.where(_delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    df['RSI_14'] = 100 - (100 / (1 + (_gain / _loss)))

    # ATR (14-period) as % of close — identical to main.py
    _hl = df['High'] - df['Low']
    _hc = (df['High'] - df['Close'].shift()).abs()
    _lc = (df['Low'] - df['Close'].shift()).abs()
    _atr = pd.concat([_hl, _hc, _lc], axis=1).max(axis=1)
    df['ATR_14'] = _atr.ewm(alpha=1/14, adjust=False).mean()
    df['ATR_14_pct'] = df['ATR_14'] / df['Close']

    # 200-day SMA distance — identical to main.py
    df['SMA200_dist_pct'] = (
        (df['Close'] - df['Close'].rolling(200).mean())
        / df['Close'].rolling(200).mean()
    )

    # Volume spike — identical to main.py
    df['Volume_Spike'] = df['Volume'] / df['Volume'].rolling(20).mean()

    return df


# ---------------------------------------------------------------------------
# OHLCV fixture builders
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int, base_price: float = 100.0, seed: int = 42) -> pd.DataFrame:
    """
    Build a synthetic OHLCV DataFrame with n rows of daily data.
    Prices follow a small random walk so indicators are non-trivial.
    """
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2015-01-01", periods=n, freq="B")
    close = base_price + np.cumsum(rng.normal(0, 0.5, n))
    close = np.maximum(close, 1.0)        # keep positive
    high  = close + rng.uniform(0.1, 1.0, n)
    low   = close - rng.uniform(0.1, 1.0, n)
    low   = np.maximum(low, 0.01)
    open_ = close + rng.normal(0, 0.3, n)
    volume = rng.integers(1_000_000, 5_000_000, n).astype(float)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": volume},
        index=dates,
    )


# ---------------------------------------------------------------------------
# S3 — Minimum Bars Filter
# ---------------------------------------------------------------------------

class TestS3MinBarsFilter:
    """S3: symbols with fewer than min_bars_required rows must be skipped."""

    def test_short_df_added_to_skipped_symbols(self):
        df = _make_ohlcv(100)
        skipped, _ = _run_s3_filter("AAPL", df, min_bars=250)
        assert len(skipped) == 1
        assert skipped[0][0] == "AAPL"

    def test_short_df_records_actual_bar_count(self):
        df = _make_ohlcv(100)
        skipped, _ = _run_s3_filter("MSFT", df, min_bars=250)
        assert skipped[0][1] == 100

    def test_short_df_not_added_to_portfolio_data(self):
        df = _make_ohlcv(100)
        _, portfolio_data = _run_s3_filter("TSLA", df, min_bars=250)
        assert "TSLA" not in portfolio_data

    def test_sufficient_df_not_in_skipped_symbols(self):
        df = _make_ohlcv(300)
        skipped, _ = _run_s3_filter("NVDA", df, min_bars=250)
        assert len(skipped) == 0

    def test_sufficient_df_added_to_portfolio_data(self):
        df = _make_ohlcv(300)
        _, portfolio_data = _run_s3_filter("NVDA", df, min_bars=250)
        assert "NVDA" in portfolio_data

    def test_exactly_min_bars_passes(self):
        """Boundary: exactly min_bars rows must pass (the check is `< min_bars`)."""
        df = _make_ohlcv(250)
        skipped, portfolio_data = _run_s3_filter("SPY", df, min_bars=250)
        assert len(skipped) == 0
        assert "SPY" in portfolio_data

    def test_one_below_min_bars_skipped(self):
        df = _make_ohlcv(249)
        skipped, portfolio_data = _run_s3_filter("SPY", df, min_bars=250)
        assert len(skipped) == 1
        assert "SPY" not in portfolio_data

    def test_none_df_produces_empty_outputs(self):
        """None returned by data_fetcher must not crash the filter."""
        skipped, portfolio_data = _run_s3_filter("XYZ", None, min_bars=250)
        assert skipped == []
        assert portfolio_data == {}

    def test_custom_min_bars_respected(self):
        """min_bars_required is read from CONFIG — verify custom values work."""
        df = _make_ohlcv(150)
        skipped_strict, _ = _run_s3_filter("A", df, min_bars=200)
        skipped_lenient, _ = _run_s3_filter("A", df, min_bars=100)
        assert len(skipped_strict) == 1
        assert len(skipped_lenient) == 0


# ---------------------------------------------------------------------------
# S4 — Feature Engineering: column presence
# ---------------------------------------------------------------------------

class TestS4ColumnsAdded:
    """S4: all four feature columns must exist after enrichment."""

    FEATURE_COLS = ["RSI_14", "ATR_14_pct", "SMA200_dist_pct", "Volume_Spike"]

    def test_rsi_14_column_added(self):
        df = _apply_feature_engineering(_make_ohlcv(300))
        assert "RSI_14" in df.columns

    def test_atr_14_pct_column_added(self):
        df = _apply_feature_engineering(_make_ohlcv(300))
        assert "ATR_14_pct" in df.columns

    def test_sma200_dist_pct_column_added(self):
        df = _apply_feature_engineering(_make_ohlcv(300))
        assert "SMA200_dist_pct" in df.columns

    def test_volume_spike_column_added(self):
        df = _apply_feature_engineering(_make_ohlcv(300))
        assert "Volume_Spike" in df.columns

    def test_original_ohlcv_columns_preserved(self):
        raw = _make_ohlcv(300)
        df = _apply_feature_engineering(raw)
        for col in ("Open", "High", "Low", "Close", "Volume"):
            assert col in df.columns


# ---------------------------------------------------------------------------
# S4 — Feature Engineering: value correctness
# ---------------------------------------------------------------------------

class TestS4CalculationCorrectness:
    """S4: indicator values on the final rows must be within expected ranges."""

    def setup_method(self):
        self.df = _apply_feature_engineering(_make_ohlcv(400))

    def test_rsi_14_bounded_0_to_100(self):
        valid = self.df["RSI_14"].dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_atr_14_pct_positive(self):
        valid = self.df["ATR_14_pct"].dropna()
        assert (valid > 0).all()

    def test_atr_14_pct_reasonable_magnitude(self):
        """For typical daily bar data, ATR% should be well below 100%."""
        valid = self.df["ATR_14_pct"].dropna()
        assert (valid < 1.0).all()

    def test_volume_spike_positive(self):
        valid = self.df["Volume_Spike"].dropna()
        assert (valid > 0).all()

    def test_volume_spike_equals_volume_over_20day_mean(self):
        """Spot-check: Volume_Spike == Volume / rolling(20).mean() on any non-NaN row."""
        row_idx = self.df["Volume_Spike"].dropna().index[0]
        i = self.df.index.get_loc(row_idx)
        expected = (
            self.df["Volume"].iloc[i]
            / self.df["Volume"].iloc[max(0, i - 19): i + 1].mean()
        )
        assert abs(self.df["Volume_Spike"].iloc[i] - expected) < 1e-9

    def test_sma200_dist_pct_is_zero_when_price_equals_sma(self):
        """If Close == 200-day SMA exactly, dist_pct == 0."""
        # Build a flat price series so Close always equals its own rolling mean.
        flat_df = pd.DataFrame(
            {
                "Open": [50.0] * 250,
                "High": [51.0] * 250,
                "Low": [49.0] * 250,
                "Close": [50.0] * 250,
                "Volume": [1_000_000.0] * 250,
            },
            index=pd.date_range("2015-01-01", periods=250, freq="B"),
        )
        df = _apply_feature_engineering(flat_df)
        non_nan = df["SMA200_dist_pct"].dropna()
        assert (non_nan.abs() < 1e-10).all()


# ---------------------------------------------------------------------------
# S4 — No Look-Ahead Bias
# ---------------------------------------------------------------------------

class TestS4NoLookAheadBias:
    """
    S4: indicators at bar T must not depend on data from bar T+1 onwards.

    Method: compute indicators on the full series, then chop the series at
    a cut-point and recompute.  The value at the cut-point must match.
    If a future bar leaked in, the values would differ.
    """

    CUT = 350   # compare values at this bar index

    def _compute_at_cut(self, cut: int):
        """
        Generate ONE 400-bar dataset then compute indicators on the full series
        and on a slice ending at `cut`.  Using the same underlying OHLCV data
        ensures EWM/rolling state is identical and avoids the RNG-state mismatch
        that occurs when _make_ohlcv(400) and _make_ohlcv(351) are called
        independently (H/L/V columns differ because the RNG is consumed in
        batches of n).
        """
        full_df = _make_ohlcv(400)
        row_full = _apply_feature_engineering(full_df.copy()).iloc[cut]
        row_cut  = _apply_feature_engineering(full_df.iloc[:cut + 1].copy()).iloc[cut]
        return row_full, row_cut

    def test_rsi_14_no_lookahead(self):
        row_full, row_cut = self._compute_at_cut(self.CUT)
        assert abs(row_full["RSI_14"] - row_cut["RSI_14"]) < 1e-9

    def test_atr_14_pct_no_lookahead(self):
        row_full, row_cut = self._compute_at_cut(self.CUT)
        assert abs(row_full["ATR_14_pct"] - row_cut["ATR_14_pct"]) < 1e-9

    def test_volume_spike_no_lookahead(self):
        row_full, row_cut = self._compute_at_cut(self.CUT)
        assert abs(row_full["Volume_Spike"] - row_cut["Volume_Spike"]) < 1e-9

    def test_sma200_dist_pct_no_lookahead(self):
        row_full, row_cut = self._compute_at_cut(self.CUT)
        # Both may be NaN if CUT < 200; use equal-or-both-NaN comparison
        if pd.isna(row_full["SMA200_dist_pct"]):
            assert pd.isna(row_cut["SMA200_dist_pct"])
        else:
            assert abs(row_full["SMA200_dist_pct"] - row_cut["SMA200_dist_pct"]) < 1e-9
