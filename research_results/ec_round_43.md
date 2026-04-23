# EC Research Round 43 — Power Dip: Mean Reversion on 52-Week-High Stocks

**Date:** 2026-04-23
**Run ID:** ec-r43-power-dip-52wk_2026-04-23_17-30-03
**Symbols:** S&P 500 Current & Past (Norgate, ~1273 valid symbols)
**Period:** 2004-01-02 → 2026-04-23
**WFA:** 80/20 split (IS: 2004-2021-11-05, OOS: 2021-11-05 → 2026-04-23), 3 rolling folds
**Timeframe:** Daily bars
**Allocation:** 2.5% per position

## Context

EC-R42 (SMA50 fast gate) created 7-8 scattered loss years vs EC-R39b's concentrated 2008/2022 losses.
Root cause of all failures identified: mean reversion without a STRONG uptrend signal keeps entering
declining stocks. EC-R43 addresses this by requiring the stock to be NEAR ITS 52-WEEK HIGH before
entering a pullback — stocks near their annual highs are in strong uptrends, not declining ones.

**EC-R43 entry conditions:**
- Close < SMA20 * 0.97 (3% pullback from short-term mean)
- Close > rolling_max_252 * 0.85 (within 15% of 52-week high)

**EC-R43 exit conditions:**
- Target: Close > SMA20 (return to mean)
- Stop: Close < rolling_max_252 * 0.80 (fallen >20% from annual high)

## Results

| Strategy | P&L | vs SPY | MaxDD | Calmar | RS(min) | OOS P&L | WFA | RollWFA | MC | Trades |
|---|---|---|---|---|---|---|---|---|---|---|
| EC-R43 (3%/2% + 52wk) | 498% | -361pp | 33.85% | 0.25 | -4.49 | +90.62% | **Pass** | **3/3** | 5 | 12,498 |
| EC-R43b (5%/3% + 52wk) | 352% | -507pp | 36.35% | 0.19 | -9.81 | +43.08% | **Pass** | **3/3** | 5 | 8,861 |

SPY B&H over period: ~859%

## Distribution Diagnostic

| Metric | EC-R43 (3%/2%) | EC-R43b (5%/3%) | Threshold |
|---|---|---|---|
| Top 1 trade / total P&L | 1.5% | 1.3% | < 3% ✓ |
| Top 5 trades / total P&L | 4.1% | 4.8% | < 15% ✓ |
| Total trades | 12,498 | 8,861 | — |
| **PASS distribution test?** | **Yes** | **Yes** | — |

No single trade dominates. The 52-week filter successfully caps individual trade upside while
maintaining uniform P&L distribution.

## Annual Equity Progression — EC-R43 (3%/2%)

| Year | Annual P&L | Cumulative Equity | Notes |
|---|---|---|---|
| 2005 | +$15,617 | $115,617 | Gradual ✓ |
| 2006 | +$12,063 | $127,680 | Gradual ✓ |
| 2007 | +$7,431 | $135,111 | Slowing before GFC |
| **2008** | **-$38,168** | **$96,943** | **Bear market cliff ✗** |
| 2009 | +$22,146 | $119,089 | Recovery begins |
| 2010 | +$21,196 | $140,285 | — |
| 2011 | +$14,122 | $154,407 | — |
| 2012 | +$19,909 | $174,317 | — |
| 2013 | +$64,841 | $239,157 | Strong year |
| 2014 | +$17,961 | $257,118 | — |
| 2015 | +$12,033 | $269,151 | — |
| 2016 | +$32,100 | $301,251 | — |
| 2017 | +$35,734 | $336,985 | — |
| **2018** | **-$31,430** | **$305,555** | **Rate hike drawdown ✗** |
| 2019 | +$62,738 | $368,293 | Strong recovery |
| 2020 | +$26,191 | $394,483 | COVID V-recovery captured ✓ |
| 2021 | +$121,784 | $516,267 | Bull year |
| **2022** | **-$69,682** | **$446,585** | **Rate hike bear ✗** |
| 2023 | +$30,665 | $477,251 | — |
| 2024 | +$82,643 | $559,894 | — |
| 2025 | +$28,365 | $588,259 | — |
| 2026 | +$9,559 | $597,818 | — |

## Key Findings

### EC-R43 PASSES WFA and distribution — but lags SPY significantly

1. **52-week filter SOLVES the dominant-trade problem** — Top5 trades = 4.1% of total P&L.
   No visible upthrust in equity curve from individual lucky winners.

2. **RS(min) dramatically improved vs EC-R39b** — EC-R43 RS(min) = -4.49 vs EC-R39b -9.81.
   The 52wk proximity filter eliminates the worst-bear-market entries that drove extreme rolling losses.

3. **2020 COVID gains preserved** — The filter allows entries during V-shaped recovery (+$26k in 2020)
   because stocks near 52wk highs are precisely the ones that recover fastest. This is a key advantage
   over VIX gating (which would block these entries).

4. **Bear market losses not fully prevented** — 2008: -$38k, 2018: -$31k, 2022: -$69k.
   The 52wk filter delays but does not stop bear market entries. In early bear markets, stocks are
   still near their highs from the preceding bull — the strategy enters normal pullbacks that become
   extended bear market declines.

5. **Significantly lags SPY** — 498% vs ~859% SPY B&H. The pullback entry + mean-reversion exit
   strategy doesn't capture the full uptrend move; it only captures the bounce portion.

### EC-R43b (5%/3% wider variant): INFERIOR across all metrics

Deeper pullback entry selects fewer, supposedly stronger setups — but weaker OOS (+43% vs +90%),
worse RS(min) (-9.81 vs -4.49), lower P&L (352% vs 498%). EC-R43 (3%/2%) is clearly superior.

## Verdict

**EC-R43 is a STEP FORWARD but not a champion.** WFA Pass, MC 5, excellent distribution — but:
- Lags SPY by 361pp over the period
- 2008 and 2022 losses still substantial (30-40% equity cliff-downs)
- OOS +90% is strong (genuine alpha) but raw returns below SPY threshold

EC-R43 is the best mean-reversion strategy found so far. The direction is right; the bear-market
entry prevention needs one more layer.

## Root Cause of Remaining Bear Market Losses

During early bear markets, stocks are still near 52-week highs from the prior bull peak.
The 15% proximity threshold allows entries even as markets begin declining. By the time stocks
fall below 85% of 52wk high (~3-4 months into a bear), the strategy has already taken losses
on early entries.

The missing signal: **is the SHORT-TERM market trend (10-20 days) positive?**
A rising 20-day SMA on SPY or on the stock itself would block entries during nascent bear markets.

## Next Research Direction

**EC-R44:** VIX gate on EC-R43 (already implemented; to be tested in the same session).
If VIX gate fails, **EC-R45** should test: short-term slope gate on SPY (SPY SMA20 today > SPY SMA20
15 days ago). This prevents entries when the overall market's short-term trend is negative — a more
responsive filter than SPY SMA200 and less prone to long exclusion periods.
