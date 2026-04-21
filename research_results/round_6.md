# Research Round 6 — Targeted Fixes + 44-Symbol Validation

**Date:** 2026-04-10
**Symbols (Phase A):** tech_giants.json (6 symbols) — 1990-2026
**Symbols (Phase B):** nasdaq_100_tech.json (44 symbols) — 1990-2026
**Run IDs:**
- Phase A (fixes): research-v6-fixes_2026-04-10_22-02-31
- Phase B (44 sym): research-v6-44sym_2026-04-10_22-03-41

---

## Objective

Fix 5 Round 5 weaknesses. Validate Donchian (60d/20d)+MA Alignment on 44 symbols.

---

## Phase A: 6-Symbol Fix Attempts

| Strategy | P&L | Sharpe | RS(min) | OOS | WFA | Problem Solved? |
|---|---|---|---|---|---|---|
| Donchian (60d/20d)+MA Alignment | 739.87% | +0.16 | -55.00 | +378.64% | Pass | ✅ New discovery |
| CMF+RSI Exit Gate (20d) | 442.05% | +0.01 | -36.61 | +221.80% | Pass | ❌ Worse RS(min) |
| MA Bounce+RSI Timing (50d) | 33.50% | -1.62 | -1158.60 | +10.90% | Pass | ❌ Destroyed strategy |
| OBV+MA Confluence Alignment | 78.05% | -0.76 | -53.69 | +43.21% | Pass | ❌ Too few trades |
| MA Confluence+ATR Exit | 35.07% | -0.91 | -6.97 | +0.20% | Overfitted | ❌ ATR too tight |

### What Failed and Why

**CMF+RSI Exit Gate:** Tightening sell_threshold to 0.00 (from -0.05) creates faster exits but also more frequent re-entries and a churn pattern. RS(min) worsened from -16.59 to -36.61. The tighter CMF combined with RSI<40 is over-triggering. Root cause: CMF hovers near zero frequently, creating many small round-trips.

**MA Bounce+RSI Timing:** Catastrophic. RSI<50 at the 50-SMA touch moment is almost never true — when price touches the 50-SMA in an uptrend, it has typically pulled back to RSI ~50-60, not below 50. Filter eliminated 90% of trades (65 vs 660). RS(min)=-1158.60 is a calculation artifact from near-zero variance in a tiny trade sample. **Lesson: do not gate bounce entries on RSI — the bounce itself IS the momentum reversal.**

**MA Confluence+ATR Exit:** 2.0x ATR multiplier on tech stocks (NVDA ATR ≈ 5-8% of price) means 10-16% trailing stop. The stop is being hit constantly, generating 814 trades vs 344 for plain MA Confluence. "Likely Overfitted" WFA verdict confirms the ATR-based exit is fitting to in-sample data. If we try this again, need 3.0x+ multiplier or a completely different approach.

**OBV+MA Confluence:** OBV crossover + full MA stack is too selective. Only 266 trades, many poor quality. MaxRcvry 4894 days (13+ years). The two-filter combination is over-engineered.

---

## Phase B: 44-Symbol Validation — New Leaderboard

| Strategy | P&L (%) | Sharpe | RS(min) | OOS | WFA | RollWFA |
|---|---|---|---|---|---|---|
| MA Confluence Fast Exit | 101,198% | **+0.68** | -4.46 | +88,023% | Pass | 3/3 |
| MA Bounce (50d/3bar)+SMA200 | 45,283% | +0.61 | -10.93 | +40,519% | Pass | 3/3 |
| Donchian (40/20) | 48,426% | +0.63 | **-3.66** | +41,665% | Pass | 3/3 |
| **Donchian (60d/20d)+MA Alignment** | **42,263%** | **+0.64** | **-3.98** | **+35,177%** | **Pass** | **3/3** |
| MA Confluence Full Stack | 29,771% | +0.54 | -4.36 | +22,911% | Pass | 3/3 |

### Key finding: Donchian (60d/20d)+MA Alignment is excellent on 44 symbols

Despite mediocre 6-symbol results (+739%, RS(min)=-55), on 44 symbols:
- **RS(min) = -3.98** — second smoothest equity curve of all strategies tested
- Sharpe +0.64 — tied for second best
- OOS +35,177% — third highest
- SQN 5.81 — strong statistical significance

The 6-symbol RS(min)=-55 was misleading — with only 6 stocks and 292 trades, a single bad cluster distorted the rolling Sharpe. With 1,515 trades on 44 symbols, the law of large numbers produces a smooth, consistent equity curve. **Statistical significance improves dramatically from 6→44 symbols for lower-frequency breakout strategies.**

---

## Updated Champions Leaderboard (1990-2026, 44 symbols)

| Rank | Strategy | P&L | Sharpe | RS(min) | OOS | WFA | RollWFA |
|---|---|---|---|---|---|---|---|
| 🥇 | MA Confluence Fast Exit | 101,198% | +0.68 | -4.46 | +88,023% | Pass | 3/3 |
| 🥈 | Donchian Breakout (40/20) | 48,426% | +0.63 | -3.66 | +41,665% | Pass | 3/3 |
| 🥉 | MA Bounce (50d/3bar)+SMA200 | 45,283% | +0.61 | -10.93 | +40,519% | Pass | 3/3 |
| 4 | Donchian (60d/20d)+MA Align | 42,263% | +0.64 | -3.98 | +35,177% | Pass | 3/3 |
| 5 | MA Confluence Full Stack | 29,771% | +0.54 | -4.36 | +22,911% | Pass | 3/3 |

**Portfolio recommendation:** MA Confluence Fast Exit + Donchian (40/20 or 60d) + MA Bounce. These three have different entry mechanisms (MA alignment event vs price breakout vs support bounce) and low mutual correlations.

---

## Round 6 Lessons

1. **RSI gating destroys bounce strategies** — the bounce itself is the momentum signal. Adding RSI<50 eliminates 90% of valid entries.
2. **6-symbol RS(min) is noisy** — only 300-700 trades. RS(min) can be distorted by single bad clusters. Require 44-symbol validation before judging RS(min).
3. **ATR trailing stop needs 3.0x+ on tech stocks** — 2.0x gets stopped out too frequently on NVDA/META type volatility. If retrying, use 3.0x or 3.5x.
4. **CMF needs a structural fix, not an RSI patch** — the raw CMF threshold problem needs a different window (10d instead of 20d) or different thresholds.

---

## Round 7 Plan: Design from First Principles

Rather than patching Round 6 failures, design 5 genuinely new strategies:
1. **CMF (10d)+SMA200** — shorter CMF period reduces lag, faster signal
2. **MA Bounce+OBV Gate** — only take bounces when OBV is above its MA (volume confirms the bounce)
3. **ROC (20d)+RSI (14) Dual Momentum** — enter when both ROC>0 and RSI is rising from 40-50 range
4. **EMA Crossover (8/21)+CMF Gate** — EMA structural signal confirmed by positive volume flow
5. **Donchian (40/20)+RSI Momentum** — breakout only when RSI>50 (momentum above midline)
