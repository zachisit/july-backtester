# Research Round 2 — Multi-Agent Improved Strategies

**Date:** 2026-04-10
**Symbols:** tech_giants.json (AAPL, MSFT, GOOG, AMZN, NVDA, META — 6 symbols)
**Period:** 2004-01-01 → 2026-04-10 (22 years)
**Data Provider:** Norgate (total-return adjusted)
**WFA Split:** 80% IS / 20% OOS (~2021-10-26)
**Run ID:** research-v2_2026-04-10_21-25-57

---

## Round 2 Strategy Origins

Each strategy was designed by a specialized analysis agent based on Round 1 weaknesses:

| Strategy | Agent | Key Change vs Round 1 |
|---|---|---|
| ROC + SMA200 Trend Filter (20d) | Momentum | Added 200-bar SMA gate to ROC |
| ROC + RSI Confirmation (20d/14d) | Momentum | RSI timing + ROC direction filter |
| EMA Crossover + ROC Gate (12/26/20d) | Momentum | EMA structural signal + ROC momentum gate |
| Donchian Breakout (40/20) | Breakout | Extended entry window 20→40 bars |
| Keltner Breakout (20d/1.5x) | Breakout | Tightened multiplier 2.0→1.5x |
| Bollinger Breakout (20d/2.0x) | Breakout | New strategy (unconditional BB breakout) |
| RSI + SMA200 Trend Filter (14/25/55) | Mean Rev | Replaced Williams %R with filtered RSI |
| VW RSI Relaxed Entry (14/40/50) | Mean Rev | Raised oversold 30→40 for more trades |
| OBV + Price EMA Dual Confirm (20/20) | Mean Rev | Volume-based signal (uncorrelated to oscillators) |

---

## Core Performance Table

| Strategy | P&L (%) | Sharpe | Max DD | MC Score | WFA Verdict |
|---|---|---|---|---|---|
| **Donchian Breakout (40/20)** | **501.94%** | **+0.42** | 15.73% | 5 | **Pass** |
| EMA Crossover + ROC Gate (12/26/20d) | 488.98% | +0.39 | 16.53% | 5 | **Pass** |
| OBV + Price EMA Dual Confirm (20/20) | 483.30% | +0.36 | 22.00% | 5 | **Pass** |
| ROC + SMA200 Trend Filter (20d) | 433.75% | +0.37 | 15.08% | 5 | **Pass** |
| Keltner Breakout (20d/1.5x) | 266.95% | +0.17 | 13.55% | 5 | **Pass** |
| Bollinger Breakout (20d/2.0x) | 195.21% | +0.03 | 12.95% | 5 | **Pass** |
| VW RSI Relaxed Entry (14/40/50) | 67.00% | -0.36 | 14.14% | 5 | Likely Overfitted |
| ROC + RSI Confirmation (20d/14d) | 17.49% | -0.85 | 14.27% | 5 | Likely Overfitted |
| RSI + SMA200 Trend Filter (14/25/55) | 1.61% | -8.96 | 1.87% | -999 | N/A |

---

## Extended Metrics

| Strategy | Calmar | PF | WinRate | Trades | Expct(R) | SQN | MaxRcvry | AvgRcvry |
|---|---|---|---|---|---|---|---|---|
| **Donchian Breakout (40/20)** | **0.53** | **3.02** | **55.47%** | 265 | **7.227** | **5.41** | 986d | 36d |
| EMA + ROC Gate | 0.50 | 1.90 | 40.70% | 968 | 1.954 | 5.21 | 977d | 37d |
| ROC + SMA200 | 0.52 | 1.88 | 39.83% | 1047 | 1.698 | 5.27 | 722d | 36d |
| OBV Dual Confirm | 0.37 | 1.61 | 35.72% | 1380 | 1.408 | 4.50 | 784d | 33d |
| Keltner (1.5x) | 0.44 | 1.90 | 41.90% | 630 | 2.187 | 4.51 | 931d | 43d |
| BB Breakout | 0.38 | 1.78 | 44.15% | 564 | 2.021 | 4.20 | 882d | 50d |
| VW RSI (40/50) | 0.16 | 1.65 | 70.63% | 446 | 1.196 | 3.30 | 1960d | 57d |
| ROC+RSI Confirm | 0.05 | 1.11 | 44.96% | 843 | 0.212 | 1.16 | 2853d | 141d |
| RSI+SMA200 (25/55) | 0.04 | 8.05 | 80.00% | **5** | 3.212 | 1.76 | 2664d | 742d |

---

## Robustness (WFA Out-of-Sample)

| Strategy | OOS P&L | WFA Verdict | MC Result |
|---|---|---|---|
| **EMA + ROC Gate** | **+204.62%** | Pass | Robust |
| **Donchian (40/20)** | **+204.60%** | Pass | Robust |
| OBV Dual Confirm | +185.93% | Pass | Robust |
| ROC + SMA200 | +154.75% | Pass | Robust |
| Keltner (1.5x) | +118.27% | Pass | Robust |
| BB Breakout | +62.61% | Pass | Robust |
| VW RSI (40/50) | +3.02% | Likely Overfitted | Robust |
| ROC+RSI Confirm | -3.30% | Likely Overfitted | Robust |
| RSI+SMA200 (25/55) | +1.17% | N/A | N/A (few trades) |

---

## Round 1 → Round 2 Improvement Summary

| Strategy | Round 1 P&L | Round 2 P&L | Round 1 OOS | Round 2 OOS | Δ Verdict |
|---|---|---|---|---|---|
| Donchian Breakout | 411.14% | **501.94%** | unknown | **+204.6%** | ✅ Major improvement |
| ROC Momentum | 554.66% | 433.75% (filtered) | unknown | +154.75% | ⚠️ Lower P&L, but SMA filter |
| Keltner Breakout | 215.66% | **266.95%** (1.5x) | unknown | **+118.27%** | ✅ Improved |
| Williams %R | 116.88% | — | — | — | ❌ Replaced by RSI+SMA200 |
| VW RSI | 36.29% | 67.00% (relaxed) | unknown | +3.02% overfitted | ⚠️ More trades but overfitted |
| BB Squeeze | 19.77% (OOS fail) | 195.21% (BB Breakout) | -0.10% | +62.61% | ✅ Significant improvement |

**New winners in Round 2:**
- **EMA + ROC Gate**: +204.62% OOS, 0.39 Sharpe, 0.50 Calmar — outstanding new strategy
- **OBV Dual Confirm**: +185.93% OOS, genuinely uncorrelated signal source

---

## Correlation Alerts

| Pair | Correlation | Action |
|---|---|---|
| ROC+SMA200 ↔ EMA+ROC Gate | r=+0.94 | High overlap — use only one in a live portfolio |
| Keltner (1.5x) ↔ OBV Dual Confirm | r=+0.72 | Moderate overlap |

---

## Key Findings

### ✅ Confirmed Winners (Pass WFA, Positive Sharpe, OOS > 100%)
1. **Donchian Breakout (40/20)** — Best balanced: highest Calmar (0.53), highest PF (3.02), highest Expectancy (7.2R), SQN 5.41. OOS +204.6%. The longer window improves trade quality massively.
2. **EMA + ROC Gate (12/26/20d)** — Best OOS (+204.6%), Sharpe 0.39, SQN 5.21. The structural EMA signal + ROC momentum gate is a powerful combination.
3. **OBV Dual Confirm** — Genuinely different signal (volume-flow, not price oscillator). OOS +185.9%. Highest trade count (1380) — needs DD management.

### ❌ Failed Round 2 Designs
1. **RSI + SMA200 (14/25/55)** — Only 5 trades total in 22 years on 6 symbols! Oversold=25 is too restrictive. Never fires.
2. **ROC + RSI Confirmation** — "Likely Overfitted" (OOS -3.3%). RSI+ROC gating too tight, strategy becomes erratic.
3. **VW RSI Relaxed (14/40/50)** — "Likely Overfitted" (OOS only +3.02%). The relaxed threshold creates too many marginal trades.

---

## Hypotheses for Round 3

### Winners to Extend
- **H1**: Donchian (40/20) on Nasdaq 100 Tech (44 symbols) — validate statistical significance at scale
- **H2**: EMA + ROC Gate with different windows (8/21, 5/13) — is 12/26 optimal?
- **H3**: OBV Dual Confirm with SMA200 filter to reduce MaxDD from 22% to <15%

### Losers to Fix
- **H4**: RSI + SMA200: increase oversold from 25 → 35 to get enough trades
- **H5**: VW RSI: drop it in favor of the OBV approach (better uncorrelated signal)
- **H6**: Can the "Likely Overfitted" flag be resolved by tightening the ROC+RSI combo?

### New Ideas
- **H7**: Donchian (40/20) + SMA200 filter: prevent entries during bear markets (reduce MaxDD from 15.7% to ~10%)
- **H8**: EMA+ROC with ATR trailing stop instead of EMA crossover exit

---

## Round 3 Strategy Plan

| Strategy | Family | Key Change | Hypothesis |
|---|---|---|---|
| Donchian (40/20) + SMA200 | Breakout | Add price > SMA200 entry gate | H7 |
| EMA + ROC Gate (8/21/20d) | Momentum | Shorter EMA windows | H2 |
| OBV + SMA200 Filter | Volume | Add SMA200 exit gate to OBV | H3 |
| RSI + SMA200 (14/35/60) | Mean Rev | Loosen oversold 25→35 | H4 |
| Donchian (40/20) on NDX Tech | Breadth | Scale to 44 symbols | H1 |
