"""
Validation gate for the rule-based universe (issue #70).

Per the condition agreed on #70, no result may be reported off a ``rule:``
universe until this has been run: measure overlap between the rule-based
top-N and a known-good PIT index roster for years where that roster is
reliable.

Overlap will NOT be 100% and should not be. The S&P 500 is a committee-selected
index with float, sector and seasoning rules; a liquidity rule is a different
selector. What matters is that overlap is HIGH and STABLE, and that the
divergences are explicable — a rule universe that tracks the index closely in
2015 and loosely in 2016 is telling you something is wrong with the cache, not
with the index.

Usage:
    python scripts/validate_rule_universe.py --cache <path> --pit-root <dir>
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from helpers import rule_based_universe as rbu  # noqa: E402
from helpers.point_in_time import tickers_as_of  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", required=True)
    ap.add_argument("--pit-root", required=True, help="dir containing sp500_pit_data")
    ap.add_argument("--index", default="sp500")
    ap.add_argument("--start-year", type=int, default=2010)
    ap.add_argument("--end-year", type=int, default=2025)
    args = ap.parse_args()

    cfg = {
        "universe_cache_path": args.cache,
        "sp500_pit_path": os.path.join(args.pit_root, "sp500_pit_data"),
        "nq100_pit_path": os.path.join(args.pit_root, "nq100_pit_data"),
    }

    print(f"{'year':<6}{'index n':>9}{'rule n':>8}{'overlap':>9}{'  % of index':>13}"
          f"{'  in rule only':>15}{'  in index only':>16}")
    rows = []
    for year in range(args.start_year, args.end_year + 1):
        date = f"{year}-06-15"
        try:
            idx = set(tickers_as_of(args.index, date, cfg))
        except Exception as e:
            print(f"{year:<6}  index roster unavailable: {e}")
            continue
        if not idx:
            continue
        # Match the index's size so the comparison is like-for-like.
        rcfg = dict(cfg, universe_top_n=len(idx))
        rule = set(rbu.universe_on(date, rcfg))
        inter = idx & rule
        pct = len(inter) / len(idx) * 100 if idx else 0.0
        print(f"{year:<6}{len(idx):>9}{len(rule):>8}{len(inter):>9}{pct:>12.1f}%"
              f"{len(rule - idx):>15}{len(idx - rule):>16}")
        rows.append({"year": year, "index_n": len(idx), "rule_n": len(rule),
                     "overlap": len(inter), "pct_of_index": round(pct, 2)})

    if not rows:
        print("\nNo comparable years — check --pit-root.", file=sys.stderr)
        return 1

    df = pd.DataFrame(rows)
    print(f"\nmean overlap {df['pct_of_index'].mean():.1f}%  "
          f"min {df['pct_of_index'].min():.1f}%  max {df['pct_of_index'].max():.1f}%  "
          f"stdev {df['pct_of_index'].std():.2f}pp")
    print("\nStability is the signal here, not the level. A high mean with a low "
          "spread means the rule is selecting a consistent slice of the market;\n"
          "a wide spread would point at the cache or the thresholds, not at the index.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
