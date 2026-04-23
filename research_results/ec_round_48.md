# EC Research Round 48 — Stop-Loss Sweep on EC-R39b (ALL FAIL)

**Date:** 2026-04-23
**Run ID:** ec-r48-stop-loss-sweep_2026-04-23_19-42-00
**Strategy:** EC-R39b: Mean Rev to SMA20 (5%/3% wide) + SMA200 Gate [Daily] (UNCHANGED)
**Stop configs tested:** none, 7% pct, 10% pct, 2.0× ATR(14) trailing
**Universe:** S&P 500 Current & Past
**Period:** 2004-01-02 → 2026-04-23
**Allocation:** 2.5% per position
**Scored with:** `scripts/score_ec_candidate.py`

## Context

Session 43 retracted the EC-R46 champion claim after the scoring helper revealed
EC-R42→R47 failed both R1 (beat SPY) and R3 (<365d recovery). The hypothesis for
EC-R48: apply per-stock stop-losses to the ONLY confirmed beats-SPY base (EC-R39b)
to compress 2008 recovery from 5.4 years to <365 days WITHOUT filtering entries.
Stop-losses cap individual trade loss — a totally different mechanism from entry gates.

## Scorecard Output

```
[REJECTED] EC-R39b (no stop):
  R1 Beats SPY:       FAIL  677% vs SPY 859% (-183pp)
  R2 Smooth curve:    PASS  top1=2.09%, top5=6.53%
  R3 <365d recovery:  FAIL  max recovery 1886 days (5.2 years)
  R4 Validation:      PASS  WFA Pass, Rolling 3/3, MC 5, OOS +212.55%

[REJECTED] EC-R39b w/ 10% SL:
  R1 Beats SPY:       FAIL  154% vs SPY 859% (-705pp)
  R2 Smooth curve:    FAIL  top1=46.98%, top5=54.77% (one outlier dominates)
  R3 <365d recovery:  FAIL  max recovery 6048 days (16.6 YEARS — worse than no stop!)
  R4 Validation:      PASS  WFA Pass, Rolling 3/3, MC 5

[REJECTED] EC-R39b w/ 7% SL:
  R1 Beats SPY:       FAIL  -20% (LOSS)
  R2 Smooth curve:    undefined (total P&L negative)
  R3 <365d recovery:  FAIL  391 days (just over threshold)
  R4 Validation:      FAIL  MC 2<4, OOS only +3%

[REJECTED] EC-R39b w/ 2.0× ATR(14) SL:
  R1 Beats SPY:       FAIL  5% (near-zero)
  R2 Smooth curve:    FAIL  top1=851% of total P&L (total P&L is noise, not signal)
  R3 <365d recovery:  PASS  198 days ← ONLY PASS of the run
  R4 Validation:      FAIL  MC 2<4

*** 0/4 candidates pass all four hard requirements ***
```

## Key Findings

### 1. EC-R39b baseline NO LONGER beats SPY on full 2004-2026 data

Session 38 reported EC-R39b P&L = 700% vs SPY B&H 534% (beat SPY by 166pp). The current
run shows EC-R39b P&L = 677% vs SPY B&H 859% (LAGS by 183pp).

The strategy is unchanged — SPY B&H grew from 534% → 859% as the backtest extended and
the 2024-2025 bull extended SPY's lead. EC-R39b didn't scale at the same rate because the
5% pullback entry filter blocked many 2024-2025 setups (SPY rarely pulled back 5% in 2024).

**This invalidates Session 38's "EC-R39b beats SPY" claim for all periods other than the
specific earlier snapshot.** Req 1 is currently failed even by the no-stop base.

### 2. Stop-losses DESTROY mean reversion — the mechanism is fundamentally incompatible

Mean reversion entries are DESIGNED to catch falling knives. The stock is at a pullback;
it often continues down 3-7% before bouncing. A 7% stop gets hit by normal pullback
continuation. A 10% stop catches only the extreme continuations.

The perverse result: 10% stop produced WORSE 2008 outcomes than no stop. Why? The stop
exits at bad prices (locks in ~10% losses on every stock that bounces back), guaranteeing
capital destruction during coordinated sector declines. The "no stop" baseline at least
has the chance to recover on the bounce. 6048-day max recovery with the 10% stop = the
strategy effectively never recovered from 2008 lock-in losses.

**Anti-pattern confirmed:** Never apply hard stop-losses to SMA-target mean reversion. The
only stop that preserves the mechanism is ATR-trailing, and even that reduces P&L to noise.

### 3. 2.0× ATR trailing stop is the ONLY variant to achieve <365d recovery

But it reduces total P&L to 5.44% (essentially zero). The strategy stops working — it
becomes a series of tiny wins cancelled by tiny losses. MC Score drops to 2 (fails R4).
Tight trailing stops + mean-reversion entries + 2.5% allocation = a strategy that generates
transaction costs without accumulating alpha.

### 4. Annual P&L Comparison (EC-R39b with each stop variant)

| Year | No Stop | 7% SL | 10% SL | 2.0× ATR |
|---|---|---|---|---|
| 2005 | +$13k | -$3k | +$6k | +$0.5k |
| 2007 | +$14k | -$2k | +$8k | -$1k |
| 2008 | **-$62k** | -$1.6k | **-$99k** | -$0.5k |
| 2013 | +$85k | +$2k | +$27k | +$0.3k |
| 2020 | +$42k | -$5k | +$19k | -$0.2k |
| 2022 | -$84k | -$3k | -$85k | -$0.1k |

Stops with hard percentage thresholds produce **worse** 2008 outcomes than no stop
(-$99k vs -$62k) because stops activate during coordinated sector declines, producing
40-60 simultaneous forced exits at cascading-down prices.

## Verdict

**EC-R48: TOTAL FAILURE across all 4 variants.** The stop-loss hypothesis was wrong.
Mean reversion + stop-loss is architecturally incompatible. The direction is dead.

**Bigger finding:** EC-R39b itself no longer beats SPY on current data. Session 38's
"beats SPY" claim relied on a shorter backtest window. Even without stops, the
mean-reversion-to-SMA20 architecture lags SPY in the current 2004-2026 data.

## Anti-patterns added (permanent — do not retry)

- **Hard percentage stop-loss on SMA-target mean reversion** — exits at bad prices,
  extends recovery, destroys alpha. Root cause: mean reversion pullback entries expect
  price continuation BEFORE the bounce; stops fire during that continuation.
- **Tight ATR trailing on mean reversion** — reduces strategy to transaction noise
  (MC 2, P&L <10%). ATR trailing stops work only on trend-following strategies.

## Next Research Direction: EC-R49 — Test Chapter 2 Weekly Champions against EC Criteria

Chapter 2 (R1-R51 research, complete) identified weekly trend-following champions:

| Strategy | P&L | Universe | Sharpe | WFA | MC |
|---|---|---|---|---|---|
| Relative Momentum (13w vs SPY) Weekly + SMA200 | 166,502% | NDX Tech 44 | 2.08 | Pass | 5 |
| BB Weekly Breakout (20w/2std) + SMA200 | 152,197% | NDX Tech 44 | 2.08 | Pass | 5 |
| Williams R Weekly Trend (above-20) + SMA200 | 156,992% | NDX Tech 44 | 1.94 | Pass | 5 |

These WILDLY beat SPY (166,502% >> 859%). They passed WFA/MC. Unknown whether they
pass EC's R2 (distribution smooth) and R3 (<365d recovery).

**EC-R49 plan:** Run these 3 champions on S&P 500 (not their historical NDX Tech 44
universe — need broader dispersion), timeframe=Weekly, then score with
`scripts/score_ec_candidate.py`. If any pass all 4 EC gates → that's the champion.
If none pass R2 or R3 → EC research must accept that the 4-gate intersection is empty
within tested architectures and pivot to long/short or options overlay.

**Critical principle reminder:** this is NOT introducing new strategies with new
parameters. It's scoring EXISTING confirmed strategies against the EC requirements.
No multiple-hypothesis overhead added.
