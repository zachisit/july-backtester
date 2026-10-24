"""Opening Kelly orders must not learn outcomes later in their fill bar (#466)."""
import logging
from unittest.mock import patch

import pandas as pd
import pytest

from helpers import portfolio_simulations as ps


def _target_size(mode, side, symbol, stopped, history_count):
    idx = pd.bdate_range("2024-01-02", periods=3 * history_count + 13)
    stop_entry = 3 * history_count + 3
    target_fill = stop_entry + 2
    final_exit = target_fill + 3

    def frame():
        return pd.DataFrame({
            "Open": 100., "High": 101., "Low": 99., "Close": 100.,
            "Volume": 1e6, "ATR_14": 1.,
        }, index=idx)

    history, stop_position, target = frame(), frame(), frame()
    history_signals = pd.Series(0, index=idx)
    for i in range(history_count):
        history_signals.iloc[3 * i] = 1
        history_signals.iloc[3 * i + 1] = -1
        exit_bar = 3 * i + (2 if mode == "open" else 1)
        price = 103. if i % 3 else 98.
        history.loc[idx[exit_bar], "Open" if mode == "open" else "Close"] = price
        history.loc[idx[exit_bar], ["High", "Low"]] = [
            max(101., price + 1), min(99., price - 1),
        ]
    if stopped:
        stop_position.loc[idx[target_fill], "Low"] = 94.
    stop_signals = pd.Series(0, index=idx)
    stop_signals.iloc[stop_entry], stop_signals.iloc[final_exit] = 1, -1
    target_signals = pd.Series(0, index=idx)
    target_signals.iloc[target_fill - 1 if mode == "open" else target_fill] = side
    target_signals.iloc[final_exit] = -1
    config = {
        "execution_time": mode, "entry_trigger": "edge",
        "position_sizing_method": "kelly", "kelly_fraction": .25,
        "max_portfolio_heat": 100., "max_pct_adv": 0.,
        "volume_impact_coeff": 0., "slippage_pct": 0.,
        "commission_per_share": 0., "htb_rate_annual": 0.,
        "exclude_open_positions": False, "include_delisted": False,
        "entry_priority": "alphabetical",
        "instruments": {
            "default_asset_class": "equity", "overrides": {},
            "futures_initial_margin_pct": .1,
            "futures_commission_per_contract": 0., "futures_slippage_ticks": 0.,
        },
    }
    with patch.dict(ps.CONFIG, config):
        result = ps.run_portfolio_simulation(
            {"HISTORY": history, "ASTOP": stop_position, symbol: target},
            {"HISTORY": history_signals, "ASTOP": stop_signals, symbol: target_signals},
            100000., .1, None, None, None, {"type": "percentage", "value": .05},
        )
    trades = [t for t in result["trade_log"] if t["Symbol"] == symbol]
    assert len(trades) == 1, (mode, side, symbol, trades)
    return trades[0]["Shares"]


@pytest.mark.parametrize("history_count", [9, 12])
@pytest.mark.parametrize("side,symbol", [
    (1, "TARGET"), (-2, "TARGET"), (1, "MESZ6"), (-2, "MESZ6"),
])
def test_open_kelly_ignores_later_intrabar_exit(side, symbol, history_count, caplog):
    caplog.set_level(logging.ERROR)
    # Only ASTOP's Low changes; the open, close, and sizing equity are identical.
    control = _target_size("open", side, symbol, False, history_count)
    stopped = _target_size("open", side, symbol, True, history_count)
    assert stopped == pytest.approx(control)


@pytest.mark.parametrize("side,symbol", [
    (1, "TARGET"), (-2, "TARGET"), (1, "MESZ6"), (-2, "MESZ6"),
])
def test_close_kelly_can_use_completed_intrabar_exit(side, symbol, caplog):
    caplog.set_level(logging.ERROR)
    assert _target_size("close", side, symbol, True, 9) != pytest.approx(
        _target_size("close", side, symbol, False, 9))
