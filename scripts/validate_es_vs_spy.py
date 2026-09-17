"""
Independent validation of the stitched ES 1-min series against SPY 1-min.

These come from two different Polygon products (futures aggregates vs equity aggregates),
so agreement is real cross-source evidence that the ES bars are correctly timestamped to
the NY cash session and that the quarterly roll is not distorting intraday levels.

Checks, all derived from the data (no hardcoded expectations):
  1. Session coverage overlap.
  2. Correlation of the opening range expressed as a fraction of the 09:30 open.
  3. Agreement on WHICH side of the opening range broke first in the 09:45-11:00 window.
  4. Roll-day behaviour: OR width on roll days vs non-roll days (a corrupted stitch would
     blow the OR out on the day the contract changes).
"""
from __future__ import annotations

import os
import sys
import time as _t
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from es_futures_data import load_es_1min, _api_key  # noqa: E402

CACHE = HERE.parent / "es_minute_cache" / "SPY_1min.parquet"
NY = "America/New_York"


def fetch_spy_1min(start: str, end: str) -> pd.DataFrame:
    if CACHE.exists():
        return pd.read_parquet(CACHE)
    key = _api_key()
    s = requests.Session()
    rows: list[dict] = []
    cur = pd.Timestamp(start)
    stop = pd.Timestamp(end)
    while cur < stop:
        nxt = min(cur + pd.DateOffset(months=1), stop)
        url = (f"https://api.polygon.io/v2/aggs/ticker/SPY/range/1/minute/"
               f"{cur.date()}/{nxt.date()}")
        params = {"adjusted": "true", "sort": "asc", "limit": 50000, "apiKey": key}
        while True:
            r = s.get(url, params=params, timeout=120)
            if r.status_code == 429:
                _t.sleep(10); continue
            r.raise_for_status()
            j = r.json()
            rows.extend(j.get("results") or [])
            nu = j.get("next_url")
            if not nu:
                break
            url, params = nu, {"apiKey": key}
        print(f"  SPY {cur.date()} -> {nxt.date()}: {len(rows):,} rows", flush=True)
        cur = nxt
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["t"], unit="ms", utc=True)
    df = df.set_index("ts").sort_index().tz_convert(NY)
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df[["open", "high", "low", "close", "volume"]]
    df = df[~df.index.duplicated(keep="first")]
    df.to_parquet(CACHE)
    return df


def or_features(df: pd.DataFrame, or_minutes: int = 15) -> pd.DataFrame:
    rth = df.between_time(time(9, 30), time(16, 0), inclusive="left")
    or_end = 9 * 60 + 30 + or_minutes
    cutoff = 11 * 60
    out = []
    for day, bars in rth.groupby(rth.index.date, sort=True):
        mins = bars.index.hour * 60 + bars.index.minute
        orb = bars[mins < or_end]
        win = bars[(mins >= or_end) & (mins <= cutoff)]
        if len(orb) < 8 or win.empty:
            continue
        o = float(orb.iloc[0]["open"])
        hi, lo = float(orb["high"].max()), float(orb["low"].min())
        # which side broke first inside the window
        first = 0
        for _, b in win.iterrows():
            up, dn = b["high"] >= hi, b["low"] <= lo
            if up and dn:
                first = 2          # both in one bar: unresolvable
                break
            if up:
                first = 1; break
            if dn:
                first = -1; break
        out.append({"session": day, "open": o, "or_hi_frac": (hi - o) / o,
                    "or_lo_frac": (lo - o) / o, "or_width_frac": (hi - lo) / o,
                    "first_break": first})
    return pd.DataFrame(out).set_index("session")


def main() -> None:
    es = load_es_1min(verbose=False)
    start = str(max(pd.Timestamp("2024-09-17").date(), es.index.min().date()))
    end = str(es.index.max().date())
    print(f"fetching SPY 1-min {start} -> {end} ...", flush=True)
    spy = fetch_spy_1min(start, end)

    fe, fs = or_features(es), or_features(spy)
    common = fe.index.intersection(fs.index)
    print(f"\nsessions: ES {len(fe)}, SPY {len(fs)}, overlapping {len(common)}")
    e, s = fe.loc[common], fs.loc[common]

    print("\n--- check 2: opening range as a fraction of the 09:30 open ---")
    for col in ("or_hi_frac", "or_lo_frac", "or_width_frac"):
        c = float(np.corrcoef(e[col], s[col])[0, 1])
        print(f"  corr({col:15s}) = {c:.4f}   ES mean {e[col].mean():+.5f}  "
              f"SPY mean {s[col].mean():+.5f}")

    print("\n--- check 3: which side of the OR broke first (09:45-11:00) ---")
    both = (e["first_break"] != 2) & (s["first_break"] != 2)
    agree = (e.loc[both, "first_break"] == s.loc[both, "first_break"])
    print(f"  comparable sessions: {int(both.sum())}")
    print(f"  agreement: {agree.mean():.1%}  (disagreements: {int((~agree).sum())})")
    xt = pd.crosstab(e.loc[both, "first_break"], s.loc[both, "first_break"])
    print("  crosstab (rows ES, cols SPY; -1 down, 0 none, 1 up):")
    print(xt.to_string())

    print("\n--- check 4: roll days vs normal days (stitch integrity) ---")
    con = es.groupby(es.index.date)["contract"].first()
    changed = con != con.shift(1)
    roll_days = set(con.index[changed.fillna(False)])
    er = fe[fe.index.isin(roll_days)]["or_width_frac"]
    en = fe[~fe.index.isin(roll_days)]["or_width_frac"]
    print(f"  roll days {len(er)}: mean OR width {er.mean():.5f}")
    print(f"  other days {len(en)}: mean OR width {en.mean():.5f}")
    print(f"  ratio {er.mean()/en.mean():.3f}  (a corrupted stitch would blow this up)")

    out = HERE.parent / "output"
    out.mkdir(exist_ok=True)
    pd.concat([e.add_prefix("es_"), s.add_prefix("spy_")], axis=1).to_csv(
        out / "validation_es_vs_spy.csv")
    print(f"\nwrote {out/'validation_es_vs_spy.csv'}")


if __name__ == "__main__":
    main()
