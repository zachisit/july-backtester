"""Honest PIT coverage check: does each member's merged file actually COVER its
membership window — not just "does a file with that name exist".

The earlier 99.2%/98.6% figure was file-EXISTS coverage (a parquet resolves for
the ticker). That overstates fitness: a file can exist but start years after the
ticker joined the index, or be the wrong (recycled) company entirely. This script
reports three numbers per universe:

  exists        : a merged file resolves for the (normalised) ticker
  covers_start  : that file's first bar is <= membership_start (+ tolerance)
  covers_span   : file covers BOTH ends of the membership window (the honest one)

Run:  rtk python scripts/verify_pit_span_coverage.py
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

import pandas as pd

from helpers.pit_enforcement import membership_intervals
from src.data.unified_market_data_provider import UnifiedMarketDataProvider

START, END = "2004-01-01", "2026-06-06"
TOL = pd.Timedelta(days=7)        # grace at each end (data starts a few days late)


def _load_env():
    """Minimal .env reader so SP500_DATA_ROOT resolves without python-dotenv."""
    p = os.path.join(ROOT, ".env")
    if not os.path.isfile(p):
        return
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _check(value, label, prov):
    intervals = membership_intervals(value, {
        "start_date": START, "end_date": END,
        "sp500_pit_path": os.environ.get("SP500_DATA_ROOT", ""),
        "nq100_pit_path": os.path.join(ROOT, "data", "nq100_membership.parquet"),
    })
    if not intervals:
        print(f"\n{label}: no membership data (source missing) — skipped")
        return
    n = len(intervals)
    exists = covers_start = covers_span = 0
    missing, short = [], []
    for ticker, spells in sorted(intervals.items()):
        spell_checks = []
        for span_lo, span_hi in spells:
            path = prov._resolve(ticker, span_lo.strftime("%Y-%m-%d"),
                                 span_hi.strftime("%Y-%m-%d"))
            if path is None:
                spell_checks.append((False, False, False, span_lo, span_hi, None, None))
                continue
            lo, hi = prov._index_range(path)
            if lo is None:
                spell_checks.append((False, False, False, span_lo, span_hi, None, None))
                continue
            ok_start = lo <= span_lo + TOL
            ok_end = hi >= span_hi - TOL
            spell_checks.append((True, ok_start, ok_start and ok_end,
                                 span_lo, span_hi, lo, hi))

        if spell_checks and all(c[0] for c in spell_checks):
            exists += 1
        else:
            missing.append(ticker)
        if spell_checks and all(c[1] for c in spell_checks):
            covers_start += 1
        if spell_checks and all(c[2] for c in spell_checks):
            covers_span += 1
        else:
            for _exists, _start_ok, span_ok, span_lo, span_hi, lo, hi in spell_checks:
                if not span_ok:
                    short.append((
                        ticker, str(span_lo.date()), str(span_hi.date()),
                        "missing" if lo is None else str(lo.date()),
                        "missing" if hi is None else str(hi.date()),
                    ))

    print(f"\n{'='*70}\n{label}  (members in {START}..{END}: {n})\n{'='*70}")
    print(f"  exists        {exists:>4}/{n}  ({exists/n:6.1%})  every spell resolves")
    print(f"  covers_start  {covers_start:>4}/{n}  ({covers_start/n:6.1%})  every spell begins by join date")
    print(f"  covers_span   {covers_span:>4}/{n}  ({covers_span/n:6.1%})  *** HONEST per-spell coverage ***")
    if missing:
        print(f"\n  no file ({len(missing)}): {', '.join(missing[:40])}"
              + (" ..." if len(missing) > 40 else ""))
    if short:
        print(f"\n  file too short ({len(short)}) — ticker | need | have:")
        for t, s0, s1, h0, h1 in short[:30]:
            print(f"    {t:<8} {s0}..{s1}  |  {h0}..{h1}")
        if len(short) > 30:
            print(f"    ... +{len(short)-30} more")


def main():
    _load_env()
    prov = UnifiedMarketDataProvider()
    _check("sp500_pit", "S&P 500 PIT", prov)
    _check("nq100_pit", "Nasdaq-100 PIT", prov)


if __name__ == "__main__":
    main()
