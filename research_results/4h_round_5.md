# 4H Research — Round 5
**Date:** 2026-04-11
**Run ID:** 4h-r5-macd-hist_2026-04-11_14-23-44
**Universe:** Liquid 4H (20) — Polygon
**Period:** 2018-01-02 → 2026-04-10 (WFA split: 2024-08-07)

## Research Question
Can MACD Histogram Crossover (4H) earn a 4th champion spot alongside the
EMA/Keltner/Donchian trio?

## Core Performance

| Strategy | P&L (%) | vs. SPY | Sharpe | Max DD | MC Score | WFA Verdict |
|---|---|---|---|---|---|---|
| EMA Velocity Breakout (4H) | +175.85% | +21.46% | -0.39 | 19.68% | 5 | Pass |
| Keltner Channel Breakout (4H) | +128.76% | -25.63% | -0.54 | 16.09% | 5 | Pass |
| Donchian Turtle (4H) | +110.37% | -44.02% | -0.56 | 16.31% | 5 | Pass |
| MACD Histogram Crossover (4H) | +46.80% | -107.59% | -0.87 | 18.53% | 5 | Pass |

## Robustness

| Strategy | OOS P&L | WFA | RollWFA | MC | Calmar | Trades | SQN |
|---|---|---|---|---|---|---|---|
| EMA Velocity Breakout (4H) | +48.68% | Pass | Pass (3/3) | 5 | 0.66 | 1019 | 4.21 |
| Keltner Channel Breakout (4H) | +33.01% | Pass | Pass (3/3) | 5 | 0.65 | 2043 | 4.25 |
| Donchian Turtle (4H) | +25.93% | Pass | Pass (3/3) | 5 | 0.58 | 2124 | 3.98 |
| MACD Histogram Crossover (4H) | +17.89% | Pass | Pass (3/3) | 5 | 0.26 | 2602 | 2.45 |

## Key Findings

1. **MACD Histogram (4H) fails the quality bar**: All formal robustness checks
   pass (WFA Pass 3/3, OOS +17.89%, MC Score 5) but fundamentally weak:
   Calmar 0.26 (threshold: >0.40), PF 1.16, SQN 2.45 (below trio's 3.98-4.25).
   2602 trades (one every ~2 weeks/symbol) → signal too noisy at 4H resolution.

2. **Root cause**: MACD histogram crosses 0 very frequently at 4H due to fast
   EMA spread oscillation around 0. Even with _b(12/26/9) scaling, the 4H MACD
   flickers above/below zero in choppy regimes, generating entries on noise.
   This is fundamentally harder to fix than the Donchian shift(1) bug — it's
   structural to MACD at sub-daily resolution.

3. **MACD REJECTED** — not promoted to champion.

## Decision for Round 6
- KEEP: EMA, Keltner, Donchian Turtle — confirmed trio
- TRY: Williams %R Dip-Recovery (4H)
  - Weekly Williams R was champion (R47, MC Score 5, WFA Pass, SQN high)
  - At 4H: Williams %R(14) spans ~8.6 trading days — measures oversold bounce
    within the LAST 8.6 DAYS of price range, not the last 14 WEEKS
  - Structurally different from RSI Dip (R1 failure): Williams %R uses actual
    price range (HH-LL normalization), not returns-based oscillator
  - Entry: %R dips below -80 (genuine oversold) then crosses above -50
    AND price > SMA(200d) AND price > EMA(50d) — stateful two-step entry
  - Expected: low-to-moderate trade count, high-conviction oversold bounces
