# Research Round 1 — Strategy Backtest Results

**Date:** 2026-04-10
**Symbol:** AAPL
**Period:** 2004-01-01 → 2026-04-10 (22 years)
**Data Provider:** Norgate (total-return adjusted)
**WFA Split:** 80% IS / 20% OOS (split ~2021-10-26)
**Capital:** $100,000 | Allocation: 10%/trade | Slippage: 0.05% | Commission: $0.002/share
**Run ID:** research-v1_2026-04-10_21-19-38

---

## Core Performance Table

| Strategy | P&L (%) | Sharpe | Max DD | MC Score | WFA Verdict |
|---|---|---|---|---|---|
| Donchian Breakout (20/10) | **83.14%** | -0.91 | 3.78% | 5 | Pass |
| ROC Momentum (20d) | 68.36% | -0.94 | 5.74% | 5 | Pass |
| ROC Momentum (10d) | 65.12% | -1.01 | 6.09% | 5 | Pass |
| Keltner Breakout (20d/2x) | 44.15% | -1.66 | 2.96% | 3 | Pass |
| BB Squeeze Breakout | 19.77% | -3.62 | 3.30% | -999 (few) | N/A |
| Williams %R (14d) | 12.31% | -2.18 | 5.32% | 5 | Pass |
| Stochastic Mean Reversion (14d) | 12.31% | -2.18 | 5.32% | 5 | Pass |
| Volume-Weighted RSI (14d) | 4.10% | -2.98 | 6.35% | -999 (few) | Pass |
| ATR Breakout Trailing Stop | ❌ CRASH | — | — | — | — |

---

## Extended Metrics

| Strategy | Calmar | PF | WinRate | Trades | Expct(R) | SQN | MaxRcvry | AvgRcvry |
|---|---|---|---|---|---|---|---|---|
| Donchian Breakout (20/10) | **0.73** | **4.37** | 62.65% | 83 | **7.511** | 3.34 | 777d | 41d |
| ROC Momentum (20d) | 0.41 | 2.21 | 43.32% | 247 | 2.171 | 3.07 | 714d | 47d |
| ROC Momentum (10d) | 0.37 | 1.92 | 43.43% | 350 | 1.465 | 3.43 | 877d | 43d |
| Keltner Breakout (20d/2x) | 0.56 | 2.76 | 55.10% | 98 | 3.817 | 2.97 | 1002d | 62d |
| BB Squeeze Breakout | 0.25 | 5.79 | 56.52% | 23 | 8.067 | 1.88 | 4320d | 121d |
| Williams %R (14d) | 0.10 | 1.46 | 62.84% | 148 | 0.814 | 1.28 | 5070d | 197d |
| Stochastic Mean Reversion (14d) | 0.10 | 1.46 | 62.84% | 148 | 0.814 | 1.28 | 5070d | 197d |
| Volume-Weighted RSI (14d) | 0.03 | 1.36 | 75.68% | 37 | 1.134 | 0.70 | 5851d | 514d |

---

## Robustness (WFA Out-of-Sample)

| Strategy | OOS P&L | WFA Verdict | MC Result |
|---|---|---|---|
| ROC Momentum (10d) | **+10.55%** | Pass | Robust |
| Donchian Breakout (20/10) | +8.83% | Pass | Robust |
| ROC Momentum (20d) | +6.85% | Pass | Robust |
| Keltner Breakout (20d/2x) | +5.47% | Pass | DD Understated |
| Volume-Weighted RSI (14d) | +3.22% | Pass | N/A (few trades) |
| Stochastic MR (14d) | +3.04% | Pass | Robust |
| Williams %R (14d) | +3.04% | Pass | Robust |
| BB Squeeze Breakout | -0.10% | N/A | N/A (few trades) |

---

## Key Findings & Issues

### ✅ Winners
1. **Donchian Breakout (20/10)** — Clear best. Highest Calmar (0.73), best PF (4.37), highest Expectancy (7.5R), lowest MaxDD (3.78%), strong OOS (+8.83%). Only 83 trades = selective entries. Low correlation (0.07) with other strategies.
2. **ROC Momentum (10d/20d)** — Both pass WFA with positive OOS. 10d has best OOS (+10.55%). High trade count but negative Sharpe (returns below 5% hurdle rate).

### ⚠️ Problems Identified
1. **ATR Breakout Trailing Stop CRASH** — `atr_trailing_stop_logic_breakout_entry` has a pandas index length mismatch bug (5583 values vs 5603 index). The indicator function is broken — do not use.
2. **Williams %R ≡ Stochastic** — Correlation r=+1.00. They generate *identical* signals on this data. One should be dropped or reconfigured with different parameters.
3. **All Sharpe ratios negative** — 5% risk-free hurdle is high relative to these strategies' annualized returns on AAPL. The strategies are profitable but don't compensate for the opportunity cost vs T-bills at 5%. Need higher-conviction entries or multi-asset application.
4. **BB Squeeze & VW RSI** — Too few trades (<50) for Monte Carlo → MC Score -999. BB Squeeze failed OOS (-0.10%). The squeeze detection may be too strict.
5. **Keltner DD Understated** — MC says drawdown is understated (MC Score 3). Rolling Sharpe min = -113.80 indicates severe periods of loss.

### 🔍 Correlation Alert
- Williams %R ↔ Stochastic: r=+1.00 (IDENTICAL — remove one)

---

## Cross-Symbol Validation: Tech Giants (AAPL, MSFT, GOOG, AMZN, NVDA, META)

Running on 6 tech giants reveals dramatically different characteristics. **The tech giants ecosystem is the primary target for Round 2.**

| Strategy | P&L (%) | Sharpe | Max DD | MC Score | WFA Verdict |
|---|---|---|---|---|---|
| **ROC Momentum (20d)** | **554.66%** | **+0.42** | 21.16% | 5 | Pass |
| **Donchian Breakout (20/10)** | **411.14%** | **+0.34** | 14.64% | 5 | Pass |
| **Keltner Breakout (20d/2x)** | **215.66%** | **+0.08** | 11.06% | 5 | Pass |
| Williams %R (14d) | 116.88% | -0.16 | 12.97% | 5 | Pass |
| Volume-Weighted RSI (14d) | 36.29% | -0.52 | 20.08% | 5 | Pass |

**Key findings:**
- Sharpe ratios turn POSITIVE on multi-symbol tech portfolios (momentum strategies need a basket of growth stocks to work)
- ROC Momentum (20d) gains 8× more P&L in the tech giants vs AAPL alone — NVDA, META, AMZN momentum is the fuel
- Donchian remains excellent: positive Sharpe, moderate MaxDD
- Keltner MaxDD 11% is acceptable and positive Sharpe confirms the strategy works in trend environments
- **All 5 strategies pass WFA and MC Score = 5** — much stronger statistical evidence with 6 symbols (many more trades)

**Conclusion: Round 2 must target the tech giants (or similar high-momentum ecosystems), not single stocks.**

---

## Hypotheses for Round 2

### Momentum Family (ROC)
- **H1**: Adding SMA-200 trend filter to ROC should reduce whipsaws and improve Sharpe
- **H2**: ROC with a VIX filter (only trade when VIX < 25) may reduce drawdown
- **H3**: ROC Momentum (20d) with a positive ROC *threshold* (+1% vs 0%) may increase per-trade profitability

### Breakout Family (Donchian, Keltner)
- **H4**: Donchian with longer entry period (40d) should have fewer but higher-quality trades
- **H5**: Donchian + SPY regime filter should eliminate bear-market losses (needs `dependencies=["spy"]`)
- **H6**: Keltner with tighter multiplier (1.5x) may generate more trades and improve MC score

### Mean Reversion Family (Williams %R, VW RSI)
- **H7**: Williams %R with tighter exit (exit at -30 instead of -50) should improve win rate further
- **H8**: VW RSI with lower exit threshold (45 instead of 55) to generate more signals
- **H9**: Combining Williams %R entry + SMA200 trend filter should eliminate mean-reversion traps in downtrends

---

## Round 2 Strategy Plan (to implement)

Based on hypotheses above, agents will design and I will implement:

| Strategy Name | Family | Key Change | Hypothesis |
|---|---|---|---|
| ROC Momentum (20d) + SMA200 | Momentum | Add SMA-200 trend filter | H1 |
| ROC Momentum (20d) Filtered | Momentum | ROC threshold = +1% | H3 |
| Donchian Breakout (40/20) | Breakout | Longer window | H4 |
| Donchian + SPY Regime | Breakout | Add SPY regime filter | H5 |
| Keltner Breakout (20d/1.5x) | Breakout | Tighter bands | H6 |
| Williams %R (14d) + SMA200 | Mean Rev | Add trend filter | H9 |
| VW RSI (14d) Aggressive | Mean Rev | Lower exit threshold | H8 |
