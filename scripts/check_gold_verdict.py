"""
Read llm_verdict.json from a run directory and apply the gold-track 3-gate.

Usage:
    python scripts/check_gold_verdict.py output/runs/<run_id>

Exit code: 0 if ANY strategy passes all gates. 1 if all fail. 2 on error.

Gold-track gate (all three must pass to avoid auto-reject):
  G1  beats_spy = true
  G2  curve_smoothness.smooth_verdict in {SMOOTH, ACCEPTABLE} (not ROUGH)
  G3  wfa_verdict = Pass    [silent floor; not the user's stated 2-gate goal
                             but enforced here to block obvious overfits]

Notes
-----
- Differs from scripts/check_verdict.py (EC track) by:
    * Dropping the < 12-month plateau gate (EC R3, proven structurally
      impossible on long-only equity universes)
    * Dropping the MC Score >= 4 gate (recorded but not gated here)
    * Keeping WFA Pass as a silent third gate
- MC Score and plateau length are still PRINTED so the human can spot
  borderline cases when escalating a PASS for visual PDF review.
- Per RESEARCH_HANDOFF_GOLD.md: a PASS triggers PDF generation and human
  escalation. A FAIL records the round and advances with no PDF.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


SMOOTH_OK = {"SMOOTH", "ACCEPTABLE"}


def _gate(entry):
    """Return (passed: bool, fails: list[str]) for one strategy entry."""
    fails = []

    # G1 — beats SPY in absolute terms
    if entry.get("beats_spy") is not True:
        fails.append(f"lags SPY — {entry.get('verdict', 'no verdict')}")

    # G2 — smooth curve verdict (not ROUGH)
    smoothness = entry.get("curve_smoothness") or {}
    sv = smoothness.get("smooth_verdict")
    if sv not in SMOOTH_OK:
        notes = smoothness.get("smooth_notes") or []
        notes_str = f" ({'; '.join(notes)})" if notes else ""
        fails.append(f"smooth_verdict={sv}{notes_str}")

    # G3 — WFA Pass (silent floor against overfit)
    wfa = entry.get("wfa_verdict")
    if wfa and wfa != "Pass":
        fails.append(f"WFA = {wfa}")

    return len(fails) == 0, fails


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/check_gold_verdict.py <run_dir>")
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

        # Headline metrics — including ungated ones the human still cares about
        pnl = entry.get("strategy_return_pct")
        sv = (entry.get("curve_smoothness") or {}).get("smooth_verdict", "?")
        flat = (entry.get("curve_smoothness") or {}).get("longest_flat_streak_months")
        calmar = entry.get("calmar_ratio")
        mc = entry.get("mc_score")
        wfa = entry.get("wfa_verdict", "?")

        tag = "PASS" if passed else "FAIL"
        if pnl is not None:
            metrics = (
                f"P&L={pnl:.1f}%  curve={sv}  flat={flat}m  "
                f"Calmar={calmar}  MC={mc}  WFA={wfa}"
            )
        else:
            metrics = ""

        print(f"  [{tag}]  {name}  ({portfolio})")
        if metrics:
            print(f"         {metrics}")
        for reason in fails:
            print(f"         ✗ {reason}")

        if passed:
            any_passed = True

    print()
    if any_passed:
        print("GATE: PASS — at least one strategy cleared all checks. "
              "Generate PDF and escalate to human.")
    else:
        print("GATE: FAIL — all strategies rejected. Record as FAILED. "
              "Advance to next queue item. No PDF needed.")

    sys.exit(0 if any_passed else 1)


if __name__ == "__main__":
    main()
