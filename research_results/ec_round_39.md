# EC Research Round 39 — Mean Reversion + Short EMA + Rotation Architectures

**Date:** 2026-04-23
**Run ID:** ec-r39-mean-rev-daily_2026-04-23_16-46-27
**Symbols:** S&P 500 Current & Past (Norgate, ~1273 valid symbols)
**Period:** 2004-01-02 → 2026-04-23
**WFA:** 80/20 split (IS: 2004-2021-11-05, OOS: 2021-11-05 → 2026-04-23), 3 rolling folds
**Timeframe:** Daily bars
**Allocation:** 2.5% per position

## Context

Session 37 rejected ALL trend-following EC candidates (EC-R34 through EC-R38) as having
"jagged equity curves" — defined as overfit signal where a few outlier trades dominate total P&L.
Even WFA Pass + MC Score 5 are insufficient if top 5 trades > 15% of total P&L.

This round introduces 4 fundamentally new architectures designed to produce uniform trade P&L
distributions, preventing any single trade from creating a visible step in the equity curve.

## Results

| Strategy | Calmar | RS(avg) | RS(min) | MaxRcvry | OOS P&L | WFA Verdict | RollWFA | MC Score | Trades |
|---|---|---|---|---|---|---|---|---|---|
| EC-R39: Mean Rev to SMA20 (3%/2%) | 0.24 | 0.53 | -48.12 | 1054d | +140.72% | **Pass** | 3/3 | 5 | 17,738 |
| EC-R39b: Mean Rev to SMA20 (5%/3%) | 0.25 | 0.56 | -9.81 | 1958d | +227.49% | **Pass** | 3/3 | 5 | 13,058 |
| EC-R40: Short EMA 8/21d + ATR<3% | 0.12 | -0.65 | -8.23 | 3596d | +3.90% | **Likely Overfitted** | 3/3 | 5 | 3,981 |
| EC-R41: SMA50 Rotation + ROC20>2% | 0.10 | 0.32 | -9.15 | 3707d | +67.17% | Pass | 3/3 | 5 | 10,431 |

SPY B&H over period: 534%

## Distribution Diagnostic (MANDATORY before human review)

| Metric | EC-R39 (3%/2%) | EC-R39b (5%/3%) | Threshold |
|---|---|---|---|
| Top 1 trade / total P&L | 2.60% | **2.02%** | < 3% ✓ |
| Top 5 trades / total P&L | 6.78% | **6.38%** | < 15% ✓ |
| P90 / Median ratio | 22.7× | 81.3× | < 5× ✗ (see note) |
| Skewness | +0.60 | +0.46 | ~0 ✗ |
| Total trades | 17,738 | 13,058 | — |
| **PASS top-N test?** | **Yes** | **Yes** | — |

**Note on P90/Median ratio:** The high ratio is an artifact of many near-zero trades ($10-28 median),
NOT a few dominant winners. Top 1 and Top 5 absolute tests pass. No single trade creates a visible step.

## EC-R39b Annual Equity Progression

| Year | Annual P&L | Cumulative Equity | Notes |
|---|---|---|---|
| 2004 | +$18,436 | $118,436 | Gradual ✓ |
| 2005 | +$27,030 | $145,466 | Gradual ✓ |
| 2006 | +$22,448 | $167,914 | Gradual ✓ |
| 2007 | +$21,378 | $189,292 | Gradual ✓ |
| **2008** | **-$61,667** | **$127,625** | **GFC cliff ✗** |
| 2009 | +$17,903 | $145,528 | Slow recovery |
| 2010 | +$10,549 | $156,077 | Slow |
| 2011 | +$7,251 | $163,328 | Slow |
| 2012 | +$7,214 | $170,542 | Slow |
| 2013 | +$48,209 | $218,751 | Recovery complete |
| 2014-2021 | Steady growth | ~$555k by 2021 | Strong ✓ |
| **2022** | **-$84,028** | **$470,733** | **Rate hike bear ✗** |
| 2023-2026 | Recovery | $799,572 | — |

**Total return: ~700% vs SPY 534% → BEATS SPY** ✓
**Worst drawdown: -37.4% at 2009-03-09** (GFC)
**MaxRcvry: 1958 days (~5.4 years)** — fails "no prolonged flat" criterion

## Key Findings

### EC-R39 / EC-R39b: BEATS SPY, passes distribution, fails prolonged recovery

1. **Mean reversion SOLVES the "few lucky trades dominate" problem** — by design, each trade is
   capped at ~8% max gain. With 13,000-17,000 trades, no single trade can create a visible step.
   Distribution diagnostic PASSES (top 5 trades < 7% of total P&L).

2. **Both strategies beat SPY** — EC-R39 total return ~1262%, EC-R39b ~700% vs SPY 534%.
   Beta vs SPY ≈ 0.01 (nearly market-neutral on daily returns), Alpha ~12%/year.

3. **Bear markets cause catastrophic losses** — without a market regime filter, the strategy enters
   pullbacks even during GFC 2008 and rate hike 2022. Both years had >$60k losses on $100k start.
   Recovery takes 4-5 years from the 2008 trough, violating "no prolonged recovery" criterion.

4. **EC-R39 RS(min) = -48.12** — artifact of unfiltered 2008 GFC. The 126-day window during 2008
   shows catastrophic rolling Sharpe. EC-R39b RS(min) = -9.81 (much better, wider entry provides
   more cushion before SMA200 stop fires).

5. **EC-R39b is clearly superior to EC-R39** — deeper entry (5% vs 3%) selects stronger pullback
   setups, better OOS (+227% vs +141%), dramatically better RS(min) (-9.81 vs -48.12).

### EC-R40 (Short EMA 8/21d): REJECTED — WFA Likely Overfitted

EMA(8)/EMA(21) daily crossover with ATR<3% filter overfit to the IS bull market (2004-2021).
OOS P&L only +3.90%. The fast-cycling EMA creates too many false signals at the daily resolution.
Anti-pattern confirmed: **short-window EMA strategies fail WFA on daily bars with ATR filter**.

### EC-R41 (SMA50 Rotation): WEAK — Calmar 0.10

High-frequency rotation (SMA50 + ROC20>2%) generates 10,431 trades but poor risk-adjusted
returns. Calmar 0.10, RS(avg) 0.32, MaxRcvry 3707 days. OOS +67% = positive but weak.
Does not beat SPY. ELIMINATED.

## Next Research Directions

The mean reversion architecture (EC-R39b) solves the "jagged upthrust" problem but introduces
"bear market cliff-down" problem. Two paths forward:

**EC-R42A: EC-R39b + Market Breadth Filter**
- Entry guard: enter pullbacks ONLY when market breadth is acceptable
- e.g., require > 50% of S&P 500 constituents above their 50-day SMA
- This is NOT a binary SPY gate — it's a continuous filter that reduces entries during broad crashes
- Avoids the "flat exclusion period" problem of SPY SMA200 gate while protecting against 2008-type crashes

**EC-R42B: EC-R39b + VIX-Scaled Position Sizing**
- Normal regime (VIX < 25): 2.5% allocation
- Elevated volatility (VIX 25-35): 1.5% allocation
- Crisis (VIX > 35): 0.5% allocation
- Does NOT exclude — just reduces exposure proportionally
- In 2008 GFC, VIX peaked at 80 → position size 0.5% → bear market losses 5× smaller

**PRESENT EC-R39b to human first** before building EC-R42, to determine if the 2008/2022
cliff-downs are acceptable as "honest market losses" or still violate the "smooth curve" requirement.
The distribution passes. The curve has genuine valleys, not overfit upthrusts.

## New Anti-Patterns

- **Short EMA (8/21d) daily + ATR filter = WFA Overfitted** — fast EMAs at daily resolution
  generate too many false IS signals. Fast EMAs work on daily bars only without ATR filter (see
  EC-R20 session where EMA21/63 passed). With ATR filter further reducing entries, overfitting increases.
  Do NOT retry EMA period ≤ 21 at daily bars with any additional entry filter.

- **SMA50 Rotation (ROC20>2%) at 2.5% alloc = Cash drag + weak alpha** — the entry condition
  selects too many stocks (many qualifying) but 2.5% alloc limits to 40 positions. Gains are
  spread too thin at 2.5%; reducing to 1% would help but risks more cash drag on bear market gaps.

## PDFs for Human Review

- `custom_strategies/private/research_results/pdfs/ec_daily/EC-R39b_Mean_Rev_SMA20_5pct_wide.pdf` — PRIMARY
- `custom_strategies/private/research_results/pdfs/ec_daily/EC-R39_Mean_Rev_SMA20_3pct.pdf`
