# Research: Consecutive-Day Streak Filter — Mo's 7/9 Heuristic

**Status:** research (not a strategy candidate — a signal screen)
**Author:** Suriya
**Universe:** Norgate parquet export, 30,329 stocks, 1990-01-02 → 2026-04-22

## What this tests

Mo's overlay, from the 7/13 call:

- **Claim 1 (reversion):** after ~7 consecutive down days, reversal odds improve.
- **Claim 2 (continuation):** once a run reaches ~9 days one direction, it's a
  trend more likely to continue than revert.

On a single index, 7 down days in a row happens ~25x in 20 years — untestable.
Pooled cross-sectionally over the full Norgate universe the same event has
100k+ occurrences, which is what makes the answer meaningful.

## Method

- One `{SYMBOL}.parquet` per name, `Close` column. Direction = sign of daily
  change; a run of *k* is *k* consecutive same-direction days.
- For every day ending a run of exactly *k*, record forward returns at
  1/3/5/10/20 days, and compare to the **unconditional baseline** (same-horizon
  return over all days). The number that matters is *excess over baseline*, not
  the raw sign — stocks drift up anyway.
- **Cleaning (identical for baseline and buckets):** dropped `#/$/&/@` symbols
  (indices, breadth lines, futures — not stocks), $1 entry-price floor, forward
  returns winsorized to [-95%, +300%], >50% single-day moves treated as breaks.
- **Survivorship:** verified free. 57% of sampled names have their last bar
  before 2025 (17% before 2000) — delisted names are in the data, so this is not
  a survivors-only artifact.

Script: `research/streak_filter_study.py`. Full table: `streak_study_results.csv`.
Chart: `streak_study_forward_by_length.png`.

## Result

**Claim 1 holds. Claim 2 does not.**

Forward 5-day excess return vs baseline, by prior streak length:

| k (streak) | after DOWN (bps) | after UP (bps) |
|-----------:|-----------------:|---------------:|
| 5 | +42 | −27 |
| 6 | +41 | −34 |
| **7** | **+49** | **−31** |
| 8 | +56 | −31 |
| **9** | **+54** | **−29** |
| 10 | +66 | −36 |
| 11 | +78 | −27 |
| ≥12 | +71 | −48 |

- **After down streaks — reversion, and it strengthens with length.** 7-day is
  +49 bps / 5d (win 52.9%); it keeps *rising* to +78 by k=11. Mo's claim-1 is
  confirmed and robust. But claim-2 is contradicted: long down streaks don't flip
  to continuation, they mean-revert *harder*.
- **After up streaks — mild continuation, never reversal.** Excess is negative at
  every length (underperforms baseline) and drifts more negative with length.
  Long up-runs keep quietly underperforming; they don't revert.

So the heuristic is directionally right on the buy side (down-streak reversion)
and wrong on the flip (no continuation regime kicks in at 9). The behavior is
asymmetric — the down side reverts, the up side weakly persists.

## Honest flags

- **Edge is in the size of the bounce, not the hit rate.** Win rates sit at
  ~50–53% while mean excess is clearly positive → a smaller number of larger
  up-moves, not a high-frequency edge. Fragile.
- **No costs.** This is close-to-close, zero spread. Names that just fell 7+ days
  straight are exactly the hard-to-borrow, wide-spread, low-price names where
  20–50 bps can vanish into the bid-ask. **Whether the edge survives a realistic
  spread is the open question** — and the first thing worth testing next.
- **t-stats overstate significance** (overlapping forward windows → autocorrelated
  observations). Read the bps and win rate, not the t.
- In-sample by construction. This screens the idea; a forward test decides.

## Suggested next step

Wire the 7-day-down-streak signal into the backtester as a long entry with
realistic costs (spread + borrow proxy) and see if +49 bps survives. If it does,
it's a candidate; if it doesn't, it's a clean "no retail edge" result — either
way, worth knowing.
