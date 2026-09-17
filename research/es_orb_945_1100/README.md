# ES Opening Range Breakout, 09:45–11:00 ET

**Question.** Take the opening range of the NY cash session — the first 15 or 30 minutes from
09:30 ET — and trade breakouts of it during the 09:45–11:00 window on ES (E-mini S&P 500).
Does it work?

**Answer. No.** Across 516 ES sessions and, as a regime check, 4,139 sessions of Nasdaq index
futures spanning 16 years, the rule is indistinguishable from a coin flip that pays
commission. On ES it is *worse than doing nothing clever*: simply buying at 09:45 and holding
beat every one of the twelve breakout configurations tested, by **$13k–$40k per contract**
over two years. The one place a positive number appears — Nasdaq futures held to the close —
is regime-specific (average R negative in nine of the eleven years before 2021, positive in
all five of 2021–2025, negative again in 2026 year-to-date) and survives no useful
significance bar. It is also a sizing artifact: risk-normalised, the typical year lost money.

---

## 1. What was actually run

| | |
|---|---|
| Opening range | first **15** or **30** minutes from 09:30 ET |
| Entry | stop order at the OR extreme, armed only between OR-end and **11:00 ET** |
| Stop | opposite OR extreme (or one OR width, where a matched comparison needed it) |
| Exit | R-multiple target (none / 1R / 2R), else flat at **11:00** or at the **close** |
| Position | one trade per session, both directions, 1 contract |
| Costs | 1 tick slippage per fill + $2.50 round-trip commission (ES); $1.04 (MNQ) |

"09:45–11:00" is ambiguous about whether the *window* is the trade or just the entry gate, so
both readings were tested: flat at 11:00, and hold to the close. That doubling is why there
are twelve configurations rather than six.

## 2. Data

**ES — Polygon futures API, 1-minute.** Polygon *does* serve futures on this plan, contrary to
what this repo's notes said: `/futures/v1/aggs/{ticker}?resolution=1min`. Aggregate history
begins **2024-09-17**, giving **516 sessions / 707,967 bars** to 2026-09-17. Contract tickers
are decade-ambiguous (`ESM4` may resolve to Jun-2024 or Jun-2034), so the quarterly chain is
enumerated explicitly and each contract's true span read from the data. Front-month is
selected by **previous** session's volume, so the roll decision uses no same-day information.

Because the strategy is flat by the close every day, **no back-adjustment is needed** — each
session is self-contained and quarterly roll gaps never touch a position.

**MNQ/NQ — Databento 1-minute RTH, 2010-06 → 2026-07, 4,139 sessions.** Two years of ES cannot
tell you whether a pattern is persistent. This leg can. It is the wrong index but the right
asset class, and it is the only 16-year intraday index-futures series on this machine.

### The ES data was validated against an independent source

ES bars were cross-checked against Polygon's *equity* 1-minute SPY series — a different
product with a different entitlement — over the 502 overlapping sessions:

| check | result |
|---|---|
| corr of OR high, as a fraction of the 09:30 open | **0.9991** |
| corr of OR low | **0.9990** |
| corr of OR width | **0.9992** |
| agreement on which side of the OR broke first | **98.6%** (7 disagreements / 501) |
| OR width on roll days vs other days | 0.00271 vs 0.00297 (ratio 0.914 — no distortion) |

The bars are correctly aligned to the cash session and the stitch is clean.

## 3. Execution honesty

Every fill in the engine is one a real order could have received. Entry is a stop: a bar that
gaps through the trigger fills at the **reopen**, never the trigger. The stop exit is the
same. The target is a limit, so it fills at its price or better. When one bar's range spans
both stop and target, the **stop** is taken, because bar data cannot resolve the intrabar
path. The entry bar is itself checked for a stop hit, so there is no window where a position
is armed but unprotected.

Two bugs were found by writing those tests *before* trusting any P&L:

1. **Protection-free window.** The original loop entered on bar *i* but only began managing
   the position on bar *i+1*, leaving the rest of the entry bar unprotected — precisely the
   failure mode that killed Sleeve A.
2. **Same-bar re-entry.** With re-entry enabled, the engine could exit and re-enter on the
   same bar, a sequence whose intrabar path is unobservable.

**Artifact size: $0 on ES, $36 (0.4%) on MNQ.** A byte-identical result under honest fills is
normally a warning sign, so the mechanism was measured rather than assumed. Inside RTH, ES
1-minute bars are contiguous: **99.6% of the 197,105 interior bar boundaries move by ≤1 tick**,
and only 10 boundaries in two years exceed 4 ticks. A resting stop has nothing to be jumped
through. The strategy is structurally immune to this artifact — it never holds overnight — and
the mutation suite confirms the gap branch does fire when gaps are present.

## 4. Results

### ES, full sample (516 sessions, 1 contract, net of costs)

| config | trades | win rate | avg R | total $ | PF | max DD $ | Sharpe | t(R) |
|---|---|---|---|---|---|---|---|---|
| OR15 · flat 11:00 · no target | 514 | 45.9% | +0.001 | −17,698 | 0.92 | −48,325 | −0.51 | 0.02 |
| OR15 · flat 11:00 · 1R | 514 | 49.8% | −0.027 | −25,910 | 0.88 | −53,155 | −0.86 | −0.68 |
| OR15 · flat 11:00 · 2R | 514 | 45.9% | +0.013 | −13,035 | 0.94 | −44,825 | −0.38 | 0.29 |
| OR15 · to close · no target | 514 | 37.2% | +0.007 | −16,810 | 0.94 | −57,612 | −0.35 | 0.11 |
| OR15 · to close · 1R | 514 | 51.0% | −0.011 | −15,760 | 0.94 | −41,768 | −0.46 | −0.26 |
| OR15 · to close · 2R | 514 | 41.1% | +0.058 | **+7,265** | 1.03 | −35,388 | 0.16 | 1.00 |
| OR30 · flat 11:00 · no target | 491 | 50.3% | +0.015 | −4,590 | 0.97 | −25,078 | −0.16 | 0.44 |
| OR30 · flat 11:00 · 1R | 491 | 51.1% | −0.000 | −5,202 | 0.97 | −28,265 | −0.18 | −0.01 |
| OR30 · flat 11:00 · 2R | 491 | 50.3% | +0.011 | −4,815 | 0.97 | −25,165 | −0.16 | 0.33 |
| OR30 · to close · no target | 491 | 43.2% | +0.024 | −11,615 | 0.96 | −42,022 | −0.23 | 0.42 |
| OR30 · to close · 1R | 491 | 50.7% | −0.019 | −17,390 | 0.94 | −37,495 | −0.41 | −0.45 |
| OR30 · to close · 2R | 491 | 43.2% | −0.009 | −18,028 | 0.94 | −44,810 | −0.38 | −0.18 |

Eleven of twelve lose money. The exception (+$7,265 over two years) carries a −$35,388
drawdown, a 1.03 profit factor and a t-statistic of 1.00 on its mean R. That is noise.

**Every configuration flipped negative out of sample.** Splitting at the pre-registered
2026-01-01 boundary, all six of the both-direction configs had positive average R in-sample
(2024-09 → 2025-12) and negative average R out-of-sample (2026), with the OOS loss running
−$9,794 to −$21,129 per contract.

### The control that settles it

Enter every session at the open of the first bar after the opening range and exit when the ORB
variant does. No breakout test, no stop:

| | OR | exit | ORB total $ | always-long total $ |
|---|---|---|---|---|
| ES | 15 | 11:00 | −17,698 | **+22,735** |
| ES | 15 | close | −16,810 | **+16,223** |
| ES | 30 | 11:00 | −4,590 | **+8,798** |
| ES | 30 | close | −11,615 | **+2,285** |

On ES the breakout filter does not merely fail to add value — it **destroys $13,388 to
$40,433 per contract** relative to unconditional exposure over the same hours. Selecting sessions by "the
opening range broke" is worse than not selecting at all.

### MNQ, 16 years — the regime story

The only positive numbers in the study are MNQ held to the close (+$9,945 to +$15,812 per
contract over 16 years). Before believing them, read the years:

| period | avg R (OR15 · to close) | across all 12 configs |
|---|---|---|
| 2010–2020 (in-sample, 2,666 trades) | **-0.061** | negative in **12 of 12**, mean -0.059 |
| 2021–2026 (out-of-sample, 1,418 trades) | **+0.095** | positive in **12 of 12**, mean +0.049 |
| 2026 YTD (139 trades) | **-0.082** | flipped back |

Year by year, average R is negative in 2010, 2011, 2012, 2013, 2014, 2015, 2017, 2019, 2020
and 2026 — **10 of 17 years**. This is not overfitting (out-of-sample is *better*
than in-sample, in every single config); it is regime dependence, and the most recent partial year has already turned over.
$15,812 over sixteen years on one MNQ contract is roughly $1,000 a year against a −$9,548
drawdown — and even that overstates it, for the sizing reason two sections below.

Separately worth noting: unconditional long exposure from 09:45 to the close on MNQ made
**+$325 over sixteen years**. The Nasdaq's entire 2010–2026 advance happened outside those
hours. There is very little directional drift in that window to harvest.

### Is it a pattern that costs eat, or no pattern at all?

This repo's earlier equity-ORB study found a real *gross* edge that died entirely in
slippage. That is a different conclusion from "there is nothing here", so the same rules were
re-run at zero cost. Gross means per trade, before any slippage or commission:

| | config | gross pts/trade | break-even slippage |
|---|---|---|---|
| ES | OR15 · flat 11:00 | **−0.139** | none — no gross edge to pay with |
| ES | OR15 · to close | **−0.104** | none — no gross edge to pay with |
| ES | OR30 · flat 11:00 | +0.363 | 0.73 ticks/fill |
| ES | OR30 · to close | +0.077 | 0.15 ticks/fill |
| MNQ | OR15 · flat 11:00 | +0.671 | 1.34 ticks/fill |
| MNQ | OR15 · to close | +2.238 | 4.48 ticks/fill |
| MNQ | OR30 · flat 11:00 | +0.728 | 1.46 ticks/fill |
| MNQ | OR30 · to close | +3.087 | 6.17 ticks/fill |

**On ES, half the configurations have no gross edge whatsoever** — they lose before a single
cent of cost. The other two break even at 0.15 and 0.73 ticks per fill, and you pay about one.
So ES is not "a good pattern ruined by costs"; it is either no pattern, or a pattern smaller
than the minimum price increment.

MNQ's gross edge does clear its costs. Which raises the question the next section settles.

### The MNQ dollar total is a sizing artifact

The two "hold to the close" MNQ configs show +$9,945 and +$15,812 per contract over sixteen
years, alongside average R-multiples of −0.004 and +0.001 with t-statistics near zero. Both
sets of numbers are right, and the reconciliation is the finding.

Trading a fixed one contract on a series whose index went from ~4,900 to ~26,900 means the
risk per trade grew with it — **from $20 per trade in 2010 to $291 in 2026, a 14.7×
increase**. Summing raw dollars therefore weights a 2025 trade about fifteen times as heavily
as a 2011 trade. The R-multiple normalises by the risk actually taken, which is the only unit
comparable across that span.

| | OR15 · to close | OR30 · to close |
|---|---|---|
| dollar total, fixed 1 contract | **+9,945** | **+15,812** |
| ≤ 2020 subtotal | −8,174 | −7,548 |
| 2021–2025 subtotal | +22,306 | +25,664 |
| 2026 YTD | −4,187 | −2,304 |
| **equal-weighted mean of yearly average R** | **−0.0122** | **−0.0036** |
| years with negative average R | **10 of 17** | **9 of 17** |

Per unit of risk actually taken, the typical year lost money in both. The positive headline is
fixed-contract sizing pointed at a 15×-inflated risk unit, with the gains concentrated in one
favourable regime that has already turned over.

### Does the breakout direction carry information?

The same rules were run twice on the same bars at the same trigger prices with matched risk of
one OR width — once following the break, once fading it — both fully simulated so stops and
time exits resolve honestly for each. The paired per-session difference is the read on whether
the *sign* means anything.

| | config | follow avg R | fade avg R | paired diff/session | paired t |
|---|---|---|---|---|---|
| ES | OR15 · flat 11:00 | −0.010 (t −0.21) | −0.048 (t −1.00) | −$41.05 | −0.46 |
| ES | OR15 · to close | +0.004 (t +0.06) | −0.061 (t −0.81) | −$16.03 | −0.14 |
| ES | OR30 · flat 11:00 | +0.018 (t +0.51) | −0.061 (t −1.87) | +$31.11 | +0.37 |
| ES | OR30 · to close | +0.031 (t +0.54) | −0.075 (t −1.33) | +$37.81 | +0.28 |
| MNQ | OR15 · flat 11:00 | −0.027 (t −1.74) | −0.065 (t −4.32) | +$1.42 | +0.43 |
| MNQ | OR15 · to close | −0.004 (t −0.16) | −0.044 (t −1.91) | +$2.11 | +0.44 |
| MNQ | OR30 · flat 11:00 | −0.021 (t −1.94) | −0.059 (t −5.54) | +$3.17 | +1.04 |

Two things fall out, and the second is the more useful one:

1. **Fading is reliably worse than following** — fade average R is negative in all seven
   comparisons, significantly so on MNQ (t up to −5.54). There is a real, weak momentum tilt
   in the breakout direction.
2. **Following is itself indistinguishable from zero** (|t| ≤ 0.54 on every ES config), and
   the paired follow-minus-fade difference never reaches significance (|t| ≤ 1.04).

So the direction is not the problem. **Both directions lose.** The losing thing is the
structure — a breakout entry paying the spread to get in, with a stop an opening-range width
away, during these hours. Choosing the right side moves you from clearly bad to approximately
zero, and zero is where costs live.

### Is there a subset of sessions where it works?

The published ORB results condition on the day being tradeable at all, so 18 session-level
gates — opening-range width relative to its trailing median, opening-range volume, gap
direction and size, position against the 20-day average, OR-to-ATR ratio, day of week — were
swept across 4 configs and both instruments. All gates use only pre-entry information
(prior-session closes, trailing statistics shifted one session, and the opening range itself).

**16 of 152 gate×config×instrument cells were positive in both in-sample and out-of-sample
with at least 30 OOS trades.** That count means nothing on its own, so it was calibrated:
each gate was replaced by a random set of sessions *of the same size*, drawn from the same
sessions, and the survivor rule re-applied 400 times.

| | |
|---|---|
| observed survivors | **16** |
| randomised gates, mean | **16.6** |
| randomised gates, median | 16 |
| randomised gates, 5th–95th percentile | 10–23 |
| **P(random ≥ observed)** | **0.585** |

The observed survivor count is precisely what *uninformative* gates produce. There is no
subset here. For completeness, the strongest-looking survivors are also not independent
discoveries: on MNQ they reduce to "gap up" plus "hold to the close", which is long exposure
in a bull regime, and the day-of-week gates are the signature of a data-mined subset rather
than a mechanism.

## 5. What this does and does not establish

**Established, for ES in the 09:45–11:00 window over 2024-09 → 2026-09:**

- Unconditional long exposure over the same hours beat every breakout configuration tested.
- Half the configurations have no gross edge at zero cost; the rest break even below one tick.
- Every configuration flipped negative out of sample.
- Fading the break is worse than following it, but following it is still zero.

**Not established, and worth being explicit about:**

1. **Two years is two years.** 516 ES sessions cannot distinguish a small edge from zero, and
   this window contains one broad regime. That is exactly why the 16-year MNQ leg is here —
   but MNQ is the Nasdaq, not the S&P, and the two indices' intraday character differs.
2. **Polygon's futures aggregates start 2024-09-17.** Nothing earlier is reachable on this
   plan, so an ES-native test across 2010–2024 is not possible here. Databento would fix this
   and there is no Databento key on this machine.
3. **The conditional sweep is exploratory.** 144 comparisons were run; the survivor count is
   calibrated against randomised gates rather than presented as a discovery, and the
   surviving gates reduce to long exposure in a bull regime plus day-of-week noise.
4. **Costs are modelled, not measured.** One tick of slippage per fill plus $2.50 round trip
   is a reasonable retail assumption for the most liquid futures contract in the world, and
   the cost ladder shows what 0 / 0.5 / 1 / 2 ticks each do. Real fills on stop orders during
   a fast 09:45 breakout could be worse, which moves the answer further negative, not less.
5. **Only the plain rule was tested.** No volatility-scaled stops, no trailing, no position
   sizing, no relative-volume day selection of the kind the Zarattini papers use. Those are
   the obvious next things to try, and this repo's earlier equity-ORB study already found
   that the day-selection version has a real gross edge that dies in slippage on the names it
   picks.

**What would change the answer:** an ES-native intraday series long enough to cover several
regimes (Databento GLBX-MDP3), and a day-selection screen applied before the breakout rather
than trading every session. As specified — every session, plain breakout, this window — the
rule does not work, and on ES it is worse than not filtering at all.

## 6. Reproducing

```bash
rtk python scripts/es_orb_research.py      # both legs, grid, IS/OOS, control, placebo
rtk python scripts/es_orb_costs.py         # cost ladder / gross-vs-net diagnostic
rtk python scripts/es_orb_conditional.py   # session-filter sweep (exploratory)
rtk python scripts/validate_es_vs_spy.py   # ES vs SPY cross-source validation
rtk python scripts/check_minute_gaps.py    # why the fill artifact is $0
rtk pytest tests/test_orb_engine.py tests/test_orb_engine_mutations.py

# every number quoted in this README, re-checked against results/
rtk python research/es_orb_945_1100/verify_readme_numbers.py
```

`verify_readme_numbers.py` re-derives all 126 figures in the tables above from
`results/*.csv` and fails on any disagreement, so the prose cannot drift away from the data.
It has itself been mutation-tested: corrupting a trade count, a control total, a gross
points-per-trade figure or the equal-weighted mean R each makes it fail.

`es_futures_data.py` caches each contract's 1-minute bars to `es_minute_cache/` on first run
(~700k bars, a few minutes). Everything downstream reads the cache.

MNQ requires the Databento parquet at
`jb-private-research/futures_intraday_data/mnq/nq_mnq_RTH_clean_stitched.parquet`; the ES leg
runs without it.
