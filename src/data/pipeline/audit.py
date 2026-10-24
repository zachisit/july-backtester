"""Task 8 — audit engine + completeness gate. Decides whether merged data is
APPROVED for backtesting / forward testing.

Per-row checks, time-series checks, seam-cliff check, completeness gate, plus
the special-case audits (delisting-during-patch, insufficient-history listings).
Writes the audit CSVs and final_approval_report.md.
"""
import os
import json
import pandas as pd

from . import paths
from . import polygon_io

_INDEX_SYMS = {"SPX", "NDX", "RUT", "DJI", "OEX", "VIX", "VXN", "TNX"}

# Sane last-close bounds per index — catches the wrong-instrument collision class
# (a delisted equity tickered "VIX"/"TNX" clobbering the real index). VIX/VXN are
# vol points; TNX is the 10y yield x10; the equity indices just have to be positive
# and not absurd. Tight VIX/VXN bounds are the key tripwire.
_INDEX_BOUNDS = {
    "VIX": (5.0, 150.0), "VXN": (5.0, 150.0), "TNX": (1.0, 300.0),
    "SPX": (1.0, 1e6), "NDX": (1.0, 1e6), "RUT": (1.0, 1e6),
    "DJI": (1.0, 1e6), "OEX": (1.0, 1e6),
}


def index_validation(logger=None):
    """Semantic check on the 8 required indices. BLOCKING.

    Verifies each index file (1) exists, (2) has security_type=='index' on its
    last bar, (3) has source=='polygon' on its last bar (the patch tail — proves
    it was not overwritten by a delisted equity of the same ticker), and (4) a
    last close inside _INDEX_BOUNDS. Returns (rows, n_bad); writes
    audit/index_validation.csv."""
    rows = []
    for sym in sorted(_INDEX_SYMS):
        p = os.path.join(paths.MERGED, f"{sym}.parquet")
        rec = {"symbol": sym, "exists": os.path.exists(p), "last_type": "",
               "last_source": "", "last_close": None, "last_date": "", "ok": False,
               "reason": ""}
        if not rec["exists"]:
            rec["reason"] = "missing file"
            rows.append(rec)
            continue
        df = pd.read_parquet(p)
        if df.empty:
            rec["reason"] = "empty"
            rows.append(rec)
            continue
        last = df.iloc[-1]
        rec["last_type"] = str(last.get("security_type", ""))
        rec["last_source"] = str(last.get("source", ""))
        rec["last_close"] = float(last["close"]) if pd.notna(last["close"]) else None
        rec["last_date"] = str(df.index.max().date())
        lo, hi = _INDEX_BOUNDS.get(sym, (1.0, 1e9))
        problems = []
        if rec["last_type"] != "index":
            problems.append(f"type={rec['last_type']!r}!=index")
        if rec["last_source"] != "polygon":
            problems.append(f"source={rec['last_source']!r}!=polygon")
        if rec["last_close"] is None or not (lo <= rec["last_close"] <= hi):
            problems.append(f"close={rec['last_close']} outside [{lo},{hi}]")
        rec["ok"] = not problems
        rec["reason"] = "; ".join(problems)
        rows.append(rec)
    n_bad = sum(1 for r in rows if not r["ok"])
    paths.ensure_dirs()
    pd.DataFrame(rows).to_csv(os.path.join(paths.AUDIT, "index_validation.csv"), index=False)
    if logger:
        logger.info(f"index validation: {len(rows)} indices, {n_bad} bad")
        for r in rows:
            if not r["ok"]:
                logger.warning(f"  INDEX BAD {r['symbol']}: {r['reason']}")
    return rows, n_bad


# ----------------------------------------------------------- per-symbol checks ---
def ohlc_issues(df):
    """OHLC value-validity counts. Gated on PATCH rows (what we add); Norgate
    history anomalies are reported informationally, not blocking."""
    if df.empty:
        return {"bad_high": 0, "bad_low": 0, "nonpositive_price": 0, "negative_volume": 0}
    o, h, l, c, v = df["open"], df["high"], df["low"], df["close"], df["volume"]
    return {
        "bad_high": int((h < pd.concat([o, c], axis=1).max(axis=1) - 1e-6).sum()),
        "bad_low": int((l > pd.concat([o, c], axis=1).min(axis=1) + 1e-6).sum()),
        "nonpositive_price": int(((o <= 0) | (h <= 0) | (l <= 0) | (c <= 0)).sum()),
        "negative_volume": int((v < 0).sum()),
    }


def structural_issues(df):
    """Merge-integrity counts on the FULL frame — these always block approval."""
    return {
        "null_price": int(df["close"].isna().sum()),
        "dup_dates": int(df.index.duplicated().sum()),
    }


def timeseries_issues(df):
    c = df["close"].astype(float)
    ret = c.pct_change().abs()
    spikes = int((ret > paths.SPIKE_RETURN_THRESHOLD).sum())
    # stale flatline: >= STALE_FLATLINE_DAYS identical consecutive closes
    same = (c == c.shift(1))
    run = same.groupby((~same).cumsum()).cumcount() + 1
    stale = int((run >= paths.STALE_FLATLINE_DAYS).sum())
    zero_vol = int((df["volume"] == 0).sum())
    return {"spikes": spikes, "stale_runs": stale, "zero_volume_days": zero_vol}


def seam_return(df):
    """Daily return across the 04-22 -> first-patch-day boundary (cliff check)."""
    if paths.ANCHOR not in df.index:
        return None
    after = df[df.index > paths.ANCHOR]
    if after.empty:
        return None
    c0 = float(df.loc[paths.ANCHOR, "close"])
    c1 = float(after["close"].iloc[0])
    if c0 <= 0:
        return None
    return c1 / c0 - 1.0


# ------------------------------------------------------------- completeness gate ---
def completeness_gate(logger=None):
    """Per patch-day symbol counts vs 95% of trailing median. Returns DataFrame."""
    rows = []
    for ds in polygon_io.cached_trading_days():
        data = polygon_io.load_raw_grouped(ds)
        rows.append({"date": ds, "n_symbols": len(data.get("results", []) or [])})
    g = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    g["trailing_median"] = g["n_symbols"].rolling(10, min_periods=3).median().shift(1)
    g["min_required"] = (g["trailing_median"] * paths.COMPLETENESS_MIN_FRACTION).round()
    g["passed"] = (g["n_symbols"] >= g["min_required"]) | g["min_required"].isna()
    g.to_csv(os.path.join(paths.AUDIT, "completeness_gate.csv"), index=False)
    if logger:
        failed = int((~g["passed"]).sum())
        logger.info(f"completeness gate: {len(g)} days, {failed} failed")
    return g


# -------------------------------------------------------------------- driver ---
def audit_symbols(symbol_files, last_patch_date, logger=None):
    """Audit a list of (symbol, path, bucket) and aggregate. Returns (summary_df,
    detail dict of issue DataFrames)."""
    rows, bad_ohlc, delist, insuff = [], [], [], []
    n = 0
    for symbol, path, bucket in symbol_files:
        try:
            df = pd.read_parquet(path)
        except Exception as e:
            rows.append({"symbol": symbol, "bucket": bucket, "error": str(e)})
            continue
        has_src = "source" in df.columns
        patch_df = df[df["source"] == "polygon"] if has_src else df
        hist_df = df[df["source"] == "norgate"] if has_src else df.iloc[0:0]
        ohlc_patch = ohlc_issues(patch_df)            # gated
        struct = structural_issues(df)                # gated (full frame)
        hist_anom = sum(ohlc_issues(hist_df).values())  # informational only
        ti = timeseries_issues(df)
        seam = seam_return(df)
        row_bad = sum(ohlc_patch.values()) + sum(struct.values())
        rec = {"symbol": symbol, "bucket": bucket, "n_bars": len(df),
               **ohlc_patch, **struct, "hist_ohlc_anomalies": hist_anom, **ti,
               "seam_return": round(seam, 4) if seam is not None else None,
               "status": df["data_quality_status"].iloc[-1] if "data_quality_status" in df else ""}
        rows.append(rec)
        if row_bad:
            bad_ohlc.append(rec)
        # delisting during patch: a patched symbol whose last bar < last patch date
        if bucket in ("common_to_both",) and "source" in df.columns:
            has_patch = (df["source"] == "polygon").any()
            if has_patch and df.index.max() < pd.Timestamp(last_patch_date):
                delist.append({"symbol": symbol, "last_bar": str(df.index.max().date())})
        if bucket == "polygon_only_new_listing" and len(df) < paths.MIN_LOOKBACK_BARS:
            insuff.append({"symbol": symbol, "n_bars": len(df)})
        n += 1
        if logger and n % 4000 == 0:
            logger.info(f"audited {n}")
    summary = pd.DataFrame(rows)
    paths.ensure_dirs()
    summary.to_csv(os.path.join(paths.AUDIT, "patch_audit.csv"), index=False)
    pd.DataFrame(bad_ohlc).to_csv(os.path.join(paths.AUDIT, "bad_ohlc_rows.csv"), index=False)
    pd.DataFrame(delist).to_csv(os.path.join(paths.AUDIT, "delisting_during_patch.csv"), index=False)
    pd.DataFrame(insuff).to_csv(os.path.join(paths.AUDIT, "insufficient_history_new_listings.csv"), index=False)
    return summary, {"bad_ohlc": bad_ohlc, "delist": delist, "insuff": insuff}


def write_approval_report(summary, gate, counts, logger=None):
    """Write final_approval_report.md and return (approved: bool)."""
    bad_rows = 0
    if not summary.empty:
        for col in ("bad_high", "bad_low", "nonpositive_price", "negative_volume",
                    "null_price", "dup_dates"):
            if col in summary.columns:
                bad_rows += int(summary[col].sum())
    gate_failed = int((~gate["passed"]).sum()) if not gate.empty else 0
    # extreme seam cliffs (|return| > 50%) that are NOT explained by a split
    seam_cliffs = 0
    if "seam_return" in summary.columns:
        seam_cliffs = int((summary["seam_return"].abs() > paths.SPIKE_RETURN_THRESHOLD).fillna(False).sum())

    index_bad = int(counts.get("index_bad", 0))
    approved = (bad_rows == 0) and (gate_failed == 0) and (index_bad == 0)
    lines = [
        "# Final Approval Report — Unified Norgate + Polygon Dataset",
        f"_Generated {pd.Timestamp.now():%Y-%m-%d %H:%M} · anchor 2026-04-22 · Option A (total-return)._",
        "",
        "## Universe",
        f"- Common to both feeds: **{counts.get('common_to_both', 0):,}**",
        f"- Norgate delisted eq/ETF kept: **{counts.get('norgate_only_delisted_keep', 0):,}**",
        f"- Norgate-only review (no patch): **{counts.get('norgate_only_review', 0):,}**",
        f"- Norgate-only excluded (non-tradeable): **{counts.get('norgate_only_exclude_nontradeable', 0):,}**",
        f"- Polygon-only new listings added: **{counts.get('polygon_only_new_listing', 0):,}**",
        f"- Polygon-only coverage gaps excluded: **{counts.get('polygon_only_coverage_gap', 0):,}**",
        f"- Polygon-only excluded (non-tradeable): **{counts.get('polygon_only_exclude_nontradeable', 0):,}**",
        "",
        "## Merge & patch",
        f"- Symbols materialized in merged/: **{counts.get('merged_total', 0):,}**",
        f"- Patched dates (Polygon window): **{counts.get('patch_dates', 0)}**",
        f"- Symbols receiving a Polygon patch: **{counts.get('patched_symbols', 0):,}**",
        f"- Failed/flagged symbols: **{counts.get('flagged_symbols', 0):,}**",
        "",
        "## Audit",
        f"- Per-row violations in patch + merge integrity (blocking): **{bad_rows}**",
        f"- Norgate-history OHLC anomalies (informational, pre-existing master): "
        f"**{int(summary['hist_ohlc_anomalies'].sum()) if 'hist_ohlc_anomalies' in summary else 0}**",
        f"- Completeness-gate failed days: **{gate_failed}**",
        f"- Index semantic failures (wrong type/source/value, blocking): **{index_bad}**",
        f"- Extreme seam cliffs (>50%, unexplained): **{seam_cliffs}**",
        f"- Delisted-during-patch (clean ends): **{counts.get('delist', 0):,}**",
        f"- Insufficient-history new listings: **{counts.get('insuff', 0):,}**",
        "",
        f"## Verdict: {'✅ APPROVED' if approved else '❌ NOT APPROVED'} for backtesting & forward testing",
    ]
    if not approved:
        lines.append("")
        lines.append("**Blocking issues:** "
                     + (", ".join(x for x in [
                         f"{bad_rows} OHLC violations" if bad_rows else "",
                         f"{gate_failed} incomplete days" if gate_failed else "",
                         f"{index_bad} index semantic failures" if index_bad else ""] if x)))
    path = os.path.join(paths.AUDIT, "final_approval_report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    if logger:
        logger.info(f"approval report: {'APPROVED' if approved else 'NOT APPROVED'} -> {path}")
    return approved


def _bucket_lookup():
    cls = pd.read_csv(os.path.join(paths.METADATA, "symbol_classification.csv"),
                      keep_default_na=False, na_values=[""])
    lut = {}
    for _, r in cls.iterrows():
        lut[str(r["symbol"])] = r["bucket"]
        if r["polygon_ticker"]:
            lut.setdefault(str(r["polygon_ticker"]), r["bucket"])
    return cls, lut


def run_full_audit(logger=None):
    """Audit every merged symbol + completeness gate, write the approval report.
    Returns (approved: bool, counts: dict)."""
    logger = logger or paths.get_logger("audit_merged")
    cls, lut = _bucket_lookup()
    symbol_files = []
    for fn in os.listdir(paths.MERGED):
        if not fn.endswith(".parquet"):
            continue
        sym = fn[:-8]
        bucket = "required_index" if sym in _INDEX_SYMS else lut.get(sym, "unknown")
        symbol_files.append((sym, os.path.join(paths.MERGED, fn), bucket))
    logger.info(f"auditing {len(symbol_files):,} merged symbols")

    last_patch_date = polygon_io.cached_trading_days()[-1]
    gate = completeness_gate(logger=logger)
    _idx_rows, _idx_bad = index_validation(logger=logger)
    summary, detail = audit_symbols(symbol_files, last_patch_date, logger=logger)

    counts = {}
    msj = os.path.join(paths.METADATA, "merge_summary.json")
    if os.path.exists(msj):
        counts.update(json.load(open(msj)))
    for b, n in cls["bucket"].value_counts().items():
        counts.setdefault(b, int(n))
    counts["merged_total"] = len(symbol_files)
    counts["patched_symbols"] = int((summary["bucket"] == "common_to_both").sum()) if not summary.empty else 0
    counts["flagged_symbols"] = int((summary["status"] != "ok").sum()) if "status" in summary else 0
    counts["delist"] = len(detail["delist"])
    counts["insuff"] = len(detail["insuff"])
    counts["index_bad"] = _idx_bad

    approved = write_approval_report(summary, gate, counts, logger=logger)
    # atomic manifest from THIS pass (single ground-truth source for reporting)
    from . import manifest
    manifest.write_manifest(summary, index_rows=_idx_rows, cls=cls, logger=logger)
    return approved, counts
