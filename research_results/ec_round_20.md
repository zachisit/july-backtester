# EC-R20: S&P 500 Universe — Three Architecture Directions
**Date:** 2026-04-17
**Run ID:** ec-r20-sp500-three-variants_2026-04-17_22-10-24
**Universe:** S&P 500 Current & Past (1273 symbols after min_bars filter)
**Config:** 5% allocation, no stop loss, Norgate daily, 2004-2026

## Context

EC-R19 champion (MA Bounce + Low-Vol ATR Filter + SPY SMA96 Gate) was rejected:
- 2022-2024 prolonged drawdown (> 2 years flat/down)
- Does not beat SPY (CAGR 9.22% vs SPY ~11%)

New hard requirements (ALL must pass):
1. Visually gradual increase — no staircases, no jagged upthrusts
2. No prolonged drawdowns (> 12 months duration disqualifies)
3. CAGR must EXCEED SPY B&H return

## Results

SPY B&H: **861.83%** (2004-2026, total return)

| Strategy | P&L | Sharpe | MaxDD | Calmar | OOS | WFA | MaxRcvry | MC |
|---|---|---|---|---|---|---|---|---|
| MA Bounce + SMA200 (no ATR, no SPY gate) | 262.76% | 0.14 | 41.74% | 0.14 | -1.85% | Overfitted | 1972d | 5 |
| SMA200 Hold + SPY SMA50 Gate | 435.72% | 0.29 | 19.51% | 0.40 | +135.45% | Pass | 953d | 5 |
| EMA21/63 Trend + SMA200 (no SPY gate) | 94.69% | -0.14 | 44.75% | 0.07 | -7.32% | Overfitted | 3317d | 3 |

## Why All Three Failed the SPY Beat Requirement

**Fundamental problem: cash drag vs always-in SPY.**

SPY B&H = 861.83% over 22 years ≈ 11.2% CAGR annually. This is the 2004-2026 period which
includes the greatest bull market in history (post-GFC, QE era, 2009-2021 virtually uninterrupted).

These strategies are OUT of the market for significant periods:
- SMA200 Hold: holds ~60-70% of S&P 500 symbols at any time
- MA Bounce: enters on specific confirmed setups, exits individually per stock
- EMA Trend: holds when EMA21 > EMA63, exits on crossing

Being 40-50% in cash (or having individual stocks exit) during a 11%/year compounding market
means roughly 6-7% CAGR → 435% max vs SPY's 861%. Mathematically impossible to close the gap
without either more time in the market OR selecting better-than-SPY-average stocks.

## Best Performer: SMA200 Hold + SPY SMA50

Despite failing the SPY beat requirement, this is the most defensible variant:
- WFA Pass, OOS +135% (not overfitted)
- MaxDD 19.51% (similar to EC champion)
- Calmar 0.40 (better risk-adjusted than most)
- MC Score 5, RollWFA Pass (3/3)
- BUT: MaxRcvry 953 days (2.6 years) — still too long per new requirements
- AND: P&L 435% vs SPY 861% — does not meet the "beats SPY" requirement

PDF: `custom_strategies/private/research_results/pdfs/ec_daily/EC-R20_SMA200_Hold_+_SPY_SMA50_Gate.pdf`

## MA Bounce Without ATR Filter: OVERFITTED

The MA Bounce without the low-vol filter performed WORSE in OOS (-1.85%) despite
better IS performance. This confirms: removing the ATR filter allows entry into
higher-volatility stocks that overfit in-sample but don't generalize.

The low-vol filter was HELPING with robustness (MC Score 5, WFA Pass) — just not CAGR.

## Root Cause Diagnosis

To beat SPY with a smooth curve, the strategy must select
**better-than-average stocks** — not just a subset of all stocks.

An always-in approach (SMA200 hold) captures the average of S&P 500 ≈ SPY.
But the strategy EXITS stocks when they breach SMA200, creating cash drag.

**The only path to beating SPY with a systematic active strategy:**
Select stocks that OUTPERFORM the index (momentum, quality, etc.)
AND hold them long enough to compound (low turnover).

## Direction for EC-R21

**Momentum selection on S&P 500:**
- Entry: stock has beaten SPY by 5%+ over the past 6 months (relative momentum)
- Gate: individual SMA200 (stock in uptrend) + SPY SMA50 (fast market gate)
- Exit: relative strength vs SPY turns negative OR SMA200 breach OR SPY gate
- Expected: concentrates in market leaders → captures momentum premium → beats SPY over time

Academic basis (Jegadeesh-Titman, 1993): stocks that have outperformed over
the past 3-12 months continue to outperform for the next 3-12 months.
This momentum premium averages 2-4%/year above market, historically.

Three variants to test in EC-R21:
1. Relative Momentum (6m, +5% vs SPY) + SMA200 + SPY SMA50
2. Absolute Momentum (ROC 6m > 15%) + SMA200 + SPY SMA50
3. Relative Momentum (6m, +5% vs SPY) + SMA200 only (no SPY gate)
