# EC-R15: 3% Allocation Test — REGRESSION (Cash Drag)
**Date:** 2026-04-17
**Run ID:** ec-r15-3pct-alloc_2026-04-17_14-54-27

## Hypothesis
Reduce allocation from 5% → 3% (max 33 positions). At 3%, a 145% winning trade contributes
3% × 145% = 4.35% portfolio gain on exit vs 7.25% at 5% — 40% less spike.

## Results

| Strategy | Calmar | Sharpe | MaxDD | OOS P&L | Trades | WFA |
|---|---|---|---|---|---|---|
| MA Bounce + Low-Vol (2.5% ATR) @ 3% | 0.32 | -0.02 | 14.29% | +46.98% | 5413 | Pass |
| SMA200 + Low-Vol (2.5% ATR) @ 3% | 0.42 | 0.16 | 14.38% | +76.09% | 5078 | Pass |

Both MC Score 5, WFA Pass (3/3).

## Why EC-R15 Failed

**Cash drag kills returns below the risk-free rate hurdle:**
- At 3% allocation, portfolio holds ~15-20 active positions = 45-60% invested at any time
- Uninvested cash earns nothing in the simulation
- MA Bounce CAGR at 3% ≈ 4.4%/year
- Risk-free rate in config: 5%/year
- Excess return = 4.4% − 5.0% = **−0.6% annually** → Sharpe = −0.02

The −0.02 Sharpe is a **measurement artifact** of the risk-free rate being above the strategy CAGR.
It does NOT mean the strategy lost money (P&L was +168.74% total). It means the strategy
fails to beat the risk-free hurdle rate after adjusting for cash drag.

**OOS P&L collapsed:** +46.98% at 3% vs +179% (EC-R13 at 5%) — same trades, less capital deployed.

**Verdict:** 3% allocation creates too much uninvested cash, dragging CAGR below hurdle rate.
The spike-reduction benefit (40% smaller per-trade impact) is not worth the return sacrifice.

## Key Insight

**The relationship between allocation and smoothness is non-linear:**
- 5% allocation: portfolio invests ~75-100% of capital → CAGR stays above hurdle
- 3% allocation: portfolio invests ~45-60% of capital → CAGR falls below 5% hurdle

The 3% allocation reduces the per-trade spike magnitude but also reduces total returns
proportionally. It does not improve the Sharpe ratio or visual smoothness — it just makes
the entire curve flatter (lower CAGR) with smaller individual spikes but the same RS(avg).

## Direction

Do NOT test sub-5% allocations. 5% is the floor before cash drag materially impairs returns.
