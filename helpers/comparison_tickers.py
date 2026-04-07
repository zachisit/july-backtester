# helpers/comparison_tickers.py
"""
Comparison ticker configuration parser and validator.

Parses CONFIG["comparison_tickers"] and provides structured data for:
1. Buy & Hold benchmarking (benchmarks)
2. Strategy dependency injection (dependencies)

Public API
----------
parse_comparison_tickers(config) -> dict
    Parse and validate comparison_tickers config.

get_legacy_comparison_tickers() -> list[dict]
    Fallback for backward compatibility when comparison_tickers is not set.

Example Config
--------------
```python
"comparison_tickers": [
    {"symbol": "SPY", "role": "both", "label": "SPY"},
    {"symbol": "QQQ", "role": "benchmark", "label": "QQQ"},
    {"symbol": "I:VIX", "role": "dependency"},  # label defaults to "VIX"
]
```

Roles:
- "benchmark" = calculate B&H return, show "vs. X (B&H)" column
- "dependency" = available for strategy injection via @register_strategy(dependencies=[...])
- "both" = serve both roles

Output Structure
----------------
```python
{
    "benchmarks": [
        {"symbol": "SPY", "label": "SPY"},
        {"symbol": "QQQ", "label": "QQQ"},
    ],
    "dependencies": {
        "spy": "SPY",  # lowercase key -> symbol
        "vix": "I:VIX",
    },
    "all_symbols": ["SPY", "QQQ", "I:VIX"],  # Unique symbols to fetch
    "comparison_tickers": [...],  # Original config for reference
}
```
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_legacy_comparison_tickers() -> list[dict[str, str]]:
    """Return legacy hardcoded comparison tickers for backward compatibility.

    Used when CONFIG["comparison_tickers"] is not set or is empty.

    Returns
    -------
    list[dict]
        Default comparison tickers matching the old hardcoded behavior:
        - SPY: both benchmark and dependency
        - QQQ: benchmark only
        - VIX: dependency only
        - TNX: dependency only (fetched but historically unused)
    """
    return [
        {"symbol": "SPY", "role": "both", "label": "SPY"},
        {"symbol": "QQQ", "role": "benchmark", "label": "QQQ"},
        {"symbol": "I:VIX", "role": "dependency"},  # label will default to "VIX"
        {"symbol": "I:TNX", "role": "dependency"},  # label will default to "TNX"
    ]


def parse_comparison_tickers(config: dict) -> dict[str, Any]:
    """Parse and validate CONFIG["comparison_tickers"].

    Parameters
    ----------
    config : dict
        The CONFIG dictionary from config.py.

    Returns
    -------
    dict
        Parsed structure with keys:
        - "benchmarks": list of {"symbol": str, "label": str} for B&H comparison
        - "dependencies": dict of {lowercase_key: symbol} for strategy injection
        - "all_symbols": list of unique symbols to fetch
        - "comparison_tickers": original config list for reference

    Examples
    --------
    >>> config = {"comparison_tickers": [
    ...     {"symbol": "SPY", "role": "both", "label": "SPY"},
    ...     {"symbol": "I:VIX", "role": "dependency"},
    ... ]}
    >>> result = parse_comparison_tickers(config)
    >>> result["benchmarks"]
    [{"symbol": "SPY", "label": "SPY"}]
    >>> result["dependencies"]
    {"spy": "SPY", "vix": "I:VIX"}
    """
    comparison_tickers = config.get("comparison_tickers")

    if comparison_tickers is None:
        raise ValueError(
            "CONFIG['comparison_tickers'] is not set. "
            "Add it to config.py — for example:\n\n"
            '    "comparison_tickers": [\n'
            '        {"symbol": "SPY",   "role": "both"},\n'
            '        {"symbol": "I:VIX", "role": "dependency"},\n'
            '        {"symbol": "I:TNX", "role": "dependency"},\n'
            "    ]\n\n"
            "Set role='benchmark' to compare B&H returns, "
            "'dependency' to make the ticker available to strategies, "
            "or 'both' for both. "
            "Use [] to run with no comparison tickers."
        )

    # Empty list is explicitly valid — user wants no comparison tickers
    if not comparison_tickers:
        return {"benchmarks": [], "dependencies": {}, "all_symbols": [], "comparison_tickers": []}

    # Parse and validate each ticker entry
    benchmarks = []
    dependencies = {}
    all_symbols = []
    seen_symbols = set()

    for i, entry in enumerate(comparison_tickers):
        # Validate required keys
        if not isinstance(entry, dict):
            logger.warning(
                f"comparison_tickers[{i}] is not a dict — skipping: {entry}"
            )
            continue

        symbol = entry.get("symbol")
        role = entry.get("role")

        if not symbol:
            logger.warning(
                f"comparison_tickers[{i}] missing required 'symbol' key — skipping"
            )
            continue

        if not role:
            logger.warning(
                f"comparison_tickers[{i}] (symbol='{symbol}') missing required 'role' key — skipping"
            )
            continue

        # Validate role
        valid_roles = {"benchmark", "dependency", "both"}
        if role not in valid_roles:
            logger.warning(
                f"comparison_tickers[{i}] (symbol='{symbol}') has invalid role '{role}'. "
                f"Must be one of {valid_roles} — skipping"
            )
            continue

        # Handle duplicate symbols
        if symbol in seen_symbols:
            logger.warning(
                f"comparison_tickers[{i}] (symbol='{symbol}') is a duplicate — "
                f"keeping first occurrence only"
            )
            continue

        seen_symbols.add(symbol)
        all_symbols.append(symbol)

        # Extract label (default to symbol if not provided)
        label = entry.get("label")
        if not label:
            # For index symbols like I:VIX, use the bare name (VIX) as default label
            if symbol.upper().startswith("I:"):
                label = symbol[2:]  # Strip "I:" prefix
            elif symbol.startswith("^"):
                label = symbol[1:]  # Strip "^" prefix
            else:
                label = symbol

        # Add to benchmarks if role is "benchmark" or "both"
        if role in ("benchmark", "both"):
            benchmarks.append({"symbol": symbol, "label": label})

        # Add to dependencies if role is "dependency" or "both"
        if role in ("dependency", "both"):
            # Dependency key is lowercase, stripped of prefixes
            # I:VIX -> "vix", ^VIX -> "vix", SPY -> "spy"
            if symbol.upper().startswith("I:"):
                dep_key = symbol[2:].lower()
            elif symbol.startswith("^"):
                dep_key = symbol[1:].lower()
            else:
                dep_key = symbol.lower()

            # Warn if duplicate dependency key (e.g., both "I:VIX" and "^VIX")
            if dep_key in dependencies:
                logger.warning(
                    f"Dependency key '{dep_key}' already exists (symbol='{dependencies[dep_key]}'). "
                    f"Symbol '{symbol}' will overwrite it."
                )

            dependencies[dep_key] = symbol

    return {
        "benchmarks": benchmarks,
        "dependencies": dependencies,
        "all_symbols": all_symbols,
        "comparison_tickers": comparison_tickers,  # Original config for reference
    }
