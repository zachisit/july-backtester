# EC Research Round 52 — Williams R Weekly at 1% allocation (SMA200 vs SMA100)

**Date:** 2026-04-23
**Run ID:** ec-r52-williams-r-diluted_2026-04-23_20-01-34
**Strategies:** Williams R Weekly Trend + SMA200, Williams R Weekly Trend + SMA100
**Universe:** Nasdaq 100 (101 symbols)
**Period:** 2004-01-02 → 2026-04-23
**Timeframe:** Weekly
**Allocation:** 1% per position (HALVED from EC-R51's 2.5%)

## Scorecard

```
[REJECTED] Williams R Weekly + SMA200 @ 1% alloc:
  R1 Beats SPY:      FAIL  675% vs SPY 859% (-185pp)   ← LOST from EC-R51's +2118pp
  R2 Smooth curve:   FAIL  top1=3.32%, top5=12.15%    ← NEAR-PASS (0.32pp over)
  R3 <365d recovery: FAIL  784 days (unchanged from R51)
  R4 Validation:     PASS  WFA Pass, Rolling 3/3, MC 5, OOS +311.18%

[REJECTED] Williams R Weekly + SMA100 @ 1% alloc:
  R1 Beats SPY:      FAIL  643% vs SPY 859% (-217pp)
  R2 Smooth curve:   FAIL  top1=3.38%, top5=12.45%    ← near-pass
  R3 <365d recovery: FAIL  798 days (14 days WORSE than SMA200)
  R4 Validation:     PASS  WFA Pass, Rolling 3/3, MC 5, OOS +243.08%
```

## Key Findings

### 1. Diluting allocation 2.5% → 1% DESTROYED R1 (the only gate passing at 2.5%)

On Nasdaq 100 weekly with SMA200 gate:
- 2.5% alloc → 2977% P&L (crushes SPY by 2118pp)
- 1.0% alloc → 675% P&L (lags SPY by 185pp)

**78% P&L reduction from halving allocation.** The cause is cash drag — at 1% alloc, max
simultaneous exposure is 101% but typical deployment is 40-50% (many symbols don't meet
entry conditions simultaneously). At 2.5% alloc, the same deployment produces 100-125% max
exposure, fully utilizing capital. Halving alloc doesn't halve P&L proportionally — it
roughly quarters it.

### 2. SMA100 gate did NOT improve R3 on this universe

EC-R51 claim (Session 47 hypothesis): SMA100 re-enters 3-8 weeks earlier post-bear,
compressing equity recovery. EC-R52 falsified this:
- SMA200 variant: 784-day recovery
- SMA100 variant: 798-day recovery (14 days WORSE)

**Mechanism of the failure:** Faster re-entry via SMA100 catches more WHIPSAWS during
unresolved bear markets. In 2022, SPY crossed SMA100 several times before the true bottom —
each premature re-entry took a loss. The extra trading compounded instead of compressing
recovery.

**SMA100 gate is not a viable R3 fix on any universe that had the 2022 stair-step bear.**
EC-R41 (SMA50 rotation on S&P 500) showed the same failure mode. Anti-pattern confirmed.

### 3. R2 now NEAR-PASSING (top1 = 3.32% vs 3.0% threshold)

Both 1% variants are close to R2 pass. At 2.5% alloc, top1 = 6.93% (far over). Relation is
approximately linear × 0.6 scaling: halving allocation reduces top1 by ~52%. Full R2 pass
would require ~0.9% allocation (top1 ≈ 3.0%) — but that would further crash R1.

### 4. 52 rounds, 0 champions — architectural exhaustion

The EC requirements form a near-empty intersection in tested architectures:

| Allocation | R1 | R2 | R3 | R4 |
|---|---|---|---|---|
| 2.5% on Nasdaq 100 | PASS (+2118pp) | FAIL (top1 6.93%) | FAIL (784d) | PASS |
| 1.0% on Nasdaq 100 | FAIL (-185pp) | FAIL (top1 3.32%) | FAIL (784d) | PASS |

The R1↔R2 tradeoff is STRICT: passing R1 requires concentrated positions producing jagged
P&L (1-3 big winners per 100 trades). Passing R2 requires dispersion that reduces P&L below
SPY. No allocation value on Nasdaq 100 passes both.

R3 (<365d recovery) is INDEPENDENT of R1/R2 tradeoff — depends on bear-market handling, not
allocation. SMA100 gate doesn't help (whipsaws). SMA200 is too slow. Probably needs:
- Explicit short side during bear (VIX>35 → short SPY 20% of book)
- Options overlay (long puts on SPY at high VIX)
- OR accept 2-year recoveries as market-relative acceptable

## Recommendation — Present findings honestly to human operator

### Honest summary of 52-round EC research

**No strategy has passed all 4 hard EC requirements.** The best candidate found is
**Williams R Weekly Trend (above-20) + SMA200 on Nasdaq 100 at 2.5% allocation**
(EC-R51 baseline):
- R1: PASS ENORMOUSLY (+2118pp vs SPY, 3.5× the SPY total return)
- R2: top1 = 6.93% (NVDA-class winners dominate — visible steps in the equity curve)
- R3: 784-day recovery (2.1 years) — violates strict <365d but is tied to 2008 + 2022 deep bears
- R4: Full pass (WFA, Rolling 3/3, MC 5, OOS +1770%)

### Human decision needed

The strict R2 (<3% top1) and R3 (<365d recovery) thresholds may be too tight for a strategy
that also beats SPY by 3.5×. The architectural tradeoffs are:

| Can achieve | At cost of |
|---|---|
| Beat SPY massively (R1) | Concentrated winners, jagged curve (fails R2) |
| Smooth distribution (R2) | Cash drag, lags SPY (fails R1) |
| Fast recovery (R3) | Requires short/options overlay (not yet built) |

**Proposed user decisions:**
1. **Relax R2 threshold** (e.g., top1 < 5%, top5 < 20%) → EC-R51 becomes champion-eligible.
   Visual review of PDF is the final test.
2. **Relax R3 threshold** (e.g., <730 days for a strategy beating SPY by 2×+) — recognizes
   that 2008 is a 5-year market-wide recovery; strategy recovery being 2 years is actually
   faster than market.
3. **Build short-side overlay** (EC-R53): add short SPY during VIX>35 to EC-R51. Requires
   verifying the engine's short-side (signal=-2) mechanism at scale — currently untested.
4. **Accept defeat**: the 4-gate intersection is empty within pure-long architectures.
   Present EC-R51 to the user as best-effort and let them decide if it meets their real
   (non-stringent) expectations.

## Proposed EC-R53

**Present EC-R51 PDF to human for visual review.** Stop spawning new research rounds until
the user has reviewed the best candidate and decided whether to relax thresholds or pivot
to short-side overlay.
