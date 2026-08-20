# Backtest spec — "Gold, dovish/real-yield regime long"

**Status:** SPEC (not yet run). Run in `Desktop/github/july-backtester` (v1.8.2, `rtk` mandatory). Flagged
2026-08-06. Companion to the **Swing Worksheet → "GOLD (GLD)" row** (checked daily) and the deep-dive in the
8/6 session. **Read this before running so we test the RIGHT hypothesis, not a flattering one.**

## The hypothesis (one sentence)
*When real yields are falling for an identifiable reason, gold is the cleanest long — entered on a
close+volume breakout gate, exited when the regime reverses — and it makes money net of the 2022+
structural-bid breakdown, not just in the friendly 2003–2021 decade.*

## Why this needs a real test (don't skip)
The gold ⇄ real-yield inverse correlation was tight 2003–2021 (r ≈ −0.7 to −0.9 on multi-month changes) then
**broke down from ~2022** — real yields rose while gold hit records, driven by central-bank buying /
de-dollarization (a variable outside the real-yield model). A strategy fit only to the correlation is the
**"incomplete risk set"** trap (cf. the 7/15 long-gamma pass that lost in `POSITIONS.md`). The test must span
the breakdown, per the repo rule *"always extend across ≥1 bear market"* (the July-seasonality correction).

## Data
- **Gold price:** GLD (unadjusted, `auto_adjust=False` — match `scan.py`), and spot XAU as a cross-check.
  Miners: GDX (for the beta/accelerator variant). Longest history via the **parquet/Norgate** provider
  (`pd.read_parquet`, bypass `import config` — it hangs when NDU is down; see `CONTEXT.md` § Backtester).
- **Real yield:** 10y TIPS real yield — **DFII10** (FRED). This is the load-bearing series; source it directly,
  don't proxy with TLT (nominal = confounded by breakevens).
- **Nominal + breakevens (for the discriminating tell):** DGS10 (nominal 10y), T10YIE (10y breakeven) → so we
  can label each gold up-move as *real-yield-driven* (DFII10 down) vs *inflation/structural-driven* (DFII10
  flat/up while gold rises).
- **Regime inputs (to define "dovish for an identifiable reason"):** VIX, oil (Brent/BNO — the global
  benchmark, NOT USO for a global read), and a Fed-path proxy (Fed funds futures / DGS2 as a stand-in).
- Align all series to daily; **beware the Norgate parquet snapshot ends 2026-04-22** — `git submodule update
  --remote` before trusting recent bars. FRED series are tz-naive; GLD via yahoo may be tz-aware/MultiIndex —
  flatten + `tz_localize(None)`.

## Signal definitions (test these AS SEPARABLE LEGS — the point is which leg carries the edge)
1. **Entry gate (technical, repo-native):** a daily CLOSE that breaks out above the prior N-day high (start
   N=20) on volume > the 20-day MEDIAN (VOLx > 1.0) AND closes strong (buy% ≥ 60). Same gate as issue #1.
2. **Regime filter (the conditioning variable):** only take the entry when real yields are **falling** —
   define as DFII10 down over a trailing window (test 5d and 20d), OR Fed-hike odds falling. This is the
   hypothesis's core: *the gate alone vs the gate+regime filter* is the key A/B.
3. **Structural-bid overlay (the 2nd variable):** tag each trade by whether it's real-yield-driven (DFII10
   down during the hold) or structural (DFII10 flat/up while gold rises). Report performance split by tag —
   this quantifies how much of the edge is the mechanism vs the CB bid.

## Entry / exit / invalidation
- **Entry:** next open after the confirming close (match the book's "enter next open" rule; also test
  a held-retest-of-the-breakout entry).
- **Stop (position):** a daily CLOSE back below the breakout level (failed breakout). Close-based, not intraday.
- **Regime exit (swing kill):** real yields turn UP over the trailing window (DFII10 rising) OR a hot
  data/hawkish-Fed flip. Test "exit on regime reversal" vs "exit only on the price stop" — does the regime
  exit add or subtract?
- **No naked buy-stop** (the 0-for-15 loser bucket).

## The A/Bs that actually answer the question
1. **Gate only** vs **Gate + falling-real-yield filter** — does conditioning on the mechanism beat the raw
   breakout? (If not, gold's real-yield story is decorative and we should admit it.)
2. **2003–2021** vs **2022–present** subsamples, reported separately — does the edge survive the breakdown, or
   was it a rates-decade artifact?
3. **GLD** vs **GDX** (the ~1.8× accelerator) — risk-adjusted, does the miner beta pay for its equity-beta +
   long-run underperformance?
4. **Regime exit** vs **price-stop-only** — does exiting on a real-yield reversal improve the curve?
5. **TLT-confirms filter:** require TLT green on the entry day (the "real-yield leg confirmed" tell) — does it
   filter the structural-only fakeouts?

## Metrics (report all; no silent caps)
Win rate, avg win/avg loss, expectancy per trade, profit factor, max drawdown, Sharpe/Sortino, # trades,
**equity curve split by subsample AND by real-yield-vs-structural tag**, and the average DFII10 change during
winners vs losers (does the mechanism actually show up in the P&L?). Log any trades dropped by a filter — a
truncated sample reads as "it works" when it doesn't.

## Kill criteria (decide BEFORE running, so we don't rationalize)
- If **Gate + regime filter ≤ Gate only** on risk-adjusted return across the full sample → the real-yield
  conditioning adds nothing; the "strategy" is just a gold-momentum breakout, say so.
- If the edge lives **only** in 2003–2021 and dies 2022+ → it's a dead regime, not a strategy; shelve it or
  rebuild it around the structural-bid variable.
- If winners and losers show the **same** average DFII10 move → the mechanism isn't in the P&L; the story is
  post-hoc.

## Open questions to resolve while building
- Best real-yield window (5d vs 20d vs a level threshold)?
- Does adding the **oil/disinflation** leg (Brent falling) to the regime filter sharpen it (our 8/5 driver)?
- Is there a cleaner short-real-yield hedge than GLD for the *pairs* version, or is the pairs trade the
  widowmaker we already suspect (residual trended, didn't mean-revert, post-2022)?

---

## RESULTS — run 2026-08-06 (first-pass screening backtest)

**Setup as run:** GLD & GDX via yfinance (2004→now, `auto_adjust=False`); real yield = FRED **DFII10** (ffill,
~1d lag). Gate = close > prior-20d high AND vol > 20d median AND buy% ≥ 60. Regime filter = DFII10 falling
over 20d. Entry next open; exits tested = price stop (close < breakout line) ± regime exit (real yields
rising). Open-to-open, **no costs/slippage, no position sizing.** Screening-grade, not production.

### ⚠ The no-regime-exit variants are DEGENERATE — ignore them
Gate-only / gate+regime with only "close < line" as the stop → a single breakout entry is held for YEARS in a
secular bull (n=6, avgW +380%, +706% total). That's **buy-and-hold with a lag**, not a tradeable signal, and
it's why "2022+ = NO TRADES" (still in the pre-2022 position). The tradeable read is the **regime-exit** row.

### The tradeable variant — GLD, gate + falling-real-yield filter + regime exit
| Sample | n | win% | exp/trade | PF | maxDD | total | RYΔ winners / losers |
|---|---|---|---|---|---|---|---|
| ALL 2004+ | 102 | 45% | +0.56% | 1.62 | −13.4% | +66% | −0.04 / +0.01 |
| **pre-2022** | 78 | 42% | **+0.69%** | **1.84** | −13.4% | +62% | **−0.06 / +0.01** |
| **2022+** | 24 | 54% | **+0.14%** | **1.12** | −12.7% | **+2%** | **+0.04 / +0.04** |

Time-in-market ~20%; **buy&hold GLD over the same span ≈ +776%.**

### Verdict vs the pre-committed kill criteria
- **Kill #2 TRIGGERED — the edge is a pre-2022 phenomenon.** PF 1.84 → 1.12, expectancy +0.69% → +0.14%,
  +2% total over 3½ years. The real-yield-conditioned edge **died when the correlation broke in 2022.**
- **The mechanism is verifiably IN the P&L pre-2022 and INVERTS post-2022 (the money finding).** Real-yield
  change *during winners*: **−0.06 pre-2022** (won while real yields fell = mechanism working) → **+0.04
  post-2022** (won while real yields ROSE = mechanism gone, the CB/de-dollarization bid). This is direct
  empirical confirmation of the "carry the 2nd variable / incomplete risk set" thesis — the gate didn't stop
  working because gold stopped rising, but because **gold's driver changed.**
- **The real-yield EXIT backfired post-2022** — exiting on rising real yields cut the strategy out of gold's
  biggest bull run (gold rose *with* yields), leaving ~700% vs buy&hold on the table.
- **GDX is not a clean vehicle:** full-sample NEGATIVE (PF 0.93, −28%), lost badly pre-2022 (−49%), only worked
  2022+ (+41%). Confirms "tactical accelerator, not a core hold; one budget."

### Actionable conclusions (they change the live playbook)
1. **Do NOT trade the real-yield-conditioned version as specified** — regime-broken by our own criteria.
2. **If long gold here, be long for the MOMENTUM / structural (CB) bid, not the real-yield mechanism** — that
   mechanism hasn't paid since 2022.
3. **Do NOT use "real yields turned up" as the exit** (it's what cut people out of 2022+). Use a **price stop**
   (close back below the breakout) or a trailing stop.
4. The earlier "hot NFP → real yields up → sell gold" logic is **empirically weakened** — post-2022 gold has
   risen through rising real yields. A hot NFP is still a near-term positioning risk, but the *mechanism* case
   for it killing gold is now weak.

### Next iterations (to rebuild, not retire)
- Replace the real-yield exit with a price/ATR trailing stop; re-test.
- Add the **structural-bid proxy** as the 2nd variable (central-bank purchase data / a de-dollarization proxy)
  and test gate + (real-yield OR structural-bid) — does modelling the actual post-2022 driver restore an edge?
- Add the oil/disinflation leg (Brent falling) to the regime filter (our 8/5 driver).
- Extend GLD history via a Norgate gold proxy pre-2004; add costs/slippage; add position sizing.
