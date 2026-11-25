# tests/test_open_sizing_equity.py
"""Issue #490: under execution_time="open", entries fill at the bar's Open and
must be sized from equity that is known at the open. Held positions are marked
at that bar's Open (prior close when the bar or its Open is missing), never at
the same bar's Close. Under execution_time="close" the fill is the bar's last
print, so close-marked sizing equity remains correct and is unchanged.

The recorded timeline point is the post-trade, close-marked equity (issue #438);
the two-symbol test below pins that alongside the sizing change."""
import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.portfolio_simulations import run_portfolio_simulation

_CFG = {
    "slippage_pct": 0.0, "commission_per_share": 0.0, "execution_time": "open",
    "risk_free_rate": 0.0, "htb_rate_annual": 0.0, "volume_impact_coeff": 0.0,
    "max_pct_adv": 0.0, "position_sizing_method": "fixed", "max_portfolio_heat": 1.0,
    "entry_priority": "alphabetical", "exclude_open_positions": False,
    "include_delisted": False,
}
_IDX = pd.bdate_range("2024-01-01", periods=6, name="Datetime")


def _frame(opens, closes, idx=_IDX):
    return pd.DataFrame({
        "Open": opens, "Close": closes,
        "High": [max(o, c) for o, c in zip(opens, closes)],
        "Low": [min(o, c) for o, c in zip(opens, closes)],
        "Volume": 1e9,
    }, index=idx)


def _run(data, sigs, alloc, execution_time="open"):
    signals = {s: pd.Series(v, index=data[s].index, dtype=int) for s, v in sigs.items()}
    cfg = {**_CFG, "execution_time": execution_time}
    with patch.dict("helpers.portfolio_simulations.CONFIG", cfg, clear=False):
        return run_portfolio_simulation(
            portfolio_data=data, signals=signals, initial_capital=100_000.0,
            allocation_pct=alloc, spy_df=None, vix_df=None, tnx_df=None,
            stop_config={"type": "none"})


def _trade(res, symbol):
    return next(t for t in res["trade_log"] if t["Symbol"] == symbol)


# --- (a) sizing must not see the fill bar's Close --------------------------

def _gap_book(aaa_close_d3):
    # AAA: signal d0 -> buy d1 open 100 (25% of 100k = 250 sh); held all run.
    # d3: AAA opens 100 and closes at `aaa_close_d3` (the open->close gap).
    # BBB: signal d2 -> buy d3 open 50, sized at that open.
    aaa = _frame([100, 100, 100, 100, 100, 100],
                 [100, 100, 100, aaa_close_d3, 100, 100])
    bbb = _frame([50] * 6, [50] * 6)
    return _run({"AAA": aaa, "BBB": bbb},
                {"AAA": [1, 0, 0, 0, 0, 0], "BBB": [0, 0, 1, 0, 0, 0]},
                alloc=0.25)


def test_open_entry_sized_from_open_marked_equity():
    res = _gap_book(aaa_close_d3=200)
    assert _trade(res, "AAA")["Shares"] == 250.0
    # Equity at the d3 open = 75,000 cash + 250 * 100 (AAA's d3 Open) = 100,000
    # -> 25% / 50 = 500 sh. Marking AAA at its d3 Close (200) gave 125,000 -> 625.
    assert _trade(res, "BBB")["Shares"] == 500.0


def test_open_entry_size_is_invariant_to_same_bar_close():
    shares = {c: _trade(_gap_book(aaa_close_d3=c), "BBB")["Shares"] for c in (20, 100, 200)}
    assert len(set(shares.values())) == 1, shares


def test_open_entry_uses_prior_close_when_held_symbol_has_no_bar():
    # AAA has no d3 bar: its last known price at the d3 open is the d2 Close (120).
    idx_aaa = _IDX.delete(3)
    aaa = _frame([100, 100, 100, 100, 100], [100, 100, 120, 300, 300], idx=idx_aaa)
    bbb = _frame([50] * 6, [50] * 6)
    res = _run({"AAA": aaa, "BBB": bbb},
               {"AAA": [1, 0, 0, 0, 0], "BBB": [0, 0, 1, 0, 0, 0]}, alloc=0.25)
    # 75,000 + 250 * 120 = 105,000 -> 26,250 / 50 = 525 sh.
    assert _trade(res, "BBB")["Shares"] == 525.0


def test_open_entry_ignores_nan_open_and_falls_back_to_prior_close():
    aaa = _frame([100, 100, 100, 100, 100, 100], [100, 100, 120, 200, 100, 100])
    aaa.loc[_IDX[3], "Open"] = np.nan
    bbb = _frame([50] * 6, [50] * 6)
    res = _run({"AAA": aaa, "BBB": bbb},
               {"AAA": [1, 0, 0, 0, 0, 0], "BBB": [0, 0, 1, 0, 0, 0]}, alloc=0.25)
    assert _trade(res, "BBB")["Shares"] == 525.0


def test_close_execution_still_sizes_from_close_marked_equity():
    # Under "close" the BBB order fills at the d2 close, after AAA's d2 Close is
    # known: AAA bought at d0 close 100 (250 sh), d2 close 200 ->
    # 75,000 + 250 * 200 = 125,000 -> 31,250 / 50 = 625 sh.
    aaa = _frame([100] * 6, [100, 100, 200, 200, 200, 200])
    bbb = _frame([50] * 6, [50] * 6)
    res = _run({"AAA": aaa, "BBB": bbb},
               {"AAA": [1, 0, 0, 0, 0, 0], "BBB": [0, 0, 1, 0, 0, 0]},
               alloc=0.25, execution_time="close")
    assert _trade(res, "BBB")["Shares"] == 625.0


# --- (b) recorded equity is post-trade, marked at the close -----------------

def test_exit_and_entry_bar_recorded_post_trade_at_close():
    # AAA: buy d1 open 100 (250 sh at 25%); signal d2 -> sell at d3 open 120,
    #      d3 close 60 (the sold shares must not be marked at 60).
    # BBB: signal d2 -> buy at d3 open 50, d3 close 80 (the new shares must be
    #      marked at 80 on d3, not a bar late).
    aaa = _frame([100, 100, 100, 120, 60, 60], [100, 100, 100, 60, 60, 60])
    bbb = _frame([50, 50, 50, 50, 80, 80], [50, 50, 50, 80, 80, 80])
    res = _run({"AAA": aaa, "BBB": bbb},
               {"AAA": [1, 0, -1, 0, 0, 0], "BBB": [0, 0, 1, 0, 0, 0]}, alloc=0.25)
    a, b = _trade(res, "AAA"), _trade(res, "BBB")
    assert a["ExitPrice"] == 120.0 and a["Profit"] == 5_000.0
    # Sizing at the d3 open: 75,000 cash + 250 * 120 (AAA's d3 Open) = 105,000
    # -> 26,250 / 50 = 525 sh.
    assert b["Shares"] == 525.0
    tl = res["portfolio_timeline"]
    # d3 close: cash = 75,000 + 30,000 - 26,250 = 78,750; BBB 525 * 80 = 42,000.
    assert tl.loc[_IDX[2]] == 100_000.0
    assert tl.loc[_IDX[3]] == 78_750.0 + 525 * 80.0
