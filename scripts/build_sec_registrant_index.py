"""
Build the SEC registrant snapshot used by the rule-based universe's
instrument-type filter (issue #70, defect 1: no filter meant ~51/185
rule-only names were ETFs/ETNs).

SEC EDGAR's company_tickers.json lists every ticker with an Exchange Act
CIK. Most '40 Act ETFs never appear there at all (they file as investment
companies, not Exchange Act reporting companies), so plain absence already
excludes the bulk of the contamination. The output here reduces that raw
file to just {ticker: filed title} -- the title is what
helpers.rule_based_universe.is_operating_company() checks for the handful
of older structures (legacy index UITs, commodity trusts, bank ETNs) that
DO have an Exchange Act CIK despite not being operating companies.

Usage:
    python scripts/build_sec_registrant_index.py
    python scripts/build_sec_registrant_index.py --source path/to/company_tickers.json
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

SEC_URL = "https://www.sec.gov/files/company_tickers.json"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(ROOT, "universe_cache", "sec_operating_company_tickers.json")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--source", help="local company_tickers.json to reduce instead of fetching")
    ap.add_argument("--fetched-at", help="ISO date to stamp; default = today (UTC)")
    args = ap.parse_args()

    if args.source:
        with open(args.source, encoding="utf-8") as f:
            raw = json.load(f)
    else:
        req = urllib.request.Request(
            SEC_URL, headers={"User-Agent": "july-backtester research contact@example.com"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.load(resp)

    tickers: dict[str, str] = {}
    for row in raw.values():
        t = str(row.get("ticker", "")).strip().upper()
        title = str(row.get("title", "")).strip()
        if t:
            tickers[t] = title

    fetched_at = args.fetched_at or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = {"_source": SEC_URL, "_fetched_at": fetched_at, "tickers": tickers}
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=0, sort_keys=True)

    print(f"wrote {len(tickers)} registrant tickers to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
