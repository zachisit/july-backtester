"""helpers/filename_utils.py

Shared filename-sanitization logic used by services and scripts.
"""

# Characters illegal in Windows (and generally problematic) filenames.
_ILLEGAL_CHARS = r'\/:*?"<>|'

# Comparison operators map to distinct semantic tokens *before* the generic
# illegal-char scrub, so paired sweep configs (e.g. ``ADX>20`` / ``ADX<20``)
# do not both collapse to ``ADX_20`` and silently overwrite each other's output
# files. Ordered longest-operator-first so ``>=`` becomes ``_gte_`` rather than
# degrading into ``_gt_=``. Both ``<`` and ``>`` are also in _ILLEGAL_CHARS as a
# defensive backstop, but the prepass consumes every occurrence first.
_SEMANTIC_OPERATORS = [
    (">=", "_gte_"),
    ("<=", "_lte_"),
    (">", "_gt_"),
    ("<", "_lt_"),
]

# Windows reserved device names — cannot be used as filenames even with extensions.
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *[f"COM{i}" for i in range(1, 10)],
    *[f"LPT{i}" for i in range(1, 10)],
}


def sanitize_symbol_for_filename(symbol: str) -> str:
    """Return *symbol* safe for use as a filename on Windows and POSIX systems.

    First maps comparison operators to distinct tokens so that comparison
    variants stay distinct filenames — ``>=``→``_gte_``, ``<=``→``_lte_``,
    ``>``→``_gt_``, ``<``→``_lt_`` (applied longest-operator-first). Without
    this, both ``>`` and ``<`` would scrub to ``_`` and paired sweep configs
    like ``ADX>20`` / ``ADX<20`` would collide on one filename, silently
    overwriting each other's results.

    Then replaces each remaining character in ``\\/:*?"|`` with an underscore,
    and prepends ``_`` when the stem (before the first ``.``) matches a Windows
    reserved device name (``CON``, ``NUL``, ``COM1``–``COM9``, etc.) so that
    e.g. ``NUL.parquet`` never appears on disk.

    ``$`` and ``.`` are intentionally left intact — both are valid in filenames
    on all supported platforms and appear in real ticker symbols (``$VIX``,
    ``$I:TNX`` → ``$I_TNX``).
    """
    for op, token in _SEMANTIC_OPERATORS:
        symbol = symbol.replace(op, token)
    for ch in _ILLEGAL_CHARS:
        symbol = symbol.replace(ch, "_")
    stem = symbol.split(".")[0].upper()
    if stem in _WINDOWS_RESERVED:
        symbol = "_" + symbol
    return symbol
