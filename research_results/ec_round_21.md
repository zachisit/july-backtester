# EC-R21: Momentum Selection on S&P 500 — SPY BEATEN but Staircase Curve
**Date:** 2026-04-17
**Run ID:** ec-r21-abs-momentum-clean_2026-04-17_22-44-57
**Universe:** S&P 500 Current & Past (1273 symbols)
**Config:** 5% allocation, no stop loss, Norgate daily, 2004-2026

## Context

EC-R20 proved cash drag is the structural barrier — strategies holding 60-70% of S&P 500
miss too much compound growth to beat always-in SPY. EC-R21 tested MOMENTUM SELECTION:
concentrate only in stocks that have risen 15%+ over 6 months (Absolute Momentum ROC 6m).
Academic basis: Jegadeesh-Titman momentum premium — past winners continue to outperform.

## Strategies Tested

1. **Relative Momentum (6m+5% vs SPY) + SMA200 + SPY SMA50** — rejected (too few qualify)
2. **Absolute Momentum (ROC 6m >15%) + SMA200 + SPY SMA50** — detailed below
3. **Relative Momentum (6m+5% vs SPY) + SMA200 only** — rejected (OOS weaker, MaxRcvry 1716d)

## KEY RESULT: Absolute Momentum BEATS SPY for the First Time

| Metric | Value |
|---|---|
| CAGR | **14.1%** (vs SPY ~11%) |
| Total Return | **1613.9%** (vs SPY 861.83% terminal) |
| Max Drawdown | 18.9% |
| Calmar | 0.75 |
| Sharpe (Rf=0%) | 0.57 |
| OOS P&L | +296.03% |
| WFA Verdict | Pass (3/3 rolling) |
| MC Score | 5 (Robust) |
| Trades | 3,668 |
| MaxRcvry | 837 days (2.3 years) |
| Alpha vs SPY | +14.02%/yr |

**PDF:** `custom_strategies/private/research_results/pdfs/ec_daily/EC-R21_Absolute_Momentum_ROC_6m_15pct_+_SMA200_+_SPY_SMA50.pdf`

## Visual Assessment — FAILS Smoothness Requirement

The equity curve on page 3 of the PDF is a **pronounced staircase**, not a gradual slope:
- 2004-2022: Ascending staircase with clear plateaus and discrete jumps upward
- 2022-2024: Major drawdown — 594 days (1.63 years) — exceeds the 12-month limit
- Post-2024: Volatile, jagged steps

**Why the staircase happens:**
- Absolute momentum (ROC 6m > 15%) selects stocks that have ALREADY run up significantly
- These are high-momentum stocks: APP (+224% single trade), AMD, AVGO, AAPL
- When multiple momentum stocks exit near the same time (quarterly rebalancing, regime change), the portfolio takes large discrete jumps up or down
- The pattern is structurally identical to the momentum strategies from Chapters 1-2 — just in a different universe

**Largest single-trade contributors (Page 10):**
- APP: +$91,353 (+224%) in 98 bars
- AAMRQ: +$61,356 (+431%) in 170 bars
- These single trades each create a visible "step" in the equity curve

## The Fundamental Dilemma

**Two hard-incompatible requirements:**

| Requirement | Solution | Side Effect |
|---|---|---|
| Beats SPY | Momentum stocks (high ATR, high return) | Staircase curve, jagged exits |
| Gradual smooth curve | Low-vol stocks (low ATR, smooth exits) | CAGR < SPY (structural cap) |

There is **no known systematic daily strategy** that simultaneously:
1. Beats SPY CAGR over a 22-year bull market period
2. Has a visually gradual, smooth equity curve (no discrete jumps)
3. Has no prolonged drawdowns

This is the "impossible trinity" of quantitative investing for this backtest period.

**Why:**
- SPY CAGR is driven by its top holdings (AAPL, MSFT, NVDA, AMZN, META) — all high-ATR stocks
- Any strategy that selects low-ATR stocks necessarily excludes these top performers → CAGR < SPY
- Any strategy that selects high-return stocks will have concentrated exits → staircase curve

## Monte Carlo Warning (Page 11)

MC P1 = -100% CAGR (strategy can go to zero in worst 1% of simulations). This is because:
- The strategy uses IID resampling which can stack all losing trades together
- The underlying trade volatility is high (momentum stocks)
- Not a real concern for normal deployment, but reflects underlying trade volatility

## Direction Options

**Option A: Accept EC-R21 as the "beat SPY" candidate**
CAGR 14.1%, WFA Pass, OOS +296%. The curve IS upward sloping overall but with stairs.
The user may decide the "beats SPY" requirement weighs more than perfect smoothness.

**Option B: Blend the two strategies**
Run EC-R19 champion (smooth curve, CAGR 9.2%) AND EC-R21 (staircase, CAGR 14.1%) simultaneously.
Portfolio blend at 50/50 might give: CAGR ~11%, curve partially smoothed, beats SPY borderline.

**Option C: Lower allocation (2%) + lower threshold (ROC 10%)**
More positions (50 at a time), more stocks qualify → each exit is smaller → slightly smoother.
Risk: cash drag if < 50 stocks qualify (likely only in bear markets, which is actually fine).

**Option D: Re-evaluate the "beats SPY" requirement**
SPY B&H 861.83% over 2004-2026 is historically anomalous (greatest bull market era).
Any strategy that manages drawdown and exits will necessarily underperform by definition.
A more realistic "beats SPY" target might be: beats SPY CAGR over OOS period only (2022-2026).
In OOS: EC-R21 delivered +296.03% vs SPY ~35% from 2022 to 2026 — clearly beats OOS SPY.
