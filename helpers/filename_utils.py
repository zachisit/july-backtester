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
    "CONIN$", "CONOUT$",
    *[f"COM{i}" for i in range(1, 10)],
    *[f"LPT{i}" for i in range(1, 10)],
}

# CON and PRN are REAL TICKERS with data in the Norgate corpus
# (CON-199804.parquet, PRN-200207.parquet - both delisted, i.e. exactly the
# survivorship-critical names). That corpus predates this guard and cannot be
# regenerated (the Norgate subscription has lapsed), so every READER must also
# try the unguarded spelling or those symbols silently resolve to None and drop
# out of backtests. Hence `guard_reserved=False` and :func:`filename_candidates`.


def sanitize_symbol_for_filename(symbol: str, *, guard_reserved: bool = True) -> str:
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

    KNOWN RESIDUAL COLLISION
    ------------------------
    The operator substitution is **not escaped**, so a label that already
    contains a literal token collides with the operator it stands for::

        sanitize_symbol_for_filename("ADX_gt_20")  ->  "ADX_gt_20"
        sanitize_symbol_for_filename("ADX>20")     ->  "ADX_gt_20"   # same

    This is deliberately narrower than the defect it replaced, which collapsed
    *every* ``>``/``<`` to ``_`` and so fired on any comparison sweep; this one
    needs a hand-authored label containing the exact substring. Fixing it
    properly requires an escape scheme (e.g. tokens ``~gt~`` with literal ``~``
    doubled), which changes the filename format and renames existing sweep
    outputs — hence tracked separately rather than bundled here. Pinned by
    strict xfails in ``tests/test_filename_utils.py`` so it cannot rot.
    """
    for op, token in _SEMANTIC_OPERATORS:
        symbol = symbol.replace(op, token)
    for ch in _ILLEGAL_CHARS:
        symbol = symbol.replace(ch, "_")
    # Control characters are illegal on Windows and NUL is illegal on POSIX too
    # (open() raises). The old caching.py whitelist scrubbed these; the shared
    # blacklist did not, so this restores that site's guarantee.
    symbol = "".join("_" if ord(c) < 32 else c for c in symbol)
    # Windows silently strips trailing dots and spaces from a name component,
    # so "CON " resolves to the CON device and "ABC." to "ABC" - both defeat
    # the reserved check below and can collide with a neighbouring name.
    symbol = symbol.rstrip(" .")
    if not symbol:
        # Everything scrubbed away. Returning "" yields a hidden ".parquet"
        # with no stem, and every such symbol collides on one file.
        return "_EMPTY_"
    if guard_reserved:
        stem = symbol.split(".")[0].upper()
        if stem in _WINDOWS_RESERVED:
            symbol = "_" + symbol
    return symbol


def filename_candidates(symbol: str) -> list[str]:
    """Every sanitized spelling *symbol* may be stored under, best first.

    READ paths must use this, not :func:`sanitize_symbol_for_filename` alone.

    The Windows reserved-name guard is a **write-side** concern: it stops this
    code creating an unwritable ``NUL.parquet``. But data written before the
    guard existed - notably the frozen Norgate corpus, which holds the real
    delisted tickers ``CON-199804.parquet`` and ``PRN-200207.parquet`` and can
    never be re-exported - uses the unguarded spelling. A reader that only looks
    for ``_CON`` finds nothing, returns ``None``, and the symbol drops out of
    the backtest with a single warning in a run of thousands. Silently losing
    delisted names is precisely the survivorship bias that corpus exists to
    prevent.

    Returns ``[guarded]`` for ordinary symbols (no behaviour change) and
    ``[guarded, legacy]`` only for the handful of reserved-name tickers.
    """
    guarded = sanitize_symbol_for_filename(symbol)
    legacy = sanitize_symbol_for_filename(symbol, guard_reserved=False)
    return [guarded] if guarded == legacy else [guarded, legacy]
