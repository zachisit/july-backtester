"""helpers/registry.py

Global strategy registry and @register_strategy decorator for auto-discovery.

A strategy is any module-level function with the signature:

    def my_strategy(df: pd.DataFrame, **kwargs) -> pd.DataFrame:
        ...

The function must add a ``Signal`` column to df before returning it:
  1  = enter / hold long
 -1  = exit / flat
  0  = no change (carry previous signal)

Public API
----------
register_strategy(name, dependencies, params) -> decorator
load_strategies(directory) -> int   (number of modules loaded)
REGISTRY  -> StrategyRegistry       (dict-like view, read-only)
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from typing import Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal backing store
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, dict] = {}


class StrategyRegistry:
    """Read-only dict-like view over all registered strategies.

    Each entry has the shape expected by ``main.py::run_single_simulation``::

        {
            "logic"       : Callable[(df, **kwargs) -> df],
            "dependencies": list[str],   # e.g. ["spy", "vix"]
            "params"      : dict,        # static kwargs merged at runtime
        }

    The interface mirrors a plain ``dict`` so that code written against
    ``STRATEGIES: dict`` continues to work unchanged.
    """

    def __getitem__(self, key: str) -> dict:
        return _REGISTRY[key]

    def __len__(self) -> int:
        return len(_REGISTRY)

    def __iter__(self):
        return iter(_REGISTRY)

    def __contains__(self, key: str) -> bool:
        return key in _REGISTRY

    def __repr__(self) -> str:
        return f"StrategyRegistry({list(_REGISTRY.keys())})"

    def items(self):
        return _REGISTRY.items()

    def keys(self):
        return _REGISTRY.keys()

    def values(self):
        return _REGISTRY.values()

    def get(self, key: str, default=None):
        return _REGISTRY.get(key, default)


#: Singleton registry instance — import and use this directly.
REGISTRY: StrategyRegistry = StrategyRegistry()


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

# Strategy kinds. "signal" is the classic per-symbol plugin (returns a Signal
# column); "rotation" is a cross-sectional ranking plugin (see helpers/rotation.py).
SIGNAL = "signal"
ROTATION = "rotation"


def register_strategy(
    name: str,
    dependencies: list[str] | None = None,
    params: dict | None = None,
    kind: str = SIGNAL,
    regime_gate: Callable | None = None,
) -> Callable:
    """Decorator that registers a strategy function in the global registry.

    The decorated function **must** accept ``(df, **kwargs)`` and return the
    DataFrame with a ``Signal`` column added.

    Injected kwargs
    ---------------
    The engine always injects ``kwargs["symbol"]`` — the ticker string for the
    DataFrame currently being processed (e.g. ``"AAPL"``) — before calling the
    logic function. This lets per-symbol / event-driven strategies (for example
    one keyed on a per-ticker earnings-date table) identify which symbol they
    are evaluating. Strategies that do not need it simply ignore the extra key.

    Parameters
    ----------
    name : str
        Display name shown in terminal reports and CSV output.
    dependencies : list[str], optional
        External dataframes required at runtime.  Supported values:
        ``"spy"``, ``"vix"``.  main.py injects these into **kwargs before
        calling the logic function.
    params : dict, optional
        Static parameters stored alongside the strategy.  main.py merges
        these into **kwargs before calling the logic function so the function
        can access them via ``kwargs["key"]``.
    kind : str, optional
        ``"signal"`` (default) for the classic per-symbol plugin, or
        ``"rotation"`` for a cross-sectional ranking plugin consumed by
        :mod:`helpers.rotation`. The default keeps every existing plugin a
        signal strategy with no change. Prefer the :func:`register_rotation`
        sibling decorator for rotation plugins.
    regime_gate : Callable, optional
        Rotation-only. ``regime_gate(data, rebalance_date) -> bool`` — when it
        returns ``False`` the rotation liquidates to cash for that rebalance.
        Ignored for signal strategies.

    Examples
    --------
    ::

        from helpers.registry import register_strategy
        from helpers.timeframe_utils import get_bars_for_period
        from helpers.indicators import sma_crossover_logic
        from config import CONFIG

        _TF  = CONFIG.get("timeframe", "D")
        _MUL = CONFIG.get("timeframe_multiplier", 1)

        @register_strategy(
            name="SMA Crossover (20d/50d)",
            dependencies=[],
            params={
                "fast": get_bars_for_period("20d", _TF, _MUL),
                "slow": get_bars_for_period("50d", _TF, _MUL),
            },
        )
        def sma_crossover_20_50(df, **kwargs):
            return sma_crossover_logic(df, fast=kwargs["fast"], slow=kwargs["slow"])
    """
    if dependencies is None:
        dependencies = []
    if params is None:
        params = {}

    def decorator(fn: Callable) -> Callable:
        _REGISTRY[name] = {
            "logic":        fn,
            "dependencies": list(dependencies),
            "params":       dict(params),
            "kind":         kind,
            "regime_gate":  regime_gate,
        }
        return fn

    return decorator


def register_rotation(
    name: str,
    dependencies: list[str] | None = None,
    params: dict | None = None,
    regime_gate: Callable | None = None,
) -> Callable:
    """Register a cross-sectional **rotation** ranking plugin (issue #294).

    The decorated function is a *ranking* function, not a per-symbol signal
    function::

        rank_fn(data: dict[str, pd.DataFrame], rebalance_date, **params) -> ranking

    where ``ranking`` is an ordered list of symbols (best first) or a
    ``{symbol: score}`` dict / Series. The framework (``helpers/rotation.py``)
    owns top-N selection, weighting, rebalance / trim / add mechanics, sizing and
    all cost / accounting — the plugin supplies only the alpha.

    This is thin sugar over :func:`register_strategy` with ``kind="rotation"``.

    Examples
    --------
    ::

        from helpers.registry import register_rotation

        @register_rotation(name="Momentum Rotation (90d)", params={"lookback": 90})
        def momentum_rank(data, rebalance_date, lookback=90, **kwargs):
            scores = {}
            for sym, df in data.items():
                window = df.loc[:rebalance_date]
                if len(window) > lookback:
                    scores[sym] = window["Close"].iloc[-1] / window["Close"].iloc[-lookback] - 1
            return scores
    """
    return register_strategy(
        name=name,
        dependencies=dependencies,
        params=params,
        kind=ROTATION,
        regime_gate=regime_gate,
    )


# ---------------------------------------------------------------------------
# Auto-discovery loader
# ---------------------------------------------------------------------------

def load_strategies(directory: str) -> int:
    """Dynamically import every ``*.py`` file in *directory*.

    Importing each module triggers the ``@register_strategy`` decorators it
    contains, which populate :data:`REGISTRY`.  Files whose names start with
    ``_`` (e.g. ``__init__.py``) are skipped.

    The function is idempotent: modules already present in ``sys.modules``
    are counted but not re-executed.

    Parameters
    ----------
    directory : str
        Path to the folder containing strategy modules.  May be absolute or
        relative to the current working directory.

    Returns
    -------
    int
        Number of modules loaded (including previously-cached ones).

    Raises
    ------
    ImportError
        If a module file exists but raises an exception when executed.
    """
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        return 0

    # Ensure the *parent* directory is on sys.path so that
    #   ``import <pkg_name>.<module>`` resolves correctly in worker processes.
    parent = os.path.dirname(directory)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    pkg_name = os.path.basename(directory)
    loaded = 0

    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".py") or filename.startswith("_"):
            continue

        module_name = f"{pkg_name}.{filename[:-3]}"  # e.g. custom_strategies.sma_crossovers

        # Already imported — count it, don't re-execute.
        if module_name in sys.modules:
            loaded += 1
            continue

        module_path = os.path.join(directory, filename)
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            continue

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(module_name, None)
            _is_private = os.path.basename(os.path.abspath(directory)) == "private"
            if _is_private:
                import logging as _logging
                _logging.getLogger(__name__).warning(
                    "load_strategies: skipping private module '%s': %s — "
                    "check private submodule state or run "
                    "'git submodule update --init'.",
                    module_path, exc,
                )
            else:
                raise ImportError(
                    f"load_strategies: failed to import '{module_path}': {exc}"
                ) from exc

        loaded += 1

    return loaded


def get_active_strategies(directory: str = "custom_strategies") -> dict:
    """Return the active strategies as a plain ``{name: config}`` dict.

    Calls :func:`load_strategies` on *directory* first so that any plugin
    files not yet imported are discovered and their ``@register_strategy``
    decorators fire.  Subsequent calls are fast because modules already in
    ``sys.modules`` are skipped by :func:`load_strategies`.

    **Private strategies submodule**: If ``custom_strategies/private/`` exists
    (the private strategies git submodule), it will also be scanned automatically.
    This allows interns to keep proprietary strategies in a separate private repo.

    The returned set is then filtered by ``CONFIG["strategies"]``:

    * ``"all"`` (or ``None``) — returns every registered strategy.
    * A list of strings — returns only the named strategies.  Any name not
      found in the registry is logged as a ``WARNING`` and skipped; a typo
      will not cause a crash.

    Parameters
    ----------
    directory : str
        Plugin directory to scan.  Defaults to ``"custom_strategies"``
        relative to the current working directory.

    Returns
    -------
    dict
        Filtered copy of the registry: ``{strategy_name: config_dict}``.
        Each value has the shape ``{"logic": callable, "dependencies": list,
        "params": dict}`` — identical to the old ``STRATEGIES`` dict format.
    """
    # Load public strategies
    load_strategies(directory)

    # Load private strategies if submodule exists
    private_dir = os.path.join(directory, "private")
    if os.path.isdir(private_dir):
        load_strategies(private_dir)

    # Signal-kind only: the legacy per-symbol pipeline (main.py) must never be
    # handed a rotation plugin (different call signature). Rotation plugins are
    # accessed via get_rotation_strategies(). Entries default to kind="signal",
    # so every pre-#294 plugin is included exactly as before.
    signal_registry = {
        n: e for n, e in _REGISTRY.items() if e.get("kind", SIGNAL) == SIGNAL
    }

    # Lazy import avoids a circular dependency at module load time
    # (config.py does not import from helpers/).
    from config import CONFIG  # noqa: PLC0415
    selection = CONFIG.get("strategies", "all")

    if selection == "all" or selection is None:
        return dict(signal_registry)

    # --- Filtered mode ---
    if not isinstance(selection, list):
        logger.warning(
            "[WARNING] CONFIG['strategies'] must be 'all' or a list of names. "
            "Got %r — falling back to 'all'.",
            selection,
        )
        return dict(signal_registry)

    result = {}
    for name in selection:
        if name in signal_registry:
            result[name] = signal_registry[name]
        else:
            logger.warning(
                "[WARNING] Strategy '%s' requested in config but no matching "
                "plugin was found. Check the name matches the @register_strategy "
                "decorator exactly (case-sensitive).",
                name,
            )
    return result


def get_rotation_strategies(directory: str = "custom_strategies") -> dict:
    """Return the registered **rotation** plugins as ``{name: config_dict}``.

    Mirrors :func:`get_active_strategies` (loads *directory* + a ``private/``
    submodule if present) but returns only ``kind == "rotation"`` entries. Each
    value has the shape ``{"logic": rank_fn, "dependencies": list, "params":
    dict, "kind": "rotation", "regime_gate": callable | None}``.

    Not filtered by ``CONFIG["strategies"]`` — rotation selection is driven by
    ``CONFIG["rotation"]["rank_strategy"]`` instead.
    """
    load_strategies(directory)
    private_dir = os.path.join(directory, "private")
    if os.path.isdir(private_dir):
        load_strategies(private_dir)

    return {
        n: e for n, e in _REGISTRY.items() if e.get("kind", SIGNAL) == ROTATION
    }
