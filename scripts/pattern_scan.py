"""Morning chart-pattern scanner — ascending-triangle continuation MVP (issue #348).

Scans a ticker universe for flat-ceiling / rising-lows geometry in an uptrend
(ascending triangle acting as a continuation), ranks candidates by mechanical
quality, and writes a self-contained HTML contact sheet with annotated
candlestick charts (ceiling, rising-lows trendline, trigger, measured target).

Standalone diagnostic tool — no engine/pipeline imports, no config.py coupling.

Usage:
    python scripts/pattern_scan.py --universe nasdaq_100.json --source yahoo
    python scripts/pattern_scan.py --universe nasdaq_100.json --source parquet
"""

import argparse
import base64
import io
import json
import logging
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

PARQUET_DIR = os.path.join(PROJECT_ROOT, "parquet_data", "data")


def load_universe(universe_arg):
    """Resolve a universe argument to a ticker list.

    Accepts a JSON filename in tickers_to_scan/, a path to a JSON file, or a
    comma-separated ticker string.
    """
    candidate = os.path.join(PROJECT_ROOT, "tickers_to_scan", universe_arg)
    if os.path.exists(candidate):
        with open(candidate) as f:
            return json.load(f)
    if os.path.exists(universe_arg):
        with open(universe_arg) as f:
            return json.load(f)
    return [t.strip().upper() for t in universe_arg.split(",") if t.strip()]


def fetch_yahoo(tickers, period="2y"):
    """Batch-download daily bars from Yahoo. Returns {symbol: OHLCV df}."""
    import yfinance as yf

    raw = yf.download(
        tickers,
        period=period,
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )
    out = {}
    for sym in tickers:
        try:
            df = raw[sym].dropna(subset=["Close"])
        except KeyError:
            continue
        if len(df) >= 260:
            out[sym] = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    return out


def fetch_parquet(tickers, lookback_bars=500):
    """Read symbols from the local parquet corpus. Returns {symbol: OHLCV df}."""
    out = {}
    for sym in tickers:
        path = os.path.join(PARQUET_DIR, f"{sym}.parquet")
        if not os.path.exists(path):
            continue
        df = pd.read_parquet(path)
        if len(df) >= 260:
            out[sym] = df.tail(lookback_bars)[["Open", "High", "Low", "Close", "Volume"]].copy()
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
                 min_touches=2, tol_pct_floor=0.012):
    """Cluster recent pivot highs into a flat resistance level.

    Returns (level, touch_indices) for the best cluster, or (None, None).
    Best = most touches, then longest span. The base must not contain a
    sustained close above the level (not already broken out).
    """
    n = len(df)
    closes = df["Close"].values
    recent = [i for i in piv_hi if i >= n - base_max]
    best = None
    for anchor in recent:
        lvl_anchor = df["High"].iloc[anchor]
        tol = max(tol_pct_floor * lvl_anchor, 0.6 * (atr[anchor] if not np.isnan(atr[anchor]) else 0))
        touches = [i for i in recent if abs(df["High"].iloc[i] - lvl_anchor) <= tol]
        if len(touches) < min_touches:
            continue
        span = max(touches) - min(touches)
        if span < base_min:
            continue
        if max(touches) < n - last_touch_within:
            continue
        level = float(np.mean([df["High"].iloc[i] for i in touches]))
        # not already broken out: no close in the base > level by more than ~0.7%
        base_closes = closes[min(touches) : n]
        if (base_closes > level * 1.007).any():
            continue
        key = (len(touches), span)
        if best is None or key > best[0]:
            best = (key, level, sorted(touches))
    if best is None:
        return None, None
    return best[1], best[2]


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
    n = len(df)
    if n < params["min_bars"]:
        return None
    atr = compute_atr(df).values
    close = df["Close"]
    last_close = float(close.iloc[-1])
    last_atr = atr[-1]
    if np.isnan(last_atr) or last_close <= 0:
        return None

    # liquidity floor (dollar ADV)
    if adv_dollar is None:
        adv_dollar = float((close * df["Volume"]).tail(20).mean())
    if adv_dollar < params["min_adv"]:
        return None

    piv_hi, piv_lo = find_pivots(df, k=params["pivot_k"], atr=atr)
    level, touches = find_ceiling(
        df, piv_hi, atr,
        base_max=params["base_max"], base_min=params["base_min"],
        last_touch_within=params["last_touch_within"],
        min_touches=params["min_touches"],
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
        max_dist = float(np.clip(0.5 * height / trigger, 0.03, 0.10))
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
        if not np.isnan(spy_aligned.iloc[-w]):
            sym_ret = last_close / close.iloc[-w] - 1.0
            spy_ret = spy_aligned.iloc[-1] / spy_aligned.iloc[-w] - 1.0
            rs_excess = float(sym_ret - spy_ret)
            rs_score = 15.0 * float(np.clip(rs_excess / 0.20, 0, 1))
    prox_score = 20.0 * float(np.clip(1.0 - max(dist, 0) / max_dist, 0, 1))
    score = touch_score + tight_score + vol_score + rs_score + prox_score

    return {
        "symbol": sym,
        "tf": params.get("tf", "D"),
        "score": round(score, 1),
        "level": level,
        "trigger": trigger,
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
    start = max(0, n - show_bars)
    sub = df.iloc[start:]
    x = np.arange(len(sub))
    off = start  # index offset between full-df bar indices and plot x

    fig = plt.figure(figsize=(11.5, 5.8), dpi=105, facecolor=DARK_BG)
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

    # rising-lows trendline from first anchor, extrapolated to right edge
    slope, intercept = cand["support"]
    a0 = cand["support_anchors"][0]
    xs = np.arange(max(a0, off), n + 3)
    ax.plot(xs - off, slope * xs + intercept, color=SUP_COLOR, linewidth=1.4)
    for t in cand["support_touches"]:
        if t >= off:
            ax.plot(t - off, df["Low"].iloc[t], marker="^", color=SUP_COLOR, markersize=5)

    # trigger + measured target
    ax.axhline(cand["target"], color=TARGET_COLOR, linewidth=1.1, linestyle="--", alpha=0.9)
    xr = len(sub) + 3
    ax.text(xr, cand["level"], f" trigger {cand['trigger']:.2f}", color=CEIL_COLOR,
            fontsize=8, va="center")
    ax.text(xr, cand["target"], f" target {cand['target']:.2f} (+{cand['upside_pct']:.1f}%)",
            color=TARGET_COLOR, fontsize=8, va="center")

    ax.set_xlim(-2, len(sub) + 16)
    ymin = float(sub["Low"].min()) * 0.985
    ymax = max(float(sub["High"].max()), cand["target"]) * 1.015
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
    ax.set_title(
        f"{cand['symbol']}  —  Ascending Triangle (continuation, {cand.get('tf', 'D')})   "
        f"score {cand['score']}   base {cand['base_days']}{unit}   "
        f"{cand['n_touches']} touches   ADV ${cand['adv_dollar'] / 1e6:,.0f}M",
        color=TEXT, fontsize=10, loc="left",
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=DARK_BG, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


# ---------------------------------------------------------------------------
# HTML contact sheet
# ---------------------------------------------------------------------------


def build_html(cands, meta, out_path):
    rows = []
    for rank, c in enumerate(cands, 1):
        img = render_chart(c)
        rs = "n/a" if c["rs_excess_pct"] is None else f"{c['rs_excess_pct']:+.1f}%"
        rows.append(f"""
<div class="card">
  <div class="head">
    <span class="rank">#{rank}</span>
    <span class="sym">{c['symbol']}</span>
    <span class="score">score {c['score']}</span>
  </div>
  <table class="stats">
    <tr><td>Last</td><td>{c['last_close']:.2f}</td>
        <td>Trigger</td><td>{c['trigger']:.2f} ({c['dist_to_trigger_pct']:+.1f}% away)</td>
        <td>Target</td><td>{c['target']:.2f} (+{c['upside_pct']:.1f}%)</td></tr>
    <tr><td>Base</td><td>{c['base_days']}{'w' if c.get('tf') == 'W' else 'd'} / {c['n_touches']} touches</td>
        <td>Vol 10d/base</td><td>{c['vol_ratio']:.2f}×</td>
        <td>Gain into base</td><td>{c['gain_into_base_pct']:+.1f}%</td></tr>
    <tr><td>RS vs SPY (120d)</td><td>{rs}</td>
        <td>ADV</td><td>${c['adv_dollar'] / 1e6:,.0f}M</td><td></td><td></td></tr>
  </table>
  <img src="data:image/png;base64,{img}" alt="{c['symbol']} chart"/>
</div>""")

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>Pattern Scan — {meta['pattern']} — {meta['date']}</title>
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
.score {{ color:{TARGET_COLOR}; font-size:13px; }}
.stats {{ border-collapse:collapse; font-size:12px; margin-bottom:8px; }}
.stats td {{ padding:1px 14px 1px 0; }}
.stats td:nth-child(odd) {{ color:#8892a8; }}
img {{ width:100%; border-radius:4px; }}
</style></head><body>
<h1>Ascending Triangle — Continuation Scan</h1>
<div class="meta">{meta['date']} · universe: {meta['universe']} ({meta['n_universe']} symbols,
{meta['n_loaded']} with data) · source: {meta['source']} · data through {meta['data_end']} ·
{len(cands)} candidates · min ADV ${meta['min_adv'] / 1e6:.0f}M ·
funnel: {meta['funnel']} · <a href="https://github.com/zachisit/july-backtester/issues/348"
style="color:{SUP_COLOR}">issue #348</a></div>
{''.join(rows) if rows else '<p>No candidates passed all gates today.</p>'}
</body></html>"""

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
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
    "uptrend_lookback": 60,
    "uptrend_min_gain": 0.12,
    "max_dist_to_trigger": None,  # None = adaptive: clip(0.5*height/trigger, 3%, 10%)
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
}


def resample_weekly(df):
    return (
        df.resample("W-FRI")
        .agg({"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"})
        .dropna(subset=["Close"])
    )


def main():
    ap = argparse.ArgumentParser(description="Chart pattern scanner (issue #348)")
    ap.add_argument("--universe", default="nasdaq_100.json")
    ap.add_argument("--source", choices=["yahoo", "parquet"], default="parquet")
    ap.add_argument("--patterns", default="ascending_triangle")
    ap.add_argument("--timeframe", choices=["D", "W"], default="D",
                    help="W resamples daily bars to weekly before detection")
    ap.add_argument("--min-base", type=int, default=None,
                    help="minimum base length in bars (e.g. 55 daily ~ 3 months)")
    ap.add_argument("--min-adv", type=float, default=DEFAULT_PARAMS["min_adv"])
    ap.add_argument("--max-dist", type=float, default=None,
                    help="fixed distance-to-trigger gate; default adapts to pattern height")
    ap.add_argument("--min-gain", type=float, default=DEFAULT_PARAMS["uptrend_min_gain"])
    ap.add_argument("--top", type=int, default=50)
    ap.add_argument("--out", default=None)
    ap.add_argument("--as-of", default=None,
                    help="drop bars after this date (YYYY-MM-DD) — replay a historical scan, "
                         "e.g. to test the scanner against a known pro call")
    args = ap.parse_args()

    if args.patterns != "ascending_triangle":
        log.error("MVP supports --patterns ascending_triangle only (issue #348 scope).")
        sys.exit(1)

    params = dict(DEFAULT_PARAMS)
    if args.timeframe == "W":
        params.update(WEEKLY_PARAMS)
    params["min_adv"] = args.min_adv
    params["max_dist_to_trigger"] = args.max_dist
    if args.min_gain != DEFAULT_PARAMS["uptrend_min_gain"]:
        params["uptrend_min_gain"] = args.min_gain
    if args.min_base is not None:
        params["base_min"] = args.min_base

    tickers = load_universe(args.universe)
    log.info("Universe: %d symbols", len(tickers))

    if args.source == "yahoo":
        data = fetch_yahoo(tickers + ["SPY"], period="5y" if args.timeframe == "W" else "2y")
    else:
        data = fetch_parquet(tickers + ["SPY"], lookback_bars=1300 if args.timeframe == "W" else 500)
    if args.as_of:
        def _truncate(df):
            ts = pd.Timestamp(args.as_of)
            if df.index.tz is not None:
                ts = ts.tz_localize(df.index.tz)
            return df[df.index <= ts]
        data = {s: d for s, d in ((s, _truncate(d)) for s, d in data.items()) if len(d)}
        log.info("Replaying as of %s", args.as_of)
    spy_close = data.pop("SPY", pd.DataFrame()).get("Close")
    log.info("Loaded data for %d symbols", len(data))

    cands = []
    for sym, df in sorted(data.items()):
        try:
            adv = None
            if args.timeframe == "W":
                adv = float((df["Close"] * df["Volume"]).tail(20).mean())  # from daily bars
                df = resample_weekly(df)
            cand = detect_ascending_triangle(sym, df, spy_close, params, adv_dollar=adv)
        except Exception as e:  # one bad symbol must not kill the scan
            log.warning("%s: detection error: %s", sym, e)
            continue
        if cand is not None:
            cands.append(cand)
            log.info("MATCH %-6s score %.1f  trigger %.2f  (%+.1f%% away)",
                     sym, cand["score"], cand["trigger"], cand["dist_to_trigger_pct"])

    cands.sort(key=lambda c: c["score"], reverse=True)
    cands = cands[: args.top]

    data_end = max((df.index.max() for df in data.values()), default=None)
    run_date = datetime.now().strftime("%Y-%m-%d")
    suffix = "" if args.timeframe == "D" else f"_{args.timeframe}"
    out_path = args.out or os.path.join(
        PROJECT_ROOT, "output", "scans", run_date, f"ascending_triangle{suffix}.html"
    )
    meta = {
        "pattern": "ascending_triangle",
        "date": run_date if not args.as_of else f"{run_date} — REPLAY as of {args.as_of}",
        "universe": args.universe,
        "n_universe": len(tickers),
        "n_loaded": len(data),
        "source": args.source,
        "data_end": "n/a" if data_end is None else str(data_end.date()),
        "min_adv": params["min_adv"],
        "funnel": f"{len(data)} scanned → {len(cands)} matched",
    }
    build_html(cands, meta, out_path)
    log.info("%d candidates → %s", len(cands), out_path)
    print(out_path)


if __name__ == "__main__":
    main()
