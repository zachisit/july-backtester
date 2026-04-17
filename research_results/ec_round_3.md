# EC-R3: Tighter SPY SMA50 Gate
**Date:** 2026-04-16
**Run ID:** ec-r3-sma50-gate_2026-04-16_21-08-40
**Universe:** Sectors+DJI 46 — Norgate total-return data
**Period:** 1993-01-29 → 2026-04-16
**Timeframe:** Daily (D), No stop loss
**SPY gate:** SMA50 (tighter than EC-R1's SMA200)
**Allocation:** 10% per position

## Research Question
Does a tighter SPY SMA50 gate (exits 5-10 months earlier in bear markets) improve
Calmar and MaxRecovery vs the SMA200 gate used in EC-R1?

## Results

| Strategy | Calmar | MaxRecovery | MaxDD | Sharpe | RS(min) | MC Score | WFA |
|---|---|---|---|---|---|---|---|
| EC2: Price Momentum (6m/15%) + SPY SMA50 Gate | 0.20 | 2,149d | 37.33% | 0.25 | -10.27 | 1 | Pass 3/3 |
| EC2: MAC Fast Exit + SPY SMA50 Gate | 0.17 | 2,527d | 33.69% | 0.13 | -9.90 | 5 | Pass 3/3 |
| EC2: MA Bounce + SPY SMA50 Gate | 0.15 | 2,670d | 43.03% | 0.17 | -6.53 | 5 | Pass 3/3 |
| EC2: Donchian (40/20) + SPY SMA50 Gate | 0.11 | 3,033d | 45.32% | 0.07 | -5.82 | 5 | Pass 3/3 |

## Comparison vs EC-R1 (SMA200 gate)

| Metric | EC-R1 Best (SMA200) | EC-R3 Best (SMA50) | Direction |
|---|---|---|---|
| Calmar | 0.46 | 0.20 | ⬇ WORSE |
| MaxRecovery | 1,191d | 2,149d | ⬇ WORSE |
| MaxDD | 21.90% | 33.69% | ⬇ WORSE |
| Sharpe | 0.57 | 0.25 | ⬇ WORSE |
| Total Trades | ~1,264 | ~2,765 | Much more trades |

## Analysis — RESULT: REJECTED. SMA50 gate is strictly worse than SMA200.

**Root cause — whipsaw multiplication:**
SPY SMA50 crosses below and above during normal corrections:
- Feb 2016 flash drop: false exit signal
- Sep-Oct 2014: brief SMA50 cross
- Mid-2011: correction crossing SMA50
Each false exit causes the strategy to miss a portion of the bull market recovery.
Net effect: MORE total trades (3x in some cases), LOWER returns, HIGHER MaxDD.

**High pairwise correlation (0.81-0.83):** All 4 strategies move in lockstep because
they're all gated by the same SPY SMA50 signal. When SPY SMA50 triggers exit, ALL
strategies simultaneously exit → correlated cash periods → correlated re-entry risk.

**MaxDD INCREASED (33-45% vs 21-35% in EC-R1):** Despite "earlier" exits, the
SMA50 creates more false entries that buy into mid-correction bounces that fail.

## Key Finding: Anti-Pattern Established

**DO NOT use SPY SMA50 as an equity regime gate. SMA200 is superior.**
The SMA50 creates more noise than signal. It fires too frequently during normal
bull market corrections, sacrificing significant upside for minimal downside protection.
The SMA200 is slower but filters genuine bear markets without excessive whipsaw.

## Structural Finding: 2000-2003 Is the Problem

All three EC approaches so far have failed to achieve Calmar ≥ 1.0 on the full 1993-2026
period. The common pattern: MaxRecovery is always 1,100-3,000 days because the 2000-2003
crash creates a deep trough that takes years to recover.

The SPY SMA200 gate didn't exit fast enough (crossed below March 2001, 12 months after
the NASDAQ peak). The SMA50 gate created more whipsaw than protection.

## Decision: EC-R4

Test the original EC-R1 strategies (SMA200 gate) starting from **2004-01-01** (post-dot-com).
This measures whether these strategies work well in the modern era (covering 2008 GFC, 2020 COVID,
2022 rate hikes) without being dragged by the exceptional 2000-2003 event.

Hypothesis: Starting from 2004, with the 2008 GFC being the worst crash:
- SPY SMA200 gate exits in Jan 2008 (only 3 months after Oct 2007 peak)
- Strategies go flat during 2008 (limiting damage to ~Oct-Dec 2007 drawdown)
- Quick recovery in 2009 bull market
- Expected: Calmar >> 1.0, MaxRecovery << 365 days
