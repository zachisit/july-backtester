"""
tests/test_symbol_injection.py

Regression tests for the per-symbol signal-generation loop in
``main.run_single_simulation``.

The engine iterates every symbol in ``portfolio_data`` and calls the strategy
logic function as ``logic_func(df.copy(), **kwargs)``. Prior to this change the
loop never told the strategy *which* symbol's DataFrame it was processing, so
per-symbol / event-driven strategies (e.g. one keyed on a per-ticker
earnings-date table) could not identify their own ticker.

These tests assert that ``kwargs["symbol"]`` is injected with the ticker being
processed for every symbol in the portfolio. They drive the real
``run_single_simulation`` code path (globals populated via ``init_worker``), so
they FAIL if the ``kwargs["symbol"] = symbol`` injection is removed and PASS
with it.

Deterministic: no network, no randomness, no file I/O.
"""

import os
import sys

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import main
from helpers.registry import _REGISTRY, register_strategy


def _ohlcv(n: int = 40) -> pd.DataFrame:
    """Minimal valid OHLCV frame with a daily DatetimeIndex."""
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    price = np.linspace(100.0, 110.0, n)
    return pd.DataFrame(
        {
            "Open": price,
            "High": price + 1.0,
            "Low": price - 1.0,
            "Close": price,
            "Volume": [1_000_000] * n,
        },
        index=idx,
    )


def _drive_loop(portfolio_data, logic_func):
    """Run the real ``run_single_simulation`` per-symbol loop and return the
    result. Globals are wired exactly as ``init_worker`` does in production."""
    # No dependencies, no benchmarks, no PIT masks -> the loop reaches the
    # ``logic_func(df.copy(), **kwargs)`` call for every symbol unconditionally.
    main.init_worker(
        comparison_dfs_dict={},
        benchmark_returns_dict={},
        dependency_map_dict={},
        portfolio_data_for_worker=portfolio_data,
        delisting_dates_for_worker=None,
        pit_member_masks_dict=None,
        intrabar_data_for_worker=None,
    )
    args = (
        "Test Portfolio",   # portfolio_name
        "Symbol Probe",     # name
        logic_func,         # logic_func
        [],                 # dependencies
        {"type": "none"},   # stop_config
        {},                 # strategy_params
        None,               # wfa_split_date
        None,               # spy_actual_start
        None,               # spy_actual_end
    )
    return main.run_single_simulation(args)


class TestSymbolInjection:
    def test_symbol_kwarg_received_for_each_ticker(self):
        """Each strategy call must receive kwargs['symbol'] == its ticker."""
        portfolio_data = {"AAPL": _ohlcv(), "MSFT": _ohlcv()}
        seen = []

        def probe(df, **kwargs):
            seen.append(kwargs.get("symbol"))
            # No-trade signal so the downstream simulation is trivial/cheap.
            return df.assign(Signal=0)

        _drive_loop(portfolio_data, probe)

        # Without the kwargs["symbol"] = symbol injection this list is
        # [None, None]; with it, it is exactly the portfolio's tickers.
        assert seen == list(portfolio_data.keys())
        assert None not in seen

    def test_single_symbol_matches_exactly(self):
        portfolio_data = {"TSLA": _ohlcv()}
        captured = {}

        def probe(df, **kwargs):
            captured["symbol"] = kwargs.get("symbol")
            return df.assign(Signal=0)

        _drive_loop(portfolio_data, probe)

        assert captured["symbol"] == "TSLA"

    def test_symbol_injection_via_registered_strategy(self):
        """A strategy registered through @register_strategy also receives the
        injected symbol (exercises the public registry API end-to-end)."""
        seen = []
        saved = dict(_REGISTRY)
        try:

            @register_strategy(name="Probe Symbol Recorder", dependencies=[], params={})
            def _probe(df, **kwargs):
                seen.append(kwargs.get("symbol"))
                return df.assign(Signal=0)

            portfolio_data = {"NVDA": _ohlcv(), "AMD": _ohlcv()}
            logic = _REGISTRY["Probe Symbol Recorder"]["logic"]
            _drive_loop(portfolio_data, logic)

            assert seen == ["NVDA", "AMD"]
        finally:
            _REGISTRY.clear()
            _REGISTRY.update(saved)
