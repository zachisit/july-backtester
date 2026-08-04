# tests/test_instruments.py
"""
Unit tests for helpers/instruments.py — the per-symbol instrument metadata layer.

Covers:
  TestResolve            — equity default, futures contract-month, overrides, default_asset_class
  TestParseRoot          — contract-month root parsing
  TestEquityNoRegression — equity default reproduces the engine's prior arithmetic
  TestCostHelpers        — commission, slippage, rounding, value, margin, unrealized, borrow
  TestStopLevel          — percentage and new points stop types
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers import instruments as I
from helpers.instruments import Instrument, resolve_instrument


# Legacy-equivalent config used across the no-regression tests.
_CFG = {
    "commission_per_share": 0.002,
    "slippage_pct": 0.0005,
    "htb_rate_annual": 0.02,
    "instruments": {"default_asset_class": "equity", "overrides": {}},
}


# ---------------------------------------------------------------------------
# TestResolve
# ---------------------------------------------------------------------------
class TestResolve:
    def test_plain_equity_is_equity(self):
        inst = resolve_instrument("AAPL", _CFG)
        assert inst.asset_class == I.EQUITY
        assert inst.point_value == 1.0
        assert inst.margin_mode == I.CASH_FULL
        assert inst.integer_units is False
        assert inst.borrow_applies is True

    def test_contract_month_ticker_is_future(self):
        inst = resolve_instrument("ESM6", _CFG)
        assert inst.asset_class == I.FUTURE
        assert inst.point_value == 50.0          # ES
        assert inst.tick_size == 0.25
        assert inst.margin_mode == I.INITIAL_MARGIN
        assert inst.integer_units is True
        assert inst.borrow_applies is False
        assert inst.calendar == I.CME_ETH

    def test_bare_futures_root_not_autoclassified(self):
        # "SI" is also a real equity ticker — must NOT become a future implicitly.
        inst = resolve_instrument("SI", _CFG)
        assert inst.asset_class == I.EQUITY

    def test_override_forces_future(self):
        cfg = {**_CFG, "instruments": {
            "default_asset_class": "equity",
            "overrides": {"NQ": {"asset_class": "future", "point_value": 20.0, "tick_size": 0.25}},
        }}
        inst = resolve_instrument("NQ", cfg)
        assert inst.asset_class == I.FUTURE
        assert inst.point_value == 20.0
        assert inst.integer_units is True

    def test_override_can_pin_equity(self):
        cfg = {**_CFG, "instruments": {
            "default_asset_class": "future",
            "overrides": {"AAPL": {"asset_class": "equity"}},
        }}
        assert resolve_instrument("AAPL", cfg).asset_class == I.EQUITY

    def test_default_asset_class_future(self):
        cfg = {**_CFG, "instruments": {"default_asset_class": "future", "overrides": {}}}
        inst = resolve_instrument("ES", cfg)
        assert inst.asset_class == I.FUTURE
        assert inst.point_value == 50.0

    def test_futures_config_overrides_applied(self):
        cfg = {**_CFG, "instruments": {
            "default_asset_class": "equity",
            "futures_initial_margin_pct": 0.05,
            "futures_commission_per_contract": 0.85,
            "futures_slippage_ticks": 2.0,
            "point_values": {"ES": 55.0},
            "overrides": {},
        }}
        inst = resolve_instrument("ESU6", cfg)
        assert inst.initial_margin_pct == 0.05
        assert inst.commission_value == 0.85
        assert inst.slippage_value == 2.0
        assert inst.point_value == 55.0


# ---------------------------------------------------------------------------
# TestParseRoot
# ---------------------------------------------------------------------------
class TestParseRoot:
    @pytest.mark.parametrize("ticker,root", [
        ("ESM6", "ES"), ("MNQZ26", "MNQ"), ("CLF7", "CL"),
        ("ES", "ES"), ("AAPL", "AAPL"), ("esm6", "ES"),
        ("M2KZ6", "M2K"), ("M2KH25", "M2K"),  # digit-in-root product (Micro Russell)
    ])
    def test_parse_root(self, ticker, root):
        assert I.parse_root(ticker) == root

    def test_m2k_contract_resolves_with_correct_point_value(self):
        # Regression for the digit-in-root regex bug: M2K (Micro Russell 2000) must
        # resolve to its real $/point (5.0), not silently fall back to 1.0.
        inst = resolve_instrument("M2KZ6", _CFG)
        assert inst.asset_class == I.FUTURE
        assert inst.point_value == 5.0
        assert inst.tick_size == 0.10

    def test_m2k_override_uses_correct_point_value(self):
        cfg = {**_CFG, "instruments": {
            "default_asset_class": "equity",
            "overrides": {"M2KZ6": {"asset_class": "future"}},
        }}
        assert resolve_instrument("M2KZ6", cfg).point_value == 5.0


# ---------------------------------------------------------------------------
# TestEquityNoRegression — helpers reproduce the pre-instrument arithmetic
# ---------------------------------------------------------------------------
class TestEquityNoRegression:
    def setup_method(self):
        self.inst = resolve_instrument("AAPL", _CFG)

    def test_commission_matches_per_share(self):
        # old: commission = shares * CONFIG['commission_per_share']
        assert I.commission(self.inst, 100) == pytest.approx(100 * 0.002)

    def test_entry_slippage_matches(self):
        # old: entry_price = raw * (1 + slippage_pct)
        assert I.apply_slippage(self.inst, 50.0, "buy") == pytest.approx(50.0 * 1.0005)

    def test_exit_slippage_matches(self):
        # old: exit_price = raw * (1 - slippage_pct)
        assert I.apply_slippage(self.inst, 50.0, "sell") == pytest.approx(50.0 * 0.9995)

    def test_market_value_matches(self):
        # old: current_market_value += shares * close
        assert I.market_value(self.inst, 100, 50.0) == pytest.approx(100 * 50.0)

    def test_margin_is_full_notional(self):
        # old: capital_needed = shares * entry_price
        assert I.margin_required(self.inst, 100, 50.0) == pytest.approx(100 * 50.0)

    def test_fractional_shares_pass_through(self):
        assert I.round_units(self.inst, 12.3456) == 12.3456

    def test_borrow_applies_for_equity(self):
        # old: cost = notional * htb_rate_per_bar (applies to short equities)
        assert I.borrow_cost_per_bar(self.inst, 10000.0, 0.001) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# TestCostHelpers — futures-specific behaviour
# ---------------------------------------------------------------------------
class TestCostHelpers:
    def setup_method(self):
        self.fut = resolve_instrument("ESM6", _CFG)  # ES: $50/pt, 0.25 tick, 10% margin

    def test_integer_contracts_floor(self):
        assert I.round_units(self.fut, 3.9) == 3.0
        assert I.round_units(self.fut, 0.9) == 0.0

    def test_tick_slippage_buy_and_sell(self):
        assert I.apply_slippage(self.fut, 5000.0, "buy") == pytest.approx(5000.0 + 1 * 0.25)
        assert I.apply_slippage(self.fut, 5000.0, "sell") == pytest.approx(5000.0 - 1 * 0.25)

    def test_market_value_uses_point_value(self):
        # 2 ES contracts at 5000 -> 2 * 5000 * 50
        assert I.market_value(self.fut, 2, 5000.0) == pytest.approx(2 * 5000.0 * 50.0)

    def test_margin_is_fraction_of_notional(self):
        # notional = 2 * 5000 * 50 = 500,000 ; margin @10% = 50,000
        assert I.margin_required(self.fut, 2, 5000.0) == pytest.approx(50000.0)

    def test_unrealized_pnl_long_and_short(self):
        # long 1 ES from 5000 -> 5010 = +10 pts * $50 = +$500
        assert I.unrealized_pnl(self.fut, 1, 5000.0, 5010.0, "long") == pytest.approx(500.0)
        # short 1 ES from 5000 -> 5010 = -$500
        assert I.unrealized_pnl(self.fut, 1, 5000.0, 5010.0, "short") == pytest.approx(-500.0)

    def test_commission_per_contract(self):
        assert I.commission(self.fut, 3) == pytest.approx(3 * 2.50)

    def test_borrow_not_applied_for_futures(self):
        assert I.borrow_cost_per_bar(self.fut, 500000.0, 0.001) == 0.0

    def test_apply_slippage_bad_side(self):
        with pytest.raises(ValueError):
            I.apply_slippage(self.fut, 5000.0, "hold")


# ---------------------------------------------------------------------------
# TestStopLevel
# ---------------------------------------------------------------------------
class TestStopLevel:
    def setup_method(self):
        self.eq = resolve_instrument("AAPL", _CFG)
        self.fut = resolve_instrument("ESM6", _CFG)

    def test_percentage_long(self):
        assert I.stop_level(self.eq, 100.0, {"type": "percentage", "value": 0.05}, "long") == pytest.approx(95.0)

    def test_percentage_short(self):
        assert I.stop_level(self.eq, 100.0, {"type": "percentage", "value": 0.05}, "short") == pytest.approx(105.0)

    def test_points_long(self):
        assert I.stop_level(self.fut, 5000.0, {"type": "points", "value": 25.0}, "long") == pytest.approx(4975.0)

    def test_points_short(self):
        assert I.stop_level(self.fut, 5000.0, {"type": "points", "value": 25.0}, "short") == pytest.approx(5025.0)

    def test_none_and_atr_return_none(self):
        assert I.stop_level(self.eq, 100.0, {"type": "none"}) is None
        assert I.stop_level(self.eq, 100.0, {"type": "atr", "multiplier": 3.0}) is None


# ---------------------------------------------------------------------------
# TestIsFuturesDataSymbol — data-endpoint routing predicate
# ---------------------------------------------------------------------------
class TestIsFuturesDataSymbol:
    """Data routing must be narrower than execution-semantics resolution:
    a blanket default_asset_class="future" must NOT reroute benchmark tickers
    (SPY, I:VIX) to the futures endpoint — they share the same fetch path."""

    def test_contract_month_code_routes_to_futures(self):
        assert I.is_futures_data_symbol("ESM6", _CFG) is True

    def test_plain_equity_does_not_route(self):
        assert I.is_futures_data_symbol("AAPL", _CFG) is False

    def test_benchmark_not_rerouted_by_future_default(self):
        cfg = {"instruments": {"default_asset_class": "future", "overrides": {}}}
        # resolve_instrument says "future" (execution semantics honour the default)...
        assert resolve_instrument("SPY", cfg).asset_class == I.FUTURE
        # ...but the DATA path must keep SPY / I:VIX on the equities/index endpoint.
        assert I.is_futures_data_symbol("SPY", cfg) is False
        assert I.is_futures_data_symbol("I:VIX", cfg) is False

    def test_explicit_override_routes_to_futures(self):
        cfg = {"instruments": {"default_asset_class": "equity",
                               "overrides": {"NQ": {"asset_class": "future"}}}}
        assert I.is_futures_data_symbol("NQ", cfg) is True

    def test_explicit_equity_override_blocks_contract_code(self):
        cfg = {"instruments": {"default_asset_class": "equity",
                               "overrides": {"ESM6": {"asset_class": "equity"}}}}
        assert I.is_futures_data_symbol("ESM6", cfg) is False
