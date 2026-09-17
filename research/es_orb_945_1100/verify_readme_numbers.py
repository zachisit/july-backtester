#!/usr/bin/env python3
"""
Verify every number quoted in README.md against the result CSVs it came from.

Numbers get copied into prose once and then drift as the code changes underneath them. This
reads the README's tables, looks each value up in the artifact it is supposed to come from,
and fails on any mismatch. Expected values are derived from the CSVs -- nothing is hardcoded
here, so a bug in the pipeline cannot be masked by a matching constant in the checker.

Run:  python research/es_orb_945_1100/verify_readme_numbers.py
Exits non-zero on the first disagreement, listing all of them.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
README = HERE / "README.md"
RESULTS = HERE / "results"

# README label -> (or_minutes, time_exit, target_r) in grid_*.csv terms
CONFIG_KEY = {
    "OR15 · flat 11:00 · no target": (15, "11:00", "none"),
    "OR15 · flat 11:00 · 1R": (15, "11:00", "1.0"),
    "OR15 · flat 11:00 · 2R": (15, "11:00", "2.0"),
    "OR15 · to close · no target": (15, "15:59", "none"),
    "OR15 · to close · 1R": (15, "15:59", "1.0"),
    "OR15 · to close · 2R": (15, "15:59", "2.0"),
    "OR30 · flat 11:00 · no target": (30, "11:00", "none"),
    "OR30 · flat 11:00 · 1R": (30, "11:00", "1.0"),
    "OR30 · flat 11:00 · 2R": (30, "11:00", "2.0"),
    "OR30 · to close · no target": (30, "15:59", "none"),
    "OR30 · to close · 1R": (30, "15:59", "1.0"),
    "OR30 · to close · 2R": (30, "15:59", "2.0"),
}
COST_KEY = {
    "OR15 · flat 11:00": (15, "11:00"),
    "OR15 · to close": (15, "15:59"),
    "OR30 · flat 11:00": (30, "11:00"),
    "OR30 · to close": (30, "15:59"),
}


def num(cell: str) -> float:
    """Parse a README table cell: strips bold, commas, unicode minus, $ and %."""
    c = cell.strip().strip("*").replace(",", "").replace("−", "-")
    c = c.replace("$", "").replace("%", "").replace("+", "")
    return float(c)


def rows_after(heading: str) -> list[list[str]]:
    """Markdown table rows following a heading, as lists of cells."""
    text = README.read_text()
    i = text.index(heading)
    out = []
    for line in text[i:].splitlines()[1:]:
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not all(set(c) <= set("-: ") for c in cells):
                out.append(cells)
        elif out and not line.strip():
            continue
        elif out:
            break
    return out


def main() -> int:
    fails: list[str] = []
    checks = 0

    # ---- ES full-sample grid table ----
    g = pd.read_csv(RESULTS / "grid_es.csv", dtype={"target_r": str})
    g = g[(g["split"] == "full") & (g["direction"] == "both")]
    for cells in rows_after("### ES, full sample"):
        label = cells[0].strip()
        if label not in CONFIG_KEY:
            continue
        om, te, tgt = CONFIG_KEY[label]
        row = g[(g["or_minutes"] == om) & (g["time_exit"] == te) & (g["target_r"] == tgt)]
        if len(row) != 1:
            fails.append(f"ES grid: {label!r} matched {len(row)} rows in grid_es.csv")
            continue
        r = row.iloc[0]
        # Compare at the precision the README prints, so a rounded display is not a
        # mismatch but a genuinely different value always is.
        for i, (name, actual, dp) in enumerate([
            ("trades", r["trades"], 0),
            ("win_rate", r["win_rate"] * 100, 1),
            ("avg_r", r["avg_r"], 3),
            ("total_usd", r["total_usd"], 0),
            ("profit_factor", r["profit_factor"], 2),
            ("max_dd_usd", r["max_dd_usd"], 0),
            ("sharpe", r["sharpe"], 2),
            ("t_stat_r", r["t_stat_r"], 2),
        ], start=1):
            claimed = num(cells[i])
            checks += 1
            if claimed != round(float(actual), dp) + 0.0:
                fails.append(f"ES grid {label!r} {name}: README {claimed} vs csv "
                             f"{actual} (rounds to {round(float(actual), dp)})")

    # ---- control table ----
    c = pd.read_csv(RESULTS / "control_always_in.csv")
    for cells in rows_after("### The control that settles it"):
        if cells[0].strip() != "ES":
            continue
        om = int(cells[1])
        te = "11:00" if cells[2].strip() == "11:00" else "15:59"
        row = c[(c["leg"] == "ES") & (c["or_minutes"] == om) & (c["time_exit"] == te)
                & (c["control"] == "always_long")]
        if len(row) != 1:
            fails.append(f"control: ES OR{om} {te} matched {len(row)} rows")
            continue
        r = row.iloc[0]
        for i, (name, actual) in enumerate([("orb_total_usd", r["orb_total_usd"]),
                                            ("control_total_usd", r["control_total_usd"])],
                                           start=3):
            claimed = num(cells[i])
            checks += 1
            if abs(claimed - actual) > 1.0:
                fails.append(f"control ES OR{om} {te} {name}: README {claimed} vs csv {actual}")

    # ---- cost ladder (gross pts/trade) ----
    cl = pd.read_csv(RESULTS / "cost_ladder.csv")
    gross = cl[(cl["slip_ticks"] == 0.0) & (cl["commission"] == "no")]
    for cells in rows_after("### Is it a pattern that costs eat"):
        leg = cells[0].strip()
        if leg not in ("ES", "MNQ"):
            continue
        key = cells[1].strip()
        if key not in COST_KEY:
            fails.append(f"cost ladder: unrecognised config label {key!r}")
            continue
        om, te = COST_KEY[key]
        pat = f"OR{om}m/cut1100/exit{te.replace(':', '')}/TE/both"
        row = gross[(gross["leg"] == leg) & (gross["config"].str.startswith(pat))]
        if len(row) != 1:
            fails.append(f"cost ladder: {leg} {key} matched {len(row)} rows")
            continue
        claimed = num(cells[2])
        actual = float(row.iloc[0]["avg_pts"])
        checks += 1
        if abs(claimed - actual) > 0.0005:
            fails.append(f"cost ladder {leg} {key} gross pts: README {claimed} vs csv {actual}")

    # ---- MNQ risk-scaling table ----
    for or_min, col in ((15, 2), (30, 3)):
        b = pd.read_csv(RESULTS / f"risk_scaling_MNQ_OR{or_min}.csv").set_index("year")
        expected = {
            "dollar total, fixed 1 contract": b["total_usd"].sum(),
            "≤ 2020 subtotal": b[b.index <= 2020]["total_usd"].sum(),
            "2021–2025 subtotal": b[(b.index >= 2021) & (b.index <= 2025)]["total_usd"].sum(),
            "2026 YTD": b[b.index >= 2026]["total_usd"].sum(),
            "**equal-weighted mean of yearly average R**": b["avg_r"].mean(),
            "years with negative average R": int((b["avg_r"] < 0).sum()),
        }
        for cells in rows_after("### The MNQ dollar total is a sizing artifact"):
            key = cells[0].strip()
            if key not in expected:
                continue
            cell = cells[col - 1]
            # "10 of 17" -> compare the count only; the denominator is len(b), checked below.
            if "years with negative" in key:
                claimed = float(cell.strip().strip("*").split()[0])
                denom = float(cell.strip().strip("*").split()[-1])
                checks += 1
                if abs(denom - len(b)) > 0:
                    fails.append(f"risk scaling MNQ OR{or_min} year count: "
                                 f"README says of {denom:.0f}, csv has {len(b)}")
            else:
                claimed = num(cell)
            actual = expected[key]
            tol = 0.0005 if "average R" in key else 1.0
            checks += 1
            if abs(claimed - actual) > tol:
                fails.append(f"risk scaling MNQ OR{or_min} {key!r}: "
                             f"README {claimed} vs csv {actual}")

    print(f"checked {checks} numbers from README.md against results/")
    if fails:
        print(f"\n{len(fails)} MISMATCH(ES):")
        for f in fails:
            print(f"  - {f}")
        return 1
    print("all match.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
