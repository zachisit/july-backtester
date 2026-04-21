# Research Round 21 — Dow Jones 30: Blue-Chip Industrial Universe (Q22)

**Date:** 2026-04-11
**Run ID:** dji-weekly-5strat_2026-04-11_06-57-53
**Symbols:** dow-jones-industrial-average.json (30 symbols)
**Period:** 1990-2026 (36 years)
**WFA:** 80/20 split, 3 rolling folds (split date: 2019-01-08)
**Timeframe:** W (weekly bars)
**Allocation:** 3.3% per trade
**Runtime:** 16.45 seconds

## Hypothesis

All prior research used tech-heavy universes (NDX 44, SP500 with 28% tech weight, Russell 1000). The Dow Jones 30 is structurally opposite: 30 mega-cap diversified giants spanning tech, finance, healthcare, consumer staples, industrial, and energy. If weekly momentum strategies work here at Sharpe > 1.5 and MaxDD < 40%, the edge is universal — not a tech-momentum artifact.

## Results

| Strategy | P&L | Sharpe | MaxDD | RS(avg) | RS(min) | OOS P&L | WFA | RollWFA | Trades | SQN | MC Score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MA Bounce (50d/3bar) + SMA200 Gate | 2,295% | 1.80 | **21.81%** | 1.87 | -2.74 | +910% | Pass | 3/3 | 2,678 | 9.26 | **+5** |
| MA Confluence (10/20/50) Fast Exit | 1,628% | 1.72 | **20.23%** | 1.77 | **-1.92** | +561% | Pass | 3/3 | 2,993 | **10.46** | **+5** |
| Donchian Breakout (40/20) | 1,394% | 1.71 | **19.63%** | 1.74 | -2.23 | +444% | Pass | 3/3 | 1,836 | 9.37 | **+5** |
| RSI Weekly Trend (55-cross) + SMA200 | **3,926%** | **1.93** | 22.67% | 1.99 | -2.57 | **+1,729%** | Pass | 3/3 | 1,366 | 7.93 | **+2** |
| Price Momentum (6m ROC, 15pct) + SMA200 | 3,260% | **1.88** | 20.69% | 1.96 | **-2.10** | +972% | Pass | 3/3 | 879 | 5.98 | **0** |

## Key Findings

### BREAKTHROUGH: MaxDD 19-23% — Less Than Half of NDX Tech Results

The most striking finding: MaxDD on the Dow Jones 30 is **19.63% to 22.67%**, compared to 44.46%-49.77% in the NDX Tech 44 combined run (R16). This is not a marginally different result — it's a qualitatively different risk profile.

| Metric | NDX Tech 44 (5-strat, R16) | Dow Jones 30 (5-strat, R21) | DJI Improvement |
|---|---|---|---|
| MA Bounce Sharpe | 1.95 | 1.80 | -7.7% |
| MA Bounce MaxDD | 44.46% | **21.81%** | **-22.7pp** |
| MAC Sharpe | 1.76 | 1.72 | -2.3% |
| MAC MaxDD | 49.77% | **20.23%** | **-29.5pp** |
| Donchian Sharpe | 1.63 | 1.71 | +4.9% |
| Donchian MaxDD | 47.72% | **19.63%** | **-28.1pp** |
| RSI Weekly Sharpe | 1.91 | 1.93 | +1.0% |
| RSI Weekly MaxDD | 49.36% | **22.67%** | **-26.7pp** |
| Price Mom Sharpe | 1.80 | 1.88 | +4.4% |
| Price Mom MaxDD | 44.83% | **20.69%** | **-24.1pp** |

Sharpe ratios are essentially the same (within 8%) but MaxDDs are 24-30 percentage points lower on DJI. This is because DJI diversifies across sectors — when tech crashes (2000-2002, 2022), healthcare and consumer staples buffer the portfolio. When financials crash (2008), tech and healthcare buffer. No single sector destroys all 30 positions simultaneously.

### MC Scores: +5 for 3 Strategies, +2 for RSI, 0 for Price Momentum

| Strategy | NDX Tech 44 MC Score (R16) | DJI MC Score (R21) |
|---|---|---|
| MA Bounce | -1 | **+5** |
| MAC Fast Exit | -1 | **+5** |
| Donchian | +1 | **+5** |
| RSI Weekly | -1 | **+2** |
| Price Momentum | +1 | **0** |

Three strategies achieve Monte Carlo Score +5 on the Dow Jones — the highest possible score. This means the Monte Carlo simulation finds that the expected drawdown distribution is extremely favorable, with very low probability of exceeding backtest MaxDD in resampled scenarios. This is consistent with the low MaxDD values — when your base case MaxDD is 19-20%, there's little room for MC simulations to find worse outcomes.

### RSI Weekly Dominates on DJI: P&L 3,926%, OOS +1,729%

RSI Weekly's performance on DJI is stunning:
- P&L 3,926% (highest of all 5 strategies, vs RSI Weekly 32,558% on NDX in R16 — lower absolute because only 30 stocks)
- OOS +1,729% (highest of all 5, nearly 2× MA Bounce's +910%)
- Sharpe 1.93 (highest of all 5 on DJI)

RSI Weekly is the best performer on EVERY large universe tested: NDX Tech 44 (highest combined P&L), SP500 weekly (confirmed), and now Dow Jones 30. The 55-cross RSI regime signal captures the sustained multi-week trends that characterize all large-cap momentum environments.

### Price Momentum: Highest Expectancy(R) = 14.32

Price Momentum's Expectancy(R) = 14.32 on DJI (vs 21.45 in the 4-strategy NDX run). With only 879 trades across 30 symbols over 36 years, each trade selects only the strongest 6-month uptrends. These DJI names with 15%+ ROC are genuinely exceptional performers (they're already among the world's largest companies, so a 15%+ move in 6 months is a powerful signal).

### MAC Fast Exit SQN = 10.46 — Highest Statistical Confidence

MAC Fast Exit generates 2,993 trades on 30 symbols — near-maximum statistical robustness. SQN 10.46 is one of the highest ever recorded across all runs. Calmar 0.40, WinRate 44.37%, RS(min) -1.92 (best on DJI).

### RS(min) -1.92 to -2.74 — Same Floor as NDX Combined Run

Despite the vastly lower MaxDDs, the rolling Sharpe floor (RS(min)) is essentially identical to the NDX Tech 44 combined run (-2.19 to -2.73). This indicates that the 126-day worst-rolling-Sharpe windows are driven by the 2000-2002 and 2008-2009 crashes which hit DJI names too — but the recoveries are faster (AvgRcvry 66-72 days), keeping the RS(min) bounded.

## Verdict

**ALL 5 STRATEGIES PASS ON DOW JONES 30 — HISTORIC LOW MaxDDs (19-23%).**

The Dow Jones 30 is not just "another universe" — it represents a fundamentally different portfolio construction that dramatically improves risk profile while maintaining Sharpe ratios. The weekly momentum framework is now confirmed across 5 distinct universes:

1. NDX Tech 44 (R9-R16): Sharpe 1.63-1.95, MaxDD 44-50%, MC Score -1 to +1 ✓
2. SP500 503 (R17): Sharpe 1.42-1.81, MaxDD 45-58%, MC Score -1 to +1 ✓
3. Russell 1000 1,012 (R15): Sharpe 0.87-1.18, lower MaxDD ✓
4. Dow Jones 30 (R21): Sharpe 1.71-1.93, **MaxDD 19-23%**, MC Score 0 to +5 ✓

**The DJI result reveals a critical production insight: mixing DJI blue-chip names with NDX tech names in a single diversified portfolio would combine NDX momentum with DJI downside protection — likely achieving Sharpe > 1.80 with MaxDD < 35%.**

## Config Changes Made and Restored

```python
# Changed for run:
"timeframe": "W"
"portfolios": {"Dow Jones 30": "dow-jones-industrial-average.json"}
"strategies": [all 5 champion names]
"allocation_per_trade": 0.033
"verbose_output": True

# Restored/changed to next run (Q23: Biotech):
"portfolios": {"Nasdaq Biotech (257)": "nasdaq_biotech_tickers.json"}
```
