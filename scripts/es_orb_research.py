"""
ES Opening Range Breakout research runner.

    Spec under test: opening range = first 15-30 min of the NY cash open; breakout entries
    taken in the 09:45-11:00 ET window.

Two data legs, because neither alone can answer the question:

  ES  -- Polygon futures 1-min, front-month stitched. Real ES, but Polygon's futures
         aggregates begin 2024-09-17, so the sample is ~2 years / ~500 sessions. Enough to
         measure the effect, far too short to establish it survives regimes.
  MNQ -- Databento 1-min RTH, 2010-06 -> 2026-07 (~4,050 sessions). Wrong index (Nasdaq,
         not S&P) but real index futures over 16 years, which is the only way to ask whether
         this pattern has ever been persistent.

Since the strategy is flat by the close every day, no back-adjustment is needed: every
session is self-contained and quarterly roll gaps never touch a position.

Outputs (output/):
    summary.txt, grid_es.csv, grid_mnq.csv, trades_<leg>_<label>.csv, by_year_mnq.csv
"""
from __future__ import annotations

import os
import sys
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from orb_engine import Costs, OrbParams, run_orb, trades_frame  # noqa: E402
from es_futures_data import load_es_1min  # noqa: E402

OUT = HERE.parent / "output"
MNQ_PATH = Path("/Users/zach/Desktop/github/jb-private-research/futures_intraday_data/mnq/"
                "nq_mnq_RTH_clean_stitched.parquet")

# Cost models. ES: 1-tick spread is the norm in RTH; retail all-in commission ~$2.50 RT.
# MNQ: 1-tick spread, ~$1.04 RT at a discount broker.
ES_COSTS = Costs(tick_size=0.25, point_value=50.0, slippage_ticks=1.0, commission_rt=2.50)
MNQ_COSTS = Costs(tick_size=0.25, point_value=2.0, slippage_ticks=1.0, commission_rt=1.04)

# Pre-registered out-of-sample boundary for the ES leg: the final ~8.5 months are held back.
ES_OOS_START = pd.Timestamp("2026-01-01").date()
# MNQ: the last ~5 years are held back from the 16-year series.
MNQ_OOS_START = pd.Timestamp("2021-01-01").date()


# ----------------------------------------------------------------------------- metrics
def metrics(t: pd.DataFrame, n_sessions: int, costs: Costs, all_sessions) -> dict:
    if t.empty:
        return {"trades": 0, "sessions": n_sessions}
    r = t["r_multiple"].to_numpy(dtype=float)
    r_ok = r[np.isfinite(r)]
    usd = t["net_usd"].to_numpy(dtype=float)
    wins = usd > 0
    gross_win = usd[usd > 0].sum()
    gross_loss = -usd[usd < 0].sum()

    # 1-contract cumulative equity -> max drawdown in dollars
    eq = np.cumsum(usd)
    dd = eq - np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]

    # Per-session return series for a Sharpe. One contract, notional = point_value * price.
    # The series spans every session in the sample: a day the strategy sat flat is a real
    # 0% day and must dilute the Sharpe, not be dropped from it.
    per_sess = t.groupby("session")["net_usd"].sum()
    notional = float(costs.point_value * t["entry_px"].median())
    full = pd.Series(0.0, index=pd.Index(sorted(all_sessions)))
    full.loc[per_sess.index] = (per_sess / notional).values
    sharpe = (full.mean() / full.std(ddof=1) * np.sqrt(252)) if full.std(ddof=1) > 0 else np.nan

    tstat = (r_ok.mean() / (r_ok.std(ddof=1) / np.sqrt(len(r_ok)))) \
        if len(r_ok) > 1 and r_ok.std(ddof=1) > 0 else np.nan
    return {
        "trades": len(t),
        "sessions": n_sessions,
        "trade_rate": len(t) / n_sessions if n_sessions else np.nan,
        "win_rate": wins.mean(),
        "avg_r": r_ok.mean() if len(r_ok) else np.nan,
        "median_r": float(np.median(r_ok)) if len(r_ok) else np.nan,
        "expectancy_usd": usd.mean(),
        "total_usd": usd.sum(),
        "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else np.inf,
        "max_dd_usd": dd.min(),
        "sharpe": sharpe,
        "t_stat_r": tstat,
        "pct_long": (t["side"] == 1).mean(),
        "long_avg_r": t.loc[t["side"] == 1, "r_multiple"].mean(),
        "short_avg_r": t.loc[t["side"] == -1, "r_multiple"].mean(),
        "pct_entry_gapped": t["entry_gapped"].mean(),
        "avg_hold_min": t["hold_minutes"].mean(),
        "exit_stop": (t["exit_reason"] == "stop").mean(),
        "exit_target": (t["exit_reason"] == "target").mean(),
        "exit_time": (t["exit_reason"] == "time").mean(),
    }


def sessions_of(df: pd.DataFrame) -> set:
    rth = df.between_time(time(9, 30), time(16, 0), inclusive="left")
    return set(rth.index.date)


def n_sessions(df: pd.DataFrame) -> int:
    return len(sessions_of(df))


# ----------------------------------------------------------------------------- grid
def build_grid() -> list[OrbParams]:
    """The spec fixes the 11:00 cutoff and a 15-30 min OR. Two readings of '09:45-11am'
    are both tested: entries-only-in-window (hold to close) and flat-at-11:00."""
    grid = []
    for or_min in (15, 30):
        for texit in (time(11, 0), time(15, 59)):
            for tgt in (None, 1.0, 2.0):
                grid.append(OrbParams(or_minutes=or_min, entry_cutoff=time(11, 0),
                                      time_exit=texit, target_r=tgt))
    # Direction split: if the P&L is really index drift, long-only carries all of it and
    # short-only is the mirror loss. Only run this on the no-target readings to keep the
    # grid small enough to interpret without multiple-comparison laundering.
    for or_min in (15, 30):
        for texit in (time(11, 0), time(15, 59)):
            for d in ("long", "short"):
                grid.append(OrbParams(or_minutes=or_min, entry_cutoff=time(11, 0),
                                      time_exit=texit, target_r=None, direction=d))
    return grid


def run_leg(df: pd.DataFrame, costs: Costs, grid: list[OrbParams],
            leg: str, oos_start) -> pd.DataFrame:
    """One engine pass per config. IS/OOS are date slices of that single trade list --
    the strategy carries no state across sessions, so slicing is exactly equivalent to
    re-running on the sub-period, and it cannot drift out of sync with the full-sample row."""
    rows = []
    all_sess = sessions_of(df)
    is_sess = {d for d in all_sess if d < oos_start}
    oos_sess = {d for d in all_sess if d >= oos_start}

    for p in grid:
        t = trades_frame(run_orb(df, p, costs))
        tag = {"leg": leg, "label": p.label(), "or_minutes": p.or_minutes,
               "entry_cutoff": p.entry_cutoff.strftime("%H:%M"),
               "time_exit": p.time_exit.strftime("%H:%M"),
               "target_r": "none" if p.target_r is None else p.target_r,
               "direction": p.direction}
        for split, sess in (("full", all_sess), ("IS", is_sess), ("OOS", oos_sess)):
            part = t[t["session"].isin(sess)] if not t.empty else t
            m = metrics(part, len(sess), costs, sess)
            m.update(tag); m["split"] = split
            rows.append(m)
    return pd.DataFrame(rows)


def run_always_in(df: pd.DataFrame, costs: Costs, or_minutes: int, time_exit: time,
                  side: int) -> pd.DataFrame:
    """CONTROL: unconditional exposure. Enter at the open of the first bar after the opening
    range every single session, exit at `time_exit`'s close. No breakout condition, no stop.

    This is the benchmark the ORB has to beat. An index that drifts up over the sample will
    make a 'hold to the close' rule profitable whether or not the breakout means anything,
    so any ORB P&L that does not exceed this is drift, not edge."""
    or_end = 9 * 60 + 30 + or_minutes
    texit = time_exit.hour * 60 + time_exit.minute
    rth = df.between_time(time(9, 30), time(16, 0), inclusive="left")
    slip = costs.slip()
    out = []
    for day, bars in rth.groupby(rth.index.date, sort=True):
        mins = bars.index.hour * 60 + bars.index.minute
        entry_bars = bars[mins >= or_end]
        exit_bars = bars[mins <= texit]
        if entry_bars.empty or exit_bars.empty:
            continue
        e_px = float(entry_bars.iloc[0]["open"])
        x_px = float(exit_bars.iloc[-1]["close"])
        entry = e_px + slip if side == 1 else e_px - slip
        exit_ = x_px - slip if side == 1 else x_px + slip
        pts = (exit_ - entry) * side
        out.append({"session": day, "side": side, "entry_px": entry, "exit_px": exit_,
                    "points": pts, "gross_usd": pts * costs.point_value,
                    "net_usd": pts * costs.point_value - costs.commission_rt,
                    "risk_pts": np.nan, "r_multiple": np.nan, "hold_minutes": texit - or_end,
                    "entry_gapped": False, "exit_reason": "time"})
    return pd.DataFrame(out)


# ----------------------------------------------------------------------------- placebo
def matched_placebo(df: pd.DataFrame, costs: Costs, or_minutes: int,
                    entry_cutoff: time, time_exit: time) -> dict:
    """Is the breakout DIRECTION informative, or is the P&L just exposure?

    Runs the identical rules twice -- follow the break, and fade it -- on the same bars, at
    the same trigger prices, with matched risk (stop_mode='frac', one OR width each side).
    Both are fully simulated paths, so stops and time exits resolve honestly for each.

    An earlier version of this test compared only the trades that reached a time exit. That
    was invalid: a trade reaches a time exit precisely BECAUSE it was never stopped out, so
    conditioning on it conditions on the outcome and flatters the real side by construction.
    The fade comparison has no such conditioning -- every session enters on both variants.
    """
    kw = dict(or_minutes=or_minutes, entry_cutoff=entry_cutoff, time_exit=time_exit,
              target_r=None, stop_mode="frac", stop_frac=1.0)
    follow = trades_frame(run_orb(df, OrbParams(**kw), costs))
    fade = trades_frame(run_orb(df, OrbParams(fade=True, **kw), costs))
    if follow.empty or fade.empty:
        return {}

    def agg(t):
        usd = t["net_usd"].to_numpy(dtype=float)
        r = t["r_multiple"].to_numpy(dtype=float)
        r = r[np.isfinite(r)]
        return {
            "trades": len(t), "win_rate": float((usd > 0).mean()),
            "avg_r": float(r.mean()) if len(r) else np.nan,
            "total_usd": float(usd.sum()), "expectancy_usd": float(usd.mean()),
            "t_stat_r": float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r))))
            if len(r) > 1 and r.std(ddof=1) > 0 else np.nan,
        }

    f, d = agg(follow), agg(fade)
    # Paired per-session difference: the cleanest read on whether the sign carries signal.
    j = follow.set_index("session")[["net_usd"]].join(
        fade.set_index("session")[["net_usd"]], lsuffix="_follow", rsuffix="_fade", how="inner")
    diff = (j["net_usd_follow"] - j["net_usd_fade"]).to_numpy(dtype=float)
    t_paired = (diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff)))) \
        if len(diff) > 1 and diff.std(ddof=1) > 0 else np.nan
    return {"follow": f, "fade": d, "paired_sessions": len(diff),
            "paired_mean_diff_usd": float(diff.mean()), "paired_t": float(t_paired)}


# ----------------------------------------------------------------------------- main
def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    grid = build_grid()
    report: list[str] = []

    def say(s: str = "") -> None:
        print(s, flush=True)
        report.append(s)

    # ---------------- ES leg ----------------
    say("=" * 78)
    say("LEG 1 -- ES (E-mini S&P 500), Polygon futures 1-min, front-month stitched")
    say("=" * 78)
    es = load_es_1min(verbose=False)
    es_rth = es.between_time(time(9, 30), time(16, 0), inclusive="left")
    say(f"bars {len(es):,} | RTH bars {len(es_rth):,} | sessions {n_sessions(es)}")
    say(f"span {es.index.min()} -> {es.index.max()}")
    say(f"contracts used: {sorted(es['contract'].unique())}")
    say(f"pre-registered OOS boundary: {ES_OOS_START}")
    say()

    g_es = run_leg(es, ES_COSTS, grid, "ES", ES_OOS_START)
    g_es.to_csv(OUT / "grid_es.csv", index=False)

    cols = ["label", "split", "trades", "win_rate", "avg_r", "expectancy_usd",
            "total_usd", "profit_factor", "max_dd_usd", "sharpe", "t_stat_r"]
    full = g_es[(g_es["split"] == "full") & (g_es["direction"] == "both")].copy()
    say("--- ES full sample (1 contract, gap-aware fills, $2.50 RT commission, 1 tick slip) ---")
    say(full[cols].to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
    say()

    # ---------------- MNQ leg ----------------
    say("=" * 78)
    say("LEG 2 -- MNQ/NQ (Nasdaq-100 futures), Databento 1-min RTH, 16-year regime check")
    say("=" * 78)
    mnq_df = None
    if not MNQ_PATH.exists():
        say(f"MNQ data not found at {MNQ_PATH} -- skipping leg 2")
        g_mnq = pd.DataFrame()
    else:
        mnq = pd.read_parquet(MNQ_PATH)[["open", "high", "low", "close", "volume"]]
        mnq_df = mnq
        say(f"bars {len(mnq):,} | sessions {n_sessions(mnq)}")
        say(f"span {mnq.index.min()} -> {mnq.index.max()}")
        say(f"pre-registered OOS boundary: {MNQ_OOS_START}")
        say()
        g_mnq = run_leg(mnq, MNQ_COSTS, grid, "MNQ", MNQ_OOS_START)
        g_mnq.to_csv(OUT / "grid_mnq.csv", index=False)
        fm = g_mnq[(g_mnq["split"] == "full") & (g_mnq["direction"] == "both")].copy()
        say("--- MNQ full sample (1 contract, gap-aware fills, $1.04 RT commission, 1 tick slip) ---")
        say(fm[cols].to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
        say()

    # ---------------- IS / OOS ----------------
    for leg_name, gdf in (("ES", g_es), ("MNQ", g_mnq)):
        if gdf.empty:
            continue
        say("=" * 78)
        say(f"{leg_name} -- in-sample vs out-of-sample (every config shown, not just the winner)")
        say("=" * 78)
        piv = gdf[(gdf["split"] != "full") & (gdf["direction"] == "both")].pivot_table(
            index="label", columns="split", values=["avg_r", "trades", "total_usd"],
            aggfunc="first")
        say(piv.to_string(float_format=lambda x: f"{x:,.3f}"))
        say()

    # ---------------- direction split ----------------
    say("=" * 78)
    say("DIRECTION SPLIT -- long-only vs short-only (no target, i.e. hold to the exit time)")
    say("=" * 78)
    for leg_name, gdf in (("ES", g_es), ("MNQ", g_mnq)):
        if gdf.empty:
            continue
        d = gdf[(gdf["split"] == "full") & (gdf["direction"] != "both")
                & (gdf["target_r"] == "none")]
        say(f"--- {leg_name} ---")
        say(d[["label", "trades", "win_rate", "avg_r", "total_usd", "profit_factor",
               "sharpe"]].to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
        say()

    # ---------------- control: unconditional exposure ----------------
    say("=" * 78)
    say("CONTROL -- does the breakout beat simply being in the market over the same hours?")
    say("=" * 78)
    say("Enter every session at the open of the first bar after the opening range, exit at")
    say("the same time the ORB variant does. No breakout test, no stop. 1 contract.")
    say()
    legs = [("ES", es, ES_COSTS, g_es)]
    if MNQ_PATH.exists():
        legs.append(("MNQ", mnq_df, MNQ_COSTS, g_mnq))
    ctrl_rows = []
    for leg_name, dfx, cx, gdf in legs:
        for or_min in (15, 30):
            for texit in (time(11, 0), time(15, 59)):
                for side, sname in ((1, "always_long"), (-1, "always_short")):
                    c = run_always_in(dfx, cx, or_min, texit, side)
                    if c.empty:
                        continue
                    orb = gdf[(gdf["split"] == "full") & (gdf["or_minutes"] == or_min)
                              & (gdf["time_exit"] == texit.strftime("%H:%M"))
                              & (gdf["target_r"] == "none")
                              & (gdf["direction"] == "both")]
                    ctrl_rows.append({
                        "leg": leg_name, "or_minutes": or_min,
                        "time_exit": texit.strftime("%H:%M"), "control": sname,
                        "control_trades": len(c),
                        "control_total_usd": c["net_usd"].sum(),
                        "control_win_rate": (c["net_usd"] > 0).mean(),
                        "orb_trades": int(orb["trades"].iloc[0]) if len(orb) else np.nan,
                        "orb_total_usd": orb["total_usd"].iloc[0] if len(orb) else np.nan,
                    })
    ctrl = pd.DataFrame(ctrl_rows)
    ctrl.to_csv(OUT / "control_always_in.csv", index=False)
    say(ctrl.to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    say()

    # ---------------- Gate 2: execution honesty ----------------
    say("=" * 78)
    say("GATE 2 -- how much of the P&L is an execution artifact?")
    say("=" * 78)
    head = OrbParams(or_minutes=15, entry_cutoff=time(11, 0), time_exit=time(15, 59),
                     target_r=None)
    for leg_name, dfx, cx in (("ES", es, ES_COSTS), ("MNQ", mnq_df, MNQ_COSTS)):
        if dfx is None:
            continue
        honest = trades_frame(run_orb(dfx, head, cx, gap_aware=True))
        fantasy = trades_frame(run_orb(dfx, head, cx, gap_aware=False))
        if honest.empty:
            continue
        delta = fantasy["net_usd"].sum() - honest["net_usd"].sum()
        say(f"{leg_name} {head.label()}: honest ${honest['net_usd'].sum():,.0f} | "
            f"fantasy-fill ${fantasy['net_usd'].sum():,.0f} | "
            f"artifact ${delta:,.0f} ({delta / abs(fantasy['net_usd'].sum()) * 100:.1f}% of fantasy P&L)")
        say(f"     entries that gapped through the trigger: {honest['entry_gapped'].mean():.1%}")
    say()

    # ---------------- placebo ----------------
    say("=" * 78)
    say("PLACEBO -- is the breakout direction informative, or just exposure?")
    say("=" * 78)
    say("Same bars, same trigger prices, matched risk of one OR width: follow the break vs")
    say("fade it. Both fully simulated. If the sign carries no information, the paired")
    say("difference is indistinguishable from zero.")
    say()
    for leg_name, dfx, cx in (("ES", es, ES_COSTS), ("MNQ", mnq_df, MNQ_COSTS)):
        if dfx is None:
            continue
        for or_min in (15, 30):
            for texit in (time(11, 0), time(15, 59)):
                pl = matched_placebo(dfx, cx, or_min, time(11, 0), texit)
                if not pl:
                    continue
                f, d = pl["follow"], pl["fade"]
                say(f"{leg_name} OR{or_min}m exit {texit.strftime('%H:%M')}:")
                say(f"    follow: {f['trades']:5d} trades  avg R {f['avg_r']:+.4f}  "
                    f"total ${f['total_usd']:>11,.0f}  t {f['t_stat_r']:+.2f}")
                say(f"    fade  : {d['trades']:5d} trades  avg R {d['avg_r']:+.4f}  "
                    f"total ${d['total_usd']:>11,.0f}  t {d['t_stat_r']:+.2f}")
                say(f"    paired follow-minus-fade: ${pl['paired_mean_diff_usd']:+,.2f}"
                    f"/session over {pl['paired_sessions']} sessions, t = {pl['paired_t']:+.2f}")
        say()

    # ---------------- MNQ by year ----------------
    if MNQ_PATH.exists():
        say("=" * 78)
        say("MNQ -- year by year (the question 500 ES sessions cannot answer)")
        say("=" * 78)
        t = trades_frame(run_orb(mnq_df, head, MNQ_COSTS))
        t["year"] = pd.to_datetime(t["session"]).dt.year
        by = t.groupby("year").agg(
            trades=("net_usd", "size"), win_rate=("net_usd", lambda s: (s > 0).mean()),
            avg_r=("r_multiple", "mean"), total_usd=("net_usd", "sum"))
        by.to_csv(OUT / "by_year_mnq.csv")
        say(by.to_string(float_format=lambda x: f"{x:,.3f}"))
        say()
        t.to_csv(OUT / f"trades_MNQ_{head.label().replace('/', '_')}.csv", index=False)

    t_es = trades_frame(run_orb(es, head, ES_COSTS))
    t_es.to_csv(OUT / f"trades_ES_{head.label().replace('/', '_')}.csv", index=False)

    (OUT / "summary.txt").write_text("\n".join(report))
    print(f"\nwrote {OUT/'summary.txt'}")


if __name__ == "__main__":
    main()
