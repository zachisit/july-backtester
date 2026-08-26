# tests/test_guard_helpers.py
"""
Tests for the two guard helpers.

Both exist to make a class of silent bug hard to write. The tests are therefore
written as INVARIANTS ("a spike cannot lift its own baseline", "a ratio is
unchanged by a split") rather than behaviour checks - behaviour-only tests are
what let this class through repeatedly in the first place.
"""

import numpy as np
import pandas as pd
import pytest

from helpers.corporate_actions import (
    ADJUSTED_TO_TODAY,
    AS_TRADED,
    adjust_per_share,
    split_adjustment_factor,
    validate_fundamentals_basis,
)
from helpers.rolling import spike_ratio, trailing_mean


# ---------------------------------------------------------------------------
# trailing_mean / spike_ratio
# ---------------------------------------------------------------------------

class TestTrailingMean:

    def test_excludes_current_bar(self):
        s = pd.Series([10.0, 10.0, 10.0, 100.0])
        # Baseline at the spike bar must be the prior three 10s, not 10-10-100.
        assert trailing_mean(s, 3).iloc[3] == pytest.approx(10.0)

    def test_inclusive_form_is_contaminated(self):
        """Documents the defect this module exists to prevent."""
        s = pd.Series([10.0, 10.0, 10.0, 100.0])
        assert s.rolling(3).mean().iloc[3] == pytest.approx(40.0)  # 10,10,100
        assert trailing_mean(s, 3).iloc[3] == pytest.approx(10.0)

    def test_spike_cannot_inflate_its_own_baseline(self):
        """THE invariant: a bar's measured multiple must not depend on itself.

        Inclusive: 100 / mean(10,10,100) = 2.5x — a 10x spike reads as 2.5x.
        Exclusive: 100 / mean(10,10,10)  = 10x.
        """
        s = pd.Series([10.0, 10.0, 10.0, 100.0])
        assert spike_ratio(s, 3).iloc[3] == pytest.approx(10.0)
        inclusive = s.iloc[3] / s.rolling(3).mean().iloc[3]
        assert inclusive == pytest.approx(2.5)

    def test_threshold_means_what_it_says(self):
        """A '2.5x average' rule must trigger at 2.5x, not 3.0x.

        The real-world case: with an inclusive 10-bar window, `vol > 2.5 * avg`
        is algebraically `vol > 3.0x` the prior nine bars, so a genuine 2.6x
        spike is silently missed.
        """
        s = pd.Series([100.0] * 9 + [260.0])   # exactly 2.6x the prior nine
        assert spike_ratio(s, 9).iloc[9] == pytest.approx(2.6)
        assert spike_ratio(s, 9).iloc[9] > 2.5          # correctly fires
        assert not (s.iloc[9] > 2.5 * s.rolling(9).mean().iloc[9])  # inclusive misses it

    def test_warmup_is_nan_not_self_reference(self):
        """min_periods=1 would make bar 0 average against itself, manufacturing
        a spurious spike at the start of every symbol."""
        s = pd.Series([10.0, 20.0, 30.0, 40.0])
        tm = trailing_mean(s, 3)
        assert tm.iloc[:3].isna().all()
        assert tm.iloc[3] == pytest.approx(20.0)

    def test_exclude_current_false_is_a_plain_moving_average(self):
        s = pd.Series([10.0, 10.0, 10.0, 100.0])
        pd.testing.assert_series_equal(
            trailing_mean(s, 3, exclude_current=False), s.rolling(3).mean()
        )

    def test_zero_baseline_yields_nan_not_inf(self):
        s = pd.Series([0.0, 0.0, 0.0, 50.0])
        assert np.isnan(spike_ratio(s, 3).iloc[3])

    def test_rejects_bad_window(self):
        with pytest.raises(ValueError, match="window must be"):
            trailing_mean(pd.Series([1.0]), 0)


# ---------------------------------------------------------------------------
# split_adjustment_factor
# ---------------------------------------------------------------------------

SPLIT_2026 = [("2026-06-12", 10.0)]


class TestSplitAdjustment:

    def test_future_split_applies_under_adjusted_to_today(self):
        """The KLAC case. Prices rebase to today's shares, so a 2026 split
        reaches back and affects a 2024 P/E."""
        f = split_adjustment_factor(SPLIT_2026, "2024-09-30",
                                    price_adjustment=ADJUSTED_TO_TODAY)
        assert f == pytest.approx(10.0)

    def test_future_split_ignored_under_as_traded(self):
        """Nominal prices: a split that has not executed affects neither side."""
        f = split_adjustment_factor(SPLIT_2026, "2024-09-30", as_of="2024-09-30",
                                    price_adjustment=AS_TRADED)
        assert f == pytest.approx(1.0)

    def test_the_two_conventions_disagree_and_that_is_the_point(self):
        """This divergence is the whole reason the argument was unresolvable by
        reading — the answer depends on a config value neither side had checked."""
        args = (SPLIT_2026, "2024-09-30")
        a = split_adjustment_factor(*args, price_adjustment=ADJUSTED_TO_TODAY)
        b = split_adjustment_factor(*args, as_of="2024-09-30",
                                    price_adjustment=AS_TRADED)
        assert a != b

    def test_in_window_split_applies_under_both(self):
        """A split between period end and evaluation date is a real mismatch
        either way — the NVDA/CTAS/WMT case."""
        splits = [("2024-06-10", 10.0)]
        assert split_adjustment_factor(splits, "2024-04-30", as_of="2024-09-30",
                                       price_adjustment=AS_TRADED) == pytest.approx(10.0)
        assert split_adjustment_factor(splits, "2024-04-30",
                                       price_adjustment=ADJUSTED_TO_TODAY) == pytest.approx(10.0)

    def test_split_before_period_end_is_already_reflected(self):
        assert split_adjustment_factor([("2020-01-01", 4.0)], "2024-09-30") == 1.0

    def test_multiple_splits_compound(self):
        splits = [("2024-06-10", 10.0), ("2025-06-10", 2.0)]
        assert split_adjustment_factor(splits, "2024-01-31") == pytest.approx(20.0)

    def test_no_splits_is_identity(self):
        assert split_adjustment_factor([], "2024-09-30") == 1.0

    def test_unknown_convention_raises(self):
        with pytest.raises(ValueError, match="unknown price_adjustment"):
            split_adjustment_factor(SPLIT_2026, "2024-09-30", price_adjustment="wat")

    def test_pe_is_invariant_once_both_sides_share_a_basis(self):
        """THE invariant. A split must not change a P/E — only the basis both
        sides are expressed in. Unadjusted, the same company reads 10x cheaper.
        """
        true_price, true_eps = 750.0, 20.0          # as traded, pre-split
        adj_price = true_price / 10.0               # vendor rebased to today
        raw_eps = true_eps                          # as filed, never restated

        wrong_pe = adj_price / raw_eps
        f = split_adjustment_factor(SPLIT_2026, "2024-09-30",
                                    price_adjustment=ADJUSTED_TO_TODAY)
        right_pe = adj_price / (raw_eps / f)

        assert wrong_pe == pytest.approx(3.75)
        assert right_pe == pytest.approx(true_price / true_eps)   # 37.5
        assert right_pe == pytest.approx(wrong_pe * 10)

    def test_adjust_per_share_vectorises(self):
        ends = pd.to_datetime(["2024-01-31", "2024-04-30", "2026-07-31"])
        eps = pd.Series([1.0, 2.0, 3.0], index=[0, 1, 2])
        out = adjust_per_share(eps, ends, SPLIT_2026,
                               price_adjustment=ADJUSTED_TO_TODAY)
        assert out.iloc[0] == pytest.approx(0.1)   # pre-split -> rescaled
        assert out.iloc[1] == pytest.approx(0.2)
        assert out.iloc[2] == pytest.approx(3.0)   # post-split -> untouched


# ---------------------------------------------------------------------------
# validate_fundamentals_basis
# ---------------------------------------------------------------------------

class TestValidator:

    def test_flags_the_total_return_requirement(self):
        w = validate_fundamentals_basis({"price_adjustment": ADJUSTED_TO_TODAY})
        assert any("after the backtest window" in m for m in w)

    def test_flags_the_as_traded_requirement(self):
        w = validate_fundamentals_basis({"price_adjustment": AS_TRADED})
        assert any("INSIDE the evaluation window" in m for m in w)

    def test_absolute_price_floor_warning_only_under_rebasing(self):
        """Ratios survive rebasing; absolute levels do not."""
        w = validate_fundamentals_basis(
            {"price_adjustment": ADJUSTED_TO_TODAY}, uses_absolute_price_floor=True)
        assert any("NOT scale-invariant" in m for m in w)

        w2 = validate_fundamentals_basis(
            {"price_adjustment": AS_TRADED}, uses_absolute_price_floor=True)
        assert not any("NOT scale-invariant" in m for m in w2)

    def test_silent_when_no_fundamentals_used(self):
        assert validate_fundamentals_basis(
            {"price_adjustment": ADJUSTED_TO_TODAY}, uses_per_share_ratio=False) == []
