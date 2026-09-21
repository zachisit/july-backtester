"""Build the unified merged/ dataset from classification + Norgate + Polygon patch.

Runs the merge cases of MERGE_SPEC.md §12 and writes merged/{symbol}.parquet plus
metadata/merge_summary.json. See data/market_data/MERGE_SPEC.md.

Usage:
    python scripts/build_merged_dataset.py                 # full build (all cases)
    python scripts/build_merged_dataset.py --skip-delisted # skip the 22k Case-B pass-throughs
    python scripts/build_merged_dataset.py --indices-only  # only required index assets
"""
import os
import sys
import json
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pandas as pd
from src.data.pipeline import paths, merge, polygon_io

REQUIRED_INDICES = ["SPX", "NDX", "RUT", "DJI", "OEX", "VIX", "VXN", "TNX"]


def load_classification():
    return pd.read_csv(os.path.join(paths.METADATA, "symbol_classification.csv"),
                       keep_default_na=False, na_values=[""])


def build(skip_delisted=False, indices_only=False, asof=None, log=None):
    """Run the merge cases. Returns the counts dict (also written to merge_summary.json)."""
    paths.ensure_dirs()
    log = log or paths.get_logger("build_merged")
    cls = load_classification()
    asof = asof or polygon_io.cached_trading_days()[-1]
    counts = {"patch_dates": sum(1 for d in polygon_io.cached_trading_days()
                                 if pd.Timestamp(d) > paths.ANCHOR)}

    # required index assets (always)
    idx_done = 0
    for sym in REQUIRED_INDICES:
        try:
            if merge.merge_required_index(sym, paths.PATCH_START, asof):
                idx_done += 1
        except Exception as e:
            log.warning(f"index {sym} failed: {e}")
    counts["required_indices"] = idx_done
    log.info(f"required indices merged: {idx_done}/{len(REQUIRED_INDICES)}")
    if indices_only:
        return _finish(counts, log)

    def run(bucket, fn, key_col):
        sub = cls[cls["bucket"] == bucket]
        n = 0
        for _, r in sub.iterrows():
            try:
                if fn(r):
                    n += 1
            except Exception as e:
                log.warning(f"{bucket} {r[key_col]} failed: {e}")
        log.info(f"{bucket}: merged {n}/{len(sub)}")
        return n

    # symbols failing the calibration identity/seam check -> history only (fail-closed)
    id_review_path = os.path.join(paths.AUDIT, "identity_review.csv")
    flagged = set()
    if os.path.exists(id_review_path):
        idr = pd.read_csv(id_review_path, keep_default_na=False, na_values=[""])
        if not idr.empty and "symbol" in idr.columns:
            flagged = set(idr["symbol"].astype(str))
    log.info(f"identity/seam-flagged commons held from patch: {len(flagged)}")

    def _common(r):
        if str(r["symbol"]) in flagged:
            return merge.merge_history_only(r["symbol"], r["security_type"], "identity_review")
        return merge.merge_common(r["symbol"], r["polygon_ticker"], r["security_type"])

    counts["common_to_both"] = run("common_to_both", _common, "symbol")
    counts["identity_held"] = len(flagged)
    counts["norgate_only_review"] = run(
        "norgate_only_review",
        lambda r: merge.merge_review(r["symbol"], r["security_type"]), "symbol")
    counts["polygon_only_new_listing"] = run(
        "polygon_only_new_listing",
        lambda r: merge.merge_new_listing(r["polygon_ticker"], r["security_type"]),
        "polygon_ticker")
    if not skip_delisted:
        # Deterministic collision guard: a delisted bare ticker can match a live
        # Polygon new-listing of the same recycled name. Pass the live-listing
        # keys so merge_delisted writes those to a -YYYYMM suffix instead of
        # clobbering the live file (and vice-versa). Lossless, order-independent.
        _live_keys = set(
            cls[cls["bucket"] == "polygon_only_new_listing"]["polygon_ticker"].astype(str))
        log.info(f"live new-listing keys for collision guard: {len(_live_keys)}")
        counts["norgate_only_delisted_keep"] = run(
            "norgate_only_delisted_keep",
            lambda r: merge.merge_delisted(r["symbol"], r["security_type"], _live_keys),
            "symbol")
    else:
        log.info("skipped Case B (delisted)")

    # PR #187 Fix 5 — unconditional index re-merge (review item: minor nit)
    # Previously this block sat inside `if not skip_delisted:`, so two callers
    # never triggered it:
    #   (a) daily update_market_data.py calls build(skip_delisted=True)
    #   (b) build(indices_only=True) also skipped Case B
    # A delisted equity tickered "VIX" or "TNX" (Case B) could overwrite the real
    # index file and corrupt the merged dataset silently. Moving the re-merge
    # outside the conditional ensures index assets always win any name collision
    # regardless of which build mode is active.
    reidx = 0
    for sym in REQUIRED_INDICES:
        try:
            if merge.merge_required_index(sym, paths.PATCH_START, asof):
                reidx += 1
        except Exception as e:
            log.warning(f"index {sym} re-merge failed: {e}")
    counts["required_indices"] = reidx
    log.info(f"required indices re-merged last (collision guard): {reidx}/{len(REQUIRED_INDICES)}")

    return _finish(counts, log)


def _finish(counts, log):
    merged_total = len([f for f in os.listdir(paths.MERGED) if f.endswith(".parquet")])
    counts["merged_total"] = merged_total
    with open(os.path.join(paths.METADATA, "merge_summary.json"), "w", encoding="utf-8") as f:
        json.dump(counts, f, indent=2)
    log.info(f"BUILD COMPLETE — merged/ now holds {merged_total:,} symbols")
    return counts


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-delisted", action="store_true")
    ap.add_argument("--indices-only", action="store_true")
    ap.add_argument("--asof", default=None)
    args = ap.parse_args()
    counts = build(skip_delisted=args.skip_delisted,
                   indices_only=args.indices_only, asof=args.asof)
    print(json.dumps(counts, indent=2))


if __name__ == "__main__":
    main()
