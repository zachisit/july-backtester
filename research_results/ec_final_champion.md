# EC RESEARCH — FINAL DAILY CHAMPION
**Declared:** 2026-04-17
**Research rounds:** EC-R1 through EC-R11 (11 rounds, 6 weeks of research)

---

## CHAMPION STRATEGY

**Name:** `EC: Price Momentum v3 (6.5m/18%) + SPY SMA96 Gate`

**Parameters:**
| Param | Value | Meaning |
|---|---|---|
| `roc_period` | 151 bars | 6.5-month price rate-of-change lookback |
| `roc_threshold` | 18.0% | Entry only if ROC > 18% (strong momentum) |
| `sma_slow` | 200 bars | Stock must be above its 200-day SMA (uptrend filter) |
| `spy_gate_length` | 96 bars | SPY must be above its 96-day SMA (≈4.8-month macro filter) |

**Universe:** Sectors+DJI 46 (46 US equities — sector ETF leaders + Dow Jones components)
**Period:** 2004-01-01 → present
**Timeframe:** Daily (D)
**Allocation:** 10% equity per position (max 10 concurrent positions)

---

## PERFORMANCE METRICS

| Metric | Value | Benchmark (SPY B&H) |
|---|---|---|
| Full-period P&L (2004–2026) | **+2295%** | +850% |
| vs. SPY (B&H) | **+1445%** | — |
| **Calmar Ratio** | **0.98** | ~0.25 |
| **Max Drawdown** | **15.66%** | ~55% (2008) |
| **Sharpe Ratio** | **0.79** | ~0.45 |
| **OOS P&L** (WFA 20% period, 2021–2026) | **+1148%** | +34% |
| Max Recovery (days from trough→peak) | 752 days | N/A |
| Avg Recovery | 26 days | N/A |
| Profit Factor | 3.26 | N/A |
| Win Rate | 48.76% | N/A |
| SQN | 7.68 | N/A |
| Trades | ~1005 | N/A |

---

## ROBUSTNESS VALIDATION

| Test | Result |
|---|---|
| Monte Carlo (1000 sims) | **MC Score 5 — Robust** |
| Walk-Forward Analysis | **Pass** |
| Rolling WFA (3 folds) | **Pass (3/3)** |
| Sensitivity sweep (±20%, 625 variants) | **100% profitable — Robust** |
| Sweep confirmed across 3 generations | EC-R7, EC-R9, EC-R11 all 100% |

---

## HOW THE STRATEGY WORKS

**Entry logic (all three must be true):**
1. Stock's 6.5-month ROC > 18% — strong price momentum
2. Stock's close > its 200-day SMA — individual uptrend confirmed
3. SPY's close > its 96-day SMA — macro bull market regime confirmed

**Exit logic (any one triggers exit):**
1. Stock's 6.5-month ROC drops below 0% — momentum gone
2. Stock falls below its 200-day SMA — uptrend broken
3. SPY falls below its 96-day SMA — macro regime turned bearish

**The SPY regime gate is the key innovation.** During 2008 and 2022 bear markets,
SPY crossing below SMA96 forces all positions to exit and blocks new entries. This
reduces MaxDD from ~28% (no gate) to ~16% (with SMA96 gate) — a 43% improvement.

---

## RESEARCH JOURNEY

| Round | Key Experiment | Finding | Calmar |
|---|---|---|---|
| R1 | Add SPY SMA200 gate to base strategies | Gate reduces MaxRecovery 35%, all MC Score 5 | 0.46 |
| R2 | 10% stop loss on sector ETFs | REJECTED: destroys edge, negative Sharpe | — |
| R3 | SPY SMA50 gate (faster) | REJECTED: whipsaw, worse results | — |
| R4 | Start 2004 (exclude dot-com) | All MC Score 5, Calmar 0.46 confirmed | 0.46 |
| R5 | 16 sector ETFs only | REJECTED: too few trades, too few symbols | — |
| R6 | Relative momentum vs Price momentum | Inferior (Calmar 0.39 vs 0.46) | 0.39 |
| R7 | Sensitivity sweep on v1 | **100%/625 profitable** → directional signal: 151-bar lookback | 0.46 |
| R8 | v2: 151-bar ROC + 18% threshold + SMA120 gate | +57% Calmar improvement | 0.72 |
| R9 | Sensitivity sweep on v2 | **100%/625 profitable** → directional signal: 96-bar gate | 0.72 |
| R10 | v3: SMA96 gate | Calmar 0.98 — target essentially reached | 0.98 |
| R11 | Final sweep on v3 | **100%/625 profitable** — CHAMPION CONFIRMED | 0.98 |

**Total Calmar improvement:** 0.46 → 0.98 (+113%) over 11 research rounds.

---

## STRUCTURAL FINDINGS (Anti-Patterns & Lessons)

**Anti-patterns confirmed:**
1. **Short stop losses (10%)** destroy momentum edge — momentum needs room to breathe
2. **Very short SPY gate (SMA50 / 50 bars)** creates whipsaw in corrections — minimum safe gate ≈ 90 bars
3. **Too few symbols (< 30) or too-diversified ETFs** create sparse trade counts → unreliable statistics
4. **Long SPY gate (SMA200)** leaves money on the table during bear markets

**Key findings:**
1. SPY regime gate is the single most important structural improvement for daily equity momentum
2. Gate length matters more than lookback period: SMA96 beats SMA120 beats SMA200
3. The 2008 crash creates the binding MaxRecovery constraint (~750 days inescapable)
4. Calmar ≥ 1.0 remains structurally elusive on daily US equities without short selling — 0.98 is near-maximum
5. Parameter sweeps as directional search: 100% profitable sweeps reveal the landscape gradient

---

## FILES

| File | Contents |
|---|---|
| `custom_strategies/smooth_curve_strategies.py` | Strategy code (v1, v2, v3 + 6 other EC variants) |
| `research_results/ec_round_1.md` through `ec_round_11.md` | Detailed round-by-round results |
| `research_results/ec_final_champion.md` | This file — champion profile |
| `tickers_to_scan/sectors_dji_combined.json` | 46-symbol universe used |
