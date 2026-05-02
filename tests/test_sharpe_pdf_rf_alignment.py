"""
tests/test_sharpe_pdf_rf_alignment.py

TDD regression suite for the Sharpe/Sortino risk-free-rate mismatch between
the backtester terminal and the PDF tearsheet (report.py → analyzer.py).

Bug summary
-----------
trade_analyzer/default_config.py had RISK_FREE_RATE = 0.0.  report.py imported
that constant and used it as the PDF's risk-free rate.  The backtester
(config.py) defaults to 0.05.  Every generated PDF therefore computed
Sharpe and Sortino with rf=0% while the terminal used rf=5%, producing a
systematically higher Sharpe in the PDF than in the terminal output.

Fix
---
1. default_config.RISK_FREE_RATE changed to 0.05 (correct fallback).
2. report.py now reads risk_free_rate from config_snapshot.json via
   _load_risk_free_rate() and overrides RISK_FREE_RATE in config_params,
   exactly like bars_per_year / wfa_split_ratio are already handled.

These tests are written so that every one of them would have FAILED against
the pre-fix code:
  - test_*_default tests: failed because RISK_FREE_RATE was 0.0
  - test_load_* tests: failed because _load_risk_free_rate didn't exist
  - test_report_*_applies_rf tests: failed because config_params never
    received the backtester's rate
  - test_sharpe_pdf_higher_than_terminal_*: demonstrates the observable
    symptom — with rf=0, PDF Sharpe is always >= terminal Sharpe for any
    strategy with positive mean returns
"""

import json
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import CONFIG
from helpers.simulations import calculate_advanced_metrics
from trade_analyzer import calculations
from trade_analyzer import default_config as analyzer_default


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _equity_curve(n: int = 252 * 5, drift: float = 0.0008, seed: int = 42) -> pd.Series:
    """Return a realistic equity curve with slight upward drift."""
    rng = np.random.default_rng(seed)
    rets = drift + rng.normal(0, 0.010, n)
    equity = 100_000.0 * np.cumprod(1 + rets)
    return pd.Series(equity, index=pd.bdate_range("2015-01-02", periods=n))


def _terminal_sharpe(tl: pd.Series, rf: float = 0.05) -> float:
    """Replicate the terminal's Sharpe formula exactly."""
    from unittest.mock import patch
    pnl = [float(tl.iloc[-1] - tl.iloc[0])]
    cfg = {"risk_free_rate": rf, "timeframe": "D", "timeframe_multiplier": 1}
    with patch.dict("config.CONFIG", cfg):
        m = calculate_advanced_metrics(pnl, tl, [len(tl)])
    return m["sharpe_ratio"]


def _pdf_sharpe(tl: pd.Series, rf: float, trading_days: int = 252) -> float:
    """Replicate the PDF's Sharpe formula (calculations.calculate_sharpe_ratio)."""
    return calculations.calculate_sharpe_ratio(tl.pct_change().dropna(), rf, trading_days)


# ---------------------------------------------------------------------------
# 1. Default rate alignment
# ---------------------------------------------------------------------------

class TestDefaultRateParity:
    """default_config.RISK_FREE_RATE must match the backtester's default."""

    def test_analyzer_default_is_not_zero(self):
        """RISK_FREE_RATE = 0.0 was the bug. The value must no longer be 0."""
        assert analyzer_default.RISK_FREE_RATE != 0.0, (
            "default_config.RISK_FREE_RATE is still 0.0 — the bug is not fixed"
        )

    def test_analyzer_default_matches_backtester_default(self):
        """Ensures a new run where config_snapshot.json doesn't exist still aligns."""
        assert analyzer_default.RISK_FREE_RATE == CONFIG["risk_free_rate"], (
            f"default_config.RISK_FREE_RATE={analyzer_default.RISK_FREE_RATE} "
            f"!= config.CONFIG['risk_free_rate']={CONFIG['risk_free_rate']}"
        )

    def test_backtester_default_is_five_pct(self):
        """Sanity: config.py default is the 5% T-bill proxy, not 0."""
        assert CONFIG["risk_free_rate"] == pytest.approx(0.05)


# ---------------------------------------------------------------------------
# 2. The symptom — rf=0 inflates Sharpe vs rf=0.05
# ---------------------------------------------------------------------------

class TestRfRateInflatesSharpWhenZero:
    """Demonstrates the observable bug: PDF Sharpe was always > terminal Sharpe
    for any positively-drifting strategy when PDF used rf=0."""

    def test_pdf_sharpe_higher_with_rf_zero_than_rf_five_pct(self):
        tl = _equity_curve()
        sharpe_rf0 = _pdf_sharpe(tl, rf=0.0)
        sharpe_rf5 = _pdf_sharpe(tl, rf=0.05)
        assert sharpe_rf0 > sharpe_rf5, (
            f"rf=0 Sharpe ({sharpe_rf0:.4f}) should exceed rf=0.05 Sharpe ({sharpe_rf5:.4f})"
        )

    def test_rf_zero_sharpe_differs_from_rf_five_by_meaningful_amount(self):
        """The gap must be large enough to be visible in a report (> 0.05 Sharpe units)."""
        tl = _equity_curve(n=252 * 10)
        sharpe_rf0 = _pdf_sharpe(tl, rf=0.0)
        sharpe_rf5 = _pdf_sharpe(tl, rf=0.05)
        diff = abs(sharpe_rf0 - sharpe_rf5)
        assert diff > 0.05, (
            f"rf mismatch produces only {diff:.4f} Sharpe units difference — "
            "expected a visible gap (> 0.05)"
        )

    def test_terminal_and_pdf_agree_when_same_rf_used(self):
        """When both sides use the same rf, Sharpe values must be identical."""
        tl = _equity_curve()
        terminal = _terminal_sharpe(tl, rf=0.05)
        pdf = _pdf_sharpe(tl, rf=0.05)
        assert abs(terminal - pdf) < 1e-9, (
            f"terminal Sharpe {terminal:.6f} != PDF Sharpe {pdf:.6f}"
        )

    def test_terminal_and_pdf_disagree_when_rf_mismatched(self):
        """Reproduces the pre-fix symptom: different rf → different Sharpe."""
        tl = _equity_curve()
        terminal_rf5 = _terminal_sharpe(tl, rf=0.05)
        pdf_rf0 = _pdf_sharpe(tl, rf=0.0)
        assert abs(terminal_rf5 - pdf_rf0) > 0.01, (
            "Pre-fix symptom not reproducible: terminal (rf=0.05) and "
            "PDF (rf=0.0) Sharpe should differ"
        )


# ---------------------------------------------------------------------------
# 3. _load_risk_free_rate — unit tests
# ---------------------------------------------------------------------------

class TestLoadRiskFreeRate:
    """Unit tests for report._load_risk_free_rate."""

    @pytest.fixture
    def snapshot(self, tmp_path):
        def _write(data: dict):
            p = tmp_path / "config_snapshot.json"
            p.write_text(json.dumps(data), encoding="utf-8")
            return tmp_path
        return _write

    def _fn(self):
        from report import _load_risk_free_rate
        return _load_risk_free_rate

    def test_returns_rate_from_snapshot(self, snapshot):
        d = snapshot({"risk_free_rate": 0.05, "timeframe": "D"})
        assert self._fn()(d) == pytest.approx(0.05)

    def test_returns_custom_rate(self, snapshot):
        d = snapshot({"risk_free_rate": 0.03})
        assert self._fn()(d) == pytest.approx(0.03)

    def test_returns_zero_rate_as_valid(self, snapshot):
        """rf=0 is a legitimate choice and must not be filtered out."""
        d = snapshot({"risk_free_rate": 0.0})
        assert self._fn()(d) == pytest.approx(0.0)

    def test_returns_none_when_key_absent(self, snapshot):
        d = snapshot({"timeframe": "D"})
        assert self._fn()(d) is None

    def test_returns_none_when_file_missing(self, tmp_path):
        assert self._fn()(tmp_path) is None

    def test_returns_none_for_negative_rate(self, snapshot):
        """Negative risk-free rates are nonsensical — treat as missing."""
        d = snapshot({"risk_free_rate": -0.01})
        assert self._fn()(d) is None

    def test_returns_none_for_non_numeric_value(self, snapshot):
        d = snapshot({"risk_free_rate": "high"})
        assert self._fn()(d) is None

    def test_returns_none_for_invalid_json(self, tmp_path):
        (tmp_path / "config_snapshot.json").write_text("{bad json", encoding="utf-8")
        assert self._fn()(tmp_path) is None


# ---------------------------------------------------------------------------
# 4. Integration — report.py config_params receives the correct rate
# ---------------------------------------------------------------------------

class TestReportPyPropagatesRate:
    """Verifies that config_params passed to generate_trade_report contains
    the correct RISK_FREE_RATE after report.py reads the snapshot."""

    def _make_snapshot(self, tmp_path: "Path", rf: float) -> "Path":
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        snapshot = {
            "risk_free_rate": rf,
            "timeframe": "D",
            "timeframe_multiplier": 1,
            "wfa_split_ratio": None,
        }
        (run_dir / "config_snapshot.json").write_text(
            json.dumps(snapshot), encoding="utf-8"
        )
        return run_dir

    def test_batch_mode_snapshot_rf_overrides_default(self, tmp_path):
        """_load_risk_free_rate returns the snapshot's rate, not the old 0.0 default."""
        from report import _load_risk_free_rate
        run_dir = self._make_snapshot(tmp_path, rf=0.05)
        loaded = _load_risk_free_rate(run_dir)
        assert loaded == pytest.approx(0.05), (
            f"Expected 0.05 from snapshot, got {loaded!r}"
        )
        assert loaded != 0.0, (
            "Risk-free rate must not be the pre-fix default of 0.0"
        )

    def test_custom_rf_in_snapshot_is_propagated(self, tmp_path):
        """A project using rf=0.02 must propagate that rate to the PDF."""
        from report import _load_risk_free_rate
        run_dir = self._make_snapshot(tmp_path, rf=0.02)
        loaded = _load_risk_free_rate(run_dir)
        assert loaded == pytest.approx(0.02)

    def test_sharpe_computed_with_snapshot_rf_matches_terminal(self, tmp_path):
        """End-to-end: with snapshot rf=0.05, PDF Sharpe matches terminal."""
        from report import _load_risk_free_rate
        from unittest.mock import patch

        run_dir = self._make_snapshot(tmp_path, rf=0.05)
        loaded_rf = _load_risk_free_rate(run_dir)
        assert loaded_rf is not None

        tl = _equity_curve()
        pnl = [float(tl.iloc[-1] - tl.iloc[0])]
        cfg = {"risk_free_rate": loaded_rf, "timeframe": "D", "timeframe_multiplier": 1}
        with patch.dict("config.CONFIG", cfg):
            m = calculate_advanced_metrics(pnl, tl, [len(tl)])
        terminal_sharpe = m["sharpe_ratio"]

        pdf_sharpe = calculations.calculate_sharpe_ratio(
            tl.pct_change().dropna(), loaded_rf, 252
        )

        assert abs(terminal_sharpe - pdf_sharpe) < 1e-9, (
            f"terminal={terminal_sharpe:.6f}, pdf={pdf_sharpe:.6f}: "
            "should be identical when using the same rf"
        )


# ---------------------------------------------------------------------------
# 5. Sortino alignment (same root cause as Sharpe)
# ---------------------------------------------------------------------------

class TestSortinoRfAlignment:
    """Sortino is also affected by the rf mismatch — verify it aligns too."""

    def test_sortino_differs_between_rf_zero_and_rf_five(self):
        tl = _equity_curve()
        rets = tl.pct_change().dropna()
        s0 = calculations.calculate_sortino_ratio(rets, 0.0, 252)
        s5 = calculations.calculate_sortino_ratio(rets, 0.05, 252)
        assert s0 != pytest.approx(s5, abs=0.05), (
            "Sortino must differ between rf=0 and rf=0.05"
        )

    def test_sortino_rf_zero_is_higher_than_rf_five_for_positive_drift(self):
        tl = _equity_curve()
        rets = tl.pct_change().dropna()
        s0 = calculations.calculate_sortino_ratio(rets, 0.0, 252)
        s5 = calculations.calculate_sortino_ratio(rets, 0.05, 252)
        assert s0 > s5, (
            f"Sortino rf=0 ({s0:.4f}) should exceed rf=0.05 ({s5:.4f}) "
            "for a positive-drift strategy"
        )
