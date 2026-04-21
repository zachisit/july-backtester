# EC-R19: Champion Visual Assessment & Sharpe Clarification
**Date:** 2026-04-17
**Run ID:** ec-r19-champion-pdf_2026-04-17_15-10-30
**Strategy:** EC: MA Bounce + Low-Vol ATR Filter + SPY SMA96 Gate
**Universe:** Sectors+DJI 46, 2004-2026
**Config:** 5% allocation, no stop loss

## Sharpe Metric Clarification

Two different Sharpe values appear across reports — both correct, different risk-free rates:

| Source | Sharpe | Risk-Free Rate Used |
|---|---|---|
| main.py verbose terminal | 0.17 | 5.0% (from `config.risk_free_rate`) |
| report.py PDF (page 1) | 0.88 | 0.0% (trade analyzer default) |

The EC-R13 research notes documented Sharpe 0.88 — this was the PDF report's Sharpe (Rf=0%).
The terminal verbose output shows the risk-adjusted Sharpe vs the configured hurdle rate.
Both are valid metrics, different questions answered.

## Full Performance Metrics (from PDF appendix)

| Metric | Value |
|---|---|
| Total Return | +565.57% |
| CAGR | 9.22% |
| After-Tax CAGR (30% flat) | 7.74% |
| Max Equity Drawdown | 19.49% |
| Calmar Ratio | 0.47 |
| Sharpe (Portfolio Daily, Rf=0%) | 0.88 |
| Sortino (Portfolio Daily, Rf=0%) | 0.82 |
| Profit Factor | 1.49 |
| Win Rate | 37.96% |
| Total Trades | 4,089 |
| Avg Trades/Year | 190.3 |
| Avg Winning Trade | $551.80 |
| Avg Losing Trade | $−226.09 |
| Max Consecutive Losses | 36 |
| OOS P&L (WFA split 2021-12-28) | +179.01% |
| MC Score | 5 (Robust) |
| WFA Verdict | Pass (3/3 rolling) |

## Visual Assessment

**Equity curve shape (page 3 of PDF):**

- **2004-2014**: Staircase pattern with small steps. Not perfectly smooth but each step is modest.
- **2014-2017**: Clear 1055-day plateau (largest drawdown in the research). Curve goes flat from late 2014 through mid-2017. This is the dominant visual weakness.
- **2017-2021**: Clean, mostly gradual upward slope — this is the "good" section. The strongest visual performance of the strategy.
- **2021-2025 (OOS)**: More volatile with larger visible steps. Post-pandemic individual stock volatility is higher; the SPY gate keeps the strategy out of the worst periods.

**Remaining spike sources (from top trades, page 10):**
1. BA 2016-11-09 to 2018-01-23: $13,968 gain (+145%, 440 bars)
2. CAT 2017-04-24 to 2018-01-31: $7,628 gain (+74%, 282 bars)
3. Both exited near January 2018 → compound spike of ~$21k in one month on a ~$190k portfolio

The November 2023 monthly gain of +$37,118 (page 7 heatmap) and August 2024 +$19,726 are also notable.

**Benchmark: is this visually smoother than prior strategies?**
- **YES, significantly.** PM v3 (EC-R11 champion) had individual upthrust spikes from NVDA/AMD explosive moves
- The MA Bounce + Low-Vol curve has smaller but more numerous gains
- The drawdown profile (page 6) shows only 5 notable drawdown periods, all recoverable

## Monte Carlo (page 11)

1,000 simulations show tight outcome distribution:
- P5 CAGR: 8.0% (worst 5% of simulations still above 8%!)
- P50 CAGR: 9.2% (median matches backtest)
- P95 CAGR: 10.2% (best 5%)
- P5 MaxDD: −19.2% (worst 5% of simulations)

**Interpretation**: The strategy is extremely robust — even in adversarial trade orderings, CAGR stays above 8%.

## Dead Ends Summary (EC-R14 through EC-R18)

All five modifications to the EC-R13 winner made performance worse:

| Round | Modification | Why it Failed |
|---|---|---|
| EC-R14 | ATR 1.5% filter | Destroys setups — too few entries |
| EC-R14 | SMA200 + Low-Vol | Removes profitable high-vol names |
| EC-R15 | 3% allocation | Cash drag: CAGR falls below 5% hurdle |
| EC-R16 | ETF-only (16 symbols) | Too few trades, same cash drag |
| EC-R17 | ATR trailing stop | Catastrophic churn (4089 → 10163 trades) |
| EC-R18 | Percentage entry stop | Inert — never fires for confirmed bounces |

## Research Conclusion

**The EC-R13/R19 champion is the best achievable result with the current strategy architecture.**

The curve is NOT perfectly smooth (the 1055-day 2014-2017 plateau is the dominant visual flaw)
but it is significantly smoother than all prior momentum-based strategies. The metrics
are robust (MC Score 5, WFA Pass OOS +179%), CAGR 9.22% is strong for a low-vol approach.

## Direction for EC-R20

**If smoother curve is still required, the only genuinely new avenue is:**

Option A: **Expand universe to S&P 500** (via Norgate watchlist) with ATR < 2.5% filter.
- At 500+ symbols, ATR filter selects ~100-150 valid names at any time
- With 5% allocation and 20 concurrent positions, each position = $12.5k average
- But 100+ setups available → more trade distribution in time
- Individual exit impact: 5% × 15% average gain = 0.75% per trade (vs 5% × 40% for DJI top winners)
- Expected: dramatically smoother curve, potentially lower CAGR per position but more consistent

Option B: **Accept EC-R19 as final champion.** Visual smoothness is materially better than
all prior strategies. CAGR 9.22%, MaxDD 19.5%, OOS +179% is a strong result for a
smooth-curve-optimized strategy. The 2014-2017 plateau is a genuine market regime issue
(declining/choppy market), not an artifact of strategy over-fitting.
