"""Futures shorts obey the same liquidity mechanics as longs (#468)."""
import numpy as np
import pandas as pd
import pytest

from helpers import portfolio_simulations as ps


@pytest.fixture
def settings(monkeypatch):
    for key, value in {
        "execution_time": "close", "entry_trigger": "edge",
        "position_sizing_method": "fixed", "max_portfolio_heat": 100.,
        "max_pct_adv": 0., "volume_impact_coeff": 0., "htb_rate_annual": 0.,
        "exclude_open_positions": False, "include_delisted": False,
        "entry_priority": "alphabetical", "entry_bar_stop_check": False,
        "instruments": {"default_asset_class": "equity", "overrides": {},
                        "futures_initial_margin_pct": .1,
                        "futures_commission_per_contract": 0.,
                        "futures_slippage_ticks": 0.},
    }.items():
        monkeypatch.setitem(ps.CONFIG, key, value)


def _run(side, volumes=None, stop=None):
    idx = pd.bdate_range("2024-01-02", periods=30)
    df = pd.DataFrame({"Open": 100., "High": 101., "Low": 99.,
                       "Close": 100., "ATR_14": 1.}, index=idx)
    if volumes is not None:
        df["Volume"] = volumes
    sig = pd.Series(0, index=idx)
    sig.iloc[21], sig.iloc[26] = side, -1
    return ps.run_portfolio_simulation(
        {"MESM6": df}, {"MESM6": sig}, 100_000., .1,
        None, None, None, stop or {"type": "none"})


@pytest.mark.parametrize("method", ["fixed", "vol_parity", "fixed_contracts"])
def test_contract_adv_cap_matches_long(settings, monkeypatch, method):
    monkeypatch.setitem(ps.CONFIG, "position_sizing_method", method)
    monkeypatch.setitem(ps.CONFIG, "fixed_contracts_per_trade", 200)
    monkeypatch.setitem(ps.CONFIG, "max_pct_adv", 5.05e-5)
    long = _run(1, 1_000_000.)["trade_log"][0]
    short = _run(-2, 1_000_000.)["trade_log"][0]
    assert long["Shares"] == short["Shares"] == 50.


def test_sub_contract_cap_declines_entry(settings, monkeypatch):
    monkeypatch.setitem(ps.CONFIG, "max_pct_adv", 5e-7)
    assert _run(-2, 1_000_000.) is None


@pytest.mark.parametrize("volume", [None, np.nan])
def test_unavailable_volume_keeps_existing_uncapped_size(settings, monkeypatch, volume):
    monkeypatch.setitem(ps.CONFIG, "max_pct_adv", .00001)
    monkeypatch.setitem(ps.CONFIG, "volume_impact_coeff", .5)
    trade, = _run(-2, volume)["trade_log"]
    assert trade["Shares"] == 200.
    assert trade["EntryPrice"] == 100.


def test_entry_impact_is_adverse_and_reported_round_trip(settings, monkeypatch):
    monkeypatch.setitem(ps.CONFIG, "volume_impact_coeff", .5)
    long = _run(1, 1_000_000.)["trade_log"][0]
    short = _run(-2, 1_000_000.)["trade_log"][0]
    impact = .5 * np.sqrt(200. / 1_000_000.)
    assert long["EntryPrice"] == pytest.approx(100. * (1 + impact))
    assert short["EntryPrice"] == pytest.approx(100. * (1 - impact))
    assert short["VolumeImpact_bps"] == long["VolumeImpact_bps"] == 141.4


def test_open_entry_uses_prior_bar_volume(settings, monkeypatch):
    monkeypatch.setitem(ps.CONFIG, "execution_time", "open")
    monkeypatch.setitem(ps.CONFIG, "max_pct_adv", 5e-5)
    monkeypatch.setitem(ps.CONFIG, "volume_impact_coeff", .5)
    control = _run(-2, 1_000_000.)["trade_log"][0]
    volume = np.full(30, 1_000_000.)
    volume[22] = 1_000.
    changed = _run(-2, volume)["trade_log"][0]
    assert control["Shares"] == changed["Shares"] == 50.
    assert control["EntryPrice"] == changed["EntryPrice"]


def test_impact_cannot_push_actual_stop_risk_over_heat(settings, monkeypatch):
    monkeypatch.setitem(ps.CONFIG, "position_sizing_method", "fixed_contracts")
    monkeypatch.setitem(ps.CONFIG, "fixed_contracts_per_trade", 100)
    monkeypatch.setitem(ps.CONFIG, "max_portfolio_heat", .03)
    monkeypatch.setitem(ps.CONFIG, "volume_impact_coeff", 1.)
    assert _run(-2, 1_000., {"type": "points", "value": 5.}) is None


def test_impacted_fill_updates_realized_risk_basis(settings, monkeypatch):
    monkeypatch.setitem(ps.CONFIG, "volume_impact_coeff", .5)
    trade, = _run(-2, 1_000_000., {"type": "points", "value": 5.})["trade_log"]
    assert trade["InitialRisk"] == pytest.approx(105. - trade["EntryPrice"])


def test_extreme_impact_cannot_create_nonpositive_fill(settings, monkeypatch):
    monkeypatch.setitem(ps.CONFIG, "volume_impact_coeff", 10.)
    assert _run(-2, 100.) is None


def test_following_entry_sees_impacted_risk(settings, monkeypatch):
    monkeypatch.setitem(ps.CONFIG, "position_sizing_method", "fixed_contracts")
    monkeypatch.setitem(ps.CONFIG, "fixed_contracts_per_trade", 4)
    monkeypatch.setitem(ps.CONFIG, "max_portfolio_heat", .005)
    monkeypatch.setitem(ps.CONFIG, "volume_impact_coeff", .5)
    idx = pd.bdate_range("2024-01-02", periods=7)
    df = pd.DataFrame({"Open": 100., "High": 101., "Low": 99.,
                       "Close": 100., "Volume": 100.}, index=idx)
    sig = pd.Series([0, -2, 0, 0, -1, 0, 0], index=idx)
    result = ps.run_portfolio_simulation(
        {"MESM6": df, "MESZ6": df.copy()}, {"MESM6": sig, "MESZ6": sig.copy()},
        100_000., .1, None, None, None, {"type": "points", "value": 5.})
    trade, = result["trade_log"]
    assert trade["Symbol"] == "MESM6"
    assert trade["EntryPrice"] == 90.
    assert trade["Shares"] * 5. * trade["InitialRisk"] == 300.


@pytest.mark.parametrize("commission,expected", [(0., 2010.), (2.5, 1913.)])
def test_affordability_uses_slipped_fill_even_without_volume_impact(
    settings, monkeypatch, commission, expected,
):
    monkeypatch.setitem(ps.CONFIG, "position_sizing_method", "fixed_contracts")
    monkeypatch.setitem(ps.CONFIG, "fixed_contracts_per_trade", 3000)
    monkeypatch.setitem(ps.CONFIG, "instruments", {
        **ps.CONFIG["instruments"], "futures_slippage_ticks": 2.,
        "futures_commission_per_contract": commission,
    })
    trade, = _run(-2)["trade_log"]
    assert trade["EntryPrice"] == 99.5
    assert trade["Shares"] == expected
    per_contract = 99.5 * 5. * .1 + commission
    assert expected * per_contract <= 100_000. < (expected + 1) * per_contract
