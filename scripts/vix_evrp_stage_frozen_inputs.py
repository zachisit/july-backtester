"""Stage the frozen PR #179 inputs as per-symbol Parquet for the engine (issue #487).

The VIX eVRP study (private-strategies PR #179) froze its inputs as CSV panels.
This converts them, unchanged, into ``{SYMBOL}.parquet`` files that the normal
``parquet`` data provider reads, so the parity run replays the exact frozen
prices rather than fresh vendor data.

The inputs are licensed and private: the staged files go to a git-ignored
directory (default ``output/frozen_inputs/vix_evrp_pr179``) and must not be
committed. Every source file is checked against the study's ``SHA256SUMS``
before anything is written.

Usage::

    python scripts/vix_evrp_stage_frozen_inputs.py \\
        --study-dir <private-strategies>/research/vix_evrp_dual_signal

The frozen panel carries only Open/Close. High/Low are set to max/min(Open,
Close) and Volume to 0 purely to satisfy the provider schema; the
target-weight engine reads Open and Close only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd  # noqa: E402

PANEL = "data/daily_inputs.csv"
SVXY = "implementation_2026-11-09/data/svxy.csv"
SGOV = "implementation_2026-11-09/data/sgov.csv"
#: panel column prefix -> staged file name (VIX/VIX3M match the plugin's
#: default I:VIX / I:VIX3M after parquet ticker normalisation)
PANEL_SYMBOLS = {"SPY": "SPY", "$VIX": "VIX", "$VIX3M": "VIX3M", "VIXY": "VIXY"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_lf(path: Path) -> str:
    """SHA256 after CRLF -> LF, for a Windows checkout with core.autocrlf=true."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def verify_checksums(study: Path, files: list[str]) -> dict:
    sums = {}
    for line in (study / "SHA256SUMS").read_text().splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1]] = parts[0]
    out = {}
    for rel in files:
        actual = _sha256(study / rel)
        if sums.get(rel) != actual and sums.get(rel) == _sha256_lf(study / rel):
            actual = sums[rel]  # same bytes once git's CRLF conversion is undone
        if sums.get(rel) != actual:
            raise SystemExit(f"Checksum mismatch for {rel}: SHA256SUMS={sums.get(rel)} actual={actual}")
        out[rel] = actual
    return out


def _ohlcv(open_: pd.Series, close: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame({"Open": open_, "Close": close}).dropna(how="any")
    df["High"] = df[["Open", "Close"]].max(axis=1)
    df["Low"] = df[["Open", "Close"]].min(axis=1)
    df["Volume"] = 0.0
    df.index = pd.DatetimeIndex(df.index, name="Datetime")
    return df[["Open", "High", "Low", "Close", "Volume"]]


def stage(study: Path, out: Path) -> dict:
    checksums = verify_checksums(study, [PANEL, SVXY, SGOV])
    read = dict(index_col=0, parse_dates=True, float_precision="round_trip")
    panel = pd.read_csv(study / PANEL, **read)
    frames = {name: _ohlcv(panel[f"{col}_Open"], panel[f"{col}_Close"])
              for col, name in PANEL_SYMBOLS.items()}
    for name, rel in (("SVXY", SVXY), ("SGOV", SGOV)):
        df = pd.read_csv(study / rel, **read)
        frames[name] = _ohlcv(df["Open"], df["Close"])
    out.mkdir(parents=True, exist_ok=True)
    # Only the study folder's name: an absolute path would leak a local machine path.
    manifest = {"source_study": study.resolve().name, "source_sha256": checksums, "files": {}}
    for name, df in frames.items():
        path = out / f"{name}.parquet"
        df.to_parquet(path)
        manifest["files"][name] = {"rows": int(len(df)), "first": str(df.index[0].date()),
                                   "last": str(df.index[-1].date()), "sha256": _sha256(path)}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--study-dir", type=Path, required=True,
                        help="research/vix_evrp_dual_signal in the private-strategies checkout")
    parser.add_argument("--out", type=Path,
                        default=Path(PROJECT_ROOT) / "output" / "frozen_inputs" / "vix_evrp_pr179")
    args = parser.parse_args()
    manifest = stage(args.study_dir.resolve(), args.out)
    for name, info in manifest["files"].items():
        print(f"{name:<6} {info['rows']:>5} rows  {info['first']} -> {info['last']}")
    print(f"Staged to {args.out} (git-ignored; do not commit licensed inputs)")


if __name__ == "__main__":
    main()
