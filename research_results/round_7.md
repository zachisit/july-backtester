# Research Round 7 — First-Principles Design + 44-Symbol Validation

**Date:** 2026-04-10
**Symbols (Phase A):** tech_giants.json (6 symbols) — 1990-2026
**Symbols (Phase B):** nasdaq_100_tech.json (44 symbols) — 1990-2026
**Run IDs:**
- Phase A (6 sym): research-v7-6sym_2026-04-10_22-10-57
- Phase B (44 sym): research-v7-44sym_2026-04-10_22-11-57

---

## Objective

Design 5 genuinely new strategies from first principles (not patches). Avoid signal source overlap with existing champions. Test on 6 symbols, validate best on 44 symbols.

---

## Phase A: 6-Symbol Results

| Strategy | P&L | Sharpe | RS(min) | OOS | WFA | RollWFA | Trades | SQN |
|---|---|---|---|---|---|---|---|---|
| CMF (10d) + SMA200 Gate | 272.39% | **-0.13** | -13.87 | +144.29% | Pass | 3/3 | **1394** | 3.68 |
| Donchian (40/20) + RSI Momentum Gate | **1152.27%** | 0.26 | -6.70 | +619.16% | Pass | 3/3 | 353 | 5.23 |
| EMA Crossover (8/21) + CMF Hold Gate | 491.96% | 0.05 | -5.61 | +266.77% | Pass | 3/3 | **1528** | 4.25 |
| ROC (20d) + MA Full Stack Gate | 591.85% | 0.10 | -7.51 | +319.73% | Pass | 3/3 | 1176 | 4.73 |
| SMA Crossover (20/50) + OBV Confirmation | 560.66% | 0.08 | -6.64 | +309.25% | Pass | 3/3 | 1220 | 4.32 |
| MA Confluence Fast Exit (benchmark) | 1695.84% | 0.35 | -5.49 | +986.23% | Pass | 3/3 | 429 | 5.63 |
| MA Bounce 50d (benchmark) | 1771.83% | 0.38 | -11.04 | +1164.40% | Pass | 3/3 | 660 | 5.70 |

### Eliminated After Phase A

**CMF (10d) + SMA200 Gate**: Negative Sharpe (-0.13). The 10-bar window is too noisy — 1,394 trades (vs ~800 for 20-bar version). The hypothesis was wrong: shorter CMF period doesn't reduce MaxDD, it increases whipsaw. The problem with CMF was never the period length — it's that CMF hovers near zero frequently, and tighter windows cause more crossings of the buy/sell thresholds. **Lesson: don't shorten CMF to fix RS(min) problems.**

**EMA Crossover (8/21) + CMF Hold Gate**: MaxRcvry 5,008 days (13+ years) — longest recovery of any Round 7 strategy. The CMF sustained hold condition exits too early when EMA is still bullish, then re-enters after the next EMA cross, creating extended flat/churning periods. This is likely the same overcrowding problem seen with dual-condition exits that conflict: EMA says hold, CMF says exit, then re-enter after EMA confirms again.

---

## Phase B: 44-Symbol Validation

Validated the top 3 new strategies + 2 benchmarks on 44 symbols (1990-2026, 36 years).

| Strategy | P&L (%) | Sharpe | RS(min) | OOS | WFA | RollWFA | Trades | SQN |
|---|---|---|---|---|---|---|---|---|
| **Donchian (40/20) + RSI Momentum Gate** | **48,426%** | **+0.63** | **-3.66** | **+41,665%** | **Pass** | **3/3** | **1760** | **6.10** |
| ROC (20d) + MA Full Stack Gate | 14,518% | +0.50 | -3.83 | +12,472% | Pass | 3/3 | 5158 | **6.95** |
| SMA Crossover (20/50) + OBV Confirmation | 10,841% | +0.46 | -4.25 | +8,832% | Pass | 3/3 | 5625 | 6.59 |
| MA Confluence Fast Exit (benchmark) | 101,198% | +0.68 | -4.46 | +88,023% | Pass | 3/3 | 2080 | 6.32 |
| Donchian Breakout (40/20) (benchmark) | 48,426% | +0.63 | -3.66 | +41,665% | Pass | 3/3 | 1760 | 6.10 |

---

## Critical Finding: RSI Gate on Donchian is Redundant

**Donchian (40/20) + RSI Momentum Gate == Donchian Breakout (40/20)** — exactly.

The correlation engine flagged r=+1.00 between these two strategies. P&L, Sharpe, RS(min), OOS, trade count — all identical to 6 decimal places.

**Root cause**: When price reaches a 40-bar new high, RSI>50 is almost always already satisfied. A 40-bar new high means the stock has been in strong upward momentum for 8+ weeks. RSI is definitionally above 50 in this regime — the filter never actually rejects a trade.

On the 6-symbol run, the RSI-gated version appeared to show higher P&L (1,152% vs 501% for historical Donchian). But this comparison was invalid — the historical 501% figure came from a 2004-start, smaller-universe run. On the same 1990-start 6-symbol universe both would be near-identical.

**Lesson: Do not add RSI gates to price-breakout strategies.** A N-bar new high IS a strong momentum signal by definition. RSI at that moment is almost always above 50. The gate is redundant and adds parameter complexity with zero benefit.

---

## Genuine New Discoveries

### ROC (20d) + MA Full Stack Gate
- **P&L**: 14,518% | **Sharpe**: +0.50 | **RS(min)**: -3.83 | **OOS**: +12,472%
- **SQN 6.95** — highest SQN of any strategy tested across all rounds
- 5,158 trades (36 years × 44 symbols) — law of large numbers fully engaged
- RS(min) -3.83 is the second-best in all research (only Donchian 40/20 at -3.66 is smoother)
- P&L is below the top tier (101K, 48K, 45K) but the SQN suggests extremely high statistical confidence
- Signal source: ROC (price velocity) + MA stack (trend quality) = two angles on momentum

### SMA Crossover (20/50) + OBV Confirmation
- **P&L**: 10,841% | **Sharpe**: +0.46 | **RS(min)**: -4.25 | **OOS**: +8,832%
- 5,625 trades — highest trade count of any validated strategy
- SQN 6.59 — very high confidence
- Signal source: structural MA cross + volume flow = price and volume aligned

Both strategies use high trade counts (5K+) to achieve extremely high SQN — the law of large numbers effect. Lower per-trade expectancy compensated by volume of opportunities.

---

## Updated Leaderboard (44 Symbols, 1990-2026) — After Round 7

| Rank | Strategy | P&L | Sharpe | RS(min) | OOS | WFA | RollWFA |
|---|---|---|---|---|---|---|---|
| 🥇 | MA Confluence (10/20/50) Fast Exit | 101,198% | +0.68 | -4.46 | +88,023% | Pass | 3/3 |
| 🥈 | Donchian Breakout (40/20) | 48,426% | +0.63 | -3.66 | +41,665% | Pass | 3/3 |
| 🥉 | MA Bounce (50d/3bar)+SMA200 | 45,283% | +0.61 | -10.93 | +40,519% | Pass | 3/3 |
| 4 | Donchian (60d/20d)+MA Alignment | 42,263% | +0.64 | -3.98 | +35,177% | Pass | 3/3 |
| 5 | CMF Momentum (20d)+SMA200 | 51,173% | +0.63 | -15.03 | +43,803% | Pass | 3/3 |
| 6 | MA Confluence Full Stack (10/20/50) | 29,771% | +0.54 | -4.36 | +22,911% | Pass | 3/3 |
| **7** | **ROC (20d) + MA Full Stack Gate** | **14,518%** | **+0.50** | **-3.83** | **+12,472%** | **Pass** | **3/3** |
| **8** | **SMA Crossover (20/50) + OBV Confirmation** | **10,841%** | **+0.46** | **-4.25** | **+8,832%** | **Pass** | **3/3** |

---

## Round 7 Lessons

1. **RSI>50 is redundant on N-bar new-high breakouts** — a 40-bar new high definitionally implies RSI>>50. Adding an RSI gate to price breakouts adds parameters with zero filtering benefit. r=+1.00 proven on 44 symbols.

2. **CMF window length is not the problem** — shortening CMF from 20 to 10 bars made things worse (negative Sharpe). The underlying issue is that CMF hovers near zero, creating threshold-crossing noise. Shorter windows amplify this. Don't fix CMF by shortening it.

3. **High trade count + moderate expectancy = high SQN** — ROC + MA Stack (5,158 trades, SQN 6.95) and SMA + OBV (5,625 trades, SQN 6.59) achieve the highest SQNs via trade count, not per-trade edge. These are statistically the most reliable strategies even though their P&L is lower.

4. **Sustained hold conditions with conflicting exits create long recovery periods** — EMA (8/21) + CMF Hold Gate had MaxRcvry 5,008 days because the dual-condition exit causes position whipsaw: EMA says hold while CMF says exit, creating many partial periods of flat equity.

---

## Round 8 Plan

Four directions worth exploring:

1. **MA Confluence + ATR Trailing Stop (3.0x or 3.5x)** — Round 6 showed 2.0x is too tight on tech (NVDA ATR ≈ 5-8%). Try 3.0x/3.5x multiplier to rescue MC Score without destroying the equity curve. This is the highest-priority open question from the final_summary.

2. **EMA (8/21) + OBV Hold Gate** — Replace CMF with OBV as the sustained hold condition. OBV doesn't have the zero-hovering problem that CMF has. Same architecture as EMA+CMF but with a more stable volume indicator.

3. **Donchian (40/20) + Volume Spike Confirmation** — Instead of RSI (proven redundant), gate breakouts on a volume spike (close > 40-bar high AND volume > 1.5× 20-bar average). Volume breakouts are much more selective than RSI gates. This tests a real hypothesis: breakouts on below-average volume often fail.

4. **MA Bounce (50d) + Volume Confirmation** — Gate MA Bounce entries on OBV being above its MA at the time of the bounce. Same r=0.02 diversifier but with a volume quality filter — should improve win rate without destroying the timing signal.
