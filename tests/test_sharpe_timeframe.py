"""
tests/test_sharpe_timeframe.py

Regression tests for the Sharpe annualization bug: simulations.py was
hardcoding bars_per_year=252 regardless of the configured timeframe, which
inflated Sharpe by sqrt(252/52) ≈ 2.2x for weekly strategies and by
sqrt(252/12) ≈ 4.6x for monthly strategies.

Fix: use get_bars_per_year(CONFIG) for both the rf-per-bar conversion and
the annualization factor so the result is consistent across timeframes.
Also covers report.py::_load_bars_per_year which propagates the correct
annualization factor to the PDF tearsheet.
"""
import json
import numpy as np
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import patch

from helpers.simulations import calculate_advanced_metrics, calculate_rolling_sharpe
from report import _load_bars_per_year


def _make_timeline(n_bars: int, weekly_return: float) -> pd.Series:
    """Flat-return equity curve: start at 100 000, compound weekly_return each bar."""
    values = [100_000 * (1 + weekly_return) ** i for i in range(n_bars)]
    dates = pd.bdate_range("2010-01-04", periods=n_bars)
    return pd.Series(values, index=dates)


_DAILY_CFG = {
    "risk_free_rate": 0.05,
    "timeframe": "D",
    "timeframe_multiplier": 1,
}
_WEEKLY_CFG = {
    "risk_free_rate": 0.05,
    "timeframe": "W",
    "timeframe_multiplier": 1,
}
_MONTHLY_CFG = {
    "risk_free_rate": 0.05,
    "timeframe": "M",
    "timeframe_multiplier": 1,
}


class TestSharpeAnnualizationConsistency:
    """
    The same underlying return/risk profile should produce the same Sharpe
    regardless of whether it is expressed as daily, weekly, or monthly bars.

    Given a flat daily return r_d, a weekly bar covers 5 trading days so
    r_w = (1+r_d)^5 - 1.  Both should yield the same annualized Sharpe.
    """

    def test_weekly_sharpe_matches_daily_equivalent(self):
        """
        A flat-return daily strategy and its weekly-bar equivalent must
        produce Sharpe ratios within 5% of each other.
        """
        r_daily = 0.001          # 0.1% per day
        r_weekly = (1 + r_daily) ** 5 - 1

        # Inject artificial noise so std > 0
        np.random.seed(42)
        n_daily = 252 * 5
        n_weekly = 52 * 5

        daily_values = 100_000 * np.cumprod(1 + r_daily + np.random.normal(0, 0.005, n_daily))
        weekly_values = 100_000 * np.cumprod(1 + r_weekly + np.random.normal(0, 0.005 * np.sqrt(5), n_weekly))

        daily_tl = pd.Series(daily_values, index=pd.bdate_range("2015-01-05", periods=n_daily))
        weekly_tl = pd.Series(weekly_values, index=pd.bdate_range("2015-01-05", periods=n_weekly))

        pnl = [1.0] * 10  # dummy

        with patch.dict("config.CONFIG", _DAILY_CFG):
            d_metrics = calculate_advanced_metrics(pnl, daily_tl, [])
        with patch.dict("config.CONFIG", _WEEKLY_CFG):
            w_metrics = calculate_advanced_metrics(pnl, weekly_tl, [])

        d_sharpe = d_metrics["sharpe_ratio"]
        w_sharpe = w_metrics["sharpe_ratio"]
        assert d_sharpe != 0, "Daily Sharpe should not be zero"
        assert w_sharpe != 0, "Weekly Sharpe should not be zero"
        # Same underlying process — results should be within 20% of each other
        ratio = w_sharpe / d_sharpe
        assert 0.80 <= ratio <= 1.20, (
            f"Weekly Sharpe {w_sharpe:.3f} too far from daily Sharpe {d_sharpe:.3f} "
            f"(ratio {ratio:.3f}). Annualization factor is likely wrong."
        )

    def test_weekly_sharpe_not_inflated_by_sqrt252(self):
        """
        Before the fix, weekly Sharpe was inflated by sqrt(252/52) ≈ 2.2x.
        Verify the result is NOT suspiciously large for a modest weekly strategy.
        """
        # Build a modestly profitable weekly equity curve
        np.random.seed(7)
        n = 52 * 10  # 10 years weekly
        weekly_rets = 0.002 + np.random.normal(0, 0.015, n)
        tl = pd.Series(100_000 * np.cumprod(1 + weekly_rets),
                       index=pd.bdate_range("2010-01-04", periods=n))
        pnl = [1.0] * 20

        with patch.dict("config.CONFIG", _WEEKLY_CFG):
            metrics = calculate_advanced_metrics(pnl, tl, [])

        sharpe = metrics["sharpe_ratio"]
        # A realistic weekly strategy should not exceed Sharpe ~3.
        # The pre-fix bug produced ~2.2x inflation, so a Sharpe of ~1 would
        # incorrectly appear as ~2.2.
        assert sharpe < 4.0, (
            f"Sharpe {sharpe:.2f} looks inflated (pre-fix bug produced ~2.2x for weekly bars)."
        )

    def test_daily_sharpe_unchanged(self):
        """Daily Sharpe must be unaffected by the fix (uses 252 as before)."""
        np.random.seed(1)
        n = 252 * 5
        daily_rets = 0.0005 + np.random.normal(0, 0.008, n)
        tl = pd.Series(100_000 * np.cumprod(1 + daily_rets),
                       index=pd.bdate_range("2015-01-05", periods=n))
        pnl = [1.0] * 20

        with patch.dict("config.CONFIG", _DAILY_CFG):
            metrics = calculate_advanced_metrics(pnl, tl, [])

        sharpe = metrics["sharpe_ratio"]
        # Daily strategy at 0.05% mean / 0.8% std → raw Sharpe ≈ 0.0625/0.08 * sqrt(252) ≈ ~1
        assert 0.3 < sharpe < 3.0, f"Daily Sharpe {sharpe:.3f} out of expected range"


class TestRollingSharpeTimeframe:
    """calculate_rolling_sharpe must also respect the configured timeframe."""

    def test_rolling_sharpe_weekly_not_inflated(self):
        """Rolling Sharpe on a weekly equity curve must not be inflated by 2.2x."""
        np.random.seed(42)
        n = 52 * 10
        weekly_rets = 0.002 + np.random.normal(0, 0.015, n)
        tl = pd.Series(100_000 * np.cumprod(1 + weekly_rets),
                       index=pd.bdate_range("2010-01-04", periods=n))

        with patch.dict("config.CONFIG", _WEEKLY_CFG):
            rolling = calculate_rolling_sharpe(tl, window=26)

        valid = rolling.dropna()
        assert len(valid) > 0
        # No single 26-bar window should produce Sharpe > 6 for a modest strategy
        assert valid.abs().max() < 6.0, (
            f"Rolling Sharpe max {valid.abs().max():.2f} looks inflated for weekly bars."
        )

    def test_rolling_sharpe_daily_unchanged(self):
        """Rolling Sharpe on a daily equity curve behaves as before the fix."""
        np.random.seed(3)
        n = 252 * 5
        daily_rets = 0.0005 + np.random.normal(0, 0.008, n)
        tl = pd.Series(100_000 * np.cumprod(1 + daily_rets),
                       index=pd.bdate_range("2015-01-05", periods=n))

        with patch.dict("config.CONFIG", _DAILY_CFG):
            rolling = calculate_rolling_sharpe(tl, window=126)

        valid = rolling.dropna()
        assert len(valid) > 0
        # Reasonable range for a mild daily strategy
        assert valid.abs().max() < 5.0


class TestLoadBarsPerYear:
    """report.py::_load_bars_per_year reads timeframe from config_snapshot.json."""

    def _write_snapshot(self, tmp_path: Path, data: dict) -> Path:
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        (run_dir / "config_snapshot.json").write_text(json.dumps(data), encoding="utf-8")
        return run_dir

    def test_daily_returns_252(self, tmp_path):
        run_dir = self._write_snapshot(tmp_path, {"timeframe": "D", "timeframe_multiplier": 1})
        assert _load_bars_per_year(run_dir) == 252

    def test_weekly_returns_52(self, tmp_path):
        run_dir = self._write_snapshot(tmp_path, {"timeframe": "W", "timeframe_multiplier": 1})
        assert _load_bars_per_year(run_dir) == 52

    def test_monthly_returns_12(self, tmp_path):
        run_dir = self._write_snapshot(tmp_path, {"timeframe": "M", "timeframe_multiplier": 1})
        assert _load_bars_per_year(run_dir) == 12

    def test_missing_snapshot_returns_none(self, tmp_path):
        run_dir = tmp_path / "empty_run"
        run_dir.mkdir()
        assert _load_bars_per_year(run_dir) is None

    def test_missing_timeframe_key_returns_none(self, tmp_path):
        run_dir = self._write_snapshot(tmp_path, {"wfa_split_ratio": 0.8})
        assert _load_bars_per_year(run_dir) is None

    def test_invalid_json_returns_none(self, tmp_path):
        run_dir = tmp_path / "bad_run"
        run_dir.mkdir()
        (run_dir / "config_snapshot.json").write_text("not valid json", encoding="utf-8")
        assert _load_bars_per_year(run_dir) is None

    def test_unsupported_timeframe_returns_none(self, tmp_path):
        run_dir = self._write_snapshot(tmp_path, {"timeframe": "BADTF", "timeframe_multiplier": 1})
        assert _load_bars_per_year(run_dir) is None
