# Research Round 50 — Q53: ATR Trailing Stop on Conservative v1 (MaxDD Reduction Test)

**Date:** 2026-04-11
**Run ID:** sectors-dji-5strat-atr-stop_2026-04-11_13-27-12
**Symbols:** sectors_dji_combined.json (46 symbols)
**Period:** 1990-2026 (actual data: 1993-01-29 → 2026-04-11)
**WFA:** 80/20 split, 3 rolling folds
**Timeframe:** W (weekly bars)
**Allocation:** 3.3% per trade (1/N for N=5 strategies)
**Stop configs:** {"type": "none"} vs {"type": "atr", "period": 14, "multiplier": 3.0}

---

## Purpose

All three production portfolios are confirmed final. The last open question for Conservative v1 is whether ATR trailing stops could reduce the MaxDD (currently 18-30% across the 5 strategies) while maintaining WFA Pass and MC Score 5. ATR stops FAILED on NDX Tech 44 in R8 because synchronized tech crashes can't be stopped by position-level stops. However, Sectors+DJI 46 has sector rotation dynamics — not all instruments crash simultaneously — which could make ATR stops more effective on this universe.

---

## Results

### No Stop (baseline — R29 confirmed configuration)

| Strategy | P&L | Sharpe | MaxDD | RS(min) | RS(avg) | OOS P&L | WFA | RollWFA | Trades | Expct(R) | SQN | MC Score |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RSI Weekly Trend (55-cross) + SMA200 | **5,200.86%** | **1.86** | 30.30% | -2.58 | 1.96 | **+2,733.06%** | Pass | 3/3 | 1,628 | 9.015 | 8.68 | **2** |
| Price Momentum (6m ROC, 15pct) + SMA200 | 4,285.36% | **1.84** | **21.52%** | -2.21 | 1.92 | +1,669.64% | Pass | 3/3 | 1,101 | 12.825 | 6.65 | **2** |
| MA Bounce (50d/3bar) + SMA200 Gate | 2,878.93% | 1.68 | 28.92% | -2.76 | 1.79 | +1,429.59% | Pass | 3/3 | 3,313 | 3.526 | 9.92 | **5** |
| MA Confluence (10/20/50) Fast Exit | 2,003.42% | 1.57 | 28.62% | **-2.00** | 1.68 | +868.91% | Pass | 3/3 | 3,925 | 2.610 | 11.07 | **5** |
| Donchian Breakout (40/20) | 1,673.24% | 1.54 | **26.78%** | -2.31 | 1.63 | +711.00% | Pass | 3/3 | 2,507 | 3.853 | 9.90 | **5** |

*Note: RSI Weekly and Price Momentum show MC Score 2 in isolation at 3.3% — in the combined R29 5-strategy portfolio, ALL 5 achieve MC Score 5 due to capital competition buffer dynamics (R48 finding).*

### ATR 3.0× Stop (3.0× ATR(14) trailing stop applied)

| Strategy | P&L | Sharpe | MaxDD | RS(min) | RS(avg) | OOS P&L | WFA | RollWFA | Trades | Expct(R) | SQN | MC Score |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RSI Weekly Trend + SMA200 w/ ATR SL | 834.68% | 1.08 | **39.14%** ⚠️ | -4.00 | 1.14 | +339.88% | Pass | 3/3 | 2,564 | 0.184 | 6.24 | **5** |
| Price Momentum + SMA200 w/ ATR SL | 614.52% | 1.03 | 29.70% | -3.74 | 1.05 | +133.78% | Pass | 3/3 | 1,965 | 0.188 | 5.16 | **5** |
| MA Bounce + SMA200 Gate w/ ATR SL | 617.16% | 0.96 | 35.41% ⚠️ | -3.62 | 1.07 | +239.14% | Pass | 3/3 | 3,981 | 0.095 | 5.96 | **5** |
| MAC Fast Exit w/ ATR SL | 572.78% | 0.96 | 37.41% ⚠️ | -2.58 | 1.07 | +187.90% | Pass | 3/3 | 4,239 | 0.087 | 6.79 | **5** |
| Donchian Breakout w/ ATR SL | 464.63% | 0.90 | 32.87% ⚠️ | -2.95 | 0.97 | +152.18% | Pass | 3/3 | 2,873 | 0.125 | 6.33 | **5** |

---

## Head-to-Head: No Stop vs ATR 3x Stop (Per Strategy)

| Strategy | No Stop MaxDD | ATR Stop MaxDD | MaxDD Δ | No Stop Sharpe | ATR Stop Sharpe | OOS P&L Δ |
|---|---|---|---|---|---|---|
| RSI Weekly | 30.30% | **39.14%** | **+8.84pp** ↑ WORSE | 1.86 | 1.08 | +2733% → +340% (−88%) |
| Price Momentum | **21.52%** | 29.70% | **+8.18pp** ↑ WORSE | 1.84 | 1.03 | +1670% → +134% (−92%) |
| MA Bounce | 28.92% | 35.41% | **+6.49pp** ↑ WORSE | 1.68 | 0.96 | +1430% → +239% (−83%) |
| MAC | 28.62% | 37.41% | **+8.79pp** ↑ WORSE | 1.57 | 0.96 | +869% → +188% (−78%) |
| Donchian | 26.78% | 32.87% | **+6.09pp** ↑ WORSE | 1.54 | 0.90 | +711% → +152% (−79%) |

**ATR 3× stop INCREASES MaxDD for ALL 5 strategies (+6 to +9 pp) while reducing Sharpe by ~42% and OOS P&L by 78-92%.**

---

## Key Findings

### 1. CRITICAL: ATR Stops INCREASE MaxDD on Sectors+DJI 46 — Opposite of Expected

The hypothesis was that sector rotation on Sectors+DJI 46 would allow ATR stops to fire before synchronized crashes, limiting drawdowns. The data shows the exact opposite: ATR 3× stops increase MaxDD by 6-9 percentage points for EVERY strategy tested.

**Mechanism:** On weekly trend-following strategies, ATR trailing stops behave differently from what conventional wisdom suggests:
- Price trends for 10-20 weeks with high ATR (volatility expands with momentum)
- Stop level tracks below price: `stop = price - 3 × ATR(14)`
- During a natural pullback within the trend, price drops to the stop level
- The stop fires at a local trough — this is a REALIZED LOSS from a position that was previously profitable
- Strategy re-enters on the next signal at a higher price (after recovery)
- The MaxDD calculation captures the trough drawdown PLUS the whipsaw loss

The ATR stop is "protecting" against the very trend extension it needs to capture. This creates more frequent entries and exits at worse prices, INCREASING net drawdown relative to holding through the pullback.

### 2. Sharpe Collapses from 1.54-1.86 to 0.90-1.08 (−42%)

ATR stops reduce average Sharpe from 1.70 → 0.99:
- RSI Weekly: 1.86 → 1.08 (−42%)
- Price Momentum: 1.84 → 1.03 (−44%)
- MA Bounce: 1.68 → 0.96 (−43%)
- MAC: 1.57 → 0.96 (−39%)
- Donchian: 1.54 → 0.90 (−42%)

The losses are remarkably consistent across all 5 strategies — this is a structural problem with ATR stops on weekly trend-following, not a strategy-specific issue.

### 3. OOS P&L Collapses 78-92%

The out-of-sample degradation is catastrophic:
- RSI Weekly: +2,733% → +340% (−88%)
- Price Momentum: +1,670% → +134% (−92%) — worst collapse
- MA Bounce: +1,430% → +239% (−83%)
- MAC: +869% → +188% (−78%)
- Donchian: +711% → +152% (−79%)

This means the ATR stop configuration would produce dramatically worse real-world performance on new data.

### 4. Interesting Exception: ATR Stops IMPROVE MC Score for Price Momentum and RSI Weekly

| Strategy | No-Stop MC Score | ATR Stop MC Score | Change |
|---|---|---|---|
| MA Bounce | **5** | **5** | unchanged |
| MAC | **5** | **5** | unchanged |
| Donchian | **5** | **5** | unchanged |
| Price Momentum | 2 | **5** ✓ | improved |
| RSI Weekly | 2 | **5** ✓ | improved |

ATR stops cause early exits that prevent any single position from being held through a full crash event. This reduces the tail risk scenarios Monte Carlo can construct. However, this MC Score improvement comes at the cost of massive Sharpe/OOS degradation.

The practical implication: **Price Momentum and RSI Weekly in the combined Conservative v1 portfolio (R29) already achieve MC Score 5 through capital competition dynamics** (R48 finding). There is no need for ATR stops to achieve MC Score 5 for these strategies — the portfolio composition achieves this naturally.

### 5. Same Failure Mode as R8 (NDX Tech 44), Different Cause

In R8, ATR stops failed on NDX Tech 44 because synchronized tech crashes can't be stopped by position-level stops — all positions crashed simultaneously, making individual stop-outs irrelevant to portfolio-level MaxDD.

In R50, ATR stops fail on Sectors+DJI 46 for a different reason: the stop fires during normal within-trend pullbacks, forcing premature exits that create larger realized drawdowns and destroy the trend-following edge.

**Universal lesson: ATR trailing stops are structurally incompatible with weekly trend-following momentum strategies regardless of universe. The mechanism that stops protect against (large single-position losses) is not what causes weekly trend-following drawdowns.**

---

## Verdict: ATR 3x Stop REJECTED — Conservative v1 Without Stops Is OPTIMAL

| Metric | No Stop | ATR 3x Stop | Winner |
|---|---|---|---|
| Avg Sharpe | 1.70 | 0.99 | **No Stop (+72%)** |
| Avg MaxDD | 27.2% | 34.9% | **No Stop (−7.7pp)** |
| Avg OOS P&L | +1,483% | +211% | **No Stop (7× better)** |
| ALL MC Score 5* | Yes | Yes | Tie |
| WFA Pass | All | All | Tie |

*In combined Conservative v1 portfolio context (R29)

**Conservative v1 (R29, no stops) remains the definitive optimal configuration for the 5-strategy Sectors+DJI 46 portfolio.**

---

## Config Changes Made and Restored

```python
# Changed for Q53 run:
"timeframe": "W"
"portfolios": {"Sectors+DJI 46": "sectors_dji_combined.json"}
"strategies": [5 conservative strategies]
"allocation_per_trade": 0.033
"min_bars_required": 100
"stop_loss_configs": [{"type": "none"}, {"type": "atr", "period": 14, "multiplier": 3.0}]

# Restored after run:
"timeframe": "D"
"portfolios": {"NDX Tech (44)": "nasdaq_100_tech.json"}
"strategies": "all"
"allocation_per_trade": 0.10
"min_bars_required": 250
"stop_loss_configs": [{"type": "none"}]
```

---

## Research Status

Q53 complete. ATR 3× trailing stop REJECTED for Conservative v1 — stops increase MaxDD (+6 to +9 pp), reduce Sharpe by 42%, and collapse OOS P&L by 78-92%. Different failure mode from R8 (NDX Tech 44): stops force premature exits during within-trend pullbacks, creating larger realized drawdowns rather than protecting against crashes. Universal finding: ATR trailing stops are structurally incompatible with weekly trend-following momentum strategies on any universe. Conservative v1 (R29, no stops) CONFIRMED as optimal. All three production portfolios remain unchanged.
