"""Smoke tests for inverse-ETF support (long SH, PSQ, SDS).

The v2 autonomous loop's primary use of the engine fix is to enable long-
only positioning on inverse ETFs as a defensive sleeve (synthetic short
exposure without invoking the signal=-2 short mechanism). These tests
verify that:

  1. SH / PSQ / SDS parquet data is present and spans the blind window.
  2. A simple long-SH-when-VIX-high strategy runs end-to-end through the
     simulation engine without error.
  3. The signal convention used (1=enter, -1=exit) goes through the long
     path, not the short path — so the engine fix is irrelevant to
     correctness here (defence in depth: confirms the strategy class is
     long-only).
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


INVERSE_ETFS = ["SH", "PSQ", "SDS"]


def _load_parquet(symbol: str) -> pd.DataFrame:
    return pd.read_parquet(f"parquet_data/data/{symbol}.parquet")


class TestInverseEtfDataAvailability:
    """The blind window is 2004-01-01 → 2022-12-31. Each inverse ETF must
    cover at least most of that window (inception dates: SH/PSQ ~2006-06,
    SDS ~2007-07)."""

    @pytest.mark.parametrize("symbol", INVERSE_ETFS)
    def test_parquet_file_exists(self, symbol):
        path = f"parquet_data/data/{symbol}.parquet"
        assert os.path.exists(path), f"Inverse-ETF parquet missing: {path}"

    @pytest.mark.parametrize("symbol", INVERSE_ETFS)
    def test_coverage_spans_blind_window(self, symbol):
        df = _load_parquet(symbol)
        idx = pd.to_datetime(df.index)
        # Coverage must reach into 2022 (most of the blind window) and
        # start no later than 2008 (mid-GFC, the canonical regime stress).
        assert idx.max() >= pd.Timestamp("2022-12-31", tz=idx.tz or None), (
            f"{symbol}: data ends at {idx.max().date()}, before blind cutoff"
        )
        assert idx.min() <= pd.Timestamp("2008-01-01", tz=idx.tz or None), (
            f"{symbol}: data starts at {idx.min().date()}, misses GFC regime"
        )


class TestLongInverseEtfStrategy:
    """A long-only inverse-ETF strategy with signal 1/-1/0 must run cleanly.
    No signal=-2; the strategy class is long-only-compatible by construction."""

    def test_long_sh_strategy_runs_end_to_end(self):
        """Smoke test: long SH when synthetic VIX > 30; exit when VIX < 20."""
        from config import CONFIG
        from helpers.portfolio_simulations import run_portfolio_simulation

        # Build synthetic VIX + SH price series spanning a regime change.
        dates = pd.bdate_range(start="2010-01-04", periods=200, tz="UTC")
        # Random-ish but reproducible VIX path: oscillates 15-40
        rng = np.random.default_rng(42)
        vix_path = 22.0 + 10.0 * np.sin(np.linspace(0, 6 * np.pi, len(dates))) + rng.normal(0, 2, len(dates))
        vix_df = pd.DataFrame(
            {
                "Open": vix_path, "High": vix_path * 1.02, "Low": vix_path * 0.98,
                "Close": vix_path, "Volume": 0,
            },
            index=dates,
        )

        # Inverse relationship: SH rises when synthetic SPY (= 1/VIX proxy) falls
        sh_path = 50.0 + (vix_path - 22.0) * 0.5
        sh_df = pd.DataFrame(
            {
                "Open": sh_path, "High": sh_path * 1.005, "Low": sh_path * 0.995,
                "Close": sh_path, "Volume": 1_000_000,
            },
            index=dates,
        )

        # Long-only signals: 1 when VIX > 30, -1 when VIX < 20, 0 otherwise.
        sig = pd.Series(0, index=dates, dtype=int)
        sig[vix_df["Close"] > 30] = 1
        sig[vix_df["Close"] < 20] = -1

        result = run_portfolio_simulation(
            portfolio_data={"SH": sh_df},
            signals={"SH": sig},
            initial_capital=10_000.0,
            allocation_pct=0.5,
            spy_df=None,
            vix_df=vix_df,
            tnx_df=None,
            stop_config={"type": "none"},
        )

        # Strategy completed and produced trades; result is a dict.
        assert result is not None, (
            "Long-SH strategy returned None — engine may have failed silently"
        )
        assert "trade_log" in result
        # At least one round-trip (entry + exit) should fire on this regime.
        long_trades = [t for t in result["trade_log"] if t["Trade"].startswith("Long")]
        assert len(long_trades) >= 1, (
            f"Expected at least one long SH trade, got {len(long_trades)}. "
            f"Total trade_log entries: {len(result['trade_log'])}"
        )

    def test_long_inverse_etf_uses_long_path_not_short(self):
        """Trades from a 1/-1 signal strategy must be tagged 'Long', not
        'Short'. This is the operational invariant: inverse ETFs as long-
        only-compatible defensive sleeves avoid the short mechanism."""
        from helpers.portfolio_simulations import run_portfolio_simulation

        dates = pd.bdate_range(start="2010-01-04", periods=10, tz="UTC")
        prices = [50.0, 50.0, 55.0, 55.0, 55.0, 55.0, 50.0, 50.0, 50.0, 50.0]
        df = pd.DataFrame(
            {
                "Open": prices, "High": [p * 1.005 for p in prices],
                "Low": [p * 0.995 for p in prices], "Close": prices,
                "Volume": [1_000_000] * 10,
            },
            index=dates,
        )

        sig = pd.Series([1, 0, 0, 0, 0, 0, -1, 0, 0, 0], index=dates, dtype=int)

        result = run_portfolio_simulation(
            portfolio_data={"SH": df},
            signals={"SH": sig},
            initial_capital=10_000.0,
            allocation_pct=1.0,
            spy_df=None,
            vix_df=None,
            tnx_df=None,
            stop_config={"type": "none"},
        )

        assert result is not None
        for trade in result["trade_log"]:
            assert trade["Trade"].startswith("Long"), (
                f"Unexpected non-Long trade: {trade['Trade']!r}. "
                f"Inverse-ETF strategies must use the long path."
            )
