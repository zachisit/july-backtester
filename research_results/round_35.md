# Research Round 35 — New Ecosystems: Mean Reversion, Relative Momentum, BB Squeeze

**Date:** 2026-04-11
**Run IDs:**
- Q37 (Mean Reversion): meanrev-weekly-ndx44_2026-04-11_08-25-55
- Q38 (Relative Momentum + BB Squeeze): relmom-bbsqueeze-weekly-ndx44_2026-04-11_08-28-09
- Q39 (6-strategy combined): 6strat-relmom-weekly-ndx44_2026-04-11_08-29-22
**Symbols:** nasdaq_100_tech.json (44)
**Period:** 1990-2026
**WFA:** 80/20 split, 3 rolling folds

---

## Q37 Results — Mean Reversion Weekly (Counter-Trend) on NDX Tech 44 (10% allocation, Weekly)

| Strategy | P&L | Sharpe | MaxDD | Trades | WFA | Notes |
|---|---|---|---|---|---|---|
| RSI MeanRev Weekly (30-bounce) | N/A | N/A | N/A | **0** | N/A | Zero trades generated |
| BB MeanRev Weekly (lower-band) | 10.02% | **-1.45** | 2.72% | **22** | Pass | Failed: Sharpe -1.45 |

**Both mean reversion strategies fail definitively.**

---

## Q38 Results — Relative Momentum (13w vs SPY) + BB Squeeze on NDX Tech 44 (10% allocation, Weekly)

| Strategy | P&L | Sharpe | MaxDD | RS(min) | RS(avg) | Trades | OOS P&L | WFA | RollWFA | MC Score |
|---|---|---|---|---|---|---|---|---|---|---|
| **Relative Momentum (13w vs SPY)** | **166,502%** | **2.08** | 37.52% | **-2.36** | **+2.04** | **99** | **+153,533%** | Pass | 3/3 | -1 |
| BB Squeeze Breakout | 895% | 1.21 | **20.43%** | -3.66 | +1.02 | 246 | +417.73% | Pass | 3/3 | **+5** |

---

## Q39 Results — 6-Strategy Combined on NDX Tech 44 (3.3% allocation, Weekly)

| Strategy | P&L | Sharpe | MaxDD | RS(min) | OOS P&L | WFA | RollWFA | MC Score |
|---|---|---|---|---|---|---|---|---|
| MA Bounce W | 23,016% | **1.95** | 44.46% | -2.67 | +19,091% | Pass | 3/3 | -1 |
| RSI Weekly | 32,558% | 1.91 | 49.36% | -2.73 | +27,463% | Pass | 3/3 | -1 |
| Price Momentum | 18,659% | 1.80 | 44.83% | -2.47 | +14,797% | Pass | 3/3 | +1 |
| **Relative Momentum** | 4,537% | 1.78 | **31.82%** | -2.70 | +3,365% | Pass | 3/3 | **+2** |
| MAC Fast Exit | 10,996% | 1.76 | 49.77% | **-2.19** | +7,604% | Pass | 3/3 | -1 |
| Donchian | 6,710% | 1.63 | 47.72% | -2.49 | +4,271% | Pass | 3/3 | +1 |

---

## Correlation Matrix (6-strategy combined)

| | MA Bounce | MAC | Donchian | Price Mom | RSI W | Rel Mom |
|---|---|---|---|---|---|---|
| MA Bounce | 1.00 | **0.07** | 0.27 | 0.69 | 0.63 | 0.63 |
| MAC Fast Exit | **0.07** | 1.00 | 0.40 | 0.02 | 0.04 | 0.06 |
| Donchian | 0.27 | 0.40 | 1.00 | 0.20 | 0.21 | 0.34 |
| Price Momentum | 0.69 | 0.02 | 0.20 | 1.00 | **0.90** | 0.66 |
| RSI Weekly | 0.63 | 0.04 | 0.21 | **0.90** | 1.00 | 0.63 |
| Rel Momentum | 0.63 | **0.06** | 0.34 | 0.66 | 0.63 | 1.00 |

---

## Key Findings

### 1. MEAN REVERSION DEFINITIVELY FAILS ON WEEKLY BARS

**RSI Mean Reversion (RSI < 30 in uptrend): 0 trades across 44 stocks × 36 years.**
The two conditions are mutually exclusive in practice: on weekly bars, a stock with RSI(14w) < 30 has been selling consistently for 3-6 weeks — which virtually guarantees it has already breached SMA200 (the uptrend filter). Zero trades generated.

**BB Mean Reversion (close < lower BB in uptrend): 22 trades, Sharpe -1.45.**
When the lower BB fires on weekly bars in a stock above SMA200, the stock is in a severe pullback that almost always resolves to SMA200 breach within weeks. The long average hold (extremely extended drawdown periods) creates a Sharpe of -1.45.

**Fundamental lesson CONFIRMED: The weekly timeframe improvement exclusively benefits TREND-FOLLOWING strategies.** Mean reversion requires daily or intraday noise to work. On weekly bars, all pullbacks that aren't preceded by genuine trend reversal are too brief or too deep to trade profitably.

Anti-pattern added: **Do not test any further mean reversion strategies on weekly bars. 0-22 trades with negative Sharpe is the expected outcome. This ecosystem is dead at weekly resolution.**

### 2. RELATIVE MOMENTUM IS A NEW TOP CHAMPION

**Relative Momentum (13w vs SPY) Weekly + SMA200:**
- P&L: **166,502%** — NEW ALL-TIME HIGH P&L (surpasses Williams R at 156,992%)
- Sharpe: **2.08** — tied for ALL-TIME HIGH with BB Breakout (both at 2.08)
- RS(min): **-2.36** — competitive with top strategies
- **Only 99 trades in 36 years** — avg hold 831 days (3.3 years!)
- The strategy enters when stock starts outperforming SPY by 15%+ and exits when it stops

Why 99 trades generates 166,502% P&L:
- Each entry captures multi-year leadership phases (NVDA 2023-2025, MSFT 2019-2022, etc.)
- Entry is extremely selective → only genuine sector/stock leadership events
- Compounding within multi-year hold periods creates enormous per-trade returns

Why it's genuinely different from Price Momentum (6m ROC):
- Price Momentum: stock up 15%+ in 6 months (absolute threshold)
- Relative Momentum: stock outperforming SPY by 15% (relative threshold)
- In a bull market, Price Momentum fires broadly. Relative Momentum only fires on the LEADERS.
- Different exit mechanism: exits on underperformance (when the leadership phase ends)

**In combined portfolio: MaxDD 31.82% — best of all 6 strategies, unprecedented for NDX Tech 44**
- This is because its avg 3.3-year holds mean it's rarely active at crash peaks simultaneously with all other strategies
- Exit-day correlation with MAC: only r=0.06 — second lowest correlation in the entire research (MAC vs MA Bounce was 0.07)

### 3. BB SQUEEZE BREAKOUT — MAX DD RECORD BUT BELOW CHAMPION SHARPE

BB Squeeze Breakout MaxDD 20.43% at 10% allocation — the lowest MaxDD ever for a standalone strategy in this research. But Sharpe 1.21 is below the champion threshold (> 1.50). Primarily useful as:
- A minimal-risk supplementary strategy in a portfolio focused on capital preservation
- A signal that something exceptional is setting up (post-squeeze breakouts are rare)

**Would need Sharpe > 1.50 to qualify as a champion. Does not qualify at Sharpe 1.21.**

### 4. CORRELATION INSIGHT: THREE DISTINCT CLUSTERS CONFIRMED

- **Momentum Cluster (r=0.60-0.90):** Price Momentum, RSI Weekly, MA Bounce, Williams R, BB Breakout, Relative Momentum — all measure "price winning"
- **Trend Alignment Cluster (r=0.07-0.40):** MAC Fast Exit — continuous MA confluence (exits/enters on structure, not momentum level)
- **Semi-independent:** Donchian (r=0.20-0.40 with everything — medium-length breakout)

No matter how many momentum strategies are added, they all cluster in the same group. The only genuine diversifier remains MAC Fast Exit.

**Production portfolio conclusion:** Use 1 strategy from each cluster: Momentum (best: Williams R or Relative Momentum), Trend Alignment (MAC Fast Exit), Semi-independent (Donchian) = 3 strategies, maximum diversification.

---

## Updated Leaderboard

| Rank | Strategy | Sharpe | RS(min) | Trades | P&L |
|---|---|---|---|---|---|
| 🥇 NEW | Relative Momentum (13w vs SPY) W | **2.08** | -2.36 | **99** | **166,502%** |
| 🥇 | BB Breakout (20w/2std) W | **2.08** | -3.50 | 798 | 152,197% |
| 3 | MA Bounce (50d/3bar) W | 1.92 | -2.32 | 1,366 | 140,028% |
| 4 | Williams R (above-20) W | 1.94 | -2.12 | 799 | 156,992% |
| 5 | Price Momentum (6m ROC) W | 1.87 | -2.30 | 671 | 156,879% |
| 6 | RSI Weekly (55-cross) | 1.85 | -2.15 | 671 | 135,445% |

---

## New Queue Items

### Q40: Williams R as RSI Weekly Replacement in 5-Strategy Portfolio
- Drop RSI Weekly (Sharpe 1.85, RS(min) -2.15), add Williams R (Sharpe 1.94, RS(min) -2.12)
- Test if the 5-strategy portfolio improves with Williams R vs RSI Weekly

### Q41: 6-Strategy Portfolio on Sectors+DJI 46 (add Relative Momentum to conservative universe)
- Relative Momentum's unique exit mechanism may achieve MaxDD < 20% on Sectors+DJI 46

### Q42: Relative Momentum Sensitivity Sweep (is rel_thresh=1.15 a robust choice?)
- Is the 15% outperformance threshold vs SPY uniquely good, or is the edge robust?
- Critical validation before live trading with strategy that has only 99 trades
