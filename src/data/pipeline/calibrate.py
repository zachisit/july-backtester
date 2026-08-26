"""Task 6 — overlap calibration (2026-04-08 .. 2026-04-22) + price-continuity
identity check (the second half of Task 2).

For every common_to_both symbol, compare Norgate (total-return) vs Polygon raw
on the same overlap dates. Expected: ratio == 1.0000 at the 04-22 anchor (proven
for KO/XLF). Used ONLY for calibration/audit — overlap rows are never stored in
merged/.

Outputs:
  audit/overlap_calibration.csv   per-symbol splice ratio + deviation + verdict
  audit/splice_ratio_report.csv   symbols whose anchor splice ratio != 1.0
  audit/join_gap_warnings.csv     date-coverage gaps between the two feeds
  audit/identity_review.csv       symbols failing the price-continuity identity check
"""
import os
import pandas as pd

from . import paths
from . import normalize

SEAM_TOL = 0.005        # |splice_ratio - 1| <= 0.5% => seam continuous
IDENTITY_LO, IDENTITY_HI = 0.5, 2.0   # ratio outside this anywhere => likely different security


def _norgate_overlap_close(symbol, overlap_dates):
    path = paths.norgate_path(symbol)
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path, columns=["Close"])
    df = df[df.index.isin(pd.DatetimeIndex(overlap_dates))]
    if df.empty:
        return None
    return df["Close"].astype(float)


def calibrate(common_df, overlap_dates, logger=None):
    overlap_dates = sorted(pd.Timestamp(d) for d in overlap_dates)
    anchor = paths.ANCHOR
    long_ov = normalize.load_long([d.strftime("%Y-%m-%d") for d in overlap_dates])
    poly_close = long_ov.pivot_table(index="date", columns="ticker", values="close")

    rows, gaps, ident = [], [], []
    n = 0
    for nsym, ptk in zip(common_df["symbol"], common_df["polygon_ticker"]):
        n_close = _norgate_overlap_close(nsym, overlap_dates)
        if n_close is None or ptk not in poly_close.columns:
            gaps.append({"symbol": nsym, "polygon_ticker": ptk,
                         "reason": "no_overlap_norgate" if n_close is None else "no_overlap_polygon"})
            continue
        p_close = poly_close[ptk].dropna()
        common_idx = n_close.index.intersection(p_close.index)
        if len(common_idx) == 0:
            gaps.append({"symbol": nsym, "polygon_ticker": ptk, "reason": "no_common_dates"})
            continue
        ratio = (n_close.reindex(common_idx) / p_close.reindex(common_idx)).replace([float("inf")], pd.NA).dropna()
        if ratio.empty:
            gaps.append({"symbol": nsym, "polygon_ticker": ptk, "reason": "all_nan_ratio"})
            continue
        splice = float(ratio.loc[anchor]) if anchor in ratio.index else float(ratio.iloc[-1])
        max_dev = float((ratio - 1.0).abs().max())
        seam_ok = abs(splice - 1.0) <= SEAM_TOL
        identity_ok = bool((ratio.between(IDENTITY_LO, IDENTITY_HI)).all())
        n_missing = len(set(overlap_dates) & set(n_close.index)) - len(common_idx)
        rows.append({
            "symbol": nsym, "polygon_ticker": ptk, "n_overlap_days": len(common_idx),
            "splice_ratio": round(splice, 6), "max_abs_dev": round(max_dev, 6),
            "anchor_norgate": round(float(n_close.get(anchor, float("nan"))), 4),
            "anchor_polygon": round(float(p_close.get(anchor, float("nan"))), 4),
            "seam_ok": seam_ok, "identity_ok": identity_ok,
        })
        if not seam_ok:
            ident.append({"symbol": nsym, "polygon_ticker": ptk, "splice_ratio": round(splice, 6),
                          "max_abs_dev": round(max_dev, 6),
                          "verdict": "identity_mismatch" if not identity_ok else "seam_offset"})
        n += 1
        if logger and n % 2000 == 0:
            logger.info(f"calibrated {n}")

    cal = pd.DataFrame(rows)
    paths.ensure_dirs()
    cal.to_csv(os.path.join(paths.AUDIT, "overlap_calibration.csv"), index=False)
    cal[~cal["seam_ok"]].to_csv(os.path.join(paths.AUDIT, "splice_ratio_report.csv"), index=False) \
        if not cal.empty else pd.DataFrame().to_csv(os.path.join(paths.AUDIT, "splice_ratio_report.csv"), index=False)
    pd.DataFrame(gaps).to_csv(os.path.join(paths.AUDIT, "join_gap_warnings.csv"), index=False)
    pd.DataFrame(ident).to_csv(os.path.join(paths.AUDIT, "identity_review.csv"), index=False)
    if logger:
        ok = int(cal["seam_ok"].sum()) if not cal.empty else 0
        logger.info(f"calibration: {len(cal)} compared, {ok} seam_ok, "
                    f"{len(gaps)} gaps, {len(ident)} identity/seam flags")
    return cal, gaps, ident


def passing_identity(cal):
    """Set of polygon tickers that pass the identity/seam check (safe to splice)."""
    if cal.empty:
        return set()
    return set(cal.loc[cal["seam_ok"] & cal["identity_ok"], "polygon_ticker"])
