# EC-R12: 5% Allocation Test — Visual Smoothness Experiment
**Date:** 2026-04-17
**Universe:** Sectors+DJI 46, 2004-2026
**Change vs EC-R11:** allocation_per_trade 10% → 5% (20 concurrent positions instead of 10)

## Objective

The EC research through R11 declared a champion (PM v3, Calmar 0.98) based on metrics alone.
Visual inspection of PDF tearsheets revealed that the equity curves still show **jagged upthrusts**
despite excellent Calmar/Sharpe/MaxDD numbers. Root cause: Price Momentum selects high-volatility
stocks by design, and concentrated 10% positions mean a single stock's explosive move spikes the
whole portfolio curve.

EC-R12 tests whether **doubling position count to 20 (5% allocation)** produces smoother curves.
Also tested: MA Bounce and Donchian as non-momentum style alternatives.

## Results

| Strategy | Calmar | MaxDD | MaxRcvry | Sharpe | OOS P&L | Trades | RS(avg) |
|---|---|---|---|---|---|---|---|
| PM v3 @ 5% alloc | 0.73 | 12.79% | 1061d | 0.44 | +214% | 1601 | ~0.22 |
| MA Bounce @ 5% alloc | 0.53 | 19.16% | 750d | 0.48 | +321% | 3408 | ~0.40 |
| Donchian @ 5% alloc | 0.41 | 19.23% | 1023d | 0.32 | +180% | 2541 | ~0.28 |

## Visual Assessment (PDF Tearsheets)

All three strategies still exhibit jagged upthrusts — increasing position count from 10→20 is
**insufficient** to achieve a visually smooth curve. The momentum-driven selection bias (strongest
recent movers) overrides the diversification benefit of more positions.

## Key Findings

**5% allocation tradeoffs vs EC-R11 (10% allocation):**
- PM v3 Calmar drops: 0.98 → 0.73 (−25%)
- PM v3 MaxRecovery worsens: 752d → 1061d (+41%)
- MA Bounce shows best MaxRecovery of the three (750d), highest OOS (+321%), most trades (3408)
- MA Bounce RS(avg) 0.40 > PM v3 RS(avg) 0.22 — more consistent Sharpe across time windows

**What 5% allocation did NOT fix:**
- Visual curve smoothness — jagged upthrusts persist for all three strategies
- The core problem is strategy-level (type of stocks selected), not just position concentration

## Direction for EC-R13

The visual smoothness requirement cannot be solved by allocation adjustments alone. Need a
fundamentally different strategy architecture:

**Option A: Mean-Reversion / Low-Volatility Focus**
- Target stocks near MA support that are already low-beta / low-volatility
- Stocks pulling back to SMA50 are typically mid-trend, not explosive breakout candidates
- MA Bounce is the best candidate but needs to explicitly filter for lower-volatility names

**Option B: Equal-Weight Rotation + More Frequent Rebalancing**
- Monthly sector rotation among the 16 sector ETFs only (not individual stocks)
- ETFs are inherently diversified → no single-stock spike possible
- Smoother underlying instruments = smoother portfolio

**Option C: Systematic Daily Trend (SMA200 Long-Only, Full Universe Exposure)**
- Hold all 46 symbols that are above SMA200, equal-weighted
- Exit all that fall below SMA200
- Forces ~20-40 concurrent positions at all times
- Trend-following without momentum concentration bias

**Verdict:** Test Option C first — systematic full-universe long-only SMA200 regime. If it
produces smooth curve with acceptable Calmar, adopt. Then test Option B as a complement.

## Research Decision

EC-R13 direction: implement systematic SMA200 long-only strategy on Sectors+DJI 46.
Also test MA Bounce with explicit low-volatility filter (ATR-based).
