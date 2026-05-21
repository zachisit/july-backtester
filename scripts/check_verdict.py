"""
Read llm_verdict.json from a run directory and apply the EC candidate gate.

Usage:
    python scripts/check_verdict.py output/runs/<run_id>

Exit code: 0 if ANY strategy passes all gates. 1 if all fail. 2 on error.

Gate rules (all must pass to avoid auto-reject):
  - beats_spy = true
  - curve_smoothness.smooth_verdict = SMOOTH or ACCEPTABLE (not ROUGH)
  - curve_smoothness.longest_flat_streak_months < 12
  - wfa_verdict = Pass
  - mc_score >= 4
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _gate(entry):
    """Return (passed: bool, fails: list[str]) for one strategy entry."""
    fails = []

    if entry.get("beats_spy") is not True:
        fails.append(f"lags SPY — {entry.get('verdict', 'no verdict')}")

    smoothness = entry.get("curve_smoothness") or {}
    sv = smoothness.get("smooth_verdict")
    if sv == "ROUGH":
        notes = smoothness.get("smooth_notes") or []
        fails.append(f"ROUGH curve ({'; '.join(notes)})")

    flat = smoothness.get("longest_flat_streak_months", 0) or 0
    if flat >= 12:
        fails.append(f"plateau {flat} months >= 12-month limit")

    wfa = entry.get("wfa_verdict")
    if wfa and wfa != "Pass":
        fails.append(f"WFA = {wfa}")

    mc = entry.get("mc_score")
    if mc is not None and mc < 4:
        fails.append(f"MC score {mc} < 4")

    return len(fails) == 0, fails


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/check_verdict.py <run_dir>")
        sys.exit(2)

    run_dir = sys.argv[1]
    verdict_path = os.path.join(run_dir, "llm_verdict.json")

    if not os.path.exists(verdict_path):
        print(f"ERROR: {verdict_path} not found — did the run complete?")
        sys.exit(2)

    with open(verdict_path, encoding="utf-8") as fh:
        data = json.load(fh)

    strategies = data.get("strategies", [])
    if not strategies:
        print("No strategies with trades in verdict — treating as FAIL.")
        sys.exit(1)

    summary = data.get("summary", {})
    beats_count = summary.get("beats_spy_count", 0)
    total = summary.get("total_strategies_with_trades", len(strategies))
    print(f"\nRun: {data.get('run_id', run_dir)}")
    print(f"Period: {data.get('period', {}).get('start')} → {data.get('period', {}).get('end')}")
    print(f"SPY B&H: {list(data.get('benchmarks', {}).values())[0] if data.get('benchmarks') else '?'}%")
    print(f"Beats SPY: {beats_count}/{total}\n")

    any_passed = False
    for entry in strategies:
        name = entry.get("strategy", "?")
        portfolio = entry.get("portfolio", "?")
        passed, fails = _gate(entry)
        pnl = entry.get("strategy_return_pct")
        sv = (entry.get("curve_smoothness") or {}).get("smooth_verdict", "?")
        calmar = entry.get("calmar_ratio")
        mc = entry.get("mc_score")
        wfa = entry.get("wfa_verdict", "?")

        tag = "PASS" if passed else "FAIL"
        metrics = f"P&L={pnl:.1f}%  curve={sv}  Calmar={calmar}  MC={mc}  WFA={wfa}" if pnl is not None else ""
        print(f"  [{tag}]  {name}  ({portfolio})")
        if metrics:
            print(f"         {metrics}")
        for reason in fails:
            print(f"         ✗ {reason}")

        if passed:
            any_passed = True

    print()
    if any_passed:
        print("GATE: PASS — at least one strategy cleared all checks. Generate PDF and escalate to human.")
    else:
        print("GATE: FAIL — all strategies rejected. Record as FAILED. Advance to next queue item. No PDF needed.")

    sys.exit(0 if any_passed else 1)


if __name__ == "__main__":
    main()
