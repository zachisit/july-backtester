"""Same-bar re-entry in the shared portfolio engine (private-strategies #135).

The engine deletes exited symbols from `positions` (portfolio_simulations.py:692)
BEFORE the entry loop runs (:1137), and the entry condition tests signal LEVEL
(:1157, `== 1`) rather than a transition. So a hold-state signal -- 1 across the
whole hold, forward-filled -- reads 1 on the bar a stop fires, the guard at :1151
sees the symbol as unheld, and the engine re-buys on the same bar it just
stopped out of. The comment at :1148-1150 documents this path as intended for
short-cover-then-long; it is the same door.

Pulse signals (1 on the entry bar only) are not exposed, which is why Donchian
is safe and why the golden master never saw it. Any hold-state strategy with an
engine-level stop is.

These tests are written to FAIL on the current engine. They are the measured
answer to #135 item 3, and they flip to passing when the engine refuses entry
on a bar that closed a trade.
"""
import pandas as pd
import pytest
from unittest.mock import patch

from tests.test_engine_characterization import _df, _sig, _BASE_CFG
from helpers.portfolio_simulations import run_portfolio_simulation

CLOSES = [100, 101, 102, 101, 100, 94, 95, 96, 97, 98]
STOP = {"type": "percentage", "value": 0.05}


def _run(sig):
    df = _df(CLOSES)
    with patch.dict("config.CONFIG", _BASE_CFG, clear=False):
        r = run_portfolio_simulation(
            portfolio_data={"BBB": df}, signals={"BBB": sig},
            initial_capital=100_000.0, allocation_pct=0.10,
            spy_df=None, vix_df=None, tnx_df=None, stop_config=STOP)
    return pd.DataFrame(r["trade_log"]) if r and r.get("trade_log") else pd.DataFrame()


def test_pulse_signal_does_not_reenter_after_stop():
    """Control: 1 on the entry bar only. Stop fires, nothing re-enters."""
    tl = _run(_sig(_df(CLOSES), {1: 1}))
    assert len(tl) == 1
    assert tl.iloc[0]["ExitReason"].startswith("Stop Loss")


@pytest.mark.xfail(strict=True, reason=(
    "#135 item 3: engine re-enters on the bar it stopped out of. Exits are "
    "deleted from `positions` at :692 before the entry loop at :1137, and the "
    "entry test at :1157 is signal LEVEL == 1, so a hold-state signal re-buys "
    "the same bar. Measured: stop-out at 95.95 then re-buy at 94.05 on "
    "2023-01-09. Flip this to a plain test when the engine refuses entry on a "
    "bar that closed a trade."))
def test_hold_state_signal_does_not_reenter_on_the_stop_bar():
    """A trade may not open on the bar that just closed one -- that requires an
    intrabar path (stop, then back to trigger) that bar data cannot show."""
    df = _df(CLOSES)
    tl = _run(_sig(df, {i: 1 for i in range(1, len(CLOSES))}))
    assert len(tl) == 1, (
        f"{len(tl)} trades; trade 2 entered {tl.iloc[1]['EntryDate']} "
        f"on the bar trade 1 exited {tl.iloc[0]['ExitDate']}")


def test_hold_state_reentry_is_on_the_exit_bar_specifically():
    """Documents the CURRENT defect precisely, so the fix is verifiable: the
    second entry lands on exactly the first exit's bar, at a price below the
    stop fill. Delete this test when the xfail above flips."""
    df = _df(CLOSES)
    tl = _run(_sig(df, {i: 1 for i in range(1, len(CLOSES))}))
    assert len(tl) == 2
    assert tl.iloc[1]["EntryDate"] == tl.iloc[0]["ExitDate"]
    assert tl.iloc[1]["EntryPrice"] < tl.iloc[0]["ExitPrice"]
