# Research Round 43 — Q46: BB Weekly Breakout in 6-Strategy Combined Portfolio on NDX Tech 44

**Date:** 2026-04-11
**Run ID:** ndx44-6strat-bb-breakout_2026-04-11_12-47-53
**Symbols:** nasdaq_100_tech.json (44 symbols)
**Period:** 1990-2026 (actual data: 1993-01-29 → 2026-04-10)
**WFA:** 80/20 split, 3 rolling folds
**Timeframe:** W (weekly bars)
**Allocation:** 2.8% per trade (1/N for N=6 strategies)

---

## Purpose

Round 42 confirmed the optimized 5-strategy NDX Tech 44 portfolio (MA Bounce + MAC + Donchian + RSI Weekly + Rel Mom at 3.3%). Donchian Breakout is the weakest strategy by Sharpe (1.63) and OOS P&L (+4,282%). BB Weekly Breakout (20w/2std) + SMA200 was already confirmed on the 6-symbol gate (R30 series) and on NDX Tech 44 in isolation — it has MC Score 5 in isolation. This run tests whether BB Breakout can serve as an additive 6th strategy (or whether it becomes a replacement candidate for Donchian) by measuring its exit-day correlations with the 5 confirmed champions.

---

## Results

| Strategy | P&L | Sharpe | MaxDD | RS(min) | RS(avg) | OOS P&L | WFA | RollWFA | Trades | Expct(R) | SQN | MC Score |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| RSI Weekly Trend (55-cross) + SMA200 | **20,699.60%** | **1.87** | 46.14% | -2.76 | 1.88 | **+17,529.28%** | Pass | 3/3 | 1,203 | 20.882 | 8.07 | 1 |
| MA Bounce (50d/3bar) + SMA200 Gate | 12,084.43% | **1.89** | **40.41%** | -2.72 | 1.91 | +9,612.35% | Pass | 3/3 | 2,342 | 8.653 | 8.23 | -1 |
| MA Confluence (10/20/50) Fast Exit | 6,134.29% | 1.69 | 45.16% | **-2.26** | 1.83 | +4,023.43% | Pass | 3/3 | 2,918 | 5.781 | 7.64 | 1 |
| Donchian Breakout (40/20) | 3,795.77% | 1.56 | 43.68% | -2.53 | 1.70 | +2,255.84% | Pass | 3/3 | 1,790 | 8.411 | 7.06 | 2 |
| **BB Weekly Breakout (20w/2std) + SMA200** | **3,198.16%** | **1.64** | **34.27%** | **-3.89** | 1.67 | **+1,952.15%** | Pass | 3/3 | 1,028 | 10.241 | 5.93 | **5** |
| Relative Momentum (13w vs SPY) + SMA200 | 2,584.78% | 1.70 | 29.46% | **-2.81** | 1.66 | +1,776.97% | Pass | 3/3 | **969** | 13.993 | 6.29 | **5** |

**ALL 6 strategies WFA Pass + RollWFA 3/3.**

---

## Correlation Matrix (exit-day P&L, NDX Tech 44 weekly)

| | MA Bounce | MAC | Donchian | RSI Weekly | Rel Mom | BB Breakout |
|---|---|---|---|---|---|---|
| MA Bounce | 1.00 | 0.10 | 0.29 | 0.56 | 0.60 | 0.6597 |
| MAC | 0.10 | 1.00 | 0.40 | 0.04 | 0.08 | 0.1264 |
| Donchian | 0.29 | 0.40 | 1.00 | 0.22 | 0.35 | 0.4305 |
| RSI Weekly | 0.56 | 0.04 | 0.22 | 1.00 | 0.57 | **0.7049** ⚠️ |
| Rel Mom | 0.60 | 0.08 | 0.35 | 0.57 | 1.00 | 0.6924 |
| **BB Breakout** | **0.6597** | **0.1264** | **0.4305** | **0.7049** ⚠️ | **0.6924** | 1.00 |

**ALERT: BB Breakout ↔ RSI Weekly r=0.7049** — exceeds the research protocol 0.70 correlation threshold.
**Near-threshold: BB Breakout ↔ Rel Mom r=0.6924** — below 0.70 but approaching the boundary.

---

## Key Findings

### 1. BB Breakout MC Score 5 — Same as Rel Mom, Unprecedented Second Strategy

BB Breakout achieves MC Score 5 on NDX Tech 44 in the 6-strategy combined context. This was also observed in isolation (confirmed in earlier rounds). The long-duration hold pattern of BB Breakout (entries on upper Bollinger Band breakouts tend to be held until mean reversion triggers or SMA200 exits) makes it structurally resistant to Monte Carlo crash scenarios, similar to Relative Momentum.

Two strategies now achieve MC Score 5 simultaneously in the same combined portfolio — Relative Momentum and BB Breakout. This is the first time two MC Score 5 strategies coexist in a single combined run.

### 2. BB Breakout MaxDD 34.27% — Second Best in Portfolio After Rel Mom

BB Breakout's MaxDD (34.27%) is higher than Rel Mom (29.46%) but dramatically lower than RSI Weekly (46.14%) or MAC (45.16%). This is consistent with the Bollinger Band exit mechanics providing a natural drawdown control — the strategy exits when price reverts below the band midpoint.

### 3. CRITICAL: BB ↔ RSI Weekly r=0.7049 — Above Research Protocol Threshold

The exit-day correlation between BB Breakout and RSI Weekly is **0.7049**, which exceeds the 0.70 research protocol threshold. Both strategies fire on similar uptrend momentum triggers on NDX tech stocks:
- RSI Weekly: RSI(14w) crosses above 55 + SMA200 filter
- BB Breakout: price closes above 2-std upper Bollinger Band (20w) + SMA200 filter

Both signals trigger at the same moment: when a NDX tech stock makes a new breakout high on high momentum. On concentrated tech (NVDA, AMZN, META), the momentum and the Bollinger Band breakout are nearly synonymous events.

**Implication: BB Breakout and RSI Weekly should NOT coexist in the same 6-strategy NDX Tech 44 portfolio without replacement logic.**

### 4. BB Breakout ↔ Rel Mom r=0.6924 — Near Threshold But Below

BB Breakout ↔ Rel Mom (r=0.6924) is near the 0.70 threshold but technically below it. In a portfolio where RSI Weekly is dropped, running BB Breakout + Rel Mom would be acceptable under the research protocol (both below 0.70 with each other), but the near-threshold value deserves monitoring.

### 5. BB Breakout vs Donchian — BB is Superior on Every Metric

Comparing BB Breakout and Donchian directly:

| Metric | Donchian | BB Breakout | Delta |
|---|---|---|---|
| Sharpe | 1.56 | **1.64** | +0.08 |
| MaxDD | 43.68% | **34.27%** | **-9.41pp** |
| RS(min) | -2.53 | -3.89 | -1.36 (worse) |
| OOS P&L | +2,255.84% | +1,952.15% | -303pp |
| MC Score | 2 | **5** | **+3** |
| Trades | 1,790 | 1,028 | -762 (fewer) |
| Correlation with RSI Weekly | 0.22 | 0.7049 ⚠️ | Much higher |

BB Breakout beats Donchian on Sharpe, MaxDD, and MC Score. However, BB Breakout's RSI Weekly correlation (r=0.7049) vs Donchian's RSI Weekly correlation (r=0.22) makes this substitution structurally problematic: **replacing Donchian with BB Breakout would eliminate one of the portfolio's best diversifiers** (Donchian has very low RSI Weekly correlation).

### 6. RS(min) = -3.89 for BB Breakout — Worst in Portfolio

BB Breakout's worst rolling Sharpe window (RS(min) = -3.89) is significantly worse than any other strategy (-2.26 to -2.81 range). This suggests BB Breakout has at least one prolonged losing streak that is more severe than the other strategies. Despite the overall high Sharpe (1.64), the regime dependency is higher than Donchian or Rel Mom.

### 7. Portfolio Optimization Analysis

This run tests BB Breakout as an additive 6th strategy, but the r=0.7049 with RSI Weekly makes the 6-strategy combination suboptimal. The better use cases for BB Breakout are:

**Option A: Replace RSI Weekly with BB Breakout** (5-strategy: MA Bounce + MAC + Donchian + Rel Mom + BB Breakout)
→ Would create a portfolio without the highest Sharpe strategy (RSI Weekly at 1.87-1.91)
→ BB Breakout Sharpe (1.64) < RSI Weekly (1.87) — net Sharpe loss
→ Not recommended

**Option B: Replace Donchian with BB Breakout** (5-strategy: MA Bounce + MAC + RSI Weekly + Rel Mom + BB Breakout)
→ BB Breakout is structurally superior (better Sharpe, MaxDD, MC Score)
→ BUT BB ↔ RSI Weekly r=0.7049 breaks the 0.70 diversification threshold
→ Borderline — requires empirical testing (Q47)

**Option C: Keep Current R42 5-Strategy Portfolio Unchanged**
→ Donchian has r=0.22 with RSI Weekly (best diversifier from the trend-following cluster)
→ Donchian MaxDD 47.72% (acceptable at 3.3% allocation)
→ Donchian OOS +4,282% (positive OOS confirmation)
→ No structural weaknesses found; BB Breakout cannot replace it without introducing r=0.7049 problem

---

## Verdict

**BB Breakout CANNOT be added as a 6th strategy to the R42 optimized portfolio** due to r=0.7049 with RSI Weekly.

**BB Breakout vs Donchian replacement is ambiguous** — better on most metrics but introduces problematic RSI Weekly correlation. Q47 should empirically test this substitution.

**Current R42 production portfolio remains the best confirmed configuration** until Q47 validates or invalidates BB Breakout as a Donchian replacement.

---

## Config Changes Made and Restored

```python
# Changed for Q46 run:
"timeframe": "W"
"portfolios": {"NDX Tech (44)": "nasdaq_100_tech.json"}
"strategies": [6 specific strategy names — R42 5 + BB Breakout]
"allocation_per_trade": 0.028
"min_bars_required": 100

# Restored after run:
"timeframe": "D"
"portfolios": {"NDX Tech (44)": "nasdaq_100_tech.json"}
"strategies": "all"
"allocation_per_trade": 0.10
"min_bars_required": 250
```

---

## New Queue Item Identified

**Q47 — BB Breakout Replacing Donchian (5-Strategy: MA Bounce + MAC + RSI Weekly + Rel Mom + BB Breakout)**

Test whether BB Breakout's superior metrics (Sharpe 1.64 vs 1.56, MaxDD 34.27% vs 47.72%, MC Score 5 vs 2) justify replacing Donchian despite BB ↔ RSI Weekly r=0.7049. If this pair exceeds 0.70 in the 5-strategy context (without Donchian acting as a structural buffer), the replacement should be rejected. Run at 3.3% allocation (1/N for N=5).

## Research Status

Q46 complete. BB Breakout cannot be added as a 6th strategy (r=0.7049 with RSI Weekly). The R42 5-strategy optimized portfolio remains the confirmed production configuration. Q47 will test BB Breakout as a Donchian replacement to determine if a better 5-strategy portfolio exists.
