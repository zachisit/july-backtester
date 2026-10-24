"""Standalone scanner for triangle, rectangle, and inverse-H&S geometry.

Produces an HTML contact sheet and optional JSON with parameter and boundary
provenance. Historical replay selects bars before applying the lookback.
See docs/PATTERN_SCANNER.md for controls and the frozen review tape.
"""

import argparse
import base64
import io
import json
import logging
import math
import re
from html import escape
from pathlib import Path
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("pattern_scan")

# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

# A standalone corpus override. Tests freeze the bars independently of provider
# refreshes and adjustments; --as-of is applied before selecting the lookback.
PARQUET_DIR = os.environ.get(
    "PATTERN_SCAN_PARQUET_DIR",
    os.path.join(PROJECT_ROOT, "parquet_data", "data"),
)


def _finviz_universe(spec):
    """Ticker list from the finviz Elite screener export.

    `spec` is either a full elite.finviz.com/screener URL (the f=... filter
    string is extracted, including the | OR syntax) or a bare filter string
    like "geo_usa,ta_pattern_multipletop". Requires FINVIZ_AUTH in the
    environment or .env — the auth= value from the Elite export link.
    """
    import csv
    import urllib.parse
    import urllib.request

    def _env(key):
        val = os.environ.get(key)
        if not val:
            env_path = os.path.join(PROJECT_ROOT, ".env")
            if os.path.exists(env_path):
                for line in open(env_path, encoding="utf-8"):
                    if line.strip().startswith(key + "="):
                        val = line.strip().split("=", 1)[1].strip().strip("\"'")
        return val

    token = _env("FINVIZ_AUTH")
    cookie = _env("FINVIZ_COOKIE")  # .ASPXAUTH value — session fallback when no API token
    if not token and not cookie:
        raise SystemExit(
            "Set FINVIZ_AUTH=<api token> or FINVIZ_COOKIE=<.ASPXAUTH cookie value> in .env."
        )
    if spec.startswith("http"):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(spec).query)
        filters = qs.get("f", [""])[0]
        ft = qs.get("ft", [None])[0]
    else:
        filters, ft = spec, None
    params = {"v": "111", "f": filters}
    if ft:
        params["ft"] = ft
    if token:
        params["auth"] = token
    url = "https://elite.finviz.com/export.ashx?" + urllib.parse.urlencode(params, safe="|,")
    headers = {"User-Agent": "Mozilla/5.0"}
    if cookie and not token:
        headers["Cookie"] = f".ASPXAUTH={cookie}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            txt = response.read().decode("utf-8", "replace")
    except Exception:
        # HTTP exceptions may retain an authenticated request URL.
        raise SystemExit("Finviz export failed; check credentials and connectivity.") from None
    if txt.lstrip().startswith("<"):
        raise SystemExit("finviz export returned HTML, not CSV — auth token invalid/expired?")
    rows = list(csv.DictReader(io.StringIO(txt)))
    tickers = [r["Ticker"].strip() for r in rows if r.get("Ticker", "").strip()]
    log.info("finviz export: %d tickers for f=%s", len(tickers), filters)
    return tickers


def load_universe(universe_arg):
    """Resolve a universe argument to a ticker list.

    Accepts a JSON filename in tickers_to_scan/, a path to a JSON file, a
    comma-separated ticker string, a finviz Elite screener URL, or
    "finviz:<filter-string>".
    """
    if universe_arg.startswith("finviz:"):
        return _finviz_universe(universe_arg[len("finviz:"):])
    if universe_arg.startswith("http") and "finviz.com" in universe_arg:
        return _finviz_universe(universe_arg)
    candidate = os.path.join(PROJECT_ROOT, "tickers_to_scan", universe_arg)
    if os.path.exists(candidate):
        with open(candidate, encoding="utf-8") as f:
            return json.load(f)
    if os.path.exists(universe_arg):
        with open(universe_arg, encoding="utf-8") as f:
            return json.load(f)
    if universe_arg.lower().endswith(".json"):
        raise FileNotFoundError(
            f"Universe file not found: {universe_arg}. Generate us_liquid.json "
            "with scripts/build_us_universe.py, or choose an existing universe.")
    return [t.strip().upper() for t in universe_arg.split(",") if t.strip()]


def _cut_frame(df, as_of=None, lookback_bars=None):
    """Select the historical window before tailing, preserving its time zone."""
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("price frame requires a DatetimeIndex")
    df = df.sort_index()
    if as_of is not None:
        end = pd.Timestamp(as_of)
        if df.index.tz is not None:
            end = end.tz_localize(df.index.tz) if end.tzinfo is None else end.tz_convert(df.index.tz)
        elif end.tzinfo is not None:
            end = end.tz_localize(None)
        df = df.loc[df.index <= end]
    if lookback_bars is not None:
        df = df.tail(lookback_bars)
    if df.index.hasnans or df.index.has_duplicates:
        raise ValueError("price timestamps must be valid and unique")
    result = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    for column in result.columns:
        result[column] = pd.to_numeric(result[column], errors="raise")
    return result


def fetch_yahoo(tickers, period="2y", chunk=300, *, as_of=None, errors=None):
    """Download daily bars; historical scans request a window ending at as_of."""
    import yfinance as yf

    out = {}
    tickers = list(dict.fromkeys(tickers))
    aliases = {symbol: symbol.replace(".", "-") for symbol in tickers}
    window = {"period": period}
    if as_of is not None:
        end = pd.Timestamp(as_of)
        years = int(period[:-1]) if period.endswith("y") else 3
        window = {"start": (end - pd.DateOffset(years=years)).strftime("%Y-%m-%d"),
                  "end": (end + pd.Timedelta(days=1)).strftime("%Y-%m-%d")}
    for i in range(0, len(tickers), chunk):
        batch = tickers[i:i + chunk]
        try:
            raw = yf.download(list(dict.fromkeys(aliases[symbol] for symbol in batch)), interval="1d", group_by="ticker", auto_adjust=True,
                              threads=True, progress=False, **window)
        except Exception as exc:
            log.warning("Yahoo batch %d failed", i)
            if errors is not None:
                errors.update({symbol: type(exc).__name__ for symbol in batch})
            continue
        if not isinstance(raw.columns, pd.MultiIndex) and len(batch) != 1:
            if errors is not None:
                errors.update({symbol: "ambiguous download columns" for symbol in batch})
            continue
        for symbol in batch:
            try:
                frame = raw[aliases[symbol]] if isinstance(raw.columns, pd.MultiIndex) else raw
                frame = _cut_frame(frame.dropna(subset=["Close"]), as_of)
                if not frame.empty:
                    out[symbol] = frame
            except (KeyError, ValueError, TypeError) as exc:
                if errors is not None:
                    errors[symbol] = type(exc).__name__
    return out


def fetch_parquet(tickers, lookback_bars=500, *, as_of=None, parquet_dir=None, errors=None):
    """Read an explicit corpus; a corrupt symbol does not erase other results."""
    out = {}
    directory = Path(parquet_dir or PARQUET_DIR).expanduser()
    for symbol in dict.fromkeys(tickers):
        if not re.fullmatch(r"[A-Za-z0-9^][A-Za-z0-9.^_-]*", symbol):
            raise ValueError(f"invalid ticker: {symbol!r}")
        path = directory / f"{symbol}.parquet"
        if not path.is_file():
            continue
        try:
            frame = _cut_frame(pd.read_parquet(path), as_of, lookback_bars)
            if not frame.empty:
                out[symbol] = frame
        except Exception as exc:
            log.warning("Could not read %s: %s", symbol, type(exc).__name__)
            if errors is not None:
                errors[symbol] = type(exc).__name__
    return out


# ---------------------------------------------------------------------------
# Detection primitives
# ---------------------------------------------------------------------------


def compute_atr(df, length=14):
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(length).mean()


def find_pivots(df, k=4, atr=None, min_prominence_atr=0.3):
    """Rolling-window swing points.

    Bar i is a pivot high if High[i] is the max of the +/-k neighbourhood
    (ties broken to the leftmost bar), pivot low likewise. An ATR prominence
    floor drops micro-wiggles: the pivot must stand off the neighbourhood
    mean close by a fraction of ATR.
    """
    highs, lows = df["High"].values, df["Low"].values
    closes = df["Close"].values
    n = len(df)
    piv_hi, piv_lo = [], []
    for i in range(k, n - k):
        win_h = highs[i - k : i + k + 1]
        win_l = lows[i - k : i + k + 1]
        if highs[i] == win_h.max() and (win_h == highs[i]).argmax() == k:
            if atr is None or np.isnan(atr[i]) or highs[i] - closes[i - k : i + k + 1].mean() >= min_prominence_atr * atr[i]:
                piv_hi.append(i)
        if lows[i] == win_l.min() and (win_l == lows[i]).argmax() == k:
            if atr is None or np.isnan(atr[i]) or closes[i - k : i + k + 1].mean() - lows[i] >= min_prominence_atr * atr[i]:
                piv_lo.append(i)
    return piv_hi, piv_lo


def find_ceiling(df, piv_hi, atr, base_max=140, base_min=15, last_touch_within=30,
                 min_touches=2, tol_pct_floor=0.012, breakout_grace=1.007,
                 live_price=None, *, tol_atr_mult=0.6, return_details=False):
    """Cluster recent pivot highs into a flat resistance level.

    Returns (level, touch_indices) for the best cluster, or (None, None).
    Best = most touches, then longest span. The base must not contain a
    sustained close above the level (not already broken out); `breakout_grace`
    sets that veto (1.03 for rectangle/H&S — Roy-style confirm is boundary
    x1.03, so closes inside that zone are still pre-confirmation).

    `live_price`: a level being retested RIGHT NOW never has a recent pivot
    touch — pivot confirmation needs k right-side bars, so the live approach
    can't count. If the current price sits at/near the level (within -3%
    above to +10% below), the recency test is waived: proximity IS liveness.
    """
    n = len(df)
    closes = df["Close"].values
    recent = [i for i in piv_hi if i >= n - base_max]
    best = None
    for anchor in recent:
        lvl_anchor = df["High"].iloc[anchor]
        pct_tol = tol_pct_floor * lvl_anchor
        atr_tol = tol_atr_mult * (atr[anchor] if np.isfinite(atr[anchor]) else 0.)
        tol = max(pct_tol, atr_tol)
        details = {"anchor": anchor, "tolerance": float(tol),
                   "source": "percent" if pct_tol > atr_tol else "atr" if atr_tol > pct_tol else "both"}
        touches = [i for i in recent if abs(df["High"].iloc[i] - lvl_anchor) <= tol]
        if len(touches) < min_touches:
            continue
        span = max(touches) - min(touches)
        if span < base_min:
            continue
        level = float(np.mean([df["High"].iloc[i] for i in touches]))
        if max(touches) < n - last_touch_within:
            live = (live_price is not None
                    and -0.03 <= (level - live_price) / level <= 0.10)
            if not live:
                continue
        base_closes = closes[min(touches) : n]
        if (base_closes > level * breakout_grace).any():
            continue
        key = (len(touches), span)
        if best is None or key > best[0]:
            best = (key, level, sorted(touches), details)
    if best is None:
        return (None, None, None) if return_details else (None, None)
    return (best[1], best[2], best[3]) if return_details else (best[1], best[2])


def find_floor(df, piv_lo, atr, window_start, min_touches=2, tol_pct_floor=0.012,
               hold_grace=0.95, *, tol_atr_mult=0.6, return_details=False):
    """Cluster pivot lows inside the base into a flat support level (rectangle
    bottom). Mirror of find_ceiling. Returns (level, touch_indices) or None.
    Closes may pierce the floor by up to (1 - hold_grace) — long rectangles
    routinely wick through their lower boundary. The hold test spans the whole
    base (from `window_start`), not merely the touched span.
    """
    n = len(df)
    closes = df["Close"].values
    cand = [i for i in piv_lo if i >= window_start - 5]
    best = None
    for anchor in cand:
        lvl_anchor = df["Low"].iloc[anchor]
        pct_tol = tol_pct_floor * lvl_anchor
        atr_tol = tol_atr_mult * (atr[anchor] if np.isfinite(atr[anchor]) else 0.)
        tol = max(pct_tol, atr_tol)
        details = {"anchor": anchor, "tolerance": float(tol),
                   "source": "percent" if pct_tol > atr_tol else "atr" if atr_tol > pct_tol else "both"}
        touches = [i for i in cand if abs(df["Low"].iloc[i] - lvl_anchor) <= tol]
        if len(touches) < min_touches:
            continue
        level = float(np.mean([df["Low"].iloc[i] for i in touches]))
        # Veto over the WHOLE base, not just from the first floor touch. The
        # candidate population is selected from `window_start` (`cand`, above),
        # so anchoring the hold test at min(touches) leaves everything between
        # the base start and the first touch unchecked -- one landmark for the
        # population, a different one for the test applied to it. On MDLZ that
        # was 112 bars containing a close 9.2% under the level.
        # min(window_start, ...) because `cand` admits pivots at window_start-5.
        if (closes[min(window_start, min(touches)):n] < level * hold_grace).any():
            continue
        key = (len(touches), max(touches) - min(touches))
        if best is None or key > best[0]:
            best = (key, level, sorted(touches), details)
    if best is None:
        return None
    return (best[1], best[2], best[3]) if return_details else (best[1], best[2])


def find_rising_support(df, piv_lo, base_start, tol_atr, min_touches=2):
    """Best rising trendline through pivot lows inside the base.

    Tries every pair of base pivot lows; keeps lines with positive slope that
    no subsequent close violates (0.5% grace); scores by touches then span.
    Returns (slope, intercept, anchor_indices, touch_indices) or None.
    """
    n = len(df)
    lows = df["Low"].values
    closes = df["Close"].values
    base_lo = [i for i in piv_lo if i >= base_start - 3]
    if len(base_lo) < 2:
        return None
    best = None
    for a in range(len(base_lo) - 1):
        for b in range(a + 1, len(base_lo)):
            i, j = base_lo[a], base_lo[b]
            if j - i < 5:
                continue
            slope = (lows[j] - lows[i]) / (j - i)
            if slope <= 0:
                continue
            intercept = lows[i] - slope * i
            line = slope * np.arange(i, n) + intercept
            if (closes[i:n] < line * 0.995).any():
                continue
            touches = [p for p in base_lo if abs(lows[p] - (slope * p + intercept)) <= tol_atr]
            if len(touches) < min_touches:
                continue
            key = (len(touches), j - i)
            if best is None or key > best[0]:
                best = (key, slope, intercept, (i, j), touches)
    if best is None:
        return None
    return best[1], best[2], best[3], best[4]


# ---------------------------------------------------------------------------
# Pattern rule: ascending triangle as uptrend continuation
# ---------------------------------------------------------------------------


def detect_ascending_triangle(sym, df, spy_close, params, adv_dollar=None):
    """Full rule: ceiling + rising lows + uptrend context + proximity + liquidity.

    `adv_dollar` may be precomputed from daily bars (weekly resample path).
    Returns a candidate dict or None.
    """
    C = _common_gates(df, params, adv_dollar)
    if C is None:
        return None
    n, atr, close = C["n"], C["atr"], C["close"]
    last_close, last_atr = C["last_close"], C["atr"][-1]
    adv_dollar, piv_hi, piv_lo = C["adv"], C["piv_hi"], C["piv_lo"]
    level, touches, ceiling_details = find_ceiling(
        df, piv_hi, atr,
        base_max=params["base_max"], base_min=params["base_min"],
        last_touch_within=params["last_touch_within"],
        min_touches=params["min_touches"], live_price=last_close,
        tol_pct_floor=params["tol_pct_floor"], tol_atr_mult=params["tol_atr_mult"], return_details=True,
    )
    if level is None:
        return None
    base_start = touches[0]

    support = find_rising_support(df, piv_lo, base_start, tol_atr=0.8 * last_atr)
    if support is None:
        return None
    slope, intercept, anchors, sup_touches = support

    # apex not passed: support line still below the ceiling at the last bar
    if slope * (n - 1) + intercept >= level:
        return None

    # continuation context: meaningful advance into the base + rising SMA50
    lb = params["uptrend_lookback"]
    if base_start - lb < 0:
        return None
    gain_into_base = close.iloc[base_start] / close.iloc[base_start - lb] - 1.0
    if gain_into_base < params["uptrend_min_gain"]:
        return None
    sma50 = close.rolling(50).mean()
    if not (last_close > sma50.iloc[-1] and sma50.iloc[-1] > sma50.iloc[-21]):
        return None

    # measured move target: pattern height above the trigger
    trigger = float(max(df["High"].iloc[i] for i in touches))
    base_low = float(df["Low"].iloc[base_start:].min())
    height = level - base_low
    target = trigger + height

    # live and actionable: near the trigger, not broken out. The proximity
    # gate scales with pattern size — a 5-month triangle's last rising low
    # sits far deeper below its ceiling than a 3-week flag's (FCX ground
    # truth: 7.8% below trigger on the TechCharts call date). Explicit
    # --max-dist overrides the adaptive gate.
    max_dist = params["max_dist_to_trigger"]
    if max_dist is None:
        max_dist = float(np.clip(0.5 * height / trigger, 0.03, params["max_dist_cap"]))
    dist = (trigger - last_close) / trigger
    if dist < -0.01 or dist > max_dist:
        return None

    # ------- ranking score -------
    touch_score = min(len(touches), 4) / 4.0 * 25.0
    range10 = float(df["High"].tail(10).max() - df["Low"].tail(10).min())
    tight_score = 20.0 * float(np.clip(1.0 - range10 / (3.0 * last_atr), 0, 1))
    base_vol = df["Volume"].iloc[base_start:].mean()
    vol_ratio = float(df["Volume"].tail(10).mean() / base_vol) if base_vol > 0 else 1.0
    vol_score = 20.0 * float(np.clip((1.2 - vol_ratio) / 0.7, 0, 1))
    rs_score = 0.0
    rs_excess = None
    if spy_close is not None:
        spy_aligned = spy_close.reindex(df.index).ffill()
        w = min(120, n - 1)
        if (np.isfinite(spy_aligned.iloc[-w]) and spy_aligned.iloc[-w] > 0
                and np.isfinite(spy_aligned.iloc[-1]) and spy_aligned.iloc[-1] > 0):
            sym_ret = last_close / close.iloc[-w] - 1.0
            spy_ret = spy_aligned.iloc[-1] / spy_aligned.iloc[-w] - 1.0
            rs_excess = float(sym_ret - spy_ret)
            rs_score = 15.0 * float(np.clip(rs_excess / 0.20, 0, 1))
    prox_score = 20.0 * float(np.clip(1.0 - max(dist, 0) / max_dist, 0, 1))
    score = touch_score + tight_score + vol_score + rs_score + prox_score

    return {
        "symbol": sym,
        "pattern": "ascending_triangle",
        "ceiling_tolerance": ceiling_details["tolerance"],
        "ceiling_tolerance_source": ceiling_details["source"],
        "tf": params.get("tf", "D"),
        "score": round(score, 1),
        "level": level,
        "trigger": trigger,
        "confirm": level * 1.03,
        "target": target,
        "upside_pct": (target / trigger - 1.0) * 100,
        "dist_to_trigger_pct": dist * 100,
        "touches": touches,
        "n_touches": len(touches),
        "base_start": base_start,
        "base_days": n - 1 - base_start,
        "support": (slope, intercept),
        "support_anchors": anchors,
        "support_touches": sup_touches,
        "gain_into_base_pct": gain_into_base * 100,
        "vol_ratio": vol_ratio,
        "rs_excess_pct": None if rs_excess is None else rs_excess * 100,
        "adv_dollar": adv_dollar,
        "last_close": last_close,
        "df": df,
    }


def _common_gates(df, params, adv_dollar):
    """Shared preamble for every detector: history, ATR, liquidity, pivots.
    Returns a dict of primitives or None."""
    n = len(df)
    if n < params["min_bars"]:
        return None
    prices = df[["Open", "High", "Low", "Close"]].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or (prices <= 0).any():
        return None
    if not np.isfinite(df["Volume"]).all() or (df["Volume"] < 0).any():
        return None
    atr = compute_atr(df).values
    close = df["Close"]
    last_close = float(close.iloc[-1])
    if not np.isfinite(atr[-1]) or atr[-1] <= 0 or not np.isfinite(last_close) or last_close <= 0:
        return None
    if adv_dollar is None:
        adv_dollar = float((close * df["Volume"]).tail(20).mean())
    if not np.isfinite(adv_dollar) or adv_dollar < params["min_adv"]:
        return None
    piv_hi, piv_lo = find_pivots(df, k=params["pivot_k"], atr=atr)
    return {"n": n, "atr": atr, "close": close, "last_close": last_close,
            "adv": adv_dollar, "piv_hi": piv_hi, "piv_lo": piv_lo}


def _consolidation_common(sym, df, spy_close, params, C, level, touches, base_low,
                          pattern, extra):
    """Proximity gate, Roy-convention levels, and scoring shared by the
    rectangle and H&S-bottom rules. Returns the candidate dict or None.

    Consolidation convention: confirm = boundary x 1.03; target = boundary x
    (boundary / pattern low). Family scoring/convention reconciliation is #383.
    """
    n, close, last_close = C["n"], C["close"], C["last_close"]
    base_start = touches[0]
    trigger = float(max(df["High"].iloc[i] for i in touches))
    height = level - base_low
    max_dist = params["max_dist_to_trigger"]
    if max_dist is None:
        max_dist = float(np.clip(0.5 * height / trigger, 0.03, params["max_dist_cap"]))
    dist = (trigger - last_close) / trigger
    # allow closes up to the +3% confirm zone (Roy flags names sitting there)
    if dist < -0.03 or dist > max_dist:
        return None

    target = level * (level / base_low)

    touch_score = min(len(touches) + len(extra.get("floor_touches", [])), 6) / 6.0 * 25.0
    last_atr = C["atr"][-1]
    range10 = float(df["High"].tail(10).max() - df["Low"].tail(10).min())
    tight_score = 20.0 * float(np.clip(1.0 - range10 / (3.0 * last_atr), 0, 1))
    base_vol = df["Volume"].iloc[base_start:].mean()
    vol_ratio = float(df["Volume"].tail(10).mean() / base_vol) if base_vol > 0 else 1.0
    vol_score = 20.0 * float(np.clip((1.2 - vol_ratio) / 0.7, 0, 1))
    rs_score, rs_excess = 0.0, None
    if spy_close is not None:
        spy_aligned = spy_close.reindex(df.index).ffill()
        w = min(120, n - 1)
        if (np.isfinite(spy_aligned.iloc[-w]) and spy_aligned.iloc[-w] > 0
                and np.isfinite(spy_aligned.iloc[-1]) and spy_aligned.iloc[-1] > 0):
            rs_excess = float(last_close / close.iloc[-w] - spy_aligned.iloc[-1] / spy_aligned.iloc[-w])
            rs_score = 15.0 * float(np.clip(rs_excess / 0.20, 0, 1))
    prox_score = 20.0 * float(np.clip(1.0 - max(dist, 0) / max_dist, 0, 1))
    score = touch_score + tight_score + vol_score + rs_score + prox_score

    cand = {
        "symbol": sym,
        "pattern": pattern,
        "tf": params.get("tf", "D"),
        "score": round(score, 1),
        "level": level,
        "trigger": trigger,
        "confirm": level * 1.03,
        "target": target,
        "upside_pct": (target / trigger - 1.0) * 100,
        "dist_to_trigger_pct": dist * 100,
        "touches": touches,
        "n_touches": len(touches),
        "base_start": base_start,
        "base_days": n - 1 - base_start,
        "gain_into_base_pct": float(close.iloc[base_start] / close.iloc[max(base_start - params["uptrend_lookback"], 0)] - 1) * 100,
        "vol_ratio": vol_ratio,
        "rs_excess_pct": None if rs_excess is None else rs_excess * 100,
        "adv_dollar": C["adv"],
        "last_close": last_close,
        "df": df,
    }
    cand.update(extra)
    return cand


def detect_rectangle(sym, df, spy_close, params, adv_dollar=None):
    """Flat ceiling + flat floor holding for months (Roy: 6-22 month
    rectangles). No trend-context gate — his rectangles are both continuation
    and reversal structures; the human classifies from the chart."""
    C = _common_gates(df, params, adv_dollar)
    if C is None:
        return None
    level, touches, ceiling_details = find_ceiling(
        df, C["piv_hi"], C["atr"],
        base_max=params["base_max_long"], base_min=params["base_min_long"],
        last_touch_within=params["last_touch_within"],
        min_touches=params["min_touches_long"], breakout_grace=1.03,
        tol_pct_floor=params["tol_pct_floor"], tol_atr_mult=params["tol_atr_mult"], return_details=True,
        live_price=C["last_close"],
    )
    if level is None:
        return None
    floor = find_floor(
        df, C["piv_lo"], C["atr"], touches[0], min_touches=params["floor_min_touches"],
        tol_pct_floor=params["tol_pct_floor"], tol_atr_mult=params["tol_atr_mult"], return_details=True)
    if floor is None:
        return None
    floor_level, floor_touches, floor_details = floor
    if floor_level >= level or (level - floor_level) / level < 0.07:
        return None
    base_low = float(df["Low"].iloc[touches[0]:].min())
    return _consolidation_common(
        sym, df, spy_close, params, C, level, touches, base_low,
        "rectangle", {"floor_level": floor_level, "floor_touches": floor_touches,
         "ceiling_tolerance": ceiling_details["tolerance"],
         "ceiling_tolerance_source": ceiling_details["source"],
         "floor_tolerance": floor_details["tolerance"],
         "floor_tolerance_source": floor_details["source"]},
    )


def detect_hs_bottom(sym, df, spy_close, params, adv_dollar=None):
    """Horizontal neckline + a head (lowest low) in the middle of the base
    with distinctly higher lows either side (shoulders). Bullish reversal —
    the >=12% head depth below the neckline encodes the prior decline, so no
    separate trend gate."""
    C = _common_gates(df, params, adv_dollar)
    if C is None:
        return None
    level, touches, ceiling_details = find_ceiling(
        df, C["piv_hi"], C["atr"],
        base_max=params["base_max_long"], base_min=params["base_min_long"],
        last_touch_within=params["last_touch_within"],
        min_touches=params["min_touches_long"], breakout_grace=1.03,
        tol_pct_floor=params["tol_pct_floor"], tol_atr_mult=params["tol_atr_mult"], return_details=True,
        live_price=C["last_close"],
    )
    if level is None:
        return None
    n = C["n"]
    base_start = touches[0]
    lows = df["Low"].values
    span = n - base_start
    head_idx = base_start + int(np.argmin(lows[base_start:n]))
    head_low = float(lows[head_idx])
    if 1.0 - head_low / level < 0.12:
        return None
    edge = max(3, int(0.15 * span))
    if not (base_start + edge < head_idx < n - edge):
        return None
    gap = max(3, int(0.10 * span))
    left_min = float(lows[base_start : head_idx - gap + 1].min()) if head_idx - gap > base_start else None
    right_min = float(lows[head_idx + gap : n].min()) if head_idx + gap < n else None
    if left_min is None or right_min is None:
        return None
    if left_min < head_low * 1.03 or right_min < head_low * 1.03:
        return None  # head must be distinctly the lowest point
    return _consolidation_common(
        sym, df, spy_close, params, C, level, touches, head_low,
        "hs_bottom", {"head_idx": head_idx, "head_low": head_low,
                      "ceiling_tolerance": ceiling_details["tolerance"],
                      "ceiling_tolerance_source": ceiling_details["source"]},
    )


DETECTORS = {
    "ascending_triangle": detect_ascending_triangle,
    "rectangle": detect_rectangle,
    "hs_bottom": detect_hs_bottom,
}

PATTERN_NAMES = {
    "ascending_triangle": "Ascending Triangle",
    "rectangle": "Rectangle",
    "hs_bottom": "H&S Bottom",
}


# ---------------------------------------------------------------------------
# Chart rendering (dark, finviz-style)
# ---------------------------------------------------------------------------

DARK_BG = "#181c27"
PANEL_BG = "#141824"
GRID = "#2a3040"
TEXT = "#c8cede"
UP = "#26a69a"
DOWN = "#ef5350"
CEIL_COLOR = "#c96bde"
SUP_COLOR = "#4aa8e0"
TARGET_COLOR = "#7ac26e"
SMA20_C = "#c25fbc"
SMA50_C = "#d9932f"


def render_chart(cand, show_bars=170):
    """Render an annotated candlestick PNG; returns base64 string."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = cand["df"]
    n = len(df)
    start = max(0, min(n - show_bars, cand["base_start"] - 20))
    sub = df.iloc[start:]
    x = np.arange(len(sub))
    off = start  # index offset between full-df bar indices and plot x

    fig = plt.figure(figsize=(11.5, 5.8), dpi=105, facecolor=DARK_BG)
    try:
        gs = fig.add_gridspec(2, 1, height_ratios=[4, 1], hspace=0.04)
        ax = fig.add_subplot(gs[0])
        axv = fig.add_subplot(gs[1], sharex=ax)
        for a in (ax, axv):
            a.set_facecolor(PANEL_BG)
            a.grid(color=GRID, linewidth=0.5, alpha=0.6)
            a.tick_params(colors=TEXT, labelsize=8)
            for s in a.spines.values():
                s.set_color(GRID)

        o, h, l, c = (sub[col].values for col in ("Open", "High", "Low", "Close"))
        up_mask = c >= o
        ax.vlines(x, l, h, color=np.where(up_mask, UP, DOWN), linewidth=0.7)
        ax.bar(x[up_mask], (c - o)[up_mask], bottom=o[up_mask], width=0.65, color=UP)
        ax.bar(x[~up_mask], (o - c)[~up_mask], bottom=c[~up_mask], width=0.65, color=DOWN)

        for length, col in ((20, SMA20_C), (50, SMA50_C)):
            sma = df["Close"].rolling(length).mean().iloc[start:]
            ax.plot(x, sma.values, color=col, linewidth=1.0, alpha=0.9)

        # ceiling from first touch to right edge
        first_t = max(cand["touches"][0] - off, 0)
        ax.hlines(cand["level"], first_t, len(sub) - 1 + 3, color=CEIL_COLOR, linewidth=1.4)
        for t in cand["touches"]:
            if t >= off:
                ax.plot(t - off, df["High"].iloc[t], marker="v", color=CEIL_COLOR, markersize=5)

        # pattern-specific structure below the ceiling
        if "support" in cand:  # ascending triangle: rising-lows trendline
            slope, intercept = cand["support"]
            a0 = cand["support_anchors"][0]
            xs = np.arange(max(a0, off), n + 3)
            ax.plot(xs - off, slope * xs + intercept, color=SUP_COLOR, linewidth=1.4)
            for t in cand["support_touches"]:
                if t >= off:
                    ax.plot(t - off, df["Low"].iloc[t], marker="^", color=SUP_COLOR, markersize=5)
        if "floor_level" in cand:  # rectangle: flat lower boundary
            first_f = max(cand["floor_touches"][0] - off, 0)
            ax.hlines(cand["floor_level"], first_f, len(sub) - 1 + 3, color=SUP_COLOR, linewidth=1.4)
            for t in cand["floor_touches"]:
                if t >= off:
                    ax.plot(t - off, df["Low"].iloc[t], marker="^", color=SUP_COLOR, markersize=5)
        if "head_idx" in cand:  # H&S bottom: mark the head
            h = cand["head_idx"]
            if h >= off:
                ax.plot(h - off, cand["head_low"], marker="^", color=TARGET_COLOR, markersize=7)
                ax.annotate("H", (h - off, cand["head_low"]), xytext=(0, -14),
                            textcoords="offset points", ha="center", color=TARGET_COLOR, fontsize=8)

        # trigger + measured target (far targets annotated, not drawn, so the
        # candles aren't squished — NUTX-style log targets can be 2.5x price)
        hi = float(sub["High"].max())
        draw_target = cand["target"] <= hi * 1.35
        xr = len(sub) + 3
        if draw_target:
            ax.axhline(cand["target"], color=TARGET_COLOR, linewidth=1.1, linestyle="--", alpha=0.9)
            ax.annotate(f" target {cand['target']:.2f} (+{cand['upside_pct']:.1f}%)",
                        (xr, cand["target"]), xytext=(2, 8), textcoords="offset points",
                        color=TARGET_COLOR, fontsize=8, va="bottom")
        else:
            ax.text(0.995, 0.975, f"target {cand['target']:.2f} (+{cand['upside_pct']:.1f}%) ↑ off-scale",
                    transform=ax.transAxes, ha="right", va="top", color=TARGET_COLOR, fontsize=8)
        ax.axhline(cand["trigger"], color=CEIL_COLOR, linewidth=.8, linestyle=":", alpha=.65)
        ax.annotate(f" trigger {cand['trigger']:.2f}\n confirm {cand['confirm']:.2f}",
                    (xr, cand["trigger"]), xytext=(2, -8), textcoords="offset points",
                    color=CEIL_COLOR, fontsize=8, va="top")

        ax.set_xlim(-2, len(sub) + 16)
        ymin = float(sub["Low"].min()) * 0.985
        ymax = (max(hi, cand["target"]) if draw_target else hi) * 1.015
        ax.set_ylim(ymin, ymax)
        plt.setp(ax.get_xticklabels(), visible=False)

        axv.bar(x, sub["Volume"].values, width=0.65,
                color=np.where(up_mask, UP, DOWN), alpha=0.55)
        axv.set_yticks([])

        # month tick labels on bar index axis (no weekend gaps)
        months = pd.Series(sub.index.strftime("%b %y"), index=x)
        ticks = [i for i in x[1:] if months[i] != months[i - 1]]
        if len(ticks) > 16:  # weekly charts span years — thin the labels
            ticks = ticks[:: max(1, len(ticks) // 12)]
        fmt = "%b %y" if cand.get("tf") == "W" else "%b"
        axv.set_xticks(ticks)
        axv.set_xticklabels([sub.index[i].strftime(fmt) for i in ticks], color=TEXT)

        unit = "w" if cand.get("tf") == "W" else "d"
        pname = PATTERN_NAMES.get(cand.get("pattern", "ascending_triangle"), cand.get("pattern"))
        ax.set_title(
            f"{cand['symbol']}  —  {pname} ({cand.get('tf', 'D')})   "
            f"score {cand['score']}   base {cand['base_days']}{unit}   "
            f"{cand['n_touches']} touches   ADV ${cand['adv_dollar'] / 1e6:,.0f}M",
            color=TEXT, fontsize=10, loc="left",
        )

        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=DARK_BG, bbox_inches="tight")
        return base64.b64encode(buf.getvalue()).decode("ascii")
    finally:
        plt.close(fig)


# ---------------------------------------------------------------------------
# HTML contact sheet
# ---------------------------------------------------------------------------


def build_html(cands, meta, out_path):
    rows = []
    for rank, c in enumerate(cands, 1):
        symbol = escape(str(c["symbol"]))
        try:
            img = render_chart(c)
            chart = f'<img src="data:image/png;base64,{img}" alt="{symbol} chart"/>'
        except Exception as exc:
            log.warning("Chart unavailable for %s: %s", c["symbol"], type(exc).__name__)
            meta["chart_errors"] = meta.get("chart_errors", 0) + 1
            chart = "<p>Chart unavailable; the detected levels are listed above.</p>"
        rs = "n/a" if c["rs_excess_pct"] is None else f"{c['rs_excess_pct']:+.1f}%"
        rows.append(f"""
<div class="card">
  <div class="head">
    <span class="rank">#{rank}</span>
    <span class="sym">{symbol}</span>
    <span class="pat">{escape(PATTERN_NAMES.get(c.get('pattern', ''), ''))} ({escape(str(c.get('tf', 'D')))}){escape(''.join(' +' + PATTERN_NAMES.get(p, p) for p in c.get('also_patterns', [])))}</span>
    <span class="score">score {c['score']}</span>
  </div>
  <table class="stats">
    <tr><td>Last</td><td>{c['last_close']:.2f}</td>
        <td>Trigger / Confirm</td><td>{c['trigger']:.2f} / {c['confirm']:.2f} ({c['dist_to_trigger_pct']:+.1f}% away)</td>
        <td>Target</td><td>{c['target']:.2f} (+{c['upside_pct']:.1f}%)</td></tr>
    <tr><td>Base</td><td>{c['base_days']}{'w' if c.get('tf') == 'W' else 'd'} / {c['n_touches']} touches</td>
        <td>Vol 10d/base</td><td>{c['vol_ratio']:.2f}×</td>
        <td>Gain into base</td><td>{c['gain_into_base_pct']:+.1f}%</td></tr>
    <tr><td>RS vs SPY (120d)</td><td>{rs}</td>
        <td>ADV</td><td>${c['adv_dollar'] / 1e6:,.0f}M</td>
        <td>Data through / tolerance</td><td>{escape(str(c.get('data_end', 'n/a')))} / {escape(str(c.get('ceiling_tolerance_source', 'n/a')))}</td></tr>
  </table>
  {chart}
</div>""")

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Pattern Scan — {escape(str(meta['pattern']))} — {escape(str(meta['date']))}</title>
<style>
body {{ background:{DARK_BG}; color:{TEXT}; font-family: 'Segoe UI', system-ui, sans-serif;
       max-width: 1240px; margin: 0 auto; padding: 18px; }}
h1 {{ font-size: 20px; margin-bottom: 2px; }}
.meta {{ color: #8892a8; font-size: 12px; margin-bottom: 20px; }}
.card {{ background:{PANEL_BG}; border: 1px solid {GRID}; border-radius: 8px;
         padding: 12px 14px; margin-bottom: 22px; }}
.head {{ display:flex; gap:14px; align-items:baseline; margin-bottom:6px; }}
.rank {{ color:#8892a8; font-size:13px; }}
.sym {{ font-size:19px; font-weight:600; color:#fff; }}
.pat {{ color:{CEIL_COLOR}; font-size:13px; }}
.score {{ color:{TARGET_COLOR}; font-size:13px; }}
.stats {{ border-collapse:collapse; font-size:12px; margin-bottom:8px; }}
.stats td {{ padding:1px 14px 1px 0; }}
.stats td:nth-child(odd) {{ color:#8892a8; }}
img {{ width:100%; border-radius:4px; }}
</style></head><body>
<h1>Chart Pattern Scan — {escape(str(meta['pattern']))}</h1>
<div class="meta">{escape(str(meta['date']))} · universe: {escape(str(meta['universe']))} ({meta['n_universe']} symbols,
{meta['n_loaded']} with data) · source: {escape(str(meta['source']))} · data through {escape(str(meta['data_end']))} ·
{len(cands)} candidates · min ADV ${meta['min_adv'] / 1e6:.0f}M ·
funnel: {escape(str(meta['funnel']))} · <a href="https://github.com/zachisit/july-backtester/issues/348"
style="color:{SUP_COLOR}">issue #348</a></div>
{''.join(rows) if rows else '<p>No candidates passed all gates today.</p>'}
</body></html>"""

    Path(out_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    with open(Path(out_path).expanduser(), "w", encoding="utf-8") as f:
        f.write(html)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

DEFAULT_PARAMS = {
    "tf": "D",
    "min_bars": 260,
    "pivot_k": 4,
    "base_max": 140,
    "base_min": 15,
    "last_touch_within": 30,
    "min_touches": 2,
    "min_touches_long": 2,
    "floor_min_touches": 2,
    "tol_pct_floor": .012,
    "tol_atr_mult": .6,
    "uptrend_lookback": 60,
    "uptrend_min_gain": 0.12,
    "max_dist_to_trigger": None,  # None = adaptive: clip(0.5*height/trigger, 3%, cap)
    "max_dist_cap": 0.10,
    "base_max_long": 280,   # rectangle / H&S bottom: Roy's run 3-22 months
    "base_min_long": 40,
    "min_adv": 25e6,
}

# Weekly bars: same rule, coarser clock. base_min 10w ~ 2.5 months keeps the
# multi-month character (Roy-style triangles) structural rather than incidental.
WEEKLY_PARAMS = {
    "tf": "W",
    "min_bars": 80,
    "pivot_k": 3,
    "base_max": 60,
    "base_min": 10,
    "last_touch_within": 8,
    "uptrend_lookback": 26,
    "uptrend_min_gain": 0.15,
    "max_dist_cap": 0.12,   # long weekly ranges oscillate deeper below the boundary
    "base_max_long": 210,   # up to ~4y of weekly bars (TALO's neckline spans years)
    "base_min_long": 20,
}


def resample_weekly(df):
    return (
        df.resample("W-FRI")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna(subset=["Close"])
    )


def _universe_label(value):
    if value.startswith("finviz:"):
        value = value[len("finviz:"):]
        if not value.startswith("http"):
            return "finviz:" + value
    if value.startswith("http") and "finviz.com" in value:
        from urllib.parse import urlparse, parse_qs
        query = parse_qs(urlparse(value).query)
        return "finviz:" + query.get("f", [""])[0]
    return value


def _validated_symbols(value):
    if not isinstance(value, list) or not value:
        raise ValueError("universe must contain a nonempty list of tickers")
    symbols = []
    for item in value:
        if not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9^][A-Za-z0-9.^_-]*", item.strip()):
            raise ValueError(f"invalid ticker: {item!r}")
        symbols.append(item.strip().upper())
    return list(dict.fromkeys(symbols))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Chart pattern scanner (issue #348)")
    ap.add_argument("--universe", default="nasdaq_100.json")
    ap.add_argument("--source", choices=["yahoo", "parquet"], default="parquet")
    ap.add_argument("--parquet-dir", default=PARQUET_DIR,
                    help="local corpus; defaults to PATTERN_SCAN_PARQUET_DIR or parquet_data/data")
    ap.add_argument("--patterns", default="all")
    ap.add_argument("--timeframe", choices=["D", "W"], default="D")
    ap.add_argument("--min-base", type=int, default=None,
                    help="floor for both pattern families; cannot loosen their defaults")
    ap.add_argument("--min-adv", type=float, default=DEFAULT_PARAMS["min_adv"])
    ap.add_argument("--max-dist", type=float, default=None)
    ap.add_argument("--min-gain", type=float, default=None)
    for key in ("min_touches", "min_touches_long", "floor_min_touches"):
        ap.add_argument("--" + key.replace("_", "-"), type=int, default=None)
    for key in ("tol_pct_floor", "tol_atr_mult"):
        ap.add_argument("--" + key.replace("_", "-"), type=float, default=None)
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--out", default=None)
    ap.add_argument("--json-out", default=None, help="optional candidate/parameter/provenance artifact")
    ap.add_argument("--as-of", default=None, help="historical cutoff, YYYY-MM-DD")
    args = ap.parse_args(argv)
    patterns = list(DETECTORS) if args.patterns.strip() == "all" else list(dict.fromkeys(
        p.strip() for p in args.patterns.split(",") if p.strip()))
    if not patterns or any(p not in DETECTORS for p in patterns):
        ap.error("--patterns must name known detectors or all")
    if args.top < 1 or (args.min_base is not None and args.min_base < 1):
        ap.error("--top and --min-base must be positive")
    if not math.isfinite(args.min_adv) or args.min_adv < 0:
        ap.error("--min-adv must be finite and nonnegative")
    if args.max_dist is not None and (not math.isfinite(args.max_dist) or args.max_dist <= 0):
        ap.error("--max-dist must be finite and positive")
    if args.min_gain is not None and not math.isfinite(args.min_gain):
        ap.error("--min-gain must be finite")
    params = {**DEFAULT_PARAMS, **(WEEKLY_PARAMS if args.timeframe == "W" else {})}
    params["min_adv"], params["max_dist_to_trigger"] = args.min_adv, args.max_dist
    if args.min_gain is not None:
        params["uptrend_min_gain"] = args.min_gain
    if args.min_base is not None:
        for key in ("base_min", "base_min_long"):
            params[key] = max(params[key], args.min_base)
    for key in ("min_touches", "min_touches_long", "floor_min_touches", "tol_pct_floor", "tol_atr_mult"):
        value = getattr(args, key)
        if value is not None:
            if not math.isfinite(value) or value <= 0:
                ap.error("--" + key.replace("_", "-") + " must be finite and positive")
            params[key] = value
    if args.as_of:
        try:
            if datetime.strptime(args.as_of, "%Y-%m-%d").strftime("%Y-%m-%d") != args.as_of:
                raise ValueError
        except ValueError:
            ap.error("--as-of must use YYYY-MM-DD")
    try:
        tickers = _validated_symbols(load_universe(args.universe))
    except (ValueError, OSError, TypeError) as exc:
        ap.error(str(exc))
    load_errors = {}
    requested = list(dict.fromkeys(tickers + ["SPY"]))
    if args.source == "yahoo":
        data = fetch_yahoo(requested, period="10y" if args.timeframe == "W" else "3y",
                           as_of=args.as_of, errors=load_errors)
    else:
        data = fetch_parquet(requested, lookback_bars=2600 if args.timeframe == "W" else 800,
                             as_of=args.as_of, parquet_dir=args.parquet_dir, errors=load_errors)
    spy_close = data.get("SPY", pd.DataFrame()).get("Close")
    data = {symbol: data[symbol] for symbol in tickers if symbol in data}
    if not data:
        log.error("Loaded no requested symbols from %s. Configure --parquet-dir / "
                  "PATTERN_SCAN_PARQUET_DIR for a local corpus, or choose --source yahoo.", args.source)
        return 2
    candidates = []
    gated = detection_errors = 0
    for symbol, daily in sorted(data.items()):
        try:
            adv = float((daily["Close"] * daily["Volume"]).tail(20).mean()) if args.timeframe == "W" else None
            frame = resample_weekly(daily) if args.timeframe == "W" else daily
        except Exception as exc:
            detection_errors += len(patterns)
            log.warning("%s: preprocessing error: %s", symbol, type(exc).__name__)
            continue
        for pattern in patterns:
            try:
                candidate = DETECTORS[pattern](symbol, frame, spy_close, params, adv_dollar=adv)
            except Exception as exc:
                detection_errors += 1
                log.warning("%s/%s: detection error: %s", symbol, pattern, type(exc).__name__)
                continue
            if candidate is None:
                gated += 1
            else:
                candidate["data_end"] = str(daily.index.max().date())
                candidates.append(candidate)
    raw_matches = len(candidates)
    merged = {}
    for candidate in sorted(candidates, key=lambda c: c["score"], reverse=True):
        existing = merged.get(candidate["symbol"])
        if existing is None:
            merged[candidate["symbol"]] = candidate
        elif abs(existing["trigger"] - candidate["trigger"]) / existing["trigger"] < .03:
            existing.setdefault("also_patterns", []).append(candidate["pattern"])
    candidates = sorted(merged.values(), key=lambda c: c["score"], reverse=True)[:args.top]
    ends = [str(frame.index.max().date()) for frame in data.values()]
    counts = {"requested": len(tickers), "loaded": len(data), "missing": len(tickers) - len(data),
              "load_errors": len(set(tickers) & set(load_errors)), "gated": gated,
              "detection_errors": detection_errors, "raw_matches": raw_matches,
              "qualified_symbols": len(merged), "shown": len(candidates)}
    run_date = datetime.now().strftime("%Y-%m-%d")
    base_name = patterns[0] if len(patterns) == 1 else "scan"
    suffix = "" if args.timeframe == "D" else "_W"
    out_path = args.out or str(Path(PROJECT_ROOT) / "output" / "scans" / run_date / f"{base_name}{suffix}.html")
    meta = {"pattern": ", ".join(PATTERN_NAMES[p] for p in patterns),
            "date": run_date if not args.as_of else f"{run_date} — REPLAY as of {args.as_of}",
            "universe": _universe_label(args.universe), "n_universe": len(tickers), "n_loaded": len(data),
            "source": args.source, "data_end": min(ends) if min(ends) == max(ends) else f"{min(ends)} to {max(ends)}",
            "min_adv": params["min_adv"], "params": params, "counts": counts,
            "funnel": ", ".join(f"{key}: {value}" for key, value in counts.items())}
    build_html(candidates, meta, out_path)
    if args.json_out:
        artifact = Path(args.json_out).expanduser()
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(json.dumps({"meta": meta,
            "candidates": [{k: v for k, v in c.items() if k != "df"} for c in candidates]},
            indent=2, allow_nan=False, default=lambda obj: obj.item() if isinstance(obj, np.generic) else str(obj)), encoding="utf-8")
    print(out_path)
    return 2 if detection_errors == len(data) * len(patterns) else 0


if __name__ == "__main__":
    raise SystemExit(main())
