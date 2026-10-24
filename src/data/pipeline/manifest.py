"""Atomic dataset manifest — one authoritative, internally-consistent snapshot of
what merged/ actually contains, derived from a single per-symbol audit pass.

Why this exists: merge_summary.json counts merge *return values at write time*
(e.g. new_listing=356), while symbol_classification.csv counts *classified rows*
(new_listing=374); the 18-row gap is new-listings that had no polygon_patch file
to materialize. Those two artifacts came from different pipeline states, so their
numbers disagree. The manifest supersedes them for reporting: every count here is
computed from the same ground-truth scan (the audit summary + the merged/ listing
+ classification), with a generated_at timestamp and git commit for provenance.
"""
import os
import re
import json
import subprocess

import pandas as pd

from . import paths

_SUFFIX_RE = re.compile(r"-\d{6}$")
_INDEX_SYMS = {"SPX", "NDX", "RUT", "DJI", "OEX", "VIX", "VXN", "TNX"}


def _git_commit():
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                           cwd=paths.ROOT, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def _collisions(cls):
    """Bare delisted tickers that also name a live Polygon new-listing."""
    delisted = set(cls[cls["bucket"] == "norgate_only_delisted_keep"]["symbol"].astype(str))
    new_keys = set(cls[cls["bucket"] == "polygon_only_new_listing"]["polygon_ticker"].astype(str))
    return sorted(k for k in (delisted & new_keys) if not _SUFFIX_RE.search(k))


def build_manifest(summary_df, index_rows=None, cls=None):
    """Return the manifest dict from a ground-truth audit summary DataFrame.

    summary_df: per-merged-symbol rows (the audit's patch_audit summary), needs
                'status' and 'bucket' columns; 'n_bars' optional.
    index_rows: output of audit.index_validation()[0] (optional).
    cls:        symbol_classification DataFrame (optional; read if None).
    """
    if cls is None:
        cls = pd.read_csv(os.path.join(paths.METADATA, "symbol_classification.csv"),
                          keep_default_na=False, na_values=[""])
    files = [f[:-8] for f in os.listdir(paths.MERGED) if f.endswith(".parquet")]
    suffixed = sum(1 for f in files if _SUFFIX_RE.search(f))

    status_counts, bucket_counts = {}, {}
    insufficient = 0
    if summary_df is not None and not summary_df.empty:
        if "status" in summary_df.columns:
            status_counts = {str(k): int(v)
                             for k, v in summary_df["status"].value_counts().items()}
            insufficient = int((summary_df["status"] == "insufficient_history").sum())
        if "bucket" in summary_df.columns:
            bucket_counts = {str(k): int(v)
                             for k, v in summary_df["bucket"].value_counts().items()}

    idx_ok = idx_bad = None
    if index_rows is not None:
        idx_ok = sum(1 for r in index_rows if r.get("ok"))
        idx_bad = sum(1 for r in index_rows if not r.get("ok"))

    return {
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "git_commit": _git_commit(),
        "anchor": str(paths.ANCHOR.date()),
        "patch_start": str(paths.PATCH_START.date()),
        "ground_truth": "merged/ directory + audit summary (single pass)",
        "merged_files_total": len(files),
        "suffixed_delisted_files": suffixed,
        "indices_present": sorted(s for s in _INDEX_SYMS
                                  if os.path.exists(os.path.join(paths.MERGED, f"{s}.parquet"))),
        "index_validation": {"ok": idx_ok, "bad": idx_bad},
        "status_counts": status_counts,
        "bucket_counts_materialized": bucket_counts,
        "insufficient_history": insufficient,
        "classification_bucket_counts": {str(k): int(v)
                                         for k, v in cls["bucket"].value_counts().items()},
        "recycled_ticker_collisions": _collisions(cls),
        "note": ("Authoritative for reporting. Supersedes merge_summary.json "
                 "(write-time return counts) and standalone insufficient-history "
                 "CSVs (different pipeline states). classification_bucket_counts "
                 "are CLASSIFIED rows; bucket_counts_materialized are what actually "
                 "landed in merged/ — a gap means rows with no source data to write."),
    }


def write_manifest(summary_df, index_rows=None, cls=None, logger=None):
    m = build_manifest(summary_df, index_rows=index_rows, cls=cls)
    paths.ensure_dirs()
    path = os.path.join(paths.METADATA, "dataset_manifest.json")
    # Atomic write: a reader never sees a half-written/empty manifest, and a
    # crash mid-write leaves the previous good manifest intact. Write to a temp
    # file in the same dir (same filesystem -> os.replace is atomic) then swap.
    tmp = f"{path}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(m, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    if logger:
        logger.info(f"dataset manifest -> {path} "
                    f"({m['merged_files_total']:,} files, "
                    f"idx ok={m['index_validation']['ok']}/8)")
    return m
