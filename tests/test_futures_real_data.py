# tests/test_futures_real_data.py
"""
Real-data verification for the futures engine against the MNQ 1-minute continuous
dataset from july-backtester-private-strategies PR #32 (merged).

These tests run only when the private submodule data is checked out; they skip
cleanly in CI / on machines without it, so they never break the public suite.

Proves the implementation works end-to-end on the *actual* delivered format:
  - tz-aware `ts_event` index (America/New_York), lowercase OHLC + close_unadj +
    source_family columns -> consumed via services/parquet_service normalisation
  - daily futures backtest on MNQ ($2/point) -> integer contracts, $/point P&L,
    margin-based equity
  - Phase-5 sub-bar resolution against genuine 1-minute session bars
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
from helpers import intrabar
from services import parquet_service

_MNQ_RTH = os.path.join(
    PROJECT_ROOT, "custom_strategies", "private",
    "futures_intraday_data", "mnq", "nq_mnq_RTH_clean_stitched.parquet",
)

pytestmark = pytest.mark.skipif(
    not os.path.isfile(_MNQ_RTH),
    reason="private MNQ intraday dataset (PR #32) not checked out; skipping real-data test",
)

_CFG = {
    "slippage_pct": 0.0005, "commission_per_share": 0.002, "execution_time": "close",
    "risk_free_rate": 0.05, "htb_rate_annual": 0.0, "volume_impact_coeff": 0.0,
    "max_pct_adv": 0.0, "position_sizing_method": "fixed", "target_risk_per_trade": 0.02,
    "max_portfolio_heat": 1.0, "entry_priority": "alphabetical",
    "exclude_open_positions": False, "include_delisted": False,
    "instruments": {
        "default_asset_class": "equity",
        "futures_initial_margin_pct": 0.10,
        "futures_commission_per_contract": 0.52,   # typical MNQ round-turn-ish, one side
        "futures_slippage_ticks": 1.0,
        "overrides": {
            "MNQ": {"asset_class": "future", "point_value": 2.0, "tick_size": 0.25},
        },
    },
}


def _load_minute(window_start="2023-01-01", window_end="2023-06-30"):
    df = pd.read_parquet(_MNQ_RTH, columns=["open", "high", "low", "close", "volume"])
    df = df.rename(columns={"open": "Open", "high": "High", "low": "Low",
                            "close": "Close", "volume": "Volume"})
    df.index = df.index.tz_convert("UTC")
    lo = pd.Timestamp(window_start, tz="UTC")
    hi = pd.Timestamp(window_end, tz="UTC")
    return df.loc[(df.index >= lo) & (df.index <= hi)]


def _to_daily(minute_df):
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    daily = minute_df.resample("1D").agg(agg).dropna(subset=["Open", "High", "Low", "Close"])
    daily.index = daily.index.normalize()
    daily.index.name = "Datetime"
    return daily


def _sma_signal(daily, fast=5, slow=20):
    f = daily["Close"].rolling(fast).mean()
    s = daily["Close"].rolling(slow).mean()
    sig = pd.Series(0, index=daily.index, dtype=int)
    long = (f > s)
    sig[long & ~long.shift(1, fill_value=False)] = 1     # cross up -> enter
    sig[~long & long.shift(1, fill_value=False)] = -1    # cross down -> exit
    return sig


def test_format_consumed_by_parquet_service():
    # The delivered lowercase/tz-aware format normalises to canonical OHLCV via the
    # same path a `parquet` data_provider run would use.
    raw = pd.read_parquet(_MNQ_RTH).head(500)
    norm = parquet_service._normalise_columns(raw.copy())
    assert norm is not None
    assert list(norm.columns) == ["Open", "High", "Low", "Close", "Volume"]
    utc = parquet_service._to_utc_index(norm)
    assert isinstance(utc.index, pd.DatetimeIndex) and str(utc.index.tz) == "UTC"


def test_mnq_daily_futures_backtest():
    from unittest.mock import patch
    daily = _to_daily(_load_minute())
    assert len(daily) > 60, "expected a few months of daily bars"
    signals = {"MNQ": _sma_signal(daily)}

    with patch.dict("config.CONFIG", _CFG, clear=False):
        assert resolve_instrument("MNQ", _CFG).asset_class == "future"
        res = run_portfolio_simulation(
            portfolio_data={"MNQ": daily}, signals=signals,
            initial_capital=100_000.0, allocation_pct=1.0,
            spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"})

    assert res is not None and res["trade_log"], "expected trades on real MNQ data"
    for t in res["trade_log"]:
        # whole contracts, and $/point P&L reconstructs from the logged fills
        assert t["Shares"] == float(int(t["Shares"])) and t["Shares"] >= 1
        exp = t["Shares"] * (t["ExitPrice"] - t["EntryPrice"]) * 2.0 - 2 * (t["Shares"] * 0.52)
        assert t["Profit"] == pytest.approx(exp, abs=1e-6)
    # margin accounting: equity never collapses by a full contract notional (~30k+)
    assert res["portfolio_timeline"].min() > 50_000.0


def test_phase5_resolver_on_real_minute_bars():
    minute = _load_minute("2023-03-01", "2023-03-31")
    # pick one real session and confirm the sub-bar resolver fills a mid-range stop
    day = pd.Timestamp(minute.index[len(minute) // 2].date())
    session = intrabar.session_bars(minute.tz_convert("America/New_York"), day)
    assert session is not None and len(session) > 10
    stop = float((session["High"].max() + session["Low"].min()) / 2)  # inside the day's range
    fill, ts = intrabar.resolve_stop_fill(session, stop, side="long")
    assert fill is not None and ts is not None
    assert fill <= stop + 1e-6  # long stop fills at or below the level (gap-aware)
