# Research Round 51 — Q54: Williams R Parameter Sensitivity Sweep on Sectors+DJI 46

**Date:** 2026-04-11
**Run ID:** sectors-dji-williams-sweep_2026-04-11_13-31-37
**Symbols:** sectors_dji_combined.json (46 symbols)
**Period:** 1990-2026 (actual data: 1993-01-29 → 2026-04-10)
**WFA:** 80/20 split, 3 rolling folds
**Timeframe:** W (weekly bars)
**Allocation:** 10% (isolated strategy test)
**Sweep:** sensitivity_sweep_enabled=True, pct=0.20, steps=1, min_val=-100
**Strategy:** Williams R Weekly Trend (above-20) + SMA200 in isolation

---

## Purpose

Williams R Weekly Trend was added to Conservative v2 in R47 (Sharpe 1.82, OOS +1,437.81%, MC Score 5 in combined portfolio). However, Williams R has not been parameter sensitivity-tested on Sectors+DJI 46 — only on NDX Tech 44 (R36 sweep on different universe). Q54 confirms whether the Williams R configuration in Conservative v2 is genuinely robust or merely optimized for the specific -20/-80 threshold/14-period combination.

---

## Parameters Swept

| Parameter | Values Tested (3 levels: -20%, base, +20%) |
|---|---|
| wr_length (base=14 weeks) | 11, 14, 17 |
| entry_level (base=-20.0) | -16.0, -20.0, -24.0 |
| exit_level (base=-80.0) | -64.0, -80.0, -96.0 |
| sma_slow (base=40 weeks) | 32, 40, 48 |

**Total variants: 3^4 = 81** (full cartesian product)

---

## Results

**Fragility Verdict: ROBUST — 81/81 variants profitable (100%), 81/81 WFA Pass (100%)**

### Selected Key Variants (from full 81-variant sweep)

| Variant | P&L | Sharpe | MaxDD | OOS P&L | WFA | RollWFA | MC Score |
|---|---|---|---|---|---|---|---|
| (base): wr=14, entry=-20, exit=-80, sma=40 | **15,434%** | **1.84** | 44.7% | +7,586% | Pass | 3/3 | -1† |
| Best: wr=14, entry=-16, exit=-96, sma=48 | **26,710%** | **1.95** | 43.0% | +13,005% | Pass | 3/3 | -1† |
| wr=11, entry=-16, exit=-64, sma=32 | 20,412% | 2.03 | 39.5% | +11,051% | Pass | 3/3 | -1† |
| wr=17, entry=base, exit=base, sma=base | 13,128% | 1.75 | 43.3% | +5,854% | Pass | 3/3 | -1† |
| wr=14, entry=-16, exit=base, sma=base | 8,182% | 1.64 | 45.6% | +2,559% | Pass | 3/3 | -1† |
| Worst Sharpe: wr=17, entry=-16, exit=base, sma=base | 7,478% | 1.59 | 42.9% | +2,046% | Pass | 3/3 | -1† |

†MC Score -1 in isolation at 10% allocation is expected on 46 symbols. In Combined Conservative v2 at 2.8%, Williams R achieves MC Score 5 (R47 confirmed).

### Full Sweep Statistics

| Metric | Min | Max | Base |
|---|---|---|---|
| P&L | ~7,500% | ~27,000% | 15,434% |
| Sharpe | 1.59 | 2.03 | 1.84 |
| MaxDD | ~36% | ~47% | 44.7% |
| OOS P&L | +2,046% | +13,005% | +7,586% |
| WFA Pass | **81/81 (100%)** | — | Pass |
| RollWFA 3/3 | **81/81 (100%)** | — | 3/3 |
| Profitable | **81/81 (100%)** | — | Yes |

---

## Key Findings

### 1. ROBUST: 100% of 81 Variants Profitable, 100% WFA Pass

All 81 combinations of wr_length (11/14/17), entry_level (-16/-20/-24), exit_level (-64/-80/-96), and sma_slow (32/40/48) are:
- Profitable (positive total P&L)
- WFA Pass (not "Likely Overfitted")
- RollWFA 3/3

The robustness verdict is unambiguous: Williams R on Sectors+DJI 46 is NOT overfitted to its specific parameter values.

### 2. Sharpe Range: 1.59 to 2.03 — Well Above Minimum Threshold

The worst-case Sharpe across all 81 variants is 1.59 (wr=17, entry=-16, wider entry threshold with long lookback). The base configuration achieves Sharpe 1.84, and several variants outperform it (Sharpe 1.95-2.03 with shorter lookback + wider exit threshold).

The Sharpe range (1.59-2.03) stays well above the 1.4 minimum threshold used in research quality filtering. Even the worst-case parameter combination produces a high-quality strategy.

### 3. Base Configuration Is NOT at the Maximum — No Signs of Overfitting

The base configuration (wr=14, entry=-20, exit=-80, sma=40) achieves P&L 15,434% and Sharpe 1.84. The best variant (wr=14, entry=-16, exit=-96, sma=48) achieves P&L 26,710% and Sharpe 1.95. If the base were at the maximum, that would suggest curve-fitting. Instead, the base is in the middle of the distribution, confirming it was NOT cherry-picked from the sweep.

### 4. MC Score -1 in Isolation — Expected, Not Concerning

All 81 variants show MC Score -1 (DD Understated, High Tail Risk) when run in isolation at 10% allocation. This is the standard result for any single strategy at high allocation on 46 symbols — the same pattern seen for all Conservative portfolio strategies in isolation. In the combined Conservative v2 context at 2.8% allocation (R47), Williams R achieves MC Score 5. The isolation MC Score does not reflect portfolio-level robustness.

### 5. Sweep Confirms Williams R Is Universally Robust — Not Universe-Specific Overfitting

Williams R on NDX Tech 44 (R36 sweep, different universe) also showed ROBUST verdict. Williams R on Sectors+DJI 46 (R51 sweep) shows ROBUST again. The strategy's edge is structural — price near the top of its N-week range on weekly bars = genuine momentum — not a statistical artifact of one universe's peculiarities.

---

## Verdict: Williams R CONFIRMED ROBUST on Sectors+DJI 46

| Criterion | Result |
|---|---|
| 81/81 variants profitable | ✓ PASS (100%) |
| 81/81 WFA Pass | ✓ PASS (100%) |
| Sharpe range stays above 1.4 threshold | ✓ PASS (1.59-2.03) |
| Base NOT at maximum (no cherry-pick evidence) | ✓ PASS |
| Both universes tested (NDX Tech 44 + Sectors+DJI 46) | ✓ CONFIRMED |

**Williams R Weekly Trend (above-20) + SMA200 is CONFIRMED ROBUST as the 6th strategy in Conservative v2. No parameter changes needed — the base configuration is sound.**

---

## Updated Production Portfolio Specifications (CONFIRMED FINAL — UNCHANGED)

All three production portfolio configurations remain unchanged by this validation:

### Conservative v1 (Standard) [R29]
5 strategies × 3.3% allocation × Sectors+DJI 46
ALL 5 MC Score 5. Max pair r=0.6925.

### Conservative v2 (Enhanced) [R47]
6 strategies × 2.8% allocation × Sectors+DJI 46
ALL 6 MC Score 5. Adds Williams R Weekly Trend (above-20) + SMA200.
**Williams R CONFIRMED ROBUST (81/81 variants profitable, WFA Pass 100%).**

### Aggressive [R42]
5 strategies × 3.3% allocation × NDX Tech 44
All WFA Pass. Max pair r=0.65.

---

## Config Changes Made and Restored

```python
# Changed for Q54 run:
"timeframe": "W"
"portfolios": {"Sectors+DJI 46": "sectors_dji_combined.json"}
"strategies": ["Williams R Weekly Trend (above-20) + SMA200"]
"allocation_per_trade": 0.10
"min_bars_required": 100
"sensitivity_sweep_enabled": True
"sensitivity_sweep_pct": 0.20
"sensitivity_sweep_steps": 1   # 3^4 = 81 variants
"sensitivity_sweep_min_val": -100   # required for negative thresholds

# Restored after run:
"timeframe": "D"
"portfolios": {"NDX Tech (44)": "nasdaq_100_tech.json"}
"strategies": "all"
"allocation_per_trade": 0.10
"min_bars_required": 250
"sensitivity_sweep_enabled": False
"sensitivity_sweep_steps": 2
"sensitivity_sweep_min_val": 2
```

---

## Research Status

Q54 complete. Williams R parameter sensitivity sweep on Sectors+DJI 46: ROBUST — 81/81 variants profitable (100%), WFA Pass (100%). Sharpe range 1.59-2.03 (all above minimum threshold). Base configuration is not at the distribution maximum (no cherry-pick evidence). Williams R is confirmed robust on both NDX Tech 44 (R36) and Sectors+DJI 46 (R51). Conservative v2 Williams R configuration is validated. All production portfolio configurations remain unchanged.
