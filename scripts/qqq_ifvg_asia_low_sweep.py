"""
scripts/qqq_ifvg_asia_low_sweep.py

Backtest the directional claim behind the "Tempo Trades IFVG Model":
    After sweeping the pre-market / overnight low during the first 90 min
    of NY trading (09:30–11:00 ET), does QQQ rally to the pre-market high
    by noon ET?

QQQ is used as a proxy for NQ1! (Polygon plan does not cover futures).
Correlation between QQQ and NQ intraday is >0.99, so the claim translates.

Data:  QQQ 5-min bars via Polygon (plan serves 2022-onwards for intraday)
Split: IS 2022-2023 (model is "designed on" this era) | OOS 2024-2025

Session definitions (all ET):
    Pre-market    04:00–09:29  (QQQ extended hours; proxy for Asia + London)
    NY open       09:30–10:59  (sweep window — first 90 min)
    Target window 09:30–11:59  (noon cutoff)

Two sweep conditions tested:
    TOUCH  — any bar's Low dips below pre-market Low (including wicks)
    CLOSE  — a bar's Close settles below pre-market Low (stronger)

Claim is falsified if:
    hit_rate(post_sweep) ≈ hit_rate(no_sweep)  [sweep adds no edge]
    OR
    hit_rate(post_sweep) is materially < hit_rate(no_sweep) [sweep is bearish]
"""

import os, sys, time, requests
import pandas as pd
import numpy as np
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

# ── config ────────────────────────────────────────────────────────────────────
SYMBOL      = "QQQ"
START_DATE  = "2022-01-03"
END_DATE    = "2025-12-31"
IS_CUTOFF   = "2024-01-01"   # in-sample / out-of-sample split
API_KEY     = os.getenv("POLYGON_API_KEY")

PM_START    = "04:00"   # pre-market open (ET)
NY_OPEN     = "09:30"   # regular open
SWEEP_END   = "11:00"   # end of sweep detection window
TARGET_END  = "12:00"   # noon — target must be hit by here
# ─────────────────────────────────────────────────────────────────────────────


def fetch_5min(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Fetch 5-min bars with full pagination; converts index to ET."""
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{symbol}"
        f"/range/5/minute/{start}/{end}"
    )
    params = {"apiKey": API_KEY, "adjusted": "true", "sort": "asc", "limit": 50000}
    rows, page = [], 0

    while url:
        page += 1
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 403:
            print(f"  403 on page {page}: {resp.json().get('message','')}")
            break
        resp.raise_for_status()
        data = resp.json()
        chunk = data.get("results", [])
        rows.extend(chunk)
        url = data.get("next_url")
        params = {"apiKey": API_KEY}          # next_url already has path params
        if chunk:
            time.sleep(0.13)                  # ~7 req/s, well inside free tier

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["dt"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
    df = df.set_index("dt").rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})
    return df[["Open", "High", "Low", "Close", "Volume"]].sort_index()


def analyze(df: pd.DataFrame) -> pd.DataFrame:
    """
    Per trading day, compute pre-market levels and sweep/target outcomes.
    Returns one row per day.
    """
    records = []

    for tdate, day in df.groupby(df.index.date):
        # ── pre-market range (04:00–09:29) ───────────────────────────────
        pm = day.between_time(PM_START, "09:29")
        if pm.empty:
            continue
        pm_low  = pm["Low"].min()
        pm_high = pm["High"].max()
        pm_bars = len(pm)

        # ── NY-open sweep window (09:30–10:59) ───────────────────────────
        sweep_bars = day.between_time(NY_OPEN, "10:59")
        if sweep_bars.empty:
            continue

        # ── target window (09:30–11:59) ───────────────────────────────────
        target_bars = day.between_time(NY_OPEN, "11:59")

        # NY open price (first bar)
        ny_open_price = sweep_bars["Open"].iloc[0]

        # touch sweep: any wick below pm_low
        touch_mask  = sweep_bars["Low"]   < pm_low
        touch_swept = touch_mask.any()
        touch_first = sweep_bars.index[touch_mask][0] if touch_swept else None

        # close sweep: any close below pm_low (stronger confirmation)
        close_mask  = sweep_bars["Close"] < pm_low
        close_swept = close_mask.any()
        close_first = sweep_bars.index[close_mask][0] if close_swept else None

        # unconditional: does price reach pm_high at any point by noon?
        unc_target = (target_bars["High"] >= pm_high).any()

        # conditional on touch sweep: post-sweep bars reach pm_high?
        touch_target = None
        if touch_swept:
            post = target_bars[target_bars.index >= touch_first]
            touch_target = (post["High"] >= pm_high).any()

        # conditional on close sweep
        close_target = None
        if close_swept:
            post = target_bars[target_bars.index >= close_first]
            close_target = (post["High"] >= pm_high).any()

        # how far did the sweep go below pm_low?
        touch_depth_pct = (
            (pm_low - sweep_bars["Low"].min()) / pm_low * 100
            if touch_swept else np.nan
        )

        # pm range as % (how big is the overnight range)
        pm_range_pct = (pm_high - pm_low) / pm_low * 100

        records.append({
            "date":           pd.Timestamp(tdate),
            "year":           pd.Timestamp(tdate).year,
            "split":          "IS" if str(tdate) < IS_CUTOFF else "OOS",
            "pm_low":         pm_low,
            "pm_high":        pm_high,
            "pm_range_pct":   pm_range_pct,
            "pm_bars":        pm_bars,
            "ny_open":        ny_open_price,
            "touch_swept":    touch_swept,
            "close_swept":    close_swept,
            "touch_depth_pct": touch_depth_pct,
            "unc_target":     unc_target,
            "touch_target":   touch_target,
            "close_target":   close_target,
        })

    return pd.DataFrame(records)


def pct(n, d):
    return f"{n/d*100:.1f}%" if d else "n/a"

def hit(series):
    v = series.dropna()
    return f"{v.mean()*100:.1f}% (n={len(v)})" if len(v) else "n/a"


def report(stats: pd.DataFrame):
    total  = len(stats)
    touch  = stats["touch_swept"].sum()
    close_ = stats["close_swept"].sum()

    print(f"\n{'='*65}")
    print(f"  QQQ 5-min  |  Asia/Pre-market Low Sweep Study")
    print(f"  Claim: NQ1! IFVG Model (Tempo Trades) — directional test")
    print(f"  Period: {stats['date'].min().date()} → {stats['date'].max().date()}")
    print(f"  IS < {IS_CUTOFF}  |  OOS >= {IS_CUTOFF}")
    print(f"{'='*65}")

    print(f"\n── SWEEP FREQUENCY ─────────────────────────────────────────")
    print(f"  Trading days total             : {total}")
    print(f"  Days with TOUCH sweep (wick)   : {touch}  ({pct(touch, total)})")
    print(f"  Days with CLOSE sweep          : {close_}  ({pct(close_, total)})")

    print(f"\n── HIT RATE: Reach pre-market HIGH by noon (09:30–12:00) ───")
    print(f"  {'Condition':<38}  {'All':>8}  {'IS':>8}  {'OOS':>8}")
    print(f"  {'-'*64}")

    groups = [("All", stats), ("IS", stats[stats["split"]=="IS"]), ("OOS", stats[stats["split"]=="OOS"])]

    def row(label, col, mask=None):
        parts = []
        for _, g in groups:
            s = g[col] if mask is None else g.loc[mask(g), col]
            parts.append(hit(s))
        print(f"  {label:<38}  {parts[0]:>8}  {parts[1]:>8}  {parts[2]:>8}")

    row("Unconditional (all days)",       "unc_target")
    row("Days WITHOUT touch sweep",        "unc_target",   lambda g: ~g["touch_swept"])
    row("Days WITH touch sweep (post-sw)", "touch_target", lambda g: g["touch_swept"])
    row("Days WITH close sweep (post-sw)", "close_target", lambda g: g["close_swept"])

    print(f"\n── YEAR-BY-YEAR ─────────────────────────────────────────────")
    print(f"  {'Year':<5} {'Days':>5} {'Touch%':>7} {'Unc.Hit%':>9} {'TouchHit%':>10} {'CloseHit%':>10}")
    print(f"  {'-'*52}")
    for yr, g in stats.groupby("year"):
        n      = len(g)
        t_pct  = g["touch_swept"].mean()*100
        u_hit  = g["unc_target"].mean()*100
        tg     = g[g["touch_swept"]]
        th_hit = tg["touch_target"].mean()*100 if not tg.empty else float("nan")
        cg     = g[g["close_swept"]]
        ch_hit = cg["close_target"].mean()*100 if not cg.empty else float("nan")
        print(f"  {yr:<5} {n:>5} {t_pct:>6.1f}% {u_hit:>8.1f}% {th_hit:>9.1f}% {ch_hit:>9.1f}%")

    print(f"\n── SWEEP DEPTH (when touch sweep occurred) ──────────────────")
    sw = stats[stats["touch_swept"]]
    if not sw.empty:
        d = sw["touch_depth_pct"]
        print(f"  Mean depth below pm_low  : {d.mean():.3f}%")
        print(f"  Median                   : {d.median():.3f}%")
        print(f"  90th pct                 : {d.quantile(0.9):.3f}%")

    print(f"\n── PRE-MARKET RANGE CONTEXT ─────────────────────────────────")
    r = stats["pm_range_pct"]
    print(f"  Mean pm_high-to-pm_low range : {r.mean():.2f}%")
    print(f"  Median                       : {r.median():.2f}%")

    print(f"\n── VERDICT ──────────────────────────────────────────────────")
    # Quick signal check
    oos = stats[stats["split"] == "OOS"]
    oos_sw = oos[oos["touch_swept"]]
    oos_nosw = oos[~oos["touch_swept"]]
    if not oos_sw.empty and not oos_nosw.empty:
        hit_sw   = oos_sw["touch_target"].mean()
        hit_nosw = oos_nosw["unc_target"].mean()
        delta    = hit_sw - hit_nosw
        if delta > 0.05:
            verdict = f"EDGE PRESENT — sweep days hit +{delta*100:.1f}pp more often OOS"
        elif delta < -0.05:
            verdict = f"COUNTER-EDGE — sweep days hit {delta*100:.1f}pp LESS often OOS"
        else:
            verdict = f"NO EDGE — sweep adds {delta*100:+.1f}pp vs no-sweep OOS (noise)"
        print(f"  {verdict}")
    print()


def analyze_trades(df: pd.DataFrame, min_room_pct: float = 0.0) -> pd.DataFrame:
    """
    Tradable version of the no-sweep finding.

    Entry : open of the 11:00 ET bar (sweep window just closed, no sweep occurred)
    Stop  : pm_low  (below the overnight low)
    Target: pm_high (the overnight high)
    Filter: only trade when (pm_high - entry) / entry >= min_room_pct

    Outcome resolution (bar-by-bar, 11:00–15:44 ET):
        WIN  — High >= pm_high before Low <= pm_low
        LOSS — Low  <= pm_low  before High >= pm_high
        EOD  — neither hit; closed at last bar's Close (R computed vs stop/target)

    When both target and stop are touched on the SAME bar, we take the
    conservative assumption: LOSS (stop hit first).
    """
    records = []

    for tdate, day in df.groupby(df.index.date):
        pm = day.between_time(PM_START, "09:29")
        if pm.empty:
            continue
        pm_low  = pm["Low"].min()
        pm_high = pm["High"].max()

        sweep_bars = day.between_time(NY_OPEN, "10:59")
        if sweep_bars.empty:
            continue

        if (sweep_bars["Low"] < pm_low).any():
            continue  # sweep occurred — skip

        # Entry bar: first 5-min bar at or after 11:00
        entry_candidates = day[day.index.time >= pd.Timestamp("11:00").time()]
        entry_candidates = entry_candidates[
            entry_candidates.index.time < pd.Timestamp("11:05").time()
        ]
        if entry_candidates.empty:
            continue
        entry_bar   = entry_candidates.iloc[0]
        entry_price = entry_bar["Open"]

        if entry_price >= pm_high:
            continue  # already through target, no trade

        room_pct = (pm_high - entry_price) / entry_price * 100
        risk_pct = (entry_price - pm_low)  / entry_price * 100

        if risk_pct <= 0 or room_pct < min_room_pct:
            continue

        rr_ratio = room_pct / risk_pct

        # Walk bars from 11:00 to 15:44 to resolve WIN / LOSS / EOD
        post = day[day.index >= entry_candidates.index[0]]
        post = post[post.index.time <= pd.Timestamp("15:44").time()]

        outcome    = "EOD"
        r_multiple = None

        for _, bar in post.iterrows():
            target_touched = bar["High"] >= pm_high
            stop_touched   = bar["Low"]  <= pm_low
            if target_touched and not stop_touched:
                outcome    = "WIN"
                r_multiple = 1.0
                break
            elif stop_touched:          # stop or ambiguous same-bar — conservative
                outcome    = "LOSS"
                r_multiple = -1.0
                break

        if outcome == "EOD":
            eod_price  = post["Close"].iloc[-1]
            r_multiple = (eod_price - entry_price) / (entry_price - pm_low)

        records.append({
            "date":       pd.Timestamp(tdate),
            "year":       pd.Timestamp(tdate).year,
            "split":      "IS" if str(tdate) < IS_CUTOFF else "OOS",
            "entry":      entry_price,
            "pm_low":     pm_low,
            "pm_high":    pm_high,
            "room_pct":   room_pct,
            "risk_pct":   risk_pct,
            "rr_ratio":   rr_ratio,
            "outcome":    outcome,
            "r_multiple": r_multiple,
            "win":        outcome == "WIN",
        })

    return pd.DataFrame(records)


def trade_report(trades: pd.DataFrame, label: str):
    if trades.empty:
        print(f"\n  No trades for: {label}")
        return

    total = len(trades)
    wins  = trades["win"].sum()
    wr    = wins / total
    avg_r = trades["r_multiple"].mean()
    med_r = trades["r_multiple"].median()
    avg_rr = trades["rr_ratio"].mean()

    # Expectancy = wr * avg_win_R + (1-wr) * avg_loss_R
    win_r  = trades.loc[trades["win"],  "r_multiple"].mean() if wins > 0          else 0
    loss_r = trades.loc[~trades["win"], "r_multiple"].mean() if (total-wins) > 0  else 0
    exp    = wr * win_r + (1 - wr) * loss_r

    print(f"\n{'='*65}")
    print(f"  TRADE STUDY: {label}")
    print(f"  Entry: 11:00 ET open | Stop: pm_low | Target: pm_high")
    print(f"  IS < {IS_CUTOFF}  |  OOS >= {IS_CUTOFF}")
    print(f"{'='*65}")

    print(f"\n── OVERALL ({'IS+OOS'}) ───────────────────────────────────────")
    print(f"  Qualifying setups : {total}")
    print(f"  Win rate          : {wr*100:.1f}%  ({wins}W / {total-wins}L)")
    print(f"  Avg R/trade       : {avg_r:+.3f}R")
    print(f"  Median R/trade    : {med_r:+.3f}R")
    print(f"  Avg R:R offered   : {avg_rr:.2f}")
    print(f"  Expectancy        : {exp:+.3f}R")
    print(f"  Avg room to tgt   : {trades['room_pct'].mean():.2f}%")
    print(f"  Avg risk to stop  : {trades['risk_pct'].mean():.2f}%")

    for split in ["IS", "OOS"]:
        g = trades[trades["split"] == split]
        if g.empty:
            continue
        gw = g["win"].sum()
        print(f"\n── {split} ({'2022-23' if split=='IS' else '2024-25'}) ──────────────────────────────────────")
        print(f"  Setups     : {len(g)}")
        print(f"  Win rate   : {g['win'].mean()*100:.1f}%  ({gw}W / {len(g)-gw}L)")
        print(f"  Avg R      : {g['r_multiple'].mean():+.3f}R")
        print(f"  Expectancy : {(g['win'].mean() * g.loc[g['win'],'r_multiple'].mean() + (1-g['win'].mean()) * g.loc[~g['win'],'r_multiple'].mean()):+.3f}R")

    print(f"\n── YEAR-BY-YEAR ─────────────────────────────────────────────")
    print(f"  {'Year':<5} {'n':>4} {'WR%':>6} {'AvgR':>7} {'Exp':>7}")
    print(f"  {'-'*33}")
    for yr, g in trades.groupby("year"):
        gw = g["win"].sum()
        gl = len(g) - gw
        wr_yr  = g["win"].mean()
        avgr   = g["r_multiple"].mean()
        wr_val = g.loc[g["win"],  "r_multiple"].mean() if gw  > 0 else 0
        lr_val = g.loc[~g["win"], "r_multiple"].mean() if gl  > 0 else 0
        exp_yr = wr_yr * wr_val + (1 - wr_yr) * lr_val
        print(f"  {yr:<5} {len(g):>4} {wr_yr*100:>5.1f}% {avgr:>+7.3f} {exp_yr:>+7.3f}")

    print(f"\n── OUTCOME MIX ──────────────────────────────────────────────")
    for oc, g in trades.groupby("outcome"):
        print(f"  {oc:<6}: {len(g):>4}  ({len(g)/total*100:.1f}%)  avg R {g['r_multiple'].mean():+.3f}")


if __name__ == "__main__":
    if not API_KEY:
        sys.exit("POLYGON_API_KEY not set.")

    print(f"Fetching {SYMBOL} 5-min bars {START_DATE} → {END_DATE}…")
    df = fetch_5min(SYMBOL, START_DATE, END_DATE)

    if df.empty:
        sys.exit("No data returned. Check plan / dates.")

    print(f"  {len(df):,} bars fetched. Earliest: {df.index[0]}  Latest: {df.index[-1]}")

    pm_sample = df.between_time("04:00", "09:29")
    print(f"  Pre-market bars in dataset: {len(pm_sample):,} "
          f"({len(pm_sample)/len(df)*100:.1f}% of total)")

    print("Analysing sessions…")
    stats = analyze(df)
    print(f"  {len(stats)} trading days analysed.\n")

    report(stats)

    # ── Trade study: no-sweep long at 11:00 ──────────────────────────────────
    print("\n" + "─"*65)
    print("  TRADE STUDY: long at 11:00 on no-sweep days")
    print("─"*65)

    for room in [0.0, 0.20, 0.40]:
        trades = analyze_trades(df, min_room_pct=room)
        trade_report(trades, f"min room to target ≥ {room:.2f}%")
