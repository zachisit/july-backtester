# tests/test_data_quality_calendar.py
"""
Calendar-aware missing-bar check in helpers/data_quality.py (futures support).

An NYSE (equity) daily series with weekday gaps is flagged for missing bars; the
same series under a CME_ETH (futures) calendar is not, because the NYSE business-day
estimate does not describe a 23/5 futures session calendar.
"""

import os
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.data_quality import validate_ohlcv, quality_report


def _gappy_daily():
    # 3 months of business days, then drop ~40% to simulate a different calendar.
    idx = pd.bdate_range("2023-01-02", periods=60)
    keep = idx[::2]  # every other business day -> ~50% "missing" under the NYSE estimate
    closes = np.linspace(100, 120, len(keep))
    return pd.DataFrame({"Open": closes, "High": closes * 1.001, "Low": closes * 0.999,
                         "Close": closes, "Volume": np.full(len(keep), 1e6)}, index=keep)


def test_nyse_flags_missing_bars():
    df = _gappy_daily()
    _, issues = validate_ohlcv(df, "AAPL", "D", calendar="NYSE")
    assert any("Missing bars" in i for i in issues)


def test_futures_calendar_skips_missing_bar_check():
    df = _gappy_daily()
    _, issues = validate_ohlcv(df, "ESM6", "D", calendar="CME_ETH")
    assert not any("Missing bars" in i for i in issues)


def test_quality_report_resolves_calendar_from_config():
    df = _gappy_daily()
    cfg = {"instruments": {"default_asset_class": "equity", "overrides": {}}}
    # ESM6 auto-resolves to a futures instrument (CME_ETH) -> no missing-bar flag.
    report = quality_report(["ESM6"], {"ESM6": df}, "D", config=cfg)
    row = report[report["symbol"] == "ESM6"].iloc[0]
    assert "Missing bars" not in row["issues"]
