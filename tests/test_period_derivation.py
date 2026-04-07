# tests/test_period_derivation.py
"""
TDD tests for main._pick_reference_df() — the helper that selects a reference
DataFrame from comparison_dfs to derive the Actual Data Period.

Regression for bug: "The truth value of a DataFrame is ambiguous"

Root cause: the original inline expression
    spy_df = comparison_dfs.get("SPY") or next(iter(comparison_dfs.values()))
calls bool(DataFrame) when SPY is present and non-empty, which raises:
    ValueError: The truth value of a DataFrame is ambiguous.

Fix: replace the `or` fallback with an explicit `is None` check.
"""

import os
import sys

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from main import _pick_reference_df


def _make_df(start="2020-01-01", periods=5):
    """Small helper — returns a minimal DataFrame with a DatetimeIndex."""
    return pd.DataFrame(
        {"Close": range(periods)},
        index=pd.date_range(start, periods=periods),
    )


# ---------------------------------------------------------------------------
# TestPickReferenceDf
# ---------------------------------------------------------------------------


class TestPickReferenceDf:
    """Tests for main._pick_reference_df(comparison_dfs)."""

    def test_returns_spy_when_present(self):
        """When SPY is in comparison_dfs, the SPY DataFrame is returned — not first."""
        spy_df = _make_df("2020-01-01")
        qqq_df = _make_df("2019-01-01")  # Earlier start — should NOT be picked
        comparison_dfs = {"QQQ": qqq_df, "SPY": spy_df}

        result = _pick_reference_df(comparison_dfs)

        assert result is spy_df, "Expected SPY to be chosen as reference"

    def test_does_not_raise_with_valid_spy_df(self):
        """Must NOT raise ValueError ('truth value of a DataFrame is ambiguous')."""
        spy_df = _make_df()
        comparison_dfs = {"SPY": spy_df}

        # This is the regression assertion — buggy code raises ValueError here
        try:
            result = _pick_reference_df(comparison_dfs)
        except ValueError as exc:
            pytest.fail(f"_pick_reference_df raised ValueError: {exc}")

        assert result is spy_df

    def test_falls_back_to_first_df_when_no_spy(self):
        """When SPY is absent, the first available DataFrame is returned."""
        qqq_df = _make_df("2019-01-01")
        comparison_dfs = {"QQQ": qqq_df}

        result = _pick_reference_df(comparison_dfs)

        assert result is qqq_df

    def test_falls_back_to_first_df_multiple_non_spy(self):
        """When multiple non-SPY tickers are present, the first is returned."""
        qqq_df = _make_df("2019-01-01")
        xlf_df = _make_df("2018-01-01")
        comparison_dfs = {"QQQ": qqq_df, "XLF": xlf_df}

        result = _pick_reference_df(comparison_dfs)

        # First value in insertion order
        assert result is qqq_df

    def test_single_non_spy_ticker(self):
        """Single non-SPY ticker — returns that ticker's DataFrame."""
        vix_df = _make_df()
        comparison_dfs = {"I:VIX": vix_df}

        result = _pick_reference_df(comparison_dfs)

        assert result is vix_df
