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
        assert (warm["target_exposure"].iloc[:10] == 0).all()  # needs 10 returns

    def test_missing_vix_is_cash_and_basket_mapping(self, mod):
        idx = pd.bdate_range("2024-01-01", periods=15)
        spy = pd.Series(np.linspace(100, 110, 15), index=idx)
        vix = pd.Series(30.0, index=idx).drop(idx[-1])
        out = mod.evrp_dual_signal(spy, vix, pd.Series(40.0, index=idx))
        assert out["state"].iloc[-1] == mod.STATE_CASH
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
    idx = pd.bdate_range(start, periods=n)
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
            "Strategy", "Strategy (immediate settlement)", "SGOV (cash sleeve)", "SPY"}
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
