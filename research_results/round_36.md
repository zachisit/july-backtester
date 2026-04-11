# Research Round 36 — Sensitivity Sweep: BB Breakout + Williams R (Anti-Overfitting Validation)

**Date:** 2026-04-11
**Run ID:** bb-wr-sensitivity-sweep_2026-04-11_08-33-40
**Symbols:** nasdaq_100_tech.json (44)
**Period:** 1990-2026
**WFA:** 80/20 split, 3 rolling folds
**Sweep config:** `sensitivity_sweep_enabled=True`, `sensitivity_sweep_pct=0.15`, `sensitivity_sweep_steps=2`

---

## Purpose

Mandatory Rule 6 compliance for Round 34 new champions. BB Weekly Breakout (Sharpe 2.08) and Williams R Weekly Trend (Sharpe 1.94) were declared provisional after Round 34 — they cannot be confirmed as champions until a sensitivity sweep validates they are not overfit to the specific parameters chosen.

---

## BB Weekly Breakout Sensitivity Sweep Results

**Base params:**
- `bb_length` = 20 bars (get_bars_for_period("100d", "W"))
- `bb_std` = 2.0
- `sma_slow` = 40 bars (get_bars_for_period("200d", "W"))

**Sweep matrix:**
- `bb_std` effective unique values: 2.0, 2.3, 2.6 (lower variants 1.4/1.7 floor to 2.0 via min_val=2)
- `bb_length` values: 14, 17, 20, 23, 26 (±15% × 2 steps)
- `sma_slow` values: 28, 34, 40, 46, 52 (±15% × 2 steps)
- Total variants: 3 × 5 × 5 = **75 variants**

**Sweep results:**

| Metric | Value |
|---|---|
| Variants tested | 75 |
| Variants profitable | **75 / 75 (100%)** |
| WFA Pass variants | **75 / 75 (100%)** |
| Sharpe range | **1.18 — 2.19** |
| Best Sharpe variant | `[bb_length=17]` — Sharpe 2.19, P&L 205,574% |
| Worst Sharpe variant | `[bb_length=14, bb_std=2.6, sma_slow=34]` — Sharpe 1.24 |
| Base variant `[(base)]` | Sharpe 2.08, P&L 152,197%, OOS +131,460%, MC -1 |

**Fragility verdict:** **ROBUST — profitable in 100% of variants (75/75)**

### Notable observations

**Sharpe sensitivity by param:**
- `bb_length`: The single most impactful parameter. Lower values (shorter window = more signals at lower quality) keep Sharpe > 1.18. Larger values (23, 26) drop trade count but maintain Sharpe 1.78-2.19. Base (20) is well-positioned.
- `bb_std`: 2.0 vs 2.3 vs 2.6: Higher std = tighter selection (fewer signals), generally improves Sharpe (1.4 → 2.08 for the base). Base at 2.0 is at the low end; going to 2.3 or 2.6 with the same bb_length actually worsens P&L (fewer trades).
- `sma_slow`: Minor impact on Sharpe. All sma_slow values produce similar results (40-week vs 28/34/46/52-week trend gate). Base at 40 is robust.

**Important: `bb_length=17` OUTPERFORMS base on every metric:**
- Sharpe 2.14-2.19 (vs base 2.08)
- P&L 109,404-205,574% (variants vs 152,197% base)
- OOS P&L even larger margin

Per research protocol, this is noted but NOT acted upon — changing champion parameters mid-study based on sweep results is p-hacking. The 20-bar base remains the official parameter.

**VERDICT: BB Weekly Breakout (20w/2std) + SMA200 is CONFIRMED CHAMPION ✓**

---

## Williams R Sensitivity Sweep — IMPAIRED (Incomplete)

**Base params:**
- `wr_length` = 14 bars
- `entry_level` = -20.0
- `exit_level` = -80.0
- `sma_slow` = 40 bars

**Issue discovered:** `sensitivity_sweep_min_val=2` clips ALL negative parameter variants for `entry_level` and `exit_level`. Williams %R ranges from -100 to 0 — all swept values (e.g., -17, -14 for entry_level) are below the floor of 2 and get replaced with 2.0. A value of 2 is outside the Williams %R range (always ≤ 0), so these variants generate 0 trades and are filtered from the output.

**Result:** Only the base variant ran successfully. All swept variants were invalid due to the floor clipping negative thresholds.

**What ran:** 1 variant (base only)
- Williams R base: Sharpe 1.94, P&L 156,991%, OOS +133,655%, WFA Pass 3/3, MC -1, RS(min) -2.12

**Conclusion:** The Williams R sweep is INCOMPLETE. A proper sweep requires `sensitivity_sweep_min_val=-100` to allow variation of Williams %R thresholds.

**Action:** Added to queue as Q43 — re-run Williams R sweep with `sensitivity_sweep_min_val=-100`.

**Interim status:** Williams R remains PROVISIONAL pending proper sensitivity sweep. Previous backtest results (Sharpe 1.94, RS(min) -2.12, 799 trades) are valid — only the sweep validation is missing.

---

## Updated Leaderboard (after sensitivity sweep validation)

| Rank | Strategy | Sharpe | RS(min) | Trades | P&L | Status |
|---|---|---|---|---|---|---|
| 🥇 | Relative Momentum (13w vs SPY) W | **2.08** | -2.36 | 99 | 166,502% | PROVISIONAL (no sweep) |
| 🥇 | **BB Breakout (20w/2std) W** | **2.08** | -3.50 | 798 | 152,197% | **CONFIRMED (sweep ROBUST)** |
| 3 | MA Bounce (50d/3bar) W | 1.92 | -2.32 | 1,366 | 140,028% | Confirmed champion |
| 4 | Williams R (above-20) W | 1.94 | -2.12 | 799 | 156,992% | PROVISIONAL (sweep impaired) |
| 5 | Price Momentum (6m ROC) W | 1.87 | -2.30 | 671 | 156,879% | Confirmed champion |
| 6 | RSI Weekly (55-cross) W | 1.85 | -2.15 | 671 | 135,445% | CONFIRMED (Q21 sweep ROBUST) |
| 7 | MAC Fast Exit W | 1.80 | -2.54 | ~2,623 | 84,447% | Confirmed champion |
| 8 | Donchian W | 1.68 | -2.06 | ~1,658 | 53,499% | Confirmed champion |

---

## Key Findings

### 1. BB Breakout is Robustly Valid

100% of 75 parameter variants are profitable with WFA Pass. The edge is structural — breaking a 20-week Bollinger Band in an SMA(40w) uptrend captures genuine sustained momentum regardless of the exact window length or std multiplier. This is the same pattern as RSI Weekly (99.8% of valid variants profitable in Q21).

### 2. Williams R Sweep Design Issue

The `sensitivity_sweep_min_val=2` setting is designed to prevent SMA/RSI periods from going below 2. But it inadvertently clips negative threshold parameters like Williams %R entry/exit levels. Any strategy using negative-value thresholds (Williams %R, Williams %R variants, inverse oscillators) will have an impaired sweep with the current config default.

**Fix required:** For sweeping strategies with negative-valued parameters, set `sensitivity_sweep_min_val=-100` before running the sweep. This is NOT a strategy bug — it is a config issue.

### 3. Research Pipeline Implications

Before promoting either new oscillator strategy to the production 5-strategy portfolio:
- BB Breakout: **APPROVED** ✓ (sweep confirms robustness)
- Williams R: **PENDING** (needs re-sweep with min_val=-100)
- Relative Momentum: **PENDING** (no sweep yet; only 99 trades in 36 years raises statistical concern)

---

## New Queue Items

### Q43: Williams R Proper Sensitivity Sweep (min_val=-100)
- Set `sensitivity_sweep_min_val=-100` (allows negative threshold variation)
- Re-run sweep for Williams R Weekly Trend
- Same sweep settings otherwise: pct=0.15, steps=2

### Q40 (from Round 35): Williams R as RSI Weekly Replacement in 5-Strategy Portfolio
- Drop RSI Weekly (Sharpe 1.85), add Williams R (Sharpe 1.94, RS(min) -2.12)
- Test if 5-strategy portfolio improves with Williams R vs RSI Weekly

### Q41 (from Round 35): 6-Strategy Portfolio on Sectors+DJI 46
- Add Relative Momentum to the conservative universe test
- Relative Momentum's 3.3-year avg hold may achieve MaxDD < 20% on Sectors+DJI 46

### Q42 (from Round 35): Relative Momentum Sensitivity Sweep
- Is the 15% outperformance threshold vs SPY uniquely good?
- Critical validation — only 99 trades makes the strategy statistically marginal
- Use `sensitivity_sweep_min_val=0.01` (rel_thresh and roc_bars are positive floats/ints)
