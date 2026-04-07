#!/usr/bin/env python3
"""
validate_norgate_export.py — Compare Norgate database against local Parquet files
==================================================================================

Checks each Norgate database (US Equities, US Equities Delisted, US Indices)
against the local parquet_data/ directory and reports any missing files.

Usage:
    python scripts/validate_norgate_export.py
    python scripts/validate_norgate_export.py --output-dir parquet_data
"""

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_ILLEGAL_FILENAME_CHARS = r'\\/:*?"<>|'

DATABASES = [
    "US Equities",
    "US Equities Delisted",
    "US Indices",
]


def _sanitize_filename(symbol: str) -> str:
    for ch in _ILLEGAL_FILENAME_CHARS:
        symbol = symbol.replace(ch, "_")
    return symbol


def validate(output_dir: Path) -> None:
    import norgatedata

    total_norgate = 0
    total_missing = 0
    total_present = 0

    for db in DATABASES:
        symbols = norgatedata.database_symbols(db)
        if not symbols:
            print(f"\n[{db}]  — 0 symbols returned, skipping")
            continue

        missing = [s for s in symbols if not (output_dir / f"{_sanitize_filename(s)}.parquet").exists()]
        present = len(symbols) - len(missing)

        total_norgate += len(symbols)
        total_missing += len(missing)
        total_present += present

        status = "OK" if not missing else f"MISSING {len(missing)}"
        print(f"\n[{db}]")
        print(f"  Norgate symbols : {len(symbols):,}")
        print(f"  Local parquet   : {present:,}")
        print(f"  Missing         : {len(missing):,}  [{status}]")
        if missing:
            for s in missing[:20]:
                print(f"    - {s}")
            if len(missing) > 20:
                print(f"    ... and {len(missing) - 20} more")

    print("\n" + "=" * 50)
    print(f"  TOTAL Norgate   : {total_norgate:,}")
    print(f"  TOTAL present   : {total_present:,}")
    print(f"  TOTAL missing   : {total_missing:,}")
    if total_missing == 0:
        print("  STATUS          : ALL PRESENT")
    else:
        pct = total_missing / total_norgate * 100
        print(f"  STATUS          : {pct:.1f}% missing — re-run export for missing symbols")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Validate Norgate export against local Parquet files.")
    parser.add_argument("--output-dir", default="parquet_data", help="Parquet output directory (default: parquet_data/)")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    if not output_dir.exists():
        print(f"ERROR: output dir '{output_dir}' does not exist.")
        sys.exit(1)

    validate(output_dir)


if __name__ == "__main__":
    main()
