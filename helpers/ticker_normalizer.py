# helpers/ticker_normalizer.py
"""
Provider-agnostic ticker normalization service.

Converts between provider-specific index symbol formats (e.g., I:VIX, ^VIX, $VIX)
to enable consistent ticker handling across data providers.

**Index Symbol Formats by Provider:**
- **Yahoo Finance**: Uses `^` prefix (e.g., `^VIX`, `^GSPC`)
- **Polygon**: Uses `I:` or `$I:` prefix (e.g., `I:VIX`, `$I:VIX`)
- **Norgate**: Uses `$` prefix (e.g., `$VIX`, `$SPX`) — native Norgate Data format
- **CSV / Parquet**: Uses bare symbol (e.g., `VIX`, `SPX`)

**Equity tickers** (AAPL, MSFT, SPY, etc.) pass through unchanged across all providers.

Public API
----------
normalize_ticker(symbol, provider) -> str
    Convert any ticker format to the provider's expected format.

is_index_ticker(symbol) -> bool
    Detect whether a symbol represents an index (not an equity).

Example
-------
>>> normalize_ticker("I:VIX", "yahoo")
'^VIX'
>>> normalize_ticker("^VIX", "polygon")
'I:VIX'
>>> normalize_ticker("AAPL", "yahoo")
'AAPL'  # Equity tickers unchanged
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical Index Mappings
# ---------------------------------------------------------------------------
# Maps canonical index names (uppercase, no prefix) to provider-specific formats.
# Unknown indices fall back to the provider's standard prefix pattern.

CANONICAL_INDEX_MAP: dict[str, dict[str, str]] = {
    # Volatility Indices
    "VIX": {
        "yahoo":   "^VIX",     # CBOE Volatility Index
        "polygon": "I:VIX",
        "norgate": "$VIX",     # Norgate native: $ prefix
        "csv":     "VIX",
    },
    "VXN": {
        "yahoo":   "^VXN",     # Nasdaq Volatility Index
        "polygon": "I:VXN",
        "norgate": "$VXN",
        "csv":     "VXN",
    },

    # Interest Rate Indices (Treasury Yields)
    # Note: TNX, TYX, FVX, IRX are Yahoo/Polygon concepts — not available in Norgate.
    # Norgate entries are best-guess $ format; calls will return no data.
    "TNX": {
        "yahoo":   "^TNX",     # 10-Year Treasury Yield
        "polygon": "I:TNX",
        "norgate": "$TNX",
        "csv":     "TNX",
    },
    "TYX": {
        "yahoo":   "^TYX",     # 30-Year Treasury Yield
        "polygon": "I:TYX",
        "norgate": "$TYX",
        "csv":     "TYX",
    },
    "FVX": {
        "yahoo":   "^FVX",     # 5-Year Treasury Yield
        "polygon": "I:FVX",
        "norgate": "$FVX",
        "csv":     "FVX",
    },
    "IRX": {
        "yahoo":   "^IRX",     # 13-Week Treasury Bill
        "polygon": "I:IRX",
        "norgate": "$IRX",
        "csv":     "IRX",
    },

    # Broad Market Indices
    "SPX": {
        "yahoo":   "^GSPC",    # S&P 500 (Yahoo uses GSPC ticker)
        "polygon": "I:SPX",
        "norgate": "$SPX",
        "csv":     "SPX",
    },
    "NDX": {
        "yahoo":   "^NDX",     # Nasdaq 100
        "polygon": "I:NDX",
        "norgate": "$NDX",
        "csv":     "NDX",
    },
    "DJI": {
        "yahoo":   "^DJI",     # Dow Jones Industrial Average
        "polygon": "I:DJI",
        "norgate": "$DJI",
        "csv":     "DJI",
    },
    "RUT": {
        "yahoo":   "^RUT",     # Russell 2000
        "polygon": "I:RUT",
        "norgate": "$RUT",
        "csv":     "RUT",
    },
    "NYA": {
        "yahoo":   "^NYA",     # NYSE Composite
        "polygon": "I:NYA",
        "norgate": "$NYA",
        "csv":     "NYA",
    },

    # Currency / Commodities
    "DXY": {
        "yahoo":   "DX-Y.NYB", # US Dollar Index (ICE) - special Yahoo format
        "polygon": "I:DXY",
        "norgate": "$DXY",
        "csv":     "DXY",
    },
}

# Reverse lookup map: provider-specific symbol → canonical name
# Built dynamically from CANONICAL_INDEX_MAP to handle special Yahoo formats like ^GSPC, DX-Y.NYB
_REVERSE_MAP: dict[str, str] | None = None

def _build_reverse_map() -> dict[str, str]:
    """Build reverse lookup map: provider symbol → canonical name.

    Enables recognition of special provider formats (e.g., ^GSPC → SPX, DX-Y.NYB → DXY).
    """
    reverse = {}
    for canonical, providers in CANONICAL_INDEX_MAP.items():
        for provider_symbol in providers.values():
            # Store uppercase for case-insensitive lookup
            reverse[provider_symbol.upper()] = canonical
    return reverse

def _get_reverse_map() -> dict[str, str]:
    """Lazy-load reverse map."""
    global _REVERSE_MAP
    if _REVERSE_MAP is None:
        _REVERSE_MAP = _build_reverse_map()
    return _REVERSE_MAP


def _extract_canonical_name(symbol: str) -> tuple[str | None, str]:
    """Extract the canonical index name from a symbol in any provider format.

    Returns
    -------
    (canonical_name, original_format) or (None, original_symbol) if not an index.

    Examples
    --------
    >>> _extract_canonical_name("I:VIX")
    ('VIX', 'polygon')
    >>> _extract_canonical_name("^VIX")
    ('VIX', 'yahoo')
    >>> _extract_canonical_name("$I:VIX")
    ('VIX', 'polygon')
    >>> _extract_canonical_name("^GSPC")
    ('SPX', 'yahoo')
    >>> _extract_canonical_name("DX-Y.NYB")
    ('DXY', 'yahoo')
    >>> _extract_canonical_name("AAPL")
    (None, 'AAPL')
    """
    s = symbol.strip()
    reverse_map = _get_reverse_map()

    # Strip leading "$" — two cases:
    # - Polygon extended format: "$I:VIX" → strip to "I:VIX" (still Polygon)
    # - Norgate native format:   "$VIX"   → canonical "VIX", format "norgate"
    if s.startswith("$"):
        s_stripped = s[1:]
        if s_stripped.upper().startswith("I:"):
            # "$I:VIX" — Polygon extended, strip and continue
            s = s_stripped
        else:
            # "$VIX" — Norgate native dollar-prefix format
            canonical = s_stripped.upper()
            if canonical in CANONICAL_INDEX_MAP:
                return canonical, "norgate"
            # Unknown $-prefixed symbol — treat as norgate index
            return canonical, "norgate"

    # Check reverse map first for exact matches (handles special formats like ^GSPC, DX-Y.NYB)
    if s.upper() in reverse_map:
        canonical = reverse_map[s.upper()]
        # Determine format based on the symbol pattern
        if s.upper().startswith("I:"):
            return canonical, "polygon"
        elif s.startswith("^") or "-" in s or "." in s:
            return canonical, "yahoo"
        else:
            return canonical, "csv"

    # Polygon/Norgate format: "I:VIX" or "i:vix"
    if s.upper().startswith("I:"):
        canonical = s[2:].upper()
        return canonical, "polygon"

    # Yahoo format: "^VIX" or "^vix" (but check if it's a special case first)
    if s.startswith("^"):
        canonical = s[1:].upper()
        # Check if ^CANONICAL is the same as the canonical name (e.g., ^VIX → VIX)
        # or if it needs reverse lookup (e.g., ^GSPC → SPX)
        if canonical in CANONICAL_INDEX_MAP:
            return canonical, "yahoo"
        # Not in canonical map directly - might be equity with ^ prefix (rare)
        return canonical, "yahoo"

    # Check if the bare symbol (uppercase) is in our canonical map
    # This handles CSV format and helps detect known indices without prefix
    if s.upper() in CANONICAL_INDEX_MAP:
        return s.upper(), "csv"

    # Not an index — likely an equity ticker
    return None, s


def normalize_ticker(symbol: str, provider: str) -> str:
    """Convert a ticker symbol to the specified provider's expected format.

    **For index symbols**, converts between provider formats using CANONICAL_INDEX_MAP.
    **For equity tickers** (AAPL, MSFT, SPY, etc.), returns the symbol unchanged.

    Parameters
    ----------
    symbol : str
        Ticker in any format: "I:VIX", "^VIX", "$I:VIX", "VIX", "AAPL", etc.
    provider : str
        Target provider: "yahoo", "polygon", "norgate", or "csv".

    Returns
    -------
    str
        Symbol in the provider's format. Unknown indices fall back to the
        provider's standard prefix (e.g., "I:XYZ" → "^XYZ" for Yahoo).

    Examples
    --------
    >>> normalize_ticker("I:VIX", "yahoo")
    '^VIX'
    >>> normalize_ticker("^VIX", "polygon")
    'I:VIX'
    >>> normalize_ticker("$I:VIX", "csv")
    'VIX'
    >>> normalize_ticker("AAPL", "yahoo")
    'AAPL'
    >>> normalize_ticker("I:XYZ", "yahoo")
    '^XYZ'  # Unknown index — fallback
    """
    provider = provider.lower()
    # Parquet files use bare symbol names (VIX.parquet, TNX.parquet) — same as CSV.
    if provider == "parquet":
        provider = "csv"
    canonical_name, original_format = _extract_canonical_name(symbol)

    # Not an index — equity ticker, pass through unchanged
    if canonical_name is None:
        return symbol

    # Known index — lookup in canonical map
    if canonical_name in CANONICAL_INDEX_MAP:
        provider_symbol = CANONICAL_INDEX_MAP[canonical_name].get(provider)
        if provider_symbol:
            if provider_symbol != symbol:
                logger.debug(
                    f"Normalized '{symbol}' → '{provider_symbol}' for provider '{provider}'"
                )
            return provider_symbol

    # Unknown index — apply fallback prefix pattern
    if provider == "yahoo":
        fallback = f"^{canonical_name}"
    elif provider == "polygon":
        fallback = f"I:{canonical_name}"
    elif provider == "norgate":
        fallback = f"${canonical_name}"
    elif provider == "csv":
        fallback = canonical_name
    else:
        # Unknown provider — return symbol unchanged with warning
        logger.warning(
            f"Unknown data provider '{provider}' for ticker normalization. "
            f"Supported providers: yahoo, polygon, norgate, csv. Returning symbol unchanged."
        )
        return symbol

    logger.debug(
        f"Unknown index '{canonical_name}' — using fallback '{fallback}' for provider '{provider}'"
    )
    return fallback


def is_index_ticker(symbol: str) -> bool:
    """Detect whether a symbol represents an index (not an equity).

    Returns ``True`` if the symbol:
    - Has an index prefix (``I:``, ``^``, ``$I:``)
    - OR is a known canonical index name in CANONICAL_INDEX_MAP

    Returns ``False`` for equity tickers like AAPL, MSFT, SPY.

    Parameters
    ----------
    symbol : str
        Ticker in any format.

    Returns
    -------
    bool
        ``True`` if the symbol is an index, ``False`` otherwise.

    Examples
    --------
    >>> is_index_ticker("I:VIX")
    True
    >>> is_index_ticker("^VIX")
    True
    >>> is_index_ticker("VIX")
    True  # Known canonical name
    >>> is_index_ticker("AAPL")
    False
    >>> is_index_ticker("SPY")
    False  # ETF, not index
    """
    canonical_name, _ = _extract_canonical_name(symbol)
    return canonical_name is not None
