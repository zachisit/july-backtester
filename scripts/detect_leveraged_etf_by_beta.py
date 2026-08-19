"""
Returns-based staleness alarm for the curated leveraged/inverse ticker list
(issue #70 / PR #281, round 3, 2026-08-17).

universe_cache/leveraged_inverse_etn_tickers.json is a hand-curated
approximation, not a derived fact -- there is no authoritative machine-
readable Vanguard ticker list to build it from. This script is the
completeness check for that list: it regresses each security's daily
returns against a market proxy and flags names whose beta clusters near a
round leverage multiplier (2x, 3x, ...) or is reliably negative, independent
of any vendor list or product name. It works on delisted names (the corpus
carries their real return history) and needs no external data.

What it can and cannot catch
-----------------------------
This is a beta-clustering heuristic against ONE equity proxy (default SPY),
so it only catches equity-indexed leveraged/inverse products (TQQQ-style).
It CANNOT identify:
  * ETNs that aren't leveraged in the regression sense (VXX, DJP, ...) --
    their return profile doesn't cluster at a clean multiplier of SPY.
  * Leveraged products indexed to something other than a broad equity index
    (commodities, single stocks, currencies, rates, sector/country baskets)
    -- their beta to SPY is usually noisy, not a clean 2x/3x, even though
    the product itself is genuinely leveraged.
Both are real gaps. This script is one input to maintaining the curated
list, not a replacement for it -- see the list's own "_caveat" field.

Output: a CSV report (ticker, beta, r_squared, n_obs, in_curated_list) plus
a stdout summary split into "new candidates" (beta-flagged, absent from the
curated list -- worth a manual look) and "known" (beta-flagged, already in
the list -- confirms the list, not actionable).

Usage:
    python scripts/detect_leveraged_etf_by_beta.py
    python scripts/detect_leveraged_etf_by_beta.py --corpus /path/to/parquet_data/data
    python scripts/detect_leveraged_etf_by_beta.py --limit 500     # smoke test
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from helpers.rule_based_universe import normalise_universe_ticker  # noqa: E402

DEFAULT_CORPUS = os.path.join(ROOT, "parquet_data", "data")
DEFAULT_LIST = os.path.join(ROOT, "universe_cache", "leveraged_inverse_etn_tickers.json")
DEFAULT_OUT = os.path.join(ROOT, "universe_cache", "beta_staleness_report.csv")

#: Multiplier targets a "clean leverage" beta should cluster near. Tolerance
#: is intentionally loose (+/-0.3) -- daily-return beta estimates are noisy
#: even for a mechanically 3x product, especially over shorter overlaps.
_TARGET_MULTIPLIERS = (2.0, 3.0)
_MULTIPLIER_TOL = 0.3
#: A beta reliably below this is inverse-shaped regardless of multiplier.
_INVERSE_BETA_MAX = -0.5
_MIN_OBS = 60


def _security_and_ticker(path: str) -> tuple[str, str]:
    stem = os.path.basename(path)[:-8]
    base = re.sub(r"-\d{6}$", "", stem)
    return stem, normalise_universe_ticker(base)


def _daily_returns(path: str) -> pd.Series | None:
    try:
        df = pd.read_parquet(path, columns=["Close"])
    except Exception:
        return None
    if df.empty:
        return None
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    close = pd.to_numeric(df["Close"], errors="coerce")
    close = close[np.isfinite(close) & (close > 0)].sort_index()
    if len(close) < 2:
        return None
    return close.pct_change().dropna()


def _beta(security_returns: pd.Series, market_returns: pd.Series) -> tuple[float, float, int] | None:
    aligned = pd.concat([security_returns, market_returns], axis=1, join="inner").dropna()
    if len(aligned) < _MIN_OBS:
        return None
    x = aligned.iloc[:, 1].to_numpy()
    y = aligned.iloc[:, 0].to_numpy()
    var_x = np.var(x, ddof=1)
    if var_x <= 0:
        return None
    beta = float(np.cov(y, x, ddof=1)[0, 1] / var_x)
    corr = float(np.corrcoef(y, x)[0, 1]) if np.std(y) > 0 else 0.0
    return beta, corr ** 2, len(aligned)


def _classify(beta: float) -> str | None:
    if beta <= _INVERSE_BETA_MAX:
        return "inverse-shaped"
    for m in _TARGET_MULTIPLIERS:
        if abs(beta - m) <= _MULTIPLIER_TOL:
            return f"~{m:g}x-shaped"
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--market-ticker", default="SPY")
    ap.add_argument("--curated-list", default=DEFAULT_LIST)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--limit", type=int, help="process only the first N files (smoke test)")
    args = ap.parse_args()

    if not os.path.isdir(args.corpus):
        print(f"ERROR: corpus not found: {args.corpus}\n"
              f"Initialise the submodule: git submodule update --init parquet_data",
              file=sys.stderr)
        return 2

    market_path = os.path.join(args.corpus, f"{args.market_ticker}.parquet")
    if not os.path.exists(market_path):
        print(f"ERROR: market proxy not found: {market_path}", file=sys.stderr)
        return 2
    market_returns = _daily_returns(market_path)
    if market_returns is None:
        print(f"ERROR: could not compute returns for market proxy {args.market_ticker}", file=sys.stderr)
        return 2

    curated: set[str] = set()
    if os.path.exists(args.curated_list):
        with open(args.curated_list, encoding="utf-8") as f:
            curated = {str(t).upper() for t in json.load(f).get("tickers", [])}
    else:
        print(f"WARNING: curated list not found at {args.curated_list} -- "
              f"'in_curated_list' will be False for everything", file=sys.stderr)

    paths = sorted(glob.glob(os.path.join(args.corpus, "*.parquet")))
    if args.limit:
        paths = paths[: args.limit]
    print(f"corpus       : {args.corpus}\nmarket proxy : {args.market_ticker}\nfiles        : {len(paths)}\n")

    rows = []
    t0 = time.time()
    for i, path in enumerate(paths, 1):
        if i % 2500 == 0:
            print(f"  {i}/{len(paths)}  ({time.time()-t0:.0f}s)")
        security, ticker = _security_and_ticker(path)
        if not security[:1].isalnum():
            continue
        returns = _daily_returns(path)
        if returns is None:
            continue
        result = _beta(returns, market_returns)
        if result is None:
            continue
        beta, r2, n_obs = result
        label = _classify(beta)
        if label is None:
            continue
        rows.append({
            "security": security,
            "ticker": ticker,
            "beta": round(beta, 3),
            "r_squared": round(r2, 3),
            "n_obs": n_obs,
            "classification": label,
            "in_curated_list": ticker in curated,
        })

    report = pd.DataFrame(
        rows, columns=["security", "ticker", "beta", "r_squared", "n_obs",
                        "classification", "in_curated_list"],
    ).sort_values(["in_curated_list", "ticker"]).reset_index(drop=True)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    report.to_csv(args.out, index=False)

    new_candidates = report[~report["in_curated_list"]]
    known = report[report["in_curated_list"]]
    print(f"\nelapsed         : {time.time()-t0:.0f}s")
    print(f"beta-flagged    : {len(report)}")
    print(f"  known (already in curated list) : {len(known)}")
    print(f"  NEW CANDIDATES (review these)   : {len(new_candidates)}")
    if not new_candidates.empty:
        print("\nNew candidates:")
        print(new_candidates.to_string(index=False))
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
