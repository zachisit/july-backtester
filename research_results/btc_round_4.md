# Bitcoin Research Round 4 — RSI Trend Sensitivity Sweep (BTC-Q5a)

**Date:** 2026-04-12
**Run ID:** btc-daily-r4-rsi-sweep_2026-04-12_11-24-44
**Symbol:** X:BTCUSD (single asset)
**Period:** 2017-01-03 → 2026-04-10
**Strategy:** BTC RSI Trend (14/60/40) + SMA200
**Params swept:** rsi_length (14), entry_level (60), exit_level (40), gate_length (200)
**Sweep config:** ±20% per param, 2 steps each side → 5 values per param × 4 params = 625 total variants (5^4)

## Results

| Metric | Value |
|---|---|
| Total variants | 625 |
| Profitable | **594/625 (95.0%)** |
| WFA Pass (of scorable) | **252/300 (84.0%)** |
| WFA Overfitted | 48/300 (16.0%) |
| WFA N/A (too sparse for eval) | 325/625 (52%) |
| OOS Positive | **522/625 (83.5%)** |
| Calmar range | -0.14 to 1.86 |
| Base rank (by Calmar) | **14/625 (top 2.2%)** |

*325 NaN WFA variants have entry_level ≥ 72 or restrictive params → generate only ~20 trades → OOS has <5 trades, WFA returns N/A. All are profitable with positive OOS.*

**VERDICT: ROBUST** — 95% profitable (threshold: 70%). 84% WFA Pass on scorable variants. **BTC RSI Trend CONFIRMED champion.**

## Base Variant

| Strategy | P&L | Calmar | OOS P&L | WFA | Trades |
|---|---|---|---|---|---|
| BTC RSI Trend (14/60/40) + SMA200 [(base)] | +6,663.04% | **1.32** | +732.31% | **Pass** | 22 |

## Top 5 Variants by Calmar

| Strategy | Calmar | P&L | OOS P&L | WFA |
|---|---|---|---|---|
| [rsi_length=11 entry_level=72 exit_level=56 gate_length=120] | **1.86** | +3,215.79% | +640.16% | Pass |
| [rsi_length=20 exit_level=56 gate_length=120] | 1.77 | +7,840.97% | +800.70% | Pass |
| [rsi_length=8 entry_level=48 exit_level=56 gate_length=120] | 1.70 | +13,217.95% | +4,268.11% | Pass |
| [rsi_length=11 exit_level=56 gate_length=120] | 1.63 | +10,320.62% | +1,198.95% | Pass |
| [rsi_length=11 entry_level=72 exit_level=56 gate_length=160] | 1.55 | +2,050.24% | +407.47% | Pass |

*All top-5 share `exit_level=56` and most use `gate_length=120`. The exit RSI level at 56 (vs base 40) = more conservative exit, holds longer during uptrends. gate_length=120 = faster re-entry. Same gate_length=120 pattern seen in MA Bounce sweep.*

## Overfitting Pattern (48 of 300 scorable variants)

Top contributing factors:
- `entry_level=36` (15 variants): RSI 36 is near-neutral/mean-reversion — not trend-following
- `entry_level=48` (14 variants): RSI 48 is below midline — too many false signals
- `rsi_length=8` (25 variants): very short RSI = noisy, overreacts to daily volatility
- `exit_level=48` (13 variants): small gap between entry(60) and exit(48) → chops in/out

**Fragile zone:** rsi_length=8 + entry_level ≤ 48 combinations.
**Robust zone:** rsi_length ≥ 11 + entry_level ≥ 60 + exit_level ≤ 44. Base params (14/60/40/200) are deep in the robust zone.

## Key Findings

### 1. 95% Profitable on 625 Variants — Second-Best Sweep in Bitcoin Research
After MA Bounce (100% profitable at 75 variants), RSI Trend achieves 95% profitable across 625 variants. This is the highest robustness measure on any 4-param sweep in all research.

### 2. Base Rank 14/625 (Top 2.2%) — Not Cherry-Picked
The base params are in the top 2.2% by Calmar — not the maximum. 611 variants have equal or worse Calmar. The base is a deliberately conservative parameter set.

### 3. gate_length=120 Pattern Repeats
Same as the MA Bounce sweep — shorter SMA gate (120 bars = 4 months) outperforms the 200-bar gate. Bitcoin trades year-round; 120 bars = faster re-entry after corrections during ongoing bull markets. NOT recommended for production (introduces more regime sensitivity), but confirms the structural pattern.

### 4. exit_level=56 Outperforms Base exit_level=40
All top-5 Calmar variants use exit_level=56. A higher exit level = exits when RSI falls below 56 (vs 40) = leaves the position earlier when upward momentum fades. This reduces trade duration and exposure during volatile periods. The base exit=40 is more patient but avoids false exits.

## Verdict

**BTC RSI Trend (14/60/40) + SMA200 is CONFIRMED as #1 Bitcoin Champion (Calmar 1.32).**

| Rule | Status |
|---|---|
| WFA Pass | ✓ Pass |
| RollWFA | ✓ 2/2 |
| Calmar > 0.5 | ✓ 1.32 |
| Calmar > BTC B&H (0.79) | ✓ 1.32 > 0.79 |
| Calmar > MA Bounce (1.22) | ✓ 1.32 > 1.22 |
| OOS positive | ✓ +732.31% |
| MaxDD < 60% | ✓ 43.72% |
| Trades ≥ 20 | ✓ 22 |
| Sweep ≥ 70% profitable | ✓ **94/625 (95.0%)** |
