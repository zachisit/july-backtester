"""
Cost ladder: is the 09:45-11:00 ORB a pattern that costs eat, or no pattern at all?

The earlier equity-ORB study in this repo found a real GROSS edge that died entirely in
slippage. That is a different conclusion from "there is nothing here", and the two are only
distinguishable by running the same rules at zero cost.

Ladder: 0 / 0.5 / 1 / 2 ticks of slippage per fill, with and without commission. Zero-cost
is not tradeable -- it is a diagnostic for whether the raw directional pattern exists.
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
from es_orb_research import MNQ_PATH  # noqa: E402

OUT = HERE.parent / "output"

CONFIGS = [
    OrbParams(or_minutes=15, entry_cutoff=time(11, 0), time_exit=time(11, 0)),
    OrbParams(or_minutes=15, entry_cutoff=time(11, 0), time_exit=time(15, 59)),
    OrbParams(or_minutes=30, entry_cutoff=time(11, 0), time_exit=time(11, 0)),
    OrbParams(or_minutes=30, entry_cutoff=time(11, 0), time_exit=time(15, 59)),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def say(s: str = "") -> None:
        print(s, flush=True)
        lines.append(s)

    legs = [("ES", load_es_1min(verbose=False), 50.0, 2.50)]
    if MNQ_PATH.exists():
        legs.append(("MNQ", pd.read_parquet(MNQ_PATH)[["open", "high", "low", "close", "volume"]],
                     2.0, 1.04))

    rows = []
    for leg, dfx, pv, comm_full in legs:
        for p in CONFIGS:
            for slip_ticks in (0.0, 0.5, 1.0, 2.0):
                for comm, cname in ((0.0, "no"), (comm_full, "yes")):
                    c = Costs(tick_size=0.25, point_value=pv,
                              slippage_ticks=slip_ticks, commission_rt=comm)
                    t = trades_frame(run_orb(dfx, p, c))
                    if t.empty:
                        continue
                    usd = t["net_usd"].to_numpy(dtype=float)
                    gw, gl = usd[usd > 0].sum(), -usd[usd < 0].sum()
                    rows.append({
                        "leg": leg, "config": p.label(), "slip_ticks": slip_ticks,
                        "commission": cname, "trades": len(t),
                        "total_usd": usd.sum(), "expectancy_usd": usd.mean(),
                        "avg_pts": t["points"].mean(),
                        "profit_factor": gw / gl if gl > 0 else np.inf,
                        "win_rate": float((usd > 0).mean()),
                    })
    res = pd.DataFrame(rows)
    res.to_csv(OUT / "cost_ladder.csv", index=False)

    say("=" * 96)
    say("COST LADDER -- gross pattern vs net tradeability")
    say("=" * 96)
    say("slip_ticks=0 with commission=no is the GROSS diagnostic: not tradeable, but it says")
    say("whether the raw directional pattern exists before execution is charged for.")
    say("ES: 1 tick = 0.25 pt = $12.50/contract.  MNQ: 1 tick = 0.25 pt = $0.50/contract.")
    say()
    for leg in res["leg"].unique():
        say(f"--- {leg} ---")
        piv = res[res["leg"] == leg].pivot_table(
            index="config", columns=["commission", "slip_ticks"],
            values="total_usd", aggfunc="first")
        say(piv.to_string(float_format=lambda x: f"{x:,.0f}"))
        say()
        say(f"  mean points per trade, gross (slip 0 / no commission):")
        g = res[(res["leg"] == leg) & (res["slip_ticks"] == 0.0) & (res["commission"] == "no")]
        for _, r in g.iterrows():
            say(f"    {r['config']:44s} {r['avg_pts']:+.4f} pts x {int(r['trades'])} trades "
                f"= {r['total_usd']:+,.0f} USD  (PF {r['profit_factor']:.3f})")
        say()

    say("=" * 96)
    say("BREAK-EVEN SLIPPAGE -- how many ticks per fill the gross edge can pay for")
    say("=" * 96)
    for leg in res["leg"].unique():
        for cfg in res[res["leg"] == leg]["config"].unique():
            g = res[(res["leg"] == leg) & (res["config"] == cfg)
                    & (res["slip_ticks"] == 0.0) & (res["commission"] == "no")]
            if g.empty:
                continue
            gross_pts = float(g["avg_pts"].iloc[0])
            # Each fill costs slip_ticks * 0.25 pts; a round trip pays it twice.
            be_ticks = gross_pts / (2 * 0.25) if gross_pts > 0 else 0.0
            say(f"{leg:4s} {cfg:44s} gross {gross_pts:+.4f} pts/trade -> "
                f"break-even at {be_ticks:.2f} ticks/fill"
                + ("  (no gross edge to pay with)" if gross_pts <= 0 else ""))
    say()
    (OUT / "cost_summary.txt").write_text("\n".join(lines))
    print(f"wrote {OUT/'cost_summary.txt'}")


if __name__ == "__main__":
    main()
