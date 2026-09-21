"""
Regression tests for issue #317 — the registered portfolio-heat risk
(``pos['risk']``) was stale.

Two defects:
  1. ``new_position_risk`` was computed from the PRE-clamp share count (before
     the ADV liquidity cap, market impact, ``round_units`` and affordability
     clamps shrink ``shares``), so an ADV-capped position registered far more
     heat than it actually holds, spuriously rejecting later entries.
  2. A partial scale-out reduced ``pos['shares']`` but not ``pos['risk']``, so
     the freed budget was never returned to the heat pot.

Both are observed through ``check_portfolio_heat``: a second entry that the stale
(overstated) risk would reject is admitted once the risk reflects reality.
"""

import numpy as np
import pandas as pd
import pytest

import helpers.portfolio_simulations as ps
from helpers.portfolio_simulations import run_portfolio_simulation


def _frame(volume, n=6, close=100.0):
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": float(volume), "ATR_14": 1.0},
        index=idx,
    )


def _patch(monkeypatch, **cfg):
    monkeypatch.setitem(ps.CONFIG, "execution_time", "close")
    monkeypatch.setitem(ps.CONFIG, "slippage_pct", 0.0)
    monkeypatch.setitem(ps.CONFIG, "exclude_open_positions", False)
    monkeypatch.setitem(ps.CONFIG, "position_sizing_method", "fixed")
    monkeypatch.setitem(ps.CONFIG, "entry_priority", "alphabetical")
    monkeypatch.setitem(ps.CONFIG, "volume_impact_coeff", 0.0)
    monkeypatch.setitem(ps.CONFIG, "max_pct_adv", 0.0)
    monkeypatch.setitem(ps.CONFIG, "target_risk_per_trade", 0.02)
    for k, v in cfg.items():
        monkeypatch.setitem(ps.CONFIG, k, v)


def test_adv_capped_position_registers_post_cap_risk(monkeypatch):
    # AAA volume 1000 -> ADV cap 0.05*1000 = 50 shares (notional 5000, risk 100),
    # vs the uncapped 500 shares (risk 1000 pre-clamp). BBB (volume 1e6) is not
    # capped (risk 1000). With a 1.5% heat cap:
    #   stale bug:  (1000 + 1000)/100000 = 2.0% > 1.5% -> BBB rejected
    #   fixed:      ( 100 + 1000)/100000 = 1.1% <= 1.5% -> BBB admitted
    _patch(monkeypatch, max_pct_adv=0.05, max_portfolio_heat=0.015)
    aaa, bbb = _frame(1000), _frame(1_000_000)
    sig = pd.Series(0, index=aaa.index); sig.iloc[1] = 1
    res = run_portfolio_simulation(
        portfolio_data={"AAA": aaa, "BBB": bbb},
        signals={"AAA": sig.copy(), "BBB": sig.copy()},
        initial_capital=100_000.0, allocation_pct=0.5,
        spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"},
    )
    trades = res["trade_log"] if res else []
    assert any(t["Symbol"] == "BBB" for t in trades), \
        "BBB rejected — AAA registered pre-clamp (overstated) risk (#317)"


def test_partial_scale_out_returns_heat_budget(monkeypatch):
    # AAA enters bar1 (risk 1000). At bar3 AAA scales out 50% (signal -0.5) and
    # BBB tries to enter (risk 1000). With a 1.7% heat cap:
    #   stale bug: AAA risk still 1000 -> (1000+1000)/100000 = 2.0% > 1.7% reject
    #   fixed:     AAA risk halved 500 -> ( 500+1000)/100000 = 1.5% <= 1.7% admit
    _patch(monkeypatch, max_portfolio_heat=0.017)
    aaa, bbb = _frame(1_000_000), _frame(1_000_000)
    sig_a = pd.Series(0.0, index=aaa.index); sig_a.iloc[1] = 1.0; sig_a.iloc[3] = -0.5
    sig_b = pd.Series(0.0, index=bbb.index); sig_b.iloc[3] = 1.0
    res = run_portfolio_simulation(
        portfolio_data={"AAA": aaa, "BBB": bbb},
        signals={"AAA": sig_a, "BBB": sig_b},
        initial_capital=100_000.0, allocation_pct=0.5,
        spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"},
    )
    trades = res["trade_log"] if res else []
    assert any(t["ExitReason"] == "Partial Scale-Out" for t in trades), \
        "expected a partial scale-out"
    assert any(t["Symbol"] == "BBB" for t in trades), \
        "BBB rejected — AAA's risk not reduced on the partial scale-out (#317)"


def test_registered_risk_magnitude_is_post_clamp(monkeypatch):
    # Spy on check_portfolio_heat to read the risk AAA registered when BBB is
    # evaluated. AAA is ADV-capped to 50 shares -> risk = 50*100*0.02 = 100
    # (NOT the pre-clamp 500*100*0.02 = 1000). Pins the recompute formula, not
    # just the admit/reject boundary.
    _patch(monkeypatch, max_pct_adv=0.05, max_portfolio_heat=1.0)
    seen = {}
    real = ps.check_portfolio_heat

    def _spy(positions, new_risk, equity, max_heat):
        # Record AAA's stored risk at the moment BBB's entry is evaluated.
        if "AAA" in positions:
            seen["aaa_risk"] = positions["AAA"].get("risk")
        return real(positions, new_risk, equity, max_heat)
    monkeypatch.setattr(ps, "check_portfolio_heat", _spy)

    aaa, bbb = _frame(1000), _frame(1_000_000)
    sig = pd.Series(0.0, index=aaa.index); sig.iloc[1] = 1.0
    run_portfolio_simulation(
        portfolio_data={"AAA": aaa, "BBB": bbb},
        signals={"AAA": sig.copy(), "BBB": sig.copy()},
        initial_capital=100_000.0, allocation_pct=0.5,
        spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"},
    )
    assert seen.get("aaa_risk") == pytest.approx(100.0), seen  # 50 * 100 * 0.02


def test_adv_capped_short_registers_post_cap_risk(monkeypatch):
    # Short mirror of test 1: AAA short is ADV-capped; a second short (BBB) is
    # admitted only because AAA's registered short risk is post-cap. Pins the
    # short-path recompute line.
    _patch(monkeypatch, max_pct_adv=0.05, max_portfolio_heat=0.015)
    aaa, bbb = _frame(1000), _frame(1_000_000)
    sig = pd.Series(0.0, index=aaa.index); sig.iloc[1] = -2.0
    res = run_portfolio_simulation(
        portfolio_data={"AAA": aaa, "BBB": bbb},
        signals={"AAA": sig.copy(), "BBB": sig.copy()},
        initial_capital=100_000.0, allocation_pct=0.5,
        spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"},
    )
    trades = res["trade_log"] if res else []
    assert any(t["Symbol"] == "BBB" and str(t["Trade"]).startswith("Short") for t in trades), \
        "BBB short rejected — AAA registered pre-clamp short risk (#317)"


def test_two_partial_scale_outs_compound(monkeypatch):
    # −0.5 then −0.5 leaves 25% of the position -> risk should be ×0.25. Read it
    # via the spy at a third entry's heat check.
    _patch(monkeypatch, max_portfolio_heat=1.0)
    seen = {}
    real = ps.check_portfolio_heat

    def _spy(positions, new_risk, equity, max_heat):
        if "AAA" in positions:
            seen["aaa_risk"] = positions["AAA"].get("risk")
        return real(positions, new_risk, equity, max_heat)
    monkeypatch.setattr(ps, "check_portfolio_heat", _spy)

    aaa, bbb = _frame(1_000_000, n=8), _frame(1_000_000, n=8)
    sig_a = pd.Series(0.0, index=aaa.index)
    sig_a.iloc[1] = 1.0; sig_a.iloc[3] = -0.5; sig_a.iloc[5] = -0.5
    sig_b = pd.Series(0.0, index=bbb.index); sig_b.iloc[6] = 1.0  # entry after both scale-outs
    run_portfolio_simulation(
        portfolio_data={"AAA": aaa, "BBB": bbb},
        signals={"AAA": sig_a, "BBB": sig_b},
        initial_capital=100_000.0, allocation_pct=0.5,
        spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"},
    )
    # AAA full risk 1000 (500 sh * 100 * 0.02); after ×0.5 ×0.5 -> 250.
    assert seen.get("aaa_risk") == pytest.approx(250.0), seen
