"""Task 7 — merge engine. Produces the single canonical series per symbol in
merged/{symbol}.parquet that the backtester reads.

Canonical merged schema (index = tz-naive NY date at midnight):
    open, high, low, close, volume, vwap,
    source, security_type, adjustment_factor, adjustment_method, data_quality_status

ALL rows carry canonical (total-return) prices: Norgate rows are native
total-return (factor 1.0); Polygon rows are raw x total-return factor (already
applied in the patch). Authority: Norgate <= 2026-04-22, Polygon > 2026-04-22.

Cases (MERGE_SPEC.md §12):
  A common_to_both          Norgate history + Polygon patch (seam/identity must pass)
  B norgate_only_delisted   Norgate history pass-through, no patch (valid series end)
  C norgate_only_review     Norgate history, NOT patched, status='review_no_patch'
  D polygon_only_new_listing Polygon patch only, history_start tag, insufficient-history flag
  E polygon_only_coverage_gap  excluded from default universe (not materialized)
  F required_strategy_asset    patched like A; index assets handled separately
"""
import os
import re
import glob
import pandas as pd

from . import paths

_MERGED_COLS = ["open", "high", "low", "close", "volume", "vwap",
                "source", "security_type", "adjustment_factor",
                "adjustment_method", "data_quality_status"]

_SUFFIX_RE = re.compile(r"-\d{6}$")  # delisted files carry a -YYYYMM suffix


def _norgate_history(symbol, security_type, status="ok"):
    """Read a Norgate parquet, slice <= ANCHOR, return canonical-schema frame."""
    path = paths.norgate_path(symbol)
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    df = df[df.index <= paths.ANCHOR].copy()
    if df.empty:
        return None
    out = pd.DataFrame(index=df.index)
    out.index.name = "date"
    out["open"] = df["Open"].astype("float64")
    out["high"] = df["High"].astype("float64")
    out["low"] = df["Low"].astype("float64")
    out["close"] = df["Close"].astype("float64")
    out["volume"] = df["Volume"].astype("float64")
    out["vwap"] = float("nan")
    out["source"] = "norgate"
    out["security_type"] = security_type
    out["adjustment_factor"] = 1.0
    out["adjustment_method"] = "norgate_native"
    out["data_quality_status"] = status
    return out


def _patch(polygon_ticker):
    path = os.path.join(paths.POLYGON_PATCH, f"{polygon_ticker}.parquet")
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    for c in _MERGED_COLS:
        if c not in df.columns:
            df[c] = pd.NA
    return df[_MERGED_COLS]


def _write(symbol, df):
    df = df[_MERGED_COLS].sort_index()
    df = df[~df.index.duplicated(keep="first")]
    df.to_parquet(os.path.join(paths.MERGED, f"{symbol}.parquet"))


def merge_common(norgate_symbol, polygon_ticker, security_type):
    """Case A/F: Norgate history + Polygon patch."""
    hist = _norgate_history(norgate_symbol, security_type)
    patch = _patch(polygon_ticker)
    if hist is None and patch is None:
        return None
    parts = [p for p in (hist, patch) if p is not None]
    df = pd.concat(parts)
    _write(norgate_symbol, df)
    return len(df)


def merge_delisted(norgate_symbol, security_type, live_keys=None):
    """Case B: Norgate-only history pass-through.

    Deterministic collision guard: if ``norgate_symbol`` is a bare ticker that
    also names a live Polygon listing (present in ``live_keys`` — the set of
    polygon_only_new_listing tickers), the delisted history is written to a
    date-suffixed name ``{SYMBOL}-YYYYMM.parquet`` so the live listing keeps the
    bare ``{SYMBOL}.parquet``. Lossless: both instruments survive, and the
    write order no longer decides the winner. Symbols that already carry a
    -YYYYMM suffix never collide and are written as-is.
    """
    hist = _norgate_history(norgate_symbol, security_type)
    if hist is None:
        return None
    name = norgate_symbol
    if live_keys and norgate_symbol in live_keys and not _SUFFIX_RE.search(norgate_symbol):
        name = f"{norgate_symbol}-{hist.index.max().strftime('%Y%m')}"
    _write(name, hist)
    return len(hist)


def merge_history_only(norgate_symbol, security_type, status):
    """Norgate history through the anchor, NOT patched. Used for Case C (review)
    and for common symbols that fail the calibration identity/seam check."""
    hist = _norgate_history(norgate_symbol, security_type, status=status)
    if hist is None:
        return None
    _write(norgate_symbol, hist)
    return len(hist)


def merge_review(norgate_symbol, security_type):
    """Case C: active Norgate symbol, no Polygon match -> history only, flagged."""
    return merge_history_only(norgate_symbol, security_type, "review_no_patch")


def merge_new_listing(polygon_ticker, security_type):
    """Case D: Polygon-only new listing (patch only)."""
    patch = _patch(polygon_ticker)
    if patch is None:
        return None
    if len(patch) < paths.MIN_LOOKBACK_BARS:
        patch = patch.copy()
        patch["data_quality_status"] = "insufficient_history"
    _write(polygon_ticker, patch)
    return len(patch)


# ---------------------------------------------------------- required indices ---
def _resolve_norgate_index(sym):
    """Return the Norgate symbol (basename, e.g. '$VIX') for an index, or None."""
    sym = sym.upper()
    for c in (f"${sym}", f"$I:{sym}", sym, f"$I_{sym}"):
        if os.path.exists(paths.norgate_path(c)):
            return c
    hits = glob.glob(os.path.join(paths.NORGATE_ROOT, f"*{sym}.parquet"))
    for h in hits:
        base = os.path.splitext(os.path.basename(h))[0]
        if base.lstrip("$").upper() == sym:
            return base
    return None


def merge_required_index(index_sym, patch_start, patch_end):
    """Case F (index): Norgate $-index history + Polygon I:<sym> patch.

    Indices have no splits/dividends -> patch factor 1.0. Written as merged/<sym>.parquet.
    Best-effort: patch-only if no Norgate history file exists.
    """
    from . import polygon_io
    sym = index_sym.upper()
    parts = []
    nsym = _resolve_norgate_index(sym)
    if nsym is not None:
        hist = _norgate_history(nsym, "index")
        if hist is not None:
            parts.append(hist)
    pdf = polygon_io.pull_index_daily(sym, patch_start, patch_end)
    if pdf is not None:
        pdf = pdf[pdf.index > paths.ANCHOR].copy()
        if not pdf.empty:
            pat = pd.DataFrame(index=pdf.index)
            pat.index.name = "date"
            for c in ("open", "high", "low", "close"):
                pat[c] = pdf[c].astype("float64")
            pat["volume"] = pdf["volume"].astype("float64")
            pat["vwap"] = float("nan")
            pat["source"] = "polygon"
            pat["security_type"] = "index"
            pat["adjustment_factor"] = 1.0
            pat["adjustment_method"] = "none"
            pat["data_quality_status"] = "ok"
            parts.append(pat)
    if not parts:
        return None
    df = pd.concat(parts)
    _write(sym, df)
    return len(df)
