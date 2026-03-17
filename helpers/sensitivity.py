# helpers/sensitivity.py
"""
Parameter sensitivity sweep utilities.

Builds a grid of param dicts by varying each numeric param in a strategy's
base param dict by ±pct across ±steps steps, then provides labelling helpers
for naming each variant in results output.

Public API
----------
build_param_grid(params, pct, steps, min_val) -> list[dict]
label_for_params(base_params, variant_params) -> str
is_sweep_enabled() -> bool
"""

from __future__ import annotations

import math
from itertools import product
from typing import Any

from config import CONFIG


def build_param_grid(
    params: dict[str, Any],
    pct: float | None = None,
    steps: int | None = None,
    min_val: int | float | None = None,
) -> list[dict]:
    """Return the cartesian product of per-param value ranges.

    Only ``int`` and ``float`` values are varied; strings, bools, and ``None``
    are carried through unchanged in every grid point.

    Parameters
    ----------
    params   : base parameter dict from ``@register_strategy(params={...})``.
    pct      : fractional step size (default: ``sensitivity_sweep_pct`` from CONFIG).
    steps    : number of steps each side of base (default: ``sensitivity_sweep_steps``).
    min_val  : minimum allowed value after rounding (default: ``sensitivity_sweep_min_val``).

    Returns
    -------
    list of dicts — the cartesian product across all numeric params.
    The base dict is always included exactly once.
    Returns ``[params]`` when params is empty or has no numeric keys.
    """
    if pct is None:
        pct = CONFIG.get("sensitivity_sweep_pct", 0.20)
    if steps is None:
        steps = CONFIG.get("sensitivity_sweep_steps", 2)
    if min_val is None:
        min_val = CONFIG.get("sensitivity_sweep_min_val", 2)

    if not params:
        return [params]

    numeric_keys = [
        k for k, v in params.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    ]

    if not numeric_keys:
        return [params]

    # Build value list for each numeric key
    per_key_values: dict[str, list] = {}
    for key in numeric_keys:
        base = params[key]
        is_int = isinstance(base, int)
        raw_vals = [base * (1 + s * pct) for s in range(-steps, steps + 1)]
        if is_int:
            rounded = [max(int(min_val), round(v)) for v in raw_vals]
        else:
            rounded = [max(float(min_val), v) for v in raw_vals]
        # De-duplicate while preserving order
        seen: set = set()
        deduped: list = []
        for v in rounded:
            if v not in seen:
                seen.add(v)
                deduped.append(v)
        per_key_values[key] = deduped

    # Cartesian product
    grid: list[dict] = []
    keys = list(per_key_values.keys())
    for combo in product(*[per_key_values[k] for k in keys]):
        variant = dict(params)
        for k, v in zip(keys, combo):
            variant[k] = v
        grid.append(variant)

    # Ensure base is present exactly once (deduplication may have already included it)
    base_in_grid = any(
        all(g[k] == params[k] for k in numeric_keys) for g in grid
    )
    if not base_in_grid:
        grid.append(dict(params))

    return grid


def label_for_params(base_params: dict[str, Any], variant_params: dict[str, Any]) -> str:
    """Return a short label describing how ``variant_params`` differs from ``base_params``.

    Returns ``"(base)"`` when the two dicts are identical on all keys that
    appear in ``base_params``.  Otherwise returns a space-separated list of
    ``key=val`` pairs for every changed key.
    """
    diffs = {
        k: variant_params[k]
        for k in base_params
        if k in variant_params and variant_params[k] != base_params[k]
    }
    if not diffs:
        return "(base)"
    return " ".join(f"{k}={v}" for k, v in diffs.items())


def is_sweep_enabled() -> bool:
    """Return ``True`` when ``sensitivity_sweep_enabled`` is truthy in CONFIG."""
    return bool(CONFIG.get("sensitivity_sweep_enabled", False))
