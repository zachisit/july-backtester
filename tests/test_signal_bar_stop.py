"""Tests for the ``signal_bar`` stop type — a structural stop anchored to the
signal bar's extreme rather than to a distance from the entry fill.

Covers the pure helper (helpers/instruments.signal_bar_stop_level) and the two
engine wiring sites (long entry and short entry) in
helpers/portfolio_simulations.py.
"""

import numpy as np
import pandas as pd
import pytest

from helpers import instruments as _inst
from helpers.portfolio_simulations import run_portfolio_simulation


# --------------------------------------------------------------------------
# Pure helper
# --------------------------------------------------------------------------
class TestSignalBarStopLevel:
    def test_long_anchors_to_low(self):
        assert _inst.signal_bar_stop_level(110.0, 90.0, side="long") == pytest.approx(90.0)

    def test_short_anchors_to_high(self):
        assert _inst.signal_bar_stop_level(110.0, 90.0, side="short") == pytest.approx(110.0)

    def test_long_buffer_pushes_stop_below_the_low(self):
        # 1% buffer -> 90 * 0.99
        assert _inst.signal_bar_stop_level(110.0, 90.0, 0.01, "long") == pytest.approx(89.1)

    def test_short_buffer_pushes_stop_above_the_high(self):
        assert _inst.signal_bar_stop_level(110.0, 90.0, 0.01, "short") == pytest.approx(111.1)

    def test_zero_buffer_sits_exactly_on_the_extreme(self):
        assert _inst.signal_bar_stop_level(110.0, 90.0, 0.0, "short") == pytest.approx(110.0)

    @pytest.mark.parametrize("high,low", [(np.nan, np.nan), (0.0, 0.0), (-5.0, -5.0), (None, None)])
    def test_missing_or_nonpositive_extreme_returns_none(self, high, low):
        assert _inst.signal_bar_stop_level(high, low, side="long") is None
        assert _inst.signal_bar_stop_level(high, low, side="short") is None

    def test_nan_on_the_unused_side_is_ignored(self):
        # a long stop only needs the Low; a NaN High must not poison it
        assert _inst.signal_bar_stop_level(np.nan, 90.0, side="long") == pytest.approx(90.0)
        assert _inst.signal_bar_stop_level(110.0, np.nan, side="short") == pytest.approx(110.0)


# --------------------------------------------------------------------------
# Engine wiring
# --------------------------------------------------------------------------
def _frame(rows):
    """rows: list of (date, open, high, low, close)."""
    idx = pd.to_datetime([r[0] for r in rows])
    df = pd.DataFrame(
        {"Open": [r[1] for r in rows], "High": [r[2] for r in rows],
         "Low": [r[3] for r in rows], "Close": [r[4] for r in rows],
         "Volume": [1_000_000] * len(rows)},
        index=idx,
    )
    df["ATR_14"] = 1.0
    df["ATR_14_pct"] = 0.01
    df["RSI_14"] = 50.0
    df["SMA_200"] = df["Close"]
    return df


def _run(df, signals, stop_config):
    return run_portfolio_simulation(
        portfolio_data={"TEST": df},
        signals={"TEST": pd.Series(signals, index=df.index)},
        initial_capital=100_000.0,
        allocation_pct=1.0,
        spy_df=None,
        vix_df=None,
        tnx_df=None,
        stop_config=stop_config,
    )


class TestLongSignalBarStop:
    """Signal on day 0 -> fill at day 1 open. Stop sits under day 0's Low."""

    def test_stop_fires_at_the_signal_bar_low(self):
        df = _frame([
            ("2024-01-02", 100, 105,  98, 104),   # signal bar: Low = 98
            ("2024-01-03", 104, 106, 103, 105),   # entry at 104
            ("2024-01-04", 105, 105,  95,  96),   # breaks 98 -> stop
            ("2024-01-05", 96,   97,  95,  96),
        ])
        res = _run(df, [1, 0, 0, 0], {"type": "signal_bar"})
        log = pd.DataFrame(res["trade_log"])
        assert len(log) == 1
        assert "Stop Loss" in log.iloc[0]["ExitReason"]
        # filled at the stop level (98), before slippage
        assert log.iloc[0]["ExitPrice"] == pytest.approx(98.0, rel=1e-3)

    def test_no_stop_when_price_holds_above_the_low(self):
        df = _frame([
            ("2024-01-02", 100, 105,  98, 104),
            ("2024-01-03", 104, 106, 103, 105),
            ("2024-01-04", 105, 107,  99, 106),   # dips to 99, never breaks 98
            ("2024-01-05", 106, 108, 105, 107),
        ])
        res = _run(df, [1, 0, 0, 0], {"type": "signal_bar"})
        log = pd.DataFrame(res["trade_log"])
        assert log.empty or "Stop Loss" not in log.iloc[0]["ExitReason"]

    def test_buffer_widens_the_stop_and_avoids_the_graze(self):
        df = _frame([
            ("2024-01-02", 100, 105,  98, 104),
            ("2024-01-03", 104, 106, 103, 105),
            ("2024-01-04", 105, 106, 97.5, 105),  # grazes just under 98
            ("2024-01-05", 105, 107, 104, 106),
        ])
        tight = pd.DataFrame(_run(df, [1, 0, 0, 0], {"type": "signal_bar"})["trade_log"])
        wide = pd.DataFrame(_run(df, [1, 0, 0, 0],
                                 {"type": "signal_bar", "buffer": 0.02})["trade_log"])
        assert "Stop Loss" in tight.iloc[0]["ExitReason"]          # 98.0 grazed
        assert wide.empty or "Stop Loss" not in wide.iloc[0]["ExitReason"]  # 96.04 held

    def test_initial_risk_is_measured_from_the_signal_bar_low(self):
        df = _frame([
            ("2024-01-02", 100, 105,  98, 104),
            ("2024-01-03", 104, 106, 103, 105),
            ("2024-01-04", 105, 105,  95,  96),
            ("2024-01-05", 96,   97,  95,  96),
        ])
        log = pd.DataFrame(_run(df, [1, 0, 0, 0], {"type": "signal_bar"})["trade_log"])
        entry = log.iloc[0]["EntryPrice"]
        # risk per share = entry - 98, not the 1% fallback proxy
        assert log.iloc[0]["InitialRisk"] == pytest.approx(entry - 98.0, rel=1e-6)


class TestShortSignalBarStop:
    """Short signal (-2) on day 0 -> fill at day 1 open. Stop sits above day 0's High."""

    def test_stop_fires_at_the_signal_bar_high(self):
        df = _frame([
            ("2024-01-02", 100, 105,  98,  99),   # signal bar: High = 105
            ("2024-01-03",  99, 100,  97,  98),   # short at 99
            ("2024-01-04",  98, 108,  98, 107),   # breaks 105 -> stop
            ("2024-01-05", 107, 108, 106, 107),
        ])
        log = pd.DataFrame(_run(df, [-2, 0, 0, 0], {"type": "signal_bar"})["trade_log"])
        assert len(log) == 1
        assert "Stop Loss" in log.iloc[0]["ExitReason"]
        assert log.iloc[0]["ExitPrice"] == pytest.approx(105.0, rel=1e-3)

    def test_no_stop_when_price_stays_under_the_high(self):
        df = _frame([
            ("2024-01-02", 100, 105,  98,  99),
            ("2024-01-03",  99, 100,  97,  98),
            ("2024-01-04",  98, 104,  96,  97),   # tops at 104, never reaches 105
            ("2024-01-05",  97,  99,  95,  96),
        ])
        log = pd.DataFrame(_run(df, [-2, 0, 0, 0], {"type": "signal_bar"})["trade_log"])
        assert log.empty or "Stop Loss" not in log.iloc[0]["ExitReason"]

    def test_short_buffer_widens_the_stop(self):
        df = _frame([
            ("2024-01-02", 100, 105,  98,  99),
            ("2024-01-03",  99, 100,  97,  98),
            ("2024-01-04",  98, 105.5, 97, 105),  # pokes just above 105
            ("2024-01-05", 105, 106, 104, 105),
        ])
        tight = pd.DataFrame(_run(df, [-2, 0, 0, 0], {"type": "signal_bar"})["trade_log"])
        wide = pd.DataFrame(_run(df, [-2, 0, 0, 0],
                                 {"type": "signal_bar", "buffer": 0.02})["trade_log"])
        assert "Stop Loss" in tight.iloc[0]["ExitReason"]
        assert wide.empty or "Stop Loss" not in wide.iloc[0]["ExitReason"]


class TestNoRegression:
    def test_signal_bar_does_not_trail(self):
        """The level is static: a later, higher low must not drag a long stop up."""
        df = _frame([
            ("2024-01-02", 100, 105,  98, 104),
            ("2024-01-03", 104, 106, 103, 105),
            ("2024-01-04", 105, 120, 110, 119),   # runs up; a trailing stop would follow
            ("2024-01-05", 119, 120, 100, 101),   # falls back to 100 — above 98
            ("2024-01-08", 101, 102, 100, 101),
        ])
        log = pd.DataFrame(_run(df, [1, 0, 0, 0, 0], {"type": "signal_bar"})["trade_log"])
        # a trailing stop would have fired on day 4; the static signal-bar stop must not
        assert log.empty or "Stop Loss" not in log.iloc[0]["ExitReason"]

    def test_unknown_stop_type_still_yields_no_stop(self):
        df = _frame([
            ("2024-01-02", 100, 105,  98, 104),
            ("2024-01-03", 104, 106, 103, 105),
            ("2024-01-04", 105, 105,  90,  91),
            ("2024-01-05",  91,  92,  90,  91),
        ])
        log = pd.DataFrame(_run(df, [1, 0, 0, 0], {"type": "none"})["trade_log"])
        assert log.empty or "Stop Loss" not in log.iloc[0]["ExitReason"]


class TestBarsBack:
    """`bars_back` walks the anchor further back than the signal bar itself."""

    def test_bars_back_1_anchors_to_the_bar_before_the_signal(self):
        # signal bar (day 1) Low = 98; the bar BEFORE it (day 0) Low = 92
        df = _frame([
            ("2024-01-02", 95, 101,  92,  99),   # bars_back=1 anchor -> 92
            ("2024-01-03", 99, 105,  98, 104),   # signal bar        -> 98
            ("2024-01-04", 104, 106, 103, 105),  # entry at 104
            ("2024-01-05", 105, 105,  95,  96),  # breaks 98 but not 92
            ("2024-01-08", 96,  97,  95,  96),
        ])
        sig = [0, 1, 0, 0, 0]
        tight = pd.DataFrame(_run(df, sig, {"type": "signal_bar"})["trade_log"])
        wide = pd.DataFrame(_run(df, sig, {"type": "signal_bar", "bars_back": 1})["trade_log"])
        assert "Stop Loss" in tight.iloc[0]["ExitReason"]          # 98 broken
        assert wide.empty or "Stop Loss" not in wide.iloc[0]["ExitReason"]   # 92 held

    def test_bars_back_0_is_the_default_and_matches_omitting_it(self):
        df = _frame([
            ("2024-01-02", 95, 101,  92,  99),
            ("2024-01-03", 99, 105,  98, 104),
            ("2024-01-04", 104, 106, 103, 105),
            ("2024-01-05", 105, 105,  95,  96),
            ("2024-01-08", 96,  97,  95,  96),
        ])
        sig = [0, 1, 0, 0, 0]
        a = pd.DataFrame(_run(df, sig, {"type": "signal_bar"})["trade_log"])
        b = pd.DataFrame(_run(df, sig, {"type": "signal_bar", "bars_back": 0})["trade_log"])
        assert a.iloc[0]["ExitPrice"] == pytest.approx(b.iloc[0]["ExitPrice"])

    def test_short_bars_back_anchors_above_the_earlier_high(self):
        df = _frame([
            ("2024-01-02", 100, 112,  98, 100),  # bars_back=1 anchor -> 112
            ("2024-01-03", 100, 105,  98,  99),  # signal bar        -> 105
            ("2024-01-04",  99, 100,  97,  98),  # short at 99
            ("2024-01-05",  98, 108,  98, 107),  # breaks 105 but not 112
            ("2024-01-08", 107, 108, 106, 107),
        ])
        sig = [0, -2, 0, 0, 0]
        tight = pd.DataFrame(_run(df, sig, {"type": "signal_bar"})["trade_log"])
        wide = pd.DataFrame(_run(df, sig, {"type": "signal_bar", "bars_back": 1})["trade_log"])
        assert "Stop Loss" in tight.iloc[0]["ExitReason"]
        assert wide.empty or "Stop Loss" not in wide.iloc[0]["ExitReason"]

    def test_walking_off_the_start_of_the_series_yields_no_stop(self):
        df = _frame([
            ("2024-01-02", 100, 105,  98, 104),  # signal on the FIRST bar
            ("2024-01-03", 104, 106, 103, 105),
            ("2024-01-04", 105, 105,  90,  91),
            ("2024-01-05",  91,  92,  90,  91),
        ])
        log = pd.DataFrame(_run(df, [1, 0, 0, 0],
                                {"type": "signal_bar", "bars_back": 5})["trade_log"])
        assert log.empty or "Stop Loss" not in log.iloc[0]["ExitReason"]


# --------------------------------------------------------------------------
# Protective-side guard: a fill that gaps THROUGH the structural level leaves
# the stop on the wrong side of entry. Left unguarded it fires next bar and
# fills at the phantom level in the trade's FAVOR (a spurious profitable
# "Stop Loss") and poisons InitialRisk/RMultiple. The guard drops the stop.
# alloc 0.5 (not 1.0) so the entry is never rejected by the full-capital
# affordability epsilon — we need the position to actually open here.
# --------------------------------------------------------------------------
def _run_half(df, signals, stop_config):
    return run_portfolio_simulation(
        portfolio_data={"TEST": df},
        signals={"TEST": pd.Series(signals, index=df.index)},
        initial_capital=100_000.0, allocation_pct=0.5,
        spy_df=None, vix_df=None, tnx_df=None, stop_config=stop_config,
    )


class TestGapThroughEntryGuard:
    def test_long_gap_down_below_low_does_not_fire_a_favorable_stop(self):
        # signal-bar Low = 98; next bar GAPS DOWN and opens at 94 (below 98),
        # so the structural stop (98) would sit ABOVE the long fill.
        df = _frame([
            ("2024-01-02", 100, 105,  98, 104),   # signal bar, Low = 98
            ("2024-01-03",  94,  95,  93,  94),    # GAP DOWN: fill at 94
            ("2024-01-04",  96,  97,  95,  96),    # trades under 98 the whole way
            ("2024-01-05",  96,  97,  95,  96),
            ("2024-01-08",  96,  97,  95,  96),
        ])
        log = pd.DataFrame(_run_half(df, [1, 0, 0, 0, 0], {"type": "signal_bar"})["trade_log"])
        assert len(log) == 1                                   # the position DID open
        assert "Stop Loss" not in log.iloc[0]["ExitReason"]    # no wrong-side stop fired
        # sanity: without the guard this same bar produced a ~+4R "Stop Loss"
        assert not (log.iloc[0]["Profit"] > 0
                    and "Stop Loss" in log.iloc[0]["ExitReason"])

    def test_short_gap_up_above_high_does_not_fire_a_favorable_stop(self):
        # signal-bar High = 105; next bar GAPS UP and opens at 108 (above 105),
        # so the structural stop (105) would sit BELOW the short fill.
        df = _frame([
            ("2024-01-02", 100, 105,  98,  99),   # signal bar, High = 105
            ("2024-01-03", 108, 109, 107, 108),   # GAP UP: short fill at 108
            ("2024-01-04", 106, 107, 104, 105),   # trades above 105 the whole way
            ("2024-01-05", 105, 106, 104, 105),
            ("2024-01-08", 105, 106, 104, 105),
        ])
        log = pd.DataFrame(_run_half(df, [-2, 0, 0, 0, 0], {"type": "signal_bar"})["trade_log"])
        assert len(log) == 1
        assert "Stop Loss" not in log.iloc[0]["ExitReason"]

    def test_long_normal_fill_still_stops_below_the_low(self):
        # Guard must NOT suppress a legitimate stop: no gap, fill above the low,
        # price later breaks 98 -> a real (losing) Stop Loss.
        df = _frame([
            ("2024-01-02", 100, 105,  98, 104),
            ("2024-01-03", 104, 106, 103, 105),   # fill at 104 (> stop 98)
            ("2024-01-04", 105, 105,  95,  96),    # breaks 98 -> stop
            ("2024-01-05",  96,  97,  95,  96),
        ])
        log = pd.DataFrame(_run_half(df, [1, 0, 0, 0], {"type": "signal_bar"})["trade_log"])
        assert "Stop Loss" in log.iloc[0]["ExitReason"]
        assert log.iloc[0]["Profit"] < 0                       # a real losing stop


# ---------------------------------------------------------------------------
# #372: risk_parity must size off the signal_bar stop, not a 3xATR proxy
# ---------------------------------------------------------------------------

class TestRiskParitySizesOffTheSignalBarStop:
    """`risk_parity` derives `stop_distance_pct` from the configured stop. It
    had branches for `percentage`, `atr`, `trailing_atr` and `points` but not
    for `signal_bar` -- so a stop whose level is exactly computable before
    entry fell through to the fallback at position_sizing.py:205, a 3xATR proxy
    read off `.iloc[-1]` of whatever slice the caller passed.

    That is the same class as the #324 regression: sizing and the stop level
    holding two different beliefs about one stop. There the disagreement put
    20% of the book at risk against a 2% target.

    The signal-bar level needs only the bar's own High/Low and the buffer, so
    there is no reason to proxy it.
    """

    CFG = {"type": "signal_bar", "buffer": 0.0}

    @staticmethod
    def _sized(stop_config, sizing_method, lead_low=None):
        from unittest.mock import patch
        import helpers.portfolio_simulations as ps
        # Signal bar Low = 90 against a ~100 entry: a 10% stop distance, which
        # is deliberately far from the 3% a 3xATR proxy would produce here
        # (ATR_14 = 1.0), so the two are not confusable.
        rows = [
            ("2024-01-02", 100, 105,  90, 100),   # signal bar, Low = 90
            ("2024-01-03", 100, 101,  99, 100),   # fill here under open-exec
            ("2024-01-04", 100, 101,  99, 100),
            ("2024-01-05", 100, 101,  99, 100),
            ("2024-01-08", 100, 101,  99, 100),
        ]
        sig = [1, 0, 0, 0, 0]
        if lead_low is not None:
            # One bar BEFORE the signal bar, with a distinct Low, so that
            # `bars_back=1` anchors somewhere the default cannot reach.
            rows.insert(0, ("2024-01-01", 100, 105, lead_low, 100))
            sig.insert(0, 0)
        df = _frame(rows)
        with patch.dict(ps.CONFIG, {"position_sizing_method": sizing_method,
                                    "target_risk_per_trade": 0.02}):
            res = ps.run_portfolio_simulation(
                portfolio_data={"TEST": df},
                signals={"TEST": pd.Series(sig, index=df.index)},
                initial_capital=100_000.0, allocation_pct=0.5,
                spy_df=None, vix_df=None, tnx_df=None,
                stop_config=stop_config,
            )
        if not res or not res.get("trade_log"):
            return None
        t = res["trade_log"][0]
        return float(t["Shares"]), float(t["InitialRisk"])

    def test_dollars_at_risk_match_the_target_not_the_atr_proxy(self):
        """risk_parity's whole purpose is equalising risk per trade. With a
        stop 10% away and a 2% target on $100k, that is ~$2,000 at risk.

        Falling through to the 3xATR proxy sizes against a 3% distance instead
        of 10%, over-sizing by more than 3x.
        """
        out = self._sized(self.CFG, "risk_parity")
        if out is None:
            pytest.skip("no trade produced")
        shares, risk_per_share = out
        dollars = shares * risk_per_share
        assert dollars == pytest.approx(2_000.0, rel=0.30), (
            f"${dollars:,.2f} at risk against a $2,000 target — sizing did not "
            f"use the signal-bar stop distance"
        )

    def test_initial_risk_is_measured_from_the_signal_bar_low(self):
        """The stop level itself is unchanged by this fix; asserted so a
        regression in the stop path cannot be mistaken for a sizing win."""
        out = self._sized(self.CFG, "risk_parity")
        if out is None:
            pytest.skip("no trade produced")
        _, risk_per_share = out
        assert risk_per_share == pytest.approx(10.0, rel=0.05), risk_per_share

    def test_sizing_honours_bars_back(self):
        """`bars_back` moves the anchor, so it must move the SIZE.

        The sizing branch walks back through `_walk_back()` exactly as the stop
        path does. Hardcoding the walk to 0 leaves every other assertion in
        this class green -- they all run at the default -- which is precisely
        the #324 shape: sizing and the stop path holding two beliefs about one
        stop, with nothing to notice.

        Lead bar Low = 80 against a 100.05 fill -> a 20% distance, double the
        default's 10%, so the two cannot be confused. @shardul0701 on #375.
        """
        cfg = {"type": "signal_bar", "buffer": 0.0, "bars_back": 1}
        out = self._sized(cfg, "risk_parity", lead_low=80)
        if out is None:
            pytest.skip("no trade produced")
        shares, risk_per_share = out
        assert risk_per_share == pytest.approx(20.05, rel=0.02), risk_per_share
        assert shares == pytest.approx(99.95, rel=0.02), shares

    @pytest.mark.parametrize("lead_low,expect_risk", [(80, 20.05), (50, 50.05)])
    def test_risk_pct_capped_also_honours_bars_back(self, lead_low, expect_risk):
        """The same assertion, one argument different — and it caught a bug.

        `_sized` was already parameterised on `sizing_method` and all four call
        sites passed `risk_parity`, so the whole class exercised ONE of the two
        stop-distance ladders. #385 added a `signal_bar` branch to the other one
        and anchored it to `signal_date` directly, without walking `bars_back`:

            stop                        method            shares   $ risk   %eq
            bars_back=0                 risk_parity       199.90  2009.00  2.01%
            bars_back=0                 risk_pct_capped   100.00  1005.00  1.01%
            bars_back=1 lead_low=80     risk_parity        99.95  2004.00  2.00%
            bars_back=1 lead_low=80     risk_pct_capped   100.00  2005.00  2.01%  <- 1% target
            bars_back=1 lead_low=50     risk_parity        39.98  2001.00  2.00%
            bars_back=1 lead_low=50     risk_pct_capped   100.00  5005.00  5.01%  <- 1% target

        The share count pinned at 100.00 across all three is the signature:
        completely insensitive to the parameter. The error is UNBOUNDED in the
        gap between the trigger low and the walked-back low, and it is
        OVER-risk. The heat gate cannot catch it — the sizer and the guard that
        checks the sizer are handed the same number. (@shardul0701 on #390.)

        Parameterised over two lead lows because a single one is satisfied by
        any anchor that happens to give the right answer once; two different
        gaps require the walk itself.
        """
        cfg = {"type": "signal_bar", "buffer": 0.0, "bars_back": 1}
        out = self._sized(cfg, "risk_pct_capped", lead_low=lead_low)
        if out is None:
            pytest.skip("no trade produced")
        shares, risk_per_share = out
        assert risk_per_share == pytest.approx(expect_risk, rel=0.02)
        # risk_pct_per_trade defaults to 1% of $100k = $1,000.
        assert shares * risk_per_share == pytest.approx(1_000.0, rel=0.02), (
            "sizing anchored to a bar the stop is not on: %.2f shares x %.2f "
            "= $%.2f against a $1,000 budget"
            % (shares, risk_per_share, shares * risk_per_share))

    def test_risk_pct_capped_matches_risk_parity_on_the_default_anchor(self):
        """Control for the two above: at `bars_back=0` the ladders agree, so a
        divergence there would mean something other than the walk."""
        rp = self._sized(self.CFG, "risk_parity")
        rc = self._sized(self.CFG, "risk_pct_capped")
        if rp is None or rc is None:
            pytest.skip("no trade produced")
        assert rp[1] == pytest.approx(rc[1], rel=0.01), (rp, rc)

    def test_sizing_honours_buffer(self):
        """`buffer` widens the level, so it must widen the risk and shrink the
        size. Hardcoding it to 0.0 survives every other test in this class.

        Low 90 with a 5% buffer -> 85.50, a 14.5% distance off the raw 100.
        """
        cfg = {"type": "signal_bar", "buffer": 0.05}
        out = self._sized(cfg, "risk_parity")
        if out is None:
            pytest.skip("no trade produced")
        shares, risk_per_share = out
        assert risk_per_share == pytest.approx(14.55, rel=0.02), risk_per_share
        assert shares == pytest.approx(137.86, rel=0.02), shares

    def test_fixed_sizing_is_unchanged(self):
        """The no-regression half: `fixed` never consulted stop_distance_pct,
        so it must not move."""
        out = self._sized(self.CFG, "fixed")
        if out is None:
            pytest.skip("no trade produced")
        shares, _ = out
        assert shares == pytest.approx(500.0, rel=0.02), shares


class TestShortSideHonoursTheSizingMethod:
    """#386: the equity short leg now reads `position_sizing_method`.

    This class replaces `TestShortSideSizingMethodIsAudible`, which pinned the
    #372 WARNING that the gap existed. The banner, its module-level
    `_WARNED_SHORT_SIZING` dedup set and the autouse fixture that reset it are
    all gone in the same change — a warning that outlives the gap it describes
    is worse than none, because the next reader has to prove it is stale before
    ignoring it.

    The fixture was the piece most likely to be left behind: it only reset
    module state, so with the set removed it would have gone silently green
    forever rather than failing. Deleted deliberately, not by accident.

    What was wrong, measured at $100k / $100 / 5% stop:

        method             long      short (before)   short (after)
        fixed             99.95         100.05          100.05    <- control
        fixed_contracts    3.00         100.05            3.00    <- was 33x
        risk_pct_capped   20.00         100.05          method
        vol_parity       999.48         100.05          method
        risk_parity      399.80         100.05          method

    `fixed` agreeing to the tick both before and after (the 0.10 is slippage
    sign) is what shows the harness is symmetric by direction, so a divergence
    in any other row is the method and not the leg.
    """

    # Instrument is a parameter, not a fixture constant. The equity-only
    # version of this class passed while the FUTURES short leg still dispatched
    # on a two-name list, so vol_parity / risk_parity / kelly fell to
    # fixed-fractional-over-margin there and nothing said so. One argument.
    # (@shardul0701 on #392.)
    # Two contract months of the SAME root, not two different roots. The first
    # draft used MESM6/MNQM6 — $5/point against $2/point — so even `fixed`, the
    # control that must agree, came out 2.5x apart and the test failed for a
    # reason with nothing to do with the short leg. A long/short comparison
    # needs the legs to differ ONLY in direction.
    SYMS = {"equity": ("LNG", "SRT"), "futures": ("MESM6", "MESZ6")}

    @staticmethod
    def _book(method, size_mult=None, instrument="equity", **cfg):
        from unittest.mock import patch
        import helpers.portfolio_simulations as ps
        lng, srt = TestShortSideHonoursTheSizingMethod.SYMS[instrument]
        rows_l = [("2024-01-02", 100, 105,  90, 100),
                  ("2024-01-03", 100, 101,  99, 100),
                  ("2024-01-04", 100, 101,  99, 100),
                  ("2024-01-05", 100, 101,  99, 100)]
        rows_s = [("2024-01-02", 100, 110,  95, 100),
                  ("2024-01-03", 100, 101,  99, 100),
                  ("2024-01-04", 100, 101,  99, 100),
                  ("2024-01-05", 100, 101,  99, 100)]
        dfl, dfs = _frame(rows_l), _frame(rows_s)
        mults = None
        if size_mult is not None:
            mults = {lng: pd.Series(size_mult, index=dfl.index, dtype=float),
                     srt: pd.Series(size_mult, index=dfs.index, dtype=float)}
        # target_risk 0.004, not the 0.02 default. At 0.02 with this frame's
        # ATR of 1.0 on a ~100 price, vol_parity sizes to 2,000 shares = 200% of
        # equity; the long leg absorbs the cash, the short cannot open, and the
        # test SKIPS on "no trade produced" — silently, for BOTH instruments,
        # on the one method whose long/short divergence is largest (7.9x). A
        # skip is not a pass, but it reads like one in a green run.
        base = {"position_sizing_method": method,
                "target_risk_per_trade": 0.004,
                "risk_pct_per_trade": 0.01,
                "max_contracts_cap": 20,
                "fixed_contracts_per_trade": 3,
                "max_portfolio_heat": 1.0,
                "max_pct_adv": 0.0}
        if instrument == "futures":
            base.setdefault("instruments", {
                "default_asset_class": "equity",
                "futures_initial_margin_pct": 0.10,
                "futures_commission_per_contract": 2.50,
                "futures_slippage_ticks": 1.0, "overrides": {}})
        base.update(cfg)
        with patch.dict(ps.CONFIG, base):
            res = ps.run_portfolio_simulation(
                portfolio_data={lng: dfl, srt: dfs},
                signals={lng: pd.Series([1, 0, 0, 0], index=dfl.index),
                         srt: pd.Series([-2, 0, 0, 0], index=dfs.index)},
                initial_capital=100_000.0, allocation_pct=0.10,
                spy_df=None, vix_df=None, tnx_df=None,
                stop_config={"type": "percentage", "value": 0.05},
                size_mults=mults,
            )
        if not res or not res.get("trade_log"):
            return {}
        by_sym = {t["Symbol"]: float(t["Shares"]) for t in res["trade_log"]}
        return {"LNG": by_sym.get(lng), "SRT": by_sym.get(srt)}

    @pytest.mark.parametrize("instrument", ["equity", "futures"])
    @pytest.mark.parametrize(
        "method", ["fixed", "vol_parity", "risk_parity", "fixed_contracts"])
    def test_both_legs_agree_on_share_count(self, method, instrument):
        """The acceptance criterion: same method, same count, modulo the
        slippage sign that separates a buy fill from a sell fill.

        `kelly` is deliberately absent. It agrees on both legs — but by
        DEGRADING, not by working: the short path never supplies
        win_rate/avg_win/avg_loss, so `_kelly_criterion` falls back to
        `_fixed_allocation` on both sides. Including it here would add a green
        row that is evidence of nothing. (@shardul0701 on #392.)
        """
        out = self._book(method, instrument=instrument)
        if out.get("LNG") is None or out.get("SRT") is None:
            pytest.skip("no trade produced")
        assert out["SRT"] == pytest.approx(out["LNG"], rel=0.01), (
            method, instrument, out)

    def test_fixed_contracts_no_longer_diverges_33x(self):
        """The widest of the five, and the one the banner originally excluded
        because it reads as a fixed method by name."""
        out = self._book("fixed_contracts")
        if "SRT" not in out:
            pytest.skip("no trade produced")
        assert out["SRT"] == pytest.approx(3.0), out

    def test_size_mults_scales_both_legs(self):
        """`size_mults` is a public parameter the long path honoured at three
        sites and the short path at none, so a 0.5x band scaled one leg of a
        long/short book and not the other. Nothing in-repo passes it, so
        nothing caught it."""
        full = self._book("fixed", size_mult=1.0)
        half = self._book("fixed", size_mult=0.5)
        if not full or not half:
            pytest.skip("no trade produced")
        assert half["LNG"] == pytest.approx(full["LNG"] * 0.5, rel=0.01)
        assert half["SRT"] == pytest.approx(full["SRT"] * 0.5, rel=0.01), (
            "short leg still drops size_mults")

    def test_the_372_banner_is_gone(self, caplog):
        """It described a gap that no longer exists. Asserted rather than
        assumed, because the whole point of retiring it is that a stale warning
        costs a reader more than a missing one."""
        import logging
        with caplog.at_level(logging.WARNING):
            self._book("vol_parity")
        assert not any("#372" in r.message for r in caplog.records), (
            [r.message for r in caplog.records])

    def test_the_dedup_set_is_gone_too(self):
        """The set and its autouse fixture go with the banner. If the set comes
        back without the warning, this is the test that says so."""
        import helpers.portfolio_simulations as ps
        assert not hasattr(ps, "_WARNED_SHORT_SIZING")
