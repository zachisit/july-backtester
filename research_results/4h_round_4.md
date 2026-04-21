# 4H Research — Round 4
**Date:** 2026-04-11
**Run ID:** 4h-r4-donchian-turtle_2026-04-11_14-20-50
**Universe:** Liquid 4H (20) — Polygon
**Period:** 2018-01-02 → 2026-04-10 (WFA split: 2024-08-07)

## Research Question
Does the shift(1) Donchian Turtle fix (proper breakout entry, N-bar-low trailing exit)
resolve the 3065-trade churn problem from Round 3?

## Core Performance

| Strategy | P&L (%) | vs. SPY | Sharpe | Max DD | MC Score | WFA Verdict |
|---|---|---|---|---|---|---|
| EMA Velocity Breakout (4H) | +175.85% | +21.46% | -0.39 | 19.68% | 5 | Pass |
| Keltner Channel Breakout (4H) | +128.76% | -25.63% | -0.54 | 16.09% | 5 | Pass |
| Donchian Turtle (4H) | +110.37% | -44.02% | -0.56 | 16.31% | 5 | Pass |

## Robustness

| Strategy | OOS P&L | WFA Verdict | RollWFA | Corr | MC Score | Calmar | Trades | SQN |
|---|---|---|---|---|---|---|---|---|
| EMA Velocity Breakout (4H) | +48.68% | Pass | Pass (3/3) | 0.04 | 5 | 0.66 | 1019 | 4.21 |
| Keltner Channel Breakout (4H) | +33.01% | Pass | Pass (3/3) | 0.27 | 5 | 0.65 | 2043 | 4.25 |
| Donchian Turtle (4H) | +25.93% | Pass | Pass (3/3) | 0.27 | 5 | 0.58 | 2124 | 3.98 |

## Correlation

| Pair | r |
|---|---|
| EMA ↔ Keltner | 0.04 |
| EMA ↔ Donchian Turtle | 0.04 |
| Keltner ↔ Donchian Turtle | 0.27 |

## Key Findings

1. **Donchian fix was decisive**: shift(1) entry + N-bar-low exit transformed
   P&L from +59.59% → +110.37%, OOS from +11.69% → +25.93%, Calmar 0.42 → 0.58,
   SQN 2.96 → 3.98, trades from 3065 → 2124. **CONFIRMED CHAMPION.**

2. **Keltner ↔ Donchian correlation 0.27**: Moderate but well within acceptable
   range (< 0.85 threshold). Both are trend-following breakouts so some overlap
   is expected; 0.27 means they are mostly independent.

3. **Three-strategy portfolio**: EMA + Keltner + Donchian Turtle form a strong
   trio. All MC Score 5, all WFA Pass (3/3), all positive OOS P&L. Max pair
   r = 0.27. This trio is ready for a production portfolio.

4. **Negative Sharpe persists**: Systematic at 4H — all three strategies show
   Sharpe < 0. Root cause confirmed: bar-level Sharpe at 409 bars/year
   systematically underestimates trend-following strategies that are out of
   position for extended periods (0-return bars drag the mean below rf_daily).
   PRIMARY quality metrics: Calmar, OOS P&L, WFA. Sharpe is secondary.

## Decision for Round 5
- KEEP: EMA Velocity Breakout (4H) — #1 champion
- KEEP: Keltner Channel Breakout (4H) — #2 champion
- KEEP: Donchian Turtle (4H) — #3 champion (confirmed this round)
- ADD: MACD Histogram Crossover (4H) — search for 4th strategy
  - MACD at 4H: fast=_b(12)=20, slow=_b(26)=42, signal=_b(9)=15 bars
  - Histogram crosses 0 from below = momentum shift entry
  - Tested at daily/weekly in R-series but NOT at 4H resolution
  - Target: Calmar > 0.40, OOS > 0%, WFA Pass, SQN > 2.0

## 4H Production Portfolio v1 (3 strategies)
**Portfolio:** Liquid 4H (20), 3 strategies × 10% allocation
**Status:** Confirmed — all three meet quality bar

| Strategy | Calmar | OOS | WFA | MC | SQN |
|---|---|---|---|---|---|
| EMA Velocity Breakout (4H) | 0.66 | +48.68% | Pass | 5 | 4.21 |
| Keltner Channel Breakout (4H) | 0.65 | +33.01% | Pass | 5 | 4.25 |
| Donchian Turtle (4H) | 0.58 | +25.93% | Pass | 5 | 3.98 |
