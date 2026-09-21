"""
Regression tests for issue #309 — the documented ATR stop config
(`{"type": "atr", "multiplier": 2.0}`, no ``period`` key) crashed every
worker task with ``KeyError: 'period'`` inside ``run_single_simulation``.

The offending line built the strategy display name as::

    f"{name} w/ {stop_config['multiplier']}x ATR({stop_config['period']}) SL"

``stop_config['period']`` is not part of the documented config shape
(``config.py`` and CLAUDE.md only ever specify ``type`` + ``multiplier``);
only the CLI shorthand ``atr:14:3.0`` injects a ``period``. The engine itself
always uses the ``ATR_14`` column, so the label must default the period to 14
rather than assume the key is present.

Two layers of coverage:

* ``TestAtrStopNaming`` exercises the extracted, pure ``main._build_strat_name``
  helper directly (fast, exhaustive over config shapes).
* ``TestRunSingleSimulationNaming`` drives ``main.run_single_simulation``
  end-to-end so the *wiring* is pinned: reverting the call site back to the
  old inline ``stop_config['period']`` access re-triggers the swallowed
  ``KeyError`` (worker returns ``None``) and fails this test — the unit tests
  on the helper alone would stay green.
"""

import os
import sys

import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import main
from main import _build_strat_name


class TestAtrStopNaming:
    def test_documented_atr_config_without_period_does_not_raise(self):
        """The exact documented config shape must not raise KeyError."""
        stop_config = {"type": "atr", "multiplier": 2.0}
        # Must not raise
        label = _build_strat_name("My Strategy", stop_config)
        assert "My Strategy" in label
        assert "ATR" in label
        assert "SL" in label

    def test_atr_config_without_period_defaults_to_14(self):
        """Engine always uses ATR_14, so the label defaults the period to 14."""
        stop_config = {"type": "atr", "multiplier": 2.0}
        assert _build_strat_name("S", stop_config) == "S w/ 2.0x ATR(14) SL"

    def test_atr_config_with_explicit_period_is_rendered_verbatim(self):
        """The CLI shorthand path supplies a period; it is rendered verbatim.

        NOTE: the engine currently reads the ``ATR_14`` column regardless, so a
        period other than 14 is a display-only value and does not change the
        backtest. Tracked as a follow-up (engine does not honor ATR period).
        """
        stop_config = {"type": "atr", "multiplier": 3.0, "period": 21}
        assert _build_strat_name("S", stop_config) == "S w/ 3.0x ATR(21) SL"

    def test_atr_config_without_multiplier_defaults_to_3(self):
        """Engine defaults a missing ATR multiplier to 3.0 and would run the
        config; the label must not crash the worker first (issue #309 class)."""
        assert _build_strat_name("S", {"type": "atr"}) == "S w/ 3.0x ATR(14) SL"

    def test_atr_multiplier_int_renders_without_forcing_float(self):
        """Parity with the old inline f-string: an int multiplier renders bare."""
        assert _build_strat_name("S", {"type": "atr", "multiplier": 2}) == "S w/ 2x ATR(14) SL"

    def test_percentage_config_label(self):
        stop_config = {"type": "percentage", "value": 0.05}
        assert _build_strat_name("S", stop_config) == "S w/ 5% SL"

    def test_percentage_config_without_value_defaults_to_5pct(self):
        """Engine defaults a missing percentage value to 0.05; label mirrors it."""
        assert _build_strat_name("S", {"type": "percentage"}) == "S w/ 5% SL"

    def test_percentage_rounding_is_half_even(self):
        """`:.0%` uses Python round-half-to-even: 12.5% -> '12%'. Pin it."""
        assert _build_strat_name("S", {"type": "percentage", "value": 0.125}) == "S w/ 12% SL"

    def test_none_config_returns_name_unchanged(self):
        assert _build_strat_name("S", {"type": "none"}) == "S"

    def test_unknown_stop_type_returns_name_unchanged(self):
        # points / signal_bar / trailing_atr etc. are not specially labelled
        assert _build_strat_name("S", {"type": "points", "value": 10}) == "S"

    def test_missing_type_key_returns_name_unchanged(self):
        """A config with no 'type' is treated as 'none' (matches the engine's
        `.get("type", "none")`), returning the bare name rather than raising."""
        assert _build_strat_name("S", {}) == "S"


class TestRunSingleSimulationNaming:
    """End-to-end: the documented ATR config must survive run_single_simulation
    and land its label in result['Strategy'] — pinning the call-site wiring."""

    def _patch_globals(self, monkeypatch):
        idx = pd.bdate_range("2023-01-02", periods=6)
        df = pd.DataFrame(
            {"Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.0, "Volume": 1e6},
            index=idx,
        )
        monkeypatch.setattr(main, "comparison_dfs_global", {}, raising=False)
        monkeypatch.setattr(main, "benchmark_returns_global", {}, raising=False)
        monkeypatch.setattr(main, "dependency_map_global", {}, raising=False)
        monkeypatch.setattr(main, "portfolio_data_global", {"AAA": df}, raising=False)
        monkeypatch.setattr(main, "delisting_dates_global", {}, raising=False)
        monkeypatch.setattr(main, "pit_member_masks_global", None, raising=False)
        monkeypatch.setattr(main, "intrabar_data_global", None, raising=False)

        # Minimal result that reaches the return without needing MC/WFA:
        # trade_pnl_list truthy -> enters the result-assembly block; Trades == 0
        # -> the no-trades branch (no Monte Carlo).
        def fake_rps(*args, **kwargs):
            return {
                "trade_pnl_list": [0.0],
                "Trades": 0,
                "initial_capital": 100000.0,
                "portfolio_timeline": None,
                "trade_log": [],
                "pnl_percent": 0.0,
            }

        monkeypatch.setattr(main, "run_portfolio_simulation", fake_rps)

    @staticmethod
    def _logic(d, **kwargs):
        d = d.copy()
        d["Signal"] = 0
        return d

    def test_documented_atr_stop_does_not_zero_result_and_labels_correctly(self, monkeypatch):
        self._patch_globals(monkeypatch)
        # The documented config shape that used to raise KeyError: 'period'.
        task = ("P", "S", self._logic, [], {"type": "atr", "multiplier": 2.0}, {}, None, None, None)
        result = main.run_single_simulation(task)
        assert result is not None, "worker swallowed an exception (the #309 regression)"
        assert result["Strategy"] == "S w/ 2.0x ATR(14) SL"

    def test_percentage_stop_end_to_end_label(self, monkeypatch):
        self._patch_globals(monkeypatch)
        task = ("P", "S", self._logic, [], {"type": "percentage", "value": 0.05}, {}, None, None, None)
        result = main.run_single_simulation(task)
        assert result is not None
        assert result["Strategy"] == "S w/ 5% SL"
