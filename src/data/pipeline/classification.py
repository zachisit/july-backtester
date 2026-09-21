"""Task 1 — universe classification into the 8 buckets defined in MERGE_SPEC.md.

Two stages:
  * build_classification(grouped_presence=None) does the structural pass from the
    Norgate last-date table + Polygon reference universe. Polygon-only tickers are
    bucketed 'polygon_only_pending' until grouped-daily presence is known.
  * finalize_polygon_only(df, present_on_or_before_anchor) splits pending into
    polygon_only_new_listing (never traded <= anchor) vs polygon_only_coverage_gap.

`bucket` is the primary (mutually-exclusive) classification; `required_asset` is an
orthogonal boolean flag (a symbol can be common_to_both AND a required asset).
"""
import os
import pandas as pd

from . import paths
from .mapping import (
    match_norgate_to_polygon, norgate_heuristic_class, is_norgate_nontradeable,
)

BUCKETS = [
    "common_to_both",
    "norgate_only_delisted_keep",
    "norgate_only_review",
    "norgate_only_exclude_nontradeable",
    "polygon_only_new_listing",
    "polygon_only_coverage_gap",
    "polygon_only_exclude_nontradeable",
    "polygon_only_pending",          # interim, before grouped-daily presence is known
]


def _read_csv(path):
    return pd.read_csv(path, keep_default_na=False, na_values=[""])


def load_reference_tables():
    nor = _read_csv(paths.NORGATE_LAST_DATES_CSV)
    nor = nor[nor["symbol"].astype(str).str.len() > 0].copy()
    nor["symbol"] = nor["symbol"].astype(str)
    nor["last_date"] = pd.to_datetime(nor["last_date"])

    poly = _read_csv(paths.POLYGON_REFERENCE_CSV)
    poly = poly[poly["ticker"].astype(str).str.len() > 0].copy()
    poly["ticker"] = poly["ticker"].astype(str)
    return nor, poly


def _required_set():
    """All accepted spellings of the required-asset allow-list."""
    s = set()
    for a in paths.REQUIRED_STRATEGY_ASSETS:
        s.update({a, a.upper(), f"I:{a}", f"${a}", f"$I:{a}"})
    return s


def build_classification(grouped_presence=None):
    nor, poly = load_reference_tables()
    poly_tickers = set(poly["ticker"])
    poly_type = dict(zip(poly["ticker"], poly["type"].astype(str)))
    poly_market = dict(zip(poly["ticker"], poly["market"].astype(str)))
    poly_name = dict(zip(poly["ticker"], poly["name"].astype(str)))
    required = _required_set()

    rows = []
    matched_poly = set()

    # --- Norgate side ---
    for sym, last_date, sec_class in zip(nor["symbol"], nor["last_date"], nor["sec_class"]):
        is_active = last_date == paths.ANCHOR
        req = sym in required
        if is_norgate_nontradeable(sym):
            rows.append((sym, "norgate", "norgate_only_exclude_nontradeable", req,
                         last_date, "", sec_class, "norgate breadth/index"))
            continue
        # equity_or_etf
        if is_active:
            pmatch, _ = match_norgate_to_polygon(sym, poly_tickers)
            if pmatch is not None:
                matched_poly.add(pmatch)
                rows.append((sym, "both", "common_to_both", req, last_date,
                             pmatch, poly_type.get(pmatch, ""), "matched"))
            else:
                rows.append((sym, "norgate", "norgate_only_review", req, last_date,
                             "", norgate_heuristic_class(sym),
                             "active, no polygon match -> review"))
        else:
            rows.append((sym, "norgate", "norgate_only_delisted_keep", req, last_date,
                         "", "equity_or_etf", "delisted, keep full history"))

    # --- Polygon-only (stocks market, not matched by any Norgate symbol) ---
    for tk in poly["ticker"]:
        if tk in matched_poly:
            continue
        if poly_market.get(tk) != "stocks":
            continue   # indices-market handled via required allow-list only
        req = tk in required
        ptype = poly_type.get(tk, "")
        if ptype in paths.NONTRADEABLE_POLYGON_TYPES and not req:
            rows.append((tk, "polygon", "polygon_only_exclude_nontradeable", req,
                         pd.NaT, tk, ptype, poly_name.get(tk, "")))
        else:
            rows.append((tk, "polygon", "polygon_only_pending", req,
                         pd.NaT, tk, ptype, poly_name.get(tk, "")))

    df = pd.DataFrame(rows, columns=[
        "symbol", "source_feed", "bucket", "required_asset",
        "last_date", "polygon_ticker", "security_type", "note"])

    if grouped_presence is not None:
        df = finalize_polygon_only(df, grouped_presence)
    return df


def finalize_polygon_only(df, present_on_or_before_anchor):
    """Split polygon_only_pending using grouped-daily presence.

    present_on_or_before_anchor: set of polygon tickers that traded on/before ANCHOR.
    Present <= anchor -> coverage_gap (existed before cutoff). Absent -> new_listing.
    """
    pending = df["bucket"] == "polygon_only_pending"
    is_gap = df["polygon_ticker"].isin(present_on_or_before_anchor)
    df.loc[pending & is_gap, "bucket"] = "polygon_only_coverage_gap"
    df.loc[pending & ~is_gap, "bucket"] = "polygon_only_new_listing"
    return df


# --- per-bucket output files --------------------------------------------------
_BUCKET_FILES = {
    "norgate_only_delisted_keep": "norgate_delisted_kept.csv",
    "norgate_only_review": "norgate_only_review.csv",
    "norgate_only_exclude_nontradeable": "norgate_only_excluded_nontradeable.csv",
    "polygon_only_new_listing": "polygon_only_new_listings.csv",
    "polygon_only_coverage_gap": "polygon_only_coverage_gaps.csv",
    "polygon_only_exclude_nontradeable": "polygon_only_excluded_nontradeable.csv",
}


def write_classification(df):
    paths.ensure_dirs()
    main = os.path.join(paths.METADATA, "symbol_classification.csv")
    df.sort_values(["bucket", "symbol"]).to_csv(main, index=False)
    for bucket, fname in _BUCKET_FILES.items():
        sub = df[df["bucket"] == bucket].sort_values("symbol")
        sub.to_csv(os.path.join(paths.METADATA, fname), index=False)
    # required assets view (orthogonal flag)
    req = df[df["required_asset"]].sort_values("symbol")
    req.to_csv(os.path.join(paths.METADATA, "required_strategy_assets.csv"), index=False)
    return main


def summarize(df):
    counts = df["bucket"].value_counts().to_dict()
    return {b: int(counts.get(b, 0)) for b in BUCKETS}


if __name__ == "__main__":
    d = build_classification()
    write_classification(d)
    import json
    print(json.dumps(summarize(d), indent=2))
    print(f"required_asset rows: {int(d['required_asset'].sum())}")
