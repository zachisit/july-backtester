"""Every entry leg reports the actual reason its configured size changed (#387)."""
import logging
from unittest.mock import patch

import pandas as pd
import pytest

from helpers import portfolio_simulations as ps

PATHS = [(1, "AAA"), (-2, "AAA"), (1, "MESM6"), (-2, "MESM6")]


def _run(side, symbol, method="fixed", stop=None, alloc=.1, **overrides):
    idx = pd.bdate_range("2024-01-02", periods=10)
    volume = overrides.pop("volume", 1e6)
    atr = overrides.pop("atr", 1.)
    df = pd.DataFrame({"Open": 100., "High": 101., "Low": 99., "Close": 100.,
                       "Volume": volume, "ATR_14": atr}, index=idx)
    sig = pd.Series(0, index=idx)
    sig.iloc[2], sig.iloc[8] = side, -1
    config = {
        "execution_time": "close", "entry_trigger": "edge",
        "position_sizing_method": method, "target_risk_per_trade": .02,
        "risk_pct_per_trade": .01, "risk_pct_capped_max_notional_pct": 1.,
        "max_contracts_cap": 20, "max_pct_adv": 0., "volume_impact_coeff": 0.,
        "max_portfolio_heat": 100., "slippage_pct": 0., "commission_per_share": 0.,
        "short_margin_requirement": .5, "htb_rate_annual": 0.,
        "exclude_open_positions": False, "include_delisted": False,
        "entry_priority": "alphabetical",
        "instruments": {"default_asset_class": "equity", "overrides": {},
                        "futures_initial_margin_pct": .1,
                        "futures_commission_per_contract": 0.,
                        "futures_slippage_ticks": 0.},
        **overrides,
    }
    with patch.dict(ps.CONFIG, config):
        return ps.run_portfolio_simulation(
            {symbol: df}, {symbol: sig}, 100_000., alloc, None, None, None,
            stop or {"type": "percentage", "value": .05})


@pytest.mark.parametrize("side,symbol", PATHS)
def test_no_stop_zero_trade_run_has_one_report(side, symbol, caplog):
    caplog.set_level(logging.WARNING)
    assert _run(side, symbol, "risk_pct_capped", {"type": "none"}) is None
    assert "no stop distance" in caplog.text.lower()
    assert caplog.text.count("Position sizing:") == 1


@pytest.mark.parametrize("side,symbol", PATHS)
def test_adv_clamp_is_reported_on_every_leg(side, symbol):
    result = _run(side, symbol, volume=100., max_pct_adv=.05)
    assert result["trade_log"][0]["Shares"] == 5.
    assert result["sizing_diagnostics"]["clamped_by_adv"] == 1


@pytest.mark.parametrize("side,symbol", PATHS)
def test_heat_rejection_is_reported_on_every_leg(side, symbol, caplog):
    caplog.set_level(logging.WARNING)
    assert _run(side, symbol, max_portfolio_heat=.0001) is None
    assert "max_portfolio_heat" in caplog.text
    assert caplog.text.count("Position sizing:") == 1


@pytest.mark.parametrize("side,symbol", PATHS)
def test_cash_or_margin_reduction_is_reported_on_every_leg(side, symbol):
    result = _run(side, symbol, alloc=3.)
    assert result["sizing_diagnostics"]["clamped_by_cash"] >= 1


@pytest.mark.parametrize("side,symbol", PATHS)
def test_actual_atr_proxy_joins_the_single_run_report(side, symbol, caplog):
    caplog.set_level(logging.WARNING)
    result = _run(side, symbol, "risk_parity", {"type": "none"})
    assert result["sizing_diagnostics"]["atr_proxy_substituted"] == 1
    assert caplog.text.count("Position sizing:") == 1
    assert not any(r.name == "helpers.position_sizing" and "3xATR" in r.message
                   for r in caplog.records)


@pytest.mark.parametrize("side", [1, -2])
def test_notional_ceiling_is_reported_in_both_equity_directions(side):
    result = _run(side, "AAA", "risk_pct_capped", {"type": "points", "value": .5})
    assert result["sizing_diagnostics"]["clamped_by_notional_ceiling"] == 1


@pytest.mark.parametrize("side,symbol", PATHS)
def test_known_stop_without_valid_atr_is_absent_distance_not_coverage_drift(side, symbol, caplog):
    caplog.set_level(logging.WARNING)
    assert _run(side, symbol, "risk_pct_capped", {"type": "atr", "multiplier": 2.}, atr=float("nan")) is None
    assert "no stop distance" in caplog.text.lower()
    assert "unsupported stop type" not in caplog.text.lower()


@pytest.mark.parametrize("side,symbol", PATHS)
def test_healthy_entries_stay_silent(side, symbol, caplog):
    caplog.set_level(logging.WARNING)
    result = _run(side, symbol)
    assert result["sizing_diagnostics"] == {}
    assert "Position sizing:" not in caplog.text


@pytest.mark.parametrize("side,symbol", PATHS)
def test_unknown_stop_is_reported_as_coverage_drift(side, symbol, caplog):
    caplog.set_level(logging.WARNING)
    assert _run(side, symbol, "risk_pct_capped", {"type": "future_stop"}) is None
    assert "unsupported stop type" in caplog.text
    assert "future_stop" in caplog.text


@pytest.mark.parametrize("side", [1, -2])
def test_zero_notional_ceiling_is_reported_before_zero_trade_return(side, caplog):
    caplog.set_level(logging.WARNING)
    assert _run(side, "AAA", "risk_pct_capped", {"type": "points", "value": .5},
                risk_pct_capped_max_notional_pct=0.) is None
    assert "ceiling-clamped" in caplog.text


@pytest.mark.parametrize("side", [1, -2])
def test_contract_risk_cap_is_reported_when_it_actually_binds(side):
    result = _run(side, "MESM6", "risk_pct_capped", {"type": "points", "value": .5})
    assert result["trade_log"][0]["Shares"] == 20.
    assert result["sizing_diagnostics"]["clamped_by_contract_cap"] == 1


def test_every_reason_has_a_producer_outside_the_reason_catalog():
    import ast
    from pathlib import Path
    from helpers.sizing_diagnostics import REASONS
    constants = set()
    for name in ("position_sizing.py", "portfolio_simulations.py"):
        tree = ast.parse((Path(ps.__file__).parent / name).read_text())
        constants.update(n.value for n in ast.walk(tree)
                         if isinstance(n, ast.Constant) and isinstance(n.value, str))
    assert set(REASONS) <= constants


@pytest.mark.parametrize("side", [1, -2])
def test_tiny_adv_limited_equity_entry_is_declined_and_explained(side, caplog):
    caplog.set_level(logging.WARNING)
    assert _run(side, "AAA", volume=.02, max_pct_adv=.05) is None
    assert "max_pct_adv" in caplog.text


@pytest.mark.parametrize("side", [1, -2])
def test_custom_ceiling_explains_configured_limit_without_claiming_leverage(side, caplog):
    caplog.set_level(logging.WARNING)
    result = _run(side, "AAA", "risk_pct_capped", {"type": "percentage", "value": .05},
                  risk_pct_capped_max_notional_pct=.10)
    assert result["trade_log"][0]["Shares"] == 100.
    assert "configured notional ceiling" in caplog.text
    assert "leverage" not in caplog.text


def test_unsupported_type_examples_are_bounded():
    from helpers.sizing_diagnostics import SizingDiagnostics
    diagnostics = SizingDiagnostics()
    for i in range(50):
        diagnostics.record("unsupported_stop_type", "AAA", detail=f"type-{i}")
    report = diagnostics.format_report()
    assert "type-0" in report and "type-49" not in report
