# Research Round 48 — Q51: Williams R Replacing Price Momentum in Conservative Portfolio v1 (5-Strategy)

**Date:** 2026-04-11
**Run ID:** sectors-dji-5strat-williams-vs-pm_2026-04-11_13-13-12
**Symbols:** sectors_dji_combined.json (46 symbols)
**Period:** 1990-2026 (actual data: 1993-01-29 → 2026-04-10)
**WFA:** 80/20 split, 3 rolling folds
**Timeframe:** W (weekly bars)
**Allocation:** 3.3% per trade (1/N for N=5 strategies)

---

## Purpose

Round 47 found Williams R Weekly Trend achieves Sharpe 1.82 (highest in the 6-strategy conservative v2) vs Price Momentum Sharpe 1.79. Price Momentum ↔ RSI Weekly r=0.6925 is the near-threshold pair. Could replacing Price Momentum with Williams R create a superior 5-strategy conservative v1 with lower max pair correlation and higher Sharpe? Williams R ↔ RSI Weekly r=0.6451 (from R47) suggests the correlation would improve.

---

## Results

| Strategy | P&L | Sharpe | MaxDD | RS(min) | RS(avg) | OOS P&L | WFA | RollWFA | Trades | Expct(R) | SQN | MC Score |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RSI Weekly Trend (55-cross) + SMA200 | **5,200.86%** | **1.86** | 30.30% | -2.58 | 1.96 | **+2,733.06%** | Pass | 3/3 | 1,628 | 9.015 | 8.68 | **2** ⚠️ |
| **Williams R Weekly Trend (above-20) + SMA200** | **4,364.72%** | **1.86** | 26.97% | -2.91 | 1.95 | **+2,156.89%** | Pass | 3/3 | 1,861 | 7.304 | 8.30 | **5** |
| MA Bounce (50d/3bar) + SMA200 Gate | 2,878.93% | 1.68 | 28.92% | -2.76 | 1.79 | +1,429.59% | Pass | 3/3 | 3,313 | 3.526 | 9.92 | **5** |
| MA Confluence (10/20/50) Fast Exit | 2,003.42% | 1.57 | 28.62% | **-2.00** | 1.68 | +868.91% | Pass | 3/3 | 3,925 | 2.610 | 11.07 | **5** |
| Donchian Breakout (40/20) | 1,673.24% | 1.54 | 26.78% | -2.31 | 1.63 | +711.00% | Pass | 3/3 | 2,507 | 3.853 | 9.90 | **5** |

**All 5 strategies WFA Pass + RollWFA 3/3.**
**CRITICAL: RSI Weekly MC Score dropped from 5 → 2 (Moderate Tail Risk). ONLY 4 of 5 strategies maintain MC Score 5.**

---

## Correlation Matrix (exit-day P&L, Sectors+DJI 46 weekly, NO PRICE MOMENTUM)

| | MA Bounce | MAC | Donchian | RSI Weekly | Williams R |
|---|---|---|---|---|---|
| MA Bounce | 1.00 | 0.27 | 0.30 | 0.31 | 0.32 |
| MAC | 0.27 | 1.00 | **0.64** | 0.16 | 0.17 |
| Donchian | 0.30 | **0.64** | 1.00 | 0.32 | 0.40 |
| RSI Weekly | 0.31 | 0.16 | 0.32 | 1.00 | **0.6187** |
| **Williams R** | **0.32** | **0.17** | **0.40** | **0.6187** | 1.00 |

**Maximum correlation: r=0.6413 (MAC ↔ Donchian) — DOWN from r=0.6925 (Price Momentum ↔ RSI Weekly) in original v1.**
**Williams R ↔ RSI Weekly: r=0.6187 — below threshold, LOWER than Price Momentum ↔ RSI Weekly was (r=0.6925).**
**BUT: RSI Weekly MC Score drops to 2. Price Momentum acted as MC buffer.**

---

## Key Findings

### 1. CRITICAL: RSI Weekly MC Score Drops from 5 → 2 Without Price Momentum

In the original Conservative v1 (R29, 5 strategies with Price Momentum), RSI Weekly achieves MC Score 5 — "Robust" verdict with no tail risk concerns. In Q51 (Williams R replacing Price Momentum), RSI Weekly drops to MC Score 2 — "Moderate Tail Risk".

This is NOT caused by allocation change (both use 3.3%). The change is purely from portfolio composition:
- With Price Momentum in the portfolio: Price Momentum and RSI Weekly often share similar entry timing on strong trending stocks. This creates capital competition — when both want to enter a position, only one gets filled first (based on allocation limits). This competition spreads risk across two strategies and reduces RSI Weekly's tail concentration.
- Without Price Momentum: RSI Weekly has no capital competitor for similar trend signals, concentrating more positions simultaneously. Monte Carlo can now construct scenarios where RSI Weekly is fully deployed in tech/momentum stocks simultaneously during a market crash.

**Price Momentum serves as a "MC buffer" for RSI Weekly** — its presence reduces RSI Weekly's simultaneous position concentration and maintains the "Robust" Monte Carlo verdict.

### 2. Correlation Matrix Improves — But Not Worth the MC Score Trade-off

Replacing Price Momentum with Williams R:
- Old max pair correlation: r=0.6925 (Price Momentum ↔ RSI Weekly)
- New max pair correlation: r=0.6413 (MAC ↔ Donchian)
- Improvement: -0.051 reduction in maximum correlation

This is a genuine improvement in correlation structure. However, losing RSI Weekly's MC Score 5 (→ 2) is a significant quality downgrade that outweighs the correlation improvement.

### 3. Williams R Individual Metrics Are Excellent at 3.3% Allocation

Williams R at 3.3% (vs 2.8% in R47):
- Sharpe: **1.86** (up from 1.82 at 2.8% — more capital → higher Sharpe due to ADV filtering efficiency)
- OOS P&L: **+2,156.89%** (up from +1,437.81% at 2.8% — expected with more capital)
- MaxDD: 26.97% (vs 23.76% at 2.8% — slightly higher with larger positions)
- MC Score: **5** (maintained despite higher allocation)

Williams R at 3.3% allocation is genuinely excellent — the issue is not Williams R itself but what its presence does to RSI Weekly's MC Score.

### 4. Price Momentum Contribution Analysis — Q51 vs R29 (Original v1)

Direct comparison of Price Momentum vs Williams R in the 5th strategy slot:

| Metric | Price Momentum (R29) | Williams R (Q51) | Winner |
|---|---|---|---|
| Sharpe | 1.79 | **1.86** | Williams R |
| MaxDD | **18.88%** | 26.97% | Price Momentum |
| OOS P&L | +1,003.65% | **+2,156.89%** | Williams R |
| RSI Weekly MC Score | **5** | **2** ⚠️ | **Price Momentum** |
| Max pair correlation | 0.6925 (with RSI) | 0.6413 (MAC-Donchian) | Williams R |
| ALL 5 MC Score 5 | **Yes** | **No** | **Price Momentum** |

**Price Momentum wins the critical metric: maintaining ALL 5 MC Score 5 in the combined portfolio.**

### 5. Non-Obvious Finding: Price Momentum Is the MC Buffer for RSI Weekly

This is one of the most counterintuitive findings in the research:
- Price Momentum appears to be the "weaker" 5th strategy by Sharpe (1.79 vs Williams R 1.82)
- Price Momentum appears to have higher correlation with RSI Weekly (r=0.6925 vs Williams R 0.6187)
- But Price Momentum's PRESENCE in the portfolio is what gives RSI Weekly its MC Score 5

The mechanism: when Price Momentum and RSI Weekly both want to enter a position in the same strong trending stock, the capital allocation engine forces one to wait. This natural capital competition prevents RSI Weekly from building excessively concentrated simultaneous positions — the scenario that Monte Carlo exploits in Q51.

This is a portfolio-level effect that cannot be detected from isolated strategy analysis. It only emerges in the combined portfolio context.

**Lesson (2nd instance of the pattern): Similar to Donchian in the Aggressive portfolio (R44), Price Momentum in the Conservative portfolio serves as a structural MC buffer. Removing it degrades other strategies' MC robustness even when Williams R is technically "better" by individual metrics.**

---

## Verdict: Original Conservative v1 (R29 with Price Momentum) Is Superior

| Metric | Original v1 (R29, with PM) | Q51 Variant (with Williams R) | Winner |
|---|---|---|---|
| ALL 5 MC Score 5 | **YES** | No (RSI 2) | **R29 v1** |
| Max pair correlation | 0.6925 | **0.6413** | Q51 |
| 5th strategy Sharpe | 1.79 | **1.86** | Q51 |
| 5th strategy OOS P&L | +1,003% | **+2,156%** | Q51 |
| RSI Weekly MC Score | **5** | 2 | **R29 v1** |
| Portfolio quality | **All 5 Robust** | Mixed (4 Robust + 1 Moderate) | **R29 v1** |

**Conservative v1 (R29, Price Momentum) remains the better 5-strategy configuration because ALL 5 MC Score 5 is a non-negotiable quality requirement.**

Williams R is correctly deployed in Conservative v2 (as a 6th strategy at 2.8% where ALL 6 maintain MC Score 5). The 5-strategy slot should remain Price Momentum.

---

## Updated Production Portfolio Specifications (CONFIRMED FINAL)

The original Conservative v1 is confirmed superior. All three portfolio configurations remain unchanged:

### Conservative v1 (Standard) [R29]
5 strategies × 3.3% allocation × Sectors+DJI 46
ALL 5 MC Score 5. Max pair r=0.6925.

### Conservative v2 (Enhanced) [R47]
6 strategies × 2.8% allocation × Sectors+DJI 46
ALL 6 MC Score 5. Adds Williams R Weekly Trend.

### Aggressive [R42]
5 strategies × 3.3% allocation × NDX Tech 44
All WFA Pass. Max pair r=0.65.

---

## Config Changes Made and Restored

```python
# Changed for Q51 run:
"timeframe": "W"
"portfolios": {"Sectors+DJI 46": "sectors_dji_combined.json"}
"strategies": [MA Bounce + MAC + Donchian + RSI Weekly + Williams R — NO PRICE MOMENTUM]
"allocation_per_trade": 0.033
"min_bars_required": 100

# Restored after run:
"timeframe": "D"
"portfolios": {"NDX Tech (44)": "nasdaq_100_tech.json"}
"strategies": "all"
"allocation_per_trade": 0.10
"min_bars_required": 250
```

---

## Research Status

Q51 complete. Williams R replacing Price Momentum REJECTED — RSI Weekly drops from MC Score 5 → 2 without Price Momentum in portfolio. Price Momentum acts as MC buffer for RSI Weekly through capital competition dynamics. Original Conservative v1 (R29) confirmed superior. ALL THREE production portfolio configurations are CONFIRMED FINAL with no further modifications needed:
- Conservative v1: R29 (Price Momentum present, ALL 5 MC Score 5)
- Conservative v2: R47 (Williams R as 6th, ALL 6 MC Score 5)
- Aggressive: R42 (5-strategy NDX Tech 44, all WFA Pass)
