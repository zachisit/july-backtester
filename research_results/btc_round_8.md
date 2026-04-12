# Bitcoin Research Round 8 — New Signal Families Base Test (BTC-R8)

**Date:** 2026-04-12
**Run ID:** btc-daily-r8-new-families_2026-04-12_12-49-37
**Symbol:** X:BTCUSD (single asset)
**Period:** 2017-01-03 → 2026-04-10
**New file created:** `custom_strategies/btc_strategies_v3.py`
**Strategies tested:** 6 (CMF ×2, Price Momentum ×2, BB Breakout ×2)

## Research Question

Three untested signal families on Bitcoin daily: CMF (volume flow), Price Momentum (ROC), and BB Breakout. Can any produce a new confirmed champion with Calmar > 0.79 and MaxDD < 60%?

## Results

| Strategy | P&L | Calmar | MaxDD | OOS P&L | WFA | RollWFA | Trades | Notes |
|---|---|---|---|---|---|---|---|---|
| BTC CMF Trend (20d/0.05) + SMA200 | +2,012.05% | 0.73 | 53.34% | +249.69% | Pass | 3/3 | 28 | Calmar < BTC B&H → FAIL |
| BTC CMF Trend (14d/0.05) + SMA120 | +1,444.93% | 0.53 | 64.86% | +75.83% | Pass | 3/3 | 42 | Calmar too low + MaxDD too high → FAIL |
| BTC Price Momentum (90d/5%) + SMA200 | +5,541.37% | **0.84** | 64.89% | +3,568.40% | Pass | 2/2 | 20 | Calmar ✓, MaxDD yellow (64.89%) → SWEEP |
| BTC Price Momentum (180d/5%) + SMA200 | +2,068.45% | 0.53 | 73.78% | +1,456.67% | N/A | 2/2 | 12 | Too sparse → FAIL |
| BTC BB Breakout (20d/2.5σ) + SMA200 | +670.82% | **0.88** | **27.94%** | +214.55% | N/A | 3/3 | 28 | Calmar ✓, MaxDD best ever → SWEEP |
| BTC BB Breakout (30d/2.0σ) + SMA200 | +1,535.90% | 0.73 | 47.84% | +162.59% | Pass | 3/3 | 33 | Calmar < BTC B&H → FAIL |

## Key Findings

### CMF (Chaikin Money Flow) — Signal Family Assessment: REJECTED
Both CMF variants fail the primary criterion: Calmar < BTC B&H (0.79).

- CMF (20d) Calmar 0.73: Volume flow alone cannot match Bitcoin B&H risk-adjusted returns
- CMF (14d) Calmar 0.53, MaxDD 64.86%: Faster CMF is worse, not better
- The exceptional RS(min) = -3.14 from BTC-R1 was a false positive: low tail risk but also low returns
- **Lesson**: CMF on Bitcoin filters bear markets effectively (good RS(min)) but also misses much of the bull run. Net result: marginally profitable but not competitive.

### Price Momentum (ROC) — Signal Family: PROMISING
- 90d/5%: Calmar 0.84 (just above BTC B&H) but MaxDD 64.89% (yellow zone)
- OOS P&L +3,568.40% — extraordinary out-of-sample performance
- Signal: worth sweeping to find parameter zone with MaxDD < 60%

### BB Breakout — Signal Family: PROMISING BUT FRAGILE
- 20d/2.5σ: Calmar 0.88 > BTC B&H, MaxDD 27.94% (LOWEST EVER — exceptional!)
- BUT: only 28 trades → WFA N/A (sparse OOS window), sweep will reveal WFA robustness
- 30d/2.0σ: Calmar 0.73 < BTC B&H → FAIL

## Survivors for Sweep (BTC-R9)
- BTC Price Momentum (90d/5%) + SMA200 — find optimal parameter zone
- BTC BB Breakout (20d/2.5σ) + SMA200 — confirm WFA robustness
