"""Target-weight portfolio engine, VIX eVRP plugin, runner and report (issue #487)."""
import json
import os
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from helpers import target_weight_portfolio as twp  # noqa: E402
from helpers.target_weight_portfolio import (  # noqa: E402
    FundingViolation, settlement_dates, simulate_target_weights,
)

PLUGIN = "VIX eVRP Dual (SGOV funded)"


def _ensure_plugin_registered():
    """Other test modules clear the registry; re-import the plugin if so."""
    import importlib
    from helpers.registry import _REGISTRY
    if PLUGIN not in _REGISTRY:
        from custom_strategies import vix_evrp_sgov
        importlib.reload(vix_evrp_sgov)
    assert PLUGIN in _REGISTRY


@pytest.fixture(autouse=True)
def _plugin_registered():
    _ensure_plugin_registered()


RISK = ["VIXY", "SVXY"]
CASH = "SGOV"
EXPOSURE = {"VIXY": 1.0, "SVXY": -0.5, "SGOV": 0.0}
COSTS = {"VIXY": 5.0, "SVXY": 5.0, "SGOV": 1.0}


def _flat(n=6, start="2020-01-06"):
    dates = pd.bdate_range(start, periods=n)
    prices = pd.DataFrame(100.0, index=dates, columns=RISK + [CASH])
    return prices


def _targets(dates, exposure):
    exposure = pd.Series(exposure, index=dates, dtype=float)
    return pd.DataFrame({"VIXY": exposure.clip(lower=0), "SVXY": (-2 * exposure).clip(lower=0)})


def _sim(opens, closes, targets, **kw):
    kw.setdefault("exposure", EXPOSURE)
    kw.setdefault("cost_bps", COSTS)
    return simulate_target_weights(opens, closes, targets, RISK, CASH, **kw)


def _random_market(seed, n=300):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2021-01-04", periods=n)
    out_o, out_c = {}, {}
    for s, vol in (("VIXY", 0.05), ("SVXY", 0.03), ("SGOV", 0.0005)):
        close = 50 * np.exp(np.cumsum(rng.normal(0, vol, n)))
        open_ = close * np.exp(rng.normal(0, vol / 2, n))
        out_o[s], out_c[s] = open_, close
    return pd.DataFrame(out_o, index=dates), pd.DataFrame(out_c, index=dates), rng


# ---------------------------------------------------------------------------
# Engine: funding, settlement, costs, causality
# ---------------------------------------------------------------------------

class TestFunding:
    def test_all_cash_sleeve_pays_initial_cost_only(self):
        p = _flat()
        r = _sim(p, p, _targets(p.index, 0.0))
        np.testing.assert_allclose(r.nav, 1 / 1.0001)
        assert r.ledger["SGOV_weight"].eq(1).all()
        assert r.ledger["unsettled"].sum() == 0

    def test_sale_proceeds_wait_for_settlement(self):
        p = _flat()  # Mon 2020-01-06 .. Mon 2020-01-13, T+2 era
        r = _sim(p, p, _targets(p.index, -0.2), cost_bps={})
        led = r.ledger
        # Day 1: SGOV sold at the open; proceeds settle T+2 -> no SVXY yet.
        assert led["SVXY_shares"].iloc[1] == 0
        assert led["SVXY_shares"].iloc[2] == 0
        assert led["unsettled"].iloc[1] == pytest.approx(0.4)
        assert bool(led["target_unfilled_at_open"].iloc[1])
        assert led["SVXY_weight"].iloc[3] == pytest.approx(0.4)
        np.testing.assert_allclose(led["nav"], 1.0)

    def test_latest_signal_supersedes_waiting_intention(self):
        p = _flat()
        t = pd.Series(0.2, index=p.index)
        t.iloc[0] = -0.2
        r = _sim(p, p, _targets(p.index, t), cost_bps={})
        assert r.ledger["SVXY_shares"].sum() == 0
        assert r.ledger["VIXY_weight"].iloc[3] == pytest.approx(0.2)
        assert r.ledger["SGOV_weight"].iloc[3] == pytest.approx(0.8)

    def test_immediate_benchmark_reuses_proceeds_same_open(self):
        p = _flat()
        r = _sim(p, p, _targets(p.index, -0.2), cost_bps={}, settlement=twp.IMMEDIATE)
        assert r.ledger["SVXY_weight"].iloc[1] == pytest.approx(0.4)
        assert r.ledger["SGOV_weight"].iloc[1] == pytest.approx(0.6)
        assert r.ledger["unsettled"].sum() == 0

    @pytest.mark.parametrize("seed", range(5))
    def test_random_paths_never_borrow_or_short(self, seed):
        opens, closes, rng = _random_market(seed)
        exposure = rng.choice([-0.2, -0.1, 0.0, 0.2], size=len(opens))
        for mode in (twp.SETTLED_ONLY, twp.IMMEDIATE):
            r = _sim(opens, closes, _targets(opens.index, exposure), settlement=mode,
                     initial_capital=250_000.0)
            led = r.ledger
            assert (led["cash"] >= 0).all()
            assert (led["unsettled"] >= 0).all()
            assert (led[[f"{s}_shares" for s in r.symbols]] >= 0).all().all()
            value = sum(led[f"{s}_value"] for s in r.symbols) + led["cash"] + led["unsettled"]
            np.testing.assert_allclose(value, led["nav"], rtol=1e-12)
            weights = sum(led[f"{s}_weight"] for s in r.symbols) + led["unsettled_weight"] \
                + led["cash"] / led["nav"]
            np.testing.assert_allclose(weights, 1.0, atol=1e-12)
            assert (r.fills["Shares"] > 0).all()

    def test_leverage_and_short_targets_are_rejected(self):
        p = _flat()
        bad = pd.DataFrame({"VIXY": 0.7, "SVXY": 0.7}, index=p.index)
        with pytest.raises(ValueError, match="borrowing"):
            _sim(p, p, bad)
        neg = pd.DataFrame({"VIXY": -0.2, "SVXY": 0.0}, index=p.index)
        with pytest.raises(ValueError, match="shorting"):
            _sim(p, p, neg)

    def test_invalid_prices_rejected(self):
        p = _flat()
        q = p.copy()
        q.iloc[2, 0] = np.nan
        with pytest.raises(ValueError, match="positive"):
            _sim(q, p, _targets(p.index, 0.0))


class TestCosts:
    def test_initial_purchase_and_rebalance_costs(self):
        p = _flat(n=8)
        r = _sim(p, p, _targets(p.index, -0.2), settlement=twp.IMMEDIATE)
        led, fills = r.ledger, r.fills
        # Every cost is fee-rate x traded notional, and it is the only NAV leak
        # at constant prices.
        rate = fills["Symbol"].map(COSTS) / 10000
        np.testing.assert_allclose(fills["Cost"], fills["Notional"] * rate, rtol=1e-12)
        np.testing.assert_allclose(led["cost"].sum(), fills["Cost"].sum(), rtol=1e-12)
        np.testing.assert_allclose(1.0 - led["nav"].iloc[-1], led["cost"].sum(), rtol=1e-9)
        assert led["cost"].iloc[0] == pytest.approx(1e-4 / 1.0001)

    def test_cost_override_changes_only_costs(self):
        p = _flat(n=8)
        cheap = _sim(p, p, _targets(p.index, -0.2), cost_bps={})
        assert cheap.ledger["cost"].sum() == 0
        np.testing.assert_allclose(cheap.nav, 1.0)


class TestRebalanceRule:
    def _drift(self, svxy_move):
        dates = pd.bdate_range("2020-01-06", periods=8)
        o = pd.DataFrame(100.0, index=dates, columns=RISK + [CASH])
        o.loc[dates[5]:, "SVXY"] = 100.0 * svxy_move
        return o

    def test_within_band_no_trade(self):
        o = self._drift(1.04)  # 40% SVXY drifts to ~-20.6% exposure: inside 2pp
        r = _sim(o, o, _targets(o.index, -0.2), cost_bps={}, settlement=twp.IMMEDIATE)
        assert not r.ledger["rebalanced"].iloc[5:].any()

    def test_outside_band_trades(self):
        o = self._drift(1.30)  # drifts to ~-24.6%: outside 2pp
        r = _sim(o, o, _targets(o.index, -0.2), cost_bps={}, settlement=twp.IMMEDIATE)
        assert r.ledger["rebalanced"].iloc[5]
        assert r.ledger["exposure_open_after"].iloc[5] == pytest.approx(-0.2)

    def test_product_exit_and_sign_change_trade(self):
        p = _flat(n=6)
        t = pd.Series([-0.2, -0.2, 0.0, 0.0, 0.2, 0.2], index=p.index)
        r = _sim(p, p, _targets(p.index, t), cost_bps={}, settlement=twp.IMMEDIATE)
        led = r.ledger
        assert led["rebalanced"].iloc[3] and led["SVXY_shares"].iloc[3] == 0
        assert led["rebalanced"].iloc[5] and led["VIXY_weight"].iloc[5] == pytest.approx(0.2)

    def test_weights_band_basis_without_exposure(self):
        p = _flat(n=5)
        tw = pd.DataFrame({"VIXY": 0.3, "SVXY": 0.1}, index=p.index)
        r = simulate_target_weights(p, p, tw, RISK, CASH, exposure=None, settlement=twp.IMMEDIATE)
        assert r.ledger["VIXY_weight"].iloc[1] == pytest.approx(0.3)
        assert r.ledger["SVXY_weight"].iloc[1] == pytest.approx(0.1)
        assert not r.ledger["rebalanced"].iloc[2:].any()


class TestCausality:
    def test_target_executes_next_open_only(self):
        opens, closes, rng = _random_market(7, n=60)
        t = pd.Series(rng.choice([-0.2, -0.1, 0.0, 0.2], size=60), index=opens.index)
        base = _sim(opens, closes, _targets(opens.index, t)).ledger
        for k in (10, 30, 59):
            t2 = t.copy()
            t2.iloc[k] = 0.2 if t.iloc[k] != 0.2 else -0.2
            alt = _sim(opens, closes, _targets(opens.index, t2)).ledger
            pd.testing.assert_frame_equal(base.iloc[:k + 1], alt.iloc[:k + 1])
        assert base["target"].iloc[0] == 0.0  # session 0 starts in the cash sleeve

    def test_scale_invariance(self):
        opens, closes, rng = _random_market(3, n=120)
        t = rng.choice([-0.2, -0.1, 0.0, 0.2], size=120)
        a = _sim(opens, closes, _targets(opens.index, t), initial_capital=1.0)
        b = _sim(opens, closes, _targets(opens.index, t), initial_capital=1e6)
        np.testing.assert_allclose(a.returns, b.returns, atol=1e-12)
        assert (a.ledger["rebalanced"] == b.ledger["rebalanced"]).all()


class TestSettlementCalendar:
    def test_t2_to_t1_cutover_and_bank_holidays(self):
        sessions = pd.DatetimeIndex(["2024-05-23", "2024-05-24", "2024-05-28", "2024-05-29",
                                     "2024-05-30", "2024-10-10", "2024-10-11", "2024-10-14",
                                     "2024-10-15", "2024-10-16"])
        m = settlement_dates(sessions)
        assert m[pd.Timestamp("2024-05-24")] == pd.Timestamp("2024-05-29")  # T+2 over Memorial Day
        assert m[pd.Timestamp("2024-05-28")] == pd.Timestamp("2024-05-29")  # T+1 from cut-over
        # Columbus Day: exchange open, banks closed -> not a settlement day.
        assert m[pd.Timestamp("2024-10-11")] == pd.Timestamp("2024-10-15")
        assert m[pd.Timestamp("2024-10-10")] == pd.Timestamp("2024-10-11")

    def test_last_session_before_good_friday(self):
        # Friday is a bank day, but XNYS is closed even beyond the supplied data.
        thursday = pd.Timestamp("2025-04-17")
        assert settlement_dates(pd.DatetimeIndex([thursday]))[thursday] == pd.Timestamp("2025-04-21")

    def test_last_session_settles_after_data_end(self):
        sessions = pd.bdate_range("2023-03-01", periods=3)
        m = settlement_dates(sessions)
        assert m[sessions[-1]] > sessions[-1]


class TestMetrics:
    def test_metrics_definitions(self):
        r = pd.Series([0.01, -0.02, 0.005, 0.0], index=pd.bdate_range("2024-01-01", periods=4))
        m = twp.performance_metrics(r, cash_reference=pd.Series(0.0, index=r.index))
        wealth = (1 + r).cumprod()
        assert m["total_return"] == pytest.approx(wealth.iloc[-1] - 1)
        assert m["max_drawdown"] == pytest.approx(wealth.iloc[1] / wealth.iloc[0] - 1)
        assert m["cagr"] == pytest.approx(wealth.iloc[-1] ** (252 / 4) - 1)
        assert m["sharpe_cash_reference"] == pytest.approx(m["sharpe_rf0"])

    def test_buy_and_hold_first_session_open_with_cost(self):
        idx = pd.bdate_range("2024-01-01", periods=3)
        o = pd.Series([100.0, 101, 102], index=idx)
        c = pd.Series([101.0, 102, 103], index=idx)
        r = twp.buy_and_hold_returns(o, c, 5)
        assert r.iloc[0] == pytest.approx(101 / 100 / 1.0005 - 1)
        assert r.iloc[1] == pytest.approx(102 / 101 - 1)


# ---------------------------------------------------------------------------
# VIX eVRP plugin
# ---------------------------------------------------------------------------

class TestVixEvrpSignal:
    @pytest.fixture(scope="class")
    def mod(self):
        from custom_strategies import vix_evrp_sgov
        return vix_evrp_sgov

    def test_evrp_formula_and_states(self, mod):
        idx = pd.bdate_range("2024-01-01", periods=15)
        spy = pd.Series(100 * np.cumprod(1 + np.linspace(-0.01, 0.012, 15)), index=idx)
        rv = spy.pct_change().iloc[-10:].std(ddof=1) * np.sqrt(252) * 100
        cases = {  # (vix, vix3m) -> state, target
            "strong": (rv + 5, rv + 8, mod.STATE_STRONG_INVERSE, -0.2),
            "weak": (rv - 1, rv + 3, mod.STATE_WEAK_INVERSE, -0.1),
            "long": (rv - 1, rv - 3, mod.STATE_LONG_VOL, 0.2),
            "flat_curve": (rv - 1, rv - 1, mod.STATE_CASH, 0.0),
            "backwardated_positive_premium": (rv + 5, rv + 2, mod.STATE_CASH, 0.0),
        }
        for name, (v, v3, state, target) in cases.items():
            out = mod.evrp_dual_signal(spy, pd.Series(v, index=idx), pd.Series(v3, index=idx))
            assert out["evrp"].iloc[-1] == pytest.approx(v - rv), name
            assert out["state"].iloc[-1] == state, name
            assert out["target_exposure"].iloc[-1] == target, name
        warm = mod.evrp_dual_signal(spy, pd.Series(20.0, index=idx), pd.Series(25.0, index=idx))
        assert warm["target_exposure"].iloc[:10].isna().all()  # needs 10 returns

    def test_missing_vix_has_no_target_and_basket_mapping(self, mod):
        idx = pd.bdate_range("2024-01-01", periods=15)
        spy = pd.Series(np.linspace(100, 110, 15), index=idx)
        vix = pd.Series(30.0, index=idx).drop(idx[-1])
        out = mod.evrp_dual_signal(spy, vix, pd.Series(40.0, index=idx))
        assert pd.isna(out["target_exposure"].iloc[-1])
        w = mod.basket_from_exposure(pd.Series([-0.2, -0.1, 0.2, 0.0]))
        assert w.values.tolist() == [[0.0, 0.4], [0.0, 0.2], [0.2, 0.0], [0.0, 0.0]]

    def test_signal_uses_only_completed_sessions(self, mod):
        rng = np.random.default_rng(1)
        idx = pd.bdate_range("2023-01-02", periods=80)
        spy = pd.Series(400 * np.cumprod(1 + rng.normal(0, 0.01, 80)), index=idx)
        vix = pd.Series(rng.uniform(12, 30, 80), index=idx)
        vix3m = vix + rng.normal(1, 2, 80)
        base = mod.evrp_dual_signal(spy, vix, vix3m)
        spy2, vix2 = spy.copy(), vix.copy()
        spy2.iloc[50:] *= 1.3
        vix2.iloc[50:] = 80
        alt = mod.evrp_dual_signal(spy2, vix2, vix3m)
        pd.testing.assert_frame_equal(base.iloc[:50], alt.iloc[:50])


class TestRegistry:
    def test_target_weight_plugin_isolated_from_signal_pipeline(self):
        from helpers.registry import get_active_strategies, get_target_weight_strategies
        tw = get_target_weight_strategies()
        assert "VIX eVRP Dual (SGOV funded)" in tw
        entry = tw["VIX eVRP Dual (SGOV funded)"]
        assert entry["symbols"] == ["VIXY", "SVXY"] and entry["cash_symbol"] == "SGOV"
        assert entry["cost_bps"] == {"VIXY": 5.0, "SVXY": 5.0, "SGOV": 1.0}
        assert entry["band"] == 0.02
        assert "VIX eVRP Dual (SGOV funded)" not in get_active_strategies()


# ---------------------------------------------------------------------------
# Runner -> artifacts -> report.py
# ---------------------------------------------------------------------------

def synthetic_universe(seed=11, start="2020-01-01", n=420):
    rng = np.random.default_rng(seed)
    idx = twp.xnys_sessions(start, pd.Timestamp(start) + pd.Timedelta(days=n*2))[:n]
    out = {}

    def ohlc(close, noise):
        open_ = close * np.exp(rng.normal(0, noise, len(close)))
        return pd.DataFrame({"Open": open_, "High": np.maximum(open_, close) * 1.001,
                             "Low": np.minimum(open_, close) * 0.999, "Close": close,
                             "Volume": 1e6}, index=idx)

    out["SPY"] = ohlc(300 * np.cumprod(1 + rng.normal(0.0004, 0.012, n)), 0.004)
    vix = np.clip(18 + np.cumsum(rng.normal(0, 1.2, n)) * 0.3 + rng.normal(0, 2, n), 9, 80)
    out["I:VIX"] = ohlc(vix, 0.01)
    out["I:VIX3M"] = ohlc(vix + rng.normal(1.5, 2.0, n), 0.01)
    out["VIXY"] = ohlc(20 * np.cumprod(1 + rng.normal(-0.002, 0.04, n)), 0.01)
    out["SVXY"] = ohlc(50 * np.cumprod(1 + rng.normal(0.001, 0.02, n)), 0.005)
    out["SGOV"] = ohlc(100 * np.cumprod(np.full(n, 1.0001)), 0.00005)
    return out


def _fetcher(universe):
    def fetch(symbol, start, end, config):
        df = universe.get(symbol)
        if df is None:
            return None
        df = df.copy()
        df.index = df.index.tz_localize("UTC")
        return df.loc[pd.Timestamp(start, tz="UTC"):pd.Timestamp(end, tz="UTC")]
    return fetch


def _config(**over):
    cfg = {"portfolio_strategy": "VIX eVRP Dual (SGOV funded)", "start_date": "2020-07-01",
           "end_date": "2021-07-30", "initial_capital": 100000.0, "pit_warmup_days": 400,
           "data_provider": "synthetic"}
    cfg.update(over)
    return cfg


@pytest.fixture(scope="module")
def portfolio_run(tmp_path_factory):
    from helpers.target_weight_runner import run_target_weight_backtest
    _ensure_plugin_registered()
    run_dir = tmp_path_factory.mktemp("run")
    summary = run_target_weight_backtest(_config(), str(run_dir), "test-run", _fetcher(synthetic_universe()))
    return run_dir, summary


class TestRunnerArtifacts:
    def test_artifacts_written(self, portfolio_run):
        run_dir, summary = portfolio_run
        csv_dir = run_dir / "analyzer_csvs" / "VIXY-SVXY-SGOV"
        stem = "VIX_eVRP_Dual_SGOV_funded"
        for f in (f"{stem}.csv", f"{stem}_equity.csv", f"{stem}.portfolio.json"):
            assert (csv_dir / f).is_file(), f
        art = run_dir / "portfolio_runs" / "VIXY-SVXY-SGOV" / stem
        for f in ("ledger.csv", "fills.csv", "signals.csv", "daily_returns.csv", "annual_returns.csv",
                  "settlement_calendar.csv", "metrics.json"):
            assert (art / f).is_file(), f
        assert (run_dir / "overall_portfolio_summary.csv").is_file()
        verdict = json.loads((run_dir / "llm_verdict.json").read_text())
        bench = verdict["strategies"][0]["benchmarks"]
        assert set(bench) == {"SPY", "SGOV"}

    def test_validation_and_periods(self, portfolio_run):
        run_dir, summary = portfolio_run
        v = summary["validation"]
        assert not v["cash_or_holdings_negative"] and v["min_cash"] >= 0 and v["min_shares"] >= 0
        assert summary["periods"]["Full period"]["Strategy"]["start"] == "2020-07-01"
        assert set(summary["periods"]["Full period"]) == {
            "Strategy", "Strategy (gfv_aware settlement)", "Strategy (immediate settlement)",
            "SGOV (cash sleeve)", "SPY"}
        equity = pd.read_csv(run_dir / "analyzer_csvs" / "VIXY-SVXY-SGOV" /
                             "VIX_eVRP_Dual_SGOV_funded_equity.csv", index_col=0)
        assert equity["Equity"].iloc[-1] == pytest.approx(summary["final_nav"])
        assert summary["activity"]["rebalance_sessions"] > 1

    def test_missing_session_refused(self):
        from helpers.target_weight_runner import PortfolioDataError, run_target_weight_backtest
        uni = synthetic_universe()
        uni["SVXY"] = uni["SVXY"].drop(uni["SVXY"].index[300])
        with pytest.raises(PortfolioDataError, match="SVXY is missing 1 session"):
            run_target_weight_backtest(_config(), "/nonexistent", "x", _fetcher(uni))

    def test_start_before_inception_refused(self):
        from helpers.target_weight_runner import PortfolioDataError, run_target_weight_backtest
        uni = synthetic_universe()
        uni["VIXY"] = uni["VIXY"].loc["2020-09-01":]
        with pytest.raises(PortfolioDataError, match="VIXY starts"):
            run_target_weight_backtest(_config(), "/nonexistent", "x", _fetcher(uni))

    def test_unknown_strategy(self):
        from helpers.target_weight_runner import resolve_strategy
        with pytest.raises(KeyError, match="not a registered target-weight strategy"):
            resolve_strategy({"portfolio_strategy": "nope"})


def _pdf_pages(path):
    data = open(path, "rb").read()
    return data.count(b"/Type /Page\n") + data.count(b"/Type /Page ") + data.count(b"/Type /Page>>")


class TestReport:
    def test_report_all_dispatches_to_portfolio_tearsheet(self, portfolio_run, monkeypatch):
        import report
        run_dir, summary = portfolio_run
        monkeypatch.setattr(sys, "argv", ["report.py", "--all", str(run_dir)])
        report.main()
        out = run_dir / "detailed_reports" / "VIXY-SVXY-SGOV" / "VIX_eVRP_Dual_SGOV_funded"
        pdf = out / "VIX_eVRP_Dual_SGOV_funded.pdf"
        md = out / "VIX_eVRP_Dual_SGOV_funded.md"
        assert pdf.is_file() and pdf.stat().st_size > 20_000
        assert open(pdf, "rb").read(5) == b"%PDF-"
        text = md.read_text()
        assert "portfolio-NAV based" in text and "not any single ticker" in text
        assert "SGOV (cash sleeve)" in text and "| SPY |" in text
        assert "Transaction costs" in text and "Unfilled target days" in text
        for img in ("portfolio_nav.png", "drawdown.png", "holdings.png", "exposure.png", "signals.png"):
            assert (out / "images" / img).is_file()
        # The trade analyzer was not used: no MC / R-multiple sections.
        assert "Monte Carlo" not in text.split("## Assumptions")[0]

    def test_single_file_mode(self, portfolio_run, monkeypatch, tmp_path):
        import report
        run_dir, _ = portfolio_run
        csv = run_dir / "analyzer_csvs" / "VIXY-SVXY-SGOV" / "VIX_eVRP_Dual_SGOV_funded.csv"
        monkeypatch.setattr(sys, "argv", ["report.py", str(csv), "--output-dir", str(tmp_path)])
        report.main()
        assert (tmp_path / "VIX_eVRP_Dual_SGOV_funded" / "VIX_eVRP_Dual_SGOV_funded.pdf").is_file()

    def test_plain_trade_csv_not_dispatched(self, tmp_path):
        from trade_analyzer.portfolio_report import is_portfolio_csv
        f = tmp_path / "x.csv"
        f.write_text("a\n1\n")
        assert not is_portfolio_csv(f)


@pytest.mark.slow
def test_main_cli_end_to_end(tmp_path):
    """python main.py --portfolio-strategy ... with the parquet provider, then report.py --all."""
    uni = synthetic_universe()
    names = {"I:VIX": "VIX", "I:VIX3M": "VIX3M"}
    for sym, df in uni.items():
        df.index.name = "Datetime"
        df.to_parquet(tmp_path / f"{names.get(sym, sym)}.parquet")
    name = f"pytest487-{os.getpid()}"
    cmd = [sys.executable, "main.py", "--provider", "parquet", "--parquet-dir", str(tmp_path),
           "--start", "2020-07-01", "--end", "2021-07-30",
           "--portfolio-strategy", "VIX eVRP Dual (SGOV funded)", "--name", name]
    res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    assert res.returncode == 0, res.stderr[-2000:]
    runs = os.path.join(PROJECT_ROOT, "output", "runs")
    run_dir = [os.path.join(runs, d) for d in os.listdir(runs) if d.startswith(name)][0]
    try:
        rep = subprocess.run([sys.executable, "report.py", "--all", run_dir], cwd=PROJECT_ROOT,
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
        assert rep.returncode == 0, rep.stderr[-2000:]
        assert "Portfolio tearsheet" in rep.stdout
    finally:
        import shutil
        shutil.rmtree(run_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Adversarial-review regressions (#487)
# ---------------------------------------------------------------------------

class TestReviewRegressions:
    def test_exposure_must_cover_every_risk_symbol(self):
        p = _flat()
        tw = pd.DataFrame({"VIXY": 0.0, "SVXY": 0.4}, index=p.index)
        with pytest.raises(ValueError, match="non-zero coefficient"):
            simulate_target_weights(p, p, tw, RISK, CASH, exposure={"VIXY": 1.0})

    def test_exposure_mode_rejects_multi_product_rows(self):
        p = _flat()
        tw = pd.DataFrame({"VIXY": 0.1, "SVXY": 0.2}, index=p.index)
        with pytest.raises(ValueError, match="at most one risk product"):
            _sim(p, p, tw)

    def test_three_products_weight_band_moves_between_same_sign_products(self):
        dates = pd.bdate_range("2020-01-06", periods=6)
        syms = ["A", "B", "C"]
        p = pd.DataFrame(100.0, index=dates, columns=syms + [CASH])
        tw = pd.DataFrame({"A": 0.5, "B": 0.0, "C": 0.1}, index=dates)
        tw.iloc[2:, :2] = [0.3, 0.2]
        r = simulate_target_weights(p, p, tw, syms, CASH, exposure=None, settlement=twp.IMMEDIATE)
        last = r.ledger.iloc[-1]
        assert last["A_weight"] == pytest.approx(0.3)
        assert last["B_weight"] == pytest.approx(0.2)
        assert last["C_weight"] == pytest.approx(0.1)

    def test_zero_lag_settlement_rejected(self):
        with pytest.raises(ValueError, match=">= 1"):
            settlement_dates(pd.bdate_range("2024-01-02", periods=3), rules=(("1900-01-01", 0),))

    def test_tz_aware_index_rejected(self):
        p = _flat()
        p.index = p.index.tz_localize("UTC")
        with pytest.raises(ValueError, match="tz-naive"):
            _sim(p, p, _targets(p.index, 0.0))

    def _refused(self, uni, match, **cfg):
        from helpers.target_weight_runner import PortfolioDataError, run_target_weight_backtest
        with pytest.raises((PortfolioDataError, ValueError), match=match):
            run_target_weight_backtest(_config(**cfg), "/nonexistent", "x", _fetcher(uni))

    def test_short_cash_sleeve_history_refused(self):
        uni = synthetic_universe()
        uni["SGOV"] = uni["SGOV"].loc["2020-09-01":]
        self._refused(uni, "SGOV starts")

    def test_cash_sleeve_ending_early_refused(self):
        uni = synthetic_universe()
        uni["SGOV"] = uni["SGOV"].loc[:"2021-03-31"]
        self._refused(uni, "SGOV ends")

    def test_signal_input_late_start_refused(self):
        uni = synthetic_universe()
        uni["I:VIX"] = uni["I:VIX"].loc["2021-02-01":]
        self._refused(uni, "signal input 'vix' starts")

    def test_global_gap_refused(self):
        uni = synthetic_universe()
        date = pd.Timestamp("2020-09-01")
        self._refused({s: df.drop(date) for s, df in uni.items()}, "missing 1 session")

    def test_invalid_index_refused_instead_of_going_to_cash(self):
        uni = synthetic_universe()
        uni["I:VIX3M"].loc["2020-09-01", "Close"] = 0
        self._refused(uni, "no target")

    def test_short_spy_warmup_refused(self):
        uni = synthetic_universe()
        uni["SPY"] = uni["SPY"].loc["2020-06-30":]
        self._refused(uni, "no target")

    def test_signal_input_gap_refused(self):
        uni = synthetic_universe()
        uni["I:VIX3M"] = uni["I:VIX3M"].drop(uni["I:VIX3M"].index[250])
        self._refused(uni, "signal input 'vix3m' is missing 1 session")

    def test_intraday_timeframe_refused(self):
        self._refused(synthetic_universe(), "daily bars only", timeframe="H")

    def test_benchmark_can_be_disabled(self, tmp_path):
        from helpers.target_weight_runner import run_target_weight_backtest
        _ensure_plugin_registered()
        summary = run_target_weight_backtest(_config(portfolio_benchmark_ticker=None), str(tmp_path),
                                             "nobench", _fetcher(synthetic_universe()))
        assert "SPY" not in summary["periods"]["Full period"]

    def test_signal_plot_handles_many_states(self):
        from trade_analyzer.portfolio_report import plot_signals
        idx = pd.bdate_range("2024-01-01", periods=12)
        sig = pd.DataFrame({"x": np.arange(12.0), "state": [f"s{i % 7}" for i in range(12)]}, index=idx)
        fig = plot_signals(sig, idx, [])
        import matplotlib.pyplot as plt
        plt.close(fig)

    def test_report_all_mixed_run_dispatches_each_csv(self, portfolio_run, monkeypatch, tmp_path):
        import shutil
        import report
        run_dir, _ = portfolio_run
        mixed = tmp_path / "run"
        shutil.copytree(run_dir, mixed)
        normal = mixed / "analyzer_csvs" / "Plain" / "Some_Strategy.csv"
        normal.parent.mkdir(parents=True)
        normal.write_text("Date,Ex. date,Profit\n2021-01-04,2021-01-05,1\n")
        calls = {"trade": [], "portfolio": []}
        monkeypatch.setattr(report, "generate_trade_report",
                            lambda df, out, name, cfg: calls["trade"].append(name))
        monkeypatch.setattr(report, "generate_portfolio_report",
                            lambda csv, out, name: calls["portfolio"].append(name))
        monkeypatch.setattr(sys, "argv", ["report.py", "--all", str(mixed)])
        report.main()
        assert calls == {"trade": ["Some_Strategy"], "portfolio": ["VIX_eVRP_Dual_SGOV_funded"]}


# ---------------------------------------------------------------------------
# Independent QA regressions (PR #489)
# ---------------------------------------------------------------------------

class TestQaEngineInputs:
    """Costs, band and capital are validated instead of silently accepted."""

    def test_negative_cost_rejected(self):
        p = _flat()
        with pytest.raises(ValueError, match="cost_bps"):
            _sim(p, p, _targets(p.index, -0.2), cost_bps={"VIXY": 5, "SVXY": -5, "SGOV": 1})

    def test_cost_key_that_is_not_a_traded_symbol_rejected(self):
        p = _flat()
        with pytest.raises(ValueError, match="svxy"):
            _sim(p, p, _targets(p.index, -0.2), cost_bps={"svxy": 20})

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), 10000.0])
    def test_non_finite_or_total_cost_rejected(self, bad):
        p = _flat()
        with pytest.raises(ValueError, match="cost_bps"):
            _sim(p, p, _targets(p.index, -0.2), cost_bps={"SGOV": bad})

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.01])
    def test_invalid_band_rejected(self, bad):
        p = _flat()
        with pytest.raises(ValueError, match="band"):
            _sim(p, p, _targets(p.index, -0.2), band=bad)

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0.0])
    def test_invalid_capital_rejected(self, bad):
        p = _flat()
        with pytest.raises(ValueError, match="initial_capital"):
            _sim(p, p, _targets(p.index, -0.2), initial_capital=bad)

    def _runner_refuses(self, match, **cfg):
        from helpers.target_weight_runner import PortfolioConfigError, run_target_weight_backtest
        with pytest.raises(PortfolioConfigError, match=match):
            run_target_weight_backtest(_config(**cfg), "/nonexistent", "x", _fetcher(synthetic_universe()))

    def test_runner_refuses_mistyped_cost_override(self):
        # Lower-case keys used to be merged, ignored, and the run completed at baseline costs.
        self._runner_refuses("vixy", portfolio_cost_bps={"vixy": 20, "svxy": 20, "sgov": 5})

    def test_runner_refuses_negative_cost_override(self):
        self._runner_refuses("portfolio_cost_bps", portfolio_cost_bps={"VIXY": -500})

    def test_runner_refuses_non_finite_band(self):
        self._runner_refuses("portfolio_rebalance_band", portfolio_rebalance_band=float("nan"))

    def test_runner_refuses_malformed_structured_keys(self):
        self._runner_refuses("portfolio_symbol_map", portfolio_symbol_map='{"vix":"VIX"}')
        self._runner_refuses("portfolio_settlement_rules", portfolio_settlement_rules=[["2024-05-28"]])

    def test_valid_stress_override_still_runs(self, tmp_path):
        from helpers.target_weight_runner import run_target_weight_backtest
        s = run_target_weight_backtest(_config(portfolio_cost_bps={"VIXY": 20, "SVXY": 20, "SGOV": 5}),
                                       str(tmp_path), "stress", _fetcher(synthetic_universe()))
        assert s["cost_bps"] == {"VIXY": 20, "SVXY": 20, "SGOV": 5}


class TestQaDustFills:
    def test_no_dust_purchases_in_fills_ledger(self):
        rng = np.random.default_rng(0)
        n = 600
        d = pd.bdate_range("2021-01-04", periods=n)
        o = pd.DataFrame({s: 50 * np.exp(np.cumsum(rng.normal(0, v, n)))
                          for s, v in (("VIXY", .05), ("SVXY", .03), ("SGOV", .0005))}, index=d)
        c = o * np.exp(rng.normal(0, .01, (n, 3)))
        e = rng.choice([-0.2, -0.1, 0, 0.2], size=n)
        capital = 1e5
        r = _sim(o, c, _targets(d, e), settlement=twp.IMMEDIATE, initial_capital=capital)
        # Sales and cash parking already skip sub-threshold amounts; purchases must too.
        assert (r.fills["Notional"] > 1e-14 * capital).all()
        signed = r.fills.assign(q=np.where(r.fills["Side"] == "BUY", r.fills["Shares"], -r.fills["Shares"]))
        for s in r.symbols:
            cum = signed[signed["Symbol"] == s].groupby("Date")["q"].sum().reindex(d, fill_value=0).cumsum()
            np.testing.assert_allclose(cum, r.ledger[f"{s}_shares"], atol=1e-9)


class TestQaReport:
    def _summary(self, portfolio_run, **over):
        import copy
        s = copy.deepcopy(portfolio_run[1])
        s.update(over)
        return s

    def test_band_is_not_rounded_to_whole_percent(self, portfolio_run):
        from trade_analyzer import portfolio_report as pr
        text = " ".join(pr.notes(self._summary(portfolio_run, band=0.025)))
        assert "2.5 pp" in text and "band 2%" not in text
        assert "0.5 pp" in " ".join(pr.notes(self._summary(portfolio_run, band=0.005)))
        ledger = pd.read_csv(portfolio_run[0] / "portfolio_runs" / "VIXY-SVXY-SGOV" /
                             "VIX_eVRP_Dual_SGOV_funded" / "ledger.csv", index_col=0, parse_dates=True)
        ledger["target_unfilled_at_open"] = True
        fig = pr.plot_exposure(ledger, 0.025)
        labels = [t.get_text() for t in fig.axes[0].get_legend().get_texts()]
        import matplotlib.pyplot as plt
        plt.close(fig)
        assert any("2.5 pp" in x for x in labels)

    def test_cash_sleeve_has_no_sharpe_against_itself(self, portfolio_run):
        from trade_analyzer import portfolio_report as pr
        table = pr.period_table(portfolio_run[1])
        own = table[table["Series"] == "SGOV (cash sleeve)"]["Sharpe vs SGOV"]
        assert len(own) and (own == "—").all()
        strat = table[table["Series"] == "Strategy"]["Sharpe vs SGOV"]
        assert (strat != "—").all()

    def test_report_without_benchmark_never_prints_none(self, tmp_path, monkeypatch):
        import report
        from helpers.target_weight_runner import run_target_weight_backtest
        run_target_weight_backtest(_config(portfolio_benchmark_ticker=None), str(tmp_path), "nobench",
                                   _fetcher(synthetic_universe()))
        monkeypatch.setattr(sys, "argv", ["report.py", "--all", str(tmp_path)])
        report.main()
        out = tmp_path / "detailed_reports" / "VIXY-SVXY-SGOV" / "VIX_eVRP_Dual_SGOV_funded"
        text = (out / "VIX_eVRP_Dual_SGOV_funded.md").read_text()
        assert "Benchmark None" not in text and "None N/A" not in text
        assert "No buy-and-hold benchmark is configured" in text
        from trade_analyzer import portfolio_report as pr
        art = pr.load_artifacts(tmp_path / "analyzer_csvs" / "VIXY-SVXY-SGOV" / "VIX_eVRP_Dual_SGOV_funded.csv")
        assert all("None" not in sub for _l, _v, sub, _p in pr.kpi_tiles(art["summary"], art["fills"]))

    def test_immediate_primary_is_flagged_non_deployable(self, tmp_path, monkeypatch):
        import report
        from helpers.target_weight_runner import run_target_weight_backtest
        run_target_weight_backtest(_config(portfolio_settlement="immediate"), str(tmp_path), "imm",
                                   _fetcher(synthetic_universe()))
        monkeypatch.setattr(sys, "argv", ["report.py", "--all", str(tmp_path)])
        report.main()
        out = tmp_path / "detailed_reports" / "VIXY-SVXY-SGOV" / "VIX_eVRP_Dual_SGOV_funded"
        text = (out / "VIX_eVRP_Dual_SGOV_funded.md").read_text()
        head = text.split("## Performance by period")[0]
        assert "NON-DEPLOYABLE" in head
        assert "headline: immediate" in text
        assert "reused at the same open" in text

    def test_settled_primary_keeps_settled_cash_statement(self, portfolio_run):
        from trade_analyzer import portfolio_report as pr
        text = " ".join(pr.notes(portfolio_run[1]))
        assert "headline: settled_only" in text and "only settled cash buys" in text
        assert "NON-DEPLOYABLE" not in text

    def test_activity_separates_rule_fired_from_traded_sessions(self, portfolio_run):
        run_dir, summary = portfolio_run
        act = summary["activity"]
        fills = pd.read_csv(run_dir / "portfolio_runs" / "VIXY-SVXY-SGOV" / "VIX_eVRP_Dual_SGOV_funded" /
                            "fills.csv", parse_dates=["Date"])
        traded = fills.loc[fills["Reason"] == "rebalance", "Date"].nunique()
        assert act["rebalance_sessions_traded"] == traded
        assert traded < act["rebalance_sessions"]  # session 0 and settlement waits fire without trading
        from trade_analyzer import portfolio_report as pr
        assert f"{traded} executed" in pr.activity_lines(summary, fills)[0]


class TestQaCli:
    def _parse(self, *sets):
        from helpers.cli_config import apply_overrides, build_parser
        args = build_parser().parse_args([x for s in sets for x in ("--set", s)])
        return apply_overrides({}, args)

    def test_structured_portfolio_keys_are_json_decoded(self):
        cfg = self._parse('portfolio_symbol_map={"vix": "$VIX", "vix3m": "$VIX3M"}',
                          'portfolio_settlement_rules=[["1900-01-01", 2], ["2024-05-28", 1]]',
                          'portfolio_cost_bps={"VIXY": 20, "SVXY": 20, "SGOV": 5}',
                          "portfolio_rebalance_band=0.03")
        assert cfg["portfolio_symbol_map"] == {"vix": "$VIX", "vix3m": "$VIX3M"}
        assert cfg["portfolio_settlement_rules"] == [["1900-01-01", 2], ["2024-05-28", 1]]
        assert cfg["portfolio_cost_bps"] == {"VIXY": 20, "SVXY": 20, "SGOV": 5}
        assert cfg["portfolio_rebalance_band"] == 0.03

    @pytest.mark.parametrize("item", ["portfolio_cost_bps={VIXY:20}", "portfolio_cost_bps=[1,2]",
                                      "portfolio_symbol_map=VIX", 'portfolio_settlement_rules={"a":1}'])
    def test_malformed_structured_value_is_a_clear_error(self, item):
        from helpers.cli_config import OverrideError
        with pytest.raises(OverrideError, match=item.split("=")[0]):
            self._parse(item)

    def test_expected_refusal_exits_cleanly_without_traceback(self, tmp_path):
        """A data refusal is reported as [ERROR] + exit 1, like an unknown strategy name."""
        name = f"pytest489-{os.getpid()}"
        cmd = [sys.executable, "main.py", "--provider", "parquet", "--parquet-dir", str(tmp_path),
               "--start", "2020-07-01", "--end", "2021-07-30",
               "--portfolio-strategy", PLUGIN, "--name", name]
        res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=120)
        runs = os.path.join(PROJECT_ROOT, "output", "runs")
        import shutil
        for d in os.listdir(runs):
            if d.startswith(name):
                shutil.rmtree(os.path.join(runs, d), ignore_errors=True)
        assert res.returncode == 1
        assert "Traceback" not in res.stderr and "Traceback" not in res.stdout
        assert "[ERROR]" in res.stdout + res.stderr and "No data for" in res.stdout + res.stderr

    def test_dry_run_validates_portfolio_settings(self, tmp_path):
        name = f"pytest489dry-{os.getpid()}"
        cmd = [sys.executable, "main.py", "--provider", "parquet", "--parquet-dir", str(tmp_path),
               "--start", "2020-07-01", "--end", "2021-07-30", "--dry-run",
               "--portfolio-strategy", PLUGIN, "--name", name,
               "--set", 'portfolio_cost_bps={"vixy": 20}']
        res = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=120)
        runs = os.path.join(PROJECT_ROOT, "output", "runs")
        import shutil
        for d in os.listdir(runs):
            if d.startswith(name):
                shutil.rmtree(os.path.join(runs, d), ignore_errors=True)
        assert res.returncode == 1
        assert "Traceback" not in res.stderr + res.stdout
        assert "[ERROR]" in res.stdout and "vixy" in res.stdout


# ---------------------------------------------------------------------------
# PR #489 review (Shardul, 2026-11-24)
# ---------------------------------------------------------------------------

def _exit_market(seed, n=40):
    """The review's repro: hold 40% SVXY for 10 sessions, then a zero target."""
    rng = np.random.default_rng(seed)
    d = pd.bdate_range("2021-01-04", periods=n)
    cl = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, [0.05, 0.05, 0.0005], (n, 3)), 0)),
                      index=d, columns=["VIXY", "SVXY", "SGOV"])
    op = cl.shift(1).fillna(cl.iloc[0]) * np.exp(rng.normal(0, 0.01, (n, 3)))
    w = pd.DataFrame(0.0, index=d, columns=RISK)
    w.iloc[:10, 1] = 0.4
    return op, cl, w


class TestReviewResidualShares:
    """#1: a full exit must leave exactly zero shares, or the band is off for good."""

    @pytest.mark.parametrize("mode", [twp.SETTLED_ONLY, twp.GFV_AWARE, twp.IMMEDIATE])
    def test_full_exit_leaves_exactly_zero_shares(self, mode):
        # Seed 74 left 4.3e-19 SVXY shares and rebalanced on 27/27 later sessions.
        for seed in (74, *range(60)):
            op, cl, w = _exit_market(seed)
            led = _sim(op, cl, w, band=0.02, settlement=mode).ledger
            after = led.iloc[16:]  # exited and settled by then in every mode
            assert (after["SVXY_shares"] == 0.0).all(), seed
            # Target unchanged (all cash sleeve) and within band: no rebalance.
            assert not after["rebalanced"].any(), seed

    def test_dust_holding_with_zero_target_is_cleared(self):
        p = _flat(8)
        w = _targets(p.index, 0.0)
        r = _sim(p, p, w, cost_bps={})
        # Inject dust directly: a 1e-19 share remainder must not keep "product_exit" firing.
        led = _sim(p, p, w.assign(SVXY=[1e-20] + [0.0] * 7), cost_bps={}).ledger
        assert (led["SVXY_shares"].iloc[2:] == 0).all()
        assert not led["rebalanced"].iloc[2:].any()
        assert r.ledger["nav"].iloc[-1] == pytest.approx(1.0)


def _replay_gfv_audit(fills: pd.DataFrame, lots: pd.DataFrame, risk: list):
    """Independent check of the good-faith rule from the fills and restricted lots.

    No SELL may take shares that are still restricted on its date, and every
    lot is backed by a BUY of at least that many shares on the same date.
    """
    bought = fills[fills["Side"] == "BUY"].groupby(["Date", "Symbol"])["Shares"].sum()
    for (d, s), sh in lots.groupby(["Date", "Symbol"])["Shares"].sum().items():
        assert sh <= bought.get((d, s), 0.0) * (1 + 1e-9) + 1e-12, (d, s)
    held = {s: 0.0 for s in risk}
    for f in fills.itertuples(index=False):
        if f.Symbol not in risk:
            continue
        if f.Side == "BUY":
            held[f.Symbol] += f.Shares
        else:
            mine = lots[(lots["Symbol"] == f.Symbol) & (lots["Date"] < f.Date) & (lots["FreeDate"] > f.Date)]
            assert f.Shares <= held[f.Symbol] - mine["Shares"].sum() + 1e-9, (f.Date, f.Symbol)
            held[f.Symbol] -= f.Shares


class TestReviewGfvAware:
    """#3: a Reg T cash account may buy with unsettled proceeds, without free-riding."""

    def test_unsettled_proceeds_buy_risk_but_not_cash_sleeve(self):
        p = _flat()
        r = _sim(p, p, _targets(p.index, -0.2), cost_bps={}, settlement=twp.GFV_AWARE)
        led = r.ledger
        # Unlike settled_only (which waits two sessions), the target is reached on day 1.
        assert led["SVXY_weight"].iloc[1] == pytest.approx(0.4)
        assert not led["target_unfilled_at_open"].iloc[1]
        buy = r.fills[(r.fills["Symbol"] == "SVXY") & (r.fills["Side"] == "BUY")].iloc[0]
        assert buy["UnsettledFunding"] == pytest.approx(0.4)
        assert buy["RestrictedUntil"] == r.settlement_map[p.index[1]]
        # The SGOV sale's receivable was spent, so nothing is left unsettled.
        assert led["unsettled"].iloc[1] == pytest.approx(0.0, abs=1e-12)

    def test_restricted_shares_are_not_sold_before_settlement(self):
        p = _flat(8)
        t = pd.Series(0.0, index=p.index)
        t.iloc[0] = -0.2  # buy SVXY on day 1 with unsettled SGOV proceeds
        r = _sim(p, p, _targets(p.index, t), cost_bps={}, settlement=twp.GFV_AWARE)
        led = r.ledger
        settles = r.settlement_map[p.index[1]]  # T+2 -> day 3
        # Target is zero from day 2, but the shares are locked until they free up.
        assert led.loc[:settles - pd.Timedelta(days=1), "SVXY_shares"].iloc[1:].gt(0).all()
        assert led["target_unfilled_at_open"].iloc[2]
        sells = r.fills[(r.fills["Symbol"] == "SVXY") & (r.fills["Side"] == "SELL")]
        assert (sells["Date"] >= settles).all() and len(sells) == 1
        assert led["SVXY_shares"].iloc[-1] == 0.0

    @pytest.mark.parametrize("seed", range(6))
    def test_random_paths_obey_good_faith_rule_and_fund(self, seed):
        opens, closes, rng = _random_market(seed)
        exposure = rng.choice([-0.2, -0.1, 0.0, 0.2], size=len(opens))
        r = _sim(opens, closes, _targets(opens.index, exposure), settlement=twp.GFV_AWARE,
                 initial_capital=250_000.0)
        led = r.ledger
        assert (led["cash"] >= 0).all() and (led["unsettled"] >= -1e-9).all()
        value = sum(led[f"{s}_value"] for s in r.symbols) + led["cash"] + led["unsettled"]
        np.testing.assert_allclose(value, led["nav"], rtol=1e-12)
        assert len(r.restrictions) > 0  # the path does exercise unsettled-funded buys
        _replay_gfv_audit(r.fills, r.restrictions, RISK)
        # Cash-sleeve purchases never use unsettled money.
        assert (r.fills.loc[r.fills["Symbol"] == CASH, "UnsettledFunding"].fillna(0) == 0).all()

    def test_audit_catches_a_free_ride(self):
        # The audit is not hollow: a sale of restricted shares must fail it.
        d = pd.Timestamp("2021-01-05")
        fills = pd.DataFrame([
            {"Date": d, "Symbol": "SVXY", "Side": "BUY", "Shares": 10.0},
            {"Date": d + pd.Timedelta(days=1), "Symbol": "SVXY", "Side": "SELL", "Shares": 10.0},
        ])
        lots = pd.DataFrame([{"Date": d, "Symbol": "SVXY", "Shares": 4.0, "FreeDate": d + pd.Timedelta(days=2)}])
        with pytest.raises(AssertionError):
            _replay_gfv_audit(fills, lots, RISK)
        _replay_gfv_audit(fills.assign(Shares=[10.0, 6.0]), lots, RISK)  # the free part may go

    def test_gfv_without_receivables_equals_settled_only(self):
        # With no sales there are no receivables, so the two modes must coincide.
        p = _flat()
        a = _sim(p, p, _targets(p.index, 0.0), settlement=twp.GFV_AWARE).ledger
        b = _sim(p, p, _targets(p.index, 0.0), settlement=twp.SETTLED_ONLY).ledger
        pd.testing.assert_frame_equal(a, b)

    def test_runner_reports_all_three_settlement_series(self, portfolio_run):
        run_dir, summary = portfolio_run
        assert summary["settlement_modes"] == ["settled_only", "gfv_aware", "immediate"]
        art = run_dir / "portfolio_runs" / "VIXY-SVXY-SGOV" / "VIX_eVRP_Dual_SGOV_funded"
        for f in ("comparison_ledger.csv", "comparison_ledger_gfv_aware.csv",
                  "comparison_ledger_immediate.csv"):
            assert (art / f).is_file(), f
        # comparison_ledger.csv keeps its meaning (the parity script reads it): immediate.
        a = pd.read_csv(art / "comparison_ledger.csv")
        b = pd.read_csv(art / "comparison_ledger_immediate.csv")
        pd.testing.assert_frame_equal(a, b)

    def test_gfv_can_be_the_headline(self, tmp_path):
        from helpers.target_weight_runner import run_target_weight_backtest
        s = run_target_weight_backtest(_config(portfolio_settlement="gfv_aware"), str(tmp_path), "gfv",
                                       _fetcher(synthetic_universe()))
        assert s["settlement"] == "gfv_aware"
        assert "Strategy (settled_only settlement)" in s["periods"]["Full period"]

    def test_report_explains_settled_only_is_stricter_than_reg_t(self, portfolio_run):
        from trade_analyzer import portfolio_report as pr
        text = " ".join(pr.notes(portfolio_run[1]))
        assert "Stricter than Regulation T" in text and "good-faith" in text


class TestReviewPriceBasis:
    """#2: Polygon adjusted=true is split-only; funded baskets need total return."""

    @pytest.mark.parametrize("provider,adj,basis", [
        ("polygon", "total_return", "price_only"),
        ("norgate", "total_return", "total_return"),
        ("yahoo", "total_return", "total_return"),
        ("yahoo", "none", "price_only"),
        ("parquet", "total_return", "as_supplied"),
        ("csv", "total_return", "as_supplied"),
    ])
    def test_price_basis_by_provider(self, provider, adj, basis):
        from helpers.target_weight_runner import price_basis
        assert price_basis({"data_provider": provider, "price_adjustment": adj})[0] == basis

    def test_polygon_refused_by_default(self):
        from helpers.target_weight_runner import PortfolioConfigError, resolve_settings, resolve_strategy
        cfg = _config(data_provider="polygon", price_adjustment="total_return")
        _, entry = resolve_strategy(cfg)
        with pytest.raises(PortfolioConfigError, match="split-adjusted only"):
            resolve_settings(entry, cfg)

    def test_price_only_opt_in_is_labelled(self, tmp_path):
        from helpers.target_weight_runner import run_target_weight_backtest
        from trade_analyzer import portfolio_report as pr
        s = run_target_weight_backtest(_config(data_provider="polygon", portfolio_allow_price_only=True),
                                       str(tmp_path), "po", _fetcher(synthetic_universe()))
        assert s["validation"]["price_basis"] == "price_only"
        assert "total-return" not in s["validation"]["distribution_treatment"].replace("not total-return", "")
        assert any(line.startswith("PRICE-ONLY INPUTS") for line in pr.flag_lines(s))

    def test_total_return_text_never_hardcoded(self, portfolio_run):
        # The synthetic provider is unverifiable: the run must not claim total return.
        v = portfolio_run[1]["validation"]
        assert v["price_basis"] == "as_supplied"
        assert "cannot verify" in v["distribution_treatment"]


class TestReviewSymbolMapAndValidity:
    """#4: SVXY's -0.5 coefficient is dated; substitutions are labelled."""

    def test_start_before_svxy_deleverage_refused(self):
        from helpers.target_weight_runner import PortfolioConfigError, resolve_settings, resolve_strategy
        cfg = _config(start_date="2017-06-01")
        _, entry = resolve_strategy(cfg)
        with pytest.raises(PortfolioConfigError, match="2018-02-28"):
            resolve_settings(entry, cfg)

    def test_substituted_cash_sleeve_is_labelled(self, tmp_path):
        from helpers.target_weight_runner import run_target_weight_backtest
        from trade_analyzer import portfolio_report as pr
        uni = synthetic_universe()
        uni["BIL"] = uni["SGOV"]
        s = run_target_weight_backtest(_config(portfolio_symbol_map={"SGOV": "BIL"}), str(tmp_path), "sub",
                                       _fetcher(uni))
        assert s["substitutions"] == {"SGOV": "BIL"}
        assert any("SGOV is run on BIL" in line for line in pr.flag_lines(s))

    def test_provider_spelling_is_not_a_substitution(self):
        from helpers.target_weight_runner import resolve_strategy, substitutions
        cfg = _config(portfolio_symbol_map={"vix": "$VIX", "vix3m": "^VIX3M"})
        _, entry = resolve_strategy(cfg)
        assert substitutions(entry, cfg) == {}


class TestReviewNits:
    def test_sharpe_uses_configured_risk_free_rate(self, tmp_path):
        from helpers.target_weight_runner import run_target_weight_backtest
        s = run_target_weight_backtest(_config(risk_free_rate=0.05), str(tmp_path), "rf",
                                       _fetcher(synthetic_universe()))
        m = s["periods"]["Full period"]["Strategy"]
        assert s["risk_free_rate"] == 0.05 and m["risk_free_rate"] == 0.05
        assert m["sharpe_rf"] == pytest.approx(m["sharpe_rf2"] - 0.03 / m["volatility"])
        summary_csv = pd.read_csv(tmp_path / "overall_portfolio_summary.csv")
        assert "Sharpe (rf=5.00%)" in summary_csv.columns

    def test_shared_ticker_fetched_once(self):
        from helpers.target_weight_runner import fetch_inputs, resolve_strategy
        calls = []
        base = _fetcher(synthetic_universe())

        def counting(symbol, *a):
            calls.append(symbol)
            return base(symbol, *a)
        cfg = _config()
        _, entry = resolve_strategy(cfg)
        data, _ = fetch_inputs(entry, cfg, counting)
        assert calls.count("SPY") == 1
        assert data["spy"] is not data["SPY"] and data["spy"].equals(data["SPY"])

    def test_staging_manifest_has_no_absolute_path_and_accepts_crlf(self, tmp_path):
        import hashlib
        sys.path.insert(0, os.path.join(PROJECT_ROOT, "scripts"))
        import vix_evrp_stage_frozen_inputs as st
        lf = b"Date,Open\n2020-01-02,1\n"
        (tmp_path / "a.csv").write_bytes(lf.replace(b"\n", b"\r\n"))  # autocrlf checkout
        (tmp_path / "SHA256SUMS").write_text(f"{hashlib.sha256(lf).hexdigest()}  a.csv\n")
        assert st.verify_checksums(tmp_path, ["a.csv"]) == {"a.csv": hashlib.sha256(lf).hexdigest()}
        (tmp_path / "a.csv").write_bytes(b"tampered\r\n")
        with pytest.raises(SystemExit, match="Checksum mismatch"):
            st.verify_checksums(tmp_path, ["a.csv"])
