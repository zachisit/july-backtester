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
        # margined=True: the cap is a CONTRACT count and #385 gates it on
        # margin_mode. On the unmargined path it no longer applies.
        got = _risk_pct_capped(100_000.0, _CFG, margined=True,
                               stop_distance_points=1.0, point_value=1.0)
        assert got == 20  # 1000 units wanted, capped

    def test_result_is_floored_not_rounded(self):
        cfg = {**_CFG, "max_contracts_cap": 1000}
        # 1000 / 350.18 = 2.856 -> 2, not 3.  floor() travels with the cap and
        # is likewise margined-only (#385) -- a share count is not integral.
        got = _risk_pct_capped(100_000.0, cfg, margined=True,
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


def _run(symbol, method, stop_config, direction="long", price=1000.0, **over):
    from unittest.mock import patch
    df = _frame(price)
    pairs = {2: -2, 9: -1} if direction == "short" else {2: 1, 9: -1}
    sig = pd.Series(0, index=df.index, dtype=int)
    for i, v in pairs.items():
        sig.iloc[i] = v
    cfg = {**_FUT_CFG, "position_sizing_method": method, **over}
    with patch.dict("config.CONFIG", cfg, clear=False):
        return run_portfolio_simulation(
            portfolio_data={symbol: df}, signals={symbol: sig},
            initial_capital=100_000.0, allocation_pct=0.10,
            spy_df=None, vix_df=None, tnx_df=None, stop_config=stop_config,
        )


_TRAILING_ATR = {"type": "trailing_atr", "stop_mult": 1.0, "trail_mult": 1.0,
                 "t1_mult": 2.0, "point_cap": 60, "floor": "breakeven"}


class TestRiskPctCappedHasTwoOutputs:
    """`risk_pct_capped` returns a unit count AND a stop fraction.

    The second output is `sizing_kwargs["stop_distance_pct"]`, read only by the
    portfolio heat check, whose fallback is a silent
    `or CONFIG.get("target_risk_per_trade", 0.02)`. A float-returning hoist
    drops it, nothing raises, and heat quietly reverts to the flat 2% proxy —
    which is 10-15x off the real fraction on the strategy this method exists
    for. It therefore stays at the CALL SITE and is pinned here.

    Both tests need a stop fraction materially under 2% (point_cap 60 on a
    5000-point index -> 1.2%) and a heat cap between the two values. At the
    config-default heat of 0.10 both sides pass and the swap is invisible;
    that is why these are not written against the defaults.
    (@shardul0701 on #384.)
    """

    def test_heat_admits_on_the_real_fraction(self):
        # Heat 0.015, not 0.01. #385 removed the 20-unit cap on the unmargined
        # path, so this position is now sized to risk a genuine ~1.0% of equity
        # instead of ~0.1%, and both the real fraction and the 2% proxy exceed a
        # 1% heat budget -- the cap was doing the discriminating, not the
        # fraction. At 1.5% the real risk (1.004%) is admitted and the proxy
        # (1.674%) is not, which is the comparison this test is for.
        res = _run("AAA", "risk_pct_capped", _TRAILING_ATR, price=5000.0,
                   max_portfolio_heat=0.015, max_pct_adv=0.05)
        assert res is not None and res["trade_log"], (
            "real risk is 1.004% of a 1.5% heat budget -- it must be admitted; "
            "with the flat 2% proxy it reads as 1.674% and is rejected")
        assert res["trade_log"][0]["InitialRisk"] == pytest.approx(60.0)

    def test_heat_rejects_when_the_real_fraction_is_larger(self):
        """The other direction: dropping the side output does not merely
        over-reject, it also ADMITS trades the real fraction excludes."""
        res = _run("AAA", "risk_pct_capped", {"type": "atr", "multiplier": 2.0},
                   price=5000.0, max_portfolio_heat=0.01, max_pct_adv=0.05)
        assert res is None or not res.get("trade_log"), (
            "a ~4% real stop fraction exceeds the 1% heat cap; with the 2% "
            "proxy it is admitted")


class TestSizeMultStaysAtTheCallSite:
    """`_size_mult` is applied by the ENGINE after the sizing call, not inside
    the shared function.

    Pulled inside, the futures-short leg would silently start honouring
    `size_mults` — which is #386's behavioural change arriving inside a ticket
    whose whole claim is that it changes nothing. The asymmetry below is
    therefore pinned as it is, not as it should be. (@shardul0701 on #384.)

    `size_mults` is latent through `main.py` — nothing in-repo passes it — so
    without these two tests the mutation that drops `shares * _size_mult`
    entirely passes the whole suite, golden master included. Measured.
    """

    def _mults(self, symbol, df, value):
        return {symbol: pd.Series(value, index=df.index, dtype=float)}

    def _shares(self, symbol, method, entry_signal, mult):
        from unittest.mock import patch
        df = _frame(1000.0)
        sig = pd.Series(0, index=df.index, dtype=int)
        sig.iloc[2], sig.iloc[9] = entry_signal, -1
        # target_risk 0.005, not the 0.02 default: at 0.02 vol_parity sizes to
        # ~100% of equity, the cash clamp (`capital_needed > cash`) bites at
        # mult=1.0 and not at mult=0.5, and the ratio comes out 0.502 for a
        # reason that has nothing to do with size_mults. Keep the position well
        # inside cash so the multiplier is the only thing moving.
        cfg = {**_FUT_CFG, "position_sizing_method": method,
               "target_risk_per_trade": 0.005}
        with patch.dict("config.CONFIG", cfg, clear=False):
            res = run_portfolio_simulation(
                portfolio_data={symbol: df}, signals={symbol: sig},
                initial_capital=100_000.0, allocation_pct=0.10,
                spy_df=None, vix_df=None, tnx_df=None,
                stop_config={"type": "atr", "multiplier": 2.0},
                size_mults=self._mults(symbol, df, mult),
            )
        return res["trade_log"][0]["Shares"]

    @pytest.mark.parametrize("method", ["risk_pct_capped", "fixed_contracts",
                                        "fixed", "vol_parity"])
    def test_long_leg_honours_it(self, method):
        # Equity, not futures: `round_units` floors a futures position to whole
        # contracts, so a 0.5x multiplier on 19 contracts lands at 9, not 9.5,
        # and an exact-ratio assertion fails for a reason that has nothing to do
        # with size_mults. Equities take fractional shares, so the ratio is clean.
        full = self._shares("AAA", method, 1, 1.0)
        half = self._shares("AAA", method, 1, 0.5)
        assert half == pytest.approx(full * 0.5), (
            "long leg dropped size_mults for %s" % method)

    def test_futures_short_leg_does_not_and_that_is_pinned_not_endorsed(self):
        """Pre-existing asymmetry, deliberately unchanged by #384 — closing it
        is #386. If this starts failing because the short leg gained
        `size_mults`, that is the right fix arriving in the wrong ticket."""
        full = self._shares("MESM6", "fixed_contracts", -2, 1.0)
        half = self._shares("MESM6", "fixed_contracts", -2, 0.5)
        # 3 contracts either way, so the futures rounding that confounds an
        # exact-ratio assertion on the long leg cannot mask the result here.
        assert full == pytest.approx(3.0)
        assert half == pytest.approx(full)


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
        fifth is ever added — the copy in this file has drifted twice already.

        Scoped to CODE, not to the file text. The first version matched raw
        source and so fired on a #385 comment that merely *names*
        `max_contracts_cap` while explaining where the cap now lives — a
        comment is the opposite of a re-inlined copy, and a guard that treats
        documenting the rule as breaking it will get commented out rather than
        satisfied. Parsing to an AST and reading string constants keeps the
        tripwire and drops the false positive.
        """
        import ast
        src = open(os.path.join(PROJECT_ROOT, "helpers",
                                "portfolio_simulations.py")).read()
        literals = {
            node.value
            for node in ast.walk(ast.parse(src))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        # Docstrings are string constants too, so exclude anything long enough
        # to be prose — a config key read is a bare short literal.
        keys = {s for s in literals if len(s) < 60}
        assert "max_contracts_cap" not in keys, (
            "risk_pct_capped arithmetic is back in the engine")
        assert "fixed_contracts_per_trade" not in keys, (
            "fixed_contracts arithmetic is back in the engine")
        assert "risk_pct_per_trade" not in keys, (
            "risk_pct_capped arithmetic is back in the engine")


# ---------------------------------------------------------------------------
class TestEngineFeedsRiskParityAFractionBehaviourally:
    """Behavioural teeth for `test_engine_still_feeds_risk_parity_a_fraction`.

    That test greps the engine source for `sizing_kwargs["stop_distance_pct"]`
    — and the string it matches is not the line it is guarding. The SAME literal
    appears on the risk_pct_capped heat side-output line, so the grep is
    satisfied by a line in a different method entirely. Measured, not argued:
    rewriting the `points` branch to feed `stop_distance_points` instead —
    which silently moves the fraction's denominator from `raw_entry_price` to
    the slipped fill inside `_risk_parity` — passed the ENTIRE suite,
    2725 passed / 0 failed.

    The grep test is kept as a cheap tripwire for wholesale deletion, but it is
    not the guard. This class is: it observes what the engine actually hands the
    sizing function rather than what the file contains, across every stop type
    that derives a fraction.

    #384 accepts points as the primitive but deliberately does NOT switch the
    engine over for risk_parity — the fraction is built with a different
    denominator per stop type, so one conversion agrees with none of them and
    live share counts move. That is #381-D's call. Found by the adversarial QA
    pass over this branch.
    """

    FRACTION_DERIVING_STOPS = {
        "percentage": {"type": "percentage", "value": 0.05},
        "trailing_atr": {"type": "trailing_atr", "stop_mult": 1.0,
                         "trail_mult": 1.0, "t1_mult": 2.0, "point_cap": 60,
                         "floor": "breakeven"},
        "atr": {"type": "atr", "multiplier": 2.0},
        "points": {"type": "points", "value": 5.0},
        "signal_bar": {"type": "signal_bar", "buffer": 0.005},
    }

    @pytest.mark.parametrize("stop_key", sorted(FRACTION_DERIVING_STOPS))
    def test_risk_parity_is_handed_a_fraction_not_points(self, stop_key):
        from unittest.mock import patch
        import helpers.portfolio_simulations as ps

        seen = []
        real = ps.calculate_position_size

        def _spy(**kwargs):
            if kwargs.get("method") == "risk_parity":
                seen.append(dict(kwargs))
            return real(**kwargs)

        df = _frame(1000.0)
        sig = pd.Series(0, index=df.index, dtype=int)
        sig.iloc[2], sig.iloc[9] = 1, -1
        cfg = {**_FUT_CFG, "position_sizing_method": "risk_parity"}
        with patch.dict("config.CONFIG", cfg, clear=False):
            with patch.object(ps, "calculate_position_size", _spy):
                ps.run_portfolio_simulation(
                    portfolio_data={"AAA": df}, signals={"AAA": sig},
                    initial_capital=100_000.0, allocation_pct=0.10,
                    spy_df=None, vix_df=None, tnx_df=None,
                    stop_config=self.FRACTION_DERIVING_STOPS[stop_key],
                )

        assert seen, "risk_parity never reached calculate_position_size"
        call = seen[0]
        assert "stop_distance_points" not in call, (
            "engine fed risk_parity POINTS for a %s stop; the fraction's "
            "denominator silently became the slipped fill (#381-D, not #384)"
            % stop_key)
        frac = call.get("stop_distance_pct")
        assert frac is not None and frac > 0, (
            "engine derived no stop fraction for a %s stop, so risk_parity fell "
            "through to the 3xATR proxy" % stop_key)


# ---------------------------------------------------------------------------
class TestModuleDefaultsAreLive:
    """`_risk_pct_capped`'s three `config.get(...)` defaults were unpinned.

    Every in-repo caller passes all three keys explicitly, so mutating any
    default survived the whole targeted sizing suite. The #384 commit message
    already flagged the `max_contracts_cap` one as a VACUOUS mutant and then
    left it uncovered — noticing a gap is not closing it.

    Direct module calls are exactly the usage #384 exists to enable (the method
    was unreachable through this function before), so these defaults are public
    surface, not dead parameters. Found by the adversarial QA pass.
    """

    def test_max_contracts_cap_defaults_to_twenty(self):
        cfg = {"risk_pct_per_trade": 0.01}          # cap omitted
        assert _risk_pct_capped(100_000.0, cfg, margined=True,
                                stop_distance_points=1.0,
                                point_value=1.0) == 20

    def test_risk_pct_per_trade_defaults_to_one_percent(self):
        cfg = {"max_contracts_cap": 100_000}        # risk pct omitted
        # 1% of 100k = $1,000 budget / $10 per unit = 100 units
        assert _risk_pct_capped(100_000.0, cfg, stop_distance_points=10.0,
                                point_value=1.0) == pytest.approx(100.0)

    def test_point_value_defaults_to_one(self):
        cfg = {"risk_pct_per_trade": 0.01, "max_contracts_cap": 100_000}
        omitted = _risk_pct_capped(100_000.0, cfg, stop_distance_points=10.0)
        explicit = _risk_pct_capped(100_000.0, cfg, stop_distance_points=10.0,
                                    point_value=1.0)
        assert omitted == pytest.approx(explicit)
        assert omitted == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# #385 — the cap, the floor and the ceiling
# ---------------------------------------------------------------------------
_PRICES = (20.0, 100.0, 500.0, 1000.0, 7000.0)
_STOP_FRACS = (0.002, 0.005, 0.01, 0.02, 0.05, 0.10)
_EQUITIES = (10_000.0, 100_000.0, 10_000_000.0)


def _expected_units(equity, price, stop_frac, risk_pct=0.01, ceiling_pct=1.0):
    """Reimplemented from the SPEC, not from the code under test.

    Derived independently on purpose: #384's first equivalence leg came out
    circular because it built the expectation by dividing raw values by the
    same ratio it was validating, so the ratio cancelled and a run with the
    split missed entirely still passed. An expectation computed from the
    function it is checking proves the function equals itself.
    """
    wanted = (equity * risk_pct) / (price * stop_frac)
    ceiling = (equity * ceiling_pct) / price
    return min(wanted, ceiling)


class TestRiskPctCappedDeliversItsBudget:
    """The #385 acceptance criterion, over all three axes at once.

    > delivers `risk_pct_per_trade` of equity, measured through the real stop
    > distance, whenever `stop_frac >= risk_pct_per_trade` — at ANY share
    > price, ANY stop width and ANY account size; below that threshold it
    > delivers the ceiling-clamped value.

    The threshold clause is load-bearing and is asserted separately rather than
    smoothed into a tolerance: below `stop_frac == risk_pct_per_trade` the
    budget is genuinely unreachable without leverage, so a test written without
    it fails on day one for a legitimate reason — and the natural response to
    that is to loosen it, which re-admits the defect it was written to catch.
    (@shardul0701 on #381 and #385.)

    Note these are unit-level assertions against the sizing function, not
    against `Shares × InitialRisk` from a trade log. Those two quantities are
    anchored to DIFFERENT prices on an equity — sizing divides by
    `raw_entry_price`, `InitialRisk` is measured off the slipped `entry_price`
    because `_stop_anchor` gates on `margin_mode` — so an exact-equality
    assertion over a trade log fails on a correct fix. The engine-level check
    lives in `TestDeliveredRiskIsPriceInvariant` below with that drift called
    out and bounded.
    """

    @pytest.mark.parametrize("equity", _EQUITIES)
    @pytest.mark.parametrize("stop_frac", _STOP_FRACS)
    @pytest.mark.parametrize("price", _PRICES)
    def test_budget_delivered_or_ceiling_clamped(self, price, stop_frac, equity):
        cfg = {"risk_pct_per_trade": 0.01, "max_contracts_cap": 20,
               "risk_pct_capped_max_notional_pct": 1.0}
        got = _risk_pct_capped(equity, cfg, price=price, margined=False,
                               stop_distance_points=price * stop_frac,
                               point_value=1.0)
        assert got == pytest.approx(_expected_units(equity, price, stop_frac))

        delivered = got * price * stop_frac          # $ risk at the stop
        if stop_frac >= 0.01:
            # Reachable: the full budget, exactly, on every axis.
            assert delivered == pytest.approx(equity * 0.01)
        else:
            # Unreachable without leverage: the ceiling-clamped value, which is
            # stop_frac of equity rather than risk_pct of it.
            assert delivered == pytest.approx(equity * stop_frac)
            assert delivered < equity * 0.01

    def test_the_old_defect_is_gone_at_the_documented_prices(self):
        """The ticket's headline table: a flat 20 shares at every price."""
        cfg = {"risk_pct_per_trade": 0.01, "max_contracts_cap": 20,
               "risk_pct_capped_max_notional_pct": 1.0}
        risks = []
        for price in (20.0, 100.0, 500.0, 1000.0, 2000.0):
            units = _risk_pct_capped(100_000.0, cfg, price=price, margined=False,
                                     stop_distance_points=price * 0.05,
                                     point_value=1.0)
            risks.append(units * price * 0.05)
        assert all(r == pytest.approx(1000.0) for r in risks), risks
        # Under the old code these were 20.01 / 100.05 / 500.25 / 1000.50 /
        # 1000.50 — a 50x spread. Now flat.
        assert max(risks) / min(risks) == pytest.approx(1.0)

    def test_no_integer_floor_on_the_unmargined_path(self):
        """A $7,000 name wanting 2.86 shares got 2 — a further 30% short."""
        cfg = {"risk_pct_per_trade": 0.01, "max_contracts_cap": 100_000,
               "risk_pct_capped_max_notional_pct": 1.0}
        got = _risk_pct_capped(100_000.0, cfg, price=7000.0, margined=False,
                               stop_distance_points=350.18, point_value=1.0)
        assert got == pytest.approx(1000.0 / 350.18)
        assert got != pytest.approx(2.0)

    def test_margined_keeps_both_the_floor_and_the_cap(self):
        """The gate is two-sided: futures behaviour must be unchanged."""
        cfg = {"risk_pct_per_trade": 0.01, "max_contracts_cap": 20}
        capped = _risk_pct_capped(100_000.0, cfg, price=1000.0, margined=True,
                                  stop_distance_points=1.0, point_value=1.0)
        assert capped == 20
        floored = _risk_pct_capped(100_000.0, {**cfg, "max_contracts_cap": 1000},
                                   price=7000.0, margined=True,
                                   stop_distance_points=350.18, point_value=1.0)
        assert floored == pytest.approx(2.0)


class TestTheCeilingIsNotAllocationPerTrade:
    """Reversal of #381-B's proposed ceiling, with the measurement behind it.

    The ticket proposed `allocation_per_trade` "since it's what a reader
    already believes is in force." Measured, that ceiling binds whenever
    `stop_frac < risk_pct / allocation_pct` — at the defaults, any stop tighter
    than 10%, which is very nearly all of them — and delivers 0.2-0.5% against
    a configured 1%. That is the same defect the cap gating removes, wearing a
    different number.
    """

    def test_an_allocation_sized_ceiling_would_re_break_it(self):
        """Pins WHY the ceiling is 1.0. Not a test of shipped behaviour — a
        test of the alternative, so the reasoning cannot be quietly undone."""
        cfg = {"risk_pct_per_trade": 0.01,
               "risk_pct_capped_max_notional_pct": 0.10}   # the rejected design
        units = _risk_pct_capped(100_000.0, cfg, price=100.0, margined=False,
                                 stop_distance_points=5.0, point_value=1.0)
        delivered = units * 5.0
        assert delivered == pytest.approx(500.0)        # 0.5%, not 1%
        assert delivered < 1000.0

    def test_the_ceiling_never_costs_a_deliverable_budget(self):
        """At 1.0 the ceiling costs nothing whenever the budget is reachable.

        Stated in terms of DELIVERED RISK rather than "did the clamp fire",
        because at exactly `stop_frac == risk_pct_per_trade` the wanted size
        and the ceiling are the same number — required notional is exactly
        equity — so both descriptions are true at once and "clamped: yes/no" is
        not a well-defined observable there. What IS well defined, and is the
        property the ticket asks for, is whether the full budget arrived.
        """
        cfg = {"risk_pct_per_trade": 0.01,
               "risk_pct_capped_max_notional_pct": 1.0}
        budget = 100_000.0 * 0.01
        for stop_frac in (0.005, 0.01, 0.02, 0.05):
            units = _risk_pct_capped(100_000.0, cfg, price=100.0, margined=False,
                                     stop_distance_points=100.0 * stop_frac,
                                     point_value=1.0)
            delivered = units * 100.0 * stop_frac
            if stop_frac >= 0.01:
                assert delivered == pytest.approx(budget), (stop_frac, delivered)
                assert units * 100.0 <= 100_000.0 + 1e-6   # never levered
            else:
                # Unreachable without leverage. Delivered is the ceiling value,
                # which is exactly stop_frac of equity.
                assert delivered == pytest.approx(100_000.0 * stop_frac)
                assert delivered < budget

    def test_the_ceiling_still_bounds_participation(self):
        """The reason a ceiling exists at all: an unbounded risk sizer takes
        1,999 shares on a 0.1% stop, 100% of cash in one name, and later
        signals get dropped for want of cash — a participation bug wearing the
        costume of a concentration strategy."""
        cfg = {"risk_pct_per_trade": 0.01,
               "risk_pct_capped_max_notional_pct": 1.0}
        units = _risk_pct_capped(100_000.0, cfg, price=50.0, margined=False,
                                 stop_distance_points=0.05, point_value=1.0)
        assert units * 50.0 == pytest.approx(100_000.0)   # not 1,000,000


class TestDeliveredRiskIsPriceInvariant:
    """End-to-end, through the real engine — the headline defect.

    Asserts a RATIO across prices rather than an absolute value, because the
    absolute is off by the raw-vs-slipped anchor drift: sizing divides by
    `raw_entry_price` while `InitialRisk` is measured from the slipped
    `entry_price`. That drift is mode-independent, so it cancels in the ratio
    and shows up as a bounded absolute error, checked separately below.
    """

    def _delivered(self, price):
        res = _run("AAA", "risk_pct_capped",
                   {"type": "percentage", "value": 0.05}, price=price,
                   max_portfolio_heat=1.0, max_pct_adv=0.0)
        assert res is not None and res["trade_log"], (
            "no trade at price %s -- assert the trade EXISTS before asserting "
            "its size, or an empty log reads as agreement" % price)
        t = res["trade_log"][0]
        assert t["InitialRisk"] > 0, (
            "InitialRisk fell back to the 1%-of-PRICE proxy, which is a "
            "different quantity from 1% of EQUITY and lands in the same "
            "numeric neighbourhood -- that reads as a pass")
        return t["Shares"] * t["InitialRisk"]

    def test_risk_does_not_vary_with_price(self):
        risks = [self._delivered(p) for p in (20.0, 100.0, 1000.0, 5000.0)]
        assert max(risks) / min(risks) == pytest.approx(1.0, abs=1e-6), risks

    def test_delivered_risk_is_the_configured_budget_within_anchor_drift(self):
        delivered = self._delivered(1000.0)
        target = 100_000.0 * 0.01
        # Tolerance is the anchor drift and nothing more: sizing divides by the
        # raw price, InitialRisk is measured off the slipped fill, so the ratio
        # is (1+slippage) = 1.0005 at the default 5 bp. Deliberately tight --
        # a tolerance wide enough to absorb a real sizing error would also
        # absorb the defect this ticket exists to fix.
        assert delivered == pytest.approx(target, rel=0.002), (
            delivered, target)
