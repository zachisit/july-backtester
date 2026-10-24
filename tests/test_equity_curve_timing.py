# tests/test_equity_curve_timing.py
"""Issue #438: the equity-curve point for a bar must reflect that bar's fills
(snapshot at END of bar), while sizing still uses start-of-bar equity."""
import os
import sys

import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from unittest.mock import patch

from helpers.portfolio_simulations import run_portfolio_simulation

_CFG = {
    "slippage_pct": 0.0, "commission_per_share": 0.0, "execution_time": "open",
    "risk_free_rate": 0.0, "htb_rate_annual": 0.0, "volume_impact_coeff": 0.0,
    "max_pct_adv": 0.0, "position_sizing_method": "fixed", "max_portfolio_heat": 1.0,
    "entry_priority": "alphabetical", "exclude_open_positions": False,
    "include_delisted": False,
}


def _frame(opens, closes, lows=None, highs=None):
    idx = pd.bdate_range("2024-01-01", periods=len(opens))
    idx.name = "Datetime"
    return pd.DataFrame({
        "Open": opens, "Close": closes,
        "High": highs if highs is not None else [max(o, c) for o, c in zip(opens, closes)],
        "Low": lows if lows is not None else [min(o, c) for o, c in zip(opens, closes)],
        "Volume": 1e9,
    }, index=idx)


def _run(df, sig, stop=None, alloc=1.0):
    signals = {"AAA": pd.Series(sig, index=df.index, dtype=int)}
    with patch.dict("helpers.portfolio_simulations.CONFIG", _CFG, clear=False):
        return run_portfolio_simulation(
            portfolio_data={"AAA": df}, signals=signals, initial_capital=100_000.0,
            allocation_pct=alloc, spy_df=None, vix_df=None, tnx_df=None,
            stop_config=stop or {"type": "none"})


def test_open_exit_gain_recorded_on_exit_bar():
    # Signal d0 -> buy at d1 open (100); signal d2 -> sell at d3 open (120), d3 close 100.
    df = _frame([100, 100, 100, 120, 100, 100], [100, 100, 100, 100, 100, 100])
    res = _run(df, [1, 0, -1, 0, 0, 0])
    tl = res["portfolio_timeline"]
    assert res["trade_log"][0]["Profit"] == 20000.0
    assert tl.loc[df.index[3]] == 120000.0   # realised on the exit bar, not a bar late
    assert tl.loc[df.index[4]] == 120000.0


def test_entry_bar_is_valued_in_that_bars_equity():
    # Buy at d1 open 100, d1 close 110 -> equity on d1 includes the position.
    df = _frame([100, 100, 110, 110], [100, 110, 110, 110])
    res = _run(df, [1, 0, 0, 0])
    tl = res["portfolio_timeline"]
    assert tl.loc[df.index[0]] == 100000.0
    assert tl.loc[df.index[1]] == 110000.0


def test_stop_exit_does_not_record_further_fall():
    # Hold from d1; d3 gaps down through the 5% stop (fill at open 90) then keeps
    # falling to close 50. The curve must stay at the realised 90000.
    df = _frame([100, 100, 100, 90, 50, 40], [100, 100, 100, 50, 40, 30])
    res = _run(df, [1, 0, 0, 0, 0, 0], stop={"type": "percentage", "value": 0.05})
    tl = res["portfolio_timeline"]
    assert res["trade_log"][0]["ExitReason"].startswith("Stop Loss")
    exit_px = res["trade_log"][0]["ExitPrice"]
    expected = 100_000.0 + (exit_px - 100.0) * res["trade_log"][0]["Shares"]
    assert abs(tl.loc[df.index[3]] - expected) < 1e-6
    assert tl.loc[df.index[4]] == tl.loc[df.index[3]]
    assert tl.loc[df.index[5]] == tl.loc[df.index[3]]


def test_same_bar_round_trip_is_realised_on_that_bar():
    # Buy at d1 open 100; d1 Low breaches the 5% stop -> opened and closed on d1.
    df = _frame([100, 100, 100, 100], [100, 100, 100, 100],
                lows=[100, 80, 100, 100], highs=[100, 100, 100, 100])
    res = _run(df, [1, 0, 0, 0], stop={"type": "percentage", "value": 0.05})
    t = res["trade_log"][0]
    tl = res["portfolio_timeline"]
    assert t["EntryDate"] == t["ExitDate"]
    assert abs(tl.loc[df.index[1]] - (100_000.0 + t["Profit"])) < 1e-6


def test_sizing_uses_start_of_bar_equity():
    # Two sequential trades; second entry sizes off cash+MTM at start of its bar.
    df = _frame([100, 100, 100, 120, 120, 120, 120], [100, 100, 100, 100, 120, 120, 120])
    res = _run(df, [1, 0, -1, 0, 1, 0, 0], alloc=0.5)
    # After exit at 120 the 50% trade earned +10000; second buy at d5 open=120
    # sizes off 110000 equity (55000 / 120 shares), unaffected by the snapshot.
    assert abs(res["trade_log"][1]["Shares"] - 55000 / 120) < 1e-6 or \
        res["trade_log"][1]["Shares"] == int(55000 / 120)
