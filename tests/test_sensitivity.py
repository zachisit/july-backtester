# tests/test_sensitivity.py
"""
Unit tests for helpers/sensitivity.py — Parameter Sensitivity Sweep.

Covers:
  build_param_grid  — cartesian product, int rounding, floor, dedup
  label_for_params  — identical/single-diff/multi-diff cases
  is_sweep_enabled  — config gate (no-regression default path)
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from unittest.mock import patch

from config import CONFIG
from helpers.sensitivity import build_param_grid, is_sweep_enabled, label_for_params


# ---------------------------------------------------------------------------
# TestBuildParamGrid
# ---------------------------------------------------------------------------

class TestBuildParamGrid:

    def test_base_always_included(self):
        """The base param dict must appear exactly once in the grid."""
        params = {"fast": 20, "slow": 50}
        grid = build_param_grid(params, pct=0.20, steps=2, min_val=2)
        base_count = sum(
            1 for g in grid
            if g["fast"] == params["fast"] and g["slow"] == params["slow"]
        )
        assert base_count == 1, f"Base appeared {base_count} times, expected 1"

    def test_single_param_five_values(self):
        """{"fast": 20} at pct=0.20, steps=2 → values [12, 16, 20, 24, 28]."""
        grid = build_param_grid({"fast": 20}, pct=0.20, steps=2, min_val=2)
        vals = sorted(g["fast"] for g in grid)
        assert vals == [12, 16, 20, 24, 28], f"Got {vals}"

    def test_two_params_cartesian(self):
        """2 params × 5 values each = 25 grid points."""
        params = {"fast": 20, "slow": 50}
        grid = build_param_grid(params, pct=0.20, steps=2, min_val=2)
        assert len(grid) == 25, f"Expected 25 grid points, got {len(grid)}"

    def test_non_numeric_keys_unchanged(self):
        """String and bool values must pass through unchanged in every grid point."""
        params = {"fast": 20, "mode": "sma", "use_filter": True}
        grid = build_param_grid(params, pct=0.20, steps=2, min_val=2)
        for g in grid:
            assert g["mode"] == "sma"
            assert g["use_filter"] is True

    def test_min_val_floor(self):
        """No generated value should fall below min_val."""
        params = {"fast": 3}  # small base: 3 * 0.60 = 1.8 → rounded 2 with floor
        grid = build_param_grid(params, pct=0.20, steps=2, min_val=2)
        for g in grid:
            assert g["fast"] >= 2, f"Value {g['fast']} is below min_val=2"

    def test_empty_params_returns_one_empty_dict(self):
        """Empty params dict must return [{}]."""
        grid = build_param_grid({}, pct=0.20, steps=2, min_val=2)
        assert grid == [{}]

    def test_no_numeric_keys_returns_base_only(self):
        """All-non-numeric params must return exactly the base dict."""
        params = {"mode": "ema", "label": "test"}
        grid = build_param_grid(params, pct=0.20, steps=2, min_val=2)
        assert grid == [params]

    def test_deduplication_on_small_base(self):
        """Small base + large pct can produce duplicate ints after rounding — must dedup."""
        params = {"fast": 2}  # 2 * 0.80=1.6→2, 2*0.60=1.2→2 (floored), collisions likely
        grid = build_param_grid(params, pct=0.20, steps=2, min_val=2)
        vals = [g["fast"] for g in grid]
        assert len(vals) == len(set(vals)), f"Duplicates found: {vals}"




# ---------------------------------------------------------------------------
# TestBuildParamGridEdgeCases (Task 7)
# ---------------------------------------------------------------------------

class TestBuildParamGridEdgeCases:
    """Edge cases requested in the contributor task list."""

    def test_param_at_floor_value_one(self):
        """
        Strategy with params={"fast": 1} — at floor.
        With min_val=2, all *generated* values are clamped to min_val,
        but the base value (1) is preserved as-is via the "ensure base
        is present" guarantee. Verify the base appears and that generated
        (non-base) values respect the floor.
        """
        params = {"fast": 1}
        grid = build_param_grid(params, pct=0.20, steps=2, min_val=2)
        vals = [g["fast"] for g in grid]
        # Base value must be present
        assert 1 in vals, "Base value 1 must appear in grid"
        # All non-base values should be >= min_val
        non_base = [v for v in vals if v != 1]
        for v in non_base:
            assert v >= 2, f"Non-base value {v} is below min_val=2"

    def test_only_boolean_param_no_sweep(self):
        """
        Params containing only a boolean — no sweep should happen.
        Booleans are not numeric for sweep purposes, so the grid should
        contain exactly the base params dict unchanged.
        """
        params = {"use_filter": True}
        grid = build_param_grid(params, pct=0.20, steps=2, min_val=2)
        assert len(grid) == 1, f"Expected 1 grid point, got {len(grid)}"
        assert grid[0] == params
        assert grid[0]["use_filter"] is True

    def test_boolean_with_numeric_only_numeric_varies(self):
        """
        Mixed params: one boolean + one numeric. Only the numeric key should
        be varied; the boolean should pass through unchanged in every variant.
        """
        params = {"fast": 20, "use_filter": True}
        grid = build_param_grid(params, pct=0.20, steps=2, min_val=2)
        # Should have 5 variants (only "fast" varies)
        assert len(grid) == 5, f"Expected 5 grid points, got {len(grid)}"
        for g in grid:
            assert g["use_filter"] is True, "Boolean param was modified"

    def test_three_params_cartesian_125_points(self):
        """
        Cartesian product with 3 numeric params at steps=2 should produce
        5 × 5 × 5 = 125 grid points. Confirm dedup still works (no duplicates).
        """
        params = {"fast": 20, "slow": 50, "signal": 10}
        grid = build_param_grid(params, pct=0.20, steps=2, min_val=2)
        assert len(grid) == 125, f"Expected 125 grid points, got {len(grid)}"
        # Check no duplicate param combinations exist
        seen = set()
        for g in grid:
            key = (g["fast"], g["slow"], g["signal"])
            assert key not in seen, f"Duplicate grid point: {key}"
            seen.add(key)

    def test_three_params_base_present(self):
        """
        With 3 params, the base combination (20, 50, 10) must appear
        exactly once in the 125-point grid.
        """
        params = {"fast": 20, "slow": 50, "signal": 10}
        grid = build_param_grid(params, pct=0.20, steps=2, min_val=2)
        base_count = sum(
            1 for g in grid
            if g["fast"] == 20 and g["slow"] == 50 and g["signal"] == 10
        )
        assert base_count == 1, f"Base appeared {base_count} times, expected 1"

    def test_float_param_not_rounded_to_int(self):
        """
        Float params should remain floats after the sweep, not get rounded
        to integers.
        """
        params = {"threshold": 0.5}
        grid = build_param_grid(params, pct=0.20, steps=2, min_val=0.1)
        for g in grid:
            assert isinstance(g["threshold"], float), f"Expected float, got {type(g['threshold'])}"

    def test_single_step_three_values(self):
        """
        steps=1 should produce 3 values per param: base-pct, base, base+pct.
        """
        params = {"fast": 100}
        grid = build_param_grid(params, pct=0.10, steps=1, min_val=2)
        vals = sorted(g["fast"] for g in grid)
        assert vals == [90, 100, 110], f"Got {vals}"

# ---------------------------------------------------------------------------
# TestLabelForParams
# ---------------------------------------------------------------------------

class TestLabelForParams:

    def test_identical_returns_base(self):
        base = {"fast": 20, "slow": 50}
        assert label_for_params(base, dict(base)) == "(base)"

    def test_one_diff(self):
        base = {"fast": 20, "slow": 50}
        variant = {"fast": 16, "slow": 50}
        label = label_for_params(base, variant)
        assert label == "fast=16"

    def test_multiple_diffs(self):
        base = {"fast": 20, "slow": 50}
        variant = {"fast": 16, "slow": 40}
        label = label_for_params(base, variant)
        # Both changed keys must appear; order matches dict iteration order
        assert "fast=16" in label
        assert "slow=40" in label


# ---------------------------------------------------------------------------
# TestNoRegressionDefaultPath
# ---------------------------------------------------------------------------

class TestNoRegressionDefaultPath:

    def test_single_variant_when_disabled(self):
        """
        When sensitivity_sweep_enabled=False, the main.py gate produces
        param_variants = [base_params] — length 1, same object as base_params.
        """
        base_params = {"fast": 20, "slow": 50}
        with patch.dict(CONFIG, {"sensitivity_sweep_enabled": False}):
            param_variants = (
                build_param_grid(base_params)
                if is_sweep_enabled() and base_params
                else [base_params]
            )
        assert len(param_variants) == 1
        assert param_variants[0] is base_params


# ---------------------------------------------------------------------------
# generate_sensitivity_report grouping (#435)
# ---------------------------------------------------------------------------

def _sens_result(portfolio, stop, label, pnl, stop_suffix=None):
    """Result dict shaped like main.py's (#434): metadata + display name."""
    name = f"Strat [{label}]" + (f" w/ {stop_suffix}" if stop_suffix else "")
    return {"Strategy": name, "Portfolio": portfolio, "base_strategy": "Strat",
            "param_label": label, "stop_label": stop, "pnl_percent": pnl,
            "sharpe_ratio": 1.0, "max_drawdown": 0.1, "mc_score": 50}


def _run_report(results):
    import io
    from contextlib import redirect_stdout
    from helpers import summary
    buf = io.StringIO()
    with patch.dict(CONFIG, {"sensitivity_sweep_enabled": True}), redirect_stdout(buf):
        summary.generate_sensitivity_report(results, "run1")
    return buf.getvalue()


class TestSensitivityReportGrouping:
    LABELS = ["(base)", "fast=8", "fast=9", "fast=11", "fast=12"]

    def _grid(self):
        res = []
        for port in ("Port A", "Port B"):
            for stop, suffix in (("", None), ("5% SL", "5% SL")):
                for i, lab in enumerate(self.LABELS):
                    # Port A profitable everywhere; Port B never profitable.
                    pnl = 0.1 + i / 100 if port == "Port A" else -0.1
                    res.append(_sens_result(port, stop, lab, pnl, suffix))
        return res

    def test_four_groups_of_five_with_labels_and_base_marker(self):
        out = _run_report(self._grid())
        assert out.count("Strat | Port") == 4
        assert "Strat | Port A\n" in out and "Strat | Port A | 5% SL" in out
        assert "Strat | Port B | 5% SL" in out
        assert out.count(" <-- base") == 4
        assert out.count("fast=8 ") == 4
        assert "w/ 5% SL" not in out and "fast=8]" not in out  # no mis-parsed labels
        assert out.count("(5/5)") == 2          # Port A groups only
        assert out.count("FRAGILE") == 2        # Port B groups, not diluted by Port A

    def test_zero_trade_variants_count_as_not_profitable(self):
        from helpers.result_status import make_stub_result
        meta = lambda lab: {"base_strategy": "Strat", "param_label": lab, "stop_label": ""}
        res = [_sens_result("P", "", "(base)", 0.3)] + [
            make_stub_result(f"Strat [{lab}]", "P", "no_trades", meta=meta(lab))
            for lab in ("fast=8", "fast=9", "fast=11")]
        out = _run_report(res)
        assert "FRAGILE" in out and "25%" in out
        assert out.count("[0 trades]") == 3

    def test_legacy_results_without_metadata_still_render(self):
        res = [{"Strategy": n, "Portfolio": "P", "pnl_percent": p}
               for n, p in (("S [(base)]", 0.2), ("S [fast=8]", 0.1), ("S [fast=9]", -0.1))]
        out = _run_report(res)
        assert "S | P" in out and "(2/3)" in out
        assert out.count(" <-- base") == 1 and "fast=8" in out
