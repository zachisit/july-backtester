# EC Research Round 44 — Power Dip + VIX Volatility Gate (FAILED)

**Date:** 2026-04-23
**Run ID:** ec-r44-power-dip-vix_2026-04-23_17-46-57
**Symbols:** S&P 500 Current & Past (Norgate, ~1273 valid symbols)
**Period:** 2004-01-02 → 2026-04-23
**WFA:** 80/20 split (IS: 2004-2021-11-05, OOS: 2021-11-05 → 2026-04-23), 3 rolling folds
**Timeframe:** Daily bars
**Allocation:** 2.5% per position

## Context

EC-R43 (52-week high filter) passed WFA and distribution but still suffered -$38k (2008) and
-$69k (2022) losses. EC-R44 adds a VIX volatility gate: only enter pullbacks when VIX < 25.
Hypothesis: VIX spikes early in every real crash → gate prevents bear-market entries while
preserving bull-market entries.

**EC-R44 entry conditions:**
- Close < SMA20 * 0.97 (3% pullback — same as EC-R43)
- Close > rolling_max_252 * 0.85 (within 15% of 52wk high — same as EC-R43)
- VIX close < 25 (no entries in elevated volatility regimes)

**EC-R44b:** Same but with 5%/3% pullback/exit thresholds (wider variant).

## Results

| Strategy | P&L | vs SPY | MaxDD | Calmar | RS(min) | OOS P&L | WFA | RollWFA | MC | Trades |
|---|---|---|---|---|---|---|---|---|---|---|
| EC-R44 (VIXlt25) | 286% | -573pp | 23.37% | 0.27 | **-111.85** | **-2.01%** | **Likely Overfitted** | 3/3 | 5 | 11,249 |
| EC-R44b (5%/3% VIX) | 234% | -625pp | 30.39% | 0.18 | **-91.90** | **+8.17%** | **Likely Overfitted** | 3/3 | 5 | 7,954 |

## Annual Equity Progression — EC-R44 (VIXlt25)

| Year | Annual P&L | Cumulative | vs EC-R43 | Notes |
|---|---|---|---|---|
| 2005-2007 | Same as EC-R43 | $132k | Same | VIX < 25 in bull years |
| **2008** | **-$19,456** | **$112k** | **Better** | VIX gate partially helps |
| 2009 | +$7,844 | $121k | **WORSE** | VIX stayed elevated; missed recovery |
| 2010 | +$27,538 | $148k | Better | — |
| 2011 | **-$2,495** | $146k | **WORSE** | EC-R43 was +$14k in 2011 |
| 2012 | +$17,727 | $164k | Similar | — |
| 2013 | +$59,292 | $222k | Similar | — |
| 2014-2017 | Mostly similar | — | — | — |
| 2018 | -$44,460 | $260k | **MUCH WORSE** | EC-R43 was -$31k |
| 2019 | +$57,916 | $318k | Similar | — |
| **2020** | **-$9,767** | **$308k** | **MUCH WORSE** | EC-R43 was +$26k (COVID V-recovery blocked) |
| 2021 | +$83,430 | $391k | Similar | — |
| 2022 | -$72,311 | $319k | Worse | — |
| 2023-2026 | Weaker gains | $387k | Weaker | VIX elevated in some OOS quarters |

## Key Findings

### EC-R44: FAILED on both critical metrics

**1. WFA "Likely Overfitted"** — The VIX<25 threshold is an IS-period fit. During 2004-2021,
VIX averaged ~17 (generally below 25 except crisis spikes). The gate "worked" in-sample by
blocking 2008/2009 entries. In OOS 2021-2026, VIX averaged higher (~22-28) — the gate blocks
too many valid entries, causing OOS P&L = -2.01%.

**2. RS(min) catastrophically worsened** — -111.85 vs EC-R43's -4.49. The VIX gate creates
a pattern where VIX spikes AFTER stocks have already fallen — so the gate blocks the recovery
entries (when VIX is still elevated but stocks are recovering), causing the strategy to miss
gains during volatile recovery periods. The 126-day rolling Sharpe during these gaps is deeply
negative.

**3. VIX gate INVERTS the alpha** — The strategy's best opportunities are exactly when VIX is
elevated (after a correction, stocks near 52wk highs start recovering). VIX<25 gate systematically
blocks these opportunities:
- 2020 COVID: VIX spiked to 80 → strategy blocked → missed +$26k EC-R43 made
- 2018 Q4: VIX elevated → strategy blocked → worse losses and missed recovery
- 2019 early: VIX still elevated post-2018 → missed initial recovery gains

**4. VIX gate does NOT prevent bear market losses** — 2022 losses (-$72k) were WORSE with the
gate than without (-$69k in EC-R43). The VIX<25 threshold in 2022 stayed below 25 for most
H1 2022, so the strategy entered freely. When VIX did spike, the gate closed AFTER losses.

### Critical lesson: VIX and 52-week high filter interact ADVERSELY

The 52-week high filter already provides bear market protection by blocking entries in stocks
that have declined significantly. Adding a VIX gate creates a second overlapping filter that
eliminates exactly the alpha opportunities that the 52wk filter was preserving (recovery entries
in strong stocks after volatility spikes).

The combination is: fewer entries during recoveries + no meaningful reduction in bear market entries.

## Anti-Pattern Confirmed

**VIX gate on top of 52-week high filter = double-gating that destroys alpha**

Do not retry VIX gating on EC-R43/EC-R44 architecture. The 52wk filter provides structural
bear market avoidance. Any volatility gate must use a DIFFERENT mechanism.

## Verdict

**EC-R44: ELIMINATED.** WFA Overfitted + RS(min) catastrophically worsened.

The EC-R43 base architecture (without VIX gate) is still the best candidate — OOS +90%, RS(min) -4.49,
WFA Pass. The bear market loss problem must be addressed via a different approach.

## EC-R45 Direction

**Hypothesis:** The remaining 2008/2022 losses occur because the market's SHORT-TERM TREND is
negative while the 52wk proximity filter still passes (early bear markets). A fast slope check
on the market index would catch this.

**EC-R45: SPY 20-day SMA Slope Gate**

Entry requires all of:
1. Close < SMA20 * 0.97 (3% pullback — same as EC-R43)
2. Close > rolling_max_252 * 0.85 (within 15% of 52wk high)
3. SPY SMA20 today ≥ SPY SMA20 15 days ago (market 20-day trend is flat or rising)

**Why this is different from SPY SMA200 gate (which caused flat periods):**
- SMA200 gate: binary on/off for months based on long-term average crossing
- SMA20 slope gate: responds in days to weeks; slope turns positive quickly in V-recoveries
- 2020 COVID: SPY SMA20 dipped briefly then recovered → gate opens within 3-4 weeks
- 2008: SPY SMA20 slope stayed negative for months → extended protection
- 2022: SPY SMA20 slope negative most of H1 2022 → protects during the steady bear phase

**Dependency:** requires `spy` dependency in @register_strategy decorator.
**Data needed:** SPY SMA20 at each entry date → shift(15) to get slope check.

Also test stock-level SMA20 slope as a simpler variant (no extra data dependency):
- Stock's own SMA20 today > SMA20 10 days ago
- Same logic but stock-specific — catches sector-level declines
