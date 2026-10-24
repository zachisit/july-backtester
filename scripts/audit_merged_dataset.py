"""Audit the merged/ dataset and write the final approval report.

Runs per-row + time-series checks on every merged symbol, the completeness gate
on the Polygon pulls, and the special-case audits, then decides APPROVED / NOT
APPROVED. See data/market_data/MERGE_SPEC.md §13.

Usage:
    python scripts/audit_merged_dataset.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:  # the approval report contains non-ASCII (✅); Windows cp1252 stdout would crash on print
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from src.data.pipeline import paths, audit


def main():
    log = paths.get_logger("audit_merged")
    approved, counts = audit.run_full_audit(logger=log)
    print(open(os.path.join(paths.AUDIT, "final_approval_report.md"), encoding="utf-8").read())
    sys.exit(0 if approved else 1)


if __name__ == "__main__":
    main()
