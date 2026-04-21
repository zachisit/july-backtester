# EC-R4: Post-2004 Modern Era (Excludes Dot-Com Crash)
**Date:** 2026-04-16
**Run ID:** ec-r4-post2004_2026-04-16_21-12-30
**Universe:** Sectors+DJI 46 — Norgate total-return data
**Period:** 2004-01-01 → 2026-04-16 (WFA split: 2021-10-28 / RollWFA: 3 folds)
**Timeframe:** Daily (D), No stop loss
**SPY gate:** SMA200

## Research Question
Do the EC strategies (SPY SMA200 gate) show Calmar ≥ 1.0 in the modern era (2004-present)?

## Results

| Strategy | Calmar | MaxRecovery | MaxDD | Sharpe | RS(avg) | MC Score | WFA | OOS P&L |
|---|---|---|---|---|---|---|---|---|
| EC: Price Momentum (6m/15%) + SPY Regime Gate | **0.46** | 794d | 27.89% | 0.58 | 0.44 | **5** | Pass 3/3 | **+605.32%** |
| EC: MA Bounce + SPY Regime Gate | **0.45** | 872d | 23.37% | 0.48 | 0.42 | **5** | Pass 3/3 | +338.82% |
| EC: MAC Fast Exit + SPY Regime Gate | 0.40 | 850d | 21.73% | 0.34 | 0.07 | **5** | Pass 3/3 | +194.75% |
| EC: Donchian (40/20) + SPY Regime Gate | 0.35 | 1,278d | 25.98% | 0.36 | 0.23 | **5** | Pass 3/3 | +295.62% |

## Key Findings

1. **All MC Score = 5 (Robust)** — first time ALL strategies achieve maximum MC robustness.
   On full 1993-present, EC-R1 had mixed MC scores (-1, 0, 2, 5). From 2004-present, all = 5.

2. **MaxRecovery improved significantly vs EC-R1:**
   - EC-R1 (1993-present): 1,191-2,527 days
   - EC-R4 (2004-present): 794-1,278 days
   - Improvement of ~35-55% in MaxRecovery

3. **Calmar plateaus at ~0.46 for daily strategies.**
   The binding constraint: 2008 GFC created a peak-to-trough of ~28% and the recovery
   took until 2011 (with SPY gate keeping strategies flat most of 2008-2009). This
   single event dominates MaxRecovery (2.2 years = 800 days) for the post-2004 period.

4. **Price Momentum + SPY Gate is the strongest daily strategy found so far:**
   Calmar 0.46, MaxRecovery 794, OOS +605%, all MC Score 5. This is the strongest
   risk-adjusted performer in this research program for daily equity bars.

## Why Calmar Stays at ~0.46

Mathematical constraint: If MaxDD = 28% and annual return = 13%, then Calmar = 0.46.
For Calmar = 1.0, need either:
  A) Same MaxDD (28%) with 28% annual return → 2.15× current returns (very hard)
  B) Same return (13%) with 13% MaxDD → halve the MaxDD (requires different asset class)
  C) Both improve: e.g., 20% annual, 20% MaxDD

On Sectors+DJI 46 (individual stocks), MaxDD during 2008 crisis is structurally ~20-30%
even with the SPY gate (stocks fall before SPY crosses SMA200).

## Decision: EC-R5

Test on **Sectors ETF universe only (16 symbols)** from 2004-present. Hypothesis:
- Sector ETFs (XLE, XLK, XLF, etc.) are inherently diversified (each holds 30-100 stocks)
- Lower single-asset volatility → structurally lower MaxDD
- If MaxDD drops to 10-15%: Calmar could reach 0.7-1.0+ with same signal quality
