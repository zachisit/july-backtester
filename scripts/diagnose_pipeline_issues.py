"""Read-only fact-gathering for the pipeline issue batch (PIT coverage, collisions,
count reconciliation, suffix resolution). Writes nothing; prints a structured report.

Usage:  python scripts/diagnose_pipeline_issues.py
"""
import os
import sys
import re
import json
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import pandas as pd
from src.data.pipeline import paths

MERGED = paths.MERGED
META = paths.METADATA
AUDIT = paths.AUDIT
SUFFIX_RE = re.compile(r"-\d{6}$")


def line(c="-"):
    print(c * 78)


# ---------- merged stems ----------
files = [f[:-8] for f in os.listdir(MERGED) if f.endswith(".parquet")]
stems = set(files)
base2files = {}
for s in files:
    if SUFFIX_RE.search(s):
        base2files.setdefault(SUFFIX_RE.sub("", s), []).append(s)
print(f"merged files: {len(files)}  | suffixed-delisted bases: {len(base2files)}")


def variants(t):
    t = str(t).strip().upper()
    return {t, t.replace(".", "-"), t.replace("-", "."), t.replace(".", ""), t.replace("-", "")}


def covered(t):
    for v in variants(t):
        if v in stems:
            return v
        if v in base2files:  # date-suffixed delisted file exists
            return sorted(base2files[v])[-1]
    return None


# ---------- PIT unions ----------
line("=")
print("PART 1 — PIT coverage (union mode)")
line("=")
sp_repo = os.environ.get("SP500_DATA_ROOT") or \
    r"C:\Users\shard\Light Water Internship\SP500-Survivorship-bias-data-2004-2026"
from helpers.pit_universe import get_sp500_tickers_in_period, get_nq100_tickers_in_period

sp = get_sp500_tickers_in_period("2004-01-01", "2026-06-06", sp_repo)
nq = get_nq100_tickers_in_period("2004-01-01", "2026-06-06",
                                 os.path.join(ROOT, "data", "nq100_membership.parquet"))
for label, lst in (("S&P500", sp), ("NQ100", nq)):
    miss = [t for t in lst if covered(t) is None]
    print(f"\n{label}: {len(lst)} members | covered {len(lst)-len(miss)} | MISSING {len(miss)}")
    print("  missing:", ", ".join(sorted(miss)))


# ---------- collisions ----------
line("=")
print("PART 2 — recycled-ticker collisions (delisted vs new_listing)")
line("=")
cls = pd.read_csv(os.path.join(META, "symbol_classification.csv"),
                  keep_default_na=False, na_values=[""])
# materializing buckets and the merged key each produces
KEY = {
    "common_to_both": "symbol",
    "norgate_only_review": "symbol",
    "norgate_only_delisted_keep": "symbol",
    "polygon_only_new_listing": "polygon_ticker",
}
keymap = {}  # merged_key -> list of (bucket, symbol, polygon_ticker)
for _, r in cls.iterrows():
    b = r["bucket"]
    if b not in KEY:
        continue
    k = str(r[KEY[b]])
    keymap.setdefault(k, []).append((b, str(r["symbol"]), str(r["polygon_ticker"])))

collisions = {k: v for k, v in keymap.items() if len(v) > 1}
print(f"merged keys produced by >1 materializing row: {len(collisions)}")
for k, v in sorted(collisions.items()):
    buckets = "+".join(sorted(b for b, _, _ in v))
    state = ""
    p = os.path.join(MERGED, f"{k}.parquet")
    if os.path.exists(p):
        d = pd.read_parquet(p)
        src = d["source"].iloc[-1] if "source" in d.columns and len(d) else "?"
        st = d["security_type"].iloc[-1] if "security_type" in d.columns and len(d) else "?"
        state = f"last={d.index.max().date()} src={src} type={st} close={d['close'].iloc[-1]:.2f}"
    print(f"  {k:10s} [{buckets}] {state}")


# ---------- count reconciliation ----------
line("=")
print("PART 3 — count reconciliation")
line("=")
print("classification bucket value_counts:")
for b, n in cls["bucket"].value_counts().items():
    print(f"  {b:32s} {n}")

ms_path = os.path.join(META, "merge_summary.json")
if os.path.exists(ms_path):
    ms = json.load(open(ms_path))
    print("\nmerge_summary.json:")
    for k, val in ms.items():
        print(f"  {k:32s} {val}")

# patch_audit / insufficient_history sources
print("\ninsufficient-history sources:")
for pa in glob.glob(os.path.join(AUDIT, "*.csv")) + glob.glob(os.path.join(META, "*.csv")):
    try:
        d = pd.read_csv(pa, keep_default_na=False, na_values=[""])
    except Exception:
        continue
    cols = {c.lower(): c for c in d.columns}
    name = os.path.basename(pa)
    if "data_quality_status" in cols:
        ih = (d[cols["data_quality_status"]] == "insufficient_history").sum()
        if ih:
            print(f"  {name}: data_quality_status==insufficient_history -> {ih}")
    for c in d.columns:
        if "insuff" in c.lower():
            try:
                print(f"  {name}: col '{c}' truthy -> {int(d[c].astype(bool).sum())}")
            except Exception:
                pass

idr = os.path.join(AUDIT, "identity_review.csv")
if os.path.exists(idr):
    d = pd.read_csv(idr, keep_default_na=False, na_values=[""])
    print(f"\nidentity_review.csv rows: {len(d)}")


# ---------- git tracked status of pipeline code ----------
line("=")
print("PART 4 — key code files git-tracked?")
line("=")
import subprocess
for f in ["src/data/unified_market_data_provider.py",
          "src/data/pipeline/merge.py", "src/data/pipeline/audit.py",
          "helpers/pit_universe.py", "helpers/point_in_time.py",
          "scripts/build_merged_dataset.py", "scripts/audit_merged_dataset.py",
          "scripts/update_market_data.py", "data/nq100_membership.parquet"]:
    r = subprocess.run(["git", "ls-files", "--error-unmatch", f],
                       cwd=ROOT, capture_output=True, text=True)
    print(f"  {'TRACKED ' if r.returncode == 0 else 'UNTRACKED'} {f}")
