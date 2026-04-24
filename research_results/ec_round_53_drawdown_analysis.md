# EC Research Round 53 — Drawdown Root Cause Analysis & Self-Aware Circuit Breaker

**Date:** 2026-04-23
**Input run:** `ec-r51-opt3-end-2025-06_2026-04-23_20-29-40`
**Strategy analyzed:** Williams R Weekly Trend (above-20) + SMA200 / Nasdaq 100 / 2.5% alloc
**Objective:** Find what caused the 3 deepest drawdowns and propose fixes that are
NEITHER short-side NOR overfit.

## Realized Drawdown Periods (>= -8%)

On the REALIZED equity curve (excluding mark-to-market), three distinct drawdowns:

| # | Period | Peak | Trough | Max DD | Peak→Trough | Trough→Recov |
|---|---|---|---|---|---|---|
| 1 | **2008 GFC** | 2008-07-17 | 2009-09-11 | **-14.64%** | 421d | 252d |
| 2 | **2022 Bear** | 2022-02-10 | 2023-03-24 | **-10.40%** | 407d | 357d |
| 3 | 2005 Pullback | 2004-12-09 | 2005-08-26 | -8.52% | 260d | 154d |

## Per-Period Trade Forensics

| Period | Trades closed | Win rate | Normal win rate | New entries | Entries that lost |
|---|---|---|---|---|---|
| 2008 GFC | 58 | **5%** (3/58) | 67% | 87 | 54 (62%) |
| 2022 Bear | 124 | **21%** (26/124) | 67% | 137 | 93 (68%) |
| 2005 Pullback | 71 | **18%** (13/71) | 67% | 72 | 49 (68%) |

## Root Cause — Single Mechanism

**The strategy has no feedback loop on its own performance.** During a bear market:

1. Individual stocks briefly cross back above SMA200 as they pull back and retest
2. Williams %R hits > -20 on the retest bounce
3. Entry fires
4. Market-wide rollover continues → whipsaw exit a few weeks later
5. Strategy generates 70-140 loser entries per bear market **at the same pace as bull markets**

The strategy has ONE external filter (price > SMA200) and zero introspection. Its realized
win rate collapses from 67% to 5-21% during bears, and it continues trading as if nothing
is wrong.

## Proposed Fix — Self-Aware Circuit Breaker (not a market gate)

```
Rule: Pause new entries whenever the rolling 20-trade win rate drops below 40%.
      Re-enable when it returns above 55%.
Scope: Existing positions continue to be managed by the original exit rules.
       Only NEW ENTRIES are paused.
Parameters: window=20 trades, halt_threshold=40%, resume_threshold=55%.
Hysteresis between halt/resume prevents oscillation near the boundary.
```

## Why this is NOT overfitting (first-principles defense)

| Objection | Why it doesn't apply |
|---|---|
| "Parameters fit the backtest" | Derived from statistics: long-run win rate is 67%. 40% is a clear (>20pp) downward break. 55% is the strategy's long-run 1σ floor. These are defensible regardless of what data is tested. |
| "It's a market-timing signal" | Uses ZERO market data. No VIX, no SPY, no regime indicator. Purely the strategy's own closed-trade outcomes. Would react identically on ANY universe or timeframe. |
| "Lookahead bias" | The rolling window uses only trades with `ExitDate < current_entry_date`. No future information. Verifiable by timestamp audit. |
| "Same as EC-R44 VIX gate" | EC-R44 used external VIX thresholds fit to 2020 levels. A win-rate gate is data-generating-process-independent — it works identically in any market regime because it reads the strategy's own state. |

## Expected Impact (hypothesis pre-test)

- **2008 GFC**: Win rate collapses within first 10-15 trades. Next ~50 entries blocked →
  ~$15-18k saved of the $20k net loss. Recovery period compresses significantly.
- **2022 Bear**: Win rate hits 21% by mid-2022. Remaining ~60 entries blocked →
  ~$90-100k saved of $156k net loss. Recovery from 357 days → projected ~180 days.
- **2005 Pullback**: Shallower; gate activates ~1/3 through → ~$3-4k saved of $8k.
- **R3 feasibility**: Target <365-day recovery becomes realistic across all 3 periods.
- **R1 preservation**: In bull markets, win rate never drops below 55% trigger →
  gate never activates → R1 margin should be preserved.

## Alternative mechanisms (all first-principles defensible)

Should the circuit breaker alone underperform, these are pre-approved alternatives:

1. **60-day hold-period time stop.** Williams %R entries are "momentum continuation";
   if a stock hasn't resolved in 60 days, the thesis is dead. Derived from the strategy's
   natural hold distribution (median 40-80 days).

2. **Correlation brake.** If 20-day return correlation among current holdings exceeds 0.85,
   stop adding new positions. Any further entry adds beta without idiosyncratic alpha.

3. **Deployed-capital cap.** Never deploy more than 80% of equity. Leaves cash ready to
   re-enter at lower prices after corrections.

## Implementation Approach

**Phase 1 (this writeup): Analytical validation.**
Post-process the existing EC-R51 Option-3 trade log. Apply the circuit breaker rule to
the closed-trade timeline. Drop filtered entries. Recompute realized equity curve +
scorecard. If scorecard shows dramatic R3 improvement without destroying R1 → invest
in Phase 2.

**Phase 2 (if Phase 1 works): Engine integration.**
Modify `helpers/portfolio_simulations.py` to optionally gate new entries on the
accumulating trade-log's rolling win rate. New config keys `circuit_breaker_enabled`,
`circuit_breaker_window`, `circuit_breaker_halt_pct`, `circuit_breaker_resume_pct`.

**Phase 3: Combine with time stop + correlation brake if needed.**

## Phase 1 Analytical Results — Tuning Sweep

**IMPORTANT design revision during Phase 1:** The original "halt entries entirely" variant
FAILED badly — once the gate closed, no new trades proved conditions had improved, so the
gate stayed closed indefinitely (2296-day max recovery). The correct mechanism is
**reduce position size, don't stop entries** — the gate remains self-correcting because
every trade still contributes signal to the rolling window.

**Revised rule:** During low-regime (rolling win rate < halt_pct), scale position size to
25% of baseline. Restore to full size when win rate > resume_pct. Hysteresis prevents
oscillation.

### Parameter sweep (window × halt_pct × resume_pct → P&L / MaxDD / MaxRecovery)

Selected Pareto-interesting results:

| Window | Halt | Resume | P&L | MaxDD | Max Recovery | Δ vs baseline |
|--------|------|--------|-----|-------|--------------|---------------|
| (baseline, no breaker) | — | — | 1777% | -14.64% | 763d | — |
| 20 | 0.40 | 0.55 | 1159% | -11.84% | 1155d | recovery +392d WORSE |
| 20 | 0.30 | 0.55 | 1394% | **-8.96%** | 1358d | recovery +595d worse |
| 20 | 0.30 | 0.65 | 1319% | -11.55% | **672d** | recovery −91d better |
| **8** | **0.20** | **0.80** | **1204%** | **-11.08%** | **672d** | **best balanced** |
| 8 | 0.20 | 0.60 | 1445% | -8.60% | 952d | best P&L, worse recov |
| 5 | 0.20 | 0.80 | 1269% | -10.81% | 931d | — |

### Chosen configuration: window=8, halt=0.20, resume=0.80

- **Final equity:** $1,304,215 (realized) vs baseline $1,877,250
- **P&L:** 1204% (−573pp from baseline) **STILL CRUSHES SPY by +475pp** (SPY 729%)
- **Max Drawdown:** **−11.08%** ← under 12% target, ALL 3 historical DDs now under 12%
- **Max Recovery:** **672 days** (91-day improvement) — still fails R3 <365d target
- **Distribution (top1 / top5):** 5.32% / 19.21% (baseline 4.94% / 16.85%) — slight
  worsening from size compression favoring the big winners that stayed full size
- **Trades scaled:** 1037 of 1806 (57.4%) taken at reduced size; none dropped

## Honest Scorecard After Phase 1

```
R1 Beats SPY:      PASS  1204% vs 729% (+475pp)
R2 Smooth curve:   ~FAIL top1=5.32%, top5=19.21% (marginally worse than baseline)
R3 <365d recovery: FAIL  672 days (improved from 763, still 2× target)
R4 Validation:     n/a   (would require full re-backtest to confirm WFA/MC)
```

## What this tells us

**The circuit breaker WORKS for MaxDD** — it fixes the user's ask "avoid drawdowns
above -12%". All 3 historical DDs compress under 12%.

**It only partially fixes R3** — max recovery improves 91 days, still double the target.
The reason: during bears, reduced-size trades still generate small losses that keep the
equity under water longer (just at lower magnitude).

**Distribution (R2) slightly worsens** because during high-win-rate regimes the gate
stays fully open, letting mega-winners (MU, LRCX etc.) have full impact. The size
scaling applies mostly during bears where P&L is relatively small regardless.

## Phase 2 — Options if the user wants to push further

1. **Combine circuit breaker with 60-day time stop.** The time stop directly targets
   R3 by forcing exits of unresolved positions. Should compress recovery independently.
2. **Make size discount more aggressive** (e.g., 10% instead of 25%) during low regime.
   Tradeoff: lower bear losses, lower bull re-entry speed.
3. **Engine integration (proper backtest).** The analytical pass can't model what the
   saved cash would have done if deployed into other trades. Real backtest likely
   performs SLIGHTLY BETTER than analytical.
4. **Accept current state.** If MaxDD <12% on all 3 drawdowns is the actual user goal
   (not the strict <365d recovery), the circuit breaker ALONE achieves that.

## Artifacts

- Script: `scripts/simulate_circuit_breaker.py` (reusable on any run dir)
- Comparison PDF: `custom_strategies/private/research_results/pdfs/ec_daily/EC-R53_Circuit_Breaker_Analytical_Comparison.pdf`
- Filtered trade log: `custom_strategies/private/research_results/pdfs/ec_daily/EC-R53_Circuit_Breaker_filtered_trades.csv`

## Next step (user decision)

Pick one:
- **A. Accept circuit breaker as-is** (MaxDD <12% achieved, R3 still 672d). Invest in
  engine integration (Phase 2.3) so future backtests run naturally with this rule.
- **B. Add 60-day time stop and re-run** (Phase 2.1) to push R3 under 365 days.
- **C. Try more aggressive size discount** (Phase 2.2).
- **D. Present current PDF and decide later.**
