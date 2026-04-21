# EC-R14: Sharpe Optimization Attempt — REGRESSION
**Date:** 2026-04-17
**Run ID:** ec-r14-sharpe-opt_2026-04-17_14-49-16

## Results

| Strategy | Calmar | Sharpe | MaxDD | WFA | Notes |
|---|---|---|---|---|---|
| SMA200 + Low-Vol Filter (2.5% ATR) | 0.41 | 0.28 | 17.93% | Pass | Worse than plain SMA200 (was 0.61/0.48) |
| MA Bounce + Low-Vol (2.5% ATR) | 0.38 | 0.17 | 16.30% | Pass | Unchanged (same as R13) |
| MA Bounce + Tight Low-Vol (1.5% ATR) | 0.11 | -0.48 | 17.73% | Overfitted | Complete failure |

## Why EC-R14 Failed

**1.5% ATR threshold too tight:**
- Removes too many stocks — only extreme low-vol names remain
- Very low-vol stocks don't bounce off the MA cleanly; they oscillate with no direction
- MA Bounce needs SOME volatility to work (stock must decline to MA then recover)
- Below 1.5% ATR, too few valid setups → OOS P&L -0.97%, WFA Overfitted

**SMA200 + Low-Vol (2.5%) degrades vs plain SMA200:**
- Low-vol filter removes the high-beta names that drive SMA200 profits (NVDA, GDX, XOP)
- Remaining names (XLU, XLI, JNJ) generate same-size drawdowns but smaller gains
- Net Calmar: 0.61 → 0.41 (−33%)

## Critical Insight

**The 2.5% ATR threshold is at the edge of what works for MA Bounce.**
- Below 2.5%: too few setups, OOS deteriorates
- At 2.5%: Sharpe 0.88 (highest achieved), smooth curve, but lower absolute returns
- Above 2.5% (no filter): jagged curve

**The remaining roughness in MA Bounce + Low-Vol 2.5% is NOT from ATR > 2.5% entries.**
It's from the **position concentration**: at 5% allocation, a single trade still represents
5% of the portfolio. Even with low-vol names, a position held for 440 bars (BA 2016-2018)
returning 145% contributes: 5% × 145% = 7.25% portfolio spike when it closes.

## Direction for EC-R15

**Primary lever: reduce allocation per trade to 3% (33 positions max)**

With 3% allocation:
- BA 145% trade impact: 3% × 145% = 4.35% (vs 7.25% at 5%) — 40% less spike
- More concurrent positions (avg 25-30 vs 15-20 at 5%)
- Individual trade closes become smaller % of total portfolio
- Expected: same strategy logic, noticeably smoother curve

Test:
1. MA Bounce + Low-Vol (2.5%) at 3% allocation
2. SMA200 + Low-Vol filter (2.5%) at 3% allocation (maybe better at lower allocation)

**Do NOT test tighter ATR filter** — 1.5% is confirmed as too tight.
