# Research Round 14 — New Weekly Strategy Family: MACD + RSI (Q15)

**Date:** 2026-04-11
**Run ID:** weekly-macd-rsi_2026-04-11_05-04-22
**Symbols:** nasdaq_100_tech.json (44 symbols)
**Period:** 1990-2026 (36 years)
**WFA:** 80/20 split, 3 rolling folds
**Timeframe:** W (weekly bars)
**Allocation:** 10% per trade
**New file created:** `custom_strategies/round13_strategies.py`

## Hypothesis

All 4 existing weekly champions use MA crossover, Donchian breakout, MA bounce, or ROC momentum. MACD and RSI weekly trend-following have never been tested on weekly bars. The weekly timeframe improvement (165-215% Sharpe vs daily) should extend to MACD and RSI signal families.

**MACD(3/6/2) on weekly** ≈ MACD(12/26/9) on daily (each period divided by 5). A weekly MACD cross represents a true shift in intermediate-term momentum, not a 2-3 day fluctuation.

**RSI(14w) crossing above 55** = genuine trend conviction on weekly bars. On daily bars, RSI frequently oscillates between 40-60 creating false crossovers. A weekly RSI(14) > 55 represents sustained multi-week buying pressure.

## Results

| Strategy | P&L | Sharpe | MaxDD | RS(min) | OOS P&L | WFA | RollWFA | MC Score |
|---|---|---|---|---|---|---|---|---|
| MACD Weekly (3/6/2) + SMA200 | 2,492% | 1.05 | 66.32% | -3.25 | — | Pass | 3/3 | -1 |
| RSI Weekly Trend (55-cross) + SMA200 | **135,445%** | **1.85** | 58.70% | **-2.15** | **+114,357%** | Pass | 3/3 | -1 |

## Extended Metrics

| Strategy | WinRate | Trades | SQN | Notes |
|---|---|---|---|---|
| MACD Weekly (3/6/2) + SMA200 | — | 4,238 | — | Too many crossovers — FAILED |
| RSI Weekly Trend (55-cross) + SMA200 | — | 686 | **6.80** | NEW CHAMPION |

## Key Findings

### MACD Weekly — FAILED

MACD (3/6/2) on weekly bars generates 4,238 trades — more than Price Momentum Weekly (671) and comparable to daily MAC Fast Exit (2,080). The MACD line crosses above/below the signal line too frequently even at weekly resolution. Sharpe 1.05 is materially below the weekly champion bar of 1.68+.

The fundamental issue: MACD crossovers at weekly resolution still trigger on multi-week momentum shifts that reverse quickly. The 3/6/2 parameters (equivalent to 12/26/9 daily) are designed for a slow/fast relationship that works on daily data — translated to weekly, the "fast" EMA(3 weekly) responds to the same raw price moves but with less context. The combination creates frequent false signals in sideways markets.

**MACD Weekly is added to the anti-patterns list.** Do not retry MACD variations on weekly bars without fundamentally changing the approach.

### RSI Weekly Trend — NEW CHAMPION (Rank 3)

RSI(14w) crossing above 55 from below, with price > SMA(40w) uptrend gate:

| Metric | RSI Weekly | Best Existing Weekly (MA Bounce W) | Delta |
|---|---|---|---|
| P&L | 135,445% | 140,028% | -3.3% |
| Sharpe | 1.85 | 1.92 | -0.07 |
| RS(min) | **-2.15** | -2.32 | **+0.17 better** |
| Trades | 686 | 1,366 | -50% (fewer, higher quality) |
| OOS P&L | +114,357% | +123,865% | -8% |
| WFA | Pass | Pass | — |
| RollWFA | 3/3 | 3/3 | — |
| SQN | 6.80 | — | Excellent |

**Leaderboard position:** RSI Weekly sits between MA Bounce W (Sharpe 1.92) and MAC Fast Exit W (Sharpe 1.80) on Sharpe. It has the best RS(min) of any weekly strategy except Donchian (-2.06). This makes it a genuine addition to the weekly champion tier.

**Why RSI Weekly works:** On weekly bars, RSI(14) represents 14 full weeks of price momentum. Crossing above 55 from below is a meaningful regime change signal — it indicates that cumulative buying pressure over a 14-week window has definitively shifted bullish. The 55 threshold (not 50) eliminates borderline crossings that tend to reverse. The 45-exit threshold gives positions room to breathe through brief pullbacks without triggering whipsaw exits.

**Why fewer trades are better:** 686 trades vs 1,366 for MA Bounce means each RSI Weekly trade is a higher-conviction, longer-duration entry. The 6.80 SQN confirms exceptional statistical quality — the system generates high-quality signals at lower frequency.

### Comparison to Existing Champions

| Rank | Strategy | TF | Sharpe | RS(min) |
|---|---|---|---|---|
| 1† | MA Bounce (50d/3bar)+SMA200 | W | **1.92** | -2.32 |
| 1† | Price Momentum (6m ROC, 15pct) | W | 1.87 | -2.30 |
| **3 NEW** | **RSI Weekly Trend (55-cross)+SMA200** | **W** | **1.85** | **-2.15** |
| 4 | MA Confluence Fast Exit | W | 1.80 | -2.54 |
| 5 | Donchian Breakout (40/20) | W | 1.68 | **-2.06** |

RSI Weekly slots directly into rank 3 — above MAC Fast Exit W and below the co-champions. Its RS(min) -2.15 is second-best only to Donchian W (-2.06).

## Strategy Implementation

**File:** `custom_strategies/round13_strategies.py`

```python
@register_strategy(
    name="RSI Weekly Trend (55-cross) + SMA200",
    dependencies=[],
    params={
        "rsi_period": 14,             # 14 weekly bars ≈ 14-week RSI
        "rsi_entry":  55.0,           # RSI above 55 = bullish momentum threshold
        "rsi_exit":   45.0,           # RSI below 45 = momentum stalled/reversed
        "sma_slow":   get_bars_for_period("200d", _TF, _MUL),  # 40w uptrend gate
    },
)
```

Entry: RSI(14w) crosses above 55 from below AND price > SMA(40w)
Exit: RSI(14w) drops below 45 OR price < SMA(40w)

## Updated Anti-Patterns

| What Failed | Why | Lesson |
|---|---|---|
| MACD Weekly (3/6/2) + SMA200 | 4,238 trades (too frequent), Sharpe only 1.05. MACD crossovers at weekly resolution still occur too frequently in sideways markets. | MACD does not benefit from weekly timeframe the same way MA/RSI/ROC strategies do. The crossover mechanism is inherently noisy regardless of bar size. |

## New Champion Added

RSI Weekly Trend (55-cross) + SMA200 is a **confirmed weekly champion** (rank 3). It should be tested in the 5-strategy combined portfolio (Queue Item 17) to determine if it adds diversification beyond the existing 4 weekly champions.
