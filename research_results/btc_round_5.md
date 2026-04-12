# Bitcoin Research Round 5 — Donchian 52/13 Sensitivity Sweep (BTC-Q5b)

**Date:** 2026-04-12
**Run ID:** btc-daily-r5-donchian-sweep_2026-04-12_11-27-09
**Symbol:** X:BTCUSD (single asset)
**Period:** 2017-01-03 → 2026-04-10
**Strategy:** BTC Donchian Wider (52/13)
**Params swept:** entry_period (52), exit_period (13)
**Sweep config:** ±20% per param, 2 steps each side → 5 values per param × 2 params = 25 total variants (5^2)

## Results

| Metric | Value |
|---|---|
| Total variants | 25 |
| Profitable | **25/25 (100.0%)** |
| WFA Pass (of scorable) | **11/15 (73.3%)** |
| WFA Overfitted | 4/15 (26.7%) |
| WFA N/A (too sparse) | 10/25 (40%) |
| OOS Positive | **21/25 (84.0%)** |
| Calmar range | 0.66 to 1.05 |
| Base rank (by Calmar) | **9/25 (top 36%)** |

*10 N/A WFA variants use entry_period=62 or entry_period=73 (larger entry window = fewer breakout signals = <5 OOS trades). All profitable.*

**VERDICT: ROBUST** — 100% profitable (threshold: 70%). 73.3% WFA Pass on scorable variants (just above 70% threshold). **BTC Donchian Wider 52/13 CONFIRMED champion.**

## Base Variant

| Strategy | P&L | Calmar | OOS P&L | WFA | RollWFA | Trades |
|---|---|---|---|---|---|---|
| BTC Donchian Wider (52/13) [(base)] | +2,919.64% | **0.84** | +805.13% | **Pass** | **3/3** | 24 |

## All Variants (sorted by Calmar)

| Strategy | Calmar | P&L | OOS P&L | WFA |
|---|---|---|---|---|
| [entry_period=73 exit_period=8] | 1.05 | +1,713.23% | +505.85% | N/A |
| [entry_period=42 exit_period=8] | 1.02 | +2,745.73% | +677.53% | Pass |
| [entry_period=31 exit_period=8] | 1.02 | +3,140.23% | +174.93% | Pass |
| [exit_period=8] | 0.93 | +1,881.88% | +520.50% | Pass |
| [entry_period=73 exit_period=10] | 0.93 | +2,438.81% | +560.51% | N/A |
| [entry_period=31 exit_period=10] | 0.92 | +3,899.02% | **-40.16%** | Overfitted |
| [entry_period=31 exit_period=18] | 0.90 | +4,760.76% | **-858.14%** | Overfitted |
| [entry_period=31] | 0.87 | +3,973.58% | **-485.11%** | Overfitted |
| [entry_period=42] | 0.84 | +3,425.29% | +522.42% | Pass |
| [exit_period=16] | 0.84 | +2,954.68% | +731.25% | Pass |
| **(base)** | **0.84** | **+2,919.64%** | **+805.13%** | **Pass** |
| [entry_period=42 exit_period=10] | 0.84 | +3,396.16% | +453.17% | Pass |
| [exit_period=10] | 0.83 | +2,840.07% | +778.11% | Pass |
| [entry_period=73] | 0.82 | +2,175.69% | +517.02% | N/A |
| [entry_period=31 exit_period=16] | 0.82 | +4,578.65% | **-380.18%** | Overfitted |
| [entry_period=62 exit_period=16] | 0.81 | +2,620.85% | +716.06% | N/A |
| [entry_period=62 exit_period=8] | 0.80 | +1,667.45% | +535.75% | N/A |
| [entry_period=73 exit_period=18] | 0.79 | +2,523.14% | +379.08% | N/A |
| [entry_period=62] | 0.79 | +2,474.62% | +726.90% | N/A |
| [entry_period=62 exit_period=10] | 0.79 | +2,429.35% | +674.92% | N/A |
| [entry_period=42 exit_period=18] | 0.78 | +3,500.14% | +65.90% | Pass |
| [exit_period=18] | 0.77 | +2,947.50% | +510.59% | Pass |
| [entry_period=42 exit_period=16] | 0.73 | +3,266.43% | +215.45% | Pass |
| [entry_period=62 exit_period=18] | 0.73 | +2,514.73% | +440.04% | N/A |
| [entry_period=73 exit_period=16] | 0.66 | +2,324.12% | +559.54% | N/A |

## Overfitting Pattern (4 of 15 scorable variants)

All 4 overfitted variants have `entry_period=31` (the shortest possible entry lookback at 31-bar). A 31-bar new high on Bitcoin captures very short-term momentum — this generates more entries during IS bull markets (high P&L) but the entry signals are too noise-sensitive for OOS generalization.

**Fragile zone:** `entry_period=31` is the only consistently fragile parameter value.
**Robust zone:** `entry_period ≥ 42` — all such scorable variants WFA Pass.
**Base `entry_period=52` is well inside the robust zone.**

## Key Findings

### 1. 100% Profitable — Same as MA Bounce
All 25 variants profitable (100%). Every Donchian parameter combination generates positive returns on Bitcoin over 9.3 years. This reflects the strong structural edge of breakout-after-new-high in Bitcoin's bull-dominated history.

### 2. WFA Pass Rate = 73.3% (Just Above Threshold)
11 of 15 WFA-scorable variants pass. The 70% threshold is met but not overwhelmingly exceeded. The fragility is localized to `entry_period=31` (3 of 4 overfitted variants). The remaining parameter space is robust.

### 3. Base Rank 9/25 — Mid-Range (Not Cherry-Picked)
The base params rank 9th out of 25 by Calmar. The base is in the middle of the distribution — not the best performer, not cherry-picked.

### 4. exit_period=8 Outperforms Base exit_period=13
Top-3 variants by Calmar all use exit_period=8. A shorter exit lookback (8 bars = 8 calendar days) = exits on 8-day lows instead of 13-day lows = tighter trailing stop behavior. Reduces time in losing positions but may exit too early on some trades. Base exit=13 is more conservative.

### 5. Calmar Cap at 1.05 — Lower Ceiling Than MA Bounce and RSI Trend
Maximum Calmar across all variants: 1.05. The Donchian strategy has a lower ceiling than RSI Trend (max 1.86) and MA Bounce (max 1.93 in sweep). This reflects a structural characteristic: Donchian enters AFTER new highs (momentum confirmation), which sacrifices the early-cycle gains that RSI and MA Bounce capture.

## Verdict

**BTC Donchian Wider (52/13) is CONFIRMED as #3 Bitcoin Champion (Calmar 0.84).**

| Rule | Status |
|---|---|
| WFA Pass | ✓ Pass |
| RollWFA | ✓ 3/3 |
| Calmar > 0.5 | ✓ 0.84 |
| Calmar > BTC B&H (0.79) | ✓ 0.84 > 0.79 |
| OOS positive | ✓ +805.13% |
| MaxDD < 60% | ✓ 53.02% |
| Trades ≥ 20 | ✓ 24 |
| Sweep ≥ 70% profitable | ✓ **25/25 (100%)** |
| Sweep WFA Pass ≥ 70% of scorable | ✓ 73.3% |
