# Research Round 13 — Monthly Timeframe Test (Q14)

**Date:** 2026-04-11
**Run ID:** monthly-timeframe-test_2026-04-11_05-02-41
**Symbols:** nasdaq_100_tech.json (44 symbols)
**Period:** 1990-2026 (36 years)
**WFA:** 80/20 split, 3 rolling folds
**Timeframe:** M (monthly bars)
**Allocation:** 10% per trade
**min_bars_required:** 60 (lowered from 250 — 250 monthly bars = ~20 years, too restrictive)

## Hypothesis

Weekly bars improved daily by 165-215% Sharpe. Does monthly improve weekly further? MA Bounce on monthly = 2-month SMA bounce vs 9-month uptrend gate. Price Momentum on monthly = ROC(6 bars) > 15% is natural on monthly closes.

## Results

| Strategy | P&L | Sharpe | MaxDD | RS(min) | OOS P&L | WFA | RollWFA | MC Score |
|---|---|---|---|---|---|---|---|---|
| MA Bounce (50d/3bar) + SMA200 Gate | 134,588% | **3.77** | 73.50% | **+0.37** | +122,485% | Pass | 3/3 | -1 |
| Price Momentum (6m ROC, 15pct) + SMA200 | 159,183% | **3.93** | 75.12% | **+0.45** | +146,809% | Pass | 3/3 | -1 |

## Extended Metrics

| Strategy | RS(avg) | WinRate | Trades | Corr (vs each other) |
|---|---|---|---|---|
| MA Bounce Monthly | high | — | 545 | 0.97 |
| Price Momentum Monthly | high | — | 469 | 0.97 |

**Strategy correlation: 0.97** — nearly perfectly correlated at monthly timeframe. Both strategies effectively do the same thing at monthly bars: hold during sustained bull markets, exit during multi-month bear phases.

## Key Findings

### Extraordinary Sharpe — But Impractical

Monthly bars produce theoretical Sharpe values of 3.77-3.93 — extraordinary by any academic or hedge fund standard. RS(min) is **POSITIVE** (+0.37, +0.45), meaning the worst 6-month rolling Sharpe window across 36 years never went negative on risk-adjusted basis. Both strategies never experienced a sustained 6-month losing period on a rolling Sharpe basis.

### Why Monthly Sharpe Is So High

On monthly bars, each "bar" represents a full month of price action. The SMA gates (9-month uptrend) filter out almost all bear market exposure. The strategy holds only when a genuine multi-month uptrend is confirmed. This creates very clean entries and exits on the smoothed monthly price series.

### The Fatal Flaw: MaxDD and Recovery Time

| Metric | Monthly | Weekly | Daily |
|---|---|---|---|
| MaxDD | **73-75%** | 49-60% | 49-69% |
| Max Recovery | **3,930 days (~11 years)** | ~2 years | ~2-3 years |
| Sharpe | 3.77-3.93 | 1.68-1.99 | 0.61-0.68 |

MaxDD of 73-75% is catastrophic for live trading. A $1M account would fall to $250,000 at the trough. A drawdown of 11+ years means a strategy started in 2000 would not recover until 2011. No institutional or retail investor can sustain this — position would be liquidated or abandoned before recovery.

### Correlation Problem

With strategy correlation = 0.97, running both monthly strategies provides no diversification benefit. At monthly timeframe granularity, both MA Bounce and Price Momentum reduce to the same meta-signal: "is the market in an uptrend month-over-month?" They exit together at every bear market and enter together at every recovery.

### min_bars_required Adjustment

Default 250 bars at monthly frequency = ~20 years of data required before a symbol can be included. This would exclude META (public 2012 = ~168 monthly bars), NVDA (before 2006 had minimal data), and other important tech names. Lowered to 60 (≈5 years) for this test, then restored to 250.

## Verdict

**NOT RECOMMENDED for live trading.** The monthly timeframe produces theoretically superior Sharpe (3.77-3.93) and RS(min) (+0.37/+0.45 positive!), but MaxDD of 73-75% and 11-year recovery windows make it impractical for any real portfolio. The weekly timeframe (Sharpe 1.68-1.99, MaxDD 49-55%) dominates monthly on the only metric that matters for live trading: drawdown survivability.

**Weekly timeframe is confirmed as the optimal production timeframe.** Monthly is a theoretical curiosity.

## Updated Anti-Patterns

| What Failed | Why | Lesson |
|---|---|---|
| Monthly timeframe on tech stocks | Sharpe 3.77-3.93 but MaxDD 73-75%, MaxRecovery 3,930 days (11 years). Both strategies correlate 0.97 — no diversification benefit at monthly granularity. | Monthly bars produce impressive Sharpe but catastrophic drawdowns. Weekly dominates monthly for live trading. Use W timeframe. |

## Config Changes Made and Restored

```python
# Changed for run:
"timeframe": "M"
"min_bars_required": 60

# Restored after run:
"timeframe": "D"
"min_bars_required": 250
```
