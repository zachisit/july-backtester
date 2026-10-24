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
import math
import re
from datetime import datetime, timezone
from pathlib import Path
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
        if "Test Issue" in df.columns:
            df = df[df["Test Issue"] == "N"]
        if "ETF" in df.columns:
            df = df[df["ETF"] == "N"]
        for _, row in df.iterrows():
            if pd.isna(row[symcol]):
                continue
            s = str(row[symcol]).strip().upper()
            # Keep common share classes in canonical dot notation. ACT's
            # preferred/warrant suffix punctuation is not a share class.
            if not re.fullmatch(r"[A-Z][A-Z0-9]*(?:[.-][A-Z])?", s):
                continue
            description = str(row.get("Security Name", "")).rsplit(" - ", 1)[-1]
            if re.search(r"\b((?:preferred|preference)\s+(?:stock|shares|securities)|warrants?|rights?|units?|notes?|bonds?|debentures?)\b",
                         description, re.IGNORECASE):
                continue
            # Explicit common-share descriptions take precedence over legacy
            # suffix guidance: GOOGL is a five-letter common-stock root.
            common = re.search(r"\b(common|capital|ordinary)\s+(stock|shares?)\b",
                               description, re.IGNORECASE)
            if (url == NASDAQ_URL and len(s) == 5
                    and s[-1] in "CGHILMNOPRTUVWXZ" and not common):
                continue
            symbols.add(s.replace("-", "."))
    return sorted(symbols)


def liquidity_filter(tickers, min_adv, chunk=300, *, stats=None):
    import yfinance as yf

    keep = {}
    aliases = {symbol: symbol.replace(".", "-") for symbol in tickers}
    for i in range(0, len(tickers), chunk):
        batch = tickers[i : i + chunk]
        try:
            raw = yf.download(list(dict.fromkeys(aliases[symbol] for symbol in batch)), period="1mo", interval="1d", group_by="ticker",
                              auto_adjust=True, threads=True, progress=False)
        except Exception as e:
            print(f"batch {i} failed: {e}")
            continue
        for s in batch:
            try:
                if not isinstance(raw.columns, pd.MultiIndex) and len(batch) != 1:
                    continue
                d = (raw[aliases[s]] if isinstance(raw.columns, pd.MultiIndex) else raw).dropna(subset=["Close"])
            except (KeyError, IndexError):
                continue
            if len(d) < 10:
                continue
            adv = float((d["Close"] * d["Volume"]).tail(20).mean())
            if not math.isfinite(adv) or adv < 0:
                continue
            if stats is not None:
                stats["scored"] = stats.get("scored", 0) + 1
            if adv >= min_adv:
                keep[s] = adv
        print(f"{min(i + chunk, len(tickers))}/{len(tickers)} screened → {len(keep)} liquid")
    return keep


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-adv", type=float, default=2e6)
    ap.add_argument("--out", default=os.path.join(PROJECT_ROOT, "tickers_to_scan", "us_liquid.json"))
    args = ap.parse_args(argv)
    if not math.isfinite(args.min_adv) or args.min_adv < 0:
        ap.error("--min-adv must be finite and nonnegative")

    listings = fetch_listings()
    print(f"{len(listings)} US-listed common stocks in symbol directories")
    stats = {}
    liquid = liquidity_filter(listings, args.min_adv, stats=stats)
    if not listings or not stats.get("scored"):
        ap.error("no listing prices were scored; the existing universe was not overwritten")
    destination = Path(args.out).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(sorted(liquid), indent=1), encoding="utf-8")
    destination.with_suffix(".meta.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "min_dollar_adv": args.min_adv, "adv_sessions": 20,
        "listed": len(listings), "scored": stats["scored"], "selected": len(liquid),
    }, indent=2), encoding="utf-8")
    print(f"{len(liquid)} symbols with dollar ADV >= ${args.min_adv / 1e6:.1f}M → {args.out}")


if __name__ == "__main__":
    main()
