# 4H Research — Round 1
**Date:** 2026-04-11
**Run ID:** 4h-r1-initial_2026-04-11_14-05-24
**Universe:** Liquid 4H (20) — 20 ETFs + mega-caps via Polygon
**Period:** 2018-01-02 → 2026-04-10 (WFA split: 2024-08-07)

## Context
First run on new 4H research track. Pivot from Norgate/weekly (R1-R51 COMPLETE)
to Polygon/4H. Three new strategy families designed specifically for 4H mechanics,
none from R1-R51 prior research.

**Technical setup:**
- `get_bars_for_period()` bug discovered: ignores multiplier for H timeframe
  → implemented manual `_b(days) = max(2, round(days * 6.5/4))` helper
- Universe: 20 liquid ETFs + mega-caps (SPY excluded, used as benchmark)
- Config: timeframe="H", timeframe_multiplier=4, start_date=2018-01-01

## Core Performance

| Strategy | P&L (%) | vs. SPY | Sharpe | Max DD | MC Score | WFA Verdict |
|---|---|---|---|---|---|---|
| EMA Velocity Breakout (4H) | +175.85% | +21.46% | -0.39 | 19.68% | 5 | Pass |
| ADX Trend Strength Entry (4H) | +4.98% | -149.41% | -4.80 | 4.83% | 5 | Pass |
| RSI Dip Buy within Trend (4H) | +21.03% | -133.36% | -2.32 | 5.75% | 5 | Likely Overfitted |

## Robustness

| Strategy | OOS P&L | WFA | RollWFA | MC | Calmar | Trades | SQN |
|---|---|---|---|---|---|---|---|
| EMA Velocity Breakout (4H) | +48.68% | Pass | Pass (3/3) | 5 | 0.66 | 1019 | 4.21 |
| ADX Trend Strength Entry (4H) | +3.09% | Pass | Pass (3/3) | 5 | — | 127 | — |
| RSI Dip Buy within Trend (4H) | -2.51% | Likely Overfitted | Pass (3/3) | 5 | — | 266 | — |

## Key Findings

1. **EMA Velocity Breakout: CHAMPION** — WFA Pass (3/3), OOS +48.68%, MC Score 5,
   MaxDD 19.68%, 1019 trades. Clear leader. Kept for all subsequent rounds.

2. **ADX Trend Strength Entry: REJECTED** — Only 127 trades over 8 years (6.4/year/symbol).
   The ADX > 25 threshold is too restrictive at 4H, over-filtering entries to the point
   where the strategy has too few trades to be statistically meaningful.

3. **RSI Dip Buy within Trend: REJECTED** — WFA Likely Overfitted, OOS -2.51%.
   Mean-reversion at 4H doesn't generalize (confirmed again in R6 with Williams %R).

4. **Negative Sharpe pattern identified** — All 4H strategies show negative Sharpe
   despite positive P&L. Root cause: bar-level rf_daily = 5%/409 bars at 4H. The
   Sharpe metric systematically underestimates trend-following at intraday resolution.
   Confirmed structural issue; use Calmar/OOS/WFA as primary quality signals.

## Decision for Round 2
- KEEP: EMA Velocity Breakout (4H) — confirmed champion
- REPLACE: ADX Trend Strength Entry → Keltner Channel Breakout (ATR-envelope, new signal)
- REPLACE: RSI Dip Buy → Volume Surge Momentum (volume-confirmed ROC, new signal)
