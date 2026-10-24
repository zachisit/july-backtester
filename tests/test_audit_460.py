"""Cross-feature regressions found while auditing epic RC #460."""
import numpy as np
import pandas as pd
import pytest

import main
from helpers import portfolio_simulations as ps
from helpers.mc_scoring import bootstrap_mean_pvalue
from helpers.wfa_rolling import evaluate_rolling_wfa, get_fold_dates
from tests.test_short_lived_names import run_main, _FakePool, _LIVES


@pytest.fixture
def engine_config(monkeypatch):
    values = {
        "execution_time": "close", "slippage_pct": 0.0,
        "commission_per_share": 0.0, "position_sizing_method": "fixed",
        "entry_priority": "alphabetical", "volume_impact_coeff": 0.0,
        "max_pct_adv": 0.0, "max_portfolio_heat": 100.0,
        "htb_rate_annual": 0.0, "short_margin_requirement": 0.5,
        "exclude_open_positions": False, "include_delisted": True,
        "delisting_price_assumption": "zero", "end_date": "2024-06-30",
        "intrabar_resolution": False, "entry_bar_stop_check": True,
    }
    for key, value in values.items():
        monkeypatch.setitem(ps.CONFIG, key, value)


def frame(tz=None):
    idx = pd.bdate_range("2024-01-01", periods=5, tz=tz)
    return pd.DataFrame({"Open": 100.0, "High": 101.0, "Low": 99.0,
                         "Close": 100.0, "Volume": 1e6}, index=idx)


def simulate(df, signals, delisting=None, stop=None, intrabar=None, alloc=0.5):
    return ps.run_portfolio_simulation(
        {"A": df}, {"A": pd.Series(signals, index=df.index)},
        100_000.0, alloc, None, None, None, stop or {"type": "none"},
        delisting_dates={"A": delisting} if delisting else None,
        intrabar_data={"A": intrabar} if intrabar is not None else None,
    )


@pytest.mark.parametrize("side", [1, -2])
def test_delisting_accepts_provider_utc_indexes(engine_config, side):
    result = simulate(frame("UTC"), [side, 0, 0, 0, 0], "2024-01-03")
    assert result["positions_delisted"] == 1
    assert result["trade_log"][0]["ExitReason"] == "Delisting"


@pytest.mark.parametrize("side", [1, -2])
def test_delisted_symbol_cannot_be_entered_again(engine_config, side):
    result = simulate(frame(), [side, 0, side, side, 0], "2024-01-03")
    assert result["Trades"] == 1
    assert result["positions_delisted"] == 1


@pytest.mark.parametrize("side", [1, -2])
def test_delisting_safety_net_includes_exit_commission(engine_config, monkeypatch, side):
    monkeypatch.setitem(ps.CONFIG, "commission_per_share", 1.0)
    result = simulate(frame(), [side, 0, 0, 0, 0], "2024-06-03")
    assert result["portfolio_timeline"].iloc[-1] == pytest.approx(
        100_000.0 + sum(t["Profit"] for t in result["trade_log"]))


def test_delisting_after_requested_end_does_not_change_past_results(engine_config, monkeypatch):
    monkeypatch.setitem(ps.CONFIG, "end_date", "2024-01-05")
    result = simulate(frame(), [1, 0, 0, 0, 0], "2024-06-03")
    assert result["positions_delisted"] == 0
    assert result["trade_log"][0]["ExitReason"] == "End of Backtest"
    assert result["pnl_percent"] == pytest.approx(0.0)


@pytest.mark.parametrize("execution_time", ["open", "close"])
@pytest.mark.parametrize("side,allocation,delisting_close", [(1, 1., 200.), (-2, 2., 50.)])
@pytest.mark.parametrize("has_delisting_bar", [True, False])
def test_delisting_close_cannot_fund_an_earlier_open(
        engine_config, monkeypatch, execution_time, side, allocation,
        delisting_close, has_delisting_bar):
    monkeypatch.setitem(ps.CONFIG, "execution_time", execution_time)
    monkeypatch.setitem(ps.CONFIG, "delisting_price_assumption", "last_close")
    a, b = frame(), frame()
    day = a.index[3]
    a.loc[day, ["Close", "High", "Low"]] = [
        delisting_close, max(101., delisting_close + 1), min(99., delisting_close - 1)]
    if not has_delisting_bar:
        a = a.iloc[:3]
    sa = pd.Series([side] + [0] * (len(a) - 1), index=a.index)
    sb = pd.Series(0, index=b.index)
    sb.iloc[2 if execution_time == "open" else 3] = 1
    result = ps.run_portfolio_simulation(
        {"A": a, "B": b}, {"A": sa, "B": sb},
        100_000., allocation, None, None, None, {"type": "none"},
        delisting_dates={"A": day})
    a_trade, = [t for t in result["trade_log"] if t["Symbol"] == "A"]
    assert a_trade["ExitReason"] == "Delisting"
    assert a_trade["ExitPrice"] == (delisting_close if has_delisting_bar else 100.)
    b_trades = [t for t in result["trade_log"] if t["Symbol"] == "B"]
    # The delisting day's Close is available for that close, not its open.
    assert len(b_trades) == (0 if execution_time == "open" and has_delisting_bar else 1)


@pytest.mark.parametrize("side", [1, -2])
def test_delisting_trade_preserves_position_size_metadata(engine_config, side):
    df = frame()
    result = ps.run_portfolio_simulation(
        {"A": df}, {"A": pd.Series([side, 0, 0, 0, 0], index=df.index)},
        100_000., .5, None, None, None, {"type": "none"},
        size_mults={"A": pd.Series(.5, index=df.index)},
        delisting_dates={"A": df.index[2]})
    trade, = result["trade_log"]
    assert trade["Shares"] == pytest.approx(250.)
    assert trade["PosSizeMult"] == .5


@pytest.mark.parametrize("side,second_open", [(1, 90.0), (-2, 110.0)])
def test_fill_bar_stop_uses_intraday_gap_fill(engine_config, monkeypatch, side, second_open):
    monkeypatch.setitem(ps.CONFIG, "execution_time", "open")
    monkeypatch.setitem(ps.CONFIG, "intrabar_resolution", True)
    df = frame()
    df.loc[df.index[1], ["Low", "High"]] = [89.0, 111.0]
    intra = pd.DataFrame({"Open": [100.0, second_open], "High": [101.0, second_open + 1],
                          "Low": [99.0, second_open - 1]},
                         index=pd.to_datetime(["2024-01-02 09:30", "2024-01-02 09:31"]))
    result = simulate(df, [side, 0, 0, 0, 0],
                      stop={"type": "percentage", "value": 0.05}, intrabar=intra)
    assert result["trade_log"][0]["ExitPrice"] == second_open


def test_short_collateral_budget_includes_entry_commission(engine_config, monkeypatch):
    monkeypatch.setitem(ps.CONFIG, "commission_per_share", 1.0)
    result = simulate(frame(), [-2, 0, 0, 0, 0], alloc=2.0)
    trade = result["trade_log"][0]
    reserved = trade["Shares"] * trade["EntryPrice"] * 0.5
    entry_commission = trade["Shares"]
    assert reserved + entry_commission <= 100_000.0 + 1e-8


def test_rolling_wfa_counts_trades_on_final_day():
    trades = [{"ExitDate": day, "Profit": 100.0}
              for day in ["2020-06-01", "2021-06-01", "2023-01-01"] for _ in range(5)]
    result = evaluate_rolling_wfa(trades, get_fold_dates("2020-01-01", "2023-01-01", 3), 1e5)
    assert result["wfa_rolling_verdict"] == "Pass (2/2)"


def test_rolling_wfa_does_not_score_na_folds_as_failures():
    trades = [{"ExitDate": day, "Profit": 100.0}
              for day in ["2020-06-01", "2021-06-01", "2022-06-01"] for _ in range(2)]
    result = evaluate_rolling_wfa(trades, get_fold_dates("2020-01-01", "2023-01-01", 3),
                                  1e5, min_fold_trades=2)
    assert result["wfa_rolling_verdict"] == "N/A"


def test_rolling_wfa_empty_folds_returns_na():
    trade = {"ExitDate": "2024-01-01", "Profit": 100.0}
    assert evaluate_rolling_wfa([trade], [], 1e5)["wfa_rolling_verdict"] == "N/A"


def test_stop_labels_distinguish_percentage_precision_and_atr_caps():
    assert main._stop_label({"type": "percentage", "value": 0.051}) != main._stop_label(
        {"type": "percentage", "value": 0.054})
    for stop_type in ("atr", "trailing_atr"):
        assert main._stop_label({"type": stop_type, "point_cap": 10}) != main._stop_label(
            {"type": stop_type, "point_cap": 20})
    assert main._stop_label({"type": "trailing_atr", "floor": "breakeven"}) != main._stop_label(
        {"type": "trailing_atr", "floor": 90})


def test_mc_block_edge_test_preserves_serial_dependence():
    pnl = [10.0] * 550 + [-10.0] * 450
    pvalue = bootstrap_mean_pvalue(pnl, rng=np.random.default_rng(42),
                                   sampling="block", block_size=100)
    assert pvalue > 0.05


def test_dependency_warmup_keeps_benchmark_window_unchanged(run_main, monkeypatch):
    monkeypatch.setitem(_LIVES, "SPY", _LIVES["LONG"])
    calls, _, _ = run_main({"P": ["LONG"]}, comparison_tickers=[{"symbol": "SPY", "role": "both"}])
    assert next(start for symbol, start, _ in calls if symbol == "SPY") < "2021-01-01"
    initargs = _FakePool.captured["initargs"]
    spy = initargs[0]["SPY"]
    assert len(spy.loc[:"2020-12-31"]) >= 200
    window = spy.loc["2021-01-01":]
    expected = window["Close"].iloc[-1] / window["Close"].iloc[0] - 1
    assert initargs[1]["SPY"] == pytest.approx(expected)
    assert initargs[1]["SPY"] != pytest.approx(spy["Close"].iloc[-1] / spy["Close"].iloc[0] - 1)


def test_first_open_uses_warmup_signal_and_structural_stop(engine_config, monkeypatch):
    monkeypatch.setitem(ps.CONFIG, "execution_time", "open")
    monkeypatch.setitem(ps.CONFIG, "start_date", "2024-01-03")
    monkeypatch.setitem(ps.CONFIG, "min_trades_for_mc", 999)
    df = frame()
    df.iloc[0, df.columns.get_loc("Low")] = 95.0
    for key, value in {
        "portfolio_data_global": {"A": df}, "comparison_dfs_global": {},
        "dependency_map_global": {}, "benchmark_returns_global": {},
        "delisting_dates_global": None, "pit_member_masks_global": None,
        "intrabar_data_global": None,
    }.items():
        monkeypatch.setattr(main, key, value)

    def signal(df, **kwargs):
        return df.assign(Signal=(df.index == pd.Timestamp("2024-01-02")).astype(int))

    result = main.run_single_simulation(("P", "Warmup", signal, [],
        {"type": "signal_bar", "bars_back": 1}, {}, None, None, None))
    assert result.get("status") not in ("no_trades", "error")
    assert result["trade_log"][0]["EntryDate"].startswith("2024-01-03")
    assert result["trade_log"][0]["InitialRisk"] == pytest.approx(5.0)
    assert result["portfolio_timeline"].index.min() == pd.Timestamp("2024-01-03")


def worker_globals(monkeypatch):
    for key, value in {
        "portfolio_data_global": {"A": frame()}, "comparison_dfs_global": {},
        "dependency_map_global": {}, "benchmark_returns_global": {},
        "delisting_dates_global": None, "pit_member_masks_global": None,
        "intrabar_data_global": None,
    }.items():
        monkeypatch.setattr(main, key, value)


def test_worker_wfa_includes_final_intraday_loss(engine_config, monkeypatch):
    worker_globals(monkeypatch)
    monkeypatch.setitem(ps.CONFIG, "min_trades_for_mc", 999)
    trades = ([{"ExitDate": "2023-12-31", "Profit": 2000.0}] * 5
              + [{"ExitDate": "2024-01-02T16:00:00", "Profit": -6000.0}] * 5)
    curve = pd.Series([100_000, 110_000, 111_000, 80_000], index=pd.to_datetime(
        ["2023-01-01", "2023-12-31", "2024-01-01T16:00:00", "2024-01-02T16:00:00"], format="mixed"))
    monkeypatch.setattr(main, "run_portfolio_simulation", lambda *a, **k: {
        "Trades": 10, "trade_pnl_list": [t["Profit"] for t in trades], "trade_log": trades,
        "initial_capital": 1e5, "pnl_percent": -0.2, "portfolio_timeline": curve})
    result = main.run_single_simulation(("P", "WFA", lambda df, **kw: df.assign(Signal=0), [],
        {"type": "none"}, {}, "2024-01-01", "2023-01-01", "2024-01-02"))
    assert result["wfa_verdict"] == "Likely Overfitted"
    assert result["oos_pnl_pct"] == pytest.approx(80_000 / 110_000 - 1)


def test_worker_mc_edge_test_uses_effective_block_sampling(engine_config, monkeypatch):
    worker_globals(monkeypatch)
    for key, value in {"min_trades_for_mc": 5, "mc_sampling": "block", "mc_block_size": 100,
                       "random_seed": 42, "smoothness_profile": "equity"}.items():
        monkeypatch.setitem(ps.CONFIG, key, value)
    pnl = [10.0] * 550 + [-10.0] * 450
    trades = [{"ExitDate": "2024-01-02", "Profit": profit} for profit in pnl]
    monkeypatch.setattr(main, "run_portfolio_simulation", lambda *a, **k: {
        "Trades": len(pnl), "trade_pnl_list": pnl, "trade_log": trades,
        "initial_capital": 1e5, "pnl_percent": 0.01, "max_drawdown": 0.045,
        "portfolio_timeline": None})
    monkeypatch.setattr(main, "run_monte_carlo_simulation", lambda *a, **k: {
        "final_equities": np.full(10, 101_000), "max_drawdowns": np.full(10, 0.045)})
    result = main.run_single_simulation(("P", "MC", lambda df, **kw: df.assign(Signal=0), [],
        {"type": "none"}, {}, None, None, None))
    assert result["mc_sampling_effective"] == "block"
    assert "No Significant Edge" in result["mc_verdict"]
    assert result["mc_edge_pvalue"] > 0.05


def test_anchored_wfa_infers_original_is_history():
    from tests.test_wfa import _compounding_fixture
    trades, curve, capital, start, _, end = _compounding_fixture(
        0.10, 0.001, start="2000-01-01", split="2004-01-01", end="2020-01-01")
    folds = get_fold_dates(start, end, 4, anchored=True)
    inferred = evaluate_rolling_wfa(trades, folds, capital, equity_curve=curve)
    explicit = evaluate_rolling_wfa(trades, folds, capital, equity_curve=curve, actual_start=start)
    assert inferred == explicit == {"wfa_rolling_verdict": "Fail (0/4)"}


def test_pool_initializer_receives_runtime_config(run_main):
    _, _, config = run_main({"P": ["LONG"]}, random_seed=42, min_trades_for_mc=5)
    snapshot = _FakePool.captured["initargs"][7]
    assert snapshot == config
    assert snapshot is not config


def test_initializer_updates_shared_config_for_spawned_workers(monkeypatch):
    worker_globals(monkeypatch)
    monkeypatch.setitem(main.CONFIG, "random_seed", None)
    parent_config = dict(main.CONFIG, random_seed=42)
    shared_config = ps.CONFIG
    main.init_worker({}, {}, {}, {"A": frame()}, config_for_worker=parent_config)
    assert main.CONFIG is shared_config
    assert shared_config["random_seed"] == 42
