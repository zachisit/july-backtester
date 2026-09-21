#!/usr/bin/env python3
"""Does the dead-money entry signal survive a volatility-normalised definition?

The absolute definition (|ret| < 2%) is confounded with ATR by construction:
ATR is the scale of returns, so a low-ATR name is mechanically more likely to
move less than any fixed threshold. Low ATR "predicting" dead money may be the
definition predicting itself -- the same shape as raw-SUE's small-EPS artifact.

Normalised definition: a trade is dead if it moved less than a fraction of what
its own entry volatility implies over its holding period,

    |ret| / (ATR_pct * sqrt(hold_days)) < threshold

with the threshold set so the dead count matches the absolute definition, so
the two are compared on the same base rate rather than different sample sizes.

Usage: python dead_money_normalised.py <trade_log.csv>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

FEATURES = ["entry_RSI_14", "entry_ATR_14_pct", "entry_SMA200_dist_pct",
            "entry_Volume_Spike"]
NQ = 5


def cliffs_delta(a, b):
    if len(a) == 0 or len(b) == 0:
        return float("nan")
    gt = (a[:, None] > b[None, :]).sum()
    lt = (a[:, None] < b[None, :]).sum()
    return float((gt - lt) / (len(a) * len(b)))


def report(df, dead, label, feats, alpha):
    print(f"\n  {'-'*66}\n  {label}   (dead: {int(dead.sum())} of {len(df)}, "
          f"{dead.mean()*100:.1f}%)\n  {'-'*66}")
    print(f"  {'feature':<24}{'dead med':>10}{'rest med':>10}{'p':>9}{'Cliff d':>9}  verdict")
    survivors = []
    for f in feats:
        a = df.loc[dead, f].dropna().to_numpy(float)
        b = df.loc[~dead, f].dropna().to_numpy(float)
        if len(a) < 5 or len(b) < 5:
            continue
        p = sps.mannwhitneyu(a, b, alternative="two-sided").pvalue
        d = cliffs_delta(a, b)
        if p < alpha:
            survivors.append(f)
        print(f"  {f:<24}{np.median(a):>10.3f}{np.median(b):>10.3f}"
              f"{p:>9.4f}{d:>+9.3f}  {'SEPARATES' if p < alpha else 'no'}")
    print(f"\n  {'ladder':<24}" + "".join(f"{'Q'+str(i+1):>8}" for i in range(NQ)))
    for f in feats:
        q = pd.qcut(df[f], NQ, labels=False, duplicates="drop")
        rates = [dead[q == i].mean() * 100 for i in sorted(pd.Series(q).dropna().unique())]
        print(f"  {f:<24}" + "".join(f"{r:>7.1f}%" for r in rates)
              + f"   span {max(rates)-min(rates):.1f}pp")
    return survivors


def main():
    df = pd.read_csv(Path(sys.argv[1]))
    for c in ("ProfitPct", "HoldDuration", "entry_ATR_14_pct"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["ProfitPct", "HoldDuration", "entry_ATR_14_pct"]).reset_index(drop=True)
    feats = [f for f in FEATURES if f in df.columns and df[f].notna().sum() > 50]
    alpha = 0.05 / len(feats)

    print(f"\n{'='*70}\n  DEAD MONEY -- ABSOLUTE vs VOLATILITY-NORMALISED DEFINITION\n{'='*70}")
    print(f"  trades {len(df)}   Bonferroni alpha = {alpha:.4f}")

    # confound check first
    rho, p = sps.spearmanr(df["entry_ATR_14_pct"], df["ProfitPct"].abs())
    print(f"\n  |return| vs entry ATR : Spearman rho {rho:+.3f} (p {p:.4f})")
    print("  ^ if positive, ATR IS the scale of returns and an absolute dead")
    print("    threshold is confounded with it by construction.")
    for f in feats:
        if f == "entry_ATR_14_pct":
            continue
        r2, _ = sps.spearmanr(df["entry_ATR_14_pct"], df[f])
        print(f"  entry ATR vs {f:<22} rho {r2:+.3f}")

    abs_dead = (df["HoldDuration"] >= 20) & (df["ProfitPct"].abs() < 0.02)
    s_abs = report(df, abs_dead, "ABSOLUTE: |ret| < 2%, held >= 20d", feats, alpha)

    # normalised: same base rate, so the comparison is like-for-like
    move_ratio = df["ProfitPct"].abs() / (df["entry_ATR_14_pct"] * np.sqrt(df["HoldDuration"]))
    eligible = df["HoldDuration"] >= 20
    thresh = move_ratio[eligible].quantile(abs_dead.sum() / eligible.sum())
    norm_dead = eligible & (move_ratio < thresh)
    s_norm = report(df, norm_dead, f"NORMALISED: |ret| < {thresh:.3f} x ATR x sqrt(days), held >= 20d",
                    feats, alpha)

    print(f"\n  overlap: {int((abs_dead & norm_dead).sum())} trades classed dead by both "
          f"(of {int(abs_dead.sum())} / {int(norm_dead.sum())})")
    print(f"\n  {'='*66}")
    print(f"  absolute definition separates : {s_abs or 'nothing'}")
    print(f"  normalised definition separates: {s_norm or 'nothing'}")
    lost = [f for f in s_abs if f not in s_norm]
    if lost:
        print(f"  -> LOST under normalisation: {lost}")
        print("     these were the definition predicting itself, not a signal.")
    if s_norm:
        print(f"  -> SURVIVES: {s_norm} -- worth pre-registering an entry filter on.")
    else:
        print("  -> nothing survives; the answer is an exit rule, not an entry filter.")
    print()


if __name__ == "__main__":
    main()
