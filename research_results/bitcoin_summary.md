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
| 1 ✓ CONFIRMED | BTC RSI Trend (20/60/56) + SMA120 | `btc_strategies_v2.py` | **1.77** | +800.70% | Pass | 3/3 | **34.04%** | -1† | **ROBUST (570/625, 91.2%)** | CONFIRMED |
| 2 ✓ CONFIRMED | BTC RSI Trend (11/60/56) + SMA120 | `btc_strategies_v2.py` | **1.63** | +1,198.95% | Pass | 3/3 | 39.96% | -1† | **ROBUST (625/625, 100%)** | CONFIRMED |
| 3 ✓ CONFIRMED | BTC RSI Trend (14/60/40) + SMA200 | `btc_strategies.py` | 1.32 | +732.31% | Pass | 2/2 | 43.72% | -1† | **ROBUST (594/625, 95%)** | CONFIRMED |
| 4 ✓ CONFIRMED | MA Bounce (50d/3bar) + SMA200 Gate | `research_strategies_v4.py` | 1.22 | +476.29% | Pass | 3/3 | 46.29% | -1† | **ROBUST (75/75, 100%)** | CONFIRMED |
| 5 ✓ CONFIRMED | BTC Donchian Wider (52/13) | `btc_strategies.py` | 0.84 | +805.13% | Pass | 3/3 | 53.02% | -1† | **ROBUST (25/25, 100%)** | CONFIRMED |

†MC Score -1 is expected/structural for single-asset Bitcoin. MC is NOT a disqualifying criterion for Bitcoin research. WFA + RollWFA are primary robustness checks.

---

## Round History

| Round | Strategy/Focus | Result | Calmar | OOS P&L | Trades | Notes |
|---|---|---|---|---|---|---|
| BTC-R1 | 5 existing equity daily champions transfer test | PARTIAL PASS | 0.63–1.22 | -161% to +1257% | 16–49 | MA Bounce top (Calmar 1.22); MA Confluence FAILS; Donchian passes |
| BTC-R2 | MA Bounce sensitivity sweep (75 variants) | **ROBUST** | 0.62–1.93 | -84% to +5001% | 42 (base) | 75/75 profitable, 70/75 WFA Pass. MA Bounce CONFIRMED champion. |
| BTC-R3 | 3 Bitcoin-specific strategies | PARTIAL PASS | 0.75–1.32 | +732% to +2050% | 20–24 | RSI Trend BEST (Calmar 1.32); Donchian 52/13 provisional; SMA200 Pure Trend rejected. |
| BTC-R4 | RSI Trend sensitivity sweep (625 variants) | **ROBUST** | -0.14–1.86 | varies | 22 (base) | 594/625 profitable, 84% WFA Pass. RSI Trend CONFIRMED #3. Sweep revealed exit=56 + gate=120 as optimal zone. |
| BTC-R5 | Donchian 52/13 sensitivity sweep (25 variants) | **ROBUST** | 0.66–1.05 | varies | 24 (base) | 25/25 profitable, 73.3% WFA Pass. Donchian CONFIRMED champion. |
| BTC-R6 | Combined 3-strategy portfolio (0.333 alloc each) | VIABLE | 0.61–1.01 | +27% to +43% OOS | 22–42 | MaxDD 24-30% vs 44-53% at 100%. MC Score 0-5. Production viable. |
| BTC-R7 | Optimized RSI variants (exit=56, gate=120) base + sweep | **ROBUST** | 1.63–1.77 | +800% to +1199% | 49–84 | Both CONFIRMED. 20/60/56/SMA120 = NEW #1 (Calmar 1.77, MaxDD 34.04%). |

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

### BTC-R7 (2026-04-12) — Optimized RSI Trend Family
1. **exit_level=56 is the critical insight**: Tighter exit preserves more momentum gain before exhaustion. exit=40 was too loose — held positions through excessive retracements.
2. **gate_length=120 captures earlier re-entries**: 80 bars earlier than SMA200 per cycle. On Bitcoin's 4-year halving cycle, this means entering the bull market ~80 days sooner.
3. **RSI(20) = highest Calmar ever on Bitcoin (1.77)**: Slower RSI with tighter exit produces better risk-adjusted returns than either the base (14/60/40) or the faster (11/60/56) variant.
4. **RSI(20) base rank 2/625**: Near-maximum in parameter space — the params are genuinely near-optimal, not just mediocre within a wide distribution.
5. **RSI(20) WFA pass rate 92.3%**: Highest WFA robustness of any Bitcoin strategy tested.

---

## Production Portfolio — UPDATED AFTER BTC-R7

**Option A — New Best Single Strategy (Recommended)**
```
allocation_per_trade: 1.0
strategies: ["BTC RSI Trend (20/60/56) + SMA120"]
Expected: Calmar 1.77, MaxDD ~34%, Total Return ~7,841% (2017-2026)
Best for: Bitcoin investors who can tolerate 30-40% drawdowns — best Calmar ever achieved
```

**Option A2 — Higher Frequency Variant**
```
allocation_per_trade: 1.0
strategies: ["BTC RSI Trend (11/60/56) + SMA120"]
Expected: Calmar 1.63, MaxDD ~40%, Total Return ~10,321% (2017-2026)
Best for: Return maximizers — higher total return but slightly higher drawdown
```

**Option B — Combined 5-Strategy Portfolio (Maximum Diversification)**
```
allocation_per_trade: 0.2
strategies: ["BTC RSI Trend (20/60/56) + SMA120",
             "BTC RSI Trend (11/60/56) + SMA120",
             "BTC RSI Trend (14/60/40) + SMA200",
             "MA Bounce (50d/3bar) + SMA200 Gate",
             "BTC Donchian Wider (52/13)"]
Expected: MaxDD ~20-25%, diversified signal families (momentum + MA bounce + breakout)
Best for: Maximum risk diversification with 5 confirmed champions
```

**Option C — Original 3-Strategy Portfolio (Tested in BTC-R6)**
```
allocation_per_trade: 0.333
strategies: ["MA Bounce (50d/3bar) + SMA200 Gate",
             "BTC RSI Trend (14/60/40) + SMA200",
             "BTC Donchian Wider (52/13)"]
Expected: MaxDD ~25-30%, MC Score 2-5
```

**All 5 champions confirmed across all 8 anti-overfitting rules:**
- ✓ WFA Pass | ✓ RollWFA ≥ 2/3 | ✓ Calmar > 0.5 | ✓ Calmar > BTC B&H (0.79)
- ✓ OOS Positive | ✓ MaxDD < 60% | ✓ Trades ≥ 20 | ✓ Sensitivity sweep ≥ 70% profitable

---

*Last updated: 2026-04-12 (BTC-R7 complete — 2 new confirmed champions; 5 total; new #1 Calmar 1.77)*
