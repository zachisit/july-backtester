# tests/test_scaled_exits.py
"""
Tests for partial / scaled exits (Phase 4 of the instrument-metadata rewrite, #229).

A strategy emits a fractional exit signal -1 < s < 0 to scale OUT abs(s) of the
open position, keeping the remainder. Full exit remains s <= -1.

  TestEquityPartial   — 50% scale-out then full exit on an equity long
  TestFuturesPartial  — integer-contract scale-out on a futures long
  TestGuards          — single-contract futures can't partial; s<=-1 still full exits
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.portfolio_simulations import run_portfolio_simulation

_BASE = {
    "slippage_pct": 0.0005, "commission_per_share": 0.002, "execution_time": "close",
    "risk_free_rate": 0.05, "htb_rate_annual": 0.0, "volume_impact_coeff": 0.0,
    "max_pct_adv": 0.0, "position_sizing_method": "fixed", "target_risk_per_trade": 0.02,
    "max_portfolio_heat": 1.0, "entry_priority": "alphabetical",
    "exclude_open_positions": False, "include_delisted": False,
    "instruments": {"default_asset_class": "equity",
                    "futures_initial_margin_pct": 0.10,
                    "futures_commission_per_contract": 2.50,
                    "futures_slippage_ticks": 1.0, "overrides": {}},
}


def _df(closes):
    closes = np.asarray(closes, dtype=float)
    idx = pd.bdate_range("2023-01-02", periods=len(closes))
    idx.name = "Datetime"
    return pd.DataFrame({"Open": closes, "High": closes * 1.002, "Low": closes * 0.998,
                         "Close": closes, "Volume": np.full(len(closes), 1e6)}, index=idx)


def _sig(df, pairs):
    s = pd.Series(0.0, index=df.index, dtype=float)
    for i, v in pairs.items():
        s.iloc[i] = v
    return s


def _run(portfolio_data, signals, cfg_over=None, initial_capital=100_000.0, allocation_pct=0.10):
    from unittest.mock import patch
    cfg = {**_BASE, **(cfg_over or {})}
    with patch.dict("config.CONFIG", cfg, clear=False):
        return run_portfolio_simulation(
            portfolio_data=portfolio_data, signals=signals,
            initial_capital=initial_capital, allocation_pct=allocation_pct,
            spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"})


class TestEquityPartial:
    def test_half_scaleout_then_full(self):
        df = _df([100, 101, 102, 103, 104, 105, 106])
        res = _run({"AAA": df}, {"AAA": _sig(df, {1: 1, 3: -0.5, 5: -1})})
        assert res is not None
        partials = [t for t in res["trade_log"] if t["ExitReason"] == "Partial Scale-Out"]
        fulls = [t for t in res["trade_log"] if t["ExitReason"] != "Partial Scale-Out"]
        assert len(partials) == 1 and len(fulls) == 1
        # 50% out then the remaining 50% -> the two legs carry equal share counts.
        assert partials[0]["Shares"] == pytest.approx(fulls[0]["Shares"], rel=1e-6)
        assert partials[0]["Trade"].endswith("(partial)")


class TestFuturesPartial:
    def test_integer_contract_scaleout(self):
        # MES @ ~2400, alloc 1.0: margin-based sizing floors
        # equity*alloc / (margin_pct * point_value * entry_price) to whole
        # contracts (see test_futures_engine.py::TestIntegerContracts::
        # test_fractional_size_floored for the equivalent full-entry assertion);
        # -0.5 then scales out half of those contracts, also floored.
        import math
        df = _df([2400, 2400, 2400, 2400, 2400, 2400])
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1, 3: -0.5, 5: -1})},
                   allocation_pct=1.0)
        assert res is not None
        partials = [t for t in res["trade_log"] if t["ExitReason"] == "Partial Scale-Out"]
        assert len(partials) == 1
        p = partials[0]
        total_contracts = float(math.floor(
            100_000.0 * 1.0 / (0.10 * 5.0 * p["EntryPrice"])))
        assert p["Shares"] == float(int(p["Shares"]))  # whole contracts
        assert p["Shares"] == float(math.floor(total_contracts * 0.5))
        total = sum(t["Shares"] for t in res["trade_log"])
        assert total == total_contracts  # scaled-out leg + closed remainder


class TestGuards:
    def test_single_contract_cannot_partial(self):
        # Margin-based sizing (see TestFuturesPartial) floors
        # equity*alloc / (margin_pct * point_value * entry_price) to whole
        # contracts; 1800 @ ~2400 -> 1800 / (0.10*5*2401.2) ~= 1.499 -> 1
        # contract. -0.5 of 1 contract rounds down to 0 -> no partial leg.
        df = _df([2400, 2400, 2400, 2400, 2400])
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1, 2: -0.5, 4: -1})},
                   initial_capital=1_800.0, allocation_pct=1.0)
        assert res is not None
        assert not any(t["ExitReason"] == "Partial Scale-Out" for t in res["trade_log"])
        assert len(res["trade_log"]) == 1  # just the full exit
        assert res["trade_log"][0]["Shares"] == 1.0  # sizing floored to exactly 1 contract

    def test_full_exit_signal_unchanged(self):
        # s == -1 still fully exits in one leg (no partial).
        df = _df([100, 101, 102, 103, 104])
        res = _run({"AAA": df}, {"AAA": _sig(df, {1: 1, 3: -1})})
        assert res is not None
        assert len(res["trade_log"]) == 1
        assert res["trade_log"][0]["ExitReason"] != "Partial Scale-Out"
