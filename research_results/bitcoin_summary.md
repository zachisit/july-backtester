# Bitcoin Strategy Research — Polygon Daily Timeframe
**Research Track:** Bitcoin (BTC) only — Polygon data provider, Daily (`D`) timeframe
**Universe:** `X:BTCUSD` (single asset)
**Period:** 2017-01-01 → present (multiple full Bitcoin market cycles)
**WFA:** 80/20 split, 3 rolling folds
**Allocation:** `allocation_per_trade = 1.0` (100% equity deployed — single-asset system, equivalent to 1/N for N=1)

---

## Research Goals

1. **Transfer test**: Do the equity daily champions (MA Confluence, Donchian, MA Bounce, Price Momentum, CMF) work on Bitcoin?
2. **Bitcoin-specific strategies**: Develop strategies tuned for Bitcoin's unique characteristics (halving cycles, 4-year macro patterns, high volatility).
3. **Risk-adjusted alpha**: Can any systematic strategy achieve Calmar ≥ 0.5 on Bitcoin daily with MaxDD < 70%?
4. **BTC B&H benchmark**: Bitcoin buy-and-hold from 2017-2026 is ~8,400% return, ~80% MaxDD, Calmar ≈ 0.83. Can strategies improve the Calmar while preserving returns?

---

## Validation Criteria (Bitcoin-Adjusted)

| Metric | Green | Yellow | Red |
|---|---|---|---|
| WFA verdict | Pass | N/A | Likely Overfitted |
| RollWFA | 3/3 | 2/3 | 1/3 or 0/3 |
| Calmar | > 0.5 | 0.3–0.5 | < 0.3 |
| OOS P&L | Positive | Break-even | Negative |
| MaxDD | < 60% | 60–75% | > 75% |
| Trades | > 30 | 15–30 | < 15 |
| MC Score | 5 | 2–4 | -1 |

*Note: Single-asset Sharpe is less reliable than multi-asset. Use Calmar as primary risk-adjusted metric.*

---

## Bitcoin Market Context

| Period | Regime | BTC Price Range | Key Event |
|---|---|---|---|
| 2017 | Bull | $1K → $20K | First retail mania |
| 2018 | Bear | $20K → $3.2K | -84% drawdown |
| 2019-2020 | Recovery | $3.2K → $29K | COVID crash + recovery |
| 2021 | Bull | $29K → $69K | Institutional adoption |
| 2022 | Bear | $69K → $15.5K | -78% drawdown (FTX crash) |
| 2023-2024 | Recovery/Bull | $15.5K → $100K+ | ETF approval, halving |
| 2025-2026 | Bull continuation | $100K+ | Current |

**Key structural fact:** Bitcoin has 4-year halving cycles. Post-halving years (2013, 2017, 2021, 2025) are historically the strongest bull markets. Strategies should ideally capitalize on post-halving momentum and avoid deep bear markets.

---

## Champion Leaderboard

| Rank | Strategy | File | Calmar | OOS P&L | WFA | RollWFA | MaxDD | MC | Sweep | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 PROVISIONAL | BTC RSI Trend (14/60/40) + SMA200 | `btc_strategies.py` | **1.32** | +732.31% | Pass | 2/2 | 43.72% | -1† | Pending BTC-Q5 | PROVISIONAL |
| 2 ✓ CONFIRMED | MA Bounce (50d/3bar) + SMA200 Gate | `research_strategies_v4.py` | 1.22 | +476.29% | Pass | 3/3 | 46.29% | -1† | **ROBUST (75/75)** | CONFIRMED |
| 3 PROVISIONAL | BTC Donchian Wider (52/13) | `btc_strategies.py` | 0.84 | +805.13% | Pass | 3/3 | 53.02% | -1† | Pending BTC-Q5 | PROVISIONAL |

†MC Score -1 is expected/structural for single-asset Bitcoin. MC is NOT a disqualifying criterion for Bitcoin research. WFA + RollWFA are primary robustness checks.

---

## Round History

| Round | Strategy/Focus | Result | Calmar | OOS P&L | Trades | Notes |
|---|---|---|---|---|---|---|
| BTC-R1 | 5 existing equity daily champions transfer test | PARTIAL PASS | 0.63–1.22 | -161% to +1257% | 16–49 | MA Bounce top (Calmar 1.22); MA Confluence FAILS; Donchian passes |
| BTC-R2 | MA Bounce sensitivity sweep (75 variants) | **ROBUST** | 0.62–1.93 | -84% to +5001% | 42 (base) | 75/75 profitable, 70/75 WFA Pass. MA Bounce CONFIRMED champion. |
| BTC-R3 | 3 Bitcoin-specific strategies | PARTIAL PASS | 0.75–1.32 | +732% to +2050% | 20–24 | RSI Trend BEST (Calmar 1.32); Donchian 52/13 provisional; SMA200 Pure Trend rejected. |

---

## Anti-Patterns (Bitcoin-Specific)

| What Failed | Why | Lesson |
|---|---|---|
| MA Confluence Fast Exit | WFA Overfitted; OOS -160.96%. Fast MA-misalignment exit fires constantly on BTC's volatile bars → premature exits during valid uptrends. | Never use MA Confluence Fast Exit on Bitcoin. |
| Price Momentum (6m ROC >15%) | 16 trades / 9 years — insufficient for WFA validation. | For BTC single-asset, use ROC threshold ≤ 5% or shorter lookback. |
| BTC SMA200 Pure Trend (crossover entry) | Calmar 0.75 < BTC B&H (0.79). MaxDD 64.86%. Only 20 trades. SMA200 crossover fires once per 4-year cycle — too sparse. | SMA200 is a great GATE (filter) but a poor ENTRY trigger for Bitcoin. Use MA Bounce or RSI crossover for actual entries. |

---

## Key Structural Findings

### BTC-R1 (2026-04-12) — Transfer Test: 5 Equity Champions on Bitcoin
1. **MA Bounce outperforms BTC B&H risk-adjusted**: Calmar 1.22 vs BTC B&H Calmar ~0.79. MaxDD 46.29% vs ~84% B&H.
2. **MA Confluence fails WFA on Bitcoin**: Fast-exit logic overfitted to equities' smooth trends. Bitcoin volatility breaks the mechanism.
3. **MC Score not computable on single asset**: All strategies below `min_trades_for_mc=50`. Lower threshold to 20 for Bitcoin.
4. **RS(min) is severely negative on Bitcoin**: Range -3.14 to -67.08. Acceptable Bitcoin threshold: RS(min) > -20 (green), -20 to -50 (yellow), < -50 (red).
5. **CMF best RS(min) = -3.14**: Volume signal avoids selling-pressure periods naturally; may capture on-chain-like dynamics.
6. **Donchian Calmar = BTC B&H Calmar**: Not a risk-adjusted improvement but provides lower-MaxDD (60%) exposure vs B&H (84%).

---

## Production Portfolio (when research is complete)

TBD — Pending BTC-Q2 (MA Bounce sweep) and BTC-Q3 (Bitcoin-specific strategies)

---

*Last updated: 2026-04-12 (BTC-R3 complete; RSI Trend new provisional #1; BTC-Q5 sweeps next)*
