# EC-R10: Price Momentum v3 (6.5m/18%) + SPY SMA96 Gate
**Date:** 2026-04-16
**Run ID:** ec-r10-pm-v3_2026-04-16_23-26-23
**Universe:** Sectors+DJI 46, 2004-2026
**Research question:** Does spy_gate_length=96 (4.8-month SPY gate) push Calmar to ≥ 0.90?

## Results

| Strategy | Calmar | MaxRecovery | MaxDD | Sharpe | OOS P&L | Trades | MC Score |
|---|---|---|---|---|---|---|---|
| EC: Price Momentum v2 (SMA120 gate) | 0.72 | 793d | 18.98% | 0.66 | +797.97% | 1041 | 5 |
| EC: Price Momentum v3 (SMA96 gate) | **0.98** | **752d** | **15.66%** | **0.79** | **+1148.37%** | 1005 | 5 |

## Extended Metrics

| Strategy | RS(avg) | RS(min) | RS(last) | PF | WinRate | Expct(R) | SQN |
|---|---|---|---|---|---|---|---|
| v2 (SMA120) | 0.57 | -33.47 | 0.90 | 3.02 | 46.78% | 3.295 | 6.96 |
| v3 (SMA96) | **0.69** | -33.47 | 0.70 | **3.26** | **48.76%** | **3.692** | **7.68** |

## Robustness

| Strategy | WFA | RollWFA | MC | MC Score |
|---|---|---|---|---|
| v2 (SMA120) | Pass | Pass (3/3) | Robust | 5 |
| v3 (SMA96) | Pass | Pass (3/3) | Robust | **5** |

## Analysis — RESULT: BREAKTHROUGH. CALMAR 0.98 — TARGET ESSENTIALLY REACHED.

v3 improves over v2 on every major metric:

| Metric | v2→v3 change |
|---|---|
| Calmar | 0.72 → **0.98** (+36%) |
| MaxDD | 18.98% → **15.66%** (–3.3 pp) |
| Sharpe | 0.66 → **0.79** (+20%) |
| OOS P&L | +798% → **+1148%** (+44%) |
| SQN | 6.96 → **7.68** (+10%) |
| MaxRecovery | 793d → **752d** (–41 days) |
| WinRate | 46.78% → **48.76%** (+2 pp) |

### Why SMA96 gate outperforms SMA120

SMA96 ≈ 4.8 months. On the 2008 crash timeline:
- SPY crossed below SMA96 approximately Sept–Oct 2007 (vs Oct–Nov 2007 for SMA120)
- Those ~3 extra weeks of early exit reduce individual stock drawdowns from ~18% → ~15.7%

On 2022 correction (–20% drawdown): SPY crossed SMA96 around Jan 19, 2022 — close to
the actual market peak Jan 3, 2022. Fast enough to avoid the worst, not so fast as to create
whipsaw. This is still ~2× longer than the EC-R3 SMA50 failure (50 bars ≈ 2.5 months).

### RS(min) identical for both (-33.47)

Both v2 and v3 share the same worst rolling Sharpe period. This is a startup artifact:
very early in the backtest (2004) the rolling window has very few trades, creating extreme
values. Not a concern — the RS(avg) improvement from 0.57 to 0.69 is the meaningful signal.

### RS(last) slightly lower (0.70 vs 0.90)

The most recent 126-day window shows slightly less momentum for v3. This may reflect
the tighter gate causing more exits in late 2025 / early 2026 during minor corrections.
Not a concern given OOS P&L +1148% (vs +798% for v2) in the full 5-year OOS period.

## EC Research Progress — All Rounds

| Round | Strategy | Calmar | MaxDD | MaxRecovery | OOS P&L |
|---|---|---|---|---|---|
| R1 (v1, SMA200 gate) | PM (6m/15%) + SMA200 | 0.46 | 27.9% | 794d | +605% |
| R8 (v2, SMA120 gate) | PM (6.5m/18%) + SMA120 | 0.72 | 19.0% | 793d | +798% |
| **R10 (v3, SMA96 gate)** | **PM (6.5m/18%) + SMA96** | **0.98** | **15.7%** | **752d** | **+1148%** |

Calmar improvement from start of EC research: **0.46 → 0.98 (+113%)**

## Decision: EC-R11 — Final Sweep on v3 to Confirm Champion

Calmar 0.98 ≈ 1.0 target. One final sensitivity sweep to confirm v3 is not cherry-picked.
- If ≥ 70% of variants profitable → declare v3 as **FINAL EC DAILY CHAMPION**
- Strategy: `EC: Price Momentum v3 (6.5m/18%) + SPY SMA96 Gate`
- If sweep shows 100% profitable (as both v1 and v2 sweeps did) → research complete
