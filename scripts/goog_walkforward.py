"""Rolling walk-forward evaluation of strategy families on GOOG.

Why this exists: a single in-sample/out-of-sample split is a single draw. The
overnight-drift candidate looked stable across thirteen in-sample years and
then died immediately in the holdout, which is exactly the failure a one-shot
split cannot warn you about.

Walk-forward refits each family's parameters on a trailing TRAIN window and
records performance only on the following TEST window, then rolls forward. Every
recorded return is therefore out-of-sample with respect to the parameters that
produced it, and the concatenated test returns are a realistic picture of what
the approach would actually have paid while being re-tuned as you went.

Families are fixed and deliberately few -- each extra family is another trial
against the same price series.
"""

import itertools
import os
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
warnings.filterwarnings("ignore")

from goog_oos_validate import load_goog, perf, RISK_FREE  # noqa: E402

TRAIN_YEARS = 5
TEST_YEARS = 1
SLIP_BPS = 5.0          # per side, on every change in exposure
ANNUAL = 252


# --------------------------------------------------------------------------
# Families: each returns a daily target-exposure series in [0, 1] from params.
# Every signal uses data up to and including bar t; execution is at t+1's open,
# handled by the shift in `apply_costs`.
# --------------------------------------------------------------------------
def fam_buyhold(df, **_):
    return pd.Series(1.0, index=df.index)


def fam_trend(df, span=200, **_):
    ma = df["Close"].rolling(int(span)).mean()
    return (df["Close"] > ma).astype(float)


def fam_voltarget(df, target=0.25, lookback=21, cap=1.0, **_):
    rv = df["Close"].pct_change().rolling(int(lookback)).std() * np.sqrt(ANNUAL)
    return (target / rv).clip(0.0, cap).fillna(0.0)


def fam_trend_voltarget(df, span=200, target=0.25, lookback=21, **_):
    return fam_trend(df, span=span) * fam_voltarget(df, target=target, lookback=lookback)


def fam_meanrev(df, down=3, hold=5, **_):
    r = df["Close"].pct_change()
    trig = (r < 0).rolling(int(down)).sum() >= int(down)
    return trig.astype(float).rolling(int(hold), min_periods=1).max().fillna(0.0)


FAMILIES = {
    "buy & hold":            (fam_buyhold, {}),
    "trend (SMA)":           (fam_trend, {"span": [50, 100, 150, 200, 250]}),
    "vol target":            (fam_voltarget, {"target": [0.20, 0.25, 0.30, 0.35],
                                              "lookback": [10, 21, 42]}),
    "trend x vol target":    (fam_trend_voltarget, {"span": [100, 200],
                                                    "target": [0.20, 0.25, 0.30],
                                                    "lookback": [21, 42]}),
    "mean reversion":        (fam_meanrev, {"down": [2, 3, 4], "hold": [3, 5, 10]}),
}


def apply_costs(df, expo, slip_bps=SLIP_BPS):
    """Exposure decided at close of t is held over bar t+1; charge turnover."""
    held = expo.shift(1).fillna(0.0).clip(0, 1)
    mkt = df["Close"].pct_change().fillna(0.0)
    turn = held.diff().abs().fillna(held.abs())
    return held * mkt - turn * (slip_bps / 1e4)


def score(ret):
    """Rank on Calmar, which is what we are actually trying to beat."""
    if ret.std() == 0 or len(ret) < 50:
        return -np.inf
    eq = (1 + ret).cumprod()
    yrs = len(ret) / ANNUAL
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    mdd = float((eq / eq.cummax() - 1).min())
    return cagr / abs(mdd) if mdd < 0 else -np.inf


def grid(params):
    if not params:
        return [{}]
    keys = list(params)
    return [dict(zip(keys, v)) for v in itertools.product(*(params[k] for k in keys))]


def walk_forward(df, verbose=True):
    years = sorted(df.index.year.unique())
    starts = [y for y in years if y - TRAIN_YEARS >= years[0]]
    results = {name: [] for name in FAMILIES}
    picks = {name: [] for name in FAMILIES}
    n_fits = 0

    for test_y in starts:
        tr = df[(df.index.year >= test_y - TRAIN_YEARS) & (df.index.year < test_y)]
        te_idx = df.index.year == test_y
        if len(tr) < 300 or te_idx.sum() < 100:
            continue
        # a warm-up tail is needed so rolling indicators are live on day 1 of test
        te = df[(df.index >= tr.index[0]) & (df.index.year <= test_y)]

        for name, (fn, pgrid) in FAMILIES.items():
            best, best_s = None, -np.inf
            for p in grid(pgrid):
                n_fits += 1
                r = apply_costs(tr, fn(tr, **p))
                s = score(r)
                if s > best_s:
                    best, best_s = p, s
            r_full = apply_costs(te, fn(te, **best))
            results[name].append(r_full[r_full.index.year == test_y])
            picks[name].append((test_y, best))

    out = {}
    for name, chunks in results.items():
        if not chunks:
            continue
        r = pd.concat(chunks).sort_index()
        eq = (1 + r).cumprod() * 100_000
        out[name] = perf(eq)
        out[name]["turnover_yrs"] = len(chunks)
    return out, picks, n_fits


if __name__ == "__main__":
    df = load_goog()
    out, picks, n_fits = walk_forward(df)
    print(f"=== WALK-FORWARD on GOOGL: train {TRAIN_YEARS}y / test {TEST_YEARS}y, rolling ===")
    print(f"    {SLIP_BPS:.0f}bp/side on every exposure change | {n_fits:,} parameter fits total")
    bh = out.get("buy & hold", {})
    print(f"\n  {'family':<22}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}{'vol':>8}{'folds':>7}")
    print("  " + "-" * 73)
    for name, s in sorted(out.items(), key=lambda kv: -kv[1].get("calmar", -9)):
        flag = ""
        if name != "buy & hold" and bh:
            if s["calmar"] > bh["calmar"] and s["sharpe"] > bh["sharpe"]:
                flag = "  <== beats B&H on both"
        print(f"  {name:<22}{s['cagr']:>9.2%}{s['sharpe']:>9.2f}{s['mdd']:>9.1%}"
              f"{s['calmar']:>9.2f}{s['vol']:>8.1%}{s['turnover_yrs']:>7}{flag}")

    print("\n  parameter stability (a family that re-picks wildly each fold is fitting noise):")
    for name, ps in picks.items():
        if not ps or not ps[0][1]:
            continue
        keys = list(ps[0][1])
        for k in keys:
            vals = [p[k] for _, p in ps]
            uniq = len(set(vals))
            print(f"    {name:<22} {k:<10} {uniq:>2} distinct values over {len(vals)} folds"
                  f"   {'STABLE' if uniq <= 3 else 'UNSTABLE'}")
