# 4H Research — Round 6
**Date:** 2026-04-11
**Run ID:** 4h-r6-williams-r_2026-04-11_14-25-53
**Universe:** Liquid 4H (20) — Polygon
**Period:** 2018-01-02 → 2026-04-10 (WFA split: 2024-08-07)

## Research Question
Can Williams %R Dip-Recovery (4H) earn a 4th champion spot?
Weekly Williams R was champion (R47); at 4H, 14 bars = 8.6 days (very different).

## Results

| Strategy | P&L | OOS | WFA | RollWFA | Calmar | SQN | Trades |
|---|---|---|---|---|---|---|---|
| EMA Velocity Breakout (4H) | +175.85% | +48.68% | Pass | Pass (3/3) | 0.66 | 4.21 | 1019 |
| Keltner Channel Breakout (4H) | +128.76% | +33.01% | Pass | Pass (3/3) | 0.65 | 4.25 | 2043 |
| Donchian Turtle (4H) | +110.37% | +25.93% | Pass | Pass (3/3) | 0.58 | 3.98 | 2124 |
| Williams %R Dip-Recovery (4H) | +3.18% | -5.60% | **Overfitted** | **Fail (1/3)** | 0.03 | 0.39 | 1238 |

## Key Findings

1. **Williams %R REJECTED** — Likely Overfitted, OOS -5.60%, RollWFA Fail (1/3).
   PF 1.03 (barely profitable), SQN 0.39 (catastrophic).

2. **Structural finding — mean-reversion fails at 4H consistently:**
   - RSI Dip Buy (R1): WFA Overfitted, OOS -2.51%
   - Williams %R Dip-Recovery (R6): WFA Overfitted, OOS -5.60%
   - Both RSI and Williams %R measure the same thing (oversold bounce) through
     different lenses; both fail at 4H because:
     * At 4H, "oversold" conditions last only 1-3 bars; recovery can take 10-50 bars
     * The IS period (2018-2024) had a strong bull run where dips always recovered —
       but OOS (2024-2026) had choppier markets where dip-recovery patterns break down
     * The dip-recovery stateful logic is path-dependent — easy to overfit to the
       specific sequences of RSI/WR dips in the IS period

3. **CONFIRMED: trend-following only for 4H Liquid universe.**
   All successful strategies (EMA, Keltner, Donchian) follow the same structural
   pattern: enter when trend is confirmed, ride it, exit when trend weakens.
   Mean-reversion requires a different type of universe or timeframe.

## Decision for Round 7
- KEEP: EMA, Keltner, Donchian Turtle — confirmed trio
- REJECT: MACD Histogram (R5), Williams %R (R6) — mean-reversion/noisy
- TRY: Relative Strength Momentum (4H) [needs SPY dependency]
  - Measures symbol's 20d return MINUS SPY's 20d return at 4H resolution
  - Entry: outperform SPY by >1% over 20d AND price > SMA(200d)
  - Different from EMA (measures price vs own EMAs) and Keltner (price vs ATR channel)
  - Relative momentum at daily/weekly was tested (R42 portfolio), but at 4H
    the 20-bar window = 20 trading days = same calendar days but 33 4H updates
    instead of 20 daily updates → more responsive signal
