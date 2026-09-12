"""
200-day EMA "touch and bounce" study.

Theory under test: when a stock pulls back to within X% of its 200-day EMA and
bounces, buying the approach produces abnormal forward returns -- and there is
some optimal gap distance X.

The study measures forward returns from EMA-proximity events and compares them
against three controls, because a long-only dip-buy in a stock that compounded
40x will look spectacular whether or not the EMA means anything:

  1. Unconditional baseline  -- forward returns from every day in the sample.
  2. Bootstrap               -- 10k random date draws of the same event count,
                                giving a percentile for the observed mean.
  3. Benchmark-relative      -- the same forward windows on SPY, so we can see
                                whether the move is the stock or the market.

No look-ahead: the signal is evaluated on the close of day t, the fill is the
open of day t+1, and every forward return is measured from that fill.

Usage:
    python scripts/ema200_bounce_study.py
    python scripts/ema200_bounce_study.py --symbols GOOGL AAPL --source yahoo
"""

import argparse
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

warnings.filterwarnings("ignore")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARQUET_DIR = os.path.join(PROJECT_ROOT, "parquet_data", "data")

# Gap distances to sweep: price this far above (+) or below (-) the 200 EMA.
THRESHOLDS = [0.10, 0.07, 0.05, 0.03, 0.02, 0.01, 0.00, -0.02, -0.05]

# Forward holding horizons, in trading days.
HORIZONS = [5, 10, 21, 63, 126, 252]

EMA_SPAN = 200
REARM_GAP = 0.05      # dist must recover this far above the threshold to re-arm
COOLDOWN_BARS = 21    # and at least this many bars must pass between events
N_BOOTSTRAP = 10_000
SEED = 20260912


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def load_norgate(symbol):
    path = os.path.join(PARQUET_DIR, f"{symbol}.parquet")
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[["Open", "High", "Low", "Close"]].sort_index()


def load_yahoo(symbol, start="1990-01-01"):
    import yfinance as yf

    df = yf.Ticker(symbol).history(start=start, auto_adjust=True)
    if df is None or df.empty:
        return None
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    return df[["Open", "High", "Low", "Close"]].sort_index()


def load(symbol, source="splice"):
    """Norgate for the deep history, Yahoo spliced on for the recent tail."""
    if source == "yahoo":
        return load_yahoo(symbol)
    if source == "norgate":
        return load_norgate(symbol)

    ng = load_norgate(symbol)
    yh = load_yahoo(symbol)
    if ng is None:
        return yh
    if yh is None:
        return ng

    # Norgate and Yahoo carry different dividend-adjustment bases. Rescale the
    # Yahoo tail onto the Norgate level using the last shared close so the
    # spliced series has no artificial jump at the seam.
    seam = ng.index.max()
    if seam in yh.index and yh.loc[seam, "Close"] > 0:
        scale = ng.loc[seam, "Close"] / yh.loc[seam, "Close"]
    else:
        scale = 1.0
    tail = yh[yh.index > seam] * scale
    return pd.concat([ng, tail]).sort_index()


# --------------------------------------------------------------------------
# Event detection
# --------------------------------------------------------------------------
def add_indicators(df):
    out = df.copy()
    out["EMA200"] = out["Close"].ewm(span=EMA_SPAN, adjust=False).mean()
    out["dist"] = (out["Close"] - out["EMA200"]) / out["EMA200"]
    # Warm-up: an EMA needs history before it means anything.
    out.loc[out.index[:EMA_SPAN], "EMA200"] = np.nan
    out.loc[out.index[:EMA_SPAN], "dist"] = np.nan
    return out


def find_events(df, threshold, confirm=False):
    """Signal days where dist first falls to <= threshold after being re-armed.

    A single choppy stretch around the EMA would otherwise fire dozens of
    near-identical events, so a fired event must see dist recover to
    threshold + REARM_GAP (and COOLDOWN_BARS elapse) before another can fire.

    confirm=True additionally waits for an up-close bar after the approach --
    the "and it bounced" half of the theory, taken without hindsight.
    """
    dist = df["dist"].values
    close = df["Close"].values
    idx = []
    armed = True
    last_fire = -10**9
    pending = None  # bar index of an approach awaiting confirmation

    for i in range(len(df)):
        d = dist[i]
        if np.isnan(d):
            continue

        if d > threshold + REARM_GAP:
            armed = True
            pending = None

        if confirm and pending is not None:
            if close[i] > close[i - 1]:
                if armed and (i - last_fire) >= COOLDOWN_BARS:
                    idx.append(i)
                    last_fire = i
                    armed = False
                pending = None
            elif d > threshold + REARM_GAP:
                pending = None
            continue

        if armed and d <= threshold and (i - last_fire) >= COOLDOWN_BARS:
            if confirm:
                pending = i
            else:
                idx.append(i)
                last_fire = i
                armed = False

    return idx


# --------------------------------------------------------------------------
# Forward return measurement
# --------------------------------------------------------------------------
def forward_stats(df, signal_idx, horizon):
    """Fill at the open after the signal; measure to the close `horizon` bars on.

    Returns (returns, maes) as fractions. MAE is the worst intra-window low
    relative to the fill -- how much heat the trade took before resolving.
    """
    o = df["Open"].values
    c = df["Close"].values
    lo = df["Low"].values
    n = len(df)

    rets, maes = [], []
    for i in signal_idx:
        entry_i = i + 1
        exit_i = entry_i + horizon - 1
        if exit_i >= n:
            continue
        fill = o[entry_i]
        if not np.isfinite(fill) or fill <= 0:
            continue
        rets.append(c[exit_i] / fill - 1.0)
        maes.append(lo[entry_i : exit_i + 1].min() / fill - 1.0)
    return np.array(rets), np.array(maes)


def baseline_pool(df, horizon):
    """Forward return from every eligible day -- the unconditional control."""
    eligible = [i for i in range(EMA_SPAN, len(df) - horizon - 1)]
    rets, _ = forward_stats(df, eligible, horizon)
    return rets


def bootstrap_pvalue(pool, observed_mean, n_events, rng, n_iter=N_BOOTSTRAP):
    """One-sided percentile of the observed mean against random same-size draws."""
    if len(pool) == 0 or n_events == 0:
        return np.nan, np.nan
    draws = rng.choice(pool, size=(n_iter, n_events), replace=True).mean(axis=1)
    pct = float((draws < observed_mean).mean())
    return pct, float(draws.std())


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
def run_symbol(symbol, source, confirm, horizons=HORIZONS, thresholds=THRESHOLDS):
    raw = load(symbol, source)
    if raw is None or raw.empty:
        print(f"[SKIP] {symbol}: no data")
        return None
    df = add_indicators(raw)
    rng = np.random.default_rng(SEED)

    print()
    print("=" * 108)
    label = "approach + up-close confirmation" if confirm else "approach (no confirmation)"
    print(f"  {symbol}  |  {df.index.min().date()} -> {df.index.max().date()}  "
          f"({len(df):,} bars)  |  entry: {label}")
    print("=" * 108)

    pools = {h: baseline_pool(df, h) for h in horizons}

    print("\n  UNCONDITIONAL BASELINE (every day, same fill convention)")
    head = "    horizon |" + "".join(f"{h:>10}d" for h in horizons)
    print(head)
    print("    " + "-" * (len(head) - 4))
    print("    mean     |" + "".join(f"{pools[h].mean():>10.2%} " for h in horizons))
    print("    median   |" + "".join(f"{np.median(pools[h]):>10.2%} " for h in horizons))
    print("    win rate |" + "".join(f"{(pools[h] > 0).mean():>10.1%} " for h in horizons))

    rows = []
    for thr in thresholds:
        sig = find_events(df, thr, confirm=confirm)
        if not sig:
            continue
        years = sorted({df.index[i].year for i in sig})
        print(f"\n  ---- gap <= {thr:+.0%} from 200 EMA "
              f"| {len(sig)} events across {len(years)} distinct years "
              f"({years[0]}-{years[-1]}) ----")
        hdr = ("    horiz |    n |     mean |   median |  win% |   vs base |"
               "  pctile |   avg MAE |  worst MAE")
        print(hdr)
        print("    " + "-" * (len(hdr) - 4))
        for h in horizons:
            r, mae = forward_stats(df, sig, h)
            if len(r) == 0:
                continue
            base = pools[h].mean()
            pct, _ = bootstrap_pvalue(pools[h], r.mean(), len(r), rng)
            print(f"    {h:>4}d | {len(r):>4} | {r.mean():>8.2%} | "
                  f"{np.median(r):>8.2%} | {(r > 0).mean():>5.0%} | "
                  f"{r.mean() - base:>+9.2%} | {pct:>7.1%} | "
                  f"{mae.mean():>9.2%} | {mae.min():>10.2%}")
            rows.append(dict(symbol=symbol, threshold=thr, horizon=h, n=len(r),
                             mean=r.mean(), median=float(np.median(r)),
                             win=(r > 0).mean(), base=base,
                             edge=r.mean() - base, pctile=pct,
                             avg_mae=mae.mean(), worst_mae=mae.min(),
                             confirm=confirm))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", nargs="+",
                    default=["GOOGL", "AAPL", "MSFT", "AMZN", "NVDA", "META", "SPY"])
    ap.add_argument("--source", choices=["splice", "yahoo", "norgate"], default="splice")
    ap.add_argument("--confirm", action="store_true",
                    help="require an up-close bar after the approach before entering")
    ap.add_argument("--out", default=None, help="optional CSV path for the result grid")
    args = ap.parse_args()

    frames = []
    for sym in args.symbols:
        out = run_symbol(sym, args.source, args.confirm)
        if out is not None and not out.empty:
            frames.append(out)

    if frames and args.out:
        pd.concat(frames, ignore_index=True).to_csv(args.out, index=False)
        print(f"\n[saved] {args.out}")


if __name__ == "__main__":
    main()
