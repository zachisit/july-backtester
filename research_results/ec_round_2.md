# EC-R2: 10% Stop Loss on Sector ETFs
**Date:** 2026-04-16
**Run ID:** ec-r2-sectors-10pct-stop_2026-04-16_21-06-03
**Universe:** Sectors 16 ETFs (sectors.json) — Norgate total-return data
**Period:** 1993 → 2026 (WFA split: 2019-08-25 / RollWFA: 3 folds)
**Timeframe:** Daily (D), Stop loss: 10% percentage
**Allocation:** 10% per position

## Research Question
Will a 10% per-trade stop loss improve Calmar and MaxRecovery on sector ETFs?

## Results

| Strategy | Calmar | MaxRecovery | MaxDD | Sharpe | RS(avg) | MC Score | WFA |
|---|---|---|---|---|---|---|---|
| EC: MA Bounce + SPY Regime Gate w/ 10% SL | 0.18 | 1,511d | 22.05% | -0.05 | -0.39 | 5 | Pass 3/3 |
| EC: MAC Fast Exit + SPY Regime Gate w/ 10% SL | 0.18 | 1,260d | 19.11% | -0.10 | -0.54 | 5 | Pass 3/3 |
| EC: Donchian (40/20) + SPY Regime Gate w/ 10% SL | 0.14 | 1,761d | 18.50% | -0.23 | -1.42 | 5 | Pass 3/3 |
| EC: Price Momentum (6m/15%) + SPY Regime Gate w/ 10% SL | 0.17 | 1,589d | 21.89% | -0.09 | -0.68 | 5 | Pass 3/3 |

## Analysis — RESULT: REJECTED. Stop losses incompatible with these strategies.

1. **Negative Sharpe on all 4 strategies** — the stop loss is cutting winning trades.
   P&L over 33 years: 99-195% (≈ 2-3.5% annually = BELOW risk-free rate).
   These strategies are literally risk-adjusted-negative with a 10% stop.

2. **Root cause: Sector ETF normal volatility is 5-15%.** During a bull market,
   XLE/XLF/XLK can retrace 8-12% before resuming uptrend. A 10% stop exits at the
   bottom of normal corrections. The ETF then bounces and the strategy misses the gain.
   This is especially fatal for MA Bounce (you BUY the pullback, then stop at 10%
   before the bounce completes).

3. **MaxRecovery not improved by stop loss** — moved from 1,191-2,527 days (EC-R1)
   to 1,260-1,761 days. Stop losses cap individual trade loss but don't change the
   fundamental issue: the strategy is flat for long periods after crashes.

4. **Total P&L completely destroyed** — went from 1,426-8,401% (EC-R1) to 99-195%.
   The stop loss sacrificed 8.5× the upside to save a minimal amount of downside.

## Key Finding: Anti-Pattern Established

**DO NOT add percentage stop losses to any of these strategies on daily ETFs.**
The ETF volatility characteristics (normal 5-15% intra-year corrections in healthy uptrends)
are incompatible with tight stop losses. The stop loss fires during normal corrections and
misses the majority of bull market gains.

If stops must be used, minimum 20-25% would be required for ETFs — at which point the
stop provides minimal downside protection and only caps catastrophic single-position losses.

## Decision: EC-R3

Try a **tighter SPY regime gate (SPY SMA50 instead of SMA200)** — no stop loss.

Rationale: SPY SMA200 fires 6-12 months too late into bear markets. SPY SMA50 fires:
- 2000 crash: ~May 2000 vs SMA200 cross March 2001 (10 months earlier)
- 2008 crash: ~August 2007 vs SMA200 cross January 2008 (5 months earlier)
- 2022 crash: ~January 2022 (similar to SMA200 for this fast crash)

By avoiding 5-10 months of losses at the start of each major bear market, MaxRecovery
should drop from 1,200-2,500 days toward the 365-day target.

Downside risk: SMA50 creates more false exit signals during normal corrections (2011, 2014,
2016), missing some upside. Net impact needs empirical validation.
