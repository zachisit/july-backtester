"""
streak_filter_study.py
======================
Cross-sectional test of Mo's consecutive-day streak heuristic:

  Claim 1 (reversion):   after ~7 consecutive DOWN days, reversal odds improve.
  Claim 2 (continuation): once a run reaches ~9 days one direction, it's a trend
                          more likely to continue than revert.

Why cross-sectional: on a single index, 7 down days in a row happens ~25x in
20 years -- far too few to conclude anything. Pooled over the full Norgate
universe (~36k symbols back to 1990, delisted included) the same event has
hundreds of thousands of occurrences, which is what makes the answer real.

Method:
  * one {SYMBOL}.parquet per symbol, uses the 'Close' column
  * daily direction = sign(close.pct_change); a >50% single-day move is treated
    as a break (likely an unadjusted split / data error, not a real streak day)
  * for every day that ends a run of exactly k same-direction days, record the
    forward return over each horizon h (close[t+h]/close[t] - 1)
  * everything is compared against the UNCONDITIONAL forward return (baseline):
    the number that matters is the excess over baseline, not the raw sign
  * running moments only (mean / std / win-rate / t-stat) -- no per-event storage,
    so the full universe fits in memory

Reads only. Standalone (pandas / numpy / pyarrow / matplotlib). Touches nothing
in the backtester.

Usage:
  python streak_filter_study.py                    # full run on ./parquet_data
  python streak_filter_study.py --limit 500        # quick dry run, first 500 symbols
  python streak_filter_study.py --parquet-dir D:\path\to\parquet_data
"""

import argparse
import glob
import math
import os
import sys
import time

import numpy as np
import pandas as pd


# ---------------------------------------------------------------- accumulators
class Moments:
    """Running mean / std / win-rate for a stream of returns, no storage."""
    __slots__ = ("n", "s", "s2", "wins")

    def __init__(self):
        self.n = 0
        self.s = 0.0
        self.s2 = 0.0
        self.wins = 0

    def update(self, arr: np.ndarray):
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return
        self.n += arr.size
        self.s += float(arr.sum())
        self.s2 += float(np.dot(arr, arr))
        self.wins += int((arr > 0).sum())

    @property
    def mean(self):
        return self.s / self.n if self.n else float("nan")

    @property
    def std(self):
        if self.n < 2:
            return float("nan")
        var = self.s2 / self.n - self.mean ** 2
        return math.sqrt(var) if var > 0 else 0.0

    @property
    def win_rate(self):
        return self.wins / self.n if self.n else float("nan")

    def tstat_vs(self, mu0=0.0):
        # t-stat of the sample mean against mu0 (baseline). See caveats: forward
        # windows overlap, so this OVERSTATES significance -- read it as indicative.
        if self.n < 2 or self.std == 0:
            return float("nan")
        return (self.mean - mu0) / (self.std / math.sqrt(self.n))


def run_lengths(dsign: np.ndarray) -> np.ndarray:
    """Length of the consecutive same-value run ending at each position."""
    n = dsign.size
    is_start = np.empty(n, dtype=bool)
    is_start[0] = True
    np.not_equal(dsign[1:], dsign[:-1], out=is_start[1:])
    start_idx = np.maximum.accumulate(np.where(is_start, np.arange(n), 0))
    return np.arange(n) - start_idx + 1


# --------------------------------------------------------------------- main run
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet-dir", default=None,
                    help="Folder of {SYMBOL}.parquet files (default: ./parquet_data)")
    ap.add_argument("--limit", type=int, default=None, help="Only first N symbols (dry run)")
    ap.add_argument("--min-days", type=int, default=250, help="Skip symbols with fewer bars")
    ap.add_argument("--min-streak", type=int, default=2)
    ap.add_argument("--max-streak", type=int, default=12, help="Top bucket is '>=max'")
    ap.add_argument("--horizons", default="1,3,5,10,20", help="Forward return horizons (days)")
    ap.add_argument("--chart-horizon", type=int, default=5, help="Horizon plotted in the PNG")
    ap.add_argument("--max-daily-move", type=float, default=0.50,
                    help="Days moving more than this are treated as a break (split guard)")
    ap.add_argument("--min-price", type=float, default=1.0,
                    help="Ignore observations whose entry close is below this (penny-stock guard)")
    ap.add_argument("--clip", type=float, default=3.0,
                    help="Winsorize forward returns to [-0.95, clip] (data-error guard)")
    ap.add_argument("--skip-prefixes", default="#,$,&,@",
                    help="Skip symbols whose name starts with any of these (indices/breadth/futures, not stocks)")
    ap.add_argument("--out-prefix", default="streak_study")
    args = ap.parse_args()

    pdir = args.parquet_dir or os.path.join(os.getcwd(), "parquet_data")
    if not os.path.isdir(pdir):
        sys.exit(f"parquet dir not found: {pdir}  (pass --parquet-dir)")

    horizons = [int(h) for h in args.horizons.split(",")]
    bad_prefixes = tuple(p for p in args.skip_prefixes.split(",") if p)
    files = sorted(glob.glob(os.path.join(pdir, "*.parquet")))
    if args.limit:
        files = files[:args.limit]
    if not files:
        sys.exit(f"no .parquet files in {pdir}")

    print(f"universe : {len(files):,} symbols  ({pdir})")
    print(f"horizons : {horizons} days   min streak {args.min_streak}  max {args.max_streak}")
    print(f"cleaning : price floor ${args.min_price:g}   winsorize [-95%, +{args.clip:.0%}]   "
          f"split-guard {args.max_daily_move:.0%}   skip prefixes {list(bad_prefixes)}\n")

    baseline = {h: Moments() for h in horizons}
    # buckets[(direction, k)][h] -> Moments ; k capped at max_streak (top = ">=max")
    buckets = {}

    def bucket(direction, k, h):
        key = (direction, k)
        if key not in buckets:
            buckets[key] = {hh: Moments() for hh in horizons}
        return buckets[key][h]

    used = skipped = 0
    dmin, dmax = pd.Timestamp.max, pd.Timestamp.min
    t0 = time.time()

    for i, fp in enumerate(files, 1):
        if i % 2000 == 0 or i == len(files):
            el = time.time() - t0
            eta = el / i * (len(files) - i)
            print(f"  {i:>6,}/{len(files):,}  used {used:,}  "
                  f"elapsed {el:5.0f}s  eta {eta:5.0f}s")
        sym = os.path.splitext(os.path.basename(fp))[0]
        if bad_prefixes and sym.startswith(bad_prefixes):
            skipped += 1
            continue
        try:
            df = pd.read_parquet(fp, columns=["Close"])
        except Exception:
            skipped += 1
            continue

        if df.shape[0] < args.min_days:
            skipped += 1
            continue

        df = df[~df.index.duplicated(keep="last")].sort_index()
        c = pd.to_numeric(df["Close"], errors="coerce").to_numpy(dtype="float64")
        ok = np.isfinite(c) & (c > 0)
        c = c[ok]
        if c.size < args.min_days:
            skipped += 1
            continue

        try:
            dmin = min(dmin, df.index.min())
            dmax = max(dmax, df.index.max())
        except Exception:
            pass

        m = c.size
        ret = c[1:] / c[:-1] - 1.0                       # len m-1, aligned to day 1..m-1
        dsign = np.sign(ret).astype("int8")
        dsign[np.abs(ret) > args.max_daily_move] = 0     # split / bad-tick guard -> break

        lo = -0.95                                        # a stock can't lose >100%
        # ---- baseline: unconditional forward returns (price floor + winsorize)
        for h in horizons:
            if m > h:
                entry = c[:-h]
                sel = entry >= args.min_price
                if sel.any():
                    fr = np.clip(c[h:][sel] / entry[sel] - 1.0, lo, args.clip)
                    baseline[h].update(fr)

        # ---- streak-conditional forward returns (same cleaning as baseline)
        rl = run_lengths(dsign)
        end_idx = np.arange(dsign.size) + 1              # close index ending the run
        base_mask = (dsign != 0) & (rl >= args.min_streak)
        if not base_mask.any():
            used += 1
            continue

        for h in horizons:
            valid = base_mask & (end_idx + h < m)
            idx = np.nonzero(valid)[0]
            if idx.size == 0:
                continue
            e = end_idx[idx]
            entry = c[e]
            keep = entry >= args.min_price                # penny-stock guard
            if not keep.any():
                continue
            fr = np.clip(c[e + h][keep] / entry[keep] - 1.0, lo, args.clip)
            k = np.minimum(rl[idx][keep], args.max_streak).astype(int)
            sgn = dsign[idx][keep]
            for direction, sv in (("down", -1), ("up", 1)):
                sel = sgn == sv
                if not sel.any():
                    continue
                kk, ff = k[sel], fr[sel]
                for kv in np.unique(kk):
                    bucket(direction, int(kv), h).update(ff[kk == kv])
        used += 1

    print(f"\nsymbols used {used:,}   skipped {skipped:,}   "
          f"coverage {dmin.date()} -> {dmax.date()}\n")

    # -------------------------------------------------------------- results table
    rows = []
    for (direction, k), hm in buckets.items():
        for h, mm in hm.items():
            if mm.n == 0:
                continue
            b = baseline[h]
            rows.append(dict(
                direction=direction, streak=k, horizon=h, n=mm.n,
                mean_bps=mm.mean * 1e4,
                win_rate=mm.win_rate,
                base_bps=b.mean * 1e4,
                excess_bps=(mm.mean - b.mean) * 1e4,
                t_vs_base=mm.tstat_vs(b.mean),
            ))
    res = pd.DataFrame(rows).sort_values(["direction", "horizon", "streak"]).reset_index(drop=True)
    csv_path = f"{args.out_prefix}_results.csv"
    res.to_csv(csv_path, index=False)

    def show(direction, h):
        sub = res[(res.direction == direction) & (res.horizon == h)].sort_values("streak")
        if sub.empty:
            print(f"  (no {direction} data at h={h})")
            return
        b = baseline[h].mean * 1e4
        print(f"  {direction.upper()} streaks, forward {h}-day   "
              f"(baseline {b:+.1f} bps, win {baseline[h].win_rate:5.1%})")
        print(f"    {'k':>4} {'N':>10} {'mean_bps':>10} {'excess':>9} {'win':>7} {'t':>7}")
        for _, r in sub.iterrows():
            klab = f">={int(r.streak)}" if r.streak == args.max_streak else f"{int(r.streak)}"
            print(f"    {klab:>4} {int(r.n):>10,} {r.mean_bps:>10.1f} "
                  f"{r.excess_bps:>+9.1f} {r.win_rate:>7.1%} {r.t_vs_base:>7.1f}")
        print()

    print("=" * 74)
    print("FORWARD RETURNS BY PRIOR STREAK LENGTH  (excess = vs unconditional)")
    print("=" * 74 + "\n")
    for h in (1, args.chart_horizon, 10):
        if h in horizons:
            show("down", h)
            show("up", h)

    # ------------------------------------------------------------------- verdicts
    def get(direction, k, h, field):
        r = res[(res.direction == direction) & (res.streak == k) & (res.horizon == h)]
        return float(r[field].iloc[0]) if len(r) else float("nan")

    print("=" * 74)
    print("READ ON MO'S TWO CLAIMS")
    print("=" * 74)

    print("\n[1] After 7 DOWN days, do reversal odds improve?")
    for h in (1, 3, 5, 10):
        if h in horizons:
            ex = get("down", 7, h, "excess_bps")
            wr = get("down", 7, h, "win_rate")
            tt = get("down", 7, h, "t_vs_base")
            verdict = "supports reversion" if (ex > 0 and wr > 0.5) else "no reversion edge"
            print(f"    fwd {h:>2}d : excess {ex:+7.1f} bps   win {wr:5.1%}   "
                  f"t {tt:+5.1f}   -> {verdict}")

    print("\n[2] By 9 in one direction, does it flip to continuation (trend)?")
    print("    down-streak excess return should fade / go negative as k rises;")
    print("    up-streak excess return should stay positive (trend persists).")
    h = args.chart_horizon
    if h in horizons:
        print(f"    (forward {h}-day excess, bps)")
        print(f"      {'k':>4} {'down':>9} {'up':>9}")
        for k in range(5, args.max_streak + 1):
            klab = f">={k}" if k == args.max_streak else f"{k}"
            print(f"      {klab:>4} {get('down', k, h, 'excess_bps'):>+9.1f} "
                  f"{get('up', k, h, 'excess_bps'):>+9.1f}")

    # ---------------------------------------------------------------------- chart
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        h = args.chart_horizon
        ks = sorted(res.streak.unique())
        dn = [get("down", k, h, "excess_bps") for k in ks]
        up = [get("up", k, h, "excess_bps") for k in ks]
        xl = [f">={int(k)}" if k == args.max_streak else str(int(k)) for k in ks]

        fig, ax = plt.subplots(figsize=(9, 5))
        ax.axhline(0, color="#6f7a87", lw=1)
        ax.plot(range(len(ks)), dn, "-o", color="#B23A1E", label="after DOWN streak")
        ax.plot(range(len(ks)), up, "-o", color="#1E3A5F", label="after UP streak")
        ax.axvline(list(ks).index(7) if 7 in ks else 0, color="#c9c2b5", ls="--", lw=1)
        ax.set_xticks(range(len(ks)))
        ax.set_xticklabels(xl)
        ax.set_xlabel("prior consecutive same-direction days (k)")
        ax.set_ylabel(f"excess fwd {h}-day return vs baseline (bps)")
        ax.set_title("Streak filter: forward return by prior streak length\n"
                     f"Norgate cross-section, {used:,} symbols, {dmin.date()}–{dmax.date()}")
        ax.legend()
        ax.grid(axis="y", color="#eef0f3")
        fig.tight_layout()
        png = f"{args.out_prefix}_forward_by_length.png"
        fig.savefig(png, dpi=150)
        print(f"\nsaved: {csv_path}")
        print(f"saved: {png}")
    except Exception as e:
        print(f"\nsaved: {csv_path}   (chart skipped: {e})")

    # ------------------------------------------------------------------- caveats
    print("""
CAVEATS (put these in the PR so Mo reads honest numbers):
  * Overlapping forward windows -> observations are autocorrelated, so t-stats
    OVERSTATE significance. Treat them as directional, not p-values.
  * Cross-sectional pooling assumes the effect is comparable across names.
  * Survivorship: this is only bias-free if parquet_data includes DELISTED
    symbols. ~36k names back to 1990 suggests it does -- worth confirming the
    export wasn't current-constituents-only.
  * Universe cleaned: #/$/&/@ symbols (indices, breadth lines, futures) dropped,
    $1 entry-price floor, forward returns winsorized to [-95%, +300%], and >50%
    single-day moves treated as breaks. Same cleaning applied to baseline and
    buckets so the excess is apples-to-apples. Uses 'Close' as stored (Norgate
    adjustment dependent).
  * In-sample by construction. This screens the idea; the forward test decides.
""")


if __name__ == "__main__":
    main()
