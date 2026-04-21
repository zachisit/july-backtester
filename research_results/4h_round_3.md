# 4H Research — Round 3
**Date:** 2026-04-11
**Run ID:** 4h-r3-donchian_2026-04-11_14-18-26
**Universe:** Liquid 4H (20) — Polygon
**Period:** 2018-01-02 → 2026-04-10 (WFA split: 2024-08-07)

## Research Question
Can Donchian Channel Momentum (4H) replace Volume Surge as the third champion
alongside EMA Velocity Breakout and Keltner Channel Breakout?

## Core Performance

| Strategy | P&L (%) | vs. SPY | Sharpe | Max DD | MC Score | WFA Verdict |
|---|---|---|---|---|---|---|
| EMA Velocity Breakout (4H) | +175.85% | +21.46% | -0.39 | 19.68% | 5 | Pass |
| Keltner Channel Breakout (4H) | +128.76% | -25.63% | -0.54 | 16.09% | 5 | Pass |
| Donchian Channel Momentum (4H) | +59.59% | -94.80% | -0.83 | 13.98% | 5 | Pass |

## Robustness

| Strategy | OOS P&L | WFA Verdict | RollWFA | MC Score | Calmar | Trades | SQN |
|---|---|---|---|---|---|---|---|
| EMA Velocity Breakout (4H) | +48.68% | Pass | Pass (3/3) | 5 | 0.66 | 1019 | 4.21 |
| Keltner Channel Breakout (4H) | +33.01% | Pass | Pass (3/3) | 5 | 0.65 | 2043 | 4.25 |
| Donchian Channel Momentum (4H) | +11.69% | Pass | Pass (3/3) | 5 | 0.42 | 3065 | 2.96 |

## Correlation

| Pair | r |
|---|---|
| EMA ↔ Keltner | 0.05 |
| EMA ↔ Donchian | 0.11 |
| Keltner ↔ Donchian | 0.10 |

## Key Findings

1. **Donchian passes all robustness checks** (OOS +11.69%, WFA Pass 3/3, MC Score 5)
   but fundamentals are weak: Calmar 0.42, PF 1.19, SQN 2.96, 3065 trades.

2. **Root cause identified**: `Close >= rolling_max(Close, window)` fires on EVERY bar
   during an uptrend (price always equals the rolling max while trending). The state
   machine's `in_pos` guard prevents re-entry, but the (high+low)/2 midline exit is
   too close to price in trending conditions, causing rapid churn:
   enter → quick midline exit → new high → re-enter → repeat.

3. **Fix for Round 4**: Proper Turtle-style Donchian:
   - Entry: `Close > max(Close.shift(1) over previous 20 bars)` — fires ONLY on a
     genuine break above prior N-bar resistance, not on continuation
   - Exit: `Close < min(Close.shift(1) over previous 10 bars)` — trailing N-bar-low
     stop, wider and more natural than the midline

## Decision for Round 4
- KEEP: EMA Velocity Breakout (4H) — confirmed champion (R1)
- KEEP: Keltner Channel Breakout (4H) — confirmed champion (R2)
- REPLACE: Donchian Channel Momentum → "Donchian Turtle (4H)"
  - Redesigned with shift(1) entry and N-bar-low exit
  - Expected: far fewer trades, better PF, cleaner OOS behavior
