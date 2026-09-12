# GOOG: 200-EMA bounces, and the search for a strategy that beats buy-and-hold

**Status:** closed, null result. Buy-and-hold is the best strategy found on GOOGL.
**Date:** 2026-09-12
**Scripts:** `scripts/ema200_bounce_study.py`, `scripts/ema200_bounce_regime.py`,
`scripts/goog_oos_validate.py`, `scripts/goog_walkforward.py`
**Audit trail:** `docs/research/goog_preregistration.md`

---

## 1. What was asked

Two questions, in sequence:

1. When GOOG pulls back to its 200-day EMA and bounces, what do you earn buying at
   X% away — and what is the optimal gap distance X?
2. Failing that: is there *any* strategy that pays on GOOG?

Both came out null. The reasoning matters more than the verdict, so it is recorded
here in full.

## 2. The 200-EMA bounce: no information

Prompted by GOOG touching its 200 EMA on 2026-03-30, 2026-07-23 and 2026-09-09 and
bouncing each time. The pattern is real as a description; it is not a signal.

Three independent controls, each stricter than the last:

| control | question it answers | result |
|---|---|---|
| unconditional baseline | vs a random day in the same name | edge surface is flat noise |
| regime-matched baseline | vs a random day with the same EMA slope + VIX | edge ≈ 0 |
| **date-matched cross-section** | vs *other names on the same date* | **+0.00%** |
| depth-matched pullback | vs an equal-depth pullback that missed the EMA | pooled t = 0.01–0.74 |

The date-matched test is decisive: 200-EMA-touch days are simply market-dip days.
Every other stock bought that same day earned the same forward return without going
near its own 200 EMA. Measured over **773 liquid US equities, 18,001 events**.

Three further reasons to disbelieve any apparent edge:

- **Anti-monotonic in gap distance.** The +5% cell beats the 0% and −2% cells
  (Spearman ρ = −1.00 at 21d in several configs). A real support effect must
  strengthen as the gap → 0. This does the reverse, so the EMA level is incidental.
- **Clustering illusion.** 18,001 events fall on only 4,551 dates (49 names touched
  on 2007-02-27 alone). Under an i.i.d. bootstrap 27/30 cells look significant; with
  cluster-robust SEs that collapses to 4/30, all at the 5-day horizon.
- **Worse drawdown.** Event entries took more heat than the matched baseline in
  *every cell of every config*. The 200 EMA is a volatility magnet, not support —
  price is only near it after a selloff.

### Two corrections to assumptions made along the way

- **Survivorship does not cancel.** It was assumed the bias would inflate the event
  arm and the baseline arm equally since both draw from the same names. It does not:
  index membership is a *bridge* condition, so below-trend days in eventual survivors
  are mechanically followed by recovery, flattering the event arm specifically. Era
  split at gap 0%/21d: **+1.34% (1990–2004, z=3.5), +0.21% (2005–2014), −0.34%
  (2015–2026)**. The edge lives where the bias is strongest and inverts in the modern
  era.
- **The "calm VIX" hypothesis was backwards.** Cross-sectional excess by VIX on the
  signal date: +0.07% (VIX<20), +0.32% (VIX 20–30), **+0.61% (VIX≥30)**. Whatever
  pullback effect exists lives in panic, not calm — the calm-market filter removes
  the only real effect.

**On GOOG specifically:** GOOGL is the lone name surviving the depth-matched test
(t = 4.33/3.32/2.83 at 5/10/21d). It cannot count as evidence — the hypothesis was
generated from GOOG's chart, so scoring it on GOOG is scoring the dart after it
landed. NVDA and META run the same test at t = −1.85 and −1.54.

## 3. The strategy search

Protocol fixed **before** searching:

- **IS** 2004-08-19 → 2017-12-31 (3,366 bars) — searched freely
- **OOS** 2018-01-01 → 2026-09-11 (2,185 bars) — held out, thresholds frozen
- Bar to beat: GOOGL buy-and-hold (IS CAGR 25.58%, Sharpe 0.77, MaxDD −65.3%,
  Calmar 0.39). "Pays" means *beats B&H*, not *is profitable* — B&H already makes 21x
  in-sample.
- Gate (`goog_oos_validate.py`), all six required: beat B&H Calmar; beat B&H Sharpe;
  retain ≥60% of B&H CAGR; deflated Sharpe > 0.95 at the full trial count; ≥30 trades;
  **paired** block-bootstrap p5 of (strategy Calmar − B&H Calmar) > 0.
- Gate validated by mutation before use: perfect-foresight oracle ACCEPT 6/6, random
  exposure REJECT 5/6, naive 200-SMA overlay REJECT.

### Results

**456 in-sample variants** (trend, vol/vol-target, momentum, mean-reversion,
drawdown-state, partial de-risk, combos, overnight conditioning). **0 of 353**
risk-overlay variants survived the ex-2008/09 restatement — every full-sample "win"
was dodging one event.

**Independent 18-fold walk-forward** (5y train / 1y test, 702 parameter fits,
parameters refit each fold, 5bp/side):

| family | CAGR | Sharpe | MaxDD | Calmar |
|---|---|---|---|---|
| **buy & hold** | **23.61%** | **0.75** | −44.3% | **0.53** |
| vol target | 20.31% | 0.74 | −40.4% | 0.50 |
| trend × vol target | 11.74% | 0.48 | −27.1% | 0.43 |
| mean reversion | 11.79% | 0.49 | −40.6% | 0.29 |
| trend (SMA) | 11.13% | 0.41 | −52.1% | 0.21 |

Beta-hedged GOOG vs QQQ (beta refit annually): CAGR 1.79%, Sharpe −0.02.

**Six candidates reached the holdout. Zero accepted.**

| candidate | IS | OOS | gates |
|---|---|---|---|
| A overnight-only @1bp | Sharpe 1.28, Calmar 1.20 | CAGR **0.05%**, Sharpe −0.09 | 1/6 |
| A @2bp | Sharpe 1.01, Calmar 0.90 | CAGR −4.86% | 1/6 |
| B overnight × vol-scale | Calmar 1.08 | CAGR −4.51% | 1/6 |
| C overnight, skip weekend | Calmar 1.08 | CAGR 2.48%, Sharpe 0.01 | 1/6 |
| D1 earnings-night only | Calmar 0.72 | CAGR 1.87% | 1/6 |
| **D2 B&H + 2× earnings nights** | Sharpe 0.99, Calmar 0.61 | 25.87% / 0.75 / 0.54 | **5/6** |

### Why everything died: GOOG-specific decay

| effect | in-sample | out-of-sample |
|---|---|---|
| overnight drift | 10.1 bp/day | 2.4 bp/day (break-even 13.3) |
| earnings-night premium | +255 bp, p=0.0075 | +72.5 bp, p=0.51 |

Over the *same* window the overnight anomaly held or grew elsewhere: MSFT +3.4,
NVDA +4.3, AMZN +0.2, SPY +1.1, QQQ +0.5 bp/day. Anomalies are not dying generally —
GOOG stopped expressing them. The OOS collapse is broad-based, not tail-driven:
trimming the top and bottom 1% of nights moves the mean only +2.87 → +2.46 bp, and
the Welch t of OOS nights vs IS 2009–17 nights is −2.09.

### The near-miss, and why the gate design mattered

D2 passed five of six gates — it beat B&H on CAGR, Sharpe *and* Calmar and cleared a
deflated Sharpe of 0.954. It failed only the paired bootstrap, where the **median**
Calmar difference vs B&H is **−0.02** (p5/p95 = −0.25/+0.23). The +2.4pp CAGR is a
coin flip across 31 nights.

On the obvious test — "does it beat buy-and-hold risk-adjusted?" — D2 wins. Freezing
the gate before looking at any candidate is the only reason it was not promoted.

## 4. Reusable finding: the vendor `Open` is not the auction print

**This affects any daily-bar research in this repo that uses opening prices.**

Exchange auction crosses print at penny increments; off-exchange midpoint prints do
not. Over 2021-09 → 2026-06:

- sub-penny **closes**: 0.1–0.3% of days — vendors *are* recording the closing cross
- sub-penny **opens**: **GOOGL 12.2%** of days, rising 6% (2021) → 20% (2025) →
  **28% (2026)**. GOOG 14.9%, AAPL 15.8%, MSFT 15.8%, AMZN 12.6%, NVDA 10.2%.
  SPY/QQQ only ~1.9%.

On those days the recorded `Open` is provably an off-exchange print that beat the
NASDAQ cross to the tape — not a price a MOO order can receive. The bias has a
direction: GOOGL's overnight return is **+7.86 bp on sub-penny-open days vs +1.45 bp
on penny-open days** (n=146 vs 1,049).

Consequence: **"buy at close, sell at open" on daily bars is not an executable
MOC/MOO strategy.** Any overnight-drift result measured this way is overstated by an
unknown amount before costs or decay are considered.

Norgate, Polygon daily aggregates and Polygon's open/close endpoint agree on the Open
to 0.00 bp, and Polygon's daily open equals its own 9:30 one-minute bar open on 24/24
sampled days. **Cross-vendor agreement was not evidence of correctness** — they agree
because they share a convention (first regular-session trade), not because that
convention is the auction price.

## 5. Practical conclusion

GOOG is a high-drift, high-volatility compounder. The volatility producing the −65%
(IS) / −44% (OOS) drawdown is the same volatility producing the compounding, and
every overlay tested traded return for drawdown at roughly 1:1 — visible from the
first test (200-SMA overlay: Calmar 0.38 vs B&H 0.39) and confirmed across all 456
variants.

**The drawdown is a position-sizing problem, not a timing problem.** It is solved at
the portfolio allocation layer by owning less of it, not by a rule on its own price
series.

## 6. Reproduction

```bash
# 200-EMA bounce study (unconditioned), 7 megacaps
rtk ./.venv/bin/python scripts/ema200_bounce_study.py --out results.csv

# regime-conditioned version, LOW-based touch, slope + VIX filters
rtk ./.venv/bin/python scripts/ema200_bounce_regime.py \
    --touch low --slope-min 0.0 --vix-max 20 --out regime.csv

# walk-forward family comparison on GOOGL
rtk ./.venv/bin/python scripts/goog_walkforward.py

# the frozen OOS gate (self-test: B&H cannot beat itself)
rtk ./.venv/bin/python scripts/goog_oos_validate.py
```

Data: Norgate parquet submodule (`parquet_data/`) spliced with a rescaled Yahoo tail,
since the submodule ends 2026-06-16. Polygon is unusable for the deep history here —
equities are capped to a ~5yr rolling window on the current plan.

## 7. Limitations

- Single-name study. Conclusions about GOOG do not transfer to other symbols; the
  overnight anomaly demonstrably remains alive in MSFT/NVDA/AMZN/SPY/QQQ.
- The holdout was looked at 8 times across 6 candidates. Later candidates carry
  correspondingly less credibility; nothing further should be tested on this split.
- Options overlays (collar, covered-call VRP harvesting) were never tested — no
  options data in this repo. Genuinely structural and left open.
- The cross-sectional overnight strategy on a basket is untested and is a different
  question from "a strategy on GOOG". Note the sub-penny contamination above applies
  to every NASDAQ mega-cap's daily bars equally.
