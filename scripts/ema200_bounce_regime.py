"""
200-day EMA bounce, conditioned on trend slope and volatility regime.

Follow-up to scripts/ema200_bounce_study.py, which found no edge in the raw
"price touches the 200 EMA" event. This version tests the narrower claim that
has an actual mechanism behind it: the touch only matters when the 200 EMA is
still sloping UP (the pullback is to support inside an intact trend) and
volatility is calm (the pullback is noise, not a regime change).

THE METHODOLOGICAL POINT THAT MAKES OR BREAKS THIS STUDY
--------------------------------------------------------
"Positive slope + low VIX" is a description of a bull market. Measured against
an unconditional baseline, ANY long entry inside that filter looks brilliant --
you would be crediting the EMA for the regime. So the baseline here is
REGIME-MATCHED: random days drawn only from days that pass the identical
slope + VIX filter. The reported edge is therefore:

    "buying an EMA touch in a calm uptrend"  vs  "buying a RANDOM DAY in a calm uptrend"

which is the only comparison that isolates the EMA itself.

Event definition follows what a human means by "it came down to the 200 EMA":
distance is measured from the bar's LOW by default (--touch low), since an
intraday probe of the average is the thing people see on the chart. The close
was +1.16% above GOOG's 200 EMA on 2026-09-09; the low was +0.32%.

No look-ahead: slope, VIX and distance are all evaluated on the close of the
signal bar; the fill is the next open; forward returns run from that fill.
"""

import argparse
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ema200_bounce_study import load, EMA_SPAN, REARM_GAP, COOLDOWN_BARS  # noqa: E402

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARQUET_DIR = os.path.join(PROJECT_ROOT, "parquet_data", "data")

THRESHOLDS = [0.05, 0.03, 0.02, 0.01, 0.00, -0.02]
HORIZONS = [5, 10, 21, 63, 126]
SLOPE_LOOKBACK = 21
N_BOOTSTRAP = 10_000
SEED = 20260912


# --------------------------------------------------------------------------
# Regime inputs
# --------------------------------------------------------------------------
def load_vix():
    """VIX from the Norgate submodule, spliced with Yahoo for the recent tail."""
    ng = None
    path = os.path.join(PARQUET_DIR, "$VIX.parquet")
    if os.path.exists(path):
        ng = pd.read_parquet(path)
        ng.index = pd.to_datetime(ng.index).tz_localize(None).normalize()
        ng = ng["Close"].sort_index()
    try:
        import yfinance as yf

        yh = yf.Ticker("^VIX").history(start="1990-01-01")
        yh.index = pd.to_datetime(yh.index).tz_localize(None).normalize()
        yh = yh["Close"].sort_index()
    except Exception:
        yh = None

    if ng is None:
        return yh
    if yh is None:
        return ng
    tail = yh[yh.index > ng.index.max()]
    return pd.concat([ng, tail]).sort_index()


def add_indicators(df, vix, touch="low"):
    out = df.copy()
    out["EMA200"] = out["Close"].ewm(span=EMA_SPAN, adjust=False).mean()

    ref = out["Low"] if touch == "low" else out["Close"]
    out["dist"] = (ref - out["EMA200"]) / out["EMA200"]

    # Trend: is the 200 EMA itself still rising over the last month?
    out["slope"] = out["EMA200"].pct_change(SLOPE_LOOKBACK)

    # Volatility regime, aligned to the signal bar (no look-ahead).
    out["VIX"] = vix.reindex(out.index).ffill() if vix is not None else np.nan

    warm = out.index[: EMA_SPAN + SLOPE_LOOKBACK]
    out.loc[warm, ["EMA200", "dist", "slope"]] = np.nan
    return out


def regime_mask(df, slope_min, vix_max):
    """Days passing the regime filter. NaN slope/VIX fails closed."""
    m = np.ones(len(df), dtype=bool)
    if slope_min is not None:
        m &= (df["slope"] > slope_min).fillna(False).values
    if vix_max is not None:
        m &= (df["VIX"] < vix_max).fillna(False).values
    return m


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------
def find_events(df, threshold, regime):
    """Re-armed EMA approaches that also pass the regime filter on the signal bar."""
    dist = df["dist"].values
    idx, armed, last_fire = [], True, -10**9
    for i in range(len(df)):
        d = dist[i]
        if np.isnan(d):
            continue
        if d > threshold + REARM_GAP:
            armed = True
        if armed and d <= threshold and (i - last_fire) >= COOLDOWN_BARS:
            last_fire, armed = i, False
            if regime[i]:
                idx.append(i)
    return idx


def forward_stats(df, signal_idx, horizon):
    o, c, lo = df["Open"].values, df["Close"].values, df["Low"].values
    n = len(df)
    rets, maes = [], []
    for i in signal_idx:
        e, x = i + 1, i + horizon
        if x >= n:
            continue
        fill = o[e]
        if not np.isfinite(fill) or fill <= 0:
            continue
        rets.append(c[x] / fill - 1.0)
        maes.append(lo[e : x + 1].min() / fill - 1.0)
    return np.array(rets), np.array(maes)


def matched_pool(df, regime, horizon):
    """THE CONTROL: every regime-passing day, same fill convention."""
    eligible = [i for i in range(EMA_SPAN + SLOPE_LOOKBACK, len(df) - horizon - 1)
                if regime[i]]
    r, mae = forward_stats(df, eligible, horizon)
    return r, mae


def bootstrap_pct(pool, observed, n_events, rng):
    if len(pool) < 30 or n_events == 0:
        return np.nan
    draws = rng.choice(pool, size=(N_BOOTSTRAP, n_events), replace=True).mean(axis=1)
    return float((draws < observed).mean())


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def run_symbol(sym, vix, touch, slope_min, vix_max, verbose=True):
    raw = load(sym, "splice" if verbose else "norgate")
    if raw is None or len(raw) < EMA_SPAN + 300:
        return []
    df = add_indicators(raw, vix, touch)
    regime = regime_mask(df, slope_min, vix_max)
    rng = np.random.default_rng(SEED)

    if verbose:
        print()
        print("=" * 104)
        print(f"  {sym}  |  {df.index.min().date()} -> {df.index.max().date()}  "
              f"|  touch={touch}  slope>{slope_min}  VIX<{vix_max}")
        print(f"  regime-passing days: {regime.sum():,} / {len(df):,} "
              f"({regime.mean():.1%} of the sample)")
        print("=" * 104)

    rows = []
    pools = {h: matched_pool(df, regime, h) for h in HORIZONS}

    if verbose:
        print("\n  REGIME-MATCHED BASELINE (random day inside the same filter)")
        print("    horizon |" + "".join(f"{h:>10}d" for h in HORIZONS))
        print("    mean    |" + "".join(f"{pools[h][0].mean():>10.2%} " for h in HORIZONS))
        print("    win rate|" + "".join(f"{(pools[h][0] > 0).mean():>10.1%} " for h in HORIZONS))

    for thr in THRESHOLDS:
        sig = find_events(df, thr, regime)
        if len(sig) < 5:
            continue
        if verbose:
            yrs = sorted({df.index[i].year for i in sig})
            print(f"\n  ---- low within {thr:+.0%} of 200 EMA, in-regime "
                  f"| {len(sig)} events, {len(yrs)} years ({yrs[0]}-{yrs[-1]}) ----")
            hdr = ("    horiz |    n |     mean | matched base |     edge |  pctile | "
                   " win% | evt MAE | base MAE")
            print(hdr)
            print("    " + "-" * (len(hdr) - 4))
        for h in HORIZONS:
            r, mae = forward_stats(df, sig, h)
            if len(r) < 5:
                continue
            b_ret, b_mae = pools[h]
            pct = bootstrap_pct(b_ret, r.mean(), len(r), rng)
            rows.append(dict(symbol=sym, touch=touch, threshold=thr, horizon=h,
                             n=len(r), mean=r.mean(), median=float(np.median(r)),
                             win=(r > 0).mean(), base=b_ret.mean(),
                             edge=r.mean() - b_ret.mean(), pctile=pct,
                             evt_mae=mae.mean(), base_mae=b_mae.mean(),
                             regime_frac=float(regime.mean())))
            if verbose:
                print(f"    {h:>4}d | {len(r):>4} | {r.mean():>8.2%} | "
                      f"{b_ret.mean():>12.2%} | {r.mean()-b_ret.mean():>+8.2%} | "
                      f"{pct:>6.1%} | {(r>0).mean():>5.0%} | {mae.mean():>7.2%} | "
                      f"{b_mae.mean():>8.2%}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+",
                    default=["GOOGL", "AAPL", "MSFT", "AMZN", "NVDA", "META", "SPY"])
    ap.add_argument("--symbols-file", default=None,
                    help="JSON list of tickers (overrides --symbols)")
    ap.add_argument("--touch", choices=["low", "close"], default="low")
    ap.add_argument("--slope-min", type=float, default=0.0,
                    help="min 21-bar %% change in the 200 EMA; omit filter with 'none'")
    ap.add_argument("--vix-max", type=float, default=20.0)
    ap.add_argument("--no-slope", action="store_true")
    ap.add_argument("--no-vix", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="suppress per-symbol tables")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    slope_min = None if args.no_slope else args.slope_min
    vix_max = None if args.no_vix else args.vix_max

    syms = args.symbols
    if args.symbols_file:
        with open(args.symbols_file) as f:
            syms = json.load(f)
        syms = [s["symbol"] if isinstance(s, dict) else s for s in syms]

    vix = load_vix()
    rows = []
    for i, s in enumerate(syms, 1):
        try:
            rows += run_symbol(s, vix, args.touch, slope_min, vix_max,
                               verbose=not args.quiet)
        except Exception as e:
            if not args.quiet:
                print(f"[SKIP] {s}: {e}")
        if args.quiet and i % 25 == 0:
            print(f"  ... {i}/{len(syms)} symbols, {len(rows)} cells", flush=True)

    if rows and args.out:
        pd.DataFrame(rows).to_csv(args.out, index=False)
        print(f"\n[saved] {args.out}  ({len(rows)} cells)")


if __name__ == "__main__":
    main()
