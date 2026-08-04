# tests/test_futures_engine.py
"""
End-to-end tests for FUTURES execution semantics in run_portfolio_simulation
(Phase 2 of the instrument-metadata rewrite, issue #229).

Proves the futures-specific behaviour the equity engine never had:
  TestIntegerContracts   — positions size in whole contracts (fractional floored)
  TestPointValuePnl      — P&L scales by the $/point multiplier
  TestMarginAccounting   — entry reserves margin (not full notional); enables leverage
  TestPointStop          — {"type":"points"} stop exits at entry ± N points
  TestNoFuturesBorrow    — HTB borrow cost never charged on futures shorts

Uses the MES micro contract (auto-detected from the "MESM6" ticker): $5/point,
0.25 tick, 10% initial margin, $2.50/contract commission, 1-tick slippage.
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
from helpers.instruments import resolve_instrument

_PV = 5.0        # MES $/point
_COMM = 2.50     # $/contract
_MARGIN_PCT = 0.10

_FUT_CFG = {
    "slippage_pct": 0.0005,
    "commission_per_share": 0.002,
    "execution_time": "close",
    "risk_free_rate": 0.05,
    "htb_rate_annual": 0.0,
    "volume_impact_coeff": 0.0,
    "max_pct_adv": 0.0,
    "position_sizing_method": "fixed",
    "target_risk_per_trade": 0.02,
    "max_portfolio_heat": 1.0,
    "entry_priority": "alphabetical",
    "exclude_open_positions": False,
    "include_delisted": False,
    "instruments": {
        "default_asset_class": "equity",
        "futures_initial_margin_pct": _MARGIN_PCT,
        "futures_commission_per_contract": _COMM,
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


def _run(portfolio_data, signals, stop_config=None, cfg_over=None,
         initial_capital=100_000.0, allocation_pct=1.0):
    from unittest.mock import patch
    cfg = {**_FUT_CFG, **(cfg_over or {})}
    with patch.dict("config.CONFIG", cfg, clear=False):
        return run_portfolio_simulation(
            portfolio_data=portfolio_data, signals=signals,
            initial_capital=initial_capital, allocation_pct=allocation_pct,
            spy_df=None, vix_df=None, tnx_df=None,
            stop_config=stop_config or {"type": "none"},
        )


# ---------------------------------------------------------------------------
class TestInstrumentResolution:
    def test_mes_ticker_resolves_to_future(self):
        inst = resolve_instrument("MESM6", _FUT_CFG)
        assert inst.asset_class == "future"
        assert inst.point_value == _PV
        assert inst.integer_units is True
        assert inst.margin_mode == "initial_margin"


# ---------------------------------------------------------------------------
class TestIntegerContracts:
    def test_positions_are_whole_contracts(self):
        df = _df([5000, 5010, 5020, 5030, 5040])
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1, 3: -1})})
        assert res is not None
        for t in res["trade_log"]:
            assert t["Shares"] == float(int(t["Shares"])), "contracts must be whole numbers"
            assert t["Shares"] >= 1

    def test_fractional_size_floored(self):
        # capital=100k, alloc=1.0. Margined futures size off margin_required(),
        # not full notional/point_value: raw = 100000 / (margin_pct * entry * $5/pt).
        # (Pre-fix math divided by full notional only, which floored contract
        # counts toward 0 as price appreciated — see TestMarginAccounting above,
        # which pins the equity-collapse regression this margin-based sizing fixes.)
        import math
        df = _df([5000, 5010, 5020, 5030])
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1})}, initial_capital=100_000.0)
        assert res is not None
        t = res["trade_log"][0]
        expected = float(math.floor(100_000.0 / (_MARGIN_PCT * t["EntryPrice"] * _PV)))
        assert t["Shares"] == expected
        assert t["Shares"] == float(int(t["Shares"]))  # whole contracts


# ---------------------------------------------------------------------------
class TestPointValuePnl:
    def test_pnl_scales_by_point_value(self):
        df = _df([5000, 5100, 5200, 5300])
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1, 3: -1})})
        assert res is not None
        t = res["trade_log"][0]
        shares = t["Shares"]
        expected = shares * (t["ExitPrice"] - t["EntryPrice"]) * _PV - 2 * (shares * _COMM)
        assert t["Profit"] == pytest.approx(expected, abs=1e-6)
        # Sanity: a 100-point move on MES ($5/pt) is worth ~$500/contract, not ~$100.
        assert t["Profit"] > shares * 400


# ---------------------------------------------------------------------------
class TestMarginAccounting:
    def test_entry_reserves_margin_not_notional(self):
        # 4 MES @ ~5000 = $100k notional on $100k capital. If entry deducted full
        # notional, equity would collapse to ~0; with 10% margin it stays ~full.
        df = _df([5000, 5010, 5020, 5030, 5040])
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1})})
        assert res is not None
        timeline = res["portfolio_timeline"]
        # Equity right after entry must remain near initial capital (only commission +
        # 1-tick slippage lost), proving notional was NOT debited from cash.
        post_entry = timeline.iloc[2]
        assert post_entry > 99_000.0, f"equity {post_entry} collapsed — notional was debited"

    def test_margin_enables_leverage_two_full_positions(self):
        # Two futures each targeting 100% notional. Full-notional cash accounting could
        # never hold both on 100k; 10% margin (20k reserved) can.
        df1 = _df([5000, 5010, 5020, 5030, 5040])
        df2 = _df([5000, 5010, 5020, 5030, 5040])
        res = _run({"MESM6": df1, "MNQZ6": df2},
                   {"MESM6": _sig(df1, {1: 1, 4: -1}), "MNQZ6": _sig(df2, {1: 1, 4: -1})})
        assert res is not None
        symbols_traded = {t["Symbol"] for t in res["trade_log"]}
        assert symbols_traded == {"MESM6", "MNQZ6"}, "margin should let both positions open"


# ---------------------------------------------------------------------------
class TestPointStop:
    def test_points_stop_exit(self):
        # Enter ~5000, point stop 50 -> stop ~4950; drop below it triggers.
        df = _df([5000, 5000, 4990, 4930, 4900, 4890])
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: 1})},
                   stop_config={"type": "points", "value": 50.0})
        assert res is not None
        t = res["trade_log"][0]
        assert t["ExitReason"] == "Stop Loss (points)"
        # Stop level is anchored to the raw (pre-slippage) entry price, not the
        # slipped fill — slippage is a separate, symmetric friction that must not
        # also shift where the stop sits (see portfolio_simulations.py raw_entry_price
        # anchoring for 'percentage'/'points' stop types).
        raw_entry = t["EntryPrice"] - 0.25  # back out the 1-tick buy slippage
        # stop = raw_entry - 50 points; the fill then takes 1 tick (0.25) of sell slippage.
        assert t["ExitPrice"] == pytest.approx(raw_entry - 50.0 - 0.25, abs=1e-6)


# ---------------------------------------------------------------------------
class TestNoFuturesBorrow:
    def test_futures_short_pays_no_borrow(self):
        # Short with a non-zero HTB rate configured — futures must ignore it.
        df = _df([5000, 4990, 4980, 4970, 4960, 4950])
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: -2, 5: -1})},
                   cfg_over={"htb_rate_annual": 0.05})
        assert res is not None
        t = res["trade_log"][0]
        assert t["Trade"].startswith("Short")
        shares = t["Shares"]
        # Profit == gross (via $/point) minus round-trip commission, with NO borrow debit.
        expected = shares * (t["EntryPrice"] - t["ExitPrice"]) * _PV - 2 * (shares * _COMM)
        assert t["Profit"] == pytest.approx(expected, abs=1e-6)
        assert t["Profit"] > 0  # price fell, short profits


# ---------------------------------------------------------------------------
class TestShortEntrySlippage:
    """Futures short-to-open fills must pay sell-side slippage (#238 review item
    #2), mirroring the buy-side slippage the long path already applies. Before
    this fix, futures shorts filled at the raw, un-slipped price -- an
    unrealistic free-fill asymmetry versus longs. This is a futures-only
    change: the equity short path (cash_full instruments) is untouched and
    still fills at the raw price (no slippage), so this test only pins the
    futures (margin_mode == initial_margin) behaviour."""

    def test_short_entry_price_pays_sell_slippage(self):
        df = _df([5000, 4990, 4980, 4970, 4960, 4950])
        res = _run({"MESM6": df}, {"MESM6": _sig(df, {1: -2, 5: -1})})
        assert res is not None
        t = res["trade_log"][0]
        assert t["Trade"].startswith("Short")
        raw_signal_close = df["Close"].iloc[1]  # un-slipped bar Close (the sell-to-open anchor)
        tick = 0.25  # MES tick size; _FUT_CFG configures 1 tick of slippage
        # A sell-to-open must fill WORSE (lower) than the raw price by one tick,
        # not at the raw price itself.
        assert t["EntryPrice"] == pytest.approx(raw_signal_close - tick, abs=1e-6)
        assert t["EntryPrice"] < raw_signal_close


# ---------------------------------------------------------------------------
class TestDelistedFuturesPosition:
    """Survivorship force-close must honour margin-mode accounting: realise P&L via
    $/point and release margin — NOT credit full notional to cash (which was never
    debited for a futures entry) or leave reserved_margin dangling."""

    def test_force_close_uses_point_value_and_no_phantom_cash(self):
        from unittest.mock import patch
        df = _df([5000, 5000, 4990, 4980, 4970, 4960, 4950, 4940])
        signals = {"MESM6": _sig(df, {1: 1})}  # enter, never exit -> delisting closes it
        delist_ts = df.index[5]
        cfg = {**_FUT_CFG, "include_delisted": True,
               "delisting_price_assumption": "last_close"}
        with patch.dict("config.CONFIG", cfg, clear=False):
            res = run_portfolio_simulation(
                portfolio_data={"MESM6": df}, signals=signals,
                initial_capital=100_000.0, allocation_pct=1.0,
                spy_df=None, vix_df=None, tnx_df=None,
                stop_config={"type": "none"},
                delisting_dates={"MESM6": delist_ts},
            )
        assert res is not None
        t = res["trade_log"][0]
        assert t["ExitReason"] == "Delisting"
        shares = t["Shares"]
        # P&L must be $/point-scaled: shares * (exit - entry) * $5/pt - 2x commission.
        expected = shares * (t["ExitPrice"] - t["EntryPrice"]) * _PV - 2 * (shares * _COMM)
        assert t["Profit"] == pytest.approx(expected, abs=1e-6)
        # Final equity ~= initial + realised loss (small). If the force-close had
        # credited full notional (shares * exit_price ~ $99k of phantom cash), the
        # final timeline value would be ~2x initial capital.
        final_equity = res["portfolio_timeline"].dropna().iloc[-1]
        assert final_equity < 105_000.0, (
            f"final equity {final_equity} — phantom notional credited to cash")
        assert final_equity == pytest.approx(100_000.0 + t["Profit"], rel=0.01)
