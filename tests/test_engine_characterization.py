# tests/test_engine_characterization.py
"""
GOLDEN-MASTER / CHARACTERIZATION TESTS for the portfolio execution engine.

Purpose
-------
This is the regression safety net for the futures instrument-metadata rewrite
(issue #229). Phase 1 routes helpers/portfolio_simulations.py through the new
Instrument layer and MUST NOT change equity behaviour by a single float.

These tests run the *real* run_portfolio_simulation across a matrix of scenarios
that each exercise a distinct engine code path, capture the full output
(trade_log + equity curve + result metrics), and assert it byte-for-byte against
a frozen fixture (tests/fixtures/engine_golden_master.json) generated from the
pre-refactor engine.

If Phase 1 (or any later phase) changes the equity path, these tests FAIL loudly,
pinpointing exactly which scenario and field diverged.

Regression map — scenario -> engine behaviour proven unchanged
--------------------------------------------------------------
  long_basic           entries/exits, %-slippage, per-share commission, end-of-run
                       mark-to-market of an open position, multi-trade sequencing
  long_pct_stop        percentage stop-loss exit path + InitialRisk / RMultiple
  long_atr_stop        ATR initial stop + ATR trailing-stop ratchet (the duplicated
                       ATR derivation that Phase 1 consolidates)
  short_borrow         short entry (-2) / cover (-1), HTB borrow-cost debit, short
                       MAE/MFE, short P&L accounting
  vol_impact           max_pct_adv liquidity cap + sqrt volume market-impact + bps log
  risk_parity_stop     risk_parity position sizing deriving stop_distance_pct from a
                       percentage stop + portfolio-heat check
  exclude_open         realized-only reporting (exclude_open_positions=True)
  multi_symbol         alphabetical entry ordering across >1 symbol, shared cash pool
  trailing_atr_equity  trailing_atr stop on an equity (CASH_FULL) symbol — anchors
                       stop/target/breakeven floor to slipped entry_price, not raw
                       (#240 fix); arm + trail + floor all exercise the equity path

Regenerate the fixture (ONLY when an intended behaviour change is reviewed):
    REGEN_GOLDEN=1 .venv/bin/python -m pytest tests/test_engine_characterization.py -q
"""

import json
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.portfolio_simulations import run_portfolio_simulation

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "engine_golden_master.json")
_ROUND = 6  # decimal places — tolerant of float repr, strict on real behaviour change


# ---------------------------------------------------------------------------
# Data builders
# ---------------------------------------------------------------------------
def _df(closes, *, opens=None, highs=None, lows=None, volumes=None, atr=None,
        start="2023-01-02"):
    """Build a deterministic OHLCV frame (optionally with an ATR_14 column)."""
    n = len(closes)
    closes = np.asarray(closes, dtype=float)
    opens = np.asarray(opens, dtype=float) if opens is not None else np.round(closes * 0.999, 4)
    highs = np.asarray(highs, dtype=float) if highs is not None else np.round(closes * 1.01, 4)
    lows = np.asarray(lows, dtype=float) if lows is not None else np.round(closes * 0.99, 4)
    vols = np.asarray(volumes, dtype=float) if volumes is not None else np.full(n, 1_000_000.0)
    idx = pd.bdate_range(start=start, periods=n, freq="B")
    idx.name = "Datetime"
    data = {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": vols}
    if atr is not None:
        data["ATR_14"] = np.asarray(atr, dtype=float)
    return pd.DataFrame(data, index=idx)


def _sig(df, pairs):
    """Signal series: pairs is {bar_index: signal_value}, else 0."""
    s = pd.Series(0, index=df.index, dtype=int)
    for i, v in pairs.items():
        s.iloc[i] = v
    return s


_BASE_CFG = {
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
}


# ---------------------------------------------------------------------------
# Scenario definitions -> (portfolio_data, signals, cfg_overrides, stop_config, kwargs)
# ---------------------------------------------------------------------------
def _scenario(name):
    if name == "long_basic":
        df = _df([100, 101, 102, 103, 104, 103, 102, 105, 106, 107, 108, 109, 110, 111, 112])
        sig = _sig(df, {3: 1, 7: -1, 9: 1})  # trade, close, re-enter, leave open -> MTM
        return {"AAA": df}, {"AAA": sig}, {}, {"type": "none"}, {}

    if name == "long_pct_stop":
        df = _df([100, 101, 102, 101, 100, 94, 95, 96, 97, 98])
        sig = _sig(df, {1: 1})  # enter; 5% stop should fire on the drop
        return {"BBB": df}, {"BBB": sig}, {}, {"type": "percentage", "value": 0.05}, {}

    if name == "long_atr_stop":
        closes = [100, 101, 102, 103, 104, 100, 96, 97, 98, 99, 101, 103]
        df = _df(closes, atr=[2.0] * len(closes))
        sig = _sig(df, {2: 1})  # execution=open -> fill next bar; ATR stop active
        return ({"CCC": df}, {"CCC": sig}, {"execution_time": "open"},
                {"type": "atr", "multiplier": 3.0}, {})

    if name == "short_borrow":
        df = _df([100, 99, 98, 97, 96, 95, 96, 97])
        sig = _sig(df, {1: -2, 5: -1})  # short entry then cover
        return ({"DDD": df}, {"DDD": sig}, {"htb_rate_annual": 0.02},
                {"type": "none"}, {})

    if name == "vol_impact":
        df = _df([100, 101, 102, 103, 104, 105, 106, 107],
                 volumes=[50_000] * 8)  # small ADV so cap + impact bite
        sig = _sig(df, {2: 1, 6: -1})
        return ({"EEE": df}, {"EEE": sig},
                {"execution_time": "open", "volume_impact_coeff": 0.1, "max_pct_adv": 0.05},
                {"type": "none"}, {})

    if name == "risk_parity_stop":
        df = _df([100, 101, 102, 103, 104, 105, 106, 107, 108, 109])
        sig = _sig(df, {1: 1, 6: -1})
        return ({"FFF": df}, {"FFF": sig},
                {"position_sizing_method": "risk_parity", "target_risk_per_trade": 0.02,
                 "max_portfolio_heat": 1.0},
                {"type": "percentage", "value": 0.05}, {})

    if name == "exclude_open":
        df = _df([100, 101, 102, 103, 104, 105, 106, 107])
        sig = _sig(df, {1: 1, 4: -1, 6: 1})  # one closed trade + one left open
        return ({"GGG": df}, {"GGG": sig}, {"exclude_open_positions": True},
                {"type": "none"}, {})

    if name == "multi_symbol":
        df1 = _df([100, 101, 102, 103, 104, 105, 106, 107, 108])
        df2 = _df([50, 51, 52, 51, 50, 49, 50, 51, 52])
        sig1 = _sig(df1, {1: 1, 5: -1})
        sig2 = _sig(df2, {1: 1, 6: -1})
        return ({"AAA": df1, "BBB": df2}, {"AAA": sig1, "BBB": sig2}, {},
                {"type": "none"}, {})

    if name == "trailing_atr_equity":
        # Exercises the equity (CASH_FULL) trailing_atr stop path introduced in #240.
        # execution_time="open": signal fires on bar 2, fill is bar 3 Open.
        # ATR locked at bar 2 = 2.0.  stop_mult=1, t1_mult=2, trail_mult=1.
        # entry_price (slipped) = bar3_Open * (1 + slippage_pct).
        # Under the #240 fix the stop/target/floor ANCHOR = slipped entry_price
        # (not raw_entry_price), so stop = entry_price - 2.0, target = entry_price + 4.0.
        # Price rises to 107 (hits target -> trail arms), then drops to 103 (trail fires).
        closes = [100, 101, 100, 101, 103, 105, 107, 107, 105, 103, 101]
        opens  = [100, 100, 101, 101, 102, 104, 106, 107, 106, 104, 102]
        highs  = [101, 102, 101, 102, 104, 106, 108, 108, 106, 104, 102]
        lows   = [99,   99,  99, 100, 101, 103, 105, 106, 104, 102, 100]
        df = _df(closes, opens=opens, highs=highs, lows=lows,
                 atr=[2.0] * len(closes))
        sig = _sig(df, {2: 1})  # enter on bar 2, leave open -> trail fires or MTM
        return ({"HHH": df}, {"HHH": sig},
                {"execution_time": "open"},
                {"type": "trailing_atr", "stop_mult": 1.0, "trail_mult": 1.0,
                 "t1_mult": 2.0, "floor": "breakeven"}, {})

    raise ValueError(name)


SCENARIOS = [
    "long_basic", "long_pct_stop", "long_atr_stop", "short_borrow",
    "vol_impact", "risk_parity_stop", "exclude_open", "multi_symbol",
    "trailing_atr_equity",
]


# ---------------------------------------------------------------------------
# Canonicalisation + run
# ---------------------------------------------------------------------------
def _canon(obj):
    """Recursively normalise for stable JSON comparison: round floats, NaN->None,
    numpy -> python, drop volatile container objects."""
    if isinstance(obj, dict):
        return {k: _canon(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_canon(v) for v in obj]
    if isinstance(obj, (np.floating, float)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else round(f, _ROUND)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _snapshot(name):
    portfolio_data, signals, cfg_over, stop_config, kwargs = _scenario(name)
    cfg = {**_BASE_CFG, **cfg_over}
    from unittest.mock import patch
    with patch.dict("config.CONFIG", cfg, clear=False):
        result = run_portfolio_simulation(
            portfolio_data=portfolio_data,
            signals=signals,
            initial_capital=100_000.0,
            allocation_pct=0.10,
            spy_df=None, vix_df=None, tnx_df=None,
            stop_config=stop_config,
            **kwargs,
        )
    assert result is not None, f"scenario {name!r} produced no trades"

    timeline = result.get("portfolio_timeline")
    scalars = {k: v for k, v in result.items()
               if isinstance(v, (int, float, str, bool, np.floating, np.integer, np.bool_))}
    return {
        "scalars": _canon(scalars),
        "trade_log": _canon(result.get("trade_log", [])),
        "equity_curve": _canon(list(timeline.values)) if timeline is not None else [],
        "equity_len": int(len(timeline)) if timeline is not None else 0,
    }


def _load_fixture():
    if not os.path.exists(_FIXTURE):
        return None
    with open(_FIXTURE) as fh:
        return json.load(fh)


def _regen_requested():
    return os.environ.get("REGEN_GOLDEN") == "1"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def golden():
    """Load the frozen fixture, regenerating it only when REGEN_GOLDEN=1."""
    existing = _load_fixture()
    if existing is not None and not _regen_requested():
        return existing
    # Generate from the current engine.
    generated = {name: _snapshot(name) for name in SCENARIOS}
    os.makedirs(os.path.dirname(_FIXTURE), exist_ok=True)
    with open(_FIXTURE, "w") as fh:
        json.dump(generated, fh, indent=2, sort_keys=True)
    return generated


@pytest.mark.parametrize("name", SCENARIOS)
def test_scenario_matches_golden_master(name, golden):
    assert name in golden, f"fixture missing scenario {name!r} — REGEN_GOLDEN=1 to add it"
    expected = golden[name]
    actual = _snapshot(name)
    assert actual["scalars"] == expected["scalars"], f"{name}: result scalars diverged"
    assert actual["trade_log"] == expected["trade_log"], f"{name}: trade_log diverged"
    assert actual["equity_curve"] == expected["equity_curve"], f"{name}: equity curve diverged"
    assert actual["equity_len"] == expected["equity_len"], f"{name}: equity length diverged"


def test_fixture_committed_and_complete():
    """The fixture must exist on disk and cover every scenario — otherwise the
    golden master is not actually guarding anything in CI."""
    fixture = _load_fixture()
    assert fixture is not None, "engine_golden_master.json missing — commit the fixture"
    for name in SCENARIOS:
        assert name in fixture, f"fixture missing scenario {name!r}"
        assert fixture[name]["trade_log"], f"scenario {name!r} has empty trade_log in fixture"
