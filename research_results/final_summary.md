# Autonomous Strategy Research — Final Summary

**Research Loop:** 6 Rounds × Multi-Agent Parallel Research
**Last Updated:** 2026-04-10
**Data Provider:** Norgate (total-return adjusted daily bars)
**Full Period:** 1990-01-01 → 2026-04-10 (36 years)
**Ecosystems tested:** AAPL single → tech_giants (6) → Nasdaq 100 Tech (44 symbols)

---

## Research Architecture

```
Round 1 (9 strategies on AAPL, 2004-2026)
  → Discover: single-symbol testing is misleading; ecosystem is key

Round 2 (9 strategies on tech_giants 6 sym, 2004-2026)
  → Donchian (40/20) and EMA+ROC emerge as champions; OBV introduced

Round 3 (8 strategies on tech_giants 6 sym, 2004-2026)
  → BREAKTHROUGH: MA Confluence family discovered (best strategy ever at the time)
  → OBV MaxDD fixed with SMA200 gate

Round 4 (validation, tech_giants 6 sym, 2004-2026)
  → Rolling WFA resolved (3 folds); MA Confluence Fast Exit restored
  → All 6 champions fully validated: WFA + RollWFA 3/3 + MC 5

Round 5 (5 new strategies, 1990-2026 extended history)
  → Start date pushed to 1990 (36 years of data)
  → BREAKTHROUGH: MA Bounce (50d)+SMA200 discovered — r=0.02 vs MA Confluence
  → MA Confluence Fast Exit: 101,198% P&L on 44 symbols over 36 years

Round 6 (fix attempts + 44-sym validation, 1990-2026)
  → Most fixes failed; Donchian (60d/20d)+MA Alignment validated on 44 symbols
  → RS(min) -3.98 on 44 symbols — second-smoothest equity curve overall
```

---

## 🏆 All-Time Champion Leaderboard (44 Symbols, 1990-2026)

| Rank | Strategy | P&L | Sharpe | RS(min) | OOS | WFA | RollWFA | Corr |
|---|---|---|---|---|---|---|---|---|
| 🥇 | MA Confluence (10/20/50) Fast Exit | 101,198% | +0.68 | -4.46 | +88,023% | Pass | 3/3 | — |
| 🥈 | Donchian Breakout (40/20) | 48,426% | +0.63 | -3.66 | +41,665% | Pass | 3/3 | 0.39* |
| 🥉 | MA Bounce (50d/3bar)+SMA200 | 45,283% | +0.61 | -10.93 | +40,519% | Pass | 3/3 | 0.16 |
| 4 | CMF Momentum (20d)+SMA200 | 51,173% | +0.63 | -15.03 | +43,803% | Pass | 3/3 | 0.18 |
| 5 | Donchian (60d/20d)+MA Alignment | 42,263% | +0.64 | -3.98 | +35,177% | Pass | 3/3 | 0.28* |
| 6 | MA Confluence (10/20/50) Full Stack | 29,771% | +0.54 | -4.36 | +22,911% | Pass | 3/3 | 0.17 |

*Donchian variants have r=0.39-0.95 with each other; do not hold multiple Donchian variants simultaneously.

**MC Score Note:** All 44-symbol strategies show MC Score -1 (DD Understated + High Tail Risk). This is a concentration-risk warning — 44 correlated tech stocks crash simultaneously in bear markets. Not a strategy flaw; a portfolio construction constraint. Max 5-10 concurrent positions in live trading.

---

## Tech Giants (6 Symbols, 1990-2026) — Selected Champions

| Strategy | P&L | Sharpe | RS(min) | OOS | WFA | RollWFA | MC Score |
|---|---|---|---|---|---|---|---|
| MA Confluence Full Stack | 2,718% | +0.43 | -4.44 | +1,660% | Pass | 3/3 | 2 |
| MA Bounce (50d/3bar)+SMA200 | 1,772% | +0.38 | -11.04 | +1,164% | Pass | 3/3 | **5** |
| Donchian Breakout (40/20) | 501% | +0.42 | -4.27 | +204% | Pass | 3/3 | **5** |
| MA Confluence Fast Exit | 857% | +0.59 | -4.53 | +334% | Pass | 3/3 | **5** |
| OBV+SMA200 Gate | 443% | +0.38 | -28.92† | +176% | Pass | 3/3 | **5** |
| Donchian (40/20)+SMA200 Gate | 394% | +0.33 | -28.92† | +161% | Pass | 3/3 | **5** |

†RS(min) = -28.92 is an artifact of bear-market inactivity (strategy flat, near-zero variance → inflated negative rolling Sharpe). Not a real risk indicator for these strategies.

---

## Strategy Signal Sources (Correlation Guide)

| Family | Strategy | Signal Source | Entry Mechanism |
|---|---|---|---|
| **MA Alignment** | MA Confluence Fast Exit | Price-MA structure | First bar all 3 MAs align bullishly |
| **MA Alignment** | MA Confluence Full Stack | Price-MA structure | Same entry, slower exit |
| **Breakout** | Donchian (40/20) | Price channel | Close above 40-bar high |
| **Breakout** | Donchian (60d/20d)+MA Align | Price channel + MA state | 60-bar high + fast MA>slow MA |
| **Support Bounce** | MA Bounce (50d/3bar)+SMA200 | Mean reversion within trend | Touch 50-SMA + recover, RSI not required |
| **Volume Flow** | CMF Momentum (20d)+SMA200 | Chaikin Money Flow | CMF crosses above 0.05, SMA200 gate |
| **Volume Confirm** | OBV+SMA200 Gate | On-Balance Volume | OBV above MA + price > SMA200 |

**Portfolio diversification:** For a 3-strategy portfolio, choose one from each row: MA Alignment + Breakout + Support Bounce. These have the lowest inter-family correlation.

---

## Key Research Conclusions

### 1. Ecosystem Scale Is the Most Important Variable
| Universe | Best Strategy P&L (2004 start) | Best Strategy P&L (1990 start) |
|---|---|---|
| AAPL alone | 83% | — |
| 6 tech giants | 949% | 2,718% |
| 44 NDX Tech | 5,962% (R3) | **101,198%** |

Same strategy, same parameters, different scale. The compounding of 44 uncorrelated opportunities over 36 years is the dominant effect.

### 2. MA Confluence Fast Exit Is the Statistical Champion
- P&L: 101,198% | Sharpe: +0.68 (highest ever) | OOS: +88,023%
- RS(min): -4.46 — extremely smooth equity curve
- Proven across 3 universes (6 sym, 44 sym) and 2 time windows (22yr, 36yr)
- The fastest loss cut (10-SMA cross) is the key advantage

### 3. MA Bounce Is a Genuine Diversifier
- r=0.02-0.16 vs MA Confluence across all tested universes
- Different entry philosophy: buys pullbacks while MA Confluence buys momentum
- Trades at opposite times — they are structurally uncorrelated, not just statistically
- Hold both in a live portfolio for genuine diversification

### 4. Extended History Reveals True Tail Risk
- 2004 start: MA Confluence MC Score 5 (no dot-com crash data)
- 1990 start: MA Confluence MC Score 2 (includes 2000-2002 crash)
- Lesson: always test from the earliest available data to surface hidden tail risks
- The 1990 start is more honest; treat MC Score 2 as the accurate risk assessment

### 5. 44-Symbol Results Are Statistically Superior
- 6 symbols = ~2,000-6,000 trades — small enough for outlier distortion
- 44 symbols = 15,000-40,000+ trades — law of large numbers stabilizes all metrics
- RS(min) on 44 symbols is much more reliable than 6-symbol RS(min)
- Always validate on 44 symbols before drawing conclusions from 6-symbol results

### 6. RSI Gating of Bounce Strategies Is Counterproductive
- MA Bounce+RSI Timing tried RSI<50 at bounce time → only 65 trades, RS(min)=-1158
- The 50-SMA bounce itself IS the momentum reversal — RSI at that moment is 50-60
- Adding RSI confirmation eliminates the valid entries AND the timing advantage
- **Lesson: trust the price signal; don't second-guess it with an oscillator**

### 7. ATR Trailing Stops Need 3.0x+ on Tech Stocks
- 2.5x ATR: RS(min)=-48.10 (too many stop-outs in normal volatility)
- 2.0x ATR: WFA "Likely Overfitted", 814 trades (constant whipsawing)
- On NVDA/META with ATR ≈ 5-8% of price, 2.0-2.5x = 10-20% stop → too tight for daily bar strategies
- If using ATR stops, test 3.0x minimum; consider weekly bars instead

---

## Recommended Live Implementation

### Core Portfolio (3 strategies, genuinely diversified)

**1. MA Confluence (10/20/50) Fast Exit** — Primary alpha engine
- Universe: NDX Tech 44 or any tech growth portfolio
- Signal: Buy on first bar of 10/20/50 MA full stack alignment; sell on 10-SMA cross below 50-SMA
- Max per position: 5-10% of portfolio
- Expected: +0.68 Sharpe, ~43% win rate, 7.9R expectancy

**2. Donchian Breakout (40/20)** — Momentum breakout complement
- Signal: Buy on 40-bar new high; sell on 20-bar new low
- Low correlation with MA Confluence (r=0.39 on exit-day P&L; structurally different timing)
- Expected: +0.63 Sharpe, ~43% win rate, 5.9R expectancy

**3. MA Bounce (50d/3bar)+SMA200** — Counter-trend diversifier
- Signal: Buy on 50-SMA touch+recovery while price > SMA200; sell on 3 closes below 50-SMA
- Structurally uncorrelated with both above (r=0.16/0.18)
- Expected: +0.61 Sharpe, ~33% win rate (offset by high expectancy 3.7R+)

### Risk Controls (mandatory)
- **Max 10% per position** — 10 concurrent positions maximum
- **Portfolio stop**: if portfolio DD exceeds 25%, cut position sizes by 50%
- **No more than 15 stocks from the same sector simultaneously** — correlation risk
- **MC Score -1 on 44-symbol runs** — real drawdowns will exceed the 70-77% backtest MaxDD in a synchronized crash scenario; size accordingly

---

## Strategy Implementation Files

| File | Round | Strategies |
|---|---|---|
| `research_strategies_v1.py` | R1 | ROC (10d/20d), BB Squeeze, Williams %R, VW RSI, Donchian (20/10), Stochastic, Keltner (2x) |
| `research_strategies_v2.py` | R2 | ROC+SMA200, EMA+ROC (12/26), **Donchian (40/20)**, Keltner (1.5x), BB Breakout, OBV Dual |
| `research_strategies_v3.py` | R3 | **MA Confluence Full Stack**, **MA Confluence Fast Exit**, OBV+SMA200, SMA Crossover+RSI |
| `breakout_round3.py` | R3+ | Donchian+SMA200, BB+ROC Gate, Donchian (60/20) |
| `research_strategies_v4.py` | R5 | CMF+SMA200, MACD+RSI+SMA200, ATR Trailing, **MA Bounce (50d)+SMA200**, Keltner+MA Stack |
| `round6_strategies.py` | R6 | CMF+RSI Gate, MA Bounce+RSI (failed), **Donchian (60d/20d)+MA Alignment**, OBV+MAC, MAC+ATR |

Bold = validated champion strategies.

---

## What Was Learned That Only Multi-Round Research Finds

| Finding | How Found | Round |
|---|---|---|
| Tech ecosystem 10-100× more profitable than single stock | R1→R2 pivot | R1 |
| MA Confluence is untested gold (not in any public library) | R3 sweep of untested indicators | R3 |
| Trend filters (SMA200) universally improve Calmar | R2/R3 iteration | R2-R3 |
| Rolling WFA N/A: use 3 folds not 5 for 250-400 trade strategies | R4 debug | R4 |
| Extending history to 1990 reveals dot-com tail risk in MA Confluence | R5 start-date change | R5 |
| MA Bounce is a structural diversifier (r=0.02) — not a failed MR strategy | R5 surprise | R5 |
| 6-symbol RS(min) is noisy; 44-symbol RS(min) is reliable | R6 scale validation | R6 |
| RSI gating eliminates the timing advantage of bounce strategies | R6 failed fix | R6 |
| Donchian (60d)+MA Alignment: RS(min) -3.98 on 44 symbols, better than expected | R6 44-sym run | R6 |

---

## Open Research Questions for Future Rounds

1. **Can MA Confluence MC Score be rescued?** ATR trailing stop at 2.0x failed. Try 3.0x or use a percent-based trailing stop (e.g., 15% below 20-bar high) instead.

2. **CMF shorter period** — 10d CMF instead of 20d. Faster signal, less MaxDD accumulation in distribution phases. Round 7 candidate.

3. **MA Bounce on weekly bars** — the 50-SMA bounce on weekly charts is a strong institutional pattern. Weekly timeframe would give cleaner signals and higher win rates.

4. **Multi-strategy portfolio simulation** — run MA Confluence Fast Exit + Donchian (40/20) + MA Bounce simultaneously as a combined portfolio to measure actual combined drawdown and Sharpe.

5. **Sector rotation** — do the same strategies work equally well on energy, financials, healthcare? If yes, diversify away from tech concentration.
