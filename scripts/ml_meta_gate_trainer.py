"""scripts/ml_meta_gate_trainer.py

ALT 2 — Train a binary classifier on ml_features.parquet to predict
trade win/loss from entry-time features. Goal: identify a meta-gate
that can filter out predictably bad entries from a champion strategy
to compress the R3 max-recovery gate without sacrificing R1.

Approach
--------
- Walk-forward train/test (chronological, no look-ahead).
- Three folds: train on year 0..N, test on year N+1..N+3.
- Model: HistGradientBoostingClassifier (sklearn, no extra deps).
- Diagnostics: ROC AUC, precision @ top-decile, calibration plot data,
  feature importance, counterfactual equity-curve impact when filtering
  the worst-decile-prob entries from the OOS trade log.

Usage
-----
    rtk .venv/bin/python scripts/ml_meta_gate_trainer.py \\
        path/to/ml_features.parquet \\
        --strategy "Williams R Weekly Trend (above-20) + SMA200" \\
        --output-dir output/alt2_ml_meta_gate

Outputs
-------
    <output-dir>/metrics.json          per-fold AUC, precision, baseline win rate
    <output-dir>/counterfactual.csv    filtered vs unfiltered OOS P&L by fold
    <output-dir>/feature_importance.csv

No new dependencies — uses pandas, numpy, scikit-learn already in
requirements.txt.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_features(path: str, strategy: Optional[str]) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if strategy is not None:
        df = df[df["Strategy"] == strategy].copy()
    df["EntryDate"] = pd.to_datetime(df["EntryDate"], errors="coerce")
    df = df.sort_values("EntryDate").reset_index(drop=True)
    df = df.dropna(subset=["EntryDate", "is_win"])
    return df


def _feature_matrix(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    feat_cols = sorted(c for c in df.columns if c.startswith("entry_"))
    X = df[feat_cols].copy()
    for c in feat_cols:
        X[c] = pd.to_numeric(X[c], errors="coerce")
    return X, feat_cols


def _walk_forward_folds(df: pd.DataFrame, n_folds: int = 3) -> list[tuple[pd.Index, pd.Index]]:
    """Chronological k-fold: each fold trains on all prior data, tests on next slice."""
    n = len(df)
    if n < n_folds * 30:
        return []
    fold_size = n // (n_folds + 1)
    folds = []
    for k in range(1, n_folds + 1):
        train_end = fold_size * k
        test_end = min(fold_size * (k + 1), n)
        train_idx = df.index[:train_end]
        test_idx = df.index[train_end:test_end]
        folds.append((train_idx, test_idx))
    return folds


def _train_fold(X_train, y_train, X_test, y_test):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import roc_auc_score

    model = HistGradientBoostingClassifier(
        max_iter=200, max_depth=6, learning_rate=0.05,
        l2_regularization=1.0, random_state=42,
    )
    model.fit(X_train, y_train)
    p_test = model.predict_proba(X_test)[:, 1]

    try:
        auc = float(roc_auc_score(y_test, p_test))
    except ValueError:
        auc = float("nan")

    return model, p_test, auc


def _precision_at_topk(p: np.ndarray, y: np.ndarray, k: float) -> float:
    if len(p) == 0:
        return float("nan")
    n_top = max(1, int(len(p) * k))
    top_idx = np.argsort(-p)[:n_top]
    return float(y[top_idx].mean())


def _counterfactual_pnl(df_test: pd.DataFrame, p_test: np.ndarray,
                        drop_quantile: float = 0.20) -> dict:
    """Counterfactual: drop entries with predicted P(win) in the lowest
    `drop_quantile` of the test fold. Sum remaining Profit. Compare to
    full-trade sum.
    """
    if len(df_test) == 0:
        return {"baseline_pnl": 0.0, "filtered_pnl": 0.0, "trades_dropped": 0}
    thresh = np.quantile(p_test, drop_quantile)
    keep = p_test > thresh
    baseline = float(df_test["Profit"].sum())
    filtered = float(df_test.loc[keep, "Profit"].sum())
    return {
        "baseline_pnl": baseline,
        "filtered_pnl": filtered,
        "trades_total": int(len(df_test)),
        "trades_dropped": int((~keep).sum()),
        "drop_threshold_prob": float(thresh),
        "delta_pnl": filtered - baseline,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("parquet_path", help="path to ml_features.parquet")
    p.add_argument("--strategy", default=None,
                   help="filter to this Strategy name (default: all strategies combined)")
    p.add_argument("--output-dir", default="output/alt2_ml_meta_gate")
    p.add_argument("--folds", type=int, default=3)
    p.add_argument("--drop-quantile", type=float, default=0.20,
                   help="counterfactual: drop bottom Q of predicted-win-prob trades")
    args = p.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[info] loading {args.parquet_path}")
    df = _load_features(args.parquet_path, args.strategy)
    print(f"[info] {len(df)} trades after filter (strategy={args.strategy!r})")
    if len(df) < 100:
        print("[warn] < 100 trades — results will be unreliable")

    print(f"[info] baseline win rate: {df['is_win'].mean():.3f}")
    print(f"[info] baseline total P&L: ${df['Profit'].sum():,.0f}")

    X, feat_cols = _feature_matrix(df)
    y = df["is_win"].astype(int).values
    print(f"[info] {len(feat_cols)} features: {feat_cols}")

    folds = _walk_forward_folds(df, n_folds=args.folds)
    if not folds:
        print("[err] not enough trades for walk-forward folds")
        sys.exit(1)

    fold_metrics = []
    counterfactuals = []
    importances_acc = pd.Series(0.0, index=feat_cols)

    for k, (train_idx, test_idx) in enumerate(folds, start=1):
        X_train, X_test = X.loc[train_idx], X.loc[test_idx]
        y_train, y_test = y[train_idx], y[test_idx]
        if len(X_test) == 0 or y_train.mean() in (0.0, 1.0):
            continue
        model, p_test, auc = _train_fold(X_train, y_train, X_test, y_test)
        prec_top10 = _precision_at_topk(p_test, y_test, k=0.10)
        prec_top25 = _precision_at_topk(p_test, y_test, k=0.25)
        base_rate = float(y_test.mean())

        cf = _counterfactual_pnl(df.loc[test_idx], p_test, args.drop_quantile)
        cf["fold"] = k
        counterfactuals.append(cf)

        fold_metrics.append({
            "fold": k,
            "train_n": int(len(X_train)),
            "test_n": int(len(X_test)),
            "train_start": str(df.loc[train_idx, "EntryDate"].min()),
            "train_end":   str(df.loc[train_idx, "EntryDate"].max()),
            "test_start":  str(df.loc[test_idx,  "EntryDate"].min()),
            "test_end":    str(df.loc[test_idx,  "EntryDate"].max()),
            "auc": auc,
            "precision_top10pct": prec_top10,
            "precision_top25pct": prec_top25,
            "baseline_win_rate": base_rate,
        })

        if hasattr(model, "feature_importances_"):
            importances_acc += pd.Series(model.feature_importances_, index=feat_cols)

    with open(out_dir / "metrics.json", "w") as fh:
        json.dump(fold_metrics, fh, indent=2)

    pd.DataFrame(counterfactuals).to_csv(out_dir / "counterfactual.csv", index=False)

    importances_mean = (importances_acc / max(1, len(fold_metrics))).sort_values(ascending=False)
    importances_mean.to_csv(out_dir / "feature_importance.csv", header=["mean_importance"])

    print("\n===== FOLD SUMMARY =====")
    for m in fold_metrics:
        print(
            f"  fold {m['fold']}: AUC={m['auc']:.3f}  "
            f"top10={m['precision_top10pct']:.3f} (base {m['baseline_win_rate']:.3f})  "
            f"n_test={m['test_n']}"
        )

    print("\n===== COUNTERFACTUAL (drop bottom {:.0%} of predicted-prob) =====".format(args.drop_quantile))
    for cf in counterfactuals:
        delta_pct = (cf["filtered_pnl"] - cf["baseline_pnl"]) / cf["baseline_pnl"] * 100 \
                    if cf["baseline_pnl"] != 0 else 0.0
        print(
            f"  fold {cf['fold']}: baseline=${cf['baseline_pnl']:>12,.0f}  "
            f"filtered=${cf['filtered_pnl']:>12,.0f}  delta={delta_pct:+.1f}%  "
            f"dropped={cf['trades_dropped']}/{cf['trades_total']}"
        )

    print(f"\n[info] outputs written to {out_dir}")
    print(f"  - metrics.json")
    print(f"  - counterfactual.csv")
    print(f"  - feature_importance.csv")


if __name__ == "__main__":
    main()
