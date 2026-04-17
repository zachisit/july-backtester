# EC-R1: SPY Macro Regime Gate on Daily Strategies
**Date:** 2026-04-16
**Run ID:** ec-r1-daily-spy-regime_2026-04-16_21-00-53
**Universe:** Sectors+DJI 46 — Norgate total-return data
**Period:** 1993-01-29 → 2026-04-16 (WFA split: 2019-08-25 / RollWFA: 3 folds)
**Timeframe:** Daily (D)
**Allocation:** 10% per position
**SPY B&H benchmark:** 2,799.99%

## Research Question
Can adding a SPY macro regime gate (SPY > SMA200) to the 6 Conservative v2 champion
strategies improve equity curve smoothness? Specifically, can we achieve Calmar ≥ 1.0
and MaxRecovery ≤ 365 days on daily strategies?

## Hypothesis
The Conservative v2 prior results showed Calmar 0.30-0.52 and MaxRecovery 1,085-1,722 days.
Root cause: per-stock SMA200 gate doesn't protect against market-wide crashes (2001-2003, 2008-2009).
Fix: portfolio-level SPY SMA200 gate forces exits and prevents entries during bear markets.

## Results

| Strategy | Calmar | MaxRecovery | MaxDD | Sharpe | RS(min) | MC Score | WFA | RollWFA |
|---|---|---|---|---|---|---|---|---|
| EC: Price Momentum (6m/15%) + SPY Regime Gate | **0.46** | 1,263d | 28.32% | 0.57 | -20.75 | -1 | Pass | 3/3 |
| EC: Williams R Weekly (above-20) + SPY Regime Gate | 0.42 | 2,059d | 23.85% | 0.42 | -627† | 0 | Pass | 3/3 |
| EC: MAC Fast Exit + SPY Regime Gate | 0.39 | **1,191d** | **21.90%** | 0.32 | -34.33 | 0 | Pass | 3/3 |
| EC: MA Bounce + SPY Regime Gate | 0.32 | 2,050d | 31.05% | 0.42 | -49.01 | 2 | Pass | 3/3 |
| EC: RSI Weekly Trend (55) + SPY Regime Gate | 0.26 | 2,135d | 30.41% | 0.28 | -109† | 5 | Pass | 3/3 |
| EC: Donchian (40/20) + SPY Regime Gate | 0.24 | 2,527d | 35.15% | 0.32 | -103† | 5 | Pass | 3/3 |

†RS(min) artifacts: RSI Weekly and Williams R were designed for WEEKLY bars. Run on daily bars with
the same period parameters, they trade far more frequently → startup artifact in rolling Sharpe.
Williams R RS(min) = -627 is NOT a real tail risk figure; it's the warmup period artifact.

## Prior Conservative v2 (weekly, same universe) for comparison

| Strategy | Calmar | MaxRecovery | MaxDD | Notes |
|---|---|---|---|---|
| MA Bounce | 0.32 | 1,085 | 26.85% | Weekly timeframe |
| MAC Fast Exit | 0.31 | 1,638 | 24.98% | Weekly timeframe |
| Donchian | 0.30 | 1,386 | 23.59% | Weekly timeframe |
| Price Momentum | 0.52 | 1,176 | 18.88% | Weekly timeframe |
| RSI Weekly | 0.39 | 1,386 | 26.34% | Weekly timeframe |
| Williams R | 0.42 | 1,722 | 23.76% | Weekly timeframe |

## Analysis

**Result: INCONCLUSIVE — SPY regime gate alone does not achieve Calmar ≥ 1.0.**

1. **SPY SMA200 gate fires too late.** During 2000-2003: stocks peaked March 2000, SPY crossed
   below SMA200 in March 2001 — 12 months of losses before the gate triggered. By then, positions
   had already accumulated large drawdowns. MaxRecovery is dominated by these deep prior drawdowns.

2. **Best performers on daily timeframe:**
   - Price Momentum: Calmar 0.46, MaxRecovery 1,263d — best Calmar
   - MAC Fast Exit: Calmar 0.39, MaxRecovery 1,191d — BEST MaxRecovery
   These two are the most promising for further development.

3. **"Weekly" strategies on daily bars show structural problems:**
   - RSI Weekly Trend: RS(min) -109.41, Calmar only 0.26
   - Williams R: RS(min) -627 (artifact), MaxRecovery 2,059d
   These strategies need weekly bars to function properly.

4. **All 6 WFA Pass + RollWFA 3/3** — the SPY gate doesn't hurt robustness.

## Why SPY SMA200 Gate Is Insufficient

Historical timeline of market crashes and SPY SMA200 crossing:
- 2000 crash: peak March 2000, SMA200 cross March 2001 = 12 MONTHS of losses before gate
- 2008 crash: peak Oct 2007, SMA200 cross Jan 2008 = 3 months of losses before gate
- 2022 crash: peak Nov 2021, SMA200 cross Jan 2022 = 2 months of losses before gate

The gate helps STOP the bleeding but doesn't PREVENT initial damage. Strategies need
either: (A) faster-trigger exit (SMA50 instead of SMA200), OR (B) per-trade stop losses
to cap maximum loss per position.

## Decision: EC-R2

Test **per-trade stop losses (10%)** on the 4 genuinely daily strategies:
- EC: MA Bounce + SPY Regime Gate
- EC: MAC Fast Exit + SPY Regime Gate
- EC: Donchian (40/20) + SPY Regime Gate
- EC: Price Momentum (6m/15%) + SPY Regime Gate

Drop RSI Weekly and Williams R from daily research (wrong timeframe).
Universe: sectors.json (16 Sector ETFs) — inherently diversified, no single-stock blowups.
Stop loss: 10% (sector ETFs rarely move 10% in a single day → not triggering on noise).
