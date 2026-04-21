# Research Round 37 — Williams R Proper Sensitivity Sweep (min_val=-100)

**Date:** 2026-04-11
**Run ID:** williams-r-sensitivity-proper_2026-04-11_08-49-15
**Symbols:** nasdaq_100_tech.json (44)
**Period:** 1990-2026
**WFA:** 80/20 split, 3 rolling folds
**Sweep config:** `sensitivity_sweep_enabled=True`, `sensitivity_sweep_pct=0.15`, `sensitivity_sweep_steps=2`, **`sensitivity_sweep_min_val=-100`** (critical fix vs Round 36)

---

## Purpose

Round 36 revealed that Williams R's sensitivity sweep was impaired: `sensitivity_sweep_min_val=2` clips negative threshold params (entry_level=-20, exit_level=-80). Re-running with `min_val=-100` allows proper variation of Williams %R thresholds within their natural range.

---

## Results

**Base params:**
- `wr_length` = 14 bars (70d at weekly)
- `entry_level` = -20.0 (near 14-week high)
- `exit_level` = -80.0 (near 14-week low)
- `sma_slow` = 40 bars (200d at weekly)

**Sweep matrix:**
- `wr_length`: 10, 12, 14, 16, 18 (±15% × 2 steps)
- `entry_level`: -26.0, -23.0, -20.0, -17.0, -14.0 (±15% × 2 steps, negative values preserved)
- `exit_level`: -104.0, -92.0, -80.0, -68.0, -56.0 (±15% × 2 steps, negative values preserved)
- `sma_slow`: 28, 34, 40, 46, 52 (±15% × 2 steps)
- Total variants: 5 × 5 × 5 × 5 = **625 variants**

**Sweep results:**

| Metric | Value |
|---|---|
| Variants tested | 625 |
| Variants profitable | **625 / 625 (100.0%)** |
| WFA Pass variants | **625 / 625 (100.0%)** |
| Sharpe range | **1.59 — 2.21** |
| Median Sharpe | **1.86** |
| Base variant `[(base)]` | Sharpe 1.94, P&L 156,992%, OOS +133,655%, RS(min) -2.12, MC -1 |

**Fragility verdict: ROBUST — profitable in 100% of 625 variants, 100% WFA Pass**

### Best variants found

| Variant | Sharpe | P&L | OOS P&L | RS(min) |
|---|---|---|---|---|
| `[entry_level=-23.0, exit_level=-56.0]` | **2.21** | 338,648% | +313,331% | -2.23 |
| `[exit_level=-56.0, sma_slow=34]` | **2.20** | 311,838% | +278,891% | **-2.06** |
| `[entry_level=-26.0, exit_level=-56.0]` | **2.16** | 234,372% | +214,280% | **-1.77** |

### Worst variants found

| Variant | Sharpe | P&L | WFA |
|---|---|---|---|
| `[wr_length=18, entry_level=-14.0, exit_level=-92.0, sma_slow=46]` | 1.59 | 37,315% | Pass |
| `[wr_length=16, entry_level=-14.0, sma_slow=46]` | 1.63 | 37,877% | Pass |

Even the worst variant (Sharpe 1.59) passes WFA and is profitable. Minimum Sharpe of 1.59 is still above the minimum threshold (> 1.50) for champion qualification.

---

## Key Findings

### 1. Williams R is ROBUSTLY CONFIRMED as a Champion

100% of 625 variants are profitable and 100% pass WFA. The edge is structural — entering when Williams %R crosses above -20 in an uptrend captures genuine 14-week momentum. This is the most robust sweep of any strategy in the research (BB Breakout: 75/75 = 100%; RSI Weekly: 534/535 = 99.8%; Williams R: 625/625 = 100%).

### 2. Base Params Are at ~70th Percentile — Not Peak-Optimized

The base variant (Sharpe 1.94) is around the 70th percentile of all 625 variants. Many variants outperform the base (best: Sharpe 2.21). This confirms the base params were chosen by first principles (Williams %R overbought boundary at -20), not by optimization. The edge is structural, not parameter-fitted.

### 3. The Parameter that Matters Most: exit_level

The best variants all use `exit_level=-56.0` (tighter exit: exits when %R drops below -56 instead of -80). This means the strategy exits sooner when momentum weakens, capturing more of the upleg. However, the base exit_level=-80 is also robust (625/625) — it's just slightly more patient/slower to exit.

This insight is noted for future live trading parameter selection but NOT acted upon in this study (no champion params changed mid-study).

### 4. Williams R vs RSI Weekly Comparison

| Metric | Williams R | RSI Weekly |
|---|---|---|
| Sharpe (base) | 1.94 | 1.85 |
| RS(min) | -2.12 | -2.15 |
| Trades | 799 | 671 |
| P&L | 156,992% | 135,445% |
| Sweep robustness | 625/625 (100%) | 534/535 (99.8%) |
| OOS P&L | +133,655% | +114,357% |

Williams R outperforms RSI Weekly on every metric: higher Sharpe, more trades, better OOS. The comparison supports Q40 (test Williams R as RSI Weekly replacement in 5-strategy portfolio).

---

## Updated Leaderboard

| Rank | Strategy | Sharpe | RS(min) | Trades | P&L | Status |
|---|---|---|---|---|---|---|
| 🥇 | Relative Momentum (13w vs SPY) W | **2.08** | -2.36 | 99 | 166,502% | PROVISIONAL (Q42 sweep pending) |
| 🥇 | **BB Breakout (20w/2std) W** | **2.08** | -3.50 | 798 | 152,197% | CONFIRMED ✓ |
| 3 | **Williams R Weekly (above-20) W** | **1.94** | **-2.12** | 799 | 156,992% | **CONFIRMED ✓** (this round) |
| 4 | MA Bounce (50d/3bar) W | 1.92 | -2.32 | 1,366 | 140,028% | Confirmed |
| 5 | Price Momentum (6m ROC) W | 1.87 | -2.30 | 671 | 156,879% | Confirmed |
| 6 | RSI Weekly (55-cross) W | 1.85 | -2.15 | 671 | 135,445% | Confirmed |
| 7 | MAC Fast Exit W | 1.80 | -2.54 | ~2,623 | 84,447% | Confirmed |
| 8 | Donchian W | 1.68 | -2.06 | ~1,658 | 53,499% | Confirmed |

---

## Next Queue Items

### Q40: Williams R as RSI Weekly Replacement in 5-Strategy Portfolio (priority: HIGH)
### Q42: Relative Momentum Sensitivity Sweep (priority: HIGH — only 99 trades)
### Q41: 6-Strategy Portfolio on Sectors+DJI 46 (add Relative Momentum)
