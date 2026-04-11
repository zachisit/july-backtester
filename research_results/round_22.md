# Research Round 22 — Nasdaq Biotech (257): Binary-Event Sector (Q23)

**Date:** 2026-04-11
**Run ID:** biotech-weekly-5strat_2026-04-11_06-58-39
**Symbols:** nasdaq_biotech_tickers.json (257 symbols; some skipped <250 bars)
**Period:** 1990-2026 (36 years)
**WFA:** 80/20 split, 3 rolling folds (split date: 2019-01-08)
**Timeframe:** W (weekly bars)
**Allocation:** 3.3% per trade

## Hypothesis

Biotech is structurally different: returns are driven by binary FDA events, clinical trial results, and partnership announcements. These events are near-random — FDA approval is not predictable from price alone. Momentum strategies might fail entirely if stock moves are random binary jumps, or succeed if post-approval momentum is real and sustained over multiple weeks. This tests whether weekly momentum strategies are universal or require sustained, non-binary trend dynamics.

## Results

| Strategy | P&L | Sharpe | MaxDD | RS(min) | OOS P&L | WFA | RollWFA | Trades | SQN | MC Score |
|---|---|---|---|---|---|---|---|---|---|---|---|
| MA Confluence (10/20/50) Fast Exit | 6,061% | **0.81** | 55.30% | **-3.09** | +1,550% | Pass | 3/3 | 4,690 | **6.16** | -1 |
| MA Bounce (50d/3bar) + SMA200 Gate | 4,703% | 0.79 | 55.37% | -4.62 | **+2,406%** | Pass | 3/3 | 3,490 | 5.80 | -1 |
| Price Momentum (6m ROC, 15pct) + SMA200 | 4,600% | 0.76 | 66.77% | -3.57 | +2,961%* | Pass | 3/3 | 1,987 | 5.65 | -1 |
| Donchian Breakout (40/20) | 3,255% | 0.72 | 59.18% | -4.02 | +2,092% | Pass | 3/3 | 2,807 | 5.15 | -1 |
| RSI Weekly Trend (55-cross) + SMA200 | 2,918% | 0.68 | **65.55%** | -3.70 | +2,046% | Pass | 3/3 | 1,837 | 4.72 | -1 |

*Note: Price Momentum OOS +2,961% is the highest OOS of any strategy here — 2019-2026 was the COVID-era biotech boom (mRNA vaccines, rare disease approvals).

## Key Findings

### ALL 5 WFA Pass + RollWFA 3/3 — Strategies Work on Biotech

Despite the binary event nature of biotech, all 5 strategies pass walk-forward analysis. This is significant: even in a universe where "news" (FDA decisions) can move stocks 50-80% overnight, the momentum framework still captures sustained post-event trends. After a major FDA approval, biotech stocks often trend for 3-6 months as institutional buyers accumulate — that sustained movement IS capturable by weekly momentum.

### Sharpe 0.68-0.81 — Lower Than Tech, Higher Than Expected

| Universe | Best Sharpe | Worst Sharpe | MaxDD Range |
|---|---|---|---|
| DJI 30 (R21) | 1.93 | 1.71 | 19-23% |
| NDX Tech 44 (R16) | 1.95 | 1.63 | 44-50% |
| SP500 (R17) | 1.81 | 1.42 | 45-58% |
| Russell 1000 (R15) | 1.18 | 0.87 | N/A |
| **Biotech 257 (R22)** | **0.81** | **0.68** | **55-67%** |

Biotech Sharpe (0.68-0.81) is comparable to the **daily** versions of these same strategies on NDX Tech 44 (0.61-0.68). The weekly timeframe improvement seen on large-cap universes partially applies to biotech, but the binary event noise floor limits how far weekly smoothing can push the Sharpe.

### MaxDD 55-67% — Binary Events Create Larger Drawdowns

MaxDD range (55-67%) is worse than NDX combined (44-50%) and much worse than DJI (19-23%). The tail risk in biotech comes from:
1. **FDA rejections** — a stock holding multiple positions after initial FDA approval then loses an additional indication → -40% in a week
2. **Clinical trial failures** — phase 3 trial failure events cause -60-80% single-week drops that fire stop losses and reduce capital before recovery
3. **Sector correlation** — all biotech names crash together during "risk-off" periods (2015 biotech correction, 2022 rate-rise environment)

Price Momentum MaxDD (66.77%) is the worst — this strategy enters after a 6-month strong run, which in biotech often follows a major approval. If a subsequent trial fails during the momentum hold, the exit fires at the next week's lower level but the damage is severe.

### RS(min) -3.09 to -4.62 — Worse Than DJI, Similar to NDX Daily

The rolling Sharpe floor (-3.09 to -4.62) indicates prolonged losing periods, consistent with biotech's cyclical boom/bust pattern:
- 2015-2016 biotech correction: -40% sector drawdown
- 2021-2022: biotech collapsed from COVID highs, -50% sector
- These periods create worst RS(min) windows regardless of strategy

MAC Fast Exit has the best RS(min) (-3.09) — consistent with its fast exit mechanism protecting against prolonged drawdowns in binary-event environments.

### OOS P&L: High (All Positive, +1,550% to +2,961%)

OOS period (2019-2026) coincides with the COVID-19 biotech super-cycle: mRNA vaccine approvals (BioNTech/Moderna), massive rare disease drug approvals (gene therapies), and 2021 biotech boom. This OOS performance is extraordinary — the strategies correctly identified and rode major biotech trends during a period of exceptional sector tailwinds. WFA Pass is valid, but the OOS environment was historically favorable for biotech momentum.

**Caution:** The next OOS period (2026-2030) may not have a COVID-scale biotech catalyst. Live trading on biotech should discount OOS P&L relative to IS P&L.

### Why Biotech WORKS Despite Binary Events

1. **Post-approval momentum is real**: After FDA approval, institutions buy over 3-6 months. Weekly RSI(14) crosses 55 as this happens — the signal fires correctly.
2. **Failed trials create short-lived drops**: Most strategy positions exit at SMA200 or RSI<45 the following week. The damage is contained to one week's movement.
3. **Sector leadership cycles**: In any given year, biotech either leads or lags the S&P 500. When it leads (2013, 2019-2021), momentum strategies capture the whole run. When it lags (2015-2016, 2022), the SMA200 gate keeps most positions out.

## Comparison: Strategy Rankings Across Universes

| Strategy | NDX 44 Sharpe | DJI 30 Sharpe | Biotech 257 Sharpe |
|---|---|---|---|
| MAC Fast Exit | 1.76 | 1.72 | **0.81** (still best on biotech) |
| MA Bounce | 1.95 | 1.80 | 0.79 |
| Price Momentum | 1.80 | 1.88 | 0.76 |
| Donchian | 1.63 | 1.71 | 0.72 |
| RSI Weekly | 1.91 | **1.93** | 0.68 (worst on biotech) |

MAC Fast Exit holds the top Sharpe position on biotech. RSI Weekly (55-cross) loses ground — the regime signal that works beautifully on sustained large-cap trends is partially disrupted by biotech's frequent RSI spikes from binary events. RSI can spike above 55 on an FDA news day and then crash below 45 on a subsequent trial failure — these entries/exits reduce net performance.

## Verdict

**ALL 5 STRATEGIES PASS ON NASDAQ BIOTECH** — but with meaningfully lower Sharpe (0.68-0.81) and higher MaxDD (55-67%) than large-cap universes.

**Key conclusion:** The 5-strategy weekly momentum framework is universal across ALL US equity sectors tested:
- NDX Tech 44: Sharpe 1.63-1.95 (tech momentum — best environment)
- Dow Jones 30: Sharpe 1.71-1.93, MaxDD 19-23% (diversified blue chip — best risk profile)
- SP500 503: Sharpe 1.42-1.81 (diversified large cap)
- Russell 1000 1,012: Sharpe 0.87-1.18 (large/mid cap, non-tech dilution)
- **Nasdaq Biotech 257: Sharpe 0.68-0.81 (binary-event sector — worst environment)**

Biotech is the lower bound. Even in the hardest-to-predict sector, the strategies generate positive OOS P&L and pass WFA. For live trading, biotech should be used only as a component of a diversified universe (e.g., run the strategy on the full SP500 which includes biotech — don't run on biotech-only universe).

## Config Changes Made and Restored

```python
# Changed for run:
"timeframe": "W"
"portfolios": {"Nasdaq Biotech (257)": "nasdaq_biotech_tickers.json"}
"strategies": [all 5 champion names]
"allocation_per_trade": 0.033
"verbose_output": True
```
