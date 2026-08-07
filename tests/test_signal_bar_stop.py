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
