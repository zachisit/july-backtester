# 4H Research — Round 8
**Date:** 2026-04-11
**Run ID:** 4h-r8-rs-momentum-sweep_2026-04-11_16-17-47
**Universe:** Liquid 4H (20) — Polygon
**Period:** 2018-01-01 → 2026-04-11 (WFA split: 2024-08-07)

## Research Question
Rule 6 (ANTI-OVERFITTING GUARD): Parameter sensitivity sweep on Relative Strength Momentum (4H)
before it can be considered a confirmed champion. Are its 4 parameters (rs_period, abs_period,
rs_threshold, sma_trend) robust, or was the base config cherry-picked from parameter space?

## Sweep Configuration

| Parameter | Values Swept (5 each) |
|---|---|
| rs_period | 19, 26, **33** (base), 38, 45 |
| abs_period | 10, 13, **16** (base), 19, 22 |
| rs_threshold | 0.006, 0.008, **0.010** (base), 0.012, 0.014 |
| sma_trend | 195, 260, **325** (base), 390, 455 |

**Total variants:** 5⁴ = 625
**Sweep range:** ±20% per step, 2 steps each direction
**min_val:** 0.001 (critical — allows rs_threshold to sweep below 2.0 threshold)

## Sensitivity Results: ROBUST

| Metric | Count | Pct |
|---|---|---|
| Profitable variants | 625 / 625 | **100%** |
| WFA Pass | 625 / 625 | **100%** |
| Rolling WFA Pass (3/3) | 625 / 625 | **100%** |
| MC Score 5 | 625 / 625 | **100%** |

## Metric Ranges Across All 625 Variants

| Metric | Min | Max | Base |
|---|---|---|---|
| P&L (%) | +65.53% | +266.58% | +176.84% |
| Calmar | 0.310 | 1.240 | 0.82 |
| OOS P&L (%) | +14.84% | +83.41% | +49.11% |
| Trades | 1,696 | 3,949 | 2,332 |

## Anti-Cherry-Pick Evidence

Base config P&L rank: **304 / 625** (50th percentile — median, NOT at maximum).

The highest P&L variants use longer rs_period (45) with tighter sma_trend (195–260). The base
parameters are centered in the distribution. This confirms the base was not hand-tuned to the
maximum — it is a genuinely representative choice.

## Worst Variants

Even the worst performers are strong:

| Strategy | P&L | Calmar | OOS P&L |
|---|---|---|---|
| rs_period=19, abs_period=19, rs_threshold=0.008, sma_trend=455 | +65.53% | 0.32 | +17.22% |
| rs_period=19, rs_threshold=0.006, sma_trend=455 | +65.91% | 0.32 | +18.99% |
| rs_period=19, abs_period=19, rs_threshold=0.006, sma_trend=455 | +66.04% | 0.32 | +17.96% |

Pattern: worst combinations always involve shortest rs_period (19) + largest sma_trend (455) —
a logically weak combo (fast momentum signal, slow trend filter that blocks many entries).
Even these earn 65%+ P&L and pass WFA.

## Best Variants

| Strategy | P&L | Calmar | OOS P&L |
|---|---|---|---|
| rs_period=45, sma_trend=195 | +266.58% | 1.20 | +78.90% |
| rs_period=45, rs_threshold=0.008, sma_trend=195 | +263.58% | 1.17 | +73.16% |
| rs_period=45, sma_trend=260 | +262.15% | 1.21 | +80.59% |

Pattern: longer rs_period (45) + tighter sma_trend (195–260) tends to produce higher P&L.
These are valid parameter choices but are NOT used as the production config (we use the base).

## Key Findings

1. **RS Momentum is EXTREMELY ROBUST**: 100%/100%/100% across all sweep metrics. This exceeds
   any previously tested strategy in the research program (Williams R was 81/81 at 100% — this
   is 625/625).

2. **No floor risk**: The minimum Calmar across all 625 variants is 0.310. Even the worst
   parameter combo achieves a reasonable risk-adjusted return.

3. **All OOS positive**: Every single variant passes WFA with positive OOS P&L (minimum +14.84%).
   The strategy generalizes to unseen data across the full parameter space.

4. **Critical fix applied**: `sensitivity_sweep_min_val=0.001` was required because
   `rs_threshold=0.010` is a small positive float — the default min_val=2 would have clipped all
   sweep values to 2.0, producing 0 trades for non-base variants (same bug class as Williams R
   negative thresholds in Round 36).

5. **RS Momentum confirmed champion — Rule 6 SATISFIED**: The sweep was the only remaining
   gate before full confirmation. The strategy now passes all 7 anti-overfitting rules.

## 4H Production Portfolio v1 — FINAL (4 strategies, all rules satisfied)

| Rank | Strategy | Calmar | OOS P&L | WFA | MC | MaxDD | Sweep |
|---|---|---|---|---|---|---|---|
| 1 | Relative Strength Momentum (4H) | 0.82 | +49.11% | Pass (3/3) | 5 | 15.94% | ROBUST (625/625) |
| 2 | EMA Velocity Breakout (4H) | 0.66 | +48.68% | Pass (3/3) | 5 | 19.68% | ROBUST (Round 3) |
| 3 | Keltner Channel Breakout (4H) | 0.65 | +33.01% | Pass (3/3) | 5 | 16.09% | ROBUST (Round 3) |
| 4 | Donchian Turtle (4H) | 0.58 | +25.93% | Pass (3/3) | 5 | 16.31% | ROBUST (Round 3) |

**Status: PRODUCTION READY — all 4 strategies satisfy all 7 anti-overfitting rules.**

## Stop Criteria Assessment

Per Stop Criteria C: "4H portfolio is complete when 4+ uncorrelated champion strategies are
confirmed with all 7 rules satisfied." All 4 strategies now satisfy all rules. The 4H research
program can be declared COMPLETE.

- Max pairwise correlation: 0.22 (well below 0.85 threshold) ✓
- All: MC Score 5 ✓
- All: WFA Pass (3/3) ✓
- All: OOS P&L ≥ +25% ✓
- All: Calmar ≥ 0.50 ✓ (RS: 0.82, EMA: 0.66, Keltner: 0.65, Donchian: 0.58)
- All: Sensitivity sweep ROBUST ✓

## Rejected Strategies (4H, cumulative)

| Round | Strategy | Reason |
|---|---|---|
| R1 | ADX Trend Strength Entry | 127 trades, Sharpe -4.80, over-filtered |
| R1 | RSI Dip Buy | WFA Overfitted, OOS -2.51% |
| R3 | Donchian Channel Momentum | 3065 trades (shift(1) bug), PF 1.19 |
| R5 | MACD Histogram Crossover | Calmar 0.26, PF 1.16, 2602 trades |
| R6 | Williams %R Dip-Recovery | WFA Overfitted, OOS -5.60%, RollWFA Fail (1/3) |
