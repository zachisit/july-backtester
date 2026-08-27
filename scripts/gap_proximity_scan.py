#!/usr/bin/env python3
"""Gap-proximity + dead-money scan for a backtest trade log (issue #102).

Zach's prod scan asked whether Bull Flag Breakout enters near parabolic
single-bar events, and found 0 of 45 on ~1 month of live trades. This runs the
same rule against a BACKTEST log -- 11 years instead of 1 month -- so the
structural claim can be tested on a sample that could actually contain the
cohort, and adds the threshold sensitivity that a single yes/no cannot give.

Also reports dead money (time in position vs distance travelled), which is the
other half of the same question: what happens when a position holds through an
event-driven repricing instead of entering near one.

Prices come from the local parquet store, not Polygon -- free, offline, and the
same split-adjusted series the backtest used.

Usage:
  python gap_proximity_scan.py <trade_log.csv> [parquet_dir]
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

MOVE_TH = 0.30          # Zach's headline rule
VOL_MULT = 5.0
VOL_WIN = 20
WINDOWS = (3, 5, 7, 10, 15)
GRID_MOVE = (0.30, 0.20, 0.15, 0.10)
GRID_VOL = (5.0, 3.0, 2.0)


def read_ohlcv(path: Path) -> pd.DataFrame | None:
    try:
        df = pd.read_parquet(path)
    except Exception:
        return None
    if "Datetime" in df.columns:
        df = df.set_index("Datetime")
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    df.index = idx.normalize()
    df = df[~df.index.duplicated(keep="last")].sort_index()
    cols = {c.lower(): c for c in df.columns}
    need = ("open", "high", "low", "close", "volume")
    if not all(k in cols for k in need):
        return None
    out = pd.DataFrame(index=df.index)
    for k in need:
        out[k.capitalize()] = df[cols[k]].astype(float)
    return out


def resolve(sym: str, pdir: Path) -> Path | None:
    p = pdir / f"{sym}.parquet"
    if p.exists():
        return p
    hits = sorted(pdir.glob(f"{sym}-*.parquet"))   # delisted: TICKER-YYYYMM
    return hits[-1] if hits else None


def qualifying(df: pd.DataFrame, move_th: float, vol_mult: float) -> pd.Series:
    """A bar is a parabolic event if the move clears move_th AND volume clears
    vol_mult x its TRAILING average. The average excludes the bar itself --
    otherwise a huge bar inflates its own baseline (8.0x -> 5.9x on a test
    spike) and the volume test partly defeats itself."""
    pc = df["Close"].shift(1)
    move = pd.concat([(df["Open"] / pc - 1).abs(),
                      (df["Close"] / pc - 1).abs(),
                      (df["High"] / pc - 1).abs()], axis=1).max(axis=1)
    avg = df["Volume"].rolling(VOL_WIN).mean().shift(1)
    return (move >= move_th) & (df["Volume"] >= vol_mult * avg)


def scoreable(df: pd.DataFrame) -> pd.Series:
    """True where a full trailing volume baseline exists.

    qualifying() returns False for the first VOL_WIN bars because the rolling
    baseline is NaN and NaN comparisons are False. That makes a bar that could
    not be tested indistinguishable from one that was tested and did not
    qualify -- the dangerous direction, since this scan's whole output is a
    count of absences. Callers use this to tell the two apart.

    Found by @shardul0701 reconciling a 30.2x vs 31.1x volume multiple on UTZ:
    the difference was a truncated baseline at the edge of a 60-day fetch
    window, not a disagreement about the data. Reading the parquet store
    directly gives full history, so unscoreable bars should be rare here --
    but the count is reported rather than assumed.
    """
    return df["Volume"].rolling(VOL_WIN).mean().shift(1).notna()


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: gap_proximity_scan.py <trade_log.csv> [parquet_dir]")
    log = Path(sys.argv[1])
    pdir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("parquet_data/data")

    tr = pd.read_csv(log)
    for c in ("EntryDate", "ExitDate"):
        tr[c] = pd.to_datetime(tr[c], utc=True, errors="coerce").dt.tz_localize(None).dt.normalize()
    tr["Profit"] = pd.to_numeric(tr["Profit"], errors="coerce")
    tr = tr.dropna(subset=["EntryDate"]).reset_index(drop=True)

    print(f"\n{'='*70}\n  GAP-PROXIMITY SCAN -- {log.name}\n{'='*70}")
    print(f"  trades : {len(tr)}")
    print(f"  span   : {tr['EntryDate'].min().date()} -> {tr['EntryDate'].max().date()}")
    print(f"  symbols: {tr['Symbol'].nunique()}")

    # --- load prices once per symbol --------------------------------------
    px, missing = {}, []
    for s in sorted(tr["Symbol"].unique()):
        p = resolve(str(s), pdir)
        d = read_ohlcv(p) if p else None
        if d is None or d.empty:
            missing.append(str(s))
        else:
            px[str(s)] = d
    print(f"  price data: {len(px)}/{tr['Symbol'].nunique()} symbols"
          + (f"  MISSING: {missing[:10]}" if missing else ""))
    if missing:
        print("  ^ trades on these symbols cannot be scanned and are excluded below")

    scan = tr[tr["Symbol"].astype(str).isin(px)].reset_index(drop=True)

    # --- headline rule, Zach's thresholds ---------------------------------
    print(f"\n  {'-'*66}")
    print(f"  Entries within N days of a qualifying bar "
          f"(move >= {MOVE_TH:.0%}, vol >= {VOL_MULT:.0f}x)")
    print(f"  {'-'*66}")
    qual = {s: qualifying(d, MOVE_TH, VOL_MULT) for s, d in px.items()}
    scor = {s: scoreable(d) for s, d in px.items()}
    for w in WINDOWS:
        n = 0
        blind = 0
        for _, r in scan.iterrows():
            sym = str(r["Symbol"])
            q, sc = qual[sym], scor[sym]
            lo, hi = r["EntryDate"] - pd.Timedelta(days=w), r["EntryDate"] + pd.Timedelta(days=w)
            win = (q.index >= lo) & (q.index <= hi)
            if q.loc[win].any():
                n += 1
            if (~sc.loc[win]).any():
                blind += 1
        note = f"   [{blind} entries have unscoreable bars in window]" if blind else ""
        print(f"      +/-{w:>2}d : {n:>4} of {len(scan)}  ({n/len(scan)*100:.1f}%){note}")

    total_unscoreable = sum(int((~s).sum()) for s in scor.values())
    total_bars = sum(len(s) for s in scor.values())
    print(f"\n      baseline coverage: {total_bars - total_unscoreable:,} of {total_bars:,} "
          f"bars scoreable ({total_unscoreable:,} in warm-up)")
    print("      a bar without a full trailing baseline cannot qualify and is not")
    print("      evidence of absence -- it is reported rather than counted as a No")

    # --- sensitivity: is 0 a property of the strategy or of the threshold? -
    print(f"\n  {'-'*66}")
    print(f"  Threshold sensitivity (+/-7d window). A single 0 at one threshold")
    print(f"  says little; the shape of this grid says where entries actually")
    print(f"  sit relative to event bars.")
    print(f"  {'-'*66}")
    hdr = "  move\\vol " + "".join(f"{v:>8.0f}x" for v in GRID_VOL)
    print(hdr)
    for mt in GRID_MOVE:
        row = f"  {mt:>7.0%}  "
        for vm in GRID_VOL:
            qq = {s: qualifying(d, mt, vm) for s, d in px.items()}
            n = 0
            for _, r in scan.iterrows():
                q = qq[str(r["Symbol"])]
                lo, hi = r["EntryDate"] - pd.Timedelta(days=7), r["EntryDate"] + pd.Timedelta(days=7)
                if q.loc[(q.index >= lo) & (q.index <= hi)].any():
                    n += 1
            row += f"{n:>9}"
        print(row)

    # --- what the near-entry bars actually look like ----------------------
    biggest = []
    for _, r in scan.iterrows():
        d = px[str(r["Symbol"])]
        lo, hi = r["EntryDate"] - pd.Timedelta(days=7), r["EntryDate"] + pd.Timedelta(days=7)
        w = d.loc[(d.index >= lo) & (d.index <= hi)]
        if len(w) < 2:
            continue
        pc = w["Close"].shift(1)
        mv = pd.concat([(w["Open"]/pc - 1).abs(), (w["Close"]/pc - 1).abs(),
                        (w["High"]/pc - 1).abs()], axis=1).max(axis=1)
        avg = d["Volume"].rolling(VOL_WIN).mean().shift(1).reindex(w.index)
        vr = (w["Volume"] / avg)
        if mv.notna().any():
            i = mv.idxmax()
            biggest.append({"sym": r["Symbol"], "entry": r["EntryDate"].date(),
                            "max_move": float(mv.loc[i]), "vol_x": float(vr.loc[i]) if pd.notna(vr.loc[i]) else np.nan,
                            "when": (i - r["EntryDate"]).days, "profit": r["Profit"]})
    bg = pd.DataFrame(biggest)
    if len(bg):
        print(f"\n  Largest single-bar move within +/-7d of each entry:")
        print(f"      median {bg['max_move'].median():.1%}   "
              f"90th pct {bg['max_move'].quantile(0.9):.1%}   max {bg['max_move'].max():.1%}")
        print(f"      entries with a >=20% bar nearby: {(bg['max_move']>=0.20).sum()} of {len(bg)}")
        top = bg.nlargest(6, "max_move")
        print(f"\n      {'sym':<8}{'entry':<12}{'max move':>9}{'vol x':>8}{'when':>7}{'profit':>10}")
        for _, r in top.iterrows():
            vx = f"{r['vol_x']:.1f}" if pd.notna(r["vol_x"]) else "n/a"
            print(f"      {str(r['sym']):<8}{str(r['entry']):<12}{r['max_move']:>8.1%}{vx:>8}"
                  f"{r['when']:>+7d}{r['profit']:>10.0f}")

    # --- dead money --------------------------------------------------------
    cl = scan.dropna(subset=["ExitDate"]).copy()
    if len(cl):
        cl["days"] = (cl["ExitDate"] - cl["EntryDate"]).dt.days
        cl["ret"] = pd.to_numeric(cl.get("ProfitPct"), errors="coerce")
        dead = cl[(cl["days"] >= 20) & (cl["ret"].abs() < 0.02)]
        print(f"\n  {'-'*66}")
        print(f"  Dead money: closed trades held >=20 days that moved <2%")
        print(f"  {'-'*66}")
        print(f"      {len(dead)} of {len(cl)} closed trades ({len(dead)/len(cl)*100:.1f}%)")
        if len(dead):
            print(f"      median hold {dead['days'].median():.0f} days, "
                  f"total P&L ${dead['Profit'].sum():,.0f}")
            print(f"      capital-days tied up: {dead['days'].sum():,} of "
                  f"{cl['days'].sum():,} ({dead['days'].sum()/cl['days'].sum()*100:.1f}%)")
        print(f"      hold-time distribution (all closed): median {cl['days'].median():.0f}d, "
              f"90th {cl['days'].quantile(0.9):.0f}d, max {cl['days'].max():.0f}d")
    print()


if __name__ == "__main__":
    main()
