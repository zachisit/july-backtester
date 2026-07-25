# tests/test_main_delisting_wiring.py
"""
Regression test for the main.py -> run_portfolio_simulation call-site wiring.

Bug: main.run_single_simulation passed `delisting_dates_global` as the 9th
positional argument, which is the `size_mults` parameter — so survivorship
force-close (`delisting_dates`) silently received None and was disabled, while
`size_mults` was fed a {symbol: date-string} dict it was never meant to get.

This test captures the actual call and asserts delisting dates arrive via the
`delisting_dates` keyword and nothing lands in the `size_mults` slot.
"""

import os
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import main


def test_delisting_dates_passed_by_keyword(monkeypatch):
    idx = pd.bdate_range("2023-01-02", periods=6)
    df = pd.DataFrame(
        {"Open": 10.0, "High": 11.0, "Low": 9.0, "Close": 10.0, "Volume": 1e6},
        index=idx,
    )

    monkeypatch.setattr(main, "comparison_dfs_global", {}, raising=False)
    monkeypatch.setattr(main, "benchmark_returns_global", {}, raising=False)
    monkeypatch.setattr(main, "dependency_map_global", {}, raising=False)
    monkeypatch.setattr(main, "portfolio_data_global", {"AAA": df}, raising=False)
    monkeypatch.setattr(main, "delisting_dates_global", {"AAA": "2023-01-05"}, raising=False)
    monkeypatch.setattr(main, "pit_member_masks_global", None, raising=False)

    def logic(d, **kwargs):
        d = d.copy()
        d["Signal"] = 0
        return d

    captured = {}

    def fake_run_portfolio_simulation(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return None  # short-circuits the rest of run_single_simulation

    monkeypatch.setattr(main, "run_portfolio_simulation", fake_run_portfolio_simulation)

    # (portfolio_name, name, logic_func, dependencies, stop_config,
    #  strategy_params, wfa_split_date, spy_actual_start, spy_actual_end)
    task = ("P", "S", logic, [], {"type": "none"}, {}, None, None, None)
    main.run_single_simulation(task)

    assert "args" in captured, "run_portfolio_simulation was never called"
    # delisting dates must arrive via the keyword, not the positional size_mults slot
    assert captured["kwargs"].get("delisting_dates") == {"AAA": "2023-01-05"}
    # exactly 8 positional args (through stop_config) — nothing spills into size_mults
    assert len(captured["args"]) == 8
    assert captured["kwargs"].get("size_mults") is None
