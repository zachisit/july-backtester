#!/usr/bin/env python3
"""Is dead money predictable at ENTRY? (bull flag, issue #102 follow-up)

The #102 scan measured that 53 of 335 trades went nowhere for 21.9% of all
capital-days. The tempting next step is to fit an exit rule to that book -- but
the outcomes are already known, so any threshold chosen will look good on the
sample that motivated it. This asks the cheaper, prior question instead: were
the dead trades distinguishable from the live ones at the moment of entry,
using only the entry_* features the log already records?

If yes -> the answer is an entry FILTER (never commit the capital).
If no  -> the answer has to be an exit RULE, and that needs pre-registering.

Deliberately univariate with a multiple-testing correction. Fitting a
classifier to 335 rows with 4 features would find something whether or not
anything is there.

Endogeneity caveat, stated up front: "dead" is defined partly by hold duration,
and hold duration is capped by the strategy's own 20-bar time stop. So dead
means "survived to the time stop without moving", not "held forever".

Usage: python dead_money_entry.py <trade_log.csv>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats as sps

FEATURES = ["entry_RSI_14", "entry_ATR_14_pct", "entry_SMA200_dist_pct",
            "entry_Volume_Spike"]
DEAD_MIN_DAYS = 20
DEAD_MAX_ABS_RET = 0.02
NQ = 5


def cliffs_delta(a: np.ndarray, b: np.ndarray) -> float:
    """Non-parametric effect size in [-1, 1]. |d| < 0.147 is 'negligible'
    by the usual convention, which is the number that matters for a null."""
    n_a, n_b = len(a), len(b)
    if n_a == 0 or n_b == 0:
        return float("nan")
    gt = sum((a[:, None] > b[None, :]).sum(axis=1))
    lt = sum((a[:, None] < b[None, :]).sum(axis=1))
    return float((gt - lt) / (n_a * n_b))


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: dead_money_entry.py <trade_log.csv>")
    df = pd.read_csv(Path(sys.argv[1]))
    df["ProfitPct"] = pd.to_numeric(df["ProfitPct"], errors="coerce")
    df["HoldDuration"] = pd.to_numeric(df["HoldDuration"], errors="coerce")
    df = df.dropna(subset=["ProfitPct", "HoldDuration"]).reset_index(drop=True)

    dead = (df["HoldDuration"] >= DEAD_MIN_DAYS) & (df["ProfitPct"].abs() < DEAD_MAX_ABS_RET)
    df["dead"] = dead

    print(f"\n{'='*70}\n  DEAD MONEY -- PREDICTABLE AT ENTRY?\n{'='*70}")
    print(f"  trades          : {len(df)}")
    print(f"  dead (>={DEAD_MIN_DAYS}d, |ret|<{DEAD_MAX_ABS_RET:.0%}) : "
          f"{int(dead.sum())} ({dead.mean()*100:.1f}%)")
    print(f"  dead P&L        : ${df.loc[dead,'Profit'].sum():,.0f} of "
          f"${df['Profit'].sum():,.0f} total")
    print(f"  hold duration   : median {df['HoldDuration'].median():.0f}, "
          f"75th {df['HoldDuration'].quantile(.75):.0f}, "
          f"max {df['HoldDuration'].max():.0f}")

    feats = [f for f in FEATURES if f in df.columns and df[f].notna().sum() > 50]
    alpha = 0.05 / len(feats)
    print(f"\n  {'-'*66}")
    print(f"  Univariate: dead vs rest. Mann-Whitney U, Bonferroni alpha "
          f"= 0.05/{len(feats)} = {alpha:.4f}")
    print(f"  {'-'*66}")
    print(f"  {'feature':<24}{'dead med':>10}{'rest med':>10}{'p':>9}{'Cliff d':>9}  verdict")
    any_sig = False
    for f in feats:
        a = df.loc[dead, f].dropna().to_numpy(float)
        b = df.loc[~dead, f].dropna().to_numpy(float)
        if len(a) < 5 or len(b) < 5:
            continue
        p = sps.mannwhitneyu(a, b, alternative="two-sided").pvalue
        d = cliffs_delta(a, b)
        sig = p < alpha
        any_sig |= sig
        print(f"  {f:<24}{np.median(a):>10.3f}{np.median(b):>10.3f}"
              f"{p:>9.4f}{d:>+9.3f}  {'SEPARATES' if sig else 'no'}")

    print(f"\n  {'-'*66}")
    print(f"  Dead-rate ladder by feature quintile (flat = no signal)")
    print(f"  {'-'*66}")
    for f in feats:
        q = pd.qcut(df[f], NQ, labels=False, duplicates="drop")
        rates = [df.loc[q == i, "dead"].mean() * 100 for i in sorted(pd.Series(q).dropna().unique())]
        span = max(rates) - min(rates)
        print(f"  {f:<24}" + "".join(f"{r:>7.1f}%" for r in rates) + f"   span {span:.1f}pp")

    print(f"\n  {'-'*66}")
    print("  Same features vs the CONTINUOUS outcome (Spearman on ProfitPct)")
    print(f"  {'-'*66}")
    for f in feats:
        sub = df[[f, "ProfitPct"]].dropna()
        rho, p = sps.spearmanr(sub[f], sub["ProfitPct"])
        print(f"  {f:<24} rho {rho:+.3f}   p {p:.4f}"
              + ("   SEPARATES" if p < alpha else ""))

    print(f"\n  VERDICT: {'at least one entry feature separates -- entry filter is live' if any_sig else 'no entry feature separates dead from live at the corrected alpha'}")
    if not any_sig:
        print("  -> the answer cannot be an entry filter on these features;")
        print("     it has to be an exit rule, which needs pre-registering.")
    print()


if __name__ == "__main__":
    main()
