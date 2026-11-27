"""Regression tests for #488: cash-clipped entries lost to float rounding.

When a sized entry costs more than the available cash, the engine clips the
share count to ``cash / (price + commission_per_share)``. Recomputing the cost
as ``shares * price + shares * commission`` can land a few ULPs ABOVE cash
(~1.5e-11 on a $100k book). A strict ``cash >= total_cost`` check then
rejected the entry silently. That hit all-in books (``allocation_per_trade =
1.0``) and same-day switches, where an exit at a gap-down open frees less cash
than the allocation sized off the prior close.

The engine steps the clipped size down by representable floats until the cost
fits, so the entry fills and cash never goes negative. These tests pin that
behaviour on the long path, the equity short path and a two-symbol switch.
"""

import pandas as pd
import pytest

from config import CONFIG
from helpers.portfolio_simulations import run_portfolio_simulation

CASH = 100_000.0
COMMISSION = 0.002

# Prices where s = cash / (p + c) gives s*p + s*c > cash in IEEE-754 doubles.
OVERSHOOT_PRICES = [2.436528526762873, 2.4983867666652984, 2.4634568331021196]
# Rebuilding cash from the trade log can differ from the engine's own cash by
# ~1e-16 relative; allow that much, far below any real overdraw.
CASH_RTOL = 1e-12


@pytest.fixture
def frictionless(monkeypatch):
    """Zero slippage/impact so the fill price IS the repro price."""
    for key, value in {
            "execution_time": "open",
            "position_sizing_method": "fixed",
            "max_portfolio_heat": 1.0,
            "max_pct_adv": 0.0,
            "volume_impact_coeff": 0.0,
            "slippage_pct": 0.0,
            "commission_per_share": COMMISSION,
            "htb_rate_annual": 0.0,
    }.items():
        monkeypatch.setitem(CONFIG, key, value)


def _flat(dates, price):
    df = pd.DataFrame({"Open": price, "High": price * 1.001, "Low": price * 0.999,
                       "Close": price, "Volume": 1e9}, index=dates)
    df["ATR_14"] = 0.01
    return df


def _cost(trade):
    return trade["Shares"] * trade["EntryPrice"] + trade["Shares"] * COMMISSION


def _assert_naive_clip_overshoots(cash, price):
    """Precondition (a): the inputs really hit the rounding path.

    Clipping to cash / (p + c) and recomputing s*p + s*c must land a few ULPs
    ABOVE cash; otherwise the engine test would pass without exercising the
    #488 bug. Each engine test checks this for its own inputs.
    """
    shares = cash / (price + COMMISSION)
    total_cost = shares * price + shares * COMMISSION
    assert total_cost > cash, "inputs no longer trigger the float overshoot"
    assert total_cost - cash < 1e-9 * cash   # float noise, not a real shortfall


# --------------------------------------------------------------------------
# (b) All-in long entry (allocation_per_trade = 1.0) must fill.
# --------------------------------------------------------------------------
class TestAllInLongEntryFills:
    @pytest.mark.parametrize("price", OVERSHOOT_PRICES)
    @pytest.mark.parametrize("execution_time", ["open", "close"])
    def test_all_in_entry_fills_without_overdraw(
            self, frictionless, monkeypatch, price, execution_time):
        _assert_naive_clip_overshoots(CASH, price)
        monkeypatch.setitem(CONFIG, "execution_time", execution_time)
        dates = pd.bdate_range("2024-01-02", periods=6)
        sig = pd.Series([0, 1, 0, 0, -1, 0], index=dates)
        result = run_portfolio_simulation(
            {"T": _flat(dates, price)}, {"T": sig}, CASH, 1.0,
            None, None, None, {"type": "none"})
        assert result is not None and result["trade_log"], (
            "all-in entry was dropped by the cash-clip rounding check")
        trade, = result["trade_log"]
        # Clipped to cash, reduced by at most a few ULPs.
        assert trade["Shares"] == pytest.approx(CASH / (price + COMMISSION), rel=1e-12)
        # Never spends more than the cash it had.
        assert _cost(trade) <= CASH


# --------------------------------------------------------------------------
# Equity short entry clipped to cash (same arithmetic, other leg).
# --------------------------------------------------------------------------
class TestAllInShortEntryFills:
    @pytest.mark.parametrize("price", OVERSHOOT_PRICES)
    def test_all_in_short_fills_without_overdraw(
            self, frictionless, monkeypatch, price):
        # Full-notional collateral so the clip is cash / (fill + commission).
        monkeypatch.setitem(CONFIG, "short_margin_requirement", 1.0)
        _assert_naive_clip_overshoots(CASH, price)
        dates = pd.bdate_range("2024-01-02", periods=6)
        sig = pd.Series([0, -2, 0, 0, -1, 0], index=dates)
        result = run_portfolio_simulation(
            {"T": _flat(dates, price)}, {"T": sig}, CASH, 1.0,
            None, None, None, {"type": "none"})
        assert result is not None and result["trade_log"], (
            "all-in short entry was dropped by the cash-clip rounding check")
        trade, = result["trade_log"]
        assert trade["Shares"] == pytest.approx(CASH / (price + COMMISSION), rel=1e-12)
        assert _cost(trade) <= CASH


# --------------------------------------------------------------------------
# (c) Same-day switch: exit at a gap-down open frees less cash than the
#     allocation sized off the prior close, so the new entry is clipped.
# --------------------------------------------------------------------------
class TestSameDaySwitchFills:
    @pytest.mark.parametrize("price", [2.436528526762873, 2.4634568331021196])
    def test_switch_entry_fills_after_gap_down_exit(self, frictionless, price):
        dates = pd.bdate_range("2024-01-02", periods=8)
        a = _flat(dates, 10.0)
        a.loc[dates[4], ["Open", "Low"]] = [9.0, 8.9]   # gap down on the switch day
        b = _flat(dates, price)
        sig_a = pd.Series([1, 0, 0, -1, 0, 0, 0, 0], index=dates)
        sig_b = pd.Series([0, 0, 0, 1, 0, 0, -1, 0], index=dates)
        result = run_portfolio_simulation(
            {"A": a, "B": b}, {"A": sig_a, "B": sig_b}, CASH, 0.999,
            None, None, None, {"type": "none"})
        trades = {t["Symbol"]: t for t in result["trade_log"]}
        assert "B" in trades, "switch entry was dropped by the cash-clip rounding check"
        a_trade, b_trade = trades["A"], trades["B"]
        assert b_trade["EntryDate"] == a_trade["ExitDate"], "not a same-day switch"
        # Cash available at the switch: what A's round trip left behind.
        cash_at_switch = CASH + a_trade["Profit"]
        _assert_naive_clip_overshoots(cash_at_switch, price)
        assert b_trade["Shares"] == pytest.approx(
            cash_at_switch / (price + COMMISSION), rel=1e-12), "entry was not clipped to cash"
        assert _cost(b_trade) <= cash_at_switch * (1 + CASH_RTOL)


# --------------------------------------------------------------------------
# (d) #496: the long clamp and step-down price the entry through the same
#     instrument helpers that charge the fill, not through the global
#     commission_per_share. A per-symbol commission override used to make the
#     clamp size off one cost while the fill and the exit charged another.
# --------------------------------------------------------------------------
# (commission_value, commission_model, price). Each price makes
# s = cash / (p + commission_value) overshoot cash, so the step-down loop
# itself runs under the overridden commission.
OVERRIDE_CASES = [
    (0.0, "per_share", 2.535882004306689),
    (0.05, "per_share", 2.0465826806177563),
    (1.0, "per_contract", 2.573025940277384),
]


def _assert_clip_overshoots(cash, price, commission):
    shares = cash / (price + commission)
    total_cost = shares * price + shares * commission
    assert total_cost > cash, "inputs no longer trigger the float overshoot"
    assert total_cost - cash < 1e-9 * cash


class TestLongClipUsesInstrumentCost:
    @pytest.mark.parametrize("commission_value, commission_model, price", OVERRIDE_CASES)
    @pytest.mark.parametrize("execution_time", ["open", "close"])
    def test_clip_and_charge_use_overridden_commission(
            self, frictionless, monkeypatch, commission_value, commission_model,
            price, execution_time):
        # Self-guard: the override must differ from the global, or the old
        # inline formula would agree with the helper and the test proves nothing.
        assert commission_value != COMMISSION
        _assert_clip_overshoots(CASH, price, commission_value)
        monkeypatch.setitem(CONFIG, "execution_time", execution_time)
        monkeypatch.setitem(CONFIG, "instruments", {"overrides": {"T": {
            "commission_model": commission_model,
            "commission_value": commission_value,
        }}})
        dates = pd.bdate_range("2024-01-02", periods=6)
        sig = pd.Series([0, 1, 0, 0, -1, 0], index=dates)
        result = run_portfolio_simulation(
            {"T": _flat(dates, price)}, {"T": sig}, CASH, 1.0,
            None, None, None, {"type": "none"})
        assert result is not None and result["trade_log"], "all-in entry was dropped"
        trade, = result["trade_log"]
        shares, fill = trade["Shares"], trade["EntryPrice"]

        # Clipped against the instrument's commission, not the global one.
        assert shares == pytest.approx(CASH / (price + commission_value), rel=1e-12)
        assert shares != pytest.approx(CASH / (price + COMMISSION), rel=1e-9)
        # The cost affordability tested is the cost charged, and it fits.
        assert shares * fill + shares * commission_value <= CASH
        # Both sides charged the instrument commission (flat price, no slippage).
        assert trade["Profit"] == pytest.approx(-2 * shares * commission_value, abs=1e-6)
        # Cash accounting closes: what the entry debited is what the trade log
        # says it cost. The pre-#496 clamp debited the global commission while
        # the log booked the override, leaving these apart by
        # shares * |override - global|.
        final_equity = result["portfolio_timeline"].iloc[-1]
        assert final_equity == pytest.approx(CASH + trade["Profit"], rel=CASH_RTOL)
