"""
Tests for custom_strategies/*.py — verifies that each registered strategy
function can be called with synthetic OHLCV data and produces a valid output.

Design principle: test behavior (does the function return a DataFrame with
a valid Signal column?), not implementation details.  We load every strategy
from the registry and call it with 300 bars of synthetic trending data so
that the strategy has enough history to compute its longest indicator (200d SMA).

Dependencies (spy_df, vix_df) are injected as synthetic DataFrames matching
the same date range, exactly as main.py would do in production.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.registry import load_strategies, REGISTRY


# ---------------------------------------------------------------------------
# Synthetic OHLCV helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(n=300, start_price=100.0, trend=0.0005, start="2020-01-01",
                volume=1_000_000):
    """Build a realistic uptrending OHLCV DataFrame with n bars."""
    dates = pd.bdate_range(start=start, periods=n)
    closes = [start_price * (1 + trend) ** i for i in range(n)]
    df = pd.DataFrame({
        "Open":   [c * 0.999 for c in closes],
        "High":   [c * 1.01 for c in closes],
        "Low":    [c * 0.99 for c in closes],
        "Close":  closes,
        "Volume": [volume] * n,
    }, index=dates)
    df.index.name = "Datetime"
    return df


def _make_vix(n=300, level=20.0, start="2020-01-01"):
    """Build a synthetic VIX DataFrame at a constant calm level."""
    dates = pd.bdate_range(start=start, periods=n)
    df = pd.DataFrame({
        "Open": [level] * n, "High": [level + 1] * n,
        "Low": [level - 1] * n, "Close": [level] * n,
        "Volume": [0] * n,
    }, index=dates)
    df.index.name = "Datetime"
    return df


# ---------------------------------------------------------------------------
# Load all daily-timeframe strategies once at module level
# ---------------------------------------------------------------------------

load_strategies("custom_strategies")

_OHLCV = _make_ohlcv(n=300)
_SPY   = _make_ohlcv(n=300, start_price=400.0, trend=0.0003)
_VIX   = _make_vix(n=300)


def _call_strategy(name: str) -> pd.DataFrame:
    """Call a registered strategy with synthetic data and return the result."""
    entry = REGISTRY[name]
    fn     = entry["logic"]
    params = entry["params"].copy()
    deps   = entry["dependencies"]

    kwargs = dict(params)
    if "spy" in deps:
        kwargs["spy_df"] = _SPY.copy()
    if "vix" in deps:
        kwargs["vix_df"] = _VIX.copy()

    return fn(_OHLCV.copy(), **kwargs)


# ---------------------------------------------------------------------------
# Helper — build param IDs for pytest so failures show the strategy name
# ---------------------------------------------------------------------------

def _daily_strategy_names():
    """Return names of all strategies that should work on daily data."""
    load_strategies("custom_strategies")
    # Exclude sub-daily (MIN) strategies — they require timeframe=MIN config
    # and are not registered under the default daily config.
    return [
        n for n in REGISTRY.keys()
        if "1m" not in n and "Scalp" not in n.lower()
    ]


DAILY_STRATEGIES = _daily_strategy_names()


# ---------------------------------------------------------------------------
# Parametrized: every daily strategy must produce a valid output
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("strategy_name", DAILY_STRATEGIES)
class TestCustomStrategyExecution:

    def test_returns_dataframe(self, strategy_name):
        result = _call_strategy(strategy_name)
        assert isinstance(result, pd.DataFrame), (
            f"Strategy '{strategy_name}' did not return a DataFrame"
        )

    def test_signal_column_present(self, strategy_name):
        result = _call_strategy(strategy_name)
        assert "Signal" in result.columns, (
            f"Strategy '{strategy_name}' missing 'Signal' column"
        )

    def test_signal_values_valid(self, strategy_name):
        """Signal values must be in {-1, 0, 1}."""
        result = _call_strategy(strategy_name)
        signals = result["Signal"].dropna().unique()
        invalid = [s for s in signals if s not in {-1, 0, 1}]
        assert not invalid, (
            f"Strategy '{strategy_name}' produced invalid signals: {invalid}"
        )

    def test_output_same_length_as_input(self, strategy_name):
        result = _call_strategy(strategy_name)
        assert len(result) == len(_OHLCV), (
            f"Strategy '{strategy_name}' changed DataFrame length"
        )
