# EC Research Round 51 — Williams R Weekly on Nasdaq 100

**Date:** 2026-04-23
**Run ID:** ec-r51-williams-r-ndx100_2026-04-23_19-58-51
**Strategy:** Williams R Weekly Trend (above-20) + SMA200
**Universe:** Nasdaq 100 (`nasdaq_100.json`, 101 symbols)
**Period:** 2004-01-02 → 2026-04-23
**Timeframe:** Weekly
**Allocation:** 2.5% per position

## Scorecard

```
R1 Beats SPY:      PASS   2977% vs SPY 859% (+2118pp margin — 3.5× SPY)
R2 Smooth curve:   FAIL   top1=6.93%, top5=23.37%
R3 <365d recovery: FAIL   784 days (2.1 years) — improved from NDX Tech's 931d
R4 Validation:     PASS   WFA Pass, Rolling 3/3, MC 5, OOS +1770.24%
```

**2/4 pass. R1 and R4 crushing. R2 and R3 still failing.**

## Key Findings

### 1. R1 margin EXPANDED from +213pp to +2118pp

Going from NDX Tech 44 to Nasdaq 100 (2.3× more symbols) produced 3× more total P&L.
Why: Nasdaq 100 captures the FULL tech-mega-cap complex plus non-tech growth (MELI, ISRG, GILD,
etc.) — more opportunities without losing quality. OOS +1770% is spectacular.

### 2. R2 did NOT improve — concentration is symbol-level, not universe-level

Top1 = 6.93% (same as NDX Tech's 6.92%). Top5 = 23.37% (vs NDX Tech's 23.85%).

**The NVDA/AAPL/MSFT problem is in both universes.** Expanding the universe adds more AVERAGE
symbols but doesn't dilute the contribution of the genuine mega-winners when captured. The
few trades where the strategy held NVDA through a multi-year rally dominate regardless of how
many symbols are in the scanning universe.

**Fix: reduce per-trade allocation (not universe size).** At 1% allocation, each trade's max
impact is 1/2.5 = 40% of current. NVDA top trade would drop from 6.93% to ~2.8% of total —
inside the R2 threshold. Downside: total P&L likely drops due to cash drag on high-setup weeks.

### 3. R3 improved from 931d to 784d (16% faster recovery)

Broader universe means more post-bear entries become available, speeding recovery. But still
2.1 years — violates R3's 365-day ceiling.

**R3 fix must be structural:** the SMA200 gate re-enters slowly. An SMA100 (or adaptive SPY
regime) gate re-enters 3-8 weeks earlier. For the Williams R Weekly strategy specifically,
this requires a new variant (current implementation hard-codes SMA200).

## Verdict

EC-R51 confirms Williams R Weekly is the RIGHT strategy. The question is tuning: can we
dilute concentration (R2) without losing the SPY-beat margin (R1)? 2118pp of R1 margin
is enormous — there's huge room to sacrifice some P&L for smoothness.

## EC-R52 Direction: 1% allocation + SMA100 variant

Change two levers simultaneously (single run, efficient):
1. **Allocation 2.5% → 1%** (test variant: "EC-R52 Williams R Weekly 1% alloc on Nasdaq 100")
   → target: R2 pass (top1 <3%, top5 <15%)
2. **Create Williams R Weekly variant with SMA100 gate** — new strategy in
   `custom_strategies/round34_strategies.py` (or smooth_curve_strategies.py):

```python
@register_strategy(
    name="Williams R Weekly Trend (above-20) + SMA100",
    dependencies=[],
    params={"wr_period": 14, "wr_threshold": -20, "gate_period": 100},
)
```

Compare side-by-side:
- A: Williams R Weekly + SMA200, 1% alloc
- B: Williams R Weekly + SMA100, 1% alloc
- C: Williams R Weekly + SMA200, 2.5% alloc (baseline = EC-R51)
- D: Williams R Weekly + SMA100, 2.5% alloc

4 variants, one run. Whichever variant (if any) passes all 4 gates → CHAMPION.

**Risk:** SMA100 variant may fail R4 WFA if too reactive (similar to the EC-R44 VIX gate
failure mode). The 200-period gate is the proven one.
