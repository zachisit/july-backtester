"""
Regression tests for issue #312 — equity short entries bypassed the cost
mechanics that the long entry path applies.

For a CASH_FULL (equity) short, the entry used to fill at the raw price `ep`
with:
  - no sell-side slippage (the futures branch applied it; the cover leg was
    already slipped, so entries were asymmetrically free),
  - no `max_pct_adv` liquidity cap,
  - no `volume_impact_coeff` market impact,
  - no `check_portfolio_heat` gate.

So every equity short trade was overstated by one side of slippage, could take
unlimited size vs ADV, paid no impact, and ignored the portfolio-heat budget —
systematically flattering short backtests vs long backtests under the identical
cost config. This mirrors the long entry path's four cost mechanics onto the
equity short entry.
"""

import numpy as np
import pandas as pd
import pytest

import helpers.portfolio_simulations as ps
from helpers.portfolio_simulations import run_portfolio_simulation


def _frame(n=6, close=100.0, volume=1_000_000.0):
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": volume, "ATR_14": 1.0},
        index=idx,
    )


def _run_short(df, monkeypatch, **cfg):
    # Deterministic close-execution short: -2 enter bar1, -1 cover bar3.
    monkeypatch.setitem(ps.CONFIG, "execution_time", "close")
    for k, v in cfg.items():
        monkeypatch.setitem(ps.CONFIG, k, v)
    sig = pd.Series(0, index=df.index)
    sig.iloc[1] = -2
    sig.iloc[3] = -1
    return run_portfolio_simulation(
        portfolio_data={"TEST": df}, signals={"TEST": sig},
        initial_capital=100_000.0, allocation_pct=1.0,
        spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"},
    )


class TestEquityShortSlippage:
    def test_short_entry_fills_below_raw_price_by_slippage(self, monkeypatch):
        df = _frame()
        res = _run_short(df, monkeypatch, slippage_pct=0.01,
                         max_pct_adv=0.0, volume_impact_coeff=0.0)
        row = pd.DataFrame(res["trade_log"]).iloc[0]
        # ep = 100 (bar1 close); sell fill = 100 * (1 - 0.01) = 99.0. Was 100.0.
        assert row["EntryPrice"] == pytest.approx(99.0)
        # Share count sizes off the SLIPPED fill, not the raw price.
        assert row["Shares"] == pytest.approx(100_000.0 / 99.0)

    def test_zero_slippage_leaves_entry_at_raw_price(self, monkeypatch):
        df = _frame()
        res = _run_short(df, monkeypatch, slippage_pct=0.0,
                         max_pct_adv=0.0, volume_impact_coeff=0.0)
        row = pd.DataFrame(res["trade_log"]).iloc[0]
        assert row["EntryPrice"] == pytest.approx(100.0)


class TestEquityShortAdvCap:
    def test_short_size_capped_by_adv(self, monkeypatch):
        # Volume 100/bar, max_pct_adv 0.05 -> max 5 shares. Unconstrained size
        # would be ~1000 shares (100k / ~100).
        df = _frame(volume=100.0)
        res = _run_short(df, monkeypatch, slippage_pct=0.0,
                         max_pct_adv=0.05, volume_impact_coeff=0.0)
        row = pd.DataFrame(res["trade_log"]).iloc[0]
        assert row["Shares"] == pytest.approx(5.0), row["Shares"]


class TestEquityShortMarketImpact:
    def test_short_entry_records_impact_and_worsens_fill(self, monkeypatch):
        # coeff>0, order is a fraction of ADV -> impact pushes the SHORT fill
        # lower (worse) and records positive VolumeImpact_bps.
        df = _frame(volume=1_000_000.0)
        res = _run_short(df, monkeypatch, slippage_pct=0.0,
                         max_pct_adv=0.0, volume_impact_coeff=0.5)
        row = pd.DataFrame(res["trade_log"]).iloc[0]
        assert row["EntryPrice"] < 100.0            # impact worsened the short fill
        assert row["VolumeImpact_bps"] > 0.0


class TestEquityShortPortfolioHeat:
    def test_short_rejected_when_over_heat_budget(self, monkeypatch):
        # new risk = notional * target_risk_per_trade (0.02) ~= 100k * 0.02 =
        # 2000 = 2% of equity; a 1% heat cap must reject the entry.
        df = _frame()
        res = _run_short(df, monkeypatch, slippage_pct=0.0, max_pct_adv=0.0,
                         volume_impact_coeff=0.0, max_portfolio_heat=0.01,
                         target_risk_per_trade=0.02)
        # No trades at all -> run_portfolio_simulation returns None. Either that,
        # or (defensively) a non-None result with no short executed.
        assert res is None or all(
            t.get("ExitReason") != "Short Cover" for t in res["trade_log"]
        ), "short should be rejected by the heat gate"

    def test_short_allowed_under_generous_heat(self, monkeypatch):
        df = _frame()
        res = _run_short(df, monkeypatch, slippage_pct=0.0, max_pct_adv=0.0,
                         volume_impact_coeff=0.0, max_portfolio_heat=1.0)
        assert any(t.get("ExitReason") == "Short Cover" for t in res["trade_log"])

    def test_second_concurrent_short_sees_first_shorts_heat(self, monkeypatch):
        # Two symbols short simultaneously, each sized to 0.5 of equity so each
        # short's risk is ~1% of equity (0.5 notional * target_risk 0.02). A 1.5%
        # heat cap admits the first (1%) but must reject the second (1%+1%=2%) —
        # proving short risk is REGISTERED and accumulates (#312 QA), not just
        # checked against longs.
        monkeypatch.setitem(ps.CONFIG, "execution_time", "close")
        monkeypatch.setitem(ps.CONFIG, "slippage_pct", 0.0)
        monkeypatch.setitem(ps.CONFIG, "max_pct_adv", 0.0)
        monkeypatch.setitem(ps.CONFIG, "volume_impact_coeff", 0.0)
        monkeypatch.setitem(ps.CONFIG, "max_portfolio_heat", 0.015)
        monkeypatch.setitem(ps.CONFIG, "target_risk_per_trade", 0.02)
        a, b = _frame(), _frame()
        siga = pd.Series(0, index=a.index); siga.iloc[1] = -2; siga.iloc[4] = -1
        sigb = pd.Series(0, index=b.index); sigb.iloc[1] = -2; sigb.iloc[4] = -1
        res = run_portfolio_simulation(
            portfolio_data={"AAA": a, "BBB": b}, signals={"AAA": siga, "BBB": sigb},
            initial_capital=100_000.0, allocation_pct=0.5,
            spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"},
        )
        shorts = [t for t in (res["trade_log"] if res else []) if str(t["Trade"]).startswith("Short")]
        assert len(shorts) == 1, f"second short should be heat-rejected, got {len(shorts)}"


class TestEquityShortCoverImpact:
    def test_cover_leg_impact_included_in_round_trip_bps(self, monkeypatch):
        # With impact on, VolumeImpact_bps must reflect BOTH entry (sell) and
        # cover (buy) legs — not entry only.
        df = _frame(volume=1_000_000.0)
        res = _run_short(df, monkeypatch, slippage_pct=0.0, max_pct_adv=0.0,
                         volume_impact_coeff=0.5)
        row = pd.DataFrame(res["trade_log"]).iloc[0]
        adv = 1_000_000.0
        shares = row["Shares"]
        one_leg = round(0.5 * (shares / adv) ** 0.5 * 10000, 1)
        # round-trip ~= 2x one leg (entry and cover shares are equal here).
        assert row["VolumeImpact_bps"] == pytest.approx(2 * one_leg, abs=0.2)
