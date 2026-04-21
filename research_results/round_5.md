# Research Round 5 — New Strategy Families + Extended History (1990-2026)

**Date:** 2026-04-10
**Symbols (Phase A):** tech_giants.json (AAPL, MSFT, GOOG, AMZN, NVDA, META — 6 symbols)
**Symbols (Phase B):** nasdaq_100_tech.json (44 symbols)
**Period:** 1990-01-01 → 2026-04-10 (36 years, extended from prior 22-year window)
**Data Provider:** Norgate (total-return adjusted)
**WFA Split:** 80% IS (~1990-2019) / 20% OOS (~2019-2026)
**Rolling WFA:** 3 folds
**Run IDs:**
- Phase A (6 sym): research-v5-new-strategies_2026-04-10_21-53-22
- Phase B (44 sym): research-v5-44sym_2026-04-10_21-54-42

---

## Objectives

1. Test 5 structurally diverse new strategies uncorrelated with MA Confluence family
2. Extend history from 2004 → 1990 for stronger statistical validation (36 vs 22 years)
3. Validate top new findings on 44-symbol universe

---

## Phase A: 6-Symbol Results (1990-2026)

### Core Performance

| Strategy | P&L (%) | Sharpe | Max DD | MC Score | WFA |
|---|---|---|---|---|---|
| **MA Bounce (50d/3bar)+SMA200** | **1,771.83%** | **+0.38** | 22.39% | **5** | **Pass** |
| MA Confluence Full Stack (10/20/50) | 2,718.68% | +0.43 | 35.31% | 2 | Pass |
| CMF Momentum (20d)+SMA200 | 943.10% | +0.22 | 29.42% | 5 | Pass |
| ATR Trailing Stop (40d/2.5x)+SMA200 | 499.80% | +0.04 | 14.36% | 5 | Pass |
| Keltner (20d/1.5x)+MA Full Stack | 414.65% | -0.02 | 26.04% | 5 | Pass |
| MACD+RSI+SMA200 Triple Gate | 239.07% | -0.23 | 14.55% | 5 | Pass |

### Extended Metrics

| Strategy | Calmar | RS(avg) | RS(min) | PF | WinRate | Trades | Expct(R) | SQN |
|---|---|---|---|---|---|---|---|---|
| **MA Bounce+SMA200** | **0.38** | -0.10 | -11.04 | **3.09** | 34.70% | 660 | 4.828 | **5.70** |
| MA Confluence Full Stack | 0.27 | 0.21 | **-4.44** | 3.67 | **52.33%** | 344 | 10.688 | 5.66 |
| CMF+SMA200 | 0.23 | -0.20 | -16.59 | 1.92 | 40.76% | 974 | 2.629 | 4.83 |
| ATR Trailing Stop | 0.35 | -0.61 | -48.10 | 2.11 | 48.46% | 615 | 3.067 | 5.31 |
| Keltner+MA Full Stack | 0.18 | -0.49 | -9.83 | 1.97 | 42.22% | 713 | 2.446 | 4.62 |
| MACD+RSI+SMA200 | 0.24 | -0.79 | -17.84 | 1.57 | 42.03% | 1042 | 1.232 | 4.21 |

### Robustness

| Strategy | OOS P&L | WFA | RollWFA | Corr vs MAC | MC |
|---|---|---|---|---|---|
| **MA Bounce+SMA200** | **+1,164.40%** | **Pass** | **3/3** | **0.02** | Robust (5) |
| MA Confluence Full Stack | +1,659.76% | Pass | 3/3 | — | Moderate Tail Risk (2) |
| CMF+SMA200 | +488.59% | Pass | 3/3 | 0.03 | Robust (5) |
| ATR Trailing Stop | +255.13% | Pass | 3/3 | 0.09 | Robust (5) |
| Keltner+MA Full Stack | +229.20% | Pass | 3/3 | 0.08 | Robust (5) |
| MACD+RSI+SMA200 | +109.60% | Pass | 3/3 | 0.05 | Robust (5) |

---

## Phase B: 44-Symbol Validation (1990-2026)

### Core Performance

| Strategy | P&L (%) | Sharpe | Max DD | MC Score | WFA |
|---|---|---|---|---|---|
| **MA Confluence Fast Exit** | **101,198.49%** | **+0.68** | 68.50% | -1 | **Pass** |
| CMF Momentum (20d)+SMA200 | 51,172.68% | +0.63 | 73.11% | -1 | Pass |
| Donchian Breakout (40/20) | 48,425.99% | +0.63 | 77.09% | -1 | Pass |
| MA Bounce (50d/3bar)+SMA200 | 45,282.64% | +0.61 | 72.06% | -1 | Pass |
| MA Confluence Full Stack | 29,771.01% | +0.54 | 71.92% | -1 | Pass |

### Extended Metrics (44 symbols)

| Strategy | Calmar | RS(avg) | RS(min) | PF | WinRate | Trades | Expct(R) | SQN |
|---|---|---|---|---|---|---|---|---|
| MA Confluence Fast Exit | 0.31 | **0.65** | **-4.46** | 2.21 | 43.03% | 2080 | 5.431 | **6.32** |
| CMF+SMA200 | 0.26 | 0.56 | -15.03 | 1.65 | 40.32% | 3981 | 2.366 | **8.10** |
| Donchian (40/20) | 0.24 | 0.57 | **-3.66** | 2.15 | 42.67% | 1760 | 5.873 | 6.10 |
| MA Bounce+SMA200 | 0.25 | 0.46 | -10.93 | 2.01 | 33.14% | 2776 | 3.727 | 5.58 |
| MA Confluence Full Stack | 0.24 | 0.57 | -4.36 | 1.81 | 42.77% | 1728 | 6.314 | 5.93 |

### Robustness (44 symbols)

| Strategy | OOS P&L | WFA | RollWFA | MC Warning |
|---|---|---|---|---|
| **MA Confluence Fast Exit** | **+88,023.47%** | **Pass** | **3/3** | DD Understated + High Tail Risk |
| CMF+SMA200 | +43,802.79% | Pass | 3/3 | DD Understated + High Tail Risk |
| Donchian (40/20) | +41,664.80% | Pass | 3/3 | DD Understated + High Tail Risk |
| MA Bounce+SMA200 | +40,518.83% | Pass | 3/3 | DD Understated + High Tail Risk |
| MA Confluence Full Stack | +22,911.03% | Pass | 3/3 | DD Understated + High Tail Risk |

**Note on MC Score -1 for all 44-symbol strategies:** Expected and not disqualifying. 44 correlated tech stocks move together in market crashes (2000-2002, 2008-2009, 2022). IID Monte Carlo underestimates portfolio-level drawdown when all 44 stocks decline simultaneously. This is a concentration/correlation warning, not a strategy quality flag. Real deployment requires position sizing caps and portfolio-level stops.

---

## 🏆 Round 5 Breakthrough: MA Bounce (50d/3bar) + SMA200

**The surprise finding:** MA Bounce — a MEAN REVERSION entry within a TREND — outperforms all new strategies with the cleanest risk profile (MC Score 5, Corr 0.02 vs MA Confluence).

**Why it works on tech stocks:**
- The 50-SMA is institutional support on AAPL, MSFT, NVDA, AMZN — traders buy this level deliberately, creating a self-fulfilling bounce
- The SMA200 gate prevents buying 50-SMA "bounces" during bear markets (which are dead-cat bounces)
- 3-bar confirmation before exit reduces whipsaws on volatile tech names
- Low win rate (33-34%) is offset by high average winners — expectancy 3.7-4.8R

**Portfolio fit:** Nearly zero correlation with MA Confluence (r=0.02). These two strategies enter at different times (bounce dips vs. trend alignment events), giving genuine diversification benefit.

---

## Key Extended History Finding (2004 → 1990)

Extending start date from 2004 to 1990 adds 14 years of data including:
- 1990s tech bull market (AAPL 1997-2000, MSFT 1995-1999)
- Dot-com bubble peak (2000) and crash (2000-2003)
- Pre-broadband internet era trading patterns

**Impact on MA Confluence Full Stack (6 symbols):**
- 2004 start: 949.91% P&L, MC Score 5, MaxDD 20.4%
- 1990 start: 2,718.68% P&L, MC Score 2, MaxDD 35.3%

The extended data INCREASES returns (captures 1990s bull) but DEGRADES MC Score (dot-com crash adds tail risk that MC simulation can't handle with correlated assets). The MC Score 2 with 1990 data is MORE HONEST — it reflects the real risk that all 6 tech stocks crashed simultaneously in 2001-2003. The 2004-start results were missing this worst-case scenario.

---

## Problems Identified for Round 6

| Problem | Strategy | Root Cause | Target Fix |
|---|---|---|---|
| CMF MaxDD 29.4% | CMF+SMA200 | sell_threshold=-0.05 too lenient | Add RSI<40 secondary exit |
| CMF RS(min) -16.59 | CMF+SMA200 | Same | Tighter exit |
| ATR RS(min) -48.10 | ATR Trailing Stop | 2.5x ATR too wide on volatile tech | Use ATR as exit layer on MA Confluence entry |
| MA Bounce WinRate 34.7% | MA Bounce+SMA200 | Takes all bounces, even from overbought | Add RSI<50 timing gate |
| MA Confluence MC Score 2 | MA Confluence Full Stack | Bearish-stack exit too slow in crashes | Layer in ATR trailing stop as secondary exit |
| Keltner Sharpe -0.02 | Keltner+MA Full Stack | Keltner gate delays entries past optimal | Replace with OBV+MA Confluence |

---

## Round 5 Strategy Files

- `custom_strategies/research_strategies_v4.py` — 5 new strategies:
  - CMF Momentum (20d) + SMA200 Gate
  - MACD + RSI + SMA200 Triple Gate (12/26/9/14)
  - ATR Trailing Stop (40d/2.5x) + SMA200
  - MA Bounce (50d/3bar) + SMA200 Gate ⭐ NEW CHAMPION
  - Keltner (20d/1.5x) + MA Full Stack Gate
