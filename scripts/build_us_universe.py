"""Build an all-US-listed common-stock universe with a dollar-ADV floor (issue #348).

Downloads the official NASDAQ symbol directories (nasdaqlisted + otherlisted,
covering NASDAQ/NYSE/AMEX/ARCA), keeps common stocks (no ETFs, test issues,
preferreds, warrants, units, rights), then screens the survivors for 20-day
dollar ADV via a light one-month yfinance pass. Writes the liquid list to
tickers_to_scan/us_liquid.json for use with scripts/pattern_scan.py.

Usage:
    python scripts/build_us_universe.py --min-adv 2e6
"""

import argparse
import io
import json
import os
import sys
import urllib.request

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


def fetch_listings():
    symbols = set()
    for url, symcol in ((NASDAQ_URL, "Symbol"), (OTHER_URL, "ACT Symbol")):
        txt = urllib.request.urlopen(url, timeout=60).read().decode("utf-8", "replace")
        df = pd.read_csv(io.StringIO(txt), sep="|")
        df = df[df.get("Test Issue", "N") == "N"]
        if "ETF" in df.columns:
            df = df[df["ETF"] == "N"]
        for s in df[symcol].dropna().astype(str):
            s = s.strip().upper()
            if not s or any(c in s for c in "$.=^"):
                continue  # preferred / when-issued / index notation
            if len(s) == 5 and s[-1] in "WRU":
                continue  # NASDAQ warrant / right / unit suffix convention
            symbols.add(s)
    return sorted(symbols)


def liquidity_filter(tickers, min_adv, chunk=300):
    import yfinance as yf

    keep = {}
    for i in range(0, len(tickers), chunk):
        batch = tickers[i : i + chunk]
        try:
            raw = yf.download(batch, period="1mo", interval="1d", group_by="ticker",
                              auto_adjust=True, threads=True, progress=False)
        except Exception as e:
            print(f"batch {i} failed: {e}")
            continue
        for s in batch:
            try:
                d = raw[s].dropna(subset=["Close"])
            except (KeyError, IndexError):
                continue
            if len(d) < 10:
                continue
            adv = float((d["Close"] * d["Volume"]).mean())
            if adv >= min_adv:
                keep[s] = adv
        print(f"{min(i + chunk, len(tickers))}/{len(tickers)} screened → {len(keep)} liquid")
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-adv", type=float, default=2e6)
    ap.add_argument("--out", default=os.path.join(PROJECT_ROOT, "tickers_to_scan", "us_liquid.json"))
    args = ap.parse_args()

    listings = fetch_listings()
    print(f"{len(listings)} US-listed common stocks in symbol directories")
    liquid = liquidity_filter(listings, args.min_adv)
    with open(args.out, "w") as f:
        json.dump(sorted(liquid), f, indent=1)
    print(f"{len(liquid)} symbols with dollar ADV >= ${args.min_adv / 1e6:.1f}M → {args.out}")


if __name__ == "__main__":
    main()
