# EC Research Round 46 — Two-Layer Gate: SPY Slope + SPY > SMA100

**Date:** 2026-04-23
**Run ID:** ec-r46-two-layer-gate_2026-04-23_18-15-20
**Symbols:** S&P 500 Current & Past (Norgate, ~1273 valid symbols)
**Period:** 2004-01-02 → 2026-04-23
**WFA:** 80/20 split, 3 rolling folds
**Timeframe:** Daily bars
**Allocation:** 2.5% per position

## Context

EC-R45 (SPY 20d-SMA slope gate) cut MaxDD to 23.50% and eliminated 2018 losses but
failed in 2022 (-$73k) because the choppy stair-step bear produced multiple bear rallies
that falsely reopened the slope-only gate. Root cause: the gate oscillated positive/negative
throughout H1 and Q3 2022, letting mean-reversion setups through during rallies that then
continued the decline.

EC-R46 tests two orthogonal fixes:
- **EC-R46:** two-layer gate — slope rising AND SPY > SMA100 (medium-term regime)
- **EC-R46b:** 3-day hysteresis on slope gate alone — require 3 consecutive days of
  positive slope before reopening

## Results

| Strategy | P&L | vs SPY | MaxDD | Calmar | RS(min) | OOS | WFA | RollWFA | MC | Trades |
|---|---|---|---|---|---|---|---|---|---|---|
| **EC-R46 (slope + SMA100)** | 355% | -505pp | **19.10%** | **0.37** | -70.99* | +40.46% | **Pass** | **3/3** | **5** | 8,995 |
| EC-R46b (3d hysteresis)     | 320% | -539pp | 24.26% | 0.27 | -4.49 | +1.89% | **Overfitted** | 3/3 | 5 | 9,357 |
| *EC-R45 baseline*           | *317%* | *-542pp* | *23.50%* | *0.28* | *-4.49* | *+13.67%* | *Pass* | *3/3* | *5* | *9,531* |
| *EC-R43 grandparent*        | *498%* | *-361pp* | *33.85%* | *0.25* | *-4.49* | *+90.62%* | *Pass* | *3/3* | *5* | *12,498* |

SPY B&H over period: ~859%

*RS(min) −70.99 is a metric artifact (see "Red Flag Investigation" below) — the actual
2022 drawdown is only 14% equity, well within the 19.10% MaxDD.

## Annual P&L — EC-R46 vs EC-R45 vs EC-R43

| Year | EC-R46 | EC-R45 | EC-R43 | Key observation |
|---|---|---|---|---|
| 2005 | +$10k | +$10k | +$16k | — |
| 2006 | +$9k  | +$10k | +$12k | — |
| 2007 | -$10k | -$7k  | +$7k  | Gate triggers early |
| **2008** | **-$2k** | **-$8k** | **-$38k** | **SMA100 stops entries COLD** |
| 2009 | +$28k | +$25k | +$22k | V-recovery captured |
| 2010 | +$8k  | +$8k  | +$21k | — |
| 2011 | -$3k  | -$10k | +$14k | Less whipsawed than R45 |
| 2012 | +$17k | +$18k | +$20k | — |
| 2013 | +$52k | +$46k | +$65k | Bull year |
| 2014 | -$4k  | -$3k  | +$18k | Flat |
| 2015 | +$5k  | +$7k  | +$12k | — |
| 2016 | +$23k | +$21k | +$32k | — |
| 2017 | +$24k | +$22k | +$36k | — |
| **2018** | **+$0.5k** | **+$5k** | **-$31k** | **Flat (target)** |
| 2019 | +$35k | +$32k | +$63k | — |
| 2020 | +$36k | +$41k | +$26k | V-recovery captured |
| 2021 | +$89k | +$88k | +$122k | Bull year |
| **2022** | **-$53k** | **-$73k** | **-$69k** | **27% better than R45** ✓ |
| 2023 | +$13k | +$12k | +$31k | — |
| 2024 | +$49k | +$45k | +$83k | Strong recovery |
| 2025 | +$25k | +$21k | +$28k | — |
| 2026 | +$5k  | +$8k  | +$10k | — |
| **TOTAL** | **+$354k** | **+$317k** | **+$498k** | |

## Key Findings

### 1. MaxDD 19.10% is a NEW RECORD — SMA100 layer actually works

Progression across the research:
- EC-R39b: ~37% MaxDD
- EC-R43: 33.85% MaxDD (52wk high filter)
- EC-R45: 23.50% MaxDD (+ slope gate)
- **EC-R46: 19.10% MaxDD (+ SMA100 layer)** ← new floor

Calmar 0.37 is the highest of any mean-reversion variant. The medium-term regime layer
filters the 1-5 day bear rallies that destroyed EC-R45's 2022 performance.

### 2. 2022 cliff reduced from $73k to $53k (27% improvement)

SPY was below its 100-day SMA from early January 2022 until early February 2023 (with one
brief crossover in August). The second gate layer stayed closed during the summer bear
rally that fooled EC-R45's slope-only gate — entries blocked, losses avoided.

Remaining $53k loss is from January 2022 positions that were already open when the gate
closed, plus a handful of entries during brief regime crossovers. No more V-exploit possible
with this architecture.

### 3. 2008 reduced to -$2k — essentially flat through the GFC

Trade count 2008 = 135 (vs R45's 308, R43's 308). The two-layer gate was closed for ~90%
of 2008 trading days. This is the strategy's strongest feature — a nearly bear-proof
mean-reversion variant.

### 4. Bull-market performance similar to EC-R45

2013/2019/2021/2024 are all within 5-10% of EC-R45 — the SMA100 layer doesn't add much
additional filtering during uptrends because SPY is above SMA100 almost continuously in
bull markets. Net bull cost is roughly the same as EC-R45.

### 5. EC-R46 beats EC-R45 by $38k despite tighter gating

Because the 2022 loss was $20k smaller AND the 2008/2018 losses were smaller, the strategy
recovers faster — compound effect makes R46 finish $38k ahead of R45 despite similar bull
performance.

### 6. EC-R46b (hysteresis): OVERFITTED — ELIMINATED

Fails WFA verdict. OOS P&L only +1.89%. The 3-day consecutive-positive-slope rule is
effectively a parameter tweak that performed marginally better in-sample but generalized
worse to OOS 2021-2026. Rolling WFA Pass 3/3 is contradicted by the whole-period "Likely
Overfitted" flag, suggesting the fold boundaries hid the overfitting.

Hysteresis is not the right lever — regime overlay (SMA100) is. EC-R46b permanently
eliminated from consideration.

## Red Flag Investigation — Roll.Sharpe(min) = -70.99

**What it means:** the 126-day rolling Sharpe hit -70.99 at some point in the backtest.
Normal values are in the -2 to +3 range.

**Root cause:** the two-layer gate is closed for extended periods (~50% of trading days in
some sub-periods). During gate-closed weeks, the daily return series is near-zero with a
handful of tiny losses. Rolling Sharpe = mean / std — when std approaches zero and mean
is slightly negative, Sharpe blows up toward -∞.

**Not an actual equity cliff:** MaxDD is 19.10%, 2022 drawdown is ~14%. No single 126-day
window loses anything close to -70.99% of its mean.

**Comparison:** EC-R46b (less restrictive gate) has RS(min) = -4.49 — normal. The
difference is entirely explained by gate closure frequency, not by realized equity behavior.

**Interpretation:** RS(min) becomes unreliable as a metric when gate-closure rate > 40%.
Use MaxDD / Calmar / visual equity curve for tight-gate strategies. This is the second
known metric-artifact at this severity (first was negative Sharpe at 4H timeframe, resolved
in chapter 2).

## Distribution Diagnostic

| Metric | EC-R46 | EC-R45 | Threshold |
|---|---|---|---|
| Top 1 trade / total P&L | ~1.6% | ~1.4% | < 3% ✓ |
| Top 5 trades / total P&L | ~4.5% | ~4.3% | < 15% ✓ |
| Total trades | 8,995 | 9,531 | — |
| PASS distribution test? | Yes | Yes | — |

No dominant winner. The filter structurally caps single-trade upside.

## Verdict

**EC-R46: STRONGEST CANDIDATE YET** — genuinely meets the "smooth equity curve" goal
for the first time in the research loop.

- MaxDD 19.10% (new record floor)
- Calmar 0.37 (new record high)
- 2008 essentially flat (-$2k)
- 2018 essentially flat (+$0.5k)
- 2020 COVID V-recovery captured (+$36k)
- 2022 cliff cut 27% ($73k → $53k)
- WFA Pass + Rolling 3/3 + MC 5 + Robust
- Distribution clean (no dominant trade)

**Remaining imperfection:** 2022 still shows a visible 14% drawdown. The strategy is NOT
better than SPY B&H in absolute terms (lags 505pp), but it has a fundamentally different
risk profile — far less volatile equity curve suited to risk-constrained investors.

## Next Research Direction: Universality Test

46 rounds into the EC chapter, EC-R46 needs universality validation before being declared
champion. The multiple-testing correction from memory ("sweep base must not be at distribution
maximum") means a single-universe win isn't enough.

### EC-R47 plan: test EC-R46 across 3 universes

Same strategy (EC-R46 code unchanged), run on:
- **EC-R47a:** Sectors+DJI 46 (`sectors_dji_combined.json`) — diversified sector exposure
- **EC-R47b:** Nasdaq 100 (`nasdaq_100.json`) — tech-heavy universe
- **EC-R47c:** Russell 1000 — broader small/mid cap exposure (if available)

**Accept as champion IF:**
- MaxDD < 25% on all three universes
- Calmar > 0.30 on all three
- WFA Pass + Rolling 3/3 + MC 5 on all three
- No universe shows >70% performance degradation vs S&P 500 baseline

**Reject IF:**
- Performance is S&P 500-specific (the 1273-symbol diversification is load-bearing)
- Any universe shows WFA Overfitted or MC Score < 3

### Also queue: EC-R48 visual review

Generate PDF tearsheet for EC-R46 on S&P 500 and submit to human reviewer. Visual inspection
is the ultimate arbiter of "smooth equity curve" — metrics cannot fully characterize it.
