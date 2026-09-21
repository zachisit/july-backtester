#!/usr/bin/env python3
"""Reconcile a run's annual returns against its own equity curve (#299).

A run report states three things that should agree: per-year returns, an equity
curve, and a total. Compounding the annual figures should reproduce the total.
On the runs that motivated #299 it does not -- and not only for the strategy,
which is what makes it a report defect rather than a strategy one.

Compute is separated from printing so the comparison can be asserted on
directly rather than by parsing stdout.

Usage:
  python scripts/check_annual.py output/runs/<run_id>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

SERIES_KEYS = {"strategy": "strategy_pct", "SPY": "SPY_pct", "QQQ": "QQQ_pct"}


def load_verdict(run_dir: Path) -> dict:
    """Read llm_verdict.json from a run directory."""
    p = Path(run_dir) / "llm_verdict.json"
    if not p.is_file():
        raise FileNotFoundError(f"no llm_verdict.json in {run_dir}")
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _totals(verdict: dict) -> dict:
    s = verdict["strategies"][0]
    b = verdict.get("benchmarks", {})
    return {"strategy": s["strategy_return_pct"],
            "SPY": b.get("SPY"), "QQQ": b.get("QQQ")}


def series_comparison(verdict: dict) -> list[dict]:
    """One row per series: compounded annuals vs curve vs reported total.

    Returns rows rather than printing them, so a caller can assert that the
    three agree -- or that they don't, which is the #299 claim.
    """
    s = verdict["strategies"][0]
    ar, ec = s["annual_returns"], s["equity_curve"]
    totals = _totals(verdict)
    rows = []
    for name, key in SERIES_KEYS.items():
        if name not in ec or totals.get(name) is None:
            continue
        comp = 1.0
        for row in ar:
            comp *= 1.0 + row[key] / 100.0
        comp = (comp - 1.0) * 100.0
        curve = (ec[name][-1] / ec[name][0] - 1.0) * 100.0
        rows.append({"series": name,
                     "annual_compounded_pct": comp,
                     "equity_curve_pct": curve,
                     "reported_total_pct": totals[name],
                     "compounded_minus_reported_pp": comp - totals[name]})
    return rows


def per_year_comparison(verdict: dict, series: str = "strategy") -> list[dict]:
    """Per-year reported figure against what the equity curve implies.

    Year one is measured from the curve's FIRST bar, not from an imaginary
    1 January -- a run starting mid-year has no prior bar to measure against,
    and pretending otherwise invents a return.
    """
    s = verdict["strategies"][0]
    ar, ec = s["annual_returns"], s["equity_curve"]
    dates, eq = ec["dates"], ec[series]
    key = SERIES_KEYS[series]
    rows = []
    for row in ar:
        yr = row["year"]
        idx = [i for i, d in enumerate(dates) if str(d).startswith(str(yr))]
        if not idx:
            continue
        start = eq[idx[0] - 1] if idx[0] > 0 else eq[0]
        derived = (eq[idx[-1]] / start - 1.0) * 100.0
        rows.append({"year": yr, "reported_pct": row[key],
                     "derived_pct": derived,
                     "diff_pp": row[key] - derived,
                     "measured_from_first_bar": idx[0] == 0})
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path, help="output/runs/<run_id>")
    ap.add_argument("--series", default="strategy", choices=sorted(SERIES_KEYS))
    args = ap.parse_args()

    v = load_verdict(args.run_dir)
    print(f"\n  {args.run_dir}")
    print(f"  {'series':<10}{'annual compounded':>19}{'equity curve':>15}{'reported total':>17}{'gap (pp)':>11}")
    for r in series_comparison(v):
        print(f"  {r['series']:<10}{r['annual_compounded_pct']:>19.4f}"
              f"{r['equity_curve_pct']:>15.4f}{r['reported_total_pct']:>17.4f}"
              f"{r['compounded_minus_reported_pp']:>+11.4f}")

    print(f"\n  per-year {args.series}: reported vs equity-curve-derived")
    print(f"  {'year':<6}{'reported':>10}{'derived':>10}{'diff':>9}")
    for r in per_year_comparison(v, args.series):
        note = "  (from first bar)" if r["measured_from_first_bar"] else ""
        print(f"  {r['year']:<6}{r['reported_pct']:>10.2f}{r['derived_pct']:>10.2f}"
              f"{r['diff_pp']:>+9.2f}{note}")
    print()


if __name__ == "__main__":
    main()
