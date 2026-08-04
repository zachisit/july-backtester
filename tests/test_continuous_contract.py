# tests/test_continuous_contract.py
"""
Unit tests for helpers/continuous_contract.py — back-adjusted futures stitching.

  TestRollInference   — volume-crossover roll date detection
  TestBuildContinuous — panama (additive) and ratio back-adjustment remove the seam
  TestValidate        — flags empty/unadjusted/duplicate/negative series
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers import continuous_contract as cc

_DATES = pd.bdate_range("2023-01-02", periods=8)


def _frame(dates, closes, vols):
    closes = np.asarray(closes, dtype=float)
    return pd.DataFrame({"Open": closes, "High": closes, "Low": closes,
                         "Close": closes, "Volume": np.asarray(vols, dtype=float)}, index=dates)


def _front():
    return _frame(_DATES[0:5], [100, 101, 102, 103, 104], [10, 10, 10, 5, 5])


def _back():
    # trades at a large premium (contango) and overlaps front on d3,d4
    return _frame(_DATES[3:8], [150, 151, 152, 153, 154], [1, 20, 20, 20, 20])


class TestRollInference:
    def test_volume_crossover(self):
        rolls = cc.infer_roll_dates_by_volume([_front(), _back()])
        assert rolls == [_DATES[4]]  # back volume (20) first exceeds front (5) on d4

    def test_no_overlap_falls_back_to_front_last(self):
        f = _frame(_DATES[0:3], [100, 101, 102], [10, 10, 10])
        b = _frame(_DATES[4:7], [200, 201, 202], [10, 10, 10])
        assert cc.infer_roll_dates_by_volume([f, b]) == [_DATES[2]]


class TestBuildContinuous:
    def test_panama_removes_seam(self):
        out = cc.build_continuous([_front(), _back()], method=cc.PANAMA, roll_dates=[_DATES[4]])
        # Back (most recent) segment keeps real prices; front is shifted up by gap (=47).
        assert out.loc[_DATES[4], "Close"] == pytest.approx(151.0)   # back real
        assert out.loc[_DATES[3], "Close"] == pytest.approx(150.0)   # front 103 + 47
        assert out.loc[_DATES[0], "Close"] == pytest.approx(147.0)   # front 100 + 47
        # Seam is continuous (tiny return), so validation passes.
        ok, issues = cc.validate_continuous(out)
        assert ok, issues

    def test_ratio_preserves_returns(self):
        out = cc.build_continuous([_front(), _back()], method=cc.RATIO, roll_dates=[_DATES[4]])
        # ratio = back/front at roll = 151/104; front d3 (103) * ratio
        ratio = 151.0 / 104.0
        assert out.loc[_DATES[4], "Close"] == pytest.approx(151.0)
        assert out.loc[_DATES[3], "Close"] == pytest.approx(103.0 * ratio)
        ok, _ = cc.validate_continuous(out)
        assert ok

    def test_single_frame_passthrough(self):
        f = _front()
        out = cc.build_continuous([f])
        pd.testing.assert_frame_equal(out, f)

    def test_index_sorted_unique(self):
        out = cc.build_continuous([_front(), _back()], roll_dates=[_DATES[4]])
        assert out.index.is_monotonic_increasing
        assert not out.index.duplicated().any()

    def test_bad_roll_dates_length_raises(self):
        with pytest.raises(ValueError):
            cc.build_continuous([_front(), _back()], roll_dates=[])


class TestValidate:
    def test_empty(self):
        ok, issues = cc.validate_continuous(pd.DataFrame())
        assert not ok and issues

    def test_unadjusted_concat_flags_jump(self):
        # Naive concat leaves the ~47pt roll gap -> a >20% close-to-close jump.
        f, b = _front(), _back()
        naive = pd.concat([f, b[b.index >= _DATES[4]]])
        naive = naive.loc[~naive.index.duplicated(keep="last")].sort_index()
        ok, issues = cc.validate_continuous(naive)
        assert not ok
        assert any("jump" in i for i in issues)

    def test_negative_prices_flagged(self):
        bad = _front().copy()
        bad.loc[_DATES[2], "Close"] = -5
        ok, issues = cc.validate_continuous(bad)
        assert not ok
        assert any("non-positive" in i for i in issues)
