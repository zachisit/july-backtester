"""
Why the MNQ dollar total is misleading: the risk unit grew ~15x over the sample.

The 16-year MNQ leg reports a positive dollar total (+$15.8k per contract) alongside an
average R-multiple of essentially zero. Both are correct, and the reconciliation matters more
than either number.

Trading a FIXED one contract on a series whose index level rose 5x and whose opening-range
width rose ~15x means each later trade risks ~15x more dollars than an early one. Summing raw
dollars therefore weights 2025 roughly fifteen times as heavily as 2011. The R-multiple
normalises by the risk actually taken, which is the comparable unit across regimes.

This script prints both, plus the equal-weighted mean of the yearly average R -- the number
that answers "in a typical year, did this work?".
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
from es_orb_research import ES_COSTS, MNQ_COSTS, MNQ_PATH  # noqa: E402

OUT = HERE.parent / "output"


def table(t: pd.DataFrame, point_value: float) -> pd.DataFrame:
    t = t.copy()
    t["year"] = pd.to_datetime(t["session"]).dt.year
    b = t.groupby("year").agg(
        trades=("net_usd", "size"),
        mean_entry_px=("entry_px", "mean"),
        mean_risk_pts=("risk_pts", "mean"),
        avg_r=("r_multiple", "mean"),
        total_usd=("net_usd", "sum"),
    )
    b["risk_usd_per_trade"] = b["mean_risk_pts"] * point_value
    return b


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def say(s: str = "") -> None:
        print(s, flush=True)
        lines.append(s)

    cfgs = [OrbParams(or_minutes=15, entry_cutoff=time(11, 0), time_exit=time(15, 59)),
            OrbParams(or_minutes=30, entry_cutoff=time(11, 0), time_exit=time(15, 59))]
    legs = [("ES", load_es_1min(verbose=False), ES_COSTS)]
    if MNQ_PATH.exists():
        legs.append(("MNQ", pd.read_parquet(MNQ_PATH)[["open", "high", "low", "close", "volume"]],
                     MNQ_COSTS))

    say("=" * 88)
    say("RISK SCALING -- reconciling the dollar total with the average R")
    say("=" * 88)
    say("both 'hold to the close' readings, 1 contract, net of costs")
    say()

    for leg, dfx, cx in legs:
      for cfg in cfgs:
        t = trades_frame(run_orb(dfx, cfg, cx))
        if t.empty:
            continue
        b = table(t, cx.point_value)
        b.to_csv(OUT / f"risk_scaling_{leg}_OR{cfg.or_minutes}.csv")
        say(f"--- {leg}  {cfg.label()} ---")
        say(b.to_string(float_format=lambda x: f"{x:,.2f}"))
        say()

        first, last = b.index.min(), b.index.max()
        early = b[b.index <= 2020]["total_usd"].sum()
        mid = b[(b.index >= 2021) & (b.index <= 2025)]["total_usd"].sum()
        late = b[b.index >= 2026]["total_usd"].sum()
        growth = b.loc[last, "mean_risk_pts"] / b.loc[first, "mean_risk_pts"]
        say(f"  risk per trade grew {growth:.1f}x from {first} to {last} "
            f"(${b.loc[first, 'risk_usd_per_trade']:,.0f} -> "
            f"${b.loc[last, 'risk_usd_per_trade']:,.0f})")
        say(f"  dollar total, fixed 1 contract .......... {b['total_usd'].sum():+,.0f} USD")
        if len(b) > 5:
            say(f"    of which <=2020 {early:+,.0f} | 2021-2025 {mid:+,.0f} | "
                f">=2026 {late:+,.0f}")
        say(f"  trade-weighted average R ................ "
            f"{np.average(b['avg_r'], weights=b['trades']):+.4f}")
        say(f"  EQUAL-WEIGHTED mean of yearly average R . {b['avg_r'].mean():+.4f}")
        say(f"  years with negative average R ........... "
            f"{int((b['avg_r'] < 0).sum())} of {len(b)}")
        say()
        if growth > 2 and b["total_usd"].sum() > 0 and b["avg_r"].mean() < 0:
            say("  => the positive dollar total is a sizing artifact. Fixed-contract sizing on")
            say("     a series whose risk unit multiplied puts almost all the weight on the")
            say("     most recent years; per unit of risk actually taken, the typical year")
            say("     LOST money.")
            say()

    (OUT / "risk_scaling_summary.txt").write_text("\n".join(lines))
    print(f"wrote {OUT/'risk_scaling_summary.txt'}")


if __name__ == "__main__":
    main()
