"""Regenerate the authoritative dataset manifest WITHOUT a full re-audit.

Aggregates the existing audit summary (audit/patch_audit.csv), the merged/ listing,
classification, and a fresh (cheap) index validation into
metadata/dataset_manifest.json. Use this when you trust the last audit pass and
just want a consistent, timestamped manifest. For a manifest that is atomic with a
fresh audit, run scripts/audit_merged_dataset.py instead.

Usage:
    python scripts/build_dataset_manifest.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import json
import pandas as pd
from src.data.pipeline import paths, audit, manifest


def main():
    log = paths.get_logger("dataset_manifest")
    pa = os.path.join(paths.AUDIT, "patch_audit.csv")
    summary = None
    if os.path.exists(pa):
        summary = pd.read_csv(pa, keep_default_na=False, na_values=[""])
        log.info(f"loaded audit summary: {len(summary):,} rows from patch_audit.csv")
    else:
        log.warning("patch_audit.csv not found — status/insufficient counts will be empty. "
                    "Run scripts/audit_merged_dataset.py for a full ground-truth pass.")
    index_rows, _ = audit.index_validation(logger=log)
    m = manifest.write_manifest(summary, index_rows=index_rows, logger=log)
    print(json.dumps(m, indent=2))


if __name__ == "__main__":
    main()
