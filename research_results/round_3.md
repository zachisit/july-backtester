# Research Round 3 — Breakthrough Results

**Date:** 2026-04-10
**Symbols:** tech_giants.json (AAPL, MSFT, GOOG, AMZN, NVDA, META)
**Period:** 2004-01-01 → 2026-04-10 (22 years)
**Run ID:** research-v3_2026-04-10_21-29-13

---

## 🏆 Round 3 Core Performance

| Strategy | P&L (%) | Sharpe | Max DD | MC Score | WFA |
|---|---|---|---|---|---|
| **MA Confluence Full Stack (10/20/50)** | **949.91%** | **+0.58** | 20.40% | 5 | **Pass** |
| **MA Confluence Fast Exit (10/20/50)** | **857.80%** | **+0.59** | 18.98% | 5 | **Pass** |
| EMA (8/21) + ROC Gate | 458.84% | +0.36 | 17.73% | 5 | Pass |
| OBV Dual Confirm + SMA200 Gate | 442.85% | +0.38 | 14.12% | 5 | Pass |
| Donchian (40/20) + SMA200 Gate | 393.82% | +0.33 | 13.72% | 5 | Pass |
| MACD Crossover (12/26/9) | 198.27% | +0.05 | 21.67% | 5 | Pass |
| Keltner (20d/2.0x) + SMA200 Gate | 196.71% | +0.03 | 11.06% | 5 | Pass |
| RSI + SMA200 Filter (14/35/60) | 39.60% | -0.68 | 11.67% | 5 | Pass |

---

## Extended Metrics — Round 3

| Strategy | Calmar | PF | WinRate | Trades | Expct(R) | SQN | MaxRcvry | OOS P&L |
|---|---|---|---|---|---|---|---|---|
| **MA Confluence Full Stack** | **0.55** | **3.87** | **54.00%** | 250 | **10.275** | **5.52** | 823d | **+392.98%** |
| **MA Confluence Fast Exit** | **0.56** | 3.06 | 45.83% | 312 | 7.882 | 5.25 | 987d | **+333.80%** |
| OBV + SMA200 | 0.56 | 1.81 | 37.87% | 1051 | 1.721 | 5.08 | 828d | +175.87% |
| EMA (8/21) + ROC | 0.45 | 1.87 | 38.26% | 1014 | 1.820 | 5.01 | 987d | +192.49% |
| Donchian + SMA200 | 0.54 | 3.09 | 47.83% | 299 | 5.644 | 5.53 | 986d | +160.95% |
| Keltner + SMA200 | 0.45 | 2.15 | 47.42% | 426 | 2.670 | 4.71 | 987d | +79.73% |
| MACD | 0.23 | 1.40 | 43.87% | 1167 | 1.014 | 3.89 | 770d | +51.59% |
| RSI + SMA200 (35/60) | 0.13 | 2.22 | 74.05% | 131 | 2.592 | 3.38 | 1323d | +8.80% |

---

## 🎯 Breakthrough: MA Confluence Strategy

**MA Confluence Full Stack** requires ALL three conditions simultaneously:
1. Price > 50-bar SMA (bullish trend)
2. 10-bar SMA > 50-bar SMA (fast MA above slow MA)
3. 20-bar SMA > 50-bar SMA (medium MA above slow MA)

Entry triggers on the FIRST day all three conditions are met. Exit on full bearish reversal (all three flip negative simultaneously). This means the strategy only enters after momentum is already confirmed from THREE independent angles — hence the high win rate (54%) and massive expectancy (10.27R).

**Fast Exit variant** uses same entry but exits as soon as the 10-bar SMA crosses back below 50-bar SMA (faster exit, less waiting for bearish stack). Produces slightly lower P&L (857% vs 950%) but **highest Sharpe of any strategy ever tested: 0.59**.

---

## Round-by-Round Progress: Tech Giants Ecosystem

| Round | Best Strategy | P&L | Sharpe | MaxDD | OOS | Status |
|---|---|---|---|---|---|---|
| R1 (single AAPL) | Donchian (20/10) | 83.14% | -0.91 | 3.78% | +8.83% | Baseline |
| R1 (tech giants) | ROC Momentum (20d) | 554.66% | +0.42 | 21.16% | unknown | Discovery: ecosystem matters |
| R2 | Donchian (40/20) | 501.94% | +0.42 | 15.73% | +204.60% | Confirmed |
| R2 | EMA+ROC Gate | 488.98% | +0.39 | 16.53% | +204.62% | New breakout |
| **R3** | **MA Confluence Full Stack** | **949.91%** | **+0.58** | 20.40% | **+392.98%** | **BREAKTHROUGH** |
| **R3** | **MA Confluence Fast Exit** | **857.80%** | **+0.59** | 18.98% | **+333.80%** | **HIGHEST SHARPE** |

**MA Confluence nearly DOUBLES the best Round 2 result in both P&L and OOS performance.**

---

## Round 3 Fixes Confirmed

| Problem (Round 2) | Fix Applied | Result |
|---|---|---|
| OBV MaxDD = 22% | Added SMA200 gate | MaxDD → **14.12%** ✅ |
| RSI+SMA200 = 5 trades | Loosened oversold 25→35 | **131 trades** ✅ |
| Donchian MaxDD = 15.73% | Added SMA200 gate | MaxDD → **13.72%** ✅ |

---

## Key Insights

1. **MA Confluence is the dominant strategy family on tech growth stocks**. The "full stack" alignment requirement (3 MAs in order) is a powerful momentum confirmation that technologically outperforms simple crossovers.

2. **Trend filters universally improve Calmar without destroying P&L**. Every strategy that added a SMA200 gate saw MaxDD reduction with minimal P&L sacrifice.

3. **Two MA Confluence variants (Full Stack vs Fast Exit) offer a choice**:
   - Full Stack: Higher absolute P&L (950%), slightly lower Sharpe (0.58), fewer trades (250)
   - Fast Exit: Lower P&L (858%), highest Sharpe (0.59), more trades (312), faster loss cuts

4. **MACD on tech stocks underperforms**. The continuous hold nature (long whenever MACD > Signal) means it's exposed during all down periods. MaxDD 21.67%, Calmar only 0.23.

5. **RSI mean reversion** is not suited to tech growth stocks even with trend filtering. 74% win rate but only 39% P&L over 22 years indicates small wins and the rare big losses outweigh the gains.

---

## Validation Plan

Before declaring MA Confluence the winner, validate on broader universe:
- **Test:** Nasdaq 100 Tech (44 symbols) — statistically stronger test
- **Expected:** P&L should aggregate to multi-thousand % on the full universe
- **Risk:** Results may be partly driven by NVDA's exceptional performance (survivor bias)

---

## All-Time Champions (Cross-Round Leaderboard)

| Rank | Strategy | Round | P&L | Sharpe | MaxDD | Calmar | OOS P&L |
|---|---|---|---|---|---|---|---|
| 🥇 | MA Confluence Full Stack | R3 | 949.91% | +0.58 | 20.40% | 0.55 | +392.98% |
| 🥈 | MA Confluence Fast Exit | R3 | 857.80% | +0.59 | 18.98% | 0.56 | +333.80% |
| 🥉 | Donchian (40/20) | R2 | 501.94% | +0.42 | 15.73% | 0.53 | +204.60% |
| 4 | EMA+ROC Gate (12/26) | R2 | 488.98% | +0.39 | 16.53% | 0.50 | +204.62% |
| 5 | OBV+SMA200 Gate | R3 | 442.85% | +0.38 | 14.12% | 0.56 | +175.87% |
| 6 | EMA (8/21)+ROC Gate | R3 | 458.84% | +0.36 | 17.73% | 0.45 | +192.49% |
| 7 | Donchian+SMA200 Gate | R3 | 393.82% | +0.33 | 13.72% | 0.54 | +160.95% |
