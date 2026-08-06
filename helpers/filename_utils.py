"""helpers/filename_utils.py

Shared filename-sanitization logic used by services and scripts.
"""

# Characters illegal in Windows (and generally problematic) filenames.
_ILLEGAL_CHARS = r'\/:*?"<>|'

# Windows reserved device names — cannot be used as filenames even with extensions.
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *[f"COM{i}" for i in range(1, 10)],
    *[f"LPT{i}" for i in range(1, 10)],
}


def sanitize_symbol_for_filename(symbol: str) -> str:
    """Return *symbol* safe for use as a filename on Windows and POSIX systems.

    Replaces each character in ``\\/:*?"<>|`` with an underscore. Also
    prepends ``_`` when the stem (before the first ``.``) matches a Windows
    reserved device name (``CON``, ``NUL``, ``COM1``–``COM9``, etc.) so that
    e.g. ``NUL.parquet`` never appears on disk.

    ``$`` and ``.`` are intentionally left intact — both are valid in filenames
    on all supported platforms and appear in real ticker symbols (``$VIX``,
    ``$I:TNX`` → ``$I_TNX``).
    """
    for ch in _ILLEGAL_CHARS:
        symbol = symbol.replace(ch, "_")
    stem = symbol.split(".")[0].upper()
    if stem in _WINDOWS_RESERVED:
        symbol = "_" + symbol
    return symbol
