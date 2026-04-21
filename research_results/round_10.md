# Research Round 10 — Weekly Timeframe Confirmation

**Date:** 2026-04-11
**Run IDs:**
- Queue Item 8 (MAC Fast Exit Weekly): mac-weekly_2026-04-10_23-04-51
- Queue Item 9 (Donchian Weekly): donchian-weekly_2026-04-10_23-05-25

---

## Objective

Test the weekly timeframe hypothesis across the remaining daily champions. Round 9 showed MA Bounce on weekly bars achieves Sharpe 1.92 vs 0.61 daily (3× improvement). Does this structural improvement hold for MA Confluence Fast Exit and Donchian (40/20)?

**Hypothesis:** Weekly bars improve ALL momentum and breakout strategies because:
1. Intra-week noise in daily data creates false entry and exit signals
2. Weekly bars represent a week's worth of consolidated market action — each signal carries more weight
3. Exit conditions (MA crossover, new 20-bar low) on weekly bars require genuine trend changes, not just 2-3 day dips

---

## Queue Item 8 — MAC Fast Exit on Weekly Bars (DONE — NEW CHAMPION)

**Config:** timeframe="W", MAC Fast Exit, 44 symbols, 10% allocation, 1990-2026

| Metric | Weekly | Daily | Improvement |
|---|---|---|---|
| P&L | 84,447% | 101,198% | -17% (fewer, larger moves captured) |
| Sharpe | **+1.80** | +0.68 | **+165% improvement** |
| RS(min) | **-2.54** | -4.46 | **1.75× better** |
| RS(avg) | +1.88 | — | — |
| WinRate | 41.98% | — | — |
| Trades | 1,896 | 2,080 | -9% (similar trade count) |
| MaxDD | 72.05% | 68.50% | -3.55pp worse |
| OOS P&L | +72,265% | +88,023% | -18% (fewer fast accelerations) |
| WFA | Pass | Pass | — |
| RollWFA | 3/3 | 3/3 | — |
| MC Score | -1 | -1 | same (concentration risk) |

**Why P&L is lower on weekly but Sharpe is dramatically better:**
- Daily MAC enters and exits on individual days' MA crossovers — it can ride rapid multi-day trend accelerations (NVDA going from $200 to $400 in 30 days)
- Weekly MAC only trades on weekly close signals — it misses some of the most aggressive trend accelerations but also avoids the whipsaw returns when those accelerations reverse
- The Sharpe improves because the trades that DO occur have much more consistent, sustainable returns — fewer -15% quick reversals

**MaxDD concern:** 72.05% vs 68.50% daily. The weekly MA crossover exit takes longer to fire at a market top — position drawdown deepens before the weekly close confirms the exit signal.

**VERDICT: NEW CHAMPION** — Sharpe 1.80 is 2.65× better than daily version. Worth the -17% P&L tradeoff and slight MaxDD increase for significantly better risk-adjusted returns.

---

## Queue Item 9 — Donchian (40/20) on Weekly Bars (DONE — NEW CHAMPION, BEST RS(min))

**Config:** timeframe="W", Donchian (40/20), 44 symbols, 10% allocation, 1990-2026

| Metric | Weekly | Daily | Improvement |
|---|---|---|---|
| P&L | 53,499% | 48,426% | **+10% better** |
| Sharpe | **+1.68** | +0.63 | **+167% improvement** |
| RS(min) | **-2.06** | -3.66 | **1.78× better (BEST OVERALL)** |
| RS(avg) | +1.78 | — | — |
| WinRate | 42.95% | — | — |
| Trades | 1,234 | 3,070 | -60% (40-week high is much rarer than 40-day) |
| MaxDD | 68.57% | 55.54% | -13pp worse |
| OOS P&L | +41,671% | +41,665% | virtually identical |
| WFA | Pass | Pass | — |
| RollWFA | 3/3 | 3/3 | — |
| MC Score | -1 | -1 | same |

**Why Donchian weekly has the BEST RS(min) of all strategies tested:**
- Weekly Donchian enters ONLY when price hits a 40-WEEK high (≈ 10-month high)
- This is a much stronger signal than a 40-DAY high (≈ 2-month high)
- A 10-month high represents genuine long-term momentum — institutional trend confirmation
- Entry quality is dramatically higher: fewer trades (1,234 vs 3,070) but each represents a more confirmed trend
- The exit (20-week new low ≈ 5-month new low) is very patient — once in a trend, holds through normal corrections
- Result: RS(min) -2.06 is the single best rolling Sharpe stress score of all 15+ strategies tested

**MaxDD concern:** 68.57% vs 55.54% daily. The 20-week exit (≈ 5-month new low) is very slow to fire — deep drawdowns can accumulate before the exit signal. This is the price of the patient hold.

**OOS identical to daily:** +41,671% vs +41,665% — remarkable coincidence. The weekly and daily Donchian generate almost identical cumulative OOS performance, despite wildly different trade timing and risk profiles.

**VERDICT: NEW CHAMPION** — RS(min) -2.06 is the best of ALL strategies tested. Sharpe 1.68 is 2.67× better than daily. Despite the MaxDD increase, the dramatically superior risk-adjusted return profile makes this a genuine champion.

---

## Weekly Timeframe Summary — All Three Core Champions

**The weekly timeframe is a structural finding — ALL three daily champions improve dramatically:**

| Strategy | Daily Sharpe | Weekly Sharpe | Daily RS(min) | Weekly RS(min) | Daily P&L | Weekly P&L |
|---|---|---|---|---|---|---|
| MA Bounce (50d/3bar) | 0.61 | **1.92** (+215%) | -10.93 | **-2.32** (+4.7×) | 45,283% | **140,028%** |
| MA Confluence Fast Exit | 0.68 | **1.80** (+165%) | -4.46 | **-2.54** (+1.75×) | 101,198% | **84,447%** |
| Donchian (40/20) | 0.63 | **1.68** (+167%) | -3.66 | **-2.06** (+1.78×) | 48,426% | **53,499%** |

**Consistent pattern across all three:**
- Sharpe improvement: 165-215% across all strategies
- RS(min) improvement: 1.75-4.7× across all strategies
- WinRate: all three improve to ~42-43% on weekly (daily baselines were 33-42%)
- MC Score: -1 on 44 tech stocks (unchanged — structural concentration risk)
- WFA Pass + RollWFA 3/3 on all three (not overfit)

**Tradeoffs (consistent across strategies):**
- MAC and Donchian: P&L slightly lower or similar on weekly bars
- MA Bounce: P&L dramatically higher on weekly bars (biggest beneficiary — bounce signals are most noise-sensitive)
- MaxDD: MAC weekly (+3.5pp worse), Donchian weekly (+13pp worse), MA Bounce weekly (-1pp better)

---

## Round 10 Lessons

1. **Weekly timeframe is a structural improvement for ALL momentum strategies** — not specific to MA Bounce. The consistency across three different strategy architectures (trend-following MA crossover, breakout channel, mean-reversion bounce) confirms this is a genuine market microstructure phenomenon: weekly bars filter out noise that causes false signals at the daily level.

2. **The RS(min) improvement is the most important finding** — all three strategies show RS(min) between -2.06 and -2.54 on weekly bars. This is dramatically better than the daily range (-3.66 to -10.93). The worst 6-month risk-adjusted return period is significantly shorter and shallower on weekly timeframes — critical for investor psychology and drawdown management.

3. **Different strategies benefit differently from weekly bars:**
   - MA Bounce: gains the most (P&L 3×, Sharpe 3×) — because daily bounces have the most noise
   - MAC Fast Exit: moderate P&L loss, massive Sharpe gain — the MA crossover is more stable weekly
   - Donchian: best RS(min) overall, similar OOS P&L, biggest MaxDD increase — 40-week high is the strongest breakout signal

4. **Weekly portfolio construction is viable** — all three strategies have sufficient trade counts (1,234-1,896 trades over 36 years) for statistical robustness. The next experiment should test a combined weekly portfolio.

---

## Updated Champion Leaderboard (44 Symbols, 1990-2026) — After Round 10

| Rank | Strategy | TF | P&L | Sharpe | RS(min) | OOS | WFA | RollWFA | Trades |
|---|---|---|---|---|---|---|---|---|---|
| 🥇 | MA Bounce (50d/3bar)+SMA200 | W | **140,028%** | **+1.92** | -2.32 | +123,865% | Pass | 3/3 | 1,366 |
| 🥈 | Price Momentum (6m ROC, 15pct) | D | 107,513% | +0.67 | -15.92 | +93,844% | Pass | 3/3 | 975 |
| 🥉 | MA Confluence Fast Exit | D | 101,198% | +0.68 | -4.46 | +88,023% | Pass | 3/3 | 2,080 |
| 4 | **MA Confluence Fast Exit** | **W** | 84,447% | +1.80 | -2.54 | +72,265% | Pass | 3/3 | 1,896 |
| 5 | CMF Momentum (20d)+SMA200 | D | 51,173% | +0.63 | -15.03 | +43,803% | Pass | 3/3 | — |
| 6 | **Donchian Breakout (40/20)** | **W** | 53,499% | +1.68 | **-2.06** | +41,671% | Pass | 3/3 | 1,234 |
| 7 | Donchian Breakout (40/20) | D | 48,426% | +0.63 | -3.66 | +41,665% | Pass | 3/3 | 3,070 |
| 8 | MA Bounce (50d/3bar)+SMA200 | D | 45,283% | +0.61 | -10.93 | +40,519% | Pass | 3/3 | ~660 |
| (9-12) | (Donchian 60d, MA Full Stack, ROC+MA Stack, SMA+OBV) | D | ... | ... | ... | ... | Pass | 3/3 | — |

**Best strategies by each metric:**
- **Highest Sharpe:** MA Bounce Weekly (+1.92)
- **Best RS(min):** Donchian Weekly (-2.06)
- **Highest P&L:** MA Bounce Weekly (140,028%)
- **Best OOS P&L:** MA Bounce Weekly (+123,865%)
- **Most trades:** daily MAC (2,080) / daily Donchian (3,070) for highest statistical confidence

---

## Round 11 Plan

1. **Combined Weekly Portfolio** — run all three weekly strategies together at 5% allocation on 44 symbols. Test whether weekly correlations are lower than daily (intuition: weekly trades on same stocks are more likely to occur at different times than daily trades).

2. **Price Momentum on SP500** (Queue Item 10) — validate the new daily champion across 500 stocks. Does RS(min) improve from -15.92 when diversified? Does MC Score reach +1?

3. **MAC Full Stack on weekly bars** — MA Confluence Full Stack (10/20/50) has not been tested on weekly bars. Expected to show similar improvement pattern.
