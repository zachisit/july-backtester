"""
Conditional sweep: is there a SUBSET of sessions where the 09:45-11:00 ORB works?

The unconditional strategy is a loser (see summary.txt). The steelman is that the published
ORB results condition on the day being tradeable at all -- Zarattini & Aziz screen for high
relative volume / volatility rather than trading every session. So this asks whether any
session-level gate rescues it.

METHOD. The base config is run ONCE and every filter is evaluated by subsetting that trade
list. This is exactly equivalent to re-running the engine per filter, because the strategy
takes at most one trade per session and carries no state between sessions, so dropping a
session's trade cannot change any other trade. All gates use only information available
before the entry decision (prior-session closes, trailing statistics shifted by one session,
and the opening range itself, which completes before the window opens).

MULTIPLICITY. This is an explicitly exploratory sweep. The number of comparisons is printed
with the results, along with the number of subsets expected to clear each bar by chance
alone. A subset that looks good here is a hypothesis, not a finding, and the IS/OOS columns
are the first thing to read -- not the full-sample column.
"""
from __future__ import annotations

import sys
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from orb_engine import Costs, OrbParams, run_orb, trades_frame  # noqa: E402
from es_futures_data import load_es_1min  # noqa: E402
from es_orb_research import (ES_COSTS, MNQ_COSTS, MNQ_PATH, ES_OOS_START,  # noqa: E402
                             MNQ_OOS_START, sessions_of)

OUT = HERE.parent / "output"


def session_features(df: pd.DataFrame, or_minutes: int = 15) -> pd.DataFrame:
    """Per-session features, each usable at the moment the trade window opens."""
    rth = df.between_time(time(9, 30), time(16, 0), inclusive="left")
    or_end = 9 * 60 + 30 + or_minutes
    g = rth.groupby(rth.index.date)
    daily = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(),
        "low": g["low"].min(), "close": g["close"].last(),
        "volume": g["volume"].sum(),
    })
    mins = rth.index.hour * 60 + rth.index.minute
    orb = rth[mins < or_end]
    og = orb.groupby(orb.index.date)
    feats = pd.DataFrame({
        "or_high": og["high"].max(), "or_low": og["low"].min(),
        "or_open": og["open"].first(), "or_volume": og["volume"].sum(),
    })
    feats["or_width"] = feats["or_high"] - feats["or_low"]
    feats["or_width_frac"] = feats["or_width"] / feats["or_open"]

    prev_close = daily["close"].shift(1)
    feats["gap_frac"] = (feats["or_open"] - prev_close) / prev_close
    feats["prev_close"] = prev_close

    # trailing, one-session-shifted normalisers (no look-ahead)
    feats["or_width_med60"] = feats["or_width_frac"].rolling(60).median().shift(1)
    feats["or_width_rel"] = feats["or_width_frac"] / feats["or_width_med60"]
    feats["or_vol_med60"] = feats["or_volume"].rolling(60).median().shift(1)
    feats["or_vol_rel"] = feats["or_volume"] / feats["or_vol_med60"]

    tr = pd.concat([daily["high"] - daily["low"],
                    (daily["high"] - prev_close).abs(),
                    (daily["low"] - prev_close).abs()], axis=1).max(axis=1)
    feats["atr14"] = tr.rolling(14).mean().shift(1)
    feats["or_over_atr"] = feats["or_width"] / feats["atr14"]

    feats["sma20"] = daily["close"].rolling(20).mean().shift(1)
    feats["above_sma20"] = feats["or_open"] > feats["sma20"]
    feats["dow"] = pd.to_datetime(feats.index).dayofweek
    return feats


def evaluate(t: pd.DataFrame, costs: Costs, n_sess: int) -> dict:
    if t.empty:
        return {"trades": 0, "win_rate": np.nan, "avg_r": np.nan, "total_usd": 0.0,
                "profit_factor": np.nan, "t_stat_r": np.nan, "max_dd_usd": np.nan}
    usd = t["net_usd"].to_numpy(dtype=float)
    r = t["r_multiple"].to_numpy(dtype=float)
    r = r[np.isfinite(r)]
    gw, gl = usd[usd > 0].sum(), -usd[usd < 0].sum()
    eq = np.cumsum(usd)
    dd = eq - np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]
    return {
        "trades": len(t), "sessions": n_sess,
        "win_rate": float((usd > 0).mean()), "avg_r": float(r.mean()) if len(r) else np.nan,
        "expectancy_usd": float(usd.mean()), "total_usd": float(usd.sum()),
        "profit_factor": float(gw / gl) if gl > 0 else np.inf,
        "max_dd_usd": float(dd.min()),
        "t_stat_r": float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r))))
        if len(r) > 1 and r.std(ddof=1) > 0 else np.nan,
    }


def build_filters(f: pd.DataFrame) -> dict[str, pd.Series]:
    """Session-level gates. Each maps to a boolean mask over the session index."""
    out: dict[str, pd.Series] = {"(none)": pd.Series(True, index=f.index)}
    for lo, hi, name in [(0.0, 0.75, "narrow"), (0.75, 1.25, "typical"), (1.25, 99.0, "wide")]:
        out[f"or_width_rel_{name}"] = (f["or_width_rel"] >= lo) & (f["or_width_rel"] < hi)
    for lo, hi, name in [(0.0, 0.9, "quiet"), (0.9, 1.3, "normal"), (1.3, 99.0, "busy")]:
        out[f"or_volume_rel_{name}"] = (f["or_vol_rel"] >= lo) & (f["or_vol_rel"] < hi)
    out["gap_up_gt_0.25pct"] = f["gap_frac"] > 0.0025
    out["gap_dn_lt_-0.25pct"] = f["gap_frac"] < -0.0025
    out["gap_small_lt_0.15pct"] = f["gap_frac"].abs() < 0.0015
    out["above_sma20"] = f["above_sma20"].fillna(False)
    out["below_sma20"] = (~f["above_sma20"].fillna(True))
    out["or_lt_0.4_atr"] = f["or_over_atr"] < 0.4
    out["or_gt_0.7_atr"] = f["or_over_atr"] > 0.7
    for d, name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri"]):
        out[f"dow_{name}"] = f["dow"] == d
    return out


def sweep(df: pd.DataFrame, costs: Costs, leg: str, oos_start,
          params: OrbParams) -> pd.DataFrame:
    t = trades_frame(run_orb(df, params, costs))
    if t.empty:
        return pd.DataFrame()
    f = session_features(df, params.or_minutes)
    filters = build_filters(f)
    t = t.copy()
    t["_sess"] = pd.to_datetime(t["session"])

    rows = []
    for name, mask in filters.items():
        keep = set(pd.to_datetime(pd.Index(mask.index)[mask.to_numpy(dtype=bool)]))
        sub = t[t["_sess"].isin(keep)]
        for split in ("full", "IS", "OOS"):
            if split == "IS":
                s2 = sub[sub["_sess"].dt.date < oos_start]
                nsess = len({d for d in keep if d.date() < oos_start})
            elif split == "OOS":
                s2 = sub[sub["_sess"].dt.date >= oos_start]
                nsess = len({d for d in keep if d.date() >= oos_start})
            else:
                s2, nsess = sub, len(keep)
            m = evaluate(s2, costs, nsess)
            m.update({"leg": leg, "filter": name, "split": split,
                      "config": params.label()})
            rows.append(m)
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def say(s: str = "") -> None:
        print(s, flush=True)
        lines.append(s)

    # Two base configs: the two readings of the spec.
    configs = [
        OrbParams(or_minutes=15, entry_cutoff=time(11, 0), time_exit=time(11, 0)),
        OrbParams(or_minutes=15, entry_cutoff=time(11, 0), time_exit=time(15, 59)),
        OrbParams(or_minutes=30, entry_cutoff=time(11, 0), time_exit=time(11, 0)),
        OrbParams(or_minutes=30, entry_cutoff=time(11, 0), time_exit=time(15, 59)),
    ]

    es = load_es_1min(verbose=False)
    legs = [("ES", es, ES_COSTS, ES_OOS_START)]
    if MNQ_PATH.exists():
        mnq = pd.read_parquet(MNQ_PATH)[["open", "high", "low", "close", "volume"]]
        legs.append(("MNQ", mnq, MNQ_COSTS, MNQ_OOS_START))

    allr = []
    for leg, dfx, cx, oos in legs:
        for p in configs:
            allr.append(sweep(dfx, cx, leg, oos, p))
    res = pd.concat(allr, ignore_index=True)
    res.to_csv(OUT / "conditional_sweep.csv", index=False)

    n_filters = res["filter"].nunique() - 1          # exclude the "(none)" baseline
    n_configs = res["config"].nunique()
    n_legs = res["leg"].nunique()
    n_tests = n_filters * n_configs * n_legs

    say("=" * 92)
    say("CONDITIONAL SWEEP -- is there a subset of sessions where the 09:45-11:00 ORB works?")
    say("=" * 92)
    say(f"{n_filters} real session gates x {n_configs} configs x {n_legs} instruments = "
        f"{n_tests} comparisons "
        f"({res['filter'].nunique()} x {n_configs} x {n_legs} = "
        f"{res['filter'].nunique() * n_configs * n_legs} cells including the unfiltered "
        f"baseline row).")
    say("Read the OOS column first. A gate that is positive full-sample but negative OOS is")
    say("a description of the past, not a strategy.")
    say()

    piv = res.pivot_table(index=["leg", "config", "filter"], columns="split",
                          values=["trades", "avg_r", "total_usd", "t_stat_r"],
                          aggfunc="first")
    piv = piv.reorder_levels([1, 0], axis=1).sort_index(axis=1)

    for leg in res["leg"].unique():
        say("=" * 92)
        say(f"--- {leg} ---")
        say("=" * 92)
        sub = piv.loc[leg]
        cols = [("full", "trades"), ("full", "avg_r"), ("full", "total_usd"),
                ("full", "t_stat_r"), ("IS", "avg_r"), ("OOS", "avg_r"),
                ("OOS", "total_usd")]
        cols = [c for c in cols if c in sub.columns]
        say(sub[cols].to_string(float_format=lambda x: f"{x:,.3f}"))
        say()

    # How many gates survive the only test that matters: positive in BOTH IS and OOS?
    say("=" * 92)
    say("SURVIVORS -- gates with positive avg R in BOTH in-sample and out-of-sample")
    say("=" * 92)
    w = res.pivot_table(index=["leg", "config", "filter"], columns="split",
                        values="avg_r", aggfunc="first")
    tr = res.pivot_table(index=["leg", "config", "filter"], columns="split",
                         values="trades", aggfunc="first")
    ok = w[(w["IS"] > 0) & (w["OOS"] > 0) & (tr["OOS"] >= 30)]
    say(f"gates tested: {len(w)} | positive in both splits with >=30 OOS trades: {len(ok)}")
    if len(ok):
        say(ok.join(tr, rsuffix="_n").to_string(float_format=lambda x: f"{x:,.3f}"))
    else:
        say("none.")
    say()

    # ---- how many survivors would random gates of the same sizes produce? ----
    say("=" * 92)
    say("MULTIPLICITY CALIBRATION -- the survivor count under randomised gates")
    say("=" * 92)
    say("Each gate is replaced by a random set of sessions OF THE SAME SIZE, drawn from the")
    say("same sessions, and the survivor rule is re-applied. This calibrates how many gates")
    say("'positive in both splits with >=30 OOS trades' produces when the gates carry no")
    say("information at all, holding the trade list and the gate sizes fixed.")
    say()
    rng = np.random.default_rng(11)
    n_perm = 400
    counts = []
    # cache per-(leg, config) trade lists and gate sizes once
    cache = []
    for leg, dfx, cx, oos in legs:
        f_all = {om: session_features(dfx, om) for om in {p.or_minutes for p in configs}}
        for p in configs:
            t = trades_frame(run_orb(dfx, p, cx))
            if t.empty:
                continue
            t = t.copy()
            t["_sess"] = pd.to_datetime(t["session"])
            f = f_all[p.or_minutes]
            sizes = [int(m.to_numpy(dtype=bool).sum())
                     for n, m in build_filters(f).items() if n != "(none)"]
            cache.append((t, pd.to_datetime(pd.Index(f.index)), sizes, oos))

    for _ in range(n_perm):
        surv = 0
        for t, sess_idx, sizes, oos in cache:
            for k in sizes:
                if k <= 0:
                    continue
                pick = set(rng.choice(sess_idx, size=min(k, len(sess_idx)), replace=False))
                sub = t[t["_sess"].isin(pick)]
                a = sub[sub["_sess"].dt.date < oos]["r_multiple"]
                b = sub[sub["_sess"].dt.date >= oos]["r_multiple"]
                if len(b) >= 30 and a.mean() > 0 and b.mean() > 0:
                    surv += 1
        counts.append(surv)
    counts = np.asarray(counts, dtype=float)
    obs = len(ok)
    say(f"observed survivors: {obs}")
    say(f"randomised gates ({n_perm} draws): mean {counts.mean():.1f}, "
        f"median {np.median(counts):.0f}, 5th-95th pct "
        f"{np.percentile(counts, 5):.0f}-{np.percentile(counts, 95):.0f}")
    say(f"P(random >= observed) = {(counts >= obs).mean():.3f}")
    if (counts >= obs).mean() > 0.05:
        say("=> the observed survivor count is NOT more than uninformative gates produce.")
    else:
        say("=> the observed survivor count exceeds the randomised null; worth a second look.")
    say()

    (OUT / "conditional_summary.txt").write_text("\n".join(lines))
    print(f"wrote {OUT/'conditional_summary.txt'}")


if __name__ == "__main__":
    main()
