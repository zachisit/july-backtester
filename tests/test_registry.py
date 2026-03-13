"""
tests/test_registry.py

Unit tests for helpers/registry.py — Strategy Registry and Plugin System.

Covers:
  register_strategy    — decorator API: stores logic, name, dependencies, params
  StrategyRegistry     — dict-like interface (len, iter, contains, get, items…)
  load_strategies      — dynamic auto-discovery from a directory of .py files
  get_active_strategies — public API used by main.py
  integration          — custom_strategies/ loads correctly end-to-end

All tests are deterministic: no network calls, no I/O beyond tmp_path.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.registry import (
    REGISTRY,
    _REGISTRY,
    get_active_strategies,
    load_strategies,
    register_strategy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_registry():
    """Save/restore the backing store around every test to avoid pollution."""
    saved = dict(_REGISTRY)
    yield
    _REGISTRY.clear()
    _REGISTRY.update(saved)


def _dummy_logic(df, **kwargs):
    df["Signal"] = 1
    return df


# ---------------------------------------------------------------------------
# TestRegisterStrategyDecorator
# ---------------------------------------------------------------------------

class TestRegisterStrategyDecorator:

    def test_stores_function_in_registry(self):
        @register_strategy(name="Test Strategy A", dependencies=[], params={})
        def _strat(df, **kwargs):
            return df

        assert "Test Strategy A" in REGISTRY
        assert REGISTRY["Test Strategy A"]["logic"] is _strat

    def test_stores_dependencies(self):
        @register_strategy(name="Test Strategy B", dependencies=["spy", "vix"])
        def _strat(df, **kwargs):
            return df

        assert REGISTRY["Test Strategy B"]["dependencies"] == ["spy", "vix"]

    def test_stores_params(self):
        @register_strategy(name="Test Strategy C", params={"fast": 20, "slow": 50})
        def _strat(df, **kwargs):
            return df

        assert REGISTRY["Test Strategy C"]["params"] == {"fast": 20, "slow": 50}

    def test_defaults_when_omitted(self):
        """dependencies and params default to [] and {} when not supplied."""
        @register_strategy(name="Test Strategy D")
        def _strat(df, **kwargs):
            return df

        entry = REGISTRY["Test Strategy D"]
        assert entry["dependencies"] == []
        assert entry["params"] == {}

    def test_decorated_function_still_callable(self):
        """The decorator must return the original function unchanged."""
        @register_strategy(name="Test Strategy E")
        def _strat(df, **kwargs):
            df["Signal"] = 99
            return df

        df = pd.DataFrame({"Close": [1.0, 2.0]})
        result = _strat(df)
        assert list(result["Signal"]) == [99, 99]

    def test_overwrite_same_name(self):
        """Registering under the same name replaces the previous entry."""
        @register_strategy(name="Test Strategy F")
        def _v1(df, **kwargs):
            return df

        @register_strategy(name="Test Strategy F")
        def _v2(df, **kwargs):
            return df

        assert REGISTRY["Test Strategy F"]["logic"] is _v2

    def test_dependencies_list_is_copied(self):
        """Mutating the original list must not affect the stored entry."""
        deps = ["spy"]
        @register_strategy(name="Test Strategy G", dependencies=deps)
        def _strat(df, **kwargs):
            return df

        deps.append("vix")
        assert REGISTRY["Test Strategy G"]["dependencies"] == ["spy"]

    def test_params_dict_is_copied(self):
        """Mutating the original dict must not affect the stored entry."""
        p = {"fast": 10}
        @register_strategy(name="Test Strategy H", params=p)
        def _strat(df, **kwargs):
            return df

        p["slow"] = 50
        assert "slow" not in REGISTRY["Test Strategy H"]["params"]


# ---------------------------------------------------------------------------
# TestStrategyRegistryInterface
# ---------------------------------------------------------------------------

class TestStrategyRegistryInterface:

    @pytest.fixture(autouse=True)
    def _populate(self):
        """Register two strategies for interface tests."""
        @register_strategy(name="Iface A", dependencies=["spy"])
        def _a(df, **kw): return df

        @register_strategy(name="Iface B", dependencies=[])
        def _b(df, **kw): return df

    def test_len(self):
        assert len(REGISTRY) >= 2

    def test_contains(self):
        assert "Iface A" in REGISTRY
        assert "Iface B" in REGISTRY
        assert "Nonexistent" not in REGISTRY

    def test_getitem(self):
        entry = REGISTRY["Iface A"]
        assert "logic" in entry
        assert "dependencies" in entry

    def test_getitem_missing_raises_key_error(self):
        with pytest.raises(KeyError):
            _ = REGISTRY["Does Not Exist"]

    def test_get_returns_default(self):
        assert REGISTRY.get("Does Not Exist", "fallback") == "fallback"

    def test_iter_yields_names(self):
        names = list(REGISTRY)
        assert "Iface A" in names
        assert "Iface B" in names

    def test_keys(self):
        assert "Iface A" in REGISTRY.keys()

    def test_values(self):
        for v in REGISTRY.values():
            assert "logic" in v
            assert "dependencies" in v
            assert "params" in v

    def test_items(self):
        for name, entry in REGISTRY.items():
            assert isinstance(name, str)
            assert isinstance(entry, dict)


# ---------------------------------------------------------------------------
# TestLoadStrategies
# ---------------------------------------------------------------------------

class TestLoadStrategies:

    def _write_strategy_file(self, directory: str, filename: str, strategy_name: str):
        """Write a minimal strategy .py file into *directory*."""
        content = (
            "import sys, os\n"
            "sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))\n"
            "from helpers.registry import register_strategy\n\n"
            f"@register_strategy(name={strategy_name!r}, dependencies=[], params={{'value': 42}})\n"
            "def _strategy(df, **kwargs):\n"
            "    return df\n"
        )
        path = os.path.join(directory, filename)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_nonexistent_directory_returns_zero(self):
        assert load_strategies("/nonexistent/path/xyz") == 0

    def test_loads_single_file(self, tmp_path):
        pkg_dir = tmp_path / "strat_pkg_single"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        self._write_strategy_file(str(pkg_dir), "dummy.py", "Dummy Loaded Strategy")

        count = load_strategies(str(pkg_dir))

        assert count == 1
        assert "Dummy Loaded Strategy" in REGISTRY

    def test_loaded_params_stored_correctly(self, tmp_path):
        pkg_dir = tmp_path / "strat_pkg_params"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        self._write_strategy_file(str(pkg_dir), "paramstrat.py", "Param Strategy")

        load_strategies(str(pkg_dir))

        assert REGISTRY["Param Strategy"]["params"] == {"value": 42}

    def test_skips_underscore_files(self, tmp_path):
        pkg_dir = tmp_path / "strat_pkg_skip"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        # Write a file starting with _ — should be skipped
        (pkg_dir / "_private.py").write_text(
            "import sys, os\n"
            "sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(os.path.abspath('.')), '')))\n"
            "from helpers.registry import register_strategy\n\n"
            "@register_strategy(name='Should Not Appear', dependencies=[])\n"
            "def _s(df, **kw): return df\n"
        )
        # Ensure a real strategy file is also present
        self._write_strategy_file(str(pkg_dir), "visible.py", "Visible Strategy")

        load_strategies(str(pkg_dir))

        assert "Should Not Appear" not in REGISTRY
        assert "Visible Strategy" in REGISTRY

    def test_loads_multiple_files(self, tmp_path):
        pkg_dir = tmp_path / "strat_pkg_multi"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        self._write_strategy_file(str(pkg_dir), "alpha.py", "Multi Alpha")
        self._write_strategy_file(str(pkg_dir), "beta.py", "Multi Beta")

        count = load_strategies(str(pkg_dir))

        assert count == 2
        assert "Multi Alpha" in REGISTRY
        assert "Multi Beta" in REGISTRY

    def test_idempotent_on_second_call(self, tmp_path):
        """Calling load_strategies twice must not raise or duplicate entries."""
        pkg_dir = tmp_path / "strat_pkg_idem"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")
        self._write_strategy_file(str(pkg_dir), "idem.py", "Idempotent Strategy")

        load_strategies(str(pkg_dir))
        count2 = load_strategies(str(pkg_dir))

        assert count2 == 1  # already in sys.modules
        assert "Idempotent Strategy" in REGISTRY


# ---------------------------------------------------------------------------
# TestIntegration — real custom_strategies/ package
# ---------------------------------------------------------------------------

class TestIntegration:
    """Verify that the real custom_strategies/ package loads correctly via
    get_active_strategies().

    This class overrides the module-level _clean_registry autouse fixture.
    Before each test it removes custom_strategies.* from sys.modules so that
    load_strategies() (called inside get_active_strategies) always re-imports
    them fresh and re-triggers the @register_strategy decorators — even though
    the module-level fixture may have cleared _REGISTRY after a previous test.
    """

    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        """Override the module-level autouse fixture for integration tests.

        Also saves/restores CONFIG['strategies'] so tests are independent of
        whatever filter value the user currently has in config.py.
        """
        from config import CONFIG
        _saved_strategies = CONFIG.get("strategies", "all")
        CONFIG["strategies"] = "all"

        # Force-evict custom_strategies modules so they are re-imported fresh.
        for key in list(sys.modules.keys()):
            if key.startswith("custom_strategies."):
                del sys.modules[key]
        yield
        _REGISTRY.clear()
        CONFIG["strategies"] = _saved_strategies

    def test_sma_strategies_are_registered(self):
        """get_active_strategies() must discover and return both SMA strategies."""
        strategies = get_active_strategies()

        assert "SMA Crossover (20d/50d)" in strategies
        assert "SMA Crossover (50d/200d)" in strategies

    def test_registry_also_populated(self):
        """After get_active_strategies(), REGISTRY reflects the loaded plugins."""
        get_active_strategies()

        assert "SMA Crossover (20d/50d)" in REGISTRY
        assert "SMA Crossover (50d/200d)" in REGISTRY

    def test_sma_logic_is_callable(self):
        strategies = get_active_strategies()

        for name in ["SMA Crossover (20d/50d)", "SMA Crossover (50d/200d)"]:
            assert callable(strategies[name]["logic"])

    def test_sma_dependencies_are_empty(self):
        strategies = get_active_strategies()

        for name in ["SMA Crossover (20d/50d)", "SMA Crossover (50d/200d)"]:
            assert strategies[name]["dependencies"] == []

    def test_sma_params_have_fast_and_slow(self):
        strategies = get_active_strategies()

        for name in ["SMA Crossover (20d/50d)", "SMA Crossover (50d/200d)"]:
            params = strategies[name]["params"]
            assert "fast" in params
            assert "slow" in params
            assert isinstance(params["fast"], int)
            assert isinstance(params["slow"], int)
            assert params["fast"] < params["slow"]

    def test_sma_logic_produces_signal_column(self):
        """End-to-end: the registered logic callable must add a Signal column."""
        strategies = get_active_strategies()

        # Build a minimal OHLCV DataFrame long enough for a 200-bar SMA
        n = 250
        df = pd.DataFrame(
            {
                "Open":   np.linspace(100, 120, n),
                "High":   np.linspace(101, 121, n),
                "Low":    np.linspace(99, 119, n),
                "Close":  np.linspace(100, 120, n),
                "Volume": [1_000_000] * n,
            }
        )
        entry = strategies["SMA Crossover (50d/200d)"]
        result = entry["logic"](df.copy(), **entry["params"])

        assert "Signal" in result.columns
        assert result["Signal"].isin([-1, 0, 1]).all()

    def test_returns_plain_dict(self):
        """get_active_strategies() must return a plain dict, not StrategyRegistry."""
        result = get_active_strategies()
        assert type(result) is dict  # noqa: E721

    def test_returns_expected_strategy_count(self):
        """custom_strategies/ ships with the full strategy library (35 on daily timeframe)."""
        strategies = get_active_strategies()
        # 2 SMA + 3 RSI + 6 MACD/EMA + 24 mean-reversion = 35 on daily timeframe.
        # Sub-daily strategies (scalping) are gated by _TF == "MIN" and excluded on "D".
        assert len(strategies) >= 35
