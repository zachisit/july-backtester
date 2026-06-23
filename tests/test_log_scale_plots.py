"""tests/test_log_scale_plots.py

Tests that plot_benchmark_comparison and plot_mc_fan auto-switch to log Y-axis
when equity range exceeds 10x, and stay on linear scale for normal ranges.
"""

import os
import sys

import matplotlib
matplotlib.use('Agg')  # non-interactive backend — must be set before pyplot import

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from trade_analyzer.plotting import (
    plot_benchmark_comparison,
    plot_equity_and_drawdown,
    plot_mc_fan,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_equity(start: float, end: float, n: int = 50) -> pd.Series:
    dates = pd.date_range('2010-01-01', periods=n, freq='B')
    values = np.linspace(start, end, n)
    return pd.Series(values, index=dates)


def _make_benchmark_df(equity: pd.Series) -> pd.DataFrame:
    """Benchmark that exactly tracks the equity (normalisation test doesn't matter here)."""
    return pd.DataFrame({'Benchmark_Price': equity.values * 1.1}, index=equity.index)


def _make_mc_paths(initial: float, final_median: float, n_trades: int = 30, n_sims: int = 100) -> pd.DataFrame:
    """Build a DataFrame of MC equity paths (shape: n_trades x n_sims)."""
    rng = np.random.default_rng(42)
    paths = np.linspace(initial, final_median, n_trades)[:, None] + rng.normal(0, initial * 0.05, (n_trades, n_sims))
    paths = np.clip(paths, 1, None)
    return pd.DataFrame(paths)


def _make_trades_with_equity(start: float, end: float, n: int = 50) -> pd.DataFrame:
    """trades_df with a compounding 'Equity' column + calendar 'Ex. date'."""
    dates = pd.date_range('2010-01-01', periods=n, freq='B')
    equity = np.linspace(start, end, n)
    return pd.DataFrame({'Ex. date': dates, 'Equity': equity})


def _make_dd_series(n: int = 50) -> pd.Series:
    """Flat (zero) drawdown series with a DatetimeIndex matching the equity x-axis."""
    dates = pd.date_range('2010-01-01', periods=n, freq='B')
    return pd.Series(np.zeros(n), index=dates)


# ---------------------------------------------------------------------------
# plot_benchmark_comparison — Y-axis scale
# ---------------------------------------------------------------------------

class TestBenchmarkComparisonLogScale:
    def test_linear_scale_for_small_range(self):
        """Range < 10× → linear scale (no change to existing behaviour)."""
        equity = _make_equity(100_000, 300_000)  # 3× — linear
        bdf = _make_benchmark_df(equity)
        fig = plot_benchmark_comparison(equity, bdf, 'SPY')
        ax = fig.axes[0]
        assert ax.get_yscale() == 'linear'

    def test_log_scale_for_large_range(self):
        """Range > 10× → log scale auto-applied."""
        equity = _make_equity(100_000, 1_100_000)  # 11× — log
        bdf = _make_benchmark_df(equity)
        fig = plot_benchmark_comparison(equity, bdf, 'SPY')
        ax = fig.axes[0]
        assert ax.get_yscale() == 'log'

    def test_boundary_at_exactly_10x_stays_linear(self):
        """Exactly 10× is NOT > 10, so stays linear."""
        equity = _make_equity(100_000, 1_000_000)  # exactly 10× (min/max = 10.0)
        bdf = _make_benchmark_df(equity)
        fig = plot_benchmark_comparison(equity, bdf, 'SPY')
        ax = fig.axes[0]
        assert ax.get_yscale() == 'linear'

    def test_returns_figure_on_large_range(self):
        """Function must not raise and must return a Figure for large compounding runs."""
        equity = _make_equity(100_000, 2_000_000)
        bdf = _make_benchmark_df(equity)
        import matplotlib.pyplot as plt
        fig = plot_benchmark_comparison(equity, bdf, 'SPY')
        assert isinstance(fig, plt.Figure)


# ---------------------------------------------------------------------------
# plot_mc_fan — Y-axis scale
# ---------------------------------------------------------------------------

class TestMcFanLogScale:
    def test_linear_scale_for_small_range(self):
        """p95/p5 ratio < 10 → linear scale."""
        paths = _make_mc_paths(100_000, 300_000)
        fig = plot_mc_fan(paths, initial_equity=100_000)
        ax = fig.axes[0]
        assert ax.get_yscale() == 'linear'

    def test_log_scale_for_large_range(self):
        """p95/p5 ratio > 10 → log scale auto-applied."""
        paths = _make_mc_paths(100_000, 1_500_000)
        fig = plot_mc_fan(paths, initial_equity=100_000)
        ax = fig.axes[0]
        assert ax.get_yscale() == 'log'

    def test_returns_figure_on_large_range(self):
        """Function must not raise and must return a Figure for large MC fans."""
        import matplotlib.pyplot as plt
        paths = _make_mc_paths(100_000, 2_000_000)
        fig = plot_mc_fan(paths, initial_equity=100_000)
        assert isinstance(fig, plt.Figure)


# ---------------------------------------------------------------------------
# plot_equity_and_drawdown — Y-axis scale (headline equity curve, 3rd chart)
# ---------------------------------------------------------------------------

class TestEquityCurveLogScale:
    def test_linear_scale_for_small_range(self):
        """Range < 10× → equity panel stays linear (no change to existing behaviour)."""
        trades = _make_trades_with_equity(100_000, 300_000)  # 3× — linear
        fig = plot_equity_and_drawdown(trades, _make_dd_series())
        assert fig.axes[0].get_yscale() == 'linear'

    def test_log_scale_for_large_range(self):
        """Range > 10× → equity panel auto-switches to log."""
        trades = _make_trades_with_equity(100_000, 1_100_000)  # 11× — log
        fig = plot_equity_and_drawdown(trades, _make_dd_series())
        assert fig.axes[0].get_yscale() == 'log'

    def test_boundary_at_exactly_10x_stays_linear(self):
        """Exactly 10× is NOT > 10, so stays linear."""
        trades = _make_trades_with_equity(100_000, 1_000_000)  # exactly 10×
        fig = plot_equity_and_drawdown(trades, _make_dd_series())
        assert fig.axes[0].get_yscale() == 'linear'

    def test_drawdown_panel_unaffected_when_equity_is_log(self):
        """Log scale must apply to the equity panel only — the drawdown % panel stays linear."""
        trades = _make_trades_with_equity(100_000, 2_000_000)  # 20× — log
        fig = plot_equity_and_drawdown(trades, _make_dd_series())
        assert fig.axes[0].get_yscale() == 'log'
        assert fig.axes[1].get_yscale() == 'linear'

    def test_returns_figure_on_large_range(self):
        """Function must not raise and must return a Figure for large compounding runs."""
        import matplotlib.pyplot as plt
        trades = _make_trades_with_equity(100_000, 2_000_000)
        fig = plot_equity_and_drawdown(trades, _make_dd_series())
        assert isinstance(fig, plt.Figure)
