"""
Issue #436: the ADV liquidity cap / market impact must use only volume known
at order time.

Under execution_time="open" the fill is at the bar's open, so the fill bar's
full-session volume is look-ahead; ADV is taken as of the PRIOR bar. Under
"close" the fill is the bar's last print, so the same bar is used.
The first bar of a symbol (no prior bar) falls back to the same-bar value so
the cap is never silently removed.
"""

import os
import sys

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from test_daily_adv_memoization import _daily_df, _run  # noqa: E402

BASE_VOL = 20_000.0
SPIKE_VOL = 2_000_000.0
SIG_IDX = 40


def _spiked_df(spike_idx):
    df = _daily_df(BASE_VOL)
    df.iloc[spike_idx, df.columns.get_loc("Volume")] = SPIKE_VOL
    return df


def _expected_adv(df, idx):
    return df["Volume"].rolling(window=20, min_periods=1).mean().iloc[idx]


class TestOpenExecutionUsesPriorBar:
    def test_spike_on_fill_bar_does_not_raise_cap(self):
        df = _spiked_df(SIG_IDX + 1)  # fill bar under open execution
        res = _run(df, entry_idx=SIG_IDX, execution_time="open")
        trade = res["trade_log"][0]
        assert trade["Shares"] == pytest.approx(BASE_VOL * 0.05, rel=1e-9)

    def test_spike_on_prior_bar_is_known_and_counts(self):
        df = _spiked_df(SIG_IDX)  # signal bar == prior bar to the fill bar
        res = _run(df, entry_idx=SIG_IDX, execution_time="open")
        trade = res["trade_log"][0]
        assert trade["Shares"] == pytest.approx(_expected_adv(df, SIG_IDX) * 0.05, rel=1e-9)

    def test_market_impact_ignores_fill_bar_spike(self):
        calm = _run(_daily_df(BASE_VOL), entry_idx=SIG_IDX, execution_time="open",
                    volume_impact_coeff=0.1)["trade_log"][0]
        spiked = _run(_spiked_df(SIG_IDX + 1), entry_idx=SIG_IDX, execution_time="open",
                      volume_impact_coeff=0.1)["trade_log"][0]
        assert spiked["Shares"] == pytest.approx(calm["Shares"])
        assert spiked["EntryPrice"] == pytest.approx(calm["EntryPrice"])
        assert calm["EntryPrice"] > 1.0  # impact is actually active


class TestCloseExecutionUsesSameBar:
    def test_spike_on_fill_bar_counts(self):
        df = _spiked_df(SIG_IDX)  # fill bar == signal bar under close
        res = _run(df, entry_idx=SIG_IDX, execution_time="close")
        trade = res["trade_log"][0]
        assert trade["Shares"] == pytest.approx(_expected_adv(df, SIG_IDX) * 0.05, rel=1e-9)


class TestFirstBarFallback:
    def test_first_fill_bar_is_still_capped(self):
        # Close execution on bar 0 is same-bar by design. Open execution on
        # bar 0 fills on bar 1 and uses bar 0's ADV. Neither is uncapped.
        df = _daily_df(BASE_VOL)
        res = _run(df, entry_idx=0, execution_time="close")
        assert res["trade_log"][0]["Shares"] == pytest.approx(BASE_VOL * 0.05, rel=1e-9)
        res = _run(df, entry_idx=0, execution_time="open")
        assert res["trade_log"][0]["Shares"] == pytest.approx(BASE_VOL * 0.05, rel=1e-9)
