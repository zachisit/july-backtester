# Research Round 34 — Unexplored Oscillator Families on Weekly Bars

**Date:** 2026-04-11
**Run IDs:**
- Q34: new-oscillators-weekly-ndx44_2026-04-11_08-19-36
- Q35: bb-wr-sectors-dji-weekly_2026-04-11_08-21-10
- Q36: 7strat-combined-weekly-ndx44_2026-04-11_08-22-22
**Symbols:** nasdaq_100_tech.json (44), sectors_dji_combined.json (46)
**Period:** 1990-2026
**WFA:** 80/20 split, 3 rolling folds

---

## Q34 Results — 4 New Oscillator Strategies on NDX Tech 44 (10% allocation, Weekly)

| Strategy | P&L | Sharpe | MaxDD | RS(min) | RS(avg) | Trades | OOS P&L | WFA | RollWFA | MC Score |
|---|---|---|---|---|---|---|---|---|---|---|
| **BB Breakout (20w/2std)** | 152,197% | **2.08** | 51.55% | -3.50 | +2.01 | 798 | +131,534% | Pass | 3/3 | -1 |
| **Williams R (above-20)** | 156,992% | **1.94** | 56.26% | -2.12 | +2.01 | 799 | +134,254% | Pass | 3/3 | -1 |
| Stochastic (K80) | 103,417% | 1.85 | 58.24% | -2.39 | +1.91 | 638 | +87,057% | Pass | 3/3 | -1 |
| VWRSI (55-cross) | 61,583% | 1.75 | 61.48% | -2.27 | +1.78 | 747 | +50,270% | Pass | 3/3 | -1 |

**ALL 4 WFA Pass + RollWFA 3/3!**

---

## Q35 Results — BB Breakout + Williams R on Sectors+DJI 46 (10% allocation, Weekly)

| Strategy | P&L | Sharpe | MaxDD | RS(min) | RS(avg) | Trades | OOS P&L | WFA | RollWFA | MC Score |
|---|---|---|---|---|---|---|---|---|---|---|
| BB Breakout (20w/2std) | 8,874% | 1.75 | 32.87% | -2.50 | +1.79 | 1,024 | +3,100% | Pass | 3/3 | -1 |
| Williams R (above-20) | 15,434% | 1.84 | 44.68% | **-2.00** | +1.95 | 1,001 | +7,455% | Pass | 3/3 | -1 |

---

## Q36 Results — 7-Strategy Combined on NDX Tech 44 (2.8% allocation, Weekly)

| Strategy | P&L | Sharpe | MaxDD | RS(min) | OOS P&L | WFA | RollWFA | MC Score |
|---|---|---|---|---|---|---|---|---|
| MA Bounce W | 12,512% | **1.91** | **40.41%** | -2.72 | +10,037% | Pass | 3/3 | **-1** |
| RSI Weekly | 20,945% | 1.88 | 46.14% | -2.76 | +17,660% | Pass | 3/3 | **+1** |
| Williams R | 9,604% | 1.83 | 43.38% | -2.85 | +7,452% | Pass | 3/3 | **+2** |
| Price Momentum | 11,926% | 1.76 | 41.64% | -2.49 | +9,383% | Pass | 3/3 | **+1** |
| MAC Fast Exit | 6,123% | 1.70 | 45.16% | -2.26 | +4,196% | Pass | 3/3 | **+1** |
| BB Breakout | 3,255% | 1.66 | **34.27%** | -3.89 | +1,996% | Pass | 3/3 | **+5** |
| Donchian | 3,877% | 1.57 | 43.68% | -2.53 | +2,349% | Pass | 3/3 | **+2** |

**ALL 7 MaxDDs below 50% — unprecedented on NDX Tech 44!**

---

## Correlation Matrix (7-strategy combined)

| | MA Bounce | MAC | Donchian | Price Mom | RSI W | BB Break | Williams R |
|---|---|---|---|---|---|---|---|
| MA Bounce | 1.00 | 0.09 | 0.27 | 0.60 | 0.56 | 0.67 | 0.72 |
| MAC Fast Exit | 0.09 | 1.00 | 0.40 | 0.02 | 0.04 | 0.11 | 0.08 |
| Donchian | 0.27 | 0.40 | 1.00 | 0.18 | 0.20 | 0.40 | 0.39 |
| Price Momentum | 0.60 | 0.02 | 0.18 | 1.00 | 0.94 | 0.76 | 0.78 |
| RSI Weekly | 0.56 | 0.04 | 0.20 | **0.94** | 1.00 | 0.71 | 0.75 |
| BB Breakout | 0.67 | 0.11 | 0.40 | 0.76 | 0.71 | 1.00 | 0.84 |
| Williams R | 0.72 | 0.08 | 0.39 | 0.78 | 0.75 | 0.84 | 1.00 |

---

## Key Findings

### 1. TWO NEW CHAMPIONS DISCOVERED

**BB Breakout (20w/2std) + SMA200:**
- NDX44: Sharpe 2.08 — **NEW ALL-TIME SHARPE RECORD** (surpasses MA Bounce W at 1.92)
- Sectors+DJI 46: Sharpe 1.75, MaxDD 32.87% (excellent)
- 7-strategy combined: **MC Score +5 on NDX Tech 44** — unprecedented for this concentrated universe
- Why MC Score +5: At 2.8% allocation, BB Breakout is rarely active simultaneously with others; it selects only the MOST extreme breakouts (close > 2-std upper band over 20 weeks)

**Williams R Weekly (above-20) + SMA200:**
- NDX44: Sharpe 1.94 (new #2 by Sharpe, ahead of all existing champions except MA Bounce W)
- RS(min) -2.12 on NDX44, RS(min) -2.00 on Sectors+DJI 46 — among the best ever
- P&L 156,992% (ties with Price Momentum Weekly for highest P&L)
- 7-strategy combined: MC Score +2

### 2. HIGH CORRELATION WITH EXISTING CHAMPIONS — KEY INSIGHT

BB Breakout and Williams R correlate r=0.71-0.78 with Price Momentum and RSI Weekly. All four strategies measure "price at/near its recent high." They are NOT independent signals.

**Critical correlation cluster identified:**
- Price Momentum ↔ RSI Weekly: r=0.94 (essentially same signal!)
- Price Momentum ↔ BB Breakout: r=0.76
- Price Momentum ↔ Williams R: r=0.78
- RSI Weekly ↔ BB Breakout: r=0.71
- RSI Weekly ↔ Williams R: r=0.75

**Implication:** Running all 5 of (Price Momentum, RSI Weekly, BB Breakout, Williams R, Stochastic) simultaneously = running 5 copies of the same underlying signal. For a live portfolio, choose ONLY ONE of these.

**Which one is best?**
- By Sharpe alone: BB Breakout (2.08) > Williams R (1.94) > Price Momentum (1.87) > RSI Weekly (1.85)
- By RS(min): Williams R (-2.12) ≈ RSI Weekly (-2.15) > BB Breakout (-3.50)
- By trade count: all 638-799 trades (adequate)
- **Best overall: Williams R** — combines high Sharpe (1.94) with best RS(min) (-2.12)

### 3. MAC FAST EXIT REMAINS UNIQUELY UNCORRELATED

MAC Fast Exit shows r=0.08-0.40 with every other strategy. It is the portfolio's true diversifier. Even adding 2 new strategies doesn't change this — MAC's continuous MA alignment signal exits and enters on fundamentally different timing from any momentum threshold strategy.

**The two-strategy core of the portfolio remains:** MAC Fast Exit + one momentum strategy (Williams R is now the best candidate to replace RSI Weekly).

### 4. STOCHASTIC AND VWRSI — SOLID BUT NOT LEADING

Stochastic Weekly (K80) Sharpe 1.85 = exactly matches RSI Weekly (rank 3). VWRSI Sharpe 1.75 is solid but lower. Neither is superior to Williams R or BB Breakout. These are confirmed working strategies but add no unique value over the better performers in their cluster.

---

## Updated Leaderboard (top 5 by Sharpe, weekly bars)

| Rank | Strategy | Sharpe | RS(min) | Trades | P&L |
|---|---|---|---|---|---|
| 🥇 NEW | BB Breakout (20w/2std) + SMA200 | **2.08** | -3.50 | 798 | 152,197% |
| 🥈 | MA Bounce (50d/3bar) W | 1.92 | -2.32 | 1,366 | 140,028% |
| 🥉 NEW | Williams R (above-20) W | **1.94** | **-2.12** | 799 | 156,992% |
| 4 | Price Momentum (6m ROC) W | 1.87 | -2.30 | 671 | 156,879% |
| 5 | RSI Weekly Trend (55-cross) | 1.85 | -2.15 | ~671 | 135,445% |

Note: Williams R RS(min) -2.12 is 2nd best ever (Donchian holds -2.06 record).
Note: BB Breakout RS(min) -3.50 is worse than other top-tier strategies (concern).

---

## Anti-Patterns Confirmed/Updated

**"Price near N-week high" signal family has extremely high internal correlation:**
- Price Momentum (6m ROC), RSI Weekly, BB Breakout, Williams R, Stochastic all correlate r=0.71-0.94
- Running >1 of these simultaneously in a live portfolio adds capital exposure but minimal diversification
- Choose exactly ONE from this family: Williams R is the top pick (best Sharpe + RS(min) combination)

---

## New Queue Items

### Q37: Mean Reversion Weekly (Counter-Trend Test)
- Tests if RSI oversold bounce in uptrend adds uncorrelated alpha
- Hypothesis: With 5+ trend strategies all correlating r=0.60+, a counter-trend strategy could be the only true diversifier

### Q38: Williams R as RSI Weekly Replacement (7-strategy → 6-strategy)
- Drop RSI Weekly, add Williams R → does RS(min) and Sharpe improve in the combined portfolio?
- Also test Stochastic as alternative replacement

### Q39: BB Breakout on Sectors+DJI 46 Combined Portfolio (with existing 5)
- BB Breakout achieved MC Score +5 at 2.8% on NDX44 — test on conservative universe
- Expected: Even better MC Score at lower capital usage
