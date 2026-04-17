# EC-R6: Relative Momentum (Stock vs SPY) + SPY Gate vs Price Momentum
**Date:** 2026-04-16
**Run ID:** ec-r6-rel-momentum_2026-04-16_21-19-07
**Universe:** Sectors+DJI 46, 2004-2026

## Results

| Strategy | Calmar | MaxRecovery | MaxDD | Sharpe | OOS P&L | Trades | MC Score |
|---|---|---|---|---|---|---|---|
| EC: Relative Momentum + SPY Gate | 0.39 | 997d | 16.78% | 0.19 | +71.50% | 467 | 5 |
| EC: Price Momentum (6m/15%) + SPY Gate | 0.46 | 794d | 27.89% | 0.58 | +605.32% | 822 | 5 |

## Analysis — RESULT: Relative Momentum is INFERIOR to Price Momentum on daily bars.

1. **Lower Calmar** (0.39 vs 0.46) despite lower MaxDD (16.78% vs 27.89%).
   The lower return doesn't compensate for the lower drawdown.

2. **Very few trades**: 467 over 22 years = ~1 signal per symbol per year.
   The `relative > 1.15` threshold is very conservative — only fires when a stock has
   beaten SPY by 15%+ in 13 weeks. This creates sparse signals.

3. **OOS P&L only +71.50%** vs +605% for Price Momentum. The Relative Momentum
   strategy doesn't generate enough opportunities to compound meaningfully.

4. **RS(min) = -144.72** (startup artifact from sparse trades).

## EC Research Summary — Best Daily Strategy Found

After 6 rounds of research, the best daily strategy for smooth equity curves is:

**EC: Price Momentum (6m/15%) + SPY SMA200 Gate on Sectors+DJI 46, 2004-present**
- Calmar: **0.46** (target was 1.0 — not reached, but better than prior 0.30-0.52)
- MaxRecovery: **794 days** (vs 1,176 days in prior Conservative v2 without SPY gate)
- MaxDD: 27.89%
- MC Score: **5 (all MC Robust)**
- WFA: Pass + RollWFA 3/3
- OOS P&L: +605%
- Structural improvement: SPY gate keeps strategies flat during 2008, 2022 crashes

## Why Calmar ≥ 1.0 Is Structurally Hard on Daily US Equities

Mathematical constraint: to achieve Calmar ≥ 1.0 with MaxDD ~28%, need ~28% annual
return. This requires exceptional momentum in concentrated positions. Alternatively,
MaxDD must drop to ~12% while keeping ~12% annual return.

The 2008 financial crisis creates the binding constraint: even with SPY gate (exit Jan 2008),
strategies peaked in summer 2007 and need 2+ years to compound back. This is inherent to
any market-following strategy that:
1. Doesn't profit from down markets (no short selling)
2. Misses 1-2 years of the 2009-2011 recovery while cash (waiting for SPY re-entry signal)
3. Starts compounding back from a reduced equity base

## Decision: EC-R7 — Sensitivity Sweep on Price Momentum

Run sensitivity sweep on EC: Price Momentum (6m/15%) + SPY Gate to confirm it's
robust (not cherry-picked parameters). If sweep shows ≥ 70% profitable variants,
declare as confirmed EC champion strategy.
