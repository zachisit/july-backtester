# EC Research Round 50 — Weekly Champions on NDX Tech 44 (BREAKTHROUGH: R1 pass)

**Date:** 2026-04-23
**Run ID:** ec-r50-weekly-on-ndx-tech_2026-04-23_19-56-22
**Strategies:** Williams R Weekly, Relative Momentum 13w, BB Breakout 20w (all Chapter-2 champions)
**Universe:** NDX Tech 44 (`nasdaq_100_tech.json`, native validation universe)
**Period:** 2004-01-02 → 2026-04-23
**Timeframe:** Weekly
**Allocation:** 2.5% per position
**Stop-loss:** none

## Context

EC-R49 tested the Chapter 2 weekly champions on Sectors+DJI 46 — all 3 failed catastrophically
because the strategies depend on explosive tech rallies that sectors+industrials don't provide.
EC-R50 tests them on their NATIVE validation universe (NDX Tech 44) to establish the R1 benchmark.

## Scorecard Output — First R1 Pass in 50 Rounds

```
[REJECTED but closest] Williams R Weekly Trend (above-20) + SMA200:
  R1 Beats SPY:      PASS  1072% vs SPY 859% (+213pp) ← FIRST PASS
  R2 Smooth curve:   FAIL  top1=6.92%, top5=23.85%
  R3 <365d recovery: FAIL  931 days (2.6 years)
  R4 Validation:     PASS  WFA Pass, Rolling 3/3, MC 5, OOS +731.91%

[REJECTED] Relative Momentum 13w Weekly + SMA200:
  R1 Beats SPY:      FAIL  440% vs SPY 859% (-420pp)
  R2 Smooth curve:   FAIL  top1=10.71%, top5=29.38%
  R3 <365d recovery: FAIL  1015 days
  R4 Validation:     PASS  WFA Pass, Rolling 3/3, MC 5, OOS +274.94%

[REJECTED] BB Weekly Breakout (20w/2std) + SMA200:
  R1 Beats SPY:      FAIL  415% vs SPY 859% (-445pp)
  R2 Smooth curve:   FAIL  top1=7.19%, top5=24.21%
  R3 <365d recovery: FAIL  938 days
  R4 Validation:     PASS  WFA Pass, Rolling 3/3, MC 5, OOS +215.68%
```

## Key Findings

### 1. Williams R Weekly IS the closest EC candidate in 50 rounds

**First strategy to PASS R1 (beats SPY).** 1072% P&L vs 859% SPY B&H — a 213pp margin.
OOS P&L +731.91% (extraordinary for a trend-follower). WFA Pass, Rolling 3/3, MC Score 5.

Only 2 gates to fix: R2 (smooth distribution) and R3 (<365d recovery).

### 2. Why Relative Momentum and BB Breakout fail R1 at 2.5% allocation

Chapter 2 results used **5% allocation** (fewer concurrent positions = higher P&L per trade).
Dropping to 2.5% doubles concurrent positions → dilutes per-trade impact → lower total P&L.
This is a CORRECT tradeoff for EC: higher concurrency = smoother curve. But it cost these two
strategies the beat-SPY margin.

**Only Williams R is robust enough to beat SPY at 2.5% allocation** on this universe.

### 3. R2 failure analysis — top-5 trades = 23.85% of P&L

NDX Tech 44 has ~6-8 explosive multi-year winners (NVDA, TSLA, META, AMD historically).
Williams R Weekly holds these during their big rallies. A single NVDA or TSLA position can
return 300-500% over a multi-month hold → dominates the sum-of-winners number.

This is a STRUCTURAL feature of any trend-following strategy on NDX Tech — can't be eliminated
without sacrificing the mechanism. The fix must dilute concentration:
- Lower allocation (1% instead of 2.5%) → max 44% exposure but 40-44 concurrent positions
- Larger universe (nasdaq_100 = 101 symbols) → more dispersion
- Position sizing by volatility (cap high-ATR stocks at smaller allocation)

### 4. R3 failure analysis — 931-day (2.6 year) recovery

NDX Tech was hit HARD in 2008 and 2022 (tech-heavy, high-beta). Williams R Weekly's SMA200
gate protected capital during those periods, but re-entry was slow. The actual equity curve
peak was Q4 2021; recovery to that peak came in mid-2024 — ~2.5 years.

To fix R3 we need faster re-entry post-bear. Options:
- SMA100 gate instead of SMA200 (shorter memory, re-enters 3-6 weeks earlier)
- Adaptive regime signal (e.g., SPY crosses SMA50 for 3 consecutive weeks)
- No gate + hard stops (but EC-R48 showed stops destroy the strategy)

## Verdict

**EC-R50: No champion yet, but Williams R Weekly on NDX Tech 44 is the closest in 50 rounds.**
First R1 pass. Two gates remain.

## Next Research Direction: EC-R51 — dilute concentration on Williams R Weekly

### Option A: Williams R Weekly on NDX Tech 44 at 1% allocation

Halving per-trade allocation from 2.5% to 1% doubles concurrent positions. Each NVDA/TSLA
outlier trade becomes 0.4% instead of 0.8% of portfolio P&L → smoother distribution.
Risk: total P&L drops (cash drag). Question: does it still beat SPY?

### Option B: Williams R Weekly on nasdaq_100 (101 symbols) at 2.5% allocation

Full Nasdaq 100 is 101 symbols vs NDX Tech 44's 44 symbols. 2.3× more dispersion.
Same capital per trade. More diverse winner pool → no single winner dominates 8%+.
Question: do non-tech NDX100 members provide enough momentum edge to keep R1?

### Option C: Williams R Weekly on nasdaq_100 at 1% allocation (combines A+B)

Most aggressive smoothing: 101 symbols × 1% = max 101% (realistic ~60-70% exposure).
Should crush R2 distribution (no single winner exceeds 3%). Risk: too diluted, fails R1.

### Recommendation: Run Option B first

B preserves allocation (safer P&L) while adding dispersion. If B still fails R2, go to C.
Pairing with SMA100 gate (for R3) in a single run if appropriate.

**EC-R51 plan:**
- `"strategies": ["Williams R Weekly Trend (above-20) + SMA200"]`
- Universe: `"Nasdaq 100": "nasdaq_100.json"`
- `"timeframe": "W"`, allocation 2.5%

If R51 passes R2 but still fails R3 → EC-R52 adds SMA100 variant.
