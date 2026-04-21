# EC-R5: Sector ETFs Only Universe (16 symbols)
**Date:** 2026-04-16
**Run ID:** ec-r5-sectors16-2004_2026-04-16_21-16-23
**Universe:** Sectors 16 ETFs (sectors.json)
**Period:** 2004-01-01 → 2026-04-16
**Timeframe:** Daily (D), No stop loss

## Results

| Strategy | Calmar | MaxRecovery | MaxDD | Sharpe | MC Score | Trades |
|---|---|---|---|---|---|---|
| EC: MA Bounce + SPY Regime Gate | 0.29 | 924d | 18.72% | 0.09 | 5 | 1,447 |
| EC: Donchian (40/20) + SPY Regime Gate | 0.23 | 942d | 16.30% | -0.09 | 5 | 995 |
| EC: MAC Fast Exit + SPY Regime Gate | 0.22 | 1,090d | 19.46% | -0.01 | 5 | 1,035 |
| EC: Price Momentum (6m/15%) + SPY Regime Gate | 0.22 | 1,611d | 20.01% | -0.01 | 5 | **355** |

## Analysis — RESULT: REJECTED. 16 sectors too few for daily momentum strategies.

- Price Momentum only generated 355 trades in 22 years on 16 ETFs = 0.16 signals/ETF/year
- Sector ETFs are too broadly diversified to show strong 6m ROC > 15% signals
- Calmar 0.22-0.29 is WORSE than Sectors+DJI 46 (0.35-0.46 in EC-R4)
- Sharpe near-zero: ETF momentum signals too weak/rare to generate consistent alpha
- MaxDD reduced to 16-20% BUT total P&L is only 124-226% in 22 years = ~3-5% annual

## Key Finding: Sector ETFs Anti-Pattern for Daily Momentum

Sector ETFs are POOR candidates for daily momentum strategies because:
1. They're too diversified — individual stock alpha averages out
2. Price Momentum > 15% over 6 months rarely fires for entire sectors
3. MA Bounce signals are weakened by the ETF's internal diversification smoothing out pullbacks
4. OOS P&L is only +25-65% (vs +195-605% on Sectors+DJI 46 in EC-R4)

Anti-pattern: DO NOT test momentum strategies on < 30 highly diversified ETF symbols.
The law of large numbers requires sufficient trade count. 355 trades is borderline (min 500).

## Best Finding in EC Research So Far

**Price Momentum (6m/15%) + SPY SMA200 Gate on Sectors+DJI 46, 2004-present (EC-R4):**
- Calmar 0.46, MaxRecovery 794 days, MaxDD 27.89%, MC Score 5, WFA Pass 3/3, OOS +605%
- This is the best daily strategy found so far in this research program

## Decision: EC-R6

Test **Relative Momentum (stock vs SPY) + SPY Regime Gate** on Sectors+DJI 46, 2004-present.
This is a confirmed weekly champion (Sharpe 2.08, P&L 166,502%) adapted for daily bars.
Adding SPY macro regime gate on top should provide additional crash protection.
