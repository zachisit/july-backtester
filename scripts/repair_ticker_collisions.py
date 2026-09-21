"""Repair the recycled-ticker collisions in merged/ WITHOUT a full 35k rebuild.

Background
----------
`merge._write` names files `{key}.parquet` with no disambiguator, so a delisted
Norgate ticker and a live Polygon new-listing of the same recycled name landed on
the same file. The delisted pass runs last, so the bare ticker currently holds the
*delisted* company and the live listing's recent Polygon bars were dropped.

This script makes both instruments coexist (the same outcome the patched
build_merged_dataset.py now produces deterministically):
  - moves the current (delisted) file to `{key}-YYYYMM.parquet`
  - re-materializes the live Polygon listing into `{key}.parquet`

Safety
------
- DRY-RUN by default. Pass --apply to write.
- Near-anchor guard: a "delisted" series ending within --near-anchor-days of the
  Norgate anchor (2026-04-22) is probably a still-live instrument that was merely
  mis-bucketed (e.g. share classes TAP.A / WSO.B). Splitting those would shorten a
  continuous backtest series, so they are SKIPPED unless --include-near-anchor.
- Reversible: the delisted history is preserved under the suffixed name; nothing
  is deleted.

Usage:
    python scripts/repair_ticker_collisions.py                 # dry-run report
    python scripts/repair_ticker_collisions.py --apply         # split safe ones
    python scripts/repair_ticker_collisions.py --apply --include-near-anchor
"""
import os
import sys
import re
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pandas as pd
from src.data.pipeline import paths, merge

SUFFIX_RE = re.compile(r"-\d{6}$")


def find_collisions():
    cls = pd.read_csv(os.path.join(paths.METADATA, "symbol_classification.csv"),
                      keep_default_na=False, na_values=[""])
    delisted = set(cls[cls["bucket"] == "norgate_only_delisted_keep"]["symbol"].astype(str))
    new_keys = {}
    for _, r in cls[cls["bucket"] == "polygon_only_new_listing"].iterrows():
        new_keys[str(r["polygon_ticker"])] = str(r["security_type"])
    return sorted(k for k in delisted if k in new_keys and not SUFFIX_RE.search(k)), new_keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry-run)")
    ap.add_argument("--near-anchor-days", type=int, default=20)
    ap.add_argument("--include-near-anchor", action="store_true")
    args = ap.parse_args()

    keys, new_keys = find_collisions()
    print(f"collision keys (bare delisted ticker == live new-listing): {len(keys)}")
    print(f"mode: {'APPLY' if args.apply else 'DRY-RUN'} | near-anchor guard: "
          f"{'OFF' if args.include_near_anchor else f'skip <={args.near_anchor_days}d to anchor'}")
    print("-" * 78)

    split, skipped = 0, 0
    for k in keys:
        p = os.path.join(paths.MERGED, f"{k}.parquet")
        if not os.path.exists(p):
            print(f"  {k:8s} SKIP (no current file)")
            continue
        cur = pd.read_parquet(p)
        last = cur.index.max()
        gap = (paths.ANCHOR - last).days
        patch_path = os.path.join(paths.POLYGON_PATCH, f"{k}.parquet")
        has_patch = os.path.exists(patch_path)
        near = gap <= args.near_anchor_days

        if near and not args.include_near_anchor:
            print(f"  {k:8s} SKIP near-anchor (ends {last.date()}, {gap}d to anchor — "
                  f"likely live/misclassified)")
            skipped += 1
            continue
        if not has_patch:
            print(f"  {k:8s} SKIP (no polygon_patch to restore live listing)")
            skipped += 1
            continue

        suffix_name = f"{k}-{last.strftime('%Y%m')}"
        action = f"move delisted -> {suffix_name}.parquet ; restore Polygon -> {k}.parquet"
        if args.apply:
            cur.to_parquet(os.path.join(paths.MERGED, f"{suffix_name}.parquet"))
            n = merge.merge_new_listing(k, new_keys[k])  # overwrites bare {k}.parquet with patch
            print(f"  {k:8s} DONE  {action}  (live bars={n})")
        else:
            print(f"  {k:8s} would: {action}")
        split += 1

    print("-" * 78)
    print(f"{'split' if args.apply else 'would split'}: {split} | skipped: {skipped}")
    if not args.apply:
        print("dry-run only — re-run with --apply to write.")


if __name__ == "__main__":
    main()
