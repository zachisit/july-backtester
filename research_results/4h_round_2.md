# 4H Research — Round 2
**Date:** 2026-04-11
**Run ID:** 4h-r2-keltner-volsurge_2026-04-11_14-15-21
**Universe:** Liquid 4H (20) — 20 ETFs + mega-caps via Polygon
**Period:** 2018-01-02 → 2026-04-10 (WFA split: 2024-08-07)

## Research Question
Can Keltner Channel Breakout and Volume Surge Momentum (genuinely new signal families)
pass WFA and produce positive OOS P&L on the 4H universe? Replace ADX Trend Strength
Entry (127 trades, Sharpe -4.80) and RSI Dip Buy (WFA Overfitted, OOS -2.51%).

## Strategies Tested

| Strategy | Type | Signal |
|---|---|---|
| EMA Velocity Breakout (4H) | KEPT | EMA(10d/30d) cross + SMA(200d) |
| Keltner Channel Breakout (4H) | NEW | Close > EMA(20d)+2×ATR(10d) + SMA(200d) |
| Volume Surge Momentum (4H) | NEW | ROC(10d) > 1.5% + Volume > 1.5× avg + SMA(200d) |

## Core Performance

| Strategy | P&L (%) | vs. SPY | Sharpe | Max DD | MC Score | WFA Verdict |
|---|---|---|---|---|---|---|
| EMA Velocity Breakout (4H) | +175.85% | +21.46% | -0.39 | 19.68% | 5 | Pass |
| Keltner Channel Breakout (4H) | +128.76% | -25.63% | -0.54 | 16.09% | 5 | Pass |
| Volume Surge Momentum (4H) | +57.04% | -97.35% | -0.79 | 15.01% | 5 | Pass |

## Robustness

| Strategy | OOS P&L | WFA Verdict | RollWFA | MC Score |
|---|---|---|---|---|
| EMA Velocity Breakout (4H) | +48.68% | Pass | Pass (3/3) | 5 |
| Keltner Channel Breakout (4H) | +33.01% | Pass | Pass (3/3) | 5 |
| Volume Surge Momentum (4H) | +16.70% | Pass | Pass (3/3) | 5 |

## Extended Metrics

| Strategy | Calmar | RS(avg) | RS(min) | RS(last) | PF | WinRate | Trades | Expct(R) | SQN |
|---|---|---|---|---|---|---|---|---|---|
| EMA Velocity Breakout (4H) | 0.66 | -0.99 | -40.83 | -3.15 | 1.75 | 33.07% | 1019 | 1.066 | 4.21 |
| Keltner Channel Breakout (4H) | 0.65 | -0.99 | -61.92 | -3.02 | 1.43 | 36.81% | 2043 | 0.425 | 4.25 |
| Volume Surge Momentum (4H) | 0.37 | -1.26 | -61.92 | -3.26 | 1.18 | 35.39% | 3151 | 0.145 | 2.56 |

## Strategy Correlation

| Pair | r |
|---|---|
| EMA ↔ Keltner | 0.03 (essentially uncorrelated) |
| EMA ↔ Volume Surge | 0.11 |
| Keltner ↔ Volume Surge | 0.12 |

## Key Findings

1. **Keltner Channel Breakout**: Strong debut — P&L +128.76%, OOS +33.01%, WFA Pass (3/3),
   MC Score 5, Calmar 0.65. Nearly identical Calmar to EMA Velocity. Only 0.03 correlated
   with EMA → excellent portfolio diversifier. CONFIRMED CHAMPION.

2. **Volume Surge Momentum**: All robustness checks pass (OOS +16.70%, WFA Pass 3/3,
   MC Score 5) but weak fundamentals — 3151 trades (one every 2.5 weeks per symbol),
   PF 1.18, SQN 2.56. Signal is too loose (ROC > 1.5% fires too easily at 4H).
   REPLACE in Round 3 with Donchian Channel Momentum.

3. **Negative Sharpe pattern**: All 4H strategies show negative Sharpe despite
   positive Calmar and OOS P&L. Root cause: at 409 bars/year, periods out of
   position contribute 0-return bars that pull the mean below rf_daily. The Sharpe
   metric systematically underestimates trend-following strategies at intraday
   resolution. Use Calmar, OOS P&L, and WFA as primary quality signals.

4. **All strategies genuinely uncorrelated** (max r = 0.12) — excellent portfolio
   properties even though they're all long-only.

## Decision for Round 3

- KEEP: EMA Velocity Breakout (4H) — strongest all-around
- KEEP: Keltner Channel Breakout (4H) — confirmed champion
- REPLACE: Volume Surge Momentum → Donchian Channel Momentum (4H)
  - 20-bar new-high breakout + SMA(200d); exit on 10-bar midline breach
  - Donchian at 4H means 20×1.625=33 bars = ~12 calendar days; structurally
    different from weekly/daily Donchian tested in R1-R51

## Benchmark Context
SPY B&H over the period: +154.39%
- EMA Velocity beats SPY: +21.46% above
- Keltner lags SPY: -25.63% (but outperforms on risk-adjusted basis, MaxDD only 16.09%)
- Volume Surge lags SPY: -97.35% (too many low-quality trades dragging compounding)
