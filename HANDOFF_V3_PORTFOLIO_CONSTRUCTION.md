# v3 Autonomous Strategy Loop — Portfolio-Construction Direction

**Date written**: 2026-05-24
**Predecessor rounds**: v1 (41 iters, exhausted), v2 (9 iters + Phase 4 unlock FAIL)
**Branch (parent)**: `autoresearch/poc` (continuing)
**Branch (private)**: `research/blind-design-v3` (new, off `research/blind-design-v2`)

## Why this round exists

v1 declared search exhausted at iter041 with the empirical R3 floor at
562d MaxRcvry. v2 (under the blind-design protocol) declared exhaustion at
iter009 with the R3 floor reappearing at 800-1200d across 4 distinct
strategy classes. The v2 unlock then FAILED — the v1 composite (EC-VIX-27
40% + DefSwitch-030 60%) lags SPY by −31.79pp on the 2023+ held-out
window. Headline +1,312pp was spec-lookahead artifact.

**The structural finding from both rounds**: signal-driven long-only
strategies that respond to drawdowns share calendar windows (GFC, 2022),
so they share the same R3 floor. This is a property of the market, not a
strategy defect.

**The unexplored class**: PORTFOLIO CONSTRUCTION. v1/v2 asked "when to be
in the market." v3 asks "how to weight what's in the market." Continuous
inverse-vol allocation, equal-risk-contribution, Markowitz mean-variance,
Bridgewater All-Weather, etc. These don't *decide* to be in/out — they
allocate dollars by some risk metric. Different mechanism, potentially
different structural floor.

## Blind-design protocol carries over

- `BLIND_DESIGN_CUTOFF="2023-01-01"`, `BLIND_DESIGN_UNLOCK=False` for all
  v3 research runs.
- `helpers/blind_design_guard.py` enforces at the data-loading layer.
- `helpers/blind_design_guard.trim_to_cutoff(df)` for cross-asset reads
  inside strategies.
- The held-out 2023+ era is unlocked exactly once at the end of v3 (or
  not at all, if v3 also produces no candidates).

## Forbidden categories (carryover from v1 + v2 KILL ledgers)

Same 10 v1 entries plus the v2 KILLs:

v1: shorts, OR-gates, bond duration swap inside iter030 shape, gold/miner
3rd sleeves, energy 3rd sleeves, VIX-level binary gates, credit-spread
gates, >3-sleeve composites, window extensions, EC-family weight
optimization.

v2: inverse-ETF standalone trend-follow, SPY/SH switch at any SMA,
SPY/SH SMA200 (Faber gate with SH), constant-weight inverse-ETF overlay,
sparse-signal long-only (Antonacci, vol-gate, SPY/GLD), 2-sleeve sub-SPY
composites.

## v3 candidate iters (initial queue — Opus QA will refine after iter003)

### iter001 — Equal-risk-contribution across SPY, IEF, GLD

3-asset portfolio with weights inversely proportional to 60-day realized
volatility, rebalanced monthly. Always-allocated (no gates). Tests pure
portfolio-construction without signal switching. **First in queue.**

### iter002 — Markowitz mean-variance on SPY/IEF/GLD

Same 3-asset universe, weights chosen monthly to maximize Sharpe given
60-day rolling estimates of returns and covariance. Bounded weights
[0, 0.6] per asset. Classical Markowitz 1952 framework.

### iter003 — Bridgewater All-Weather inspired (4-asset, fixed risk parity)

SPY 30% + IEF 40% + GLD 7.5% + Commodity-proxy DBC 7.5% + TIPS 15%
(approximate Bridgewater weights). No timing — pure static rebalance
monthly. Tests whether the canonical All-Weather framework cracks R3.

### iter004 — Volatility-targeted long-only SSO (2× SPY)

If standalone return is the problem (v2 found sleeves bounded below SPY),
test a SUPER-SPY base: SSO at vol-targeted exposure. Position size scaled
to target 15% annualized portfolio vol. SSO daily-rebalance decay is a
known headwind; vol-target may dominate it. Different from v1 iter004
(TQQQ macro-gated) which was binary trend gate + 3× decay.

### iter005 — Multi-asset momentum rotation top-N

Pick the top-2 of {SPY, QQQ, IEF, GLD, DBC, IWM} by 12-month return each
month; hold 50/50. Generalises Antonacci to N>2. Different shape from
v1 iter020 (which was top-1) and v2 iter005/009 (which were 2-leg).

### iter006 — Empirical PCA factor-mimicking

Compute first 2 principal components on {SPY, IEF, GLD, DBC} returns;
allocate to the eigenvectors. Untested in v1/v2; pre-1990s technique.

## Workflow contract (same as v2)

| Term | Value |
|------|-------|
| Session unit | ≈ 3 iters/session |
| Total budget | up to 15 iters across ~5 sessions (smaller than v2 since v3 has a narrower thesis) |
| Stop condition | (a) Opus QA declares the BLIND search exhausted in v3, OR (b) a v3 candidate passes all 4 R-gates on the 2004-2022 BLIND window |
| Commit cadence | Commit + push after every iteration. Both repos. |
| Knowledge file | `custom_strategies/private/AUTONOMOUS_LOG_V3.md` (new) |
| Model assignment | Opus = QA + judgment; Sonnet = strategy code; Haiku = trivial tooling |

## Champions DO NOT MODIFY

Same as v2: v1 frozen composite (EC27+iter030+gold trio) remains frozen.
After the v2 unlock FAIL, the operator is reconsidering forward-deployment
of all v1 strategies. v3 is independent research, not a fix for v1.

## Phase 4 of v3

If a v3 candidate passes the blind R-gates, execute the standard unlock
procedure (HANDOFF_BLIND_DESIGN.md §7.2) on the v3 candidate.

If v3 declares exhaustion with 0 candidates: skip unlock and document. The
v2 round already established that the v1 composite FAILS on 2023+; no
further unlock on prior champions is informative.

## Quick-start prompt for resumption

> Resume the v3 autonomous strategy loop from `HANDOFF_V3_PORTFOLIO_CONSTRUCTION.md`.
> Read v1+v2 KILL ledgers + the v2 unlock verdict before iterating. Operator
> not present. Use Opus QA every ~3 iters. Stop on Phase 4 completion or
> Section 8 halt. RTK prefix on every command.
