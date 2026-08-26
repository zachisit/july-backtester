# tests/test_guard_helpers.py
"""
Tests for the two guard helpers.

Both exist to make a class of silent bug hard to write. The tests are therefore
written as INVARIANTS ("a spike cannot lift its own baseline", "a ratio is
unchanged by a split") rather than behaviour checks - behaviour-only tests are
what let this class through repeatedly in the first place.
"""

import logging

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
        # Pin both values, not just `a != b` — inequality alone passes even if the
        # AS_TRADED branch returned 0.0, 3.7, or any other wrong number.
        assert a == pytest.approx(10.0)
        assert b == pytest.approx(1.0)

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


# ---------------------------------------------------------------------------
# Branches a QA pass found unpinned: both date-boundary operators survived
# mutation (<= -> < and > -> >=) with the whole suite still green, and the
# as_of=None path under AS_TRADED had no coverage at all — which is how it
# shipped returning a silent 1.0.
# ---------------------------------------------------------------------------

class TestSplitBoundariesAndGuards:

    def test_split_executing_on_period_end_is_already_reflected(self):
        """Pins `exec_date <= period_end`. The as-filed weighted-average share
        count for a period already reflects a split on its final day."""
        assert split_adjustment_factor(
            [("2024-09-30", 10.0)], "2024-09-30") == pytest.approx(1.0)

    def test_split_executing_one_day_after_period_end_applies(self):
        """The other side of the same boundary."""
        assert split_adjustment_factor(
            [("2024-10-01", 10.0)], "2024-09-30") == pytest.approx(10.0)

    def test_split_executing_exactly_on_as_of_has_executed(self):
        """Pins `exec_date > as_of`. A split is effective on its execution date,
        so as_of == exec_date must apply it, not skip it."""
        assert split_adjustment_factor(
            [("2024-06-10", 10.0)], "2024-04-30", as_of="2024-06-10",
            price_adjustment=AS_TRADED) == pytest.approx(10.0)

    def test_split_executing_one_day_after_as_of_has_not(self):
        assert split_adjustment_factor(
            [("2024-06-11", 10.0)], "2024-04-30", as_of="2024-06-10",
            price_adjustment=AS_TRADED) == pytest.approx(1.0)

    def test_as_traded_without_as_of_raises_rather_than_silently_skipping(self):
        """The defect this class exists for. Returning 1.0 here left a real
        in-window split unadjusted with no error and no log line — the same
        silent-wrong-answer shape the module was written to prevent."""
        with pytest.raises(ValueError, match="as_of is required"):
            split_adjustment_factor([("2024-06-10", 10.0)], "2024-04-30",
                                    price_adjustment=AS_TRADED)

    def test_as_of_not_required_under_rebasing(self):
        """Only AS_TRADED needs it; the rebased price side carries every split."""
        assert split_adjustment_factor(
            SPLIT_2026, "2024-09-30",
            price_adjustment=ADJUSTED_TO_TODAY) == pytest.approx(10.0)

    def test_reverse_split_is_valid_and_shrinks_the_factor(self):
        """A 1-for-10 is a ratio of 0.1, not an error. EPS scales up, not down."""
        f = split_adjustment_factor([("2025-01-01", 0.1)], "2024-09-30")
        assert f == pytest.approx(0.1)
        eps = pd.Series([2.0])
        out = adjust_per_share(eps, ["2024-09-30"], [("2025-01-01", 0.1)])
        assert out.iloc[0] == pytest.approx(20.0)

    @pytest.mark.parametrize("bad", [0.0, -2.0, float("nan"), float("inf")])
    def test_non_positive_or_infinite_ratio_raises(self, bad):
        """A vendor zero used to divide EPS to inf, giving a P/E of 0 — which
        sends the affected name to the TOP of a lowest-P/E ranking."""
        with pytest.raises(ValueError, match="positive finite"):
            split_adjustment_factor([("2025-01-01", bad)], "2024-09-30")

    def test_tz_aware_period_end_does_not_raise(self):
        """Provider indices in this project are UTC-aware; vendor split dates are
        naive calendar strings. Comparing them used to raise TypeError."""
        f = split_adjustment_factor(
            SPLIT_2026, pd.Timestamp("2024-09-30", tz="UTC"))
        assert f == pytest.approx(10.0)

    def test_generator_of_splits_is_not_exhausted_after_the_first_period(self):
        """adjust_per_share calls the factor function once per period end; a
        one-shot iterable used to be spent after the first, leaving every later
        period silently unadjusted."""
        gen = (x for x in [("2026-06-12", 10.0)])
        out = adjust_per_share(pd.Series([1.0, 2.0]),
                               ["2024-01-31", "2024-04-30"], gen)
        assert list(out) == pytest.approx([0.1, 0.2])

    def test_adjust_per_share_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="align positionally"):
            adjust_per_share(pd.Series([1.0, 2.0]), ["2024-01-31"], SPLIT_2026)


class TestTrailingMeanGuards:

    def test_explicit_min_periods_counts_prior_bars(self):
        """min_periods=1 means one PRIOR bar, so index 0 stays NaN — no bar can
        average against itself even with a relaxed warm-up."""
        s = pd.Series([10.0, 20.0, 30.0, 40.0])
        out = trailing_mean(s, 3, min_periods=1)
        assert np.isnan(out.iloc[0])
        assert out.iloc[1] == pytest.approx(10.0)
        assert out.iloc[2] == pytest.approx(15.0)

    def test_min_periods_zero_rejected_not_silently_treated_as_unset(self):
        """`min_periods or window` swallowed 0 as falsy, silently applying the
        full window instead of the value the caller asked for."""
        with pytest.raises(ValueError, match="min_periods must be >= 1"):
            trailing_mean(pd.Series([1.0, 2.0, 3.0]), 3, min_periods=0)

    def test_negative_baseline_yields_nan_not_a_sign_flipped_ratio(self):
        out = spike_ratio(pd.Series([-5.0, -5.0, -5.0, 10.0]), 3)
        assert out.isna().all()

    def test_inclusive_multiple_is_k_times_n_minus_1_over_n_minus_k(self):
        """Pins the docstring arithmetic. For N=20, k=2.5 the inclusive form is
        2.714x the prior 19 bars — NOT kN/(N-1) = 2.632, a correction that omits
        the current bar's effect on the denominator."""
        n, k = 20, 2.5
        true_multiple = k * (n - 1) / (n - k)
        assert true_multiple == pytest.approx(2.7142857, abs=1e-6)

        # A bar at exactly that multiple sits exactly on the inclusive threshold.
        s = pd.Series([1.0] * (n - 1) + [true_multiple])
        inclusive_mean = s.rolling(n).mean().iloc[-1]
        assert s.iloc[-1] / inclusive_mean == pytest.approx(k)

        # ...while spike_ratio reports the honest number.
        assert spike_ratio(s, n - 1).iloc[-1] == pytest.approx(true_multiple)


class TestValidatorLogLevel:
    """The look-ahead message is the only genuine defect this validator reports,
    and its return value is freely ignorable - so the log line IS the enforcement.
    Emitting it at INFO under a default WARNING-level root logger made it
    invisible exactly when it mattered."""

    def test_lookahead_message_is_logged_at_warning(self, caplog):
        with caplog.at_level(logging.WARNING, logger="helpers.corporate_actions"):
            validate_fundamentals_basis(
                {"price_adjustment": ADJUSTED_TO_TODAY},
                uses_absolute_price_floor=True,
            )
        warned = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("NOT scale-invariant" in r.getMessage() for r in warned)

    def test_informational_messages_stay_below_warning(self, caplog):
        """Only the real defect escalates; the basis reminders are not alarms."""
        with caplog.at_level(logging.DEBUG, logger="helpers.corporate_actions"):
            validate_fundamentals_basis({"price_adjustment": ADJUSTED_TO_TODAY})
        assert caplog.records
        assert all(r.levelno < logging.WARNING for r in caplog.records)


class TestUnknownConventionIsRejectedEverywhere:
    """@shardul0701's review finding on #302.

    `split_adjustment_factor` raised on an unrecognised `price_adjustment` while
    `validate_fundamentals_basis` fell through its if/elif and returned `[]`. So
    a typo produced ZERO warnings from the one function whose entire job is to
    state the requirement rather than let it be assumed - F1's shape reached
    through a different door.

    It compounds downstream: `services/polygon_service.py` (3 sites) tests the
    same value with `== "total_return"` and falls back to `"false"`, so the same
    typo also silently requests as-traded prices from the vendor, while
    `helpers/config_validator.py` only checks the key is present, not its value.
    """

    BAD = ["Total_Return", "TOTAL_RETURN", "total return", "adjusted", "", "nonsense"]

    @pytest.mark.parametrize("bad", BAD)
    def test_validator_rejects_unknown_convention(self, bad):
        with pytest.raises(ValueError, match="unknown price_adjustment"):
            validate_fundamentals_basis({"price_adjustment": bad})

    @pytest.mark.parametrize("bad", BAD)
    def test_factor_rejects_the_same_values(self, bad):
        with pytest.raises(ValueError, match="unknown price_adjustment"):
            split_adjustment_factor(SPLIT_2026, "2024-09-30", price_adjustment=bad)

    @pytest.mark.parametrize("bad", BAD)
    def test_the_two_functions_agree_on_bad_input(self, bad):
        """THE invariant this fix exists for. The functions must not disagree
        about what is acceptable - that divergence IS the bug, independently of
        which behaviour is chosen."""
        def outcome(fn):
            try:
                fn()
                return "accepted"
            except ValueError:
                return "rejected"

        assert outcome(lambda: validate_fundamentals_basis({"price_adjustment": bad})) == \
               outcome(lambda: split_adjustment_factor(
                   SPLIT_2026, "2024-09-30", price_adjustment=bad))

    def test_typo_no_longer_silently_suppresses_the_lookahead_warning(self):
        """The concrete regression: a misspelled convention used to return [],
        swallowing even the absolute-price-floor warning."""
        with pytest.raises(ValueError, match="unknown price_adjustment"):
            validate_fundamentals_basis({"price_adjustment": "Total_Return"},
                                        uses_absolute_price_floor=True)

    def test_absent_key_still_defaults_and_warns(self):
        """An ABSENT key is not a typo - it defaults to ADJUSTED_TO_TODAY and
        must keep warning normally. Only unrecognised VALUES are rejected."""
        w = validate_fundamentals_basis({})
        assert any("after the backtest window" in m for m in w)

    def test_both_known_conventions_still_accepted(self):
        assert validate_fundamentals_basis({"price_adjustment": ADJUSTED_TO_TODAY})
        assert validate_fundamentals_basis({"price_adjustment": AS_TRADED})
