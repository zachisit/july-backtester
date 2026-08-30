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
    # Windows treats the ISO/IEC 8859-1 superscript digits as digits, so
    # COM¹/COM²/COM³ and LPT¹/LPT²/LPT³ are reserved too — `echo test > COM¹`
    # fails to create a file. Documented in "Naming Files, Paths, and
    # Namespaces"; missing here until a QA sweep checked the set against the
    # spec rather than against itself.
    *[f"COM{d}" for d in ("¹", "²", "³")],
    *[f"LPT{d}" for d in ("¹", "²", "³")],
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


def resolve_existing(directory, symbol: str, template: str = "{name}.parquet",
                     case_variants: bool = True):
    """First EXISTING file for *symbol* in *directory*, or ``None``.

    The single read-path entry point. Tries every candidate spelling from
    :func:`filename_candidates` (guarded first, then the legacy unguarded form),
    each in exact / upper / lower case, and returns the first that exists.

    *template* has every ``{name}`` occurrence REPLACED with the spelling (not
    ``str.format`` — any other brace field is left literal), so callers with a richer
    filename than ``SYMBOL.ext`` can use it too::

        resolve_existing(d, "CON")                                  # CON.parquet
        resolve_existing(d, "I:VIX", template="{name}.csv")         # I_VIX.csv
        resolve_existing(d, "CON", template="{name}_2020_D_1.parquet")

    WHY THIS EXISTS RATHER THAN LEAVING CALLERS TO COMPOSE IT
    ---------------------------------------------------------
    :func:`filename_candidates` documented the contract - "READ paths must use
    this" - and three of five read paths did not, because composing the
    candidate x case x extension loop by hand is tedious and
    :func:`sanitize_symbol_for_filename` is right there with the shorter name.

    That is the wrong way round for a contract whose violation is **silent**: a
    reader that checks only the guarded spelling reports "missing" or "not
    cached" for a file that exists, and the affected tickers - ``CON``, ``PRN``
    - are delisted names the survivorship work depends on. The failure never
    raises.

    So the safe call is now the short obvious one, and there is nothing left to
    compose. Anything under ``services/``, ``helpers/`` or ``scripts/`` that
    tests a path for existence should call this instead of building the name.
    """
    import os

    for name in filename_candidates(symbol):
        spellings = [name, name.upper(), name.lower()] if case_variants else [name]
        seen = set()
        for spelling in spellings:
            if spelling in seen:
                continue
            seen.add(spelling)
            # .replace rather than .format: a template carrying any second
            # field -- "{name}_{a}.parquet" -- raised KeyError('a'). Safe today
            # (caching.py interpolates its dates before passing the template),
            # but a needless footgun in a helper whose whole point is to be the
            # obvious safe call. @shardul0701.
            path = os.path.join(str(directory),
                                template.replace("{name}", spelling))
            if os.path.isfile(path):
                return path
    return None
