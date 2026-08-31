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


class TestShortSideSizingMethodIsAudible:
    """#372: the equity short entry sizes as alloc/fill unconditionally, so a
    run configured risk_parity gets FIXED allocation on every short while the
    long side honours the setting — the book sized by two different methods
    depending on direction, silently.

    Wiring it is a behavioural change for every existing non-fixed run and
    wants its own PR. Until then the gap is at least audible: pinned here so
    nobody removes the warning without replacing it with the fix.
    """

    @pytest.fixture(autouse=True)
    def _reset_warn_dedup(self):
        """The banner is deduped once-per-method-per-process, so without this
        the warn test passes only while it happens to run first. Clearing makes
        every test in the class independent of collection order."""
        import helpers.portfolio_simulations as ps
        ps._WARNED_SHORT_SIZING.clear()
        yield
        ps._WARNED_SHORT_SIZING.clear()

    def test_a_short_book_with_non_fixed_sizing_warns(self, caplog):
        from unittest.mock import patch
        import logging
        import helpers.portfolio_simulations as ps
        df = _frame([
            ("2024-01-02", 100, 105,  95, 100),
            ("2024-01-03", 100, 101,  99, 100),
            ("2024-01-04", 100, 101,  99, 100),
        ])
        with patch.dict(ps.CONFIG, {"position_sizing_method": "risk_parity"}):
            with caplog.at_level(logging.WARNING):
                ps.run_portfolio_simulation(
                    portfolio_data={"TEST": df},
                    signals={"TEST": pd.Series([-2, 0, 0], index=df.index)},
                    initial_capital=100_000.0, allocation_pct=0.5,
                    spy_df=None, vix_df=None, tnx_df=None,
                    stop_config={"type": "none"},
                )
        assert any("#372" in r.message or "LONG side only" in r.message
                   for r in caplog.records), [r.message for r in caplog.records]

    def test_a_long_only_book_does_not_warn(self, caplog):
        """No false alarm on the overwhelming majority of runs."""
        from unittest.mock import patch
        import logging
        import helpers.portfolio_simulations as ps
        df = _frame([
            ("2024-01-02", 100, 105,  95, 100),
            ("2024-01-03", 100, 101,  99, 100),
            ("2024-01-04", 100, 101,  99, 100),
        ])
        with patch.dict(ps.CONFIG, {"position_sizing_method": "risk_parity"}):
            with caplog.at_level(logging.WARNING):
                ps.run_portfolio_simulation(
                    portfolio_data={"TEST": df},
                    signals={"TEST": pd.Series([1, 0, 0], index=df.index)},
                    initial_capital=100_000.0, allocation_pct=0.5,
                    spy_df=None, vix_df=None, tnx_df=None,
                    stop_config={"type": "none"},
                )
        assert not any("#372" in r.message for r in caplog.records)

    @pytest.mark.parametrize("label,sig", [
        ("long entry then long EXIT", [1, 0, -1]),
        ("long entry then SCALED partial exit", [1, 0, -0.5]),
    ])
    def test_a_long_only_book_that_exits_does_not_warn(self, caplog, label, sig):
        """The discriminator is -2, not "negative".

        `-1` is *exit long* as well as *cover short*, and `-1 < s < 0` is a
        scaled partial exit (v1.11.0) -- so a guard keyed on `s < 0` is true
        for any long book the moment it closes a position. An AST walk over
        helpers/indicators.py counts 39 signal functions emitting -1 against
        exactly 2 emitting -2, so `s < 0` matches ~95% of the shipped signal
        logic and is short-specific for none of it.

        `[1, 0, 0]` above is the one long-only shape that does NOT trip it --
        a book that enters and never exits. These two are the shapes real
        strategies actually produce. @shardul0701 on #375.
        """
        from unittest.mock import patch
        import logging
        import helpers.portfolio_simulations as ps
        df = _frame([
            ("2024-01-02", 100, 105,  95, 100),
            ("2024-01-03", 100, 101,  99, 100),
            ("2024-01-04", 100, 101,  99, 100),
        ])
        with patch.dict(ps.CONFIG, {"position_sizing_method": "risk_parity"}):
            with caplog.at_level(logging.WARNING):
                ps.run_portfolio_simulation(
                    portfolio_data={"TEST": df},
                    signals={"TEST": pd.Series(sig, index=df.index)},
                    initial_capital=100_000.0, allocation_pct=0.5,
                    spy_df=None, vix_df=None, tnx_df=None,
                    stop_config={"type": "none"},
                )
        assert not any("#372" in r.message for r in caplog.records), (
            f"{label}: warned on a long-only book -> {[r.message for r in caplog.records]}")

    def test_a_futures_short_book_does_NOT_warn(self, caplog):
        """The gap is the equity `cash_full` branch. The FUTURES short leg does
        dispatch on position_sizing_method, so both legs agree there and the
        banner was a false alarm:

            futures, fixed_contracts   LONG 1.0   SHORT 1.0   banner fired

        `_has_shorts` scanned for -2 and never consulted margin_mode. A futures
        user reading "sized by two different methods depending on direction"
        would go hunting for an inconsistency that isn't there.
        @shardul0701 on #381.
        """
        from unittest.mock import patch
        import logging
        import helpers.portfolio_simulations as ps
        df = _frame([
            ("2024-01-02", 5000, 5050, 4950, 5000),
            ("2024-01-03", 5000, 5050, 4950, 5000),
            ("2024-01-04", 5000, 5050, 4950, 5000),
        ])
        ovr = {"instruments": {"overrides": {"ESZ6": {
            "asset_class": "future", "point_value": 20.0, "tick_size": 0.25,
            "margin_mode": "initial_margin", "initial_margin": 20000.0,
            "integer_units": True, "borrow_applies": False}}},
            "position_sizing_method": "fixed_contracts",
            "fixed_contracts_per_trade": 1}
        with patch.dict(ps.CONFIG, ovr):
            with caplog.at_level(logging.WARNING):
                ps.run_portfolio_simulation(
                    portfolio_data={"ESZ6": df},
                    signals={"ESZ6": pd.Series([-2, 0, 0], index=df.index)},
                    initial_capital=200_000.0, allocation_pct=0.5,
                    spy_df=None, vix_df=None, tnx_df=None,
                    stop_config={"type": "none"})
        assert not any("#372" in r.message for r in caplog.records), \
            [r.message for r in caplog.records]

    def test_a_MIXED_book_still_warns_for_the_equity_short(self, caplog):
        """The row that separates a per-symbol gate from a whole-book one.

        A futures-only book is the easy case. The way this gate goes wrong is
        MIXED: collapse the book to a single instrument class and an equity
        short sitting beside a futures short gets silenced -- turning the
        false-positive fix into a false-NEGATIVE on the real gap.

        `_has_shorts` evaluates `margin_mode` per symbol inside the `any()`,
        so it doesn't. Both shapes pass every other test in this class, which
        is why this one exists. @shardul0701 on #381.
        """
        from unittest.mock import patch
        import logging
        import helpers.portfolio_simulations as ps
        fut = _frame([
            ("2024-01-02", 5000, 5050, 4950, 5000),
            ("2024-01-03", 5000, 5050, 4950, 5000),
            ("2024-01-04", 5000, 5050, 4950, 5000),
        ])
        eq = _frame([
            ("2024-01-02", 100, 105,  95, 100),
            ("2024-01-03", 100, 101,  99, 100),
            ("2024-01-04", 100, 101,  99, 100),
        ])
        ovr = {"instruments": {"overrides": {"ESZ6": {
            "asset_class": "future", "point_value": 20.0, "tick_size": 0.25,
            "margin_mode": "initial_margin", "initial_margin": 20000.0,
            "integer_units": True, "borrow_applies": False}}},
            "position_sizing_method": "fixed_contracts",
            "fixed_contracts_per_trade": 1}
        with patch.dict(ps.CONFIG, ovr):
            with caplog.at_level(logging.WARNING):
                ps.run_portfolio_simulation(
                    portfolio_data={"ESZ6": fut, "TEST": eq},
                    signals={"ESZ6": pd.Series([-2, 0, 0], index=fut.index),
                             "TEST": pd.Series([-2, 0, 0], index=eq.index)},
                    initial_capital=200_000.0, allocation_pct=0.5,
                    spy_df=None, vix_df=None, tnx_df=None,
                    stop_config={"type": "none"})
        assert any("#372" in r.message for r in caplog.records), (
            "a mixed book with an EQUITY short must still warn; the gate "
            "collapsed to book level")

    def test_fixed_contracts_DOES_warn_with_shorts(self, caplog):
        """`fixed_contracts` reads as a fixed method by name and is not one.

        The equity short leg implements neither `fixed_contracts` nor any other
        non-default method -- it sizes as alloc/fill unconditionally -- so a
        run configured for 3 contracts takes 3 shares long and ~100 short. That
        is the WIDEST divergence of the five methods (33x) and it was the one
        configuration excluded from the banner. @shardul0701 on #381.
        """
        from unittest.mock import patch
        import logging
        import helpers.portfolio_simulations as ps
        df = _frame([
            ("2024-01-02", 100, 105,  95, 100),
            ("2024-01-03", 100, 101,  99, 100),
            ("2024-01-04", 100, 101,  99, 100),
        ])
        with patch.dict(ps.CONFIG, {"position_sizing_method": "fixed_contracts",
                                    "fixed_contracts_per_trade": 3}):
            with caplog.at_level(logging.WARNING):
                ps.run_portfolio_simulation(
                    portfolio_data={"TEST": df},
                    signals={"TEST": pd.Series([-2, 0, 0], index=df.index)},
                    initial_capital=100_000.0, allocation_pct=0.5,
                    spy_df=None, vix_df=None, tnx_df=None,
                    stop_config={"type": "none"})
        assert any("#372" in r.message or "LONG side only" in r.message
                   for r in caplog.records), [r.message for r in caplog.records]

    def test_fixed_sizing_does_not_warn_even_with_shorts(self):
        """`fixed` is honoured identically on both sides, so there is nothing
        to warn about."""
        from unittest.mock import patch
        import logging
        import helpers.portfolio_simulations as ps
        import io
        df = _frame([
            ("2024-01-02", 100, 105,  95, 100),
            ("2024-01-03", 100, 101,  99, 100),
        ])
        stream = io.StringIO()
        h = logging.StreamHandler(stream)
        ps.logger.addHandler(h)
        try:
            with patch.dict(ps.CONFIG, {"position_sizing_method": "fixed"}):
                ps.run_portfolio_simulation(
                    portfolio_data={"TEST": df},
                    signals={"TEST": pd.Series([-2, 0], index=df.index)},
                    initial_capital=100_000.0, allocation_pct=0.5,
                    spy_df=None, vix_df=None, tnx_df=None,
                    stop_config={"type": "none"},
                )
        finally:
            ps.logger.removeHandler(h)
        assert "#372" not in stream.getvalue()
