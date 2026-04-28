"""
Momentum Rotation — One-Command Runner
=======================================
Usage:
    python run_momentum_rotation.py          # v2 (20% alloc, no stop)
    python run_momentum_rotation.py --v3     # v3 (15% alloc, 15% stop) — when ready

Steps:
    0. Flush data_cache/ — ensures consistent Yahoo Finance data across all 101 tickers
    1. Run the standalone script — prints stats, runs MC/WFA, writes PDF tearsheet
"""

import subprocess
import shutil
import sys
import os
import argparse


def run_step(label: str, cmd: list):
    sep = "=" * 64
    print(f"\n{sep}")
    print(f"  {label}")
    print(f"  Command: {' '.join(cmd)}")
    print(sep)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\n  ERROR: step failed with exit code {result.returncode}. Stopping.")
        sys.exit(result.returncode)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--v3", action="store_true",
                        help="Run v3 (15% alloc, 15% daily stop loss)")
    args, _ = parser.parse_known_args()

    py      = sys.executable
    version = "v3" if args.v3 else "v2"
    script  = f"scripts/momentum_rotation_{version}.py"

    print(f"\n  Running: Momentum Rotation {version.upper()}")
    print(f"  Script : {script}")

    # ── Step 0: flush stale cache ─────────────────────────────────────────────
    cache_dir = "data_cache"
    sep = "=" * 64
    if os.path.isdir(cache_dir):
        file_count = sum(len(files) for _, _, files in os.walk(cache_dir))
        print(f"\n{sep}")
        print(f"  STEP 0 / 1 — Flushing {file_count} stale cache file(s) from {cache_dir}/")
        print(f"  Reason: mixed stale/fresh data causes non-reproducible RS_60d rankings.")
        print(sep)
        shutil.rmtree(cache_dir)
        os.makedirs(cache_dir, exist_ok=True)
        print(f"  Cache cleared.\n")
    else:
        print(f"\n  (No cache directory found — fetching all data fresh.)\n")

    # ── Step 1: run standalone backtest + PDF ────────────────────────────────
    run_step(f"STEP 1 / 1 — Backtest + PDF tearsheet ({version})", [py, script])

    print("\n" + "=" * 64)
    print("  All steps complete.")
    print("  PDF is in:  output/runs/momentum-rotation-v2_<timestamp>/detailed_reports/")
    print("=" * 64)
