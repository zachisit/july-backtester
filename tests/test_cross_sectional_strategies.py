# tests/test_cross_sectional_strategies.py
"""
Tests for ``@register_portfolio_strategy`` — cross-sectional strategy support.

The gap this closes: ``register_strategy`` calls its function once per symbol,
so a strategy can never rank the universe against itself. Anything
cross-sectional therefore had to be written as a standalone script with its own
execution loop — duplicating sizing, costs and equity accounting outside the
engine and outside the golden-master suite that protects it.

These cover the registration mechanics, the return-shape contract, causality,
and that the per-symbol path is untouched.
"""

import numpy as np
import pandas as pd
import pytest

from helpers.registry import (
    REGISTRY,
    is_portfolio_level,
    register_portfolio_strategy,
    register_strategy,
)


def _ohlcv(n=300, start=100.0, step=0.5, seed=0):
    rng = np.random.default_rng(seed)
    close = start + np.cumsum(rng.normal(step, 1.0, n))
    close = np.maximum(close, 1.0)
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": 1_000_000.0},
        index=idx,
    )


def _universe(n_sym=6, n=300):
    return {f"S{i}": _ohlcv(n, start=50.0 + 10 * i, step=0.1 * (i + 1), seed=i)
            for i in range(n_sym)}


# ---------------------------------------------------------------------------
# Registration mechanics
# ---------------------------------------------------------------------------

class TestRegistration:

    def test_portfolio_strategy_is_flagged(self):
        @register_portfolio_strategy(name="_t_flagged", params={"a": 1})
        def strat(portfolio_data, **kwargs):
            return {}

        assert is_portfolio_level(strat)
        assert REGISTRY["_t_flagged"]["portfolio_level"] is True
        assert REGISTRY["_t_flagged"]["params"] == {"a": 1}

    def test_per_symbol_strategy_is_not_flagged(self):
        @register_strategy(name="_t_plain")
        def strat(df, **kwargs):
            return df.assign(Signal=0)

        assert not is_portfolio_level(strat)
        assert REGISTRY["_t_plain"]["portfolio_level"] is False

    def test_is_portfolio_level_defaults_false_for_plain_callable(self):
        """An undecorated function must not be mistaken for cross-sectional."""
        assert not is_portfolio_level(lambda df, **kw: df)

    def test_both_kinds_coexist_in_one_registry(self):
        @register_portfolio_strategy(name="_t_xs")
        def a(portfolio_data, **kwargs):
            return {}

        @register_strategy(name="_t_ps")
        def b(df, **kwargs):
            return df.assign(Signal=0)

        assert REGISTRY["_t_xs"]["portfolio_level"] is True
        assert REGISTRY["_t_ps"]["portfolio_level"] is False

    def test_dependencies_and_params_are_copied_not_aliased(self):
        deps, params = ["spy"], {"n": 5}

        @register_portfolio_strategy(name="_t_copy", dependencies=deps, params=params)
        def strat(portfolio_data, **kwargs):
            return {}

        deps.append("vix")
        params["n"] = 99
        assert REGISTRY["_t_copy"]["dependencies"] == ["spy"]
        assert REGISTRY["_t_copy"]["params"] == {"n": 5}


# ---------------------------------------------------------------------------
# The reference plugin
# ---------------------------------------------------------------------------

class TestCrossSectionalMomentum:

    @staticmethod
    def _load():
        import importlib
        mod = importlib.import_module("custom_strategies.cross_sectional_momentum")
        return mod.cross_sectional_momentum

    def test_registers_as_portfolio_level(self):
        assert is_portfolio_level(self._load())

    def test_returns_one_series_per_symbol_aligned_to_its_index(self):
        fn = self._load()
        uni = _universe()
        out = fn(uni, lookback=60, top_n=2, exit_rank=4, trend_ma=100)

        assert set(out) == set(uni)
        for sym, sig in out.items():
            assert isinstance(sig, pd.Series)
            assert sig.index.equals(uni[sym].index)
            assert set(np.unique(sig)).issubset({-1, 1})

    def test_holds_at_most_top_n_after_hysteresis_band(self):
        """No bar may hold more names than exit_rank allows."""
        fn = self._load()
        uni = _universe(n_sym=8)
        out = fn(uni, lookback=60, top_n=2, exit_rank=4, trend_ma=100)
        held = pd.DataFrame(out)
        assert (held == 1).sum(axis=1).max() <= 4

    def test_no_look_ahead(self):
        """Truncation invariance — a signal at t must not depend on t+1.

        The load-bearing test for any ranking strategy: cross-sectional ops make
        it easy to accidentally rank against a future row.
        """
        fn = self._load()
        uni = _universe(n_sym=5, n=300)
        kw = dict(lookback=60, top_n=2, exit_rank=4, trend_ma=100)

        full = fn(uni, **kw)
        for cut in (200, 250, 280):
            trunc = fn({s: d.iloc[: cut + 1] for s, d in uni.items()}, **kw)
            for sym in uni:
                assert full[sym].iloc[cut] == trunc[sym].iloc[cut], (
                    f"{sym} signal at bar {cut} changed when future bars were removed"
                )

    def test_empty_universe_is_handled(self):
        assert self._load()({}, lookback=60, top_n=5, exit_rank=15, trend_ma=200) == {}

    def test_warmup_is_flat_not_long(self):
        """Before enough history exists nothing may be held."""
        fn = self._load()
        uni = _universe(n_sym=4, n=300)
        out = fn(uni, lookback=60, top_n=2, exit_rank=4, trend_ma=200)
        held = pd.DataFrame(out).iloc[:199]
        assert (held == 1).sum().sum() == 0, "held a position before warm-up completed"


# ---------------------------------------------------------------------------
# Return-shape contract (what main.py's dispatch accepts)
# ---------------------------------------------------------------------------

class TestReturnShapeContract:
    """main.py accepts {sym: Series} or {sym: DataFrame-with-Signal}, and treats
    an omitted symbol as flat. Asserted here on the same normalisation logic."""

    @staticmethod
    def _normalise(raw_signals, portfolio_data, name="test"):
        out = {}
        for symbol, df in portfolio_data.items():
            sig = raw_signals.get(symbol)
            if sig is None:
                out[symbol] = pd.Series(0, index=df.index)
                continue
            if isinstance(sig, pd.DataFrame):
                if "Signal" not in sig.columns:
                    raise KeyError(name)
                sig = sig["Signal"]
            out[symbol] = pd.Series(sig).reindex(df.index).fillna(0)
        return out

    def test_series_return_is_accepted(self):
        uni = _universe(n_sym=3, n=50)
        raw = {s: pd.Series(1, index=d.index) for s, d in uni.items()}
        out = self._normalise(raw, uni)
        assert all((v == 1).all() for v in out.values())

    def test_dataframe_with_signal_is_accepted(self):
        uni = _universe(n_sym=3, n=50)
        raw = {s: d.assign(Signal=1) for s, d in uni.items()}
        out = self._normalise(raw, uni)
        assert all((v == 1).all() for v in out.values())

    def test_omitted_symbol_is_flat_not_missing(self):
        """A symbol the strategy never selected must be flat, not dropped —
        otherwise run_portfolio_simulation would see an incomplete universe."""
        uni = _universe(n_sym=3, n=50)
        raw = {"S0": pd.Series(1, index=uni["S0"].index)}
        out = self._normalise(raw, uni)
        assert set(out) == set(uni)
        assert (out["S1"] == 0).all() and (out["S2"] == 0).all()

    def test_partial_index_is_reindexed_and_zero_filled(self):
        uni = _universe(n_sym=1, n=50)
        short = pd.Series(1, index=uni["S0"].index[-10:])
        out = self._normalise({"S0": short}, uni)
        assert out["S0"].index.equals(uni["S0"].index)
        assert (out["S0"].iloc[:-10] == 0).all()
        assert (out["S0"].iloc[-10:] == 1).all()

    def test_dataframe_without_signal_column_raises(self):
        uni = _universe(n_sym=1, n=50)
        with pytest.raises(KeyError):
            self._normalise({"S0": uni["S0"]}, uni)
