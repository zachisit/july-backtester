"""Futures long heat must measure the actual initial stop exposure (#467)."""
import pandas as pd
import pytest

from helpers import portfolio_simulations as ps


@pytest.fixture
def settings(monkeypatch):
    values = {
        "execution_time": "close", "position_sizing_method": "fixed",
        "target_risk_per_trade": .004, "max_portfolio_heat": .005,
        "fixed_contracts_per_trade": 200, "max_pct_adv": 0.,
        "volume_impact_coeff": 0., "include_delisted": False,
        "entry_priority": "alphabetical", "exclude_open_positions": False,
        "instruments": {"default_asset_class": "equity", "overrides": {},
                        "futures_initial_margin_pct": .1,
                        "futures_commission_per_contract": 0.,
                        "futures_slippage_ticks": 0.},
    }
    for key, value in values.items():
        monkeypatch.setitem(ps.CONFIG, key, value)


def frame(price=100., volume=1_000_000.):
    idx = pd.bdate_range("2024-01-02", periods=7)
    return pd.DataFrame({"Open": price, "High": price + 1., "Low": price - 1.,
                         "Close": price, "Volume": volume, "ATR_14": 1.}, index=idx)


def run(df, stop):
    sig = pd.Series([0, 1, 0, 0, -1, 0, 0], index=df.index)
    return ps.run_portfolio_simulation(
        {"MESM6": df}, {"MESM6": sig}, 100_000., .1,
        None, None, None, stop)


@pytest.mark.parametrize("method", ["fixed", "kelly", "vol_parity", "fixed_contracts"])
@pytest.mark.parametrize("stop", [
    {"type": "percentage", "value": .05}, {"type": "points", "value": 5.},
    {"type": "atr", "multiplier": 2.},
    {"type": "trailing_atr", "stop_mult": 2.},
    {"type": "signal_bar", "bars_back": 1, "buffer": .01},
])
def test_known_stop_rejects_exposure_above_heat(settings, monkeypatch, method, stop):
    monkeypatch.setitem(ps.CONFIG, "position_sizing_method", method)
    assert run(frame(), stop) is None


def test_missing_stop_keeps_the_existing_proxy(settings):
    result = run(frame(), {"type": "none"})
    assert result is not None
    assert result["trade_log"][0]["Shares"] == 200.


def test_market_impact_cannot_push_final_stop_risk_over_heat(settings, monkeypatch):
    monkeypatch.setitem(ps.CONFIG, "position_sizing_method", "fixed_contracts")
    monkeypatch.setitem(ps.CONFIG, "fixed_contracts_per_trade", 100)
    monkeypatch.setitem(ps.CONFIG, "max_portfolio_heat", .03)
    monkeypatch.setitem(ps.CONFIG, "volume_impact_coeff", 1.)
    assert run(frame(volume=1000.), {"type": "points", "value": 5.}) is None


@pytest.mark.parametrize("price", [2500., 2500.25, 2500.5])
def test_exact_heat_budget_is_allowed_without_fraction_round_trip(settings, monkeypatch, price):
    monkeypatch.setitem(ps.CONFIG, "position_sizing_method", "fixed_contracts")
    monkeypatch.setitem(ps.CONFIG, "fixed_contracts_per_trade", 4)
    result = run(frame(price), {"type": "points", "value": 25.})
    assert result is not None, "exactly $500 of stop risk must fit a $500 cap"
    trade, = result["trade_log"]
    assert trade["Shares"] == 4.
    assert trade["InitialRisk"] == 25.


def test_later_entry_sees_the_first_positions_filled_risk(settings, monkeypatch):
    monkeypatch.setitem(ps.CONFIG, "position_sizing_method", "fixed_contracts")
    monkeypatch.setitem(ps.CONFIG, "fixed_contracts_per_trade", 4)
    monkeypatch.setitem(ps.CONFIG, "volume_impact_coeff", .5)
    data = {symbol: frame(volume=100.) for symbol in ("MESM6", "MESZ6")}
    signals = {}
    for symbol, entry in (("MESM6", 1), ("MESZ6", 2)):
        sig = pd.Series(0, index=data[symbol].index)
        sig.iloc[entry], sig.iloc[5] = 1, -1
        signals[symbol] = sig
    result = ps.run_portfolio_simulation(
        data, signals, 100_000., .1, None, None, None,
        {"type": "points", "value": 5.})
    trade, = result["trade_log"]
    assert trade["Symbol"] == "MESM6"
    assert trade["EntryPrice"] == pytest.approx(110.)
    assert trade["Shares"] * 5. * trade["InitialRisk"] == pytest.approx(300.)
