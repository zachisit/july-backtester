# tests/test_position_sizing_consolidation.py
"""
#384 (part of #381) — `calculate_position_size` is the single sizing entry point.

Before this change the long path was a three-way dispatch and only the third arm
reached `calculate_position_size`; `risk_pct_capped` and `fixed_contracts` were
open-coded there, and open-coded AGAIN on the futures-short path. Four copies of
two methods, none of them in the sizing module — so calling the module directly
with either name produced "Unknown position sizing method", which is wrong on its
face for two documented, validated KNOWN_KEYS values.

What is pinned here
-------------------
  TestAllSixMethodsAreImplemented   no method emits the unknown-method warning
  TestRiskPctCappedArithmetic       floor / cap / point_value / no-stop behaviour
  TestFixedContractsArithmetic      constant count, never equity-scaled
  TestPointsIsThePrimitive          risk_parity accepts points and converts
  TestUnitCountMethodsSkipConversion  the one load-bearing branch the refactor kept
  TestLongAndShortShareTheFunction  the futures-short mirrors are gone

The unit-count gate (`TestUnitCountMethodsSkipConversion`) is the only piece of
the old dispatch that was NOT duplication: `risk_pct_capped` and
`fixed_contracts` answer in contracts, the other four answer in dollars, so only
the dollar answers get the point_value / margin_required conversion. Deleting
that gate doubles a futures `fixed_contracts` position (3 -> 6 contracts) and the
test below dies when it is removed.
"""

import logging
import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.position_sizing import (  # noqa: E402
    _fixed_contracts,
    _risk_pct_capped,
    calculate_position_size,
)
from helpers.portfolio_simulations import run_portfolio_simulation  # noqa: E402

ALL_METHODS = ("fixed", "kelly", "vol_parity", "risk_parity",
               "risk_pct_capped", "fixed_contracts")

_CFG = {
    "allocation_per_trade": 0.10,
    "target_risk_per_trade": 0.02,
    "risk_pct_per_trade": 0.01,
    "max_contracts_cap": 20,
    "fixed_contracts_per_trade": 3,
}


@pytest.fixture
def caplog_sizing(caplog):
    caplog.set_level(logging.WARNING, logger="helpers.position_sizing")
    return caplog


# ---------------------------------------------------------------------------
class TestAllSixMethodsAreImplemented:
    """The #384 acceptance criterion."""

    @pytest.mark.parametrize("method", ALL_METHODS)
    def test_no_unknown_method_warning(self, method, caplog_sizing):
        df = pd.DataFrame({"ATR_14": [2.0, 2.0, 2.0]})
        calculate_position_size(
            method=method, equity=100_000.0, price=100.0, symbol_data=df,
            config=_CFG, allocation_pct=0.10,
            win_rate=0.55, avg_win=0.10, avg_loss=0.05,
            stop_distance_pct=0.05, stop_distance_points=5.0, point_value=1.0,
        )
        assert "Unknown position sizing method" not in caplog_sizing.text

    def test_an_actually_unknown_method_still_warns(self, caplog_sizing):
        """The warning is not simply gone — it still fires for a real typo."""
        df = pd.DataFrame({"ATR_14": [2.0]})
        calculate_position_size(method="risk_pct_capepd", equity=100_000.0,
                                price=100.0, symbol_data=df, config=_CFG)
        assert "Unknown position sizing method" in caplog_sizing.text


# ---------------------------------------------------------------------------
class TestRiskPctCappedArithmetic:

    def test_budget_divided_by_stop_dollars(self):
        # 1% of 100k = $1,000 budget; $10/point stop x pv 1 -> 100 units,
        # under the 20 cap only if we raise it.
        cfg = {**_CFG, "max_contracts_cap": 1000}
        got = _risk_pct_capped(100_000.0, cfg,
                               stop_distance_points=10.0, point_value=1.0)
        assert got == pytest.approx(100.0)

    def test_point_value_scales_the_denominator(self):
        cfg = {**_CFG, "max_contracts_cap": 1000}
        got = _risk_pct_capped(100_000.0, cfg,
                               stop_distance_points=10.0, point_value=5.0)
        assert got == pytest.approx(20.0)  # 1000 / (10 * 5)

    def test_cap_binds(self):
        got = _risk_pct_capped(100_000.0, _CFG,
                               stop_distance_points=1.0, point_value=1.0)
        assert got == 20  # 1000 units wanted, capped

    def test_result_is_floored_not_rounded(self):
        cfg = {**_CFG, "max_contracts_cap": 1000}
        # 1000 / 350.18 = 2.856 -> 2, not 3
        got = _risk_pct_capped(100_000.0, cfg,
                               stop_distance_points=350.18, point_value=1.0)
        assert got == pytest.approx(2.0)

    def test_compounds_with_equity_below_the_cap(self):
        cfg = {**_CFG, "max_contracts_cap": 100_000}
        small = _risk_pct_capped(10_000.0, cfg, stop_distance_points=10.0,
                                 point_value=1.0)
        big = _risk_pct_capped(1_000_000.0, cfg, stop_distance_points=10.0,
                               point_value=1.0)
        assert big == pytest.approx(small * 100)

    @pytest.mark.parametrize("bad", [None, 0.0, -5.0])
    def test_no_stop_distance_sizes_to_zero(self, bad):
        """Pre-existing behaviour of both inline copies. Whether 'declined to
        size' should be distinguishable from 'sized to zero' is #381-D."""
        assert _risk_pct_capped(100_000.0, _CFG, stop_distance_points=bad,
                                point_value=1.0) == 0.0

    def test_negative_equity_does_not_produce_a_negative_size(self):
        assert _risk_pct_capped(-50_000.0, _CFG, stop_distance_points=10.0,
                                point_value=1.0) == 0.0


# ---------------------------------------------------------------------------
class TestFixedContractsArithmetic:

    def test_reads_the_config_key(self):
        assert _fixed_contracts({"fixed_contracts_per_trade": 7}) == 7.0

    def test_defaults_to_one(self):
        assert _fixed_contracts({}) == 1.0

    def test_never_scales_with_equity(self):
        a = calculate_position_size("fixed_contracts", 10_000.0, 100.0,
                                    pd.DataFrame(), _CFG)
        b = calculate_position_size("fixed_contracts", 10_000_000.0, 100.0,
                                    pd.DataFrame(), _CFG)
        assert a == b == 3.0


# ---------------------------------------------------------------------------
class TestPointsIsThePrimitive:

    def test_risk_parity_accepts_points_and_converts(self):
        df = pd.DataFrame({"ATR_14": [2.0]})
        via_points = calculate_position_size("risk_parity", 100_000.0, 100.0,
                                             df, _CFG, stop_distance_points=5.0)
        via_pct = calculate_position_size("risk_parity", 100_000.0, 100.0,
                                          df, _CFG, stop_distance_pct=0.05)
        assert via_points == pytest.approx(via_pct)

    def test_points_wins_when_both_are_supplied(self):
        df = pd.DataFrame({"ATR_14": [2.0]})
        got = calculate_position_size("risk_parity", 100_000.0, 100.0, df, _CFG,
                                      stop_distance_points=5.0,
                                      stop_distance_pct=0.99)
        expect = calculate_position_size("risk_parity", 100_000.0, 100.0, df,
                                         _CFG, stop_distance_pct=0.05)
        assert got == pytest.approx(expect)

    def test_engine_still_feeds_risk_parity_a_fraction(self):
        """Guards the deliberate NON-change. The engine builds
        stop_distance_pct with a different denominator per stop type, so
        switching risk_parity to points changes live share counts — that is
        #381-D's call, not #384's. If this assertion ever fails because the
        engine started passing points, the golden master must be re-blessed."""
        src = open(os.path.join(PROJECT_ROOT, "helpers",
                                "portfolio_simulations.py")).read()
        assert 'sizing_kwargs["stop_distance_pct"]' in src


# ---------------------------------------------------------------------------
_FUT_CFG = {
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
    "allocation_per_trade": 0.10,
    "risk_pct_per_trade": 0.01,
    "max_contracts_cap": 20,
    "fixed_contracts_per_trade": 3,
    "instruments": {
        "default_asset_class": "equity",
        "futures_initial_margin_pct": 0.10,
        "futures_commission_per_contract": 2.50,
        "futures_slippage_ticks": 1.0,
        "overrides": {},
    },
}


def _frame(base_price, n=14, atr_pct=2.0):
    closes = np.array([base_price * (1 + 0.002 * i) for i in range(n)])
    idx = pd.bdate_range(start="2023-01-02", periods=n, freq="B")
    idx.name = "Datetime"
    return pd.DataFrame({
        "Open": np.round(closes * 0.999, 6),
        "High": np.round(closes * 1.010, 6),
        "Low": np.round(closes * 0.990, 6),
        "Close": closes,
        "Volume": np.full(n, 5_000_000.0),
        "ATR_14": np.full(n, atr_pct * base_price / 100.0),
    }, index=idx)


def _run(symbol, method, stop_config, direction="long", price=1000.0):
    from unittest.mock import patch
    df = _frame(price)
    pairs = {2: -2, 9: -1} if direction == "short" else {2: 1, 9: -1}
    sig = pd.Series(0, index=df.index, dtype=int)
    for i, v in pairs.items():
        sig.iloc[i] = v
    cfg = {**_FUT_CFG, "position_sizing_method": method}
    with patch.dict("config.CONFIG", cfg, clear=False):
        return run_portfolio_simulation(
            portfolio_data={symbol: df}, signals={symbol: sig},
            initial_capital=100_000.0, allocation_pct=0.10,
            spy_df=None, vix_df=None, tnx_df=None, stop_config=stop_config,
        )


class TestUnitCountMethodsSkipConversion:
    """The one load-bearing branch of the old three-way dispatch.

    `fixed_contracts` and `risk_pct_capped` already answer in contracts; the
    other four answer in dollars and get divided by point_value (or by
    margin_required for margined instruments). Routing a contract count through
    that conversion re-scales an answer that was already in the right units.
    """

    def test_futures_fixed_contracts_takes_exactly_n(self):
        res = _run("MESM6", "fixed_contracts", {"type": "atr", "multiplier": 2.0})
        assert res is not None and res["trade_log"]
        # Dies at 6.0 if the unit-count gate is removed (MES margin is 10% of
        # a $5/point notional, so the conversion doubles the count).
        assert res["trade_log"][0]["Shares"] == pytest.approx(3.0)

    def test_equity_fixed_contracts_takes_exactly_n(self):
        res = _run("AAA", "fixed_contracts", {"type": "atr", "multiplier": 2.0})
        assert res is not None and res["trade_log"]
        assert res["trade_log"][0]["Shares"] == pytest.approx(3.0)

    def test_a_dollar_method_still_gets_the_conversion(self):
        """Control: `fixed` must NOT skip it, or the gate is over-broad."""
        eq = _run("AAA", "fixed", {"type": "atr", "multiplier": 2.0})
        fut = _run("MESM6", "fixed", {"type": "atr", "multiplier": 2.0})
        assert eq["trade_log"][0]["Shares"] != pytest.approx(
            fut["trade_log"][0]["Shares"])


class TestLongAndShortShareTheFunction:
    """The futures-short mirrors are gone; both legs call the same function.

    Note the scope line: this covers the FUTURES short leg only. The EQUITY
    short leg still hardcodes allocation/fill and does not read
    position_sizing_method at all — that is #381-C.
    """

    def test_futures_short_fixed_contracts_matches_long(self):
        lng = _run("MESM6", "fixed_contracts", {"type": "atr", "multiplier": 2.0},
                   direction="long")
        sht = _run("MESM6", "fixed_contracts", {"type": "atr", "multiplier": 2.0},
                   direction="short")
        assert lng["trade_log"][0]["Shares"] == pytest.approx(
            sht["trade_log"][0]["Shares"])

    def test_futures_short_risk_pct_capped_uses_point_value(self):
        """Dies if the short call site stops passing inst_se.point_value:
        MES is $5/point, so a pv of 1.0 would size 5x larger (up to the cap)."""
        sht = _run("MESM6", "risk_pct_capped",
                   {"type": "percentage", "value": 0.05}, direction="short")
        assert sht is not None and sht["trade_log"]
        shares = sht["trade_log"][0]["Shares"]
        risk = sht["trade_log"][0]["InitialRisk"]
        expected = np.floor((100_000.0 * 0.01) / (risk * 5.0))
        assert shares == pytest.approx(min(expected, 20))

    def test_no_inline_sizing_copies_remain(self):
        """The four open-coded copies were the actual defect. This fails if a
        fifth is ever added — the copy in this file has drifted twice already."""
        src = open(os.path.join(PROJECT_ROOT, "helpers",
                                "portfolio_simulations.py")).read()
        assert "max_contracts_cap" not in src, (
            "risk_pct_capped arithmetic is back in the engine")
        assert "fixed_contracts_per_trade" not in src, (
            "fixed_contracts arithmetic is back in the engine")
