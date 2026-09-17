"""
Why is the gap-aware-fill artifact exactly $0?

Claim: the strategy is STRUCTURALLY immune to the fantasy-fill artifact, because (a) it never
holds a position overnight, and (b) inside RTH, ES trades continuously, so each 1-minute
bar's open equals the prior bar's close to within a tick -- there is no bar-boundary gap for
a resting stop to be jumped through.

That claim is only worth anything if measured. The mutation tests already prove the engine's
gap logic fires on synthetic gapped bars, so if real RTH minute bars are contiguous, a $0
artifact is the correct answer rather than a dead code path.
"""
from __future__ import annotations

import sys
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from es_futures_data import load_es_1min  # noqa: E402
from es_orb_research import MNQ_PATH  # noqa: E402


def report(name: str, df: pd.DataFrame, tick: float) -> None:
    rth = df.between_time(time(9, 30), time(16, 0), inclusive="left")
    out = []
    for _, bars in rth.groupby(rth.index.date, sort=True):
        o = bars["open"].to_numpy(dtype=float)
        c = bars["close"].to_numpy(dtype=float)
        if len(o) < 2:
            continue
        # gap at each interior bar boundary: this bar's open vs the previous bar's close
        out.append(o[1:] - c[:-1])
    g = np.concatenate(out)
    aticks = np.abs(g) / tick
    print(f"--- {name}: {len(g):,} interior 1-min bar boundaries ---")
    print(f"  |gap| == 0 ticks : {(aticks < 1e-9).mean():7.3%}")
    print(f"  |gap| <= 1 tick  : {(aticks <= 1.0 + 1e-9).mean():7.3%}")
    print(f"  |gap| <= 2 ticks : {(aticks <= 2.0 + 1e-9).mean():7.3%}")
    print(f"  |gap|  > 4 ticks : {(aticks > 4.0).mean():7.3%}  "
          f"(count {int((aticks > 4.0).sum()):,})")
    print(f"  max |gap|        : {aticks.max():.1f} ticks")
    print(f"  mean |gap|       : {aticks.mean():.4f} ticks")
    print()


def main() -> None:
    report("ES  (Polygon futures 1-min, RTH)", load_es_1min(verbose=False), 0.25)
    if MNQ_PATH.exists():
        mnq = pd.read_parquet(MNQ_PATH)[["open", "high", "low", "close", "volume"]]
        report("MNQ (Databento 1-min, RTH)", mnq, 0.25)
    print("A stop can only be jumped at a bar boundary. With essentially every boundary at")
    print("0-1 ticks, a resting stop inside RTH fills at its level, so honest and fantasy")
    print("fills coincide. The artifact is absent by construction, not by omission.")


if __name__ == "__main__":
    main()
