"""Task 4 — normalize Polygon grouped-daily JSON to the canonical schema and
write per-ticker patch files (with Option-A total-return adjustment applied).

Canonical patch schema (index = tz-naive NY market date at midnight):
    open, high, low, close, volume, vwap,
    source, security_type, adjustment_factor, adjustment_method, data_quality_status

OHLC and volume in the patch are CANONICAL (total-return continuous from the
2026-04-22 anchor). Raw price is recoverable as close / adjustment_factor.
Dates are tagged from the REQUESTED grouped-daily date (no ms-timestamp parsing),
so there is no timezone drift and no duplicate (ticker, date).
"""
import os
import pandas as pd

from . import paths
from . import polygon_io
from . import adjust


def load_long(date_strs):
    """Concatenate grouped-daily results for the given dates into a long frame:
    columns [date, ticker, open, high, low, close, volume, vwap]."""
    frames = []
    for ds in date_strs:
        data = polygon_io.load_raw_grouped(ds)
        if not data or not data.get("results"):
            continue
        r = pd.DataFrame(data["results"])
        r = r.rename(columns={"T": "ticker", "o": "open", "h": "high",
                              "l": "low", "c": "close", "v": "volume", "vw": "vwap"})
        keep = ["ticker", "open", "high", "low", "close", "volume"]
        if "vwap" in r.columns:
            keep.append("vwap")
        r = r[keep].copy()
        r["date"] = pd.Timestamp(ds)
        frames.append(r)
    if not frames:
        return pd.DataFrame(columns=["date", "ticker", "open", "high", "low",
                                     "close", "volume", "vwap"])
    out = pd.concat(frames, ignore_index=True)
    if "vwap" not in out.columns:
        out["vwap"] = pd.NA
    return out


def presence_on_or_before(date_strs):
    """Set of tickers that traded on any date <= the given dates (for new/gap split)."""
    seen = set()
    for ds in date_strs:
        data = polygon_io.load_raw_grouped(ds)
        if data and data.get("results"):
            seen.update(r["T"] for r in data["results"])
    return seen


def build_patch(universe, all_dates, patch_dates, last_date, sec_type_map, logger=None):
    """Write per-ticker patch parquet for every `universe` ticker present in the
    patch window. Returns (written_tickers, warnings_rows, patch_presence)."""
    paths.ensure_dirs()
    long_all = load_long(all_dates)          # incl. overlap + anchor (for div prev-close)
    long_patch = long_all[long_all["date"] > paths.ANCHOR].copy()
    splits_by, divs_by = adjust.load_corporate_actions(last_date)

    raw_close_by = {tk: sub.set_index("date")["close"]
                    for tk, sub in long_all.groupby("ticker")}

    written, warn_rows = [], []
    patch_presence = set(long_patch["ticker"].unique())
    targets = patch_presence & set(universe)
    n = 0
    for tk, sub in long_patch.groupby("ticker"):
        if tk not in targets:
            continue
        sub = sub.sort_values("date").drop_duplicates("date")
        dates = pd.DatetimeIndex(sub["date"])
        raw_close = raw_close_by.get(tk, pd.Series(dtype=float)).to_dict()
        pf, vf, method, warns = adjust.build_factors(
            dates, raw_close, splits_by.get(tk, []), divs_by.get(tk, []))

        df = pd.DataFrame(index=dates)
        df.index.name = "date"
        fac = pf.reindex(dates).values
        vfac = vf.reindex(dates).values
        for col in ("open", "high", "low", "close"):
            df[col] = sub[col].values * fac
        df["volume"] = sub["volume"].values * vfac
        df["vwap"] = (sub["vwap"].values * fac) if sub["vwap"].notna().any() else float("nan")
        df["source"] = "polygon"
        df["security_type"] = sec_type_map.get(tk, "")
        df["adjustment_factor"] = fac
        df["adjustment_method"] = method
        df["data_quality_status"] = "flagged" if warns else "ok"

        df.to_parquet(os.path.join(paths.POLYGON_PATCH, f"{tk}.parquet"))
        written.append(tk)
        for w in warns:
            warn_rows.append({"ticker": tk, **w})
        n += 1
        if logger and n % 2000 == 0:
            logger.info(f"patch written: {n}")
    if logger:
        logger.info(f"patch complete: {len(written)} tickers, {len(warn_rows)} warnings")
    return written, warn_rows, patch_presence
