# EC Research Round 49 — Chapter-2 Weekly Champions on Sectors+DJI (ALL FAIL)

**Date:** 2026-04-23
**Run ID:** ec-r49-weekly-champions_2026-04-23_19-53-46
**Strategies tested:** Relative Momentum 13w, BB Breakout 20w, Williams R Weekly (unchanged from Chapter 2)
**Universe:** Sectors+DJI 46 (sectors_dji_combined.json)
**Period:** 2004-01-02 → 2026-04-23
**Timeframe:** Weekly
**Allocation:** 2.5% per position
**Stop-loss:** none

## Context

Session 43 retracted the EC-R46 champion. EC-R48 proved stop-losses are incompatible
with mean reversion. EC-R49 tests whether the Chapter 2 trend-following champions
(validated on NDX Tech 44 weekly) satisfy the 4 EC hard requirements. The universe
was switched to Sectors+DJI 46 to simultaneously check universality and potentially
smoother curves from sector diversification.

## Scorecard Output

```
[REJECTED] Relative Momentum (13w vs SPY) Weekly + SMA200:
  R1 Beats SPY:      FAIL  62% P&L vs SPY 859% (-798pp)
  R2 Smooth curve:   FAIL  top1=9.05%, top5=35.48%
  R3 <365d recovery: FAIL  2520 days (6.9 years)
  R4 Validation:     PASS  WFA Pass, Rolling 3/3, MC 5, OOS +13.66%

[REJECTED] BB Weekly Breakout (20w/2std) + SMA200:
  R1 Beats SPY:      FAIL  151% P&L vs SPY 859% (-708pp)
  R2 Smooth curve:   FAIL  top1=4.36%, top5=19.45%
  R3 <365d recovery: FAIL  1190 days (3.3 years)
  R4 Validation:     PASS  WFA Pass, Rolling 3/3, MC 5, OOS +38.14%

[REJECTED] Williams R Weekly Trend (above-20) + SMA200:
  R1 Beats SPY:      FAIL  388% P&L vs SPY 859% (-471pp)
  R2 Smooth curve:   FAIL  top1=3.94%, top5=15.95% (just over 15% bar)
  R3 <365d recovery: FAIL  833 days (2.3 years)
  R4 Validation:     PASS  WFA Pass, Rolling 3/3, MC 5, OOS +163.96%

*** 0/3 candidates pass all four hard requirements ***
```

## Key Findings

### 1. Universe shift destroyed the strategies

On NDX Tech 44 (Chapter 2 validation universe), these strategies produced:
- Relative Momentum: **166,502% P&L** (vs 62% here)
- BB Breakout: **152,197% P&L** (vs 151% here)
- Williams R: **156,992% P&L** (vs 388% here)

The P&L gap of 1000-2600x confirms these strategies depend heavily on explosive tech
moves (NVDA/META/TSLA-type multi-hundred-percent rallies). On sector ETFs + industrial
stocks, the moves are more modest → trend-following setups don't have outsized winners
to capture.

### 2. Jagged distribution even at diversified universe

Williams R Weekly's top5 trades = 15.95% of total P&L (fails <15% bar by 0.95pp).
Relative Momentum top5 = 35.48% — a few winners dominate the total. This happens
because on a diversified universe the FEW symbols that DO have momentum surges
(e.g. ISRG, LLY, NVDA when present) account for most of the gains.

### 3. Multi-year recoveries persist even on smooth universes

All 3 strategies have multi-year drawdowns (833-2520 days):
- Trend-following at weekly resolution avoids bear-market entries via SMA200 gate
- BUT the SMA200 gate re-entry is slow (weeks-months after bottom)
- The strategy-specific recovery is then compounded by missing the initial recovery
- Net: 2-7 year underwater periods

### 4. EC-R42 → R49 chain of failure

| Round | Approach | R1 | R2 | R3 | R4 | Verdict |
|---|---|---|---|---|---|---|
| EC-R39b | Mean rev + SMA200 gate | FAIL | PASS | FAIL | PASS | 2/4 |
| EC-R43 | Mean rev + 52wk filter | FAIL | PASS | FAIL | PASS | 2/4 |
| EC-R44 | EC-R43 + VIX gate | FAIL | PASS | FAIL | FAIL | 1/4 |
| EC-R45 | EC-R43 + SPY slope | FAIL | PASS | FAIL | PASS | 2/4 |
| EC-R46 | EC-R45 + SMA100 layer | FAIL | PASS | FAIL | PASS | 2/4 |
| EC-R48 (4 stop variants) | EC-R39b + stops | all FAIL | mixed | 1 pass | mixed | 0/4 for all |
| EC-R49 (3 weekly) | Ch2 champions/Sectors+DJI | FAIL | FAIL | FAIL | PASS | 1/4 |

**No round has produced a strategy that passes all 4 requirements.**

## Interpretation

The 4 EC hard requirements create a near-empty solution space on current architectures:

- **Beats SPY** requires capturing concentrated upside → high-beta assets or momentum
- **Smooth distribution** requires dispersed returns → diversification, no winner dominance
- **<365d recovery** requires avoiding 2008-type drawdowns → short bear exposure or gates
- **WFA/MC/OOS** pass is achievable → not the binding constraint

The first three are in structural tension. Concentrated momentum → few big winners → jagged
AND hard 2008 drawdowns. Diversified mean reversion → smooth AND bear-proof via gates → but
lags SPY in bull markets.

## Next Research Direction: EC-R50

### Option A (next to run): Re-test Williams R Weekly on NDX Tech 44 — its native universe

Williams R Weekly was closest to passing (R2 just over at 15.95%, R3 833 days). On its
native NDX Tech 44 universe where it scored 156,992% P&L, R1 passes massively. If the
distribution on NDX Tech is also smooth and recovery is shorter, we might have a champion.
Risk: NDX Tech has deeper 2008/2022 drawdowns than Sectors+DJI; R3 may get worse, not better.

### Option B: Long/short book with SPY short during VIX>35

Add a short SPY overlay during crisis regimes. Short profits offset long losses in 2008/2022,
compressing recovery. Preserves bull-market long P&L. Truly different architecture — the
4-gate intersection is plausibly non-empty here.

### Option C: ETF-only sector rotation at weekly resolution

Only 11-13 sector ETFs. No single-stock outlier problem. Monthly rebalance to top-3 momentum
ETFs. Natural smoothness from ETF composition. May not beat SPY by huge margin but likely
beats by small margin with much smaller drawdown.

### Recommendation: Run Option A first (smallest change), then Option C if A fails

Option B requires building short-side capability in the engine (signal=-2), which exists
but is untested at scale. Save for EC-R52 if A and C both fail.
