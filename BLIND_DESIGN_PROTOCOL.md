# Blind-Design Protocol — v2 Autonomous Strategy Loop

**Date written**: 2026-05-24
**Status**: ACTIVE
**Branch**: `autoresearch/poc` (parent), `research/blind-design-v2` (private submodule)

This document is the **public methodology commitment** that operationalises
the response to a real public critique (LinkedIn thread; see
`custom_strategies/private/GOLD_STRATEGY_LINKEDIN_THREAD.md` for the
recorded discussion). The core critique:

> Walk-forward inside that window doesn't fix it: train and test both contain
> the crisis the rule was designed to catch. — Dmitrii Shevchenko

This is **spec-level lookahead**. WFA validates parameters within a chosen
rule shape; it cannot validate the rule shape itself if that shape was
designed with the crisis it's meant to catch already visible. Every
v1-shipped strategy was specified with full 2004–2025 history available.

The v2 loop is built on the only mitigation that can answer the critique:
**hold out an era and never query it during research**, then verify the
candidate against the unseen era exactly once.

## The protocol

### 1. The cutoff

**Blind cutoff date**: `2023-01-01`.

All research, iteration, parameter selection, and QA judgment happens on
data with `EntryDate < 2023-01-01`. Data from `2023-01-01` onward is the
**held-out verification era** (≈ 2.5 years of post-design data).

The cutoff was chosen for three reasons:

1. It's the natural boundary after the 2022 dual-bear regime — the
   spec-lookahead concern centres on 2022, which the v1 loop's "TLT/TNX
   panic" rule was designed with visible.
2. It cleanly excludes COVID-recovery dynamics, which have been heavily
   reasoned about in public.
3. It gives ~2.5 years of post-design data — enough for the one-shot
   verification to produce a meaningful sample of trades on a typical
   1-trade-per-day aggregate.

### 2. Enforcement: the guard

The cutoff is enforced **mechanically** by `helpers/blind_design_guard.py`.

- Reads `BLIND_DESIGN_CUTOFF` from `config.py` (default: `None` = disabled).
- When set, wraps every data-loading code path
  (`services/__init__.py::get_data_service`, `helpers/caching.py`) so that
  any returned DataFrame containing timestamps `>= BLIND_DESIGN_CUTOFF`
  raises `BlindDesignViolation`.
- Bypassed only when `BLIND_DESIGN_UNLOCK=True` — used **exactly once**, at
  the end of the round, for the final verification pass.

All v2 research runs **must** set
`BLIND_DESIGN_CUTOFF="2023-01-01"` and `BLIND_DESIGN_UNLOCK=False`.

### 3. What's allowed during research

**Blind-safe inputs** (designed independently of the held-out era):

- Textbook indicators invented decades before the cutoff (RSI, SMA, EMA,
  ATR, Williams %R, MACD, Bollinger Bands, etc.).
- Engine primitives (simulation loop, WFA, MC, regime heatmap, composite
  scorer) — infrastructure, not strategy spec.
- Cross-asset signals from instruments with full pre-cutoff history (HYG,
  GLD, XLE, AGG, IEF, TLT, LQD, VIX, TNX, inverse ETFs SH/PSQ/SDS).
- Long-only and long-inverse-ETF positioning.
- The v1 anti-pattern ledger (as **constraints** that shrink the search
  space, not as parameters fit to data).

### 4. What's forbidden

Anything that would re-introduce spec-level lookahead:

- Re-using a v1 rule shape with new parameters (HYG-trend gating,
  OR-gates, credit-spread gates, VIX-level binary gates, etc. — the full
  v1 KILL ledger in `custom_strategies/private/AUTONOMOUS_LOG.md`).
- Reasoning aloud or in code about specific post-2022 events
  (e.g. "we need a sleeve that handles 2023 banking stress").
- Tuning thresholds to known v1 outcomes (no `hyg_sma_len=50` because v1
  used it; no `tnx_panic_rise=0.08` because v1 used it).
- Querying the held-out era during research (the guard enforces this, but
  PR descriptions and commit messages must also avoid post-cutoff
  references).

### 5. The unlock procedure

Phase 4 of the v2 loop. Triggered when **either**:

- Opus QA declares the blind search exhausted, or
- A v2 candidate passes all R-gates (or composite-gates) on the
  2004-2022 blind window.

Steps:

1. Set `BLIND_DESIGN_UNLOCK=True` in a dedicated config branch.
2. Re-run the candidate(s) over the full 2004 → present window.
3. Compute metrics for the held-out 2023+ window *specifically*.
4. Apply the same R-gate or composite-gate criteria to the held-out
   window alone.
5. PASS or FAIL — **binary, no third option**.
6. Commit the unlock event as a labelled commit:
   `BLIND-UNLOCK: <candidate> on 2023+`.
7. Append the outcome to:
   - `custom_strategies/private/AUTONOMOUS_LOG_V2.md`
   - `custom_strategies/private/GOLD_STRATEGY_LINKEDIN_THREAD.md`
   - this protocol document (under "Outcomes" below)
8. Push both repos.

### 6. The honest-negative commitment

If the unlock fails, **the unlock fails**. The protocol works only if a
negative outcome is documented and accepted. Fitting the held-out era to
turn a fail into a pass would dissolve the protocol's value entirely.

A documented honest negative is more defensible than a fitted positive.

---

## The 4-gate R-criteria (carried over from v1)

The v2 round inherits v1's gate definitions:

- **R1**: BEATS SPY total return over the blind window.
- **R2**: `smooth_verdict ∈ {SMOOTH, ACCEPTABLE}`.
- **R3**: `MaxRcvry < 365 days`.
- **R4**: WFA `Pass` AND `MC ≥ 4`.

Composite co-champion gates (5):

- `MaxRcvry < 365d`, pairwise daily-return `r < 0.40`, `Sharpe ≥ 1.10`,
  `TotalRet ≥ 2× SPY`, regime overlap `< 60%`.

R3 is the gate v1 could not crack (empirical floor: 562d). The v2 round's
working theory is that the engine fix (Phase 2) unlocks inverse-ETF
defensive sleeves as long-only-compatible instruments that may compress
the 2022 dual-bear plateau.

---

## Operational invariants

- v2 research runs **always** set
  `BLIND_DESIGN_CUTOFF="2023-01-01"` and `BLIND_DESIGN_UNLOCK=False`.
- v1 champions are **frozen** as the shipping config; they are the
  control group, never to be modified or retuned.
- Every iteration commits and pushes both repos (parent + private).
- Opus QA gate every ~3 iterations; QA verdicts are authoritative.

---

## Outcomes

| Date | Candidate | Blind result | 2023+ result | Verdict |
|------|-----------|--------------|--------------|---------|
| 2026-05-24 | v1 frozen composite (EC-VIX-27 40% + DefSwitch-030 60%) — used as the documented control after v2 Phase 3 declared search exhausted with 0 candidates | Composite designed with full 2004-present visibility. v1 headline claim: +2,137% TotalRet, +1,312pp vs SPY, MaxRcvry 562d on 2004-06 → 2026-04 | TotalRet +63.02%, SPY +94.81%, composite LAGS SPY by **−31.79pp**. MaxRcvry: **open** drawdown (peak unrecovered). R1+R3 both FAIL on the held-out slice. | **FAIL** |

### What this outcome demonstrates

The blind protocol worked as designed. Two independent findings:

1. **v2 Phase 3 (genuine blind constraints)**: 9 iterations across 4 distinct
   strategy classes (inverse-ETF substitution, constant-weight overlay,
   sparse-signal long-only, 2-sleeve sub-SPY composites) produced **zero**
   standalone R-gate champions. The R3 floor v1 hit empirically (562d
   composite) reappeared at 800-1200d across every direction. That floor is
   therefore a property of the equity market's regime structure under the
   available signal classes, not a v1 artifact.

2. **v2 Phase 4 (unlock)**: The v1 composite, designed with full 2004-present
   data visible, **lags SPY by 31.79pp on the held-out 2023+ window alone**.
   The apparent v1 outperformance was at least partly spec-lookahead
   artifact: the rules that "looked great" on 2004-2026 with all data visible
   do not deliver on the slice that was conceptually held out.

Together: the spec-level lookahead critique from the LinkedIn thread is
**real and material**. The v1 shipping configuration should be
reconsidered before live deployment.

### Why this is a valid scientific outcome

Per HANDOFF_BLIND_DESIGN.md §12:

> Producing a positive result that the operator can't defend in front of the
> next Dmitrii is worse than producing nothing.

This protocol was designed to be falsifiable. It produced an honest negative
on both the v2 search AND the v1 control. That is the deliverable.

### Operator action items

1. Pause any forward-deployment plans for the v1 EC-VIX-27 + iter030
   composite (e.g., signaldeckapi MR !652).
2. Consider re-running the gold-trio strategies (MR !588) on the 2023+
   unlock window using the same methodology to check whether their headline
   claims hold up out-of-sample as well.
3. Future strategy research should follow the blind-design protocol from
   inception (cutoff set BEFORE any backtest is run), not retroactively
   applied to v1 work.

---

## References

- `helpers/blind_design_guard.py` — the guard module
- `tests/test_blind_design_guard.py` — guard test suite (7 tests)
- `config.py` (SECTION 23) — `BLIND_DESIGN_CUTOFF` and
  `BLIND_DESIGN_UNLOCK` config keys
- `HANDOFF_BLIND_DESIGN.md` — protocol design and v2 loop workflow
- `custom_strategies/private/AUTONOMOUS_LOG.md` — v1 history (frozen)
- `custom_strategies/private/AUTONOMOUS_LOG_V2.md` — v2 working log
- `custom_strategies/private/GOLD_STRATEGY_LINKEDIN_THREAD.md` — public
  critique that motivated this round
