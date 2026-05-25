"""Tests for the blind-design cutoff guard.

The guard is the operational backbone of the v2 autonomous loop's response
to the spec-level-lookahead critique. These tests pin its three observable
behaviours:
  1. Loading data wholly before the cutoff succeeds.
  2. Loading data that crosses the cutoff raises BlindDesignViolation.
  3. Setting BLIND_DESIGN_UNLOCK=True bypasses the guard.
  4. Setting BLIND_DESIGN_CUTOFF=None is a complete no-op.
"""

from __future__ import annotations

import importlib
from unittest import mock

import pandas as pd
import pytest

from helpers import blind_design_guard


def _build_df(start: str, end: str) -> pd.DataFrame:
    idx = pd.date_range(start=start, end=end, freq="D", tz="UTC")
    return pd.DataFrame(
        {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1},
        index=idx,
    )


@pytest.fixture
def patched_config(monkeypatch):
    """Yields a function that sets CONFIG cutoff/unlock for one test."""
    from config import CONFIG

    def _apply(cutoff, unlock=False):
        monkeypatch.setitem(CONFIG, "BLIND_DESIGN_CUTOFF", cutoff)
        monkeypatch.setitem(CONFIG, "BLIND_DESIGN_UNLOCK", unlock)

    yield _apply


def test_pre_cutoff_load_succeeds(patched_config):
    patched_config("2023-01-01", unlock=False)

    @blind_design_guard.enforce
    def fetcher(symbol, *_a, **_kw):
        return _build_df("2004-01-01", "2022-12-31")

    out = fetcher("SPY")
    assert out is not None
    assert len(out) > 0
    assert out.index.max() < pd.Timestamp("2023-01-01", tz="UTC")


def test_crossing_cutoff_raises(patched_config):
    patched_config("2023-01-01", unlock=False)

    @blind_design_guard.enforce
    def fetcher(symbol, *_a, **_kw):
        return _build_df("2004-01-01", "2024-12-31")

    with pytest.raises(blind_design_guard.BlindDesignViolation) as exc:
        fetcher("SPY")
    assert "2023-01-01" in str(exc.value)
    assert "SPY" in str(exc.value)


def test_unlock_flag_bypasses(patched_config):
    patched_config("2023-01-01", unlock=True)

    @blind_design_guard.enforce
    def fetcher(symbol, *_a, **_kw):
        return _build_df("2004-01-01", "2024-12-31")

    out = fetcher("SPY")
    assert out is not None
    assert out.index.max() > pd.Timestamp("2023-01-01", tz="UTC")


def test_cutoff_unset_is_noop(patched_config):
    patched_config(None, unlock=False)

    @blind_design_guard.enforce
    def fetcher(symbol, *_a, **_kw):
        return _build_df("2004-01-01", "2024-12-31")

    out = fetcher("SPY")
    assert out is not None
    assert len(out) > 0


def test_none_return_is_safe(patched_config):
    patched_config("2023-01-01", unlock=False)

    @blind_design_guard.enforce
    def fetcher(symbol, *_a, **_kw):
        return None

    assert fetcher("SPY") is None


def test_tz_naive_index_handled(patched_config):
    patched_config("2023-01-01", unlock=False)

    idx = pd.date_range("2004-01-01", "2024-06-30", freq="D")  # tz-naive
    df = pd.DataFrame({"Close": 1.0}, index=idx)

    with pytest.raises(blind_design_guard.BlindDesignViolation):
        blind_design_guard.check(df, source="naive-index-test")


def test_check_function_alone(patched_config):
    """The free function `check` should work without the decorator."""
    patched_config("2023-01-01", unlock=False)
    df_ok = _build_df("2010-01-01", "2022-06-30")
    blind_design_guard.check(df_ok, source="ok-load")  # no raise

    df_bad = _build_df("2010-01-01", "2024-06-30")
    with pytest.raises(blind_design_guard.BlindDesignViolation):
        blind_design_guard.check(df_bad, source="bad-load")
