"""
Regression tests for issue #310 — look-ahead leak in captured entry features.

The engine stores per-trade ``entry_*`` feature columns (RSI_14, ATR_14_pct,
SMA200_dist_pct, Volume_Spike, and the SPY/VIX/TNX comparison values) in the
trade log; these feed ``ml_features.parquet``. They used to be read from
``df.loc[entry_exec_date]`` — the *fill* bar. Under the default
``execution_time="open"`` the fill is at that bar's **open**, but the feature
values on that row embed the bar's **close** (and full-day volume), which was
unknowable at fill time. Any model trained on ``entry_*`` -> ``is_win`` was
therefore contaminated with same-bar future information.

Fix: capture features from the **signal bar** — ``signal_date`` (long) /
``sig_date`` (short), which is the bar *before* the fill under open execution
and the fill bar itself under close execution — matching what was actually
known when the entry decision was made.
"""

import numpy as np
import pandas as pd
import pytest

import helpers.portfolio_simulations as ps
from helpers.portfolio_simulations import run_portfolio_simulation


@pytest.fixture
def open_execution(monkeypatch):
    """Force execution_time='open' so open-mode tests don't pass vacuously when
    config.py is set to 'close' (under close execution signal bar == fill bar,
    which would satisfy the assertions with or without the fix)."""
    monkeypatch.setitem(ps.CONFIG, "execution_time", "open")


def _feature_frame(rows):
    """rows: list of (date, close, rsi, atr_pct, sma_dist, vol_spike).

    Every feature column is given a distinct per-bar value so the captured
    entry feature unambiguously identifies which bar it was read from.
    """
    idx = pd.to_datetime([r[0] for r in rows])
    close = np.array([r[1] for r in rows], dtype=float)
    df = pd.DataFrame(
        {
            "Open": close,          # open == close keeps fills simple/deterministic
            "High": close * 1.02,
            "Low": close * 0.98,
            "Close": close,
            "Volume": 1_000_000.0,
            "RSI_14": [r[2] for r in rows],
            "ATR_14": 1.0,
            "ATR_14_pct": [r[3] for r in rows],
            "SMA200_dist_pct": [r[4] for r in rows],
            "Volume_Spike": [r[5] for r in rows],
        },
        index=idx,
    )
    return df


# Four bars, each feature column strictly increasing so the value pins the bar.
_ROWS = [
    ("2024-01-02", 100.0, 11.0, 0.011, 0.101, 1.1),   # bar 0  <- signal bar
    ("2024-01-03", 101.0, 22.0, 0.022, 0.202, 2.2),   # bar 1  <- fill bar (open exec)
    ("2024-01-04", 102.0, 33.0, 0.033, 0.303, 3.3),   # bar 2  <- exit signal
    ("2024-01-05", 103.0, 44.0, 0.044, 0.404, 4.4),   # bar 3  <- exit fill
]


class TestLongEntryFeatureCapture:
    def test_open_execution_captures_signal_bar_not_fill_bar(self, open_execution):
        df = _feature_frame(_ROWS)
        # signal on bar 0 -> fill bar 1 open; exit signal bar 2 -> fill bar 3.
        res = run_portfolio_simulation(
            portfolio_data={"TEST": df},
            signals={"TEST": pd.Series([1, 0, -1, 0], index=df.index)},
            initial_capital=100_000.0, allocation_pct=1.0,
            spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"},
        )
        log = pd.DataFrame(res["trade_log"])
        assert len(log) == 1
        row = log.iloc[0]
        # bar 0 (signal) values, NOT bar 1 (fill) values.
        assert row["entry_RSI_14"] == pytest.approx(11.0)
        assert row["entry_ATR_14_pct"] == pytest.approx(0.011)
        assert row["entry_SMA200_dist_pct"] == pytest.approx(0.101)
        assert row["entry_Volume_Spike"] == pytest.approx(1.1)

    def test_open_execution_captures_signal_bar_comparison_features(self, open_execution):
        df = _feature_frame(_ROWS)
        spy = _feature_frame([
            ("2024-01-02", 400.0, 55.0, 0.05, -0.10, 1.0),  # bar 0
            ("2024-01-03", 401.0, 66.0, 0.06, -0.20, 2.0),  # bar 1
            ("2024-01-04", 402.0, 77.0, 0.07, -0.30, 3.0),
            ("2024-01-05", 403.0, 88.0, 0.08, -0.40, 4.0),
        ])
        vix = _feature_frame([
            ("2024-01-02", 15.0, 0, 0, 0, 0),  # bar 0 Close = 15.0
            ("2024-01-03", 16.0, 0, 0, 0, 0),  # bar 1 Close = 16.0
            ("2024-01-04", 17.0, 0, 0, 0, 0),
            ("2024-01-05", 18.0, 0, 0, 0, 0),
        ])
        tnx = _feature_frame([
            ("2024-01-02", 4.10, 0, 0, 0, 0),  # bar 0 Close = 4.10
            ("2024-01-03", 4.20, 0, 0, 0, 0),
            ("2024-01-04", 4.30, 0, 0, 0, 0),
            ("2024-01-05", 4.40, 0, 0, 0, 0),
        ])
        res = run_portfolio_simulation(
            portfolio_data={"TEST": df},
            signals={"TEST": pd.Series([1, 0, -1, 0], index=df.index)},
            initial_capital=100_000.0, allocation_pct=1.0,
            spy_df=spy, vix_df=vix, tnx_df=tnx, stop_config={"type": "none"},
        )
        row = pd.DataFrame(res["trade_log"]).iloc[0]
        assert row["entry_SPY_RSI_14"] == pytest.approx(55.0)          # bar 0, not 66.0
        assert row["entry_SPY_SMA200_dist_pct"] == pytest.approx(-0.10)
        assert row["entry_VIX_Close"] == pytest.approx(15.0)           # bar 0, not 16.0
        assert row["entry_TNX_Close"] == pytest.approx(4.10)           # bar 0, not 4.20

    def test_spy_missing_signal_bar_does_not_drop_vix_tnx(self, open_execution):
        # SPY frame starts at the FILL bar (2024-01-03), so signal_date
        # (2024-01-02) is absent from it. VIX/TNX contain the signal bar. The
        # per-frame guards must still capture VIX/TNX (not drop them with SPY),
        # and must NOT fall back to the fill bar (which would re-leak).
        df = _feature_frame(_ROWS)
        spy = _feature_frame([
            ("2024-01-03", 401.0, 66.0, 0.06, -0.20, 2.0),  # starts at fill bar
            ("2024-01-04", 402.0, 77.0, 0.07, -0.30, 3.0),
            ("2024-01-05", 403.0, 88.0, 0.08, -0.40, 4.0),
        ])
        vix = _feature_frame([
            ("2024-01-02", 15.0, 0, 0, 0, 0),
            ("2024-01-03", 16.0, 0, 0, 0, 0),
            ("2024-01-04", 17.0, 0, 0, 0, 0),
            ("2024-01-05", 18.0, 0, 0, 0, 0),
        ])
        res = run_portfolio_simulation(
            portfolio_data={"TEST": df},
            signals={"TEST": pd.Series([1, 0, -1, 0], index=df.index)},
            initial_capital=100_000.0, allocation_pct=1.0,
            spy_df=spy, vix_df=vix, tnx_df=None, stop_config={"type": "none"},
        )
        row = pd.DataFrame(res["trade_log"]).iloc[0]
        assert row["entry_VIX_Close"] == pytest.approx(15.0)       # VIX kept despite SPY miss
        assert pd.isna(row.get("entry_SPY_RSI_14"))                # SPY dropped, not fill-bar filled
        assert row["entry_RSI_14"] == pytest.approx(11.0)          # symbol feature unaffected

    def test_close_execution_captures_the_signal_which_is_the_fill_bar(self, monkeypatch):
        # Under close execution the signal bar IS the fill bar, so the feature
        # comes from that same bar (bar 1 when the signal fires on bar 1).
        import helpers.portfolio_simulations as ps
        monkeypatch.setitem(ps.CONFIG, "execution_time", "close")
        df = _feature_frame(_ROWS)
        # signal fires on bar 1 -> fill bar 1 close; exit signal bar 2.
        res = run_portfolio_simulation(
            portfolio_data={"TEST": df},
            signals={"TEST": pd.Series([0, 1, -1, 0], index=df.index)},
            initial_capital=100_000.0, allocation_pct=1.0,
            spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"},
        )
        row = pd.DataFrame(res["trade_log"]).iloc[0]
        assert row["entry_RSI_14"] == pytest.approx(22.0)  # bar 1 (the signal == fill bar)


class TestShortEntryFeatureCapture:
    def test_open_execution_short_captures_signal_bar(self, open_execution):
        df = _feature_frame(_ROWS)
        # -2 enter short on bar 0 -> fill bar 1 open; -1 cover signal bar 2.
        res = run_portfolio_simulation(
            portfolio_data={"TEST": df},
            signals={"TEST": pd.Series([-2, 0, -1, 0], index=df.index)},
            initial_capital=100_000.0, allocation_pct=1.0,
            spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"},
        )
        log = pd.DataFrame(res["trade_log"])
        assert len(log) == 1
        row = log.iloc[0]
        assert row["entry_RSI_14"] == pytest.approx(11.0)   # bar 0 signal, not bar 1 fill
        assert row["entry_Volume_Spike"] == pytest.approx(1.1)

    def test_close_execution_short_captures_signal_equals_fill_bar(self, monkeypatch):
        monkeypatch.setitem(ps.CONFIG, "execution_time", "close")
        df = _feature_frame(_ROWS)
        # -2 enter short on bar 1 -> fill bar 1 close; -1 cover signal bar 2.
        res = run_portfolio_simulation(
            portfolio_data={"TEST": df},
            signals={"TEST": pd.Series([0, -2, -1, 0], index=df.index)},
            initial_capital=100_000.0, allocation_pct=1.0,
            spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"},
        )
        row = pd.DataFrame(res["trade_log"]).iloc[0]
        assert row["entry_RSI_14"] == pytest.approx(22.0)   # bar 1 (signal == fill bar)
