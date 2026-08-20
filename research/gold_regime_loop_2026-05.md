# Gold regime-loop strategy research (May 2026) — research record

**Status:** RESEARCH ARCHIVE. Code lives on branch `research/gold-regime-loop` (this repo, unmerged; last commit
2026-05-19). The round-by-round narrative + tearsheet PDFs live in the `custom_strategies/private` submodule
(`research_context`) that the branch's repeated "bump submodule pointer" commits track.

## What it was
An autonomous, multi-session strategy-iteration loop searching for a gold-regime long/rotation configuration,
run across **NDX / DJI / SPY+GLD / Sectors** universes (`tickers_to_scan/gold_{ndx,dji,spy,sectors}.json`) with a
verdict checker (`scripts/check_gold_verdict.py`).

## Arc / findings (reconstructed from the branch history)
- **~26+ iteration rounds** across the four universes.
- Two **gate-passing candidates** found (allocation 0.09 and 0.10).
- **R21 locked as the "champion"** configuration after the round sweep; a robustness check was completed.
- **Kill-switch overlay** added (`helpers/kill_switch.py`, `scripts/apply_kill_switch.py`) + tests.
- **Defensive sleeve** setup; **extended history wired back to 1990** (Yahoo→parquet) to span ≥1 bear market.
- Final direction flagged: a **Kalman-β Gold** research candidate (the branch's last commit).

## Status / how to resolve
⚠️ The `research/gold-regime-loop` branch is **~3 months behind `main`** and is **not merge-ready** — a direct
merge would revert newer engine work. To productionize: cherry-pick the gold universes + kill-switch +
`check_gold_verdict` onto a fresh branch off current `main`, re-run R21 / the Kalman-β candidate on the current
engine, and open a clean feature PR. This doc + PR formalize the research record so it isn't lost on an orphaned
branch.

## Relationship to the real-yield backtest (distinct effort)
The **real-yield** gold backtest (Aug 2026, `research/gold-realyield-backtest-spec.md`) tested a *different*
hypothesis — a real-yield-conditioned breakout — and was **rejected as regime-broken** (edge died 2022). The
regime-loop work recorded here is a momentum/rotation search, not a real-yield model. Keep the two separate.
