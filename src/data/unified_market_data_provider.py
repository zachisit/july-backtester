"""Task 9 — UnifiedMarketDataProvider.

The single read interface for the backtester. Reads data/market_data/merged/ ONLY.
The engine is agnostic to whether a row came from Norgate, Polygon, or a local
fallback; provenance (source / adjustment_factor / adjustment_method /
data_quality_status) is preserved internally and available via
get_with_provenance().

Drop-in data-provider compatibility: get_price_data(symbol, start, end, config)
returns Open/High/Low/Close/Volume with a tz-naive midnight DatetimeIndex named
'Datetime', matching the engine's fetcher contract.
"""
import os
import re
import glob
import json

import pandas as pd

from .pipeline import paths

_CANON = ["open", "high", "low", "close", "volume"]
_SUFFIX_RE = re.compile(r"-\d{6}$")  # delisted files carry a -YYYYMM suffix
_RENAME = {"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"}


class UnifiedMarketDataProvider:
    def __init__(self, merged_dir=None, metadata_dir=None):
        self.merged_dir = merged_dir or paths.MERGED
        self.metadata_dir = metadata_dir or paths.METADATA
        self._class = None
        self._range_cache = {}

    # ------------------------------------------------------------- internals ---
    def _candidate_paths(self, symbol):
        """All existing merged files that could be this symbol: bare/share-class
        variants first, then date-suffixed delisted files. Returns
        ``[(path, is_suffixed), ...]`` de-duplicated, order-preserving."""
        cands = []
        for c in (symbol, symbol.upper(), symbol.replace("/", "-"),
                  symbol.upper().replace(".", "-"), symbol.upper().replace("-", ".")):
            if c not in cands:
                cands.append(c)
        out, seen = [], set()
        for c in cands:
            p = os.path.join(self.merged_dir, f"{c}.parquet")
            if os.path.exists(p) and p not in seen:
                out.append((p, False)); seen.add(p)
        for c in cands:
            for h in glob.glob(os.path.join(self.merged_dir, f"{c}-*.parquet")):
                stem = os.path.splitext(os.path.basename(h))[0]
                if _SUFFIX_RE.search(stem) and h not in seen:
                    out.append((h, True)); seen.add(h)
        return out

    def _index_range(self, path):
        """(min_ts, max_ts) of a parquet's index, cached. (None, None) on error."""
        if path not in self._range_cache:
            try:
                idx = pd.read_parquet(path, columns=["close"]).index
                self._range_cache[path] = ((idx.min(), idx.max()) if len(idx)
                                           else (None, None))
            except Exception:
                self._range_cache[path] = (None, None)
        return self._range_cache[path]

    def _resolve(self, symbol, start_date=None, end_date=None):
        """Return the merged parquet path for a requested symbol, or None.

        DATE-AWARE: when a [start, end] window is given and several files share a
        base ticker (a recycled ticker — the delisted original AND a live namesake,
        e.g. historical JAVA/SNDK/LIFE vs today's company), pick the file whose data
        actually covers the requested window, NOT just whichever file matches the
        name. Without a window, falls back to the legacy preference: a bare
        (non-suffixed) exact file, else the most recent ``-YYYYMM`` delisted file.
        """
        paths_ = self._candidate_paths(symbol)
        if not paths_:
            return None
        if start_date is None and end_date is None:
            bare = [p for p, suf in paths_ if not suf]
            if bare:
                return bare[0]
            suff = sorted(p for p, suf in paths_ if suf)
            return suff[-1] if suff else None
        # date-aware scoring: most calendar-day overlap with [start, end],
        # tie-broken by "contains the start date", then by recency (later end).
        s = pd.Timestamp(start_date) if start_date is not None else pd.Timestamp.min
        e = pd.Timestamp(end_date) if end_date is not None else pd.Timestamp.max
        best, best_key = None, None
        for p, _suf in paths_:
            lo, hi = self._index_range(p)
            if lo is None:
                continue
            overlap = min(hi, e) - max(lo, s)
            overlap_days = overlap.days if overlap > pd.Timedelta(0) else -1
            key = (overlap_days, bool(lo <= s <= hi), hi)
            if best_key is None or key > best_key:
                best_key, best = key, p
        if best is not None:
            return best
        bare = [p for p, suf in paths_ if not suf]
        return bare[0] if bare else sorted(p for p, _ in paths_)[-1]

    def _read(self, symbol, start_date=None, end_date=None):
        p = self._resolve(symbol, start_date, end_date)
        if p is None:
            return None
        return pd.read_parquet(p)

    @staticmethod
    def _slice(df, start_date, end_date):
        if start_date is not None:
            df = df[df.index >= pd.Timestamp(start_date)]
        if end_date is not None:
            df = df[df.index <= pd.Timestamp(end_date)]
        return df

    # ------------------------------------------------------------- public API ---
    def get_price_data(self, symbol, start_date=None, end_date=None, config=None):
        """Engine-compatible OHLCV (Open/High/Low/Close/Volume, Datetime index)."""
        df = self._read(symbol, start_date, end_date)
        if df is None or df.empty:
            return None
        df = self._slice(df, start_date, end_date)
        if df.empty:
            return None
        out = df[_CANON].rename(columns=_RENAME).copy()
        out.index = pd.DatetimeIndex(out.index).normalize()
        out.index.name = "Datetime"
        return out

    def get_price_data_for_intervals(self, symbol, intervals, warmup_days=400,
                                     exit_buffer_days=10):
        """Resolve and combine the correct parquet file for each PIT spell."""
        frames = []
        warmup = pd.Timedelta(days=warmup_days)
        exit_buffer = pd.Timedelta(days=exit_buffer_days)
        for start, end in intervals or ():
            start = pd.Timestamp(start)
            end = pd.Timestamp(end)
            lo = start - warmup
            hi = end + exit_buffer
            df = self._read(symbol, lo, hi)
            if df is None or df.empty:
                continue
            piece = self._slice(df, lo, hi).copy()
            if not piece.empty:
                piece["_pit_era_priority"] = 0
                piece.loc[(piece.index >= start) & (piece.index <= end),
                          "_pit_era_priority"] = 2
                piece.loc[(piece.index > end) & (piece.index <= hi),
                          "_pit_era_priority"] = 1
                frames.append(piece)
        if not frames:
            return None
        df = pd.concat(frames)
        df["_pit_sort_index"] = df.index
        df = df.sort_values(["_pit_sort_index", "_pit_era_priority"])
        df = df[~df.index.duplicated(keep="last")]
        df = df.drop(columns=["_pit_sort_index", "_pit_era_priority"])
        out = df[_CANON].rename(columns=_RENAME).copy()
        out.index = pd.DatetimeIndex(out.index).normalize()
        out.index.name = "Datetime"
        return out

    def load_prices(self, symbols, start_date=None, end_date=None):
        """Return {symbol: OHLCV DataFrame} for the symbols that exist."""
        out = {}
        for s in symbols:
            df = self.get_price_data(s, start_date, end_date)
            if df is not None:
                out[s] = df
        return out

    def load_required_asset(self, symbol, start_date=None, end_date=None):
        """Required commodity/bond/FX/index asset (same store, may be index-named)."""
        return self.get_price_data(symbol, start_date, end_date)

    def get_with_provenance(self, symbol, start_date=None, end_date=None):
        """Full canonical schema including source / adjustment_factor / method / status."""
        df = self._read(symbol, start_date, end_date)
        if df is None or df.empty:
            return None
        return self._slice(df, start_date, end_date)

    # ------------------------------------------------ raw (unadjusted) price API ---
    def get_raw_price_data(self, symbol, start_date=None, end_date=None, config=None):
        """RAW (unadjusted) OHLC, NOT total-return adjusted.

        Canonical prices are forward-adjusted to the 2026-04-22 anchor, so after a
        post-anchor split/dividend they diverge from the unadjusted print. Use THIS
        when you need the raw unadjusted price (e.g. display or external comparison),
        never get_price_data. raw = canonical / adjustment_factor (per row). Volume is
        passed through unchanged (price factor does not reconstruct raw volume).
        Returns Open/High/Low/Close/Volume with a Datetime index, or None.
        """
        df = self._read(symbol, start_date, end_date)
        if df is None or df.empty:
            return None
        df = self._slice(df, start_date, end_date)
        if df.empty:
            return None
        factor = pd.to_numeric(df.get("adjustment_factor", 1.0), errors="coerce").fillna(1.0)
        factor = factor.replace(0.0, 1.0)
        out = pd.DataFrame(index=df.index)
        for lc, cc in (("open", "Open"), ("high", "High"), ("low", "Low"), ("close", "Close")):
            out[cc] = df[lc].astype("float64") / factor
        out["Volume"] = df["volume"].astype("float64")
        out.index = pd.DatetimeIndex(out.index).normalize()
        out.index.name = "Datetime"
        return out

    def get_execution_price(self, symbol, date, field="close"):
        """Scalar RAW price for `symbol` on the last bar on/before `date`.

        Returns a float (raw unadjusted price) or None if no bar exists
        on/before the date.
        """
        df = self._read(symbol, date, date)
        if df is None or df.empty:
            return None
        df = df[df.index <= pd.Timestamp(date)]
        if df.empty:
            return None
        row = df.iloc[-1]
        factor = row.get("adjustment_factor", 1.0)
        try:
            factor = float(factor)
        except (TypeError, ValueError):
            factor = 1.0
        if not factor:
            factor = 1.0
        return float(row[field]) / factor

    def load_universe(self, date, universe_name):
        """Symbols in a named ticker list that have data on/through `date`.

        universe_name may be a tickers_to_scan/*.json filename or a bucket name.
        """
        date = pd.Timestamp(date)
        symbols = self._universe_symbols(universe_name)
        live = []
        for s in symbols:
            p = self._resolve(s)
            if p is None:
                continue
            # cheap last-date check via the parquet (already small)
            try:
                idx = pd.read_parquet(p, columns=["close"]).index
            except Exception:
                continue
            if idx.min() <= date <= idx.max() or idx.max() >= date:
                live.append(s)
        return sorted(live)

    def _universe_symbols(self, universe_name):
        # named JSON list under tickers_to_scan/
        jpath = os.path.join(paths.ROOT, "tickers_to_scan", universe_name)
        if os.path.exists(jpath):
            with open(jpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else list(data)
        # otherwise treat as a classification bucket
        if self._class is None:
            self._class = pd.read_csv(
                os.path.join(self.metadata_dir, "symbol_classification.csv"),
                keep_default_na=False, na_values=[""])
        sub = self._class[self._class["bucket"] == universe_name]
        return sub["symbol"].astype(str).tolist()

    def available_symbols(self):
        return sorted(f[:-8] for f in os.listdir(self.merged_dir) if f.endswith(".parquet"))

    # --------------------------------------------------------- quality screen ---
    def quality_status(self, symbol):
        """Last-row data_quality_status for a symbol, or None if not found.
        Values: ok / review_no_patch / insufficient_history / identity_review /
        flagged."""
        df = self._read(symbol)
        if df is None or df.empty or "data_quality_status" not in df.columns:
            return None
        return str(df["data_quality_status"].iloc[-1])

    # NOT yet wired into the default backtest path — reserved for a future
    # data-quality-screen integration (see pit_enforcement 'Integration status').
    def filter_universe(self, symbols,
                        exclude_statuses=("insufficient_history", "review_no_patch",
                                          "identity_review", "flagged"),
                        min_bars=0, min_avg_dollar_volume=0.0, lookback=60):
        """Screen a symbol list for backtest fitness. Returns (kept, dropped) where
        dropped is ``{symbol: reason}``.

        - exclude_statuses: drop quarantined data. Defaults are FAIL-CLOSED and
          exclude new listings with too little history (#8), active Norgate names
          with no Polygon patch / stale at the anchor (#6), identity-flagged
          fail-closed names (#7), and seam/identity ``flagged`` rows held to
          history-only. Pass ``exclude_statuses=()`` to keep everything, or a
          narrower tuple (e.g. drop only ``insufficient_history``) to opt back in.
        - min_bars: drop series shorter than this (long-lookback strategies).
        - min_avg_dollar_volume: drop illiquid names (mean close*volume over the
          last `lookback` bars) — mitigates micro-cap anomalies (#12).
        Only the requested symbols are opened (cheap for a few-hundred-name
        universe; do not call on all 35k)."""
        exclude_statuses = set(exclude_statuses or ())
        kept, dropped = [], {}
        for s in symbols:
            df = self.get_with_provenance(s)
            if df is None or df.empty:
                dropped[s] = "no data"
                continue
            status = str(df["data_quality_status"].iloc[-1]) if "data_quality_status" in df else "ok"
            if status in exclude_statuses:
                dropped[s] = f"status={status}"
                continue
            if min_bars and len(df) < min_bars:
                dropped[s] = f"bars={len(df)}<{min_bars}"
                continue
            if min_avg_dollar_volume and {"close", "volume"} <= set(df.columns):
                tail = df.tail(lookback)
                adv = float((tail["close"] * tail["volume"]).mean())
                if adv < min_avg_dollar_volume:
                    dropped[s] = f"adv=${adv:,.0f}<${min_avg_dollar_volume:,.0f}"
                    continue
            kept.append(s)
        return kept, dropped

    def filter_membership_intervals(
            self, symbol, intervals,
            exclude_statuses=("insufficient_history", "review_no_patch",
                              "identity_review", "flagged"),
            tolerance_days=7):
        """Return complete, non-quarantined PIT spells plus an audit row per spell."""
        exclude_statuses = set(exclude_statuses or ())
        tolerance = pd.Timedelta(days=tolerance_days)
        kept, audit_rows = [], []

        for start, end in intervals or ():
            start, end = pd.Timestamp(start), pd.Timestamp(end)
            path = self._resolve(symbol, start, end)
            row = {
                "symbol": symbol,
                "spell_start": start.date().isoformat(),
                "spell_end": end.date().isoformat(),
                "path": os.path.basename(path) if path else "",
            }
            if path is None:
                row.update(action="drop", reason="no_file")
                audit_rows.append(row)
                continue

            lo, hi = self._index_range(path)
            if lo is None or hi is None:
                row.update(action="drop", reason="unreadable_file")
                audit_rows.append(row)
                continue
            row["data_start"] = lo.date().isoformat()
            row["data_end"] = hi.date().isoformat()

            missing_start = lo > start + tolerance
            missing_end = hi < end - tolerance
            if missing_start or missing_end:
                gaps = []
                if missing_start:
                    gaps.append("starts_after_join")
                if missing_end:
                    gaps.append("ends_before_leave")
                row.update(action="drop", reason="+".join(gaps))
                audit_rows.append(row)
                continue

            try:
                prov = pd.read_parquet(path, columns=["data_quality_status"])
            except Exception:
                prov = None
            statuses = set()
            if prov is not None and "data_quality_status" in prov.columns:
                relevant = prov[(prov.index >= start) & (prov.index <= end)]
                if relevant.empty:
                    relevant = prov
                statuses = {
                    str(v) for v in relevant["data_quality_status"].dropna().unique()
                }
            blocked = sorted(statuses & exclude_statuses)
            row["quality_statuses"] = ",".join(sorted(statuses))
            if blocked:
                row.update(action="drop", reason=f"status={','.join(blocked)}")
                audit_rows.append(row)
                continue

            kept.append((start, end))
            row.update(action="keep", reason="complete")
            audit_rows.append(row)

        return kept, audit_rows


# module-level singleton for drop-in use as a data provider
_PROVIDER = None


def _provider():
    global _PROVIDER
    if _PROVIDER is None:
        _PROVIDER = UnifiedMarketDataProvider()
    return _PROVIDER


def get_price_data(symbol, start_date=None, end_date=None, config=None):
    """Module-level fetcher matching services.* signature."""
    return _provider().get_price_data(symbol, start_date, end_date, config)


def get_price_data_for_intervals(symbol, intervals, warmup_days=400,
                                 exit_buffer_days=10):
    """Module-level PIT spell fetcher for the merged provider."""
    return _provider().get_price_data_for_intervals(
        symbol, intervals, warmup_days=warmup_days,
        exit_buffer_days=exit_buffer_days)
