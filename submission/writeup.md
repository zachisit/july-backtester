# Pay the Bills — 12-Month Momentum on SPY

## Strategy idea
Hold SPY when its trailing 12-month return (252 trading days) is positive.
Go to cash when it is zero or negative. Long-only, single parameter, low
turnover. Implemented as a plugin in custom_strategies/pay_the_bills_momentum.py.

## Why I expect it to work
Time-series momentum is one of the most robust anomalies in finance
(Moskowitz, Ooi & Pedersen 2012; Faber 2007). Bear markets tend to persist
rather than reverse instantly — slow information diffusion, forced selling
by leveraged funds, and herding all extend downtrends. A simple positive/
negative filter on the trailing year's return captures most of the equity
risk premium while stepping aside during the deepest parts of sustained
downtrends. Expected result: return comfortably above cash, with a maximum
drawdown substantially smaller than buy-and-hold.

## What I tried that didn't work
The framework runs every strategy in custom_strategies/ on the same data in
one pass, so alternatives were visible side by side in the same backtest:
- RSI mean reversion (7/20 and 14d + SMA200): larger drawdowns than buy-and-
  hold in 2008-09. Mean reversion assumes prices revert; during a structural
  crash they don't.
- 50/200-day SMA crossover: worked, but slower to re-enter after downtrends,
  producing a larger max drawdown (33.7% vs 28.5%) for similar returns.
- Shorter momentum windows (3-6 months): rejected on principle — higher
  turnover, more whipsaw, and 5bps/side costs grow with turnover.
The 12-month version was the simplest strategy that met both targets.

## Where I think it could fail
1. Fast crashes (e.g. March 2020): a 12-month lookback is slow; the strategy
   may not exit before the worst of a sudden, short-lived crash.
2. Choppy sideways markets: repeated small flips produce whipsaw losses with
   no offsetting trend.
3. Persistently higher cash rates: if T-bills yield 7-8%, the strategy's ~7%
   CAGR no longer clears "cash + 1-2%".
4. Regime change in equity autocorrelation: if medium-term return
   autocorrelation structurally weakens, the trend edge could decay.

## Results (2004-01-01 → 2026-12-31, after 5bps slippage + $0.002/share)

| Metric           | Strategy | SPY B&H |
|------------------|----------|---------|
| CAGR             | 7.04%    | 10.23%  |
| Max Drawdown     | -28.51%  | ~-55%   |
| Excess over cash | +2.04%   | +5.23%  |
| Trades (23 yrs)  | 35       | 0       |

Return target (cash + 1-2%): PASS. Against the framework's 5% risk-free rate,
excess is +2.04%; against realized T-bill returns over the period
(~1.5-2% CAGR), excess is ~5%.
Risk target (max DD < SPY): PASS. -28.51% vs ~-55%.

## Config changes I made
- data_provider: "polygon" → "yahoo" (no API key required)
- allocation_per_trade: 0.10 → 1.0 (default deploys only 10% per position)
- portfolios: {"My Symbols": ["AAPL"]} → {"SPY Only": ["SPY"]}
- execution_time, slippage_pct, commission_per_share, risk_free_rate left at
  framework defaults (open fill, 5bps, $0.002/share, 5%) — appropriate for
  this strategy.
