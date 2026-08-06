"""
Tests for get_bars_per_day_exact() and the ADV window it sizes (issue #268).

Background
----------
#264/#265 fixed the 20-day average-daily-volume calculation to span 20 real
trading days on intraday data. That fix rests on the identity

    mean(20*bpd bars) * bpd == sum(window)/(20*bpd) * bpd == sum(window)/20

which is true daily ADV -- but ONLY while the window genuinely spans 20 days.
`get_bars_per_day()` truncates (int()), so any multiplier that does not divide
the session length evenly lost the fraction, corrupting both the window width
and the rescale factor:

    H x1 / MIN x60 -> int(6.5)   == 6     (-7.7%)
    H x2           -> int(3.25)  == 3     (-7.7%)
    H x4           -> int(1.625) == 1     (-38.5%)

Left #264 closed only for D/W/M and MIN 5/15/30.

These tests are pure arithmetic -- no I/O, no network, no randomness.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.timeframe_utils import (  # noqa: E402
    get_bars_per_day,
    get_bars_per_day_exact,
)


def _window(config):
    """
    Reproduce the ADV window sizing in helpers/portfolio_simulations.py.

    This is a REIMPLEMENTATION of the production expression (which is a local
    inside run_portfolio_simulation and so cannot be imported). Tests built on
    it verify the arithmetic is right; they cannot detect the engine drifting
    away from it. TestAdvWindowSpansTwentyDays.
    test_engine_end_to_end_uses_exact_bars_per_day runs the real simulation
    and is what actually pins the engine.
    """
    return max(1, round(20 * get_bars_per_day_exact(config)))


class TestExactBarsPerDay:
    """get_bars_per_day_exact() keeps the fraction get_bars_per_day() drops."""

    @pytest.mark.parametrize(
        "config, expected",
        [
            ({"timeframe": "D"}, 1.0),
            ({"timeframe": "D", "timeframe_multiplier": 1}, 1.0),
            ({"timeframe": "W"}, 1.0),
            ({"timeframe": "M"}, 1.0),
            ({"timeframe": "MIN", "timeframe_multiplier": 5}, 78.0),
            ({"timeframe": "MIN", "timeframe_multiplier": 15}, 26.0),
            ({"timeframe": "MIN", "timeframe_multiplier": 30}, 13.0),
            # The cases get_bars_per_day() truncated:
            ({"timeframe": "MIN", "timeframe_multiplier": 60}, 6.5),
            ({"timeframe": "H", "timeframe_multiplier": 1}, 6.5),
            ({"timeframe": "H", "timeframe_multiplier": 2}, 3.25),
            ({"timeframe": "H", "timeframe_multiplier": 4}, 1.625),
        ],
    )
    def test_exact_values(self, config, expected):
        assert get_bars_per_day_exact(config) == pytest.approx(expected)

    def test_honours_trading_hours_per_day(self):
        """A 24h futures session yields 24 one-hour bars, not 6.5."""
        cfg = {"timeframe": "H", "timeframe_multiplier": 1,
               "trading_hours_per_day": 24}
        assert get_bars_per_day_exact(cfg) == pytest.approx(24.0)

    def test_bar_spanning_more_than_a_session_is_below_one(self):
        """
        A bar longer than the session legitimately carries more than one
        day's volume, so the rescale factor must be < 1 (scale DOWN), not
        clamped up to 1 the way the bar-count version has to.
        """
        cfg = {"timeframe": "H", "timeframe_multiplier": 13}  # 6.5/13
        assert get_bars_per_day_exact(cfg) == pytest.approx(0.5)
        assert get_bars_per_day(cfg) == 1  # count version clamps

    @pytest.mark.parametrize("timeframe", ["D", "W", "M", "H", "MIN"])
    def test_rejects_non_positive_multiplier(self, timeframe):
        with pytest.raises(ValueError, match="timeframe_multiplier"):
            get_bars_per_day_exact(
                {"timeframe": timeframe, "timeframe_multiplier": 0}
            )

    def test_rejects_non_positive_session_length(self):
        """
        A zero-length session would drive the ADV rescale to 0.0, making the
        max_pct_adv cap silently reject every trade. Fail loudly instead.
        """
        with pytest.raises(ValueError, match="trading_hours_per_day"):
            get_bars_per_day_exact(
                {"timeframe": "MIN", "timeframe_multiplier": 5,
                 "trading_hours_per_day": 0}
            )

    def test_daily_ignores_session_length(self):
        """D/W/M never read the session length, so a bogus value can't break them."""
        assert get_bars_per_day_exact(
            {"timeframe": "D", "trading_hours_per_day": 0}
        ) == 1.0

    def test_rejects_unsupported_timeframe(self):
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            get_bars_per_day_exact({"timeframe": "Q"})

    def test_unsupported_timeframe_reported_before_session_length(self):
        """
        An unsupported timeframe must report itself as such even when another
        key is also invalid -- otherwise a user debugging `timeframe: "Q"`
        gets pointed at trading_hours_per_day instead.
        """
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            get_bars_per_day_exact(
                {"timeframe": "Q", "trading_hours_per_day": 0}
            )


class TestBarsPerDayDelegation:
    """The integer version stays byte-for-byte what it was, via the exact one."""

    @pytest.mark.parametrize(
        "config, expected",
        [
            ({"timeframe": "D"}, 1),
            ({"timeframe": "W"}, 1),
            ({"timeframe": "M"}, 1),
            ({"timeframe": "MIN", "timeframe_multiplier": 5}, 78),
            ({"timeframe": "MIN", "timeframe_multiplier": 15}, 26),
            ({"timeframe": "MIN", "timeframe_multiplier": 30}, 13),
            ({"timeframe": "MIN", "timeframe_multiplier": 60}, 6),
            ({"timeframe": "H", "timeframe_multiplier": 1}, 6),
            ({"timeframe": "H", "timeframe_multiplier": 2}, 3),
            ({"timeframe": "H", "timeframe_multiplier": 4}, 1),
        ],
    )
    def test_unchanged_after_refactor(self, config, expected):
        assert get_bars_per_day(config) == expected

    def test_is_truncation_of_exact(self):
        for mult in (1, 2, 3, 4, 5, 7, 13):
            cfg = {"timeframe": "H", "timeframe_multiplier": mult}
            assert get_bars_per_day(cfg) == max(
                1, int(get_bars_per_day_exact(cfg))
            )

    def test_inherits_multiplier_validation(self):
        with pytest.raises(ValueError, match="timeframe_multiplier"):
            get_bars_per_day({"timeframe": "MIN", "timeframe_multiplier": 0})

    def test_inherits_session_length_validation(self):
        """
        Behaviour change from #268: delegating to the exact helper means the
        int wrapper now raises on a zero-length session where it previously
        returned 1. Pinned here because it is a public-API contract change.
        """
        with pytest.raises(ValueError, match="trading_hours_per_day"):
            get_bars_per_day(
                {"timeframe": "H", "timeframe_multiplier": 1,
                 "trading_hours_per_day": 0}
            )

    def test_inherits_unsupported_timeframe_validation(self):
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            get_bars_per_day({"timeframe": "Q"})


class TestAdvWindowSpansTwentyDays:
    """
    The whole point of the fix: the window must span ~20 sessions so that
    mean * bars_per_day == total volume / 20 == true daily ADV.
    """

    @pytest.mark.parametrize(
        "config",
        [
            {"timeframe": "D"},
            {"timeframe": "MIN", "timeframe_multiplier": 5},
            {"timeframe": "MIN", "timeframe_multiplier": 15},
            {"timeframe": "MIN", "timeframe_multiplier": 30},
            {"timeframe": "MIN", "timeframe_multiplier": 60},
            {"timeframe": "H", "timeframe_multiplier": 1},
            {"timeframe": "H", "timeframe_multiplier": 2},
            {"timeframe": "H", "timeframe_multiplier": 4},
            # 6 and 7 are the multipliers where 20*bpd lands far enough from
            # a whole number that round() and int() disagree (21.67 -> 22 vs
            # 21; 18.57 -> 19 vs 18), so they document why the formula rounds
            # rather than truncates. NOTE: this is a formula-level assertion
            # -- _window() below reimplements the production expression, so it
            # cannot detect a change to the engine itself. The engine binding
            # is pinned separately by
            # test_engine_end_to_end_uses_exact_bars_per_day.
            {"timeframe": "H", "timeframe_multiplier": 6},
            {"timeframe": "H", "timeframe_multiplier": 7},
        ],
    )
    def test_window_spans_twenty_days_within_tolerance(self, config):
        bpd = get_bars_per_day_exact(config)
        days_spanned = _window(config) / bpd
        assert days_spanned == pytest.approx(20.0, abs=0.5), (
            f"{config} spans {days_spanned:.2f} days, not ~20"
        )

    @pytest.mark.parametrize(
        "config, old_bpd, expected_min_improvement",
        [
            # (config, truncated bars-per-day, how much error the fix removes)
            ({"timeframe": "H", "timeframe_multiplier": 1}, 6, 0.05),
            ({"timeframe": "H", "timeframe_multiplier": 2}, 3, 0.05),
            ({"timeframe": "H", "timeframe_multiplier": 4}, 1, 0.30),
        ],
    )
    def test_fix_beats_the_truncated_window(
        self, config, old_bpd, expected_min_improvement
    ):
        """
        Regression guard: reproduces the pre-fix window and asserts the new
        one is materially closer to a true 20-day span.
        """
        bpd = get_bars_per_day_exact(config)

        old_days = (20 * old_bpd) / bpd
        new_days = _window(config) / bpd

        old_error = abs(old_days - 20.0) / 20.0
        new_error = abs(new_days - 20.0) / 20.0

        assert old_error >= expected_min_improvement, (
            "pre-fix error smaller than expected; test premise is stale"
        )
        assert new_error < 0.02
        assert new_error < old_error

    def test_daily_window_is_exactly_twenty_bars(self):
        """
        Golden-master invariant: daily runs must produce window == 20 and a
        x1.0 rescale, i.e. arithmetically identical to the pre-#265 code.
        """
        for cfg in ({"timeframe": "D"}, {"timeframe": "W"}, {"timeframe": "M"}):
            assert _window(cfg) == 20
            assert get_bars_per_day_exact(cfg) == 1.0

    def test_engine_end_to_end_uses_exact_bars_per_day(self):
        """
        Pins the ENGINE, not just the arithmetic.

        The invariant tests above reimplement the window formula, so they
        would all still pass if helpers/portfolio_simulations.py were
        reverted to the truncated get_bars_per_day(). This runs the real
        simulation on 4H bars, where the two helpers disagree most:

            exact:     window round(20*1.625) = 32 bars, ADV = V * 1.625
            truncated: window 20*1            = 20 bars, ADV = V * 1.000

        With V = 20,000/bar and max_pct_adv = 5%, the cap is 1,625 shares
        under the fix and 1,000 shares under the bug -- so this test fails
        if the production line regresses.
        """
        from unittest.mock import patch

        import pandas as pd

        from helpers.portfolio_simulations import run_portfolio_simulation

        per_bar_volume = 20_000.0
        price = 1.0
        n_bars = 80
        entry_idx = 60  # >32 bars of history behind the window

        idx = pd.DatetimeIndex(
            pd.date_range("2024-01-02", periods=n_bars, freq="4h")
        )
        idx.name = "Datetime"
        df = pd.DataFrame(
            {
                "Open": price, "High": price, "Low": price, "Close": price,
                "Volume": per_bar_volume,
            },
            index=idx,
        )

        signal = pd.Series(0, index=idx)
        signal.iloc[entry_idx] = 1  # enter, never exit -> closed by end-of-run MTM

        test_config = {
            "timeframe": "H",
            "timeframe_multiplier": 4,
            "trading_hours_per_day": 6.5,
            "execution_time": "close",
            "slippage_pct": 0.0,
            "commission_per_share": 0.0,
            "max_pct_adv": 0.05,
            "volume_impact_coeff": 0.0,
            "risk_free_rate": 0.05,
            "htb_rate_annual": 0.0,
            "position_sizing_method": "fixed",
        }

        with patch.dict("config.CONFIG", test_config):
            result = run_portfolio_simulation(
                portfolio_data={"TEST": df},
                signals={"TEST": signal},
                initial_capital=100_000.0,   # asks for 10,000 shares at $1
                allocation_pct=0.10,         # -> the cap is what binds
                spy_df=None,
                vix_df=None,
                tnx_df=None,
                stop_config={"type": "none"},
            )

        assert result is not None
        trade = result["trade_log"][0]

        exact_cap = per_bar_volume * 1.625 * 0.05      # 1,625
        truncated_cap = per_bar_volume * 1.0 * 0.05    # 1,000

        assert trade["Shares"] == pytest.approx(exact_cap, rel=1e-6), (
            f"expected the exact-bars-per-day cap ({exact_cap}), got "
            f"{trade['Shares']} -- {truncated_cap} means the engine "
            f"regressed to the truncated get_bars_per_day()"
        )

    def test_true_daily_adv_recovered_on_four_hour_bars(self):
        """
        End-to-end arithmetic on the worst case (4H, previously -38.5%):
        constant per-bar volume => recovered ADV == per-bar * true bpd.
        """
        import numpy as np
        import pandas as pd

        cfg = {"timeframe": "H", "timeframe_multiplier": 4}
        bpd = get_bars_per_day_exact(cfg)
        per_bar_volume = 20_000.0

        n = 400
        series = pd.Series(
            np.full(n, per_bar_volume),
            index=pd.date_range("2024-01-01", periods=n, freq="4h"),
        )

        window = _window(cfg)
        per_bar_avg = series.rolling(window=window, min_periods=1).mean().iloc[-1]

        recovered = per_bar_avg * bpd
        expected = per_bar_volume * bpd  # 20,000 * 1.625 == 32,500/day

        assert recovered == pytest.approx(expected)

        # The truncated path reported one bar's volume as a whole day's.
        bugged = per_bar_avg * 1
        assert bugged == pytest.approx(20_000.0)
        assert recovered / bugged == pytest.approx(1.625)
