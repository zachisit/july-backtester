# Research Round 39 — Q42: Relative Momentum Sensitivity Sweep + Column Misread Correction

**Date:** 2026-04-11
**Run ID:** relmom-sensitivity-sweep_2026-04-11_11-52-18
**Symbols:** nasdaq_100_tech.json (44 symbols)
**Period:** 1993-2026 (actual data: 1993-01-29 → 2026-04-10)
**WFA:** 80/20 split, 3 rolling folds
**Timeframe:** W (weekly bars)
**Sweep config:** `sensitivity_sweep_enabled=True`, `sensitivity_sweep_pct=0.15`, `sensitivity_sweep_steps=2`, **`sensitivity_sweep_min_val=0.5`**

---

## CRITICAL CORRECTION: "99 Trades" Was a Column Misread

Round 35 and RESEARCH_HANDOFF.md recorded Relative Momentum as having "99 trades, avg hold 831 days." This was a **column swapping error**. The CSV columns `Avg. Hold (d)` and `Trades` were misread.

**Correct values (confirmed by Q42 base variant):**
- **Trades = 831** (not 99)
- **Avg. Hold (d) = 99 days** ≈ 20 weeks / 4.7 months (not 831 days)

The "only 99 trades" concern that placed Relative Momentum as PROVISIONAL was entirely based on this misread. With 831 trades, the strategy is WELL ABOVE the 500-trade threshold for full statistical confidence.

---

## Purpose

Q42 was designed to sensitivity-sweep Relative Momentum's parameters to validate robustness before live trading. The key concern: rel_thresh=1.15 (outperform SPY by 15%) chosen by first principles — is this threshold uniquely good, or does a range of values work?

**Note on min_val fix:** Q42 spec originally listed `sensitivity_sweep_min_val=2`. This would clip rel_thresh values (range 0.80-1.50) since ALL are below 2.0 — same class of bug as Williams R (min_val=2 clips negative %R params). Used `min_val=0.5` instead, which properly varies rel_thresh while preventing period lengths from reaching 0.

---

## Sweep Configuration

**Base params:**
- `roc_bars` = 13 bars (13-week lookback)
- `rel_thresh` = 1.15 (outperform SPY by 15%+)
- `sma_slow` = 40 bars (200d/40w uptrend gate)

**Sweep matrix (±15% × 2 steps per param, min_val=0.5):**
- `roc_bars`: 9, 11, 13, 15, 17
- `rel_thresh`: 0.805, 0.978, 1.15, 1.323, 1.495
- `sma_slow`: 28, 34, 40, 46, 52
- Total: 5 × 5 × 5 = **125 variants**

---

## Results

| Metric | Value |
|---|---|
| Variants tested | 125 |
| Variants profitable | **125 / 125 (100.0%)** |
| WFA Pass variants | **124 / 125 (99.2%)** |
| Sharpe range | **-0.36 — 2.08** |
| Median Sharpe | **1.62** |
| Base variant `[(base)]` | Sharpe 2.08, P&L 166,502%, OOS +153,533%, Trades 831 |

**Fragility verdict: ROBUST — profitable in 100% of 125 variants, 99.2% WFA Pass**

---

## Breakdown by rel_thresh Group

| rel_thresh | Variants | Profitable | WFA Pass | Sharpe Range | Trade Range |
|---|---|---|---|---|---|
| 0.805 (-30%) | 25 | 25/25 (100%) | 24/25 (96%) | -0.36 to 0.48 | 122 to 268 |
| 0.978 (-15%) | 25 | 25/25 (100%) | 25/25 (100%) | 1.48 to 1.96 | 1,260 to 1,773 |
| **1.150 (base)** | **25** | **25/25 (100%)** | **25/25 (100%)** | **1.79 to 2.08** | **748 to 1,018** |
| 1.323 (+15%) | 25 | 25/25 (100%) | 25/25 (100%) | 1.21 to 1.82 | 333 to 450 |
| 1.495 (+30%) | 25 | 25/25 (100%) | 25/25 (100%) | 1.01 to 1.44 | 140 to 243 |

---

## Top Variants

| Variant | Sharpe | P&L | WFA |
|---|---|---|---|
| `[(base)]` | **2.08** | 166,502% | Pass |
| `[sma_slow=34]` | **2.07** | ~161,000% | Pass |
| `[sma_slow=52]` | **2.04** | ~155,000% | Pass |
| `[sma_slow=46]` | **2.04** | ~157,000% | Pass |
| `[roc_bars=11]` | **2.03** | ~170,000% | Pass |

The base variant is the BEST variant by Sharpe — confirming the first-principles parameter selection.

## Worst Variants (Valid Only)

| Variant | Sharpe | P&L | WFA | Notes |
|---|---|---|---|---|
| `[rel_thresh=0.805, sma_slow=28]` | -0.36 | 4.97% | Pass | Degenerate: loose threshold + short SMA |
| `[roc_bars=11, rel_thresh=0.805, sma_slow=28]` | -0.13 | 23.73% | **Likely Overfitted** | Only WFA failure |
| `[rel_thresh=0.805, sma_slow=34]` | -0.02 | 34.74% | Pass | Still profitable! |

Even the worst variant (Sharpe -0.36) is profitable (P&L 4.97%). Negative Sharpe with positive P&L means the raw return is positive but below the 5% risk-free rate — technically correct but not an investment-grade result. This only occurs at the extreme degenerate combination of rel_thresh=0.805 (too loose) + sma_slow=28 (too short).

---

## Key Findings

### 1. Relative Momentum Is CONFIRMED CHAMPION (Trade Count Misread Corrected)

The "only 99 trades" concern was based on a column misread in round_35.md. The actual trade count is **831** (avg hold is 99 days). This resolves the PROVISIONAL status entirely:
- 831 trades > 500-trade threshold ✓
- 125/125 profitable ✓
- 124/125 WFA Pass ✓
- Base params at the TOP of the distribution ✓

**Promoted from PROVISIONAL to CONFIRMED champion.**

### 2. Base Params Are Optimal, Not Mid-Distribution

Unlike other sensitivity sweeps where the base was near the median:
- RSI Weekly: base at ~85th percentile of all variants
- Williams R: base at ~70th percentile
- **Relative Momentum: base at ~99th percentile** (highest Sharpe of all 125 variants!)

The 1.15 threshold is genuinely the best value tested, not merely "good enough." This is consistent with first-principles selection: 15% outperformance vs SPY captures genuine leadership without triggering on normal correlation variance.

### 3. rel_thresh Is the Critical Parameter

| rel_thresh | Sharpe Range | Quality |
|---|---|---|
| 0.805 (too loose) | -0.36 to 0.48 | Near-degenerate: too many stocks qualify |
| 0.978 (-15%) | 1.48 to 1.96 | Good, but lower quality than base |
| **1.150 (base)** | **1.79 to 2.08** | **Optimal: selective but sufficient signal** |
| 1.323 (+15%) | 1.21 to 1.82 | Fewer trades, lower Sharpe |
| 1.495 (too tight) | 1.01 to 1.44 | Very few trades, signal too rare |

The 1.15 threshold is at the "sweet spot" — capturing genuine relative strength events without being so common that noise creeps in.

### 4. Avg Hold Is 99 Days (~20 Weeks), Not 3.3 Years

With avg hold of 99 trading days ≈ 20 weeks ≈ 5 months, Relative Momentum is a MEDIUM-term hold strategy — longer than MA Bounce (90-days Avg Hold in weekly mode) but much shorter than the "3.3 years" that was claimed.

The actual dynamics:
- Strategy enters when stock starts a relative leadership phase (outperforming SPY by 15%+ in last 13w)
- Hold through the leadership phase
- Exit when leadership fades (stock stops outperforming SPY)
- Average leadership phase: ~5 months

This is much more similar to other strategies than previously thought.

### 5. Correlation Update: r=0.06 vs MAC Is Still the Key Diversifier

The exceptional correlation property of Relative Momentum (r=0.06 vs MAC Fast Exit in the 6-strategy combined run from Round 35) is NOT due to multi-year holds but rather because the MAC signal (MA alignment) and the relative outperformance signal fire on DIFFERENT market conditions. MAC enters when trend structure aligns (EMA 10/20/50 aligned); Relative Momentum enters when the stock is beating SPY — these can diverge significantly in rotation periods.

---

## Updated Champion Status

| Rank | Strategy | Sharpe | Trades | Status |
|---|---|---|---|---|
| 🥇 | Relative Momentum (13w vs SPY) W | **2.08** | **831** | **CONFIRMED ✓** (was PROVISIONAL — trade misread corrected) |
| 🥇 | BB Breakout (20w/2std) W | **2.08** | 798 | CONFIRMED ✓ |
| 3 | Williams R Weekly (above-20) W | **1.94** | 799 | CONFIRMED ✓ |
| 4 | MA Bounce (50d/3bar) W | 1.92 | 1,366 | Confirmed |
| 5 | Price Momentum (6m ROC) W | 1.87 | 671 | Confirmed |
| 6 | RSI Weekly (55-cross) W | 1.85 | 671 | Confirmed |

---

## Config Changes Made and Restored

```python
# Changed for run:
"timeframe": "W"
"strategies": ["Relative Momentum (13w vs SPY) Weekly + SMA200"]
"sensitivity_sweep_enabled": True
"sensitivity_sweep_pct": 0.15
"sensitivity_sweep_steps": 2
"sensitivity_sweep_min_val": 0.5  # needed for rel_thresh (values 0.80-1.50 < default min_val=2)

# Restored after run:
"timeframe": "D"
"strategies": "all"
"sensitivity_sweep_enabled": False
"sensitivity_sweep_pct": 0.20
"sensitivity_sweep_steps": 2
"sensitivity_sweep_min_val": 2
```

---

## Next Queue Items

### Q41: 6-Strategy Portfolio on Sectors+DJI 46 with Relative Momentum (priority: MEDIUM)
Now that Relative Momentum is CONFIRMED, test it in the conservative Sectors+DJI 46 universe with all 6 strategies at 2.8% allocation.
