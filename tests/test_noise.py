"""
tests/test_noise.py

Unit tests for helpers/noise.py — inject_price_noise.

Covers:
  - Zero / negative noise_pct returns unchanged dataframe
  - OHLC values are modified when noise_pct > 0
  - Volume and index are never touched
  - High == row-wise max(O, H, L, C) after injection
  - Low  == row-wise min(O, H, L, C) after injection
  - High >= Low for every row (valid candlestick guarantee)
  - Deterministic output when NumPy seed is fixed
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import CONFIG
from helpers.noise import inject_price_noise, generate_noise_chart_from_csv


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(n: int = 50) -> pd.DataFrame:
    """Return a minimal OHLCV DataFrame with a DatetimeIndex."""
    rng = pd.date_range("2020-01-01", periods=n, freq="B")
    closes = np.linspace(100.0, 150.0, n)
    return pd.DataFrame(
        {
            "Open":   closes * 0.99,
            "High":   closes * 1.01,
            "Low":    closes * 0.98,
            "Close":  closes,
            "Volume": [1_000_000] * n,
        },
        index=rng,
    )


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------

class TestConfigDefaults:

    def test_noise_injection_pct_default_is_zero(self):
        """noise_injection_pct must default to 0.0 so stress testing is opt-in."""
        assert CONFIG["noise_injection_pct"] == 0.0

    def test_zero_noise_config_returns_identical_df(self):
        """inject_price_noise with the default config value returns the same object unchanged."""
        df = _make_df()
        result = inject_price_noise(df, CONFIG["noise_injection_pct"])
        assert result is df
        pd.testing.assert_frame_equal(result, df)


# ---------------------------------------------------------------------------
# No-op cases
# ---------------------------------------------------------------------------

class TestNoopCases:

    def test_zero_noise_returns_identical_df(self):
        df = _make_df()
        result = inject_price_noise(df, 0.0)
        pd.testing.assert_frame_equal(result, df)

    def test_negative_noise_returns_identical_df(self):
        df = _make_df()
        result = inject_price_noise(df, -0.05)
        pd.testing.assert_frame_equal(result, df)

    def test_zero_noise_is_same_object(self):
        """No copy is made when noise is disabled."""
        df = _make_df()
        result = inject_price_noise(df, 0.0)
        assert result is df


# ---------------------------------------------------------------------------
# Mutation checks
# ---------------------------------------------------------------------------

class TestMutationChecks:

    def test_ohlc_values_changed(self):
        df = _make_df()
        np.random.seed(42)
        result = inject_price_noise(df, 0.05)
        # At least one OHLC value must differ
        changed = (
            (result["Open"] != df["Open"]).any()
            or (result["High"] != df["High"]).any()
            or (result["Low"] != df["Low"]).any()
            or (result["Close"] != df["Close"]).any()
        )
        assert changed

    def test_volume_unchanged(self):
        df = _make_df()
        np.random.seed(42)
        result = inject_price_noise(df, 0.05)
        pd.testing.assert_series_equal(result["Volume"], df["Volume"])

    def test_index_unchanged(self):
        df = _make_df()
        np.random.seed(42)
        result = inject_price_noise(df, 0.05)
        pd.testing.assert_index_equal(result.index, df.index)

    def test_original_df_not_mutated(self):
        df = _make_df()
        original_close = df["Close"].copy()
        np.random.seed(42)
        inject_price_noise(df, 0.05)
        pd.testing.assert_series_equal(df["Close"], original_close)


# ---------------------------------------------------------------------------
# Candlestick validity guarantees
# ---------------------------------------------------------------------------

class TestCandlestickValidity:

    def test_high_is_max_of_ohlc_per_row(self):
        df = _make_df()
        np.random.seed(0)
        result = inject_price_noise(df, 0.05)
        expected_high = result[["Open", "High", "Low", "Close"]].max(axis=1)
        pd.testing.assert_series_equal(result["High"], expected_high, check_names=False)

    def test_low_is_min_of_ohlc_per_row(self):
        df = _make_df()
        np.random.seed(0)
        result = inject_price_noise(df, 0.05)
        expected_low = result[["Open", "High", "Low", "Close"]].min(axis=1)
        pd.testing.assert_series_equal(result["Low"], expected_low, check_names=False)

    def test_high_gte_low_always(self):
        df = _make_df()
        np.random.seed(1)
        result = inject_price_noise(df, 0.10)
        assert (result["High"] >= result["Low"]).all()

    def test_validity_holds_with_large_noise(self):
        """Even at 50% noise every candlestick must remain valid."""
        df = _make_df()
        np.random.seed(99)
        result = inject_price_noise(df, 0.50)
        assert (result["High"] >= result["Low"]).all()


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:

    def test_deterministic_with_seed(self):
        df = _make_df()
        np.random.seed(7)
        result_a = inject_price_noise(df, 0.03)
        np.random.seed(7)
        result_b = inject_price_noise(df, 0.03)
        pd.testing.assert_frame_equal(result_a, result_b)

    def test_different_seeds_produce_different_output(self):
        df = _make_df()
        np.random.seed(1)
        result_a = inject_price_noise(df, 0.03)
        np.random.seed(2)
        result_b = inject_price_noise(df, 0.03)
        assert not result_a["Close"].equals(result_b["Close"])


# ---------------------------------------------------------------------------
# generate_noise_chart_from_csv
# ---------------------------------------------------------------------------

class TestGenerateNoiseChartFromCsv:

    def _write_sample_csv(self, tmp_path) -> str:
        """Write a minimal noise_sample_data.csv as produced by main.py."""
        df = _make_df(30)
        np.random.seed(42)
        df_noisy = inject_price_noise(df, 0.05)

        clean = df[["Open", "High", "Low", "Close"]].copy()
        noisy = df_noisy[["Open", "High", "Low", "Close"]].copy()
        clean.columns = [f"Clean_{c}" for c in clean.columns]
        noisy.columns = [f"Noisy_{c}" for c in noisy.columns]
        combined = pd.concat([clean, noisy], axis=1)
        combined.insert(0, "Symbol", "TEST")

        csv_path = str(tmp_path / "noise_sample_data.csv")
        combined.to_csv(csv_path)
        return csv_path

    def test_creates_png_file(self, tmp_path):
        csv_path = self._write_sample_csv(tmp_path)
        img_path = str(tmp_path / "out.png")
        generate_noise_chart_from_csv(csv_path, img_path)
        assert os.path.isfile(img_path)

    def test_output_is_nonzero_size(self, tmp_path):
        csv_path = self._write_sample_csv(tmp_path)
        img_path = str(tmp_path / "out.png")
        generate_noise_chart_from_csv(csv_path, img_path)
        assert os.path.getsize(img_path) > 0

    def test_no_open_figures_after_call(self, tmp_path):
        """Function must close the figure — no memory leak."""
        import matplotlib.pyplot as plt
        csv_path = self._write_sample_csv(tmp_path)
        img_path = str(tmp_path / "out.png")
        before = len(plt.get_fignums())
        generate_noise_chart_from_csv(csv_path, img_path)
        after = len(plt.get_fignums())
        assert after == before
