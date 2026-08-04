# tests/test_sizing_methods.py
"""
Unit/integration coverage for the two inline futures position-sizing methods
added directly in helpers/portfolio_simulations.py -- `risk_pct_capped` and
`fixed_contracts`. Both bypass helpers/position_sizing.py::calculate_position_size
entirely, so they have no unit-test coverage there; these tests exercise them
end-to-end via run_portfolio_simulation with synthetic single-symbol data
(#238 review item #3).

  TestRiskPctCapped  -- compounding risk-percent-of-equity sizing math + cap
  TestFixedContracts -- fixed contract-count sizing, never equity-scaled
"""

import math
import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.portfolio_simulations import run_portfolio_simulation

_PV = 5.0        # MES $/point
_MARGIN_PCT = 0.10

_BASE_CFG = {
    "slippage_pct": 0.0005,
    "commission_per_share": 0.002,
    "execution_time": "close",
    "risk_free_rate": 0.05,
    "htb_rate_annual": 0.0,
    "volume_impact_coeff": 0.0,
    "max_pct_adv": 0.0,
    "target_risk_per_trade": 0.02,
    "max_portfolio_heat": 1.0,
    "entry_priority": "alphabetical",
    "exclude_open_positions": False,
    "include_delisted": False,
    "instruments": {
        "default_asset_class": "equity",
        "futures_initial_margin_pct": _MARGIN_PCT,
        "futures_commission_per_contract": 2.50,
        "futures_slippage_ticks": 1.0,
        "overrides": {},
    },
}


def _df(closes, start="2023-01-02"):
    n = len(closes)
    closes = np.asarray(closes, dtype=float)
    idx = pd.bdate_range(start=start, periods=n, freq="B")
    idx.name = "Datetime"
    return pd.DataFrame({
        "Open": closes, "High": closes * 1.002, "Low": closes * 0.998,
        "Close": closes, "Volume": np.full(n, 1_000_000.0),
    }, index=idx)


def _sig(df, pairs):
    s = pd.Series(0, index=df.index, dtype=int)
    for i, v in pairs.items():
        s.iloc[i] = v
    return s


def _run(portfolio_data, signals, stop_config, cfg_over,
         initial_capital=100_000.0, allocation_pct=1.0):
    cfg = {**_BASE_CFG, **cfg_over}
    with patch.dict("config.CONFIG", cfg, clear=False):
        return run_portfolio_simulation(
            portfolio_data=portfolio_data, signals=signals,
            initial_capital=initial_capital, allocation_pct=allocation_pct,
            spy_df=None, vix_df=None, tnx_df=None, stop_config=stop_config,
        )


class TestRiskPctCapped:
    """position_sizing_method == "risk_pct_capped": contracts = floor(
    (equity * risk_pct_per_trade) / (stop_dist_pts * point_value)), capped at
    max_contracts_cap. Verified here against the "percentage" stop type, where
    stop_dist_pts = stop value fraction * raw (pre-slippage) entry price."""

    def test_contracts_match_risk_budget_formula(self):
        df = _df([5000, 5000, 5010, 5020, 5030])
        cfg = {
            "position_sizing_method": "risk_pct_capped",
            "risk_pct_per_trade": 0.01,
            "max_contracts_cap": 20,
        }
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1, 3: -1})},
                   stop_config={"type": "percentage", "value": 0.02}, cfg_over=cfg)
        assert res is not None
        assert len(res["trade_log"]) == 1
        t = res["trade_log"][0]

        raw_entry = df["Close"].iloc[1]  # signal bar's raw (pre-slippage) Close
        risk_budget = 100_000.0 * 0.01
        stop_dist_pts = 0.02 * raw_entry
        expected_contracts = float(math.floor(risk_budget / (stop_dist_pts * _PV)))

        assert expected_contracts > 0, "test fixture must produce a non-trivial contract count"
        assert t["Shares"] == expected_contracts
        assert t["Shares"] == float(int(t["Shares"]))  # whole contracts

    def test_max_contracts_cap_is_enforced(self):
        # Same setup but a much larger risk_pct_per_trade drives the raw
        # (uncapped) contract count well above max_contracts_cap.
        df = _df([5000, 5000, 5010, 5020, 5030])
        cfg = {
            "position_sizing_method": "risk_pct_capped",
            "risk_pct_per_trade": 0.5,   # 50% of equity risked -> huge raw count
            "max_contracts_cap": 3,
        }
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1, 3: -1})},
                   stop_config={"type": "percentage", "value": 0.02}, cfg_over=cfg)
        assert res is not None
        assert len(res["trade_log"]) == 1
        assert res["trade_log"][0]["Shares"] == 3.0

    def test_zero_stop_distance_yields_no_position(self):
        # stop_config type "none" -> _rp_stop_dist_pts stays None -> shares == 0
        # -> the entry is skipped entirely (mirrors the sizing method's own
        # "else: shares = 0.0" guard, then the "if shares < 1: continue" futures
        # entry guard). With zero trades ever opened, run_portfolio_simulation
        # returns None (see the `if not pnl_list: return None` guard).
        df = _df([5000, 5000, 5010, 5020, 5030])
        cfg = {
            "position_sizing_method": "risk_pct_capped",
            "risk_pct_per_trade": 0.01,
            "max_contracts_cap": 20,
        }
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1, 3: -1})},
                   stop_config={"type": "none"}, cfg_over=cfg)
        assert res is None


class TestFixedContracts:
    """position_sizing_method == "fixed_contracts": exactly N contracts every
    trade, forever -- never scaled to equity (unlike risk_pct_capped, which
    compounds with account growth)."""

    def test_every_trade_sizes_to_fixed_count(self):
        df = _df([5000, 5000, 5010, 5020, 5030])
        cfg = {
            "position_sizing_method": "fixed_contracts",
            "fixed_contracts_per_trade": 3,
        }
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1, 3: -1})},
                   stop_config={"type": "none"}, cfg_over=cfg)
        assert res is not None
        assert len(res["trade_log"]) == 1
        assert res["trade_log"][0]["Shares"] == 3.0

    def test_contract_count_independent_of_equity(self):
        # A much smaller starting equity should still open the same fixed
        # contract count as long as margin + commission fit in cash (i.e. this
        # is genuinely NOT equity-scaled, unlike risk_pct_capped or "fixed").
        df = _df([5000, 5000, 5010, 5020, 5030])
        cfg = {
            "position_sizing_method": "fixed_contracts",
            "fixed_contracts_per_trade": 2,
        }
        res_small = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1, 3: -1})},
                          stop_config={"type": "none"}, cfg_over=cfg,
                          initial_capital=10_000.0)
        res_large = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1, 3: -1})},
                          stop_config={"type": "none"}, cfg_over=cfg,
                          initial_capital=1_000_000.0)
        assert res_small is not None and res_large is not None
        assert res_small["trade_log"][0]["Shares"] == 2.0
        assert res_large["trade_log"][0]["Shares"] == 2.0
