"""Task 10 — daily updater for the unified market-data pipeline.

Idempotent and safe to rerun. Each run:
  1. finds the latest completed trading day,
  2. re-pulls a trailing 5 trading-day window (Polygon revisions) + any new days,
  3. re-pulls splits/dividends,
  4. rebuilds per-ticker patch files,
  5. rebuilds affected merged tickers (common/new/review/indices; delisted unchanged),
  6. runs the completeness gate + full audit,
  7. approves or fails the update and writes logs + final_approval_report.md.

Usage:
    python scripts/update_market_data.py --asof latest
    python scripts/update_market_data.py --asof 2026-06-08
"""
import os
import sys
import json
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:  # approval report has non-ASCII (✅); Windows cp1252 stdout crashes on print otherwise
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import importlib
import pandas as pd
from src.data.pipeline import paths, polygon_io, normalize, audit


def _universe_and_types():
    cls = pd.read_csv(os.path.join(paths.METADATA, "symbol_classification.csv"),
                      keep_default_na=False, na_values=[""])
    common = cls[cls["bucket"] == "common_to_both"]
    pending_new = cls[cls["bucket"].isin(["polygon_only_new_listing", "polygon_only_coverage_gap"])]
    universe = set(common["polygon_ticker"]) | set(pending_new["polygon_ticker"]) \
        | set(paths.REQUIRED_STRATEGY_ASSETS)
    sec_type = dict(zip(cls["polygon_ticker"].astype(str), cls["security_type"].astype(str)))
    return cls, universe, sec_type


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default="latest", help="'latest' or YYYY-MM-DD")
    ap.add_argument("--trailing", type=int, default=paths.TRAILING_REPULL_DAYS)
    args = ap.parse_args()

    log = paths.get_logger("update_market_data")
    asof = pd.Timestamp.now().normalize() if args.asof == "latest" else pd.Timestamp(args.asof)
    log.info(f"=== daily update asof {asof.date()} ===")

    # 1-3. pull: new days + force trailing window + corp actions
    cached = polygon_io.cached_trading_days()
    trailing = set(cached[-args.trailing:]) if cached else set()
    log.info(f"re-pulling trailing window: {sorted(trailing)}")
    trading_days = polygon_io.pull_range(paths.OVERLAP_START, asof,
                                         force_dates=trailing, logger=log)
    polygon_io.pull_splits(logger=log)
    polygon_io.pull_dividends(logger=log)

    # PR #187 Fix 4 — empty trading_days guard (review item: minor nit)
    # polygon_io.pull_range() returns [] on US market holidays and on reruns where
    # every date in the window is already cached. Without this guard, trading_days[-1]
    # raised IndexError and left patch state in a partially-written, inconsistent
    # condition that silently broke the next successful run.
    if not trading_days:
        log.warning("pull_range returned no trading days (holiday or empty rerun) — nothing to update.")
        return

    last_day = trading_days[-1]
    log.info(f"latest completed trading day: {last_day}")

    # 4. rebuild patch
    cls, universe, sec_type = _universe_and_types()
    all_dates = polygon_io.cached_trading_days()
    patch_dates = [d for d in all_dates if pd.Timestamp(d) > paths.ANCHOR]
    written, warns, presence = normalize.build_patch(
        universe, all_dates, patch_dates, last_day, sec_type, logger=log)
    pd.DataFrame(warns).to_csv(os.path.join(paths.AUDIT, "corporate_action_warnings.csv"), index=False)
    log.info(f"patch rebuilt: {len(written)} tickers, {len(warns)} warnings")

    # 5. rebuild merged (skip delisted — unchanged after the anchor)
    bm = importlib.import_module("build_merged_dataset")
    counts = bm.build(skip_delisted=True, asof=last_day, log=log)

    # 6-7. audit + approve
    approved, audit_counts = audit.run_full_audit(logger=log)
    log.info(json.dumps({**counts, **{k: audit_counts[k] for k in
             ("merged_total", "flagged_symbols", "delist", "insuff") if k in audit_counts}}, indent=2))
    log.info(f"UPDATE {'APPROVED' if approved else 'FAILED'}")
    print(open(os.path.join(paths.AUDIT, "final_approval_report.md"), encoding="utf-8").read())
    sys.exit(0 if approved else 1)


if __name__ == "__main__":
    main()
