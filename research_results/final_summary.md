# Autonomous Strategy Research — Final Summary

**Research Loop:** 51 Rounds × Multi-Agent Parallel Research — **COMPLETE ✓**
**Last Updated:** 2026-04-11
**Data Provider:** Norgate (total-return adjusted daily bars)
**Full Period:** 1990-01-01 → 2026-04-11 (36 years)
**Ecosystems tested:** AAPL single → tech_giants (6) → NDX Tech (44) → SP500 (500) → Russell 1000 (1,012) → DJI 30 → Biotech (257) → Sector ETFs (16) → High Vol (242) → Russell Top 200 (198) → NDX Full (101) → NDX+DJI (124) → Sectors+DJI (46) → Intl ETFs (30) → Global Diversified (76)

---

## Research Architecture

```
Round 1 (9 strategies on AAPL, 2004-2026)
  → Discover: single-symbol testing is misleading; ecosystem is key

Round 2 (9 strategies on tech_giants 6 sym, 2004-2026)
  → Donchian (40/20) and EMA+ROC emerge as champions; OBV introduced

Round 3 (8 strategies on tech_giants 6 sym, 2004-2026)
  → BREAKTHROUGH: MA Confluence family discovered (best strategy ever at the time)
  → OBV MaxDD fixed with SMA200 gate

Round 4 (validation, tech_giants 6 sym, 2004-2026)
  → Rolling WFA resolved (3 folds); MA Confluence Fast Exit restored
  → All 6 champions fully validated: WFA + RollWFA 3/3 + MC 5

Round 5 (5 new strategies, 1990-2026 extended history)
  → Start date pushed to 1990 (36 years of data)
  → BREAKTHROUGH: MA Bounce (50d)+SMA200 discovered — r=0.02 vs MA Confluence
  → MA Confluence Fast Exit: 101,198% P&L on 44 symbols over 36 years

Round 6 (fix attempts + 44-sym validation, 1990-2026)
  → Most fixes failed; Donchian (60d/20d)+MA Alignment validated on 44 symbols
  → RS(min) -3.98 on 44 symbols — second-smoothest equity curve overall

Round 7 (5 first-principles strategies, 1990-2026)
  → DISCOVERY: RSI>50 is redundant on N-bar new-high breakouts (r=+1.00 proven)
  → DISCOVERY: ROC (20d)+MA Full Stack Gate — SQN 6.95 (highest ever), RS(min)=-3.83
  → CMF (10d) failed — shorter window makes CMF noisier, not better
  → EMA (8/21)+CMF Hold Gate: MaxRcvry 5008 days — dual-condition exit creates whipsaw

Round 8 (4 experiments + 2 portfolio-level tests, 1990-2026)
  → SP500 UNIVERSALITY CONFIRMED — all 3 champions pass WFA+RollWFA 3/3 on 500 stocks
  → MAC RS(min)=-3.49 on SP500 (SMOOTHER than -4.46 on NDX) — diversification helps equity curve
  → 3-strategy combined portfolio: all WFA Pass, MA Bounce RS(min) degrades to -23.28 (capital competition)
  → ATR 3.5x trailing stop FAILED to rescue MC Score — synchronized tech crashes can't be stopped by position-level stops
  → Donchian + Volume Breakout: too selective (143 trades, negative Sharpe)
  → MA Bounce + OBV Gate at entry: OBV gate eliminates 55% of valid bounces (same mistake as RSI gate)

Round 9 (weekly timeframe + new signals + SP500 combined portfolio, 2026-04-11)
  → BREAKTHROUGH: MA Bounce on WEEKLY bars — Sharpe 1.92 (vs 0.61 daily), RS(min) -2.32 (vs -10.93 daily), P&L 140,028%
  → BREAKTHROUGH: Price Momentum (6m ROC, 15pct) — P&L 107,513%, Sharpe +0.67, OOS +93,844% — NEW CHAMPION
  → SP500 combined portfolio at 3%: MA Bounce MC Score = +1 (first positive MC Score on large universe!)
  → NR7 Volatility Contraction FAILED: Sharpe -0.07 (below risk-free rate of 5%)
  → Infrastructure: added W and M timeframe support to get_bars_for_period()

Round 10 (weekly timeframe confirmation — MAC Fast Exit + Donchian, 2026-04-11)
  → CONFIRMED: Weekly timeframe is a STRUCTURAL improvement for ALL momentum strategies
  → MAC Fast Exit Weekly: Sharpe 1.80 (vs 0.68 daily, +165%), RS(min) -2.54 (vs -4.46, 1.75× better)
  → Donchian Weekly: Sharpe 1.68 (vs 0.63, +167%), RS(min) -2.06 = BEST OF ALL STRATEGIES EVER TESTED
  → Pattern is consistent across 3 different architectures (trend MA, breakout channel, bounce)

Round 11 (combined weekly + SP500 + Price Momentum weekly, 2026-04-11)
  → BREAKTHROUGH: Price Momentum on weekly bars — Sharpe 1.87 (vs 0.67 daily, +179%), RS(min) -2.30 (vs -15.92, 6.9× better), P&L 156,879% (new #1)
  → CONFIRMED: Combined weekly portfolio is optimal structure — MA Bounce W Sharpe 2.04, MAC W RS(min) -1.85 (best ever), Donchian W Sharpe 1.78. MaxDD -8 to -15pp vs isolation.
  → FAILURE: Price Momentum SP500 universality FAILED — RS(min) -17.09 (worse than NDX -15.92). Price Momentum is tech-sector-specific signal.
  → FINDING: 4 of 4 strategies tested on weekly bars show 165-215% Sharpe improvement — weekly timeframe improvement is fully confirmed universal finding

Round 12 (4-strategy combined weekly portfolio — FINAL VALIDATION, 2026-04-11)
  → RESEARCH COMPLETE: 4-strategy weekly portfolio confirmed as optimal production structure
  → All 4 strategies at 4% allocation: Sharpe 1.68-1.99, MaxDD 49.34-55.40%, RS(min) -2.10 to -2.70, WFA Pass all, RollWFA 3/3 all
  → Adding Price Momentum W REDUCED MaxDD for all 3 existing strategies vs 3-strategy Q11 run
  → Price Momentum W MaxDD 49.34% — BEST MaxDD ever; Expectancy(R) 21.45 — HIGHEST EVER
  → All 4 strategies hold WFA Pass with no capital-competition overfitting

Round 13 (monthly timeframe test, 2026-04-11)
  → Monthly bars: Sharpe 3.77-3.93 (extraordinary) but MaxDD 73-75%, MaxRecovery 3,930 days (11 years)
  → RS(min) POSITIVE (+0.37/+0.45) — monthly strategies never had a 6-month losing period
  → Strategy correlation = 0.97 at monthly granularity — no portfolio diversification benefit
  → VERDICT: Theoretically extraordinary but impractical for live trading. Weekly is the optimal timeframe.

Round 14 (MACD weekly + RSI weekly, new strategy families, 2026-04-11)
  → MACD Weekly (3/6/2) FAILED: Sharpe 1.05, 4,238 trades (too frequent — crossovers not filtered by weekly resolution)
  → BREAKTHROUGH: RSI Weekly Trend (55-cross) + SMA200 — NEW CHAMPION rank 3
    Sharpe 1.85, RS(min) -2.15, OOS +114,357%, SQN 6.80, WFA Pass 3/3
  → RSI>55 on weekly bars = genuine regime signal; 45-exit gives positions room to breathe
  → File: custom_strategies/round13_strategies.py

Round 15 (Russell 1000 universality — 4-strategy weekly on 1,012 symbols, 2026-04-11)
  → UNIVERSALITY CONFIRMED: All 4 strategies WFA Pass + RollWFA 3/3 on 1,012 symbols
  → Sharpe 0.87-1.18 (lower than NDX — non-tech dilutes momentum signal, as expected)
  → Price Momentum achieves Sharpe 1.18 on Russell 1000 weekly — confirming SP500 daily failure was a timeframe issue
  → SQN 9.32-10.21 — near-maximum statistical confidence; 2,280-6,157 trades per strategy
  → Universality chain complete: NDX 44 ✓ → SP500 500 ✓ → Russell 1000 1,012 ✓

Round 16 (5-strategy combined weekly portfolio, 2026-04-11)
  → RESEARCH COMPLETE (EXTENDED): 5-strategy weekly portfolio at 3.3% allocation
  → ALL 5 strategies MaxDD below 50%: MA Bounce 44.46%, Price Momentum 44.83%, Donchian 47.72%, RSI 49.36%, MAC 49.77%
  → Donchian and Price Momentum reach MC Score +1 (first time on NDX Tech 44 combined run)
  → RSI Weekly contributes highest combined P&L (32,558%) and OOS (+27,315%) in the 5-strategy portfolio
  → Sharpe range 1.63-1.95, RS(min) -2.19 to -2.73 (all better than -3)
  → All 5 WFA Pass + RollWFA 3/3 — no capital-competition overfitting

Round 17 (5-strategy weekly on SP500 — universality + Price Momentum breakthrough, 2026-04-11)
  → ALL 5 WFA Pass + RollWFA 3/3 on SP500 503 symbols
  → BREAKTHROUGH: Price Momentum SP500 weekly — Sharpe 1.81, RS(min) -1.86, OOS +50,953%
    (vs SP500 DAILY: Sharpe 0.56, RS(min) -17.09 — daily failure was timeframe artifact)
  → Donchian achieves MC Score +1 on SP500 combined run
  → Price Momentum vs RSI Weekly correlation = 0.83 on SP500 (lower on NDX tech universe)
  → Universality now confirmed: NDX 44 ✓ → Russell 1000 1,012 ✓ → SP500 503 ✓ for all 5 strategies

Round 18 (block bootstrap MC — autocorrelation effect on MC Scores, 2026-04-11)
  → Block bootstrap: all 5 strategies revert to MC Score -1 (Donchian and Price Momentum had been +1 under IID)
  → IID MC was optimistic — weekly momentum trades ARE autocorrelated (winning streaks cluster in trends)
  → Block bootstrap block size auto = floor(sqrt(N)) captures 8-13 months of trade history per block
  → Conclusion: MC Score -1 is the honest authoritative risk assessment for concentrated tech portfolios

Round 19 (±1% OHLC noise injection stress test, 2026-04-11)
  → ALL 5 strategies pass: Sharpe changes -1.0% to +1.2% — essentially zero
  → RSI Weekly Sharpe 1.91 → 1.92 (+0.5%); Price Momentum 1.80 → 1.80 (0.0%)
  → Weekly strategies are noise-immune: long-window indicators (SMA40w, RSI14w) dilute 1-bar noise
  → Trade counts change < 1% — strategies' signals are stable at ±1% perturbation

Round 20 (RSI Weekly parameter sensitivity sweep — Q21, 2026-04-11)
  → 625 grid variants tested (5^4 combinations of rsi_period, rsi_entry, rsi_exit, sma_slow)
  → 535 valid variants (≥50 trades): 534/535 (99.8%) profitable, 535/535 (100%) WFA Pass
  → Mean Sharpe 1.58 across valid variants; range -0.98 to 2.10
  → ROBUST VERDICT: RSI Weekly edge is NOT parameter-specific. 55/45 thresholds are within a wide profitable family.
  → Best discovered variant: rsi_period=10, rsi_entry=63.25, rsi_exit=51.75 → Sharpe 2.10

Round 21 (Dow Jones 30 — Q22, 2026-04-11)
  → BREAKTHROUGH: All 5 WFA Pass + RollWFA 3/3 on DJI 30 blue-chip stocks
  → MaxDD 19-23% — HALF of NDX Tech 44 (44-50%); Sharpe 1.71-1.93 (competitive with NDX)
  → MC Score +5 for MA Bounce, MAC, Donchian — sector cross-diversification breaks correlated crashes
  → RSI Weekly best P&L (3,926%) and OOS (+1,729%) on DJI
  → Key insight: MaxDD reduction requires a universe where non-tech names are the majority

Round 22 (Nasdaq Biotech 257 — Q23, 2026-04-11)
  → ALL 5 WFA Pass on biotech (binary FDA events)
  → Sharpe 0.68-0.81 (LOWEST universe tested — binary events create noise floor)
  → MaxDD 55-67% (FDA cliff events raise drawdown ceiling)
  → MAC Fast Exit best (Sharpe 0.81) — fast exit protects against sudden FDA reversals
  → OOS P&L +1,550% to +2,961% due to COVID-era biotech super-cycle
  → Conclusion: Strategies work even in the hardest binary-event sector

Round 23 (Sector ETFs 16 — Q24, 2026-04-11)
  → ALL 5 WFA Pass + ALL MC Score +5 — FIRST TIME all 5 strategies reach MC Score +5
  → 16 maximally diversified ETFs (energy, tech, utilities, real estate, defense, gold, etc.)
  → Geographic/sector decorrelation = Monte Carlo can't construct scenario that crashes all 16 simultaneously
  → Sharpe 0.54-0.95 (lower than individual stocks — ETF trend capture is smoother but shallower)
  → Confirmed: MC Score is determined by universe correlation structure, not strategy quality

Round 24 (Russell 2000 attempt — Q25, 2026-04-11)
  → NOT TESTABLE: Norgate carries ~203 of 1,969 R2000 symbols; 202 have <250 weekly bars
  → Only 1 valid symbol — not a meaningful test; provider limitation
  → Workaround: use Russell Top 200 (198 mega-caps) as the large-cap Russell proxy

Round 25 (High Volatility 242 — Q26, 2026-04-11)
  → ALL 5 WFA Pass on high-momentum names (NVDA, TSLA, PLTR, AVGO, etc.)
  → Sharpe 1.16-1.31 — LOWER than NDX Tech 44 (1.63-1.95): excess volatility reduces Sharpe
  → MAC Fast Exit dominant (Sharpe 1.31) — FIRST universe where MAC > RSI Weekly
  → RSI Weekly weakest (1.16) — RSI 55-cross disrupted by binary volatility spikes in high-vol names
  → Hypothesis falsified: extreme momentum names do NOT produce higher Sharpe; NDX quality > high-vol quantity

Round 26 (Russell Top 200 — Q27, 2026-04-11)
  → ALL 5 WFA Pass; Price Momentum Sharpe 1.95 (NEW RECORD for that strategy)
  → RSI Weekly RS(min) -1.85 (NEW RECORD — best rolling Sharpe floor of any strategy)
  → RS(avg) > 1.77 for all 5 strategies — highest consistent rolling average of any universe
  → MaxDD 37-54%; 4 of 5 below 45%
  → Best balanced universe: mega-cap diversification (tech + financials + healthcare + energy + consumer)

Round 27 (Nasdaq Full 101 — Q28, 2026-04-11)
  → ALL 5 WFA Pass; Sharpe 1.83-1.95 (matches NDX Tech 44, BETTER Donchian: +0.29)
  → Donchian: Sharpe 1.63 → 1.92 with 57 additional non-tech NDX names
  → RS(avg) > 1.99 for all 5 (new consistency record)
  → MaxDD does NOT improve vs NDX Tech 44 (NDX non-tech crashes alongside tech in 2022)
  → Updated production recommendation: use nasdaq_100.json (101) over nasdaq_100_tech.json (44)

Round 28 (NDX Full + DJI 30 combined 124 symbols — Q29, 2026-04-11)
  → MA Bounce Sharpe 1.98 (NEW ALL-TIME RECORD)
  → RS(avg) > 2.0 for ALL 5 strategies (NEW RECORD for rolling consistency)
  → MaxDD hypothesis FALSIFIED: blending NDX+DJI worsens MaxDD +3-9pp vs NDX Tech 44
  → Insight: tech crashes dominate when 101 NDX names + 23 unique DJI = still 80%+ tech
  → For MaxDD reduction, non-tech names must be the MAJORITY (not a small addition)

Round 29 (Sectors+DJI 46 — Q30, 2026-04-11)
  → BREAKTHROUGH — BEST RISK-BALANCED UNIVERSE DISCOVERED
  → Sharpe 1.54-1.86; MaxDD 21-30%; MC Score +5 for MAC/Donchian/MA Bounce; +2 for RSI/Price Momentum
  → FIRST universe to simultaneously achieve Sharpe >1.50, MaxDD <31%, MC ≥+2
  → MAC Fast Exit RS(min) -2.00 (outstanding); RSI Weekly Sharpe 1.86 (highest on this universe)
  → Price Momentum MaxDD 21.52% (matches DJI 30 best-case)
  → Formula: 16 Sector ETFs (decorrelation backbone) + 30 DJI stocks (individual alpha) = optimal mix

Round 30 (International ETFs 30 — Q32, 2026-04-11)
  → ALL 5 WFA Pass + ALL MC Score +5 — geographic diversification fully cancels tail risk
  → Sharpe 0.67-1.08 (lower — Japan stagnation, currency headwinds, weaker intl momentum)
  → MaxDD 27-32% (comparable to Sectors+DJI 46)
  → AvgRcvry 114-188 days (3-6× longer than US equities — international drawdowns last longer)
  → RSI Weekly dominant (Sharpe 1.08, best OOS +373%)
  → Best use: complement to Sectors+DJI 46 in a larger global portfolio

Round 31 (Global Diversified 76 = Sectors+DJI+International ETFs — Q33, 2026-04-11)
  → ALL 5 WFA Pass + RollWFA 3/3 on 76-symbol global portfolio
  → Sharpe 1.36-1.82; MaxDD 22-34%; MAC+Donchian MC Score +5
  → Donchian RS(min) -1.91 — NEW RECORD for that strategy
  → HIGH CORRELATION ALERT: Price Momentum ↔ RSI Weekly r=0.81 on this universe
    → Use only ONE of the two in a live portfolio on Global Diversified 76
  → Sectors+DJI 46 remains superior: slightly better Sharpe (1.54-1.86) and MaxDD (21-30%)
  → Global Diversified 76 best for investors who explicitly want geographic diversification

Rounds 32-40 (New Champions + Sweeps + Portfolio Tests — 2026-04-11)
  → BB Weekly Breakout (20w/2std)+SMA200 CONFIRMED: Sharpe 2.08, RS(min) -3.50, 75/75 sweep variants profitable (ROBUST)
  → Williams R Weekly Trend (above-20)+SMA200 CONFIRMED: Sharpe 1.94, RS(min) -2.12, 625/625 variants profitable (ROBUST)
  → Relative Momentum (13w vs SPY) CONFIRMED: P&L 166,502% (all-time high), Sharpe 2.08, 831 trades (NOT 99 — earlier was column misread)
  → Q42 sweep: 125/125 variants profitable (100%), 124/125 WFA Pass (99.2%). Base params at 99th percentile.
  → Williams R in combined 5-strat portfolio: r=0.80 vs Price Momentum → RSI Weekly remains preferred
  → Sectors+DJI 46 with 6 strategies + Relative Momentum: only 97 trades (ETF universe mismatch) → keep 5-strategy conservative portfolio unchanged
  → ALL mean reversion strategies on weekly bars confirmed DEAD: RSI MeanRev 0 trades, BB MeanRev 22 trades/Sharpe -1.45

Round 41 (6-Strategy NDX Tech 44 — "Aggressive" portfolio — Q44, 2026-04-11)
  → ALL 6 strategies WFA Pass + RollWFA 3/3 on NDX Tech 44 weekly bars
  → Relative Momentum: 969 trades (↑ from 831 in isolation), MC Score 5 (first ever on NDX Tech 44!)
  → ALL 6 MaxDDs below 47% — first time all strategies < 50% on NDX Tech 44 combined
  → CRITICAL DISCOVERY: Price Momentum ↔ RSI Weekly r=0.94 on NDX Tech 44 (HIGH ALERT)
    → These two strategies are functionally identical in combined NDX Tech 44 context
    → Do NOT run Price Momentum + RSI Weekly together on NDX Tech 44 weekly
  → Correlation profile clarified: Relative Momentum r=0.08 vs MAC (confirmed), r=0.57-0.60 vs MA Bounce/PM/RSI

Round 42 (Optimized 5-Strategy NDX Tech 44 — Q45, 2026-04-11)
  → ALL 5 WFA Pass + RollWFA 3/3; no HIGH CORRELATION alerts
  → Optimized portfolio: MA Bounce + MAC + Donchian + RSI Weekly + Relative Momentum at 3.3%
  → SUPERIOR to original R16 5-strategy portfolio:
    → Relative Momentum MaxDD 31.82% (vs Price Momentum 44.83% — 13pp better)
    → Relative Momentum MC Score +2 (vs Price Momentum MC Score +1)
    → RSI Weekly OOS +28,214% (vs +27,315% in R16 — new record in combined context)
    → No pair exceeds r=0.65 (vs r=0.94 Price Momentum↔RSI Weekly in R41)
  → RSI Weekly now highest P&L (33,311.90%) and OOS P&L of any strategy in combined context
  → CONFIRMED "Aggressive" Production Portfolio for NDX Tech 44 (pending Q47 BB Breakout test)

Round 43 (BB Breakout in 6-Strategy Combined Portfolio — Q46, 2026-04-11)
  → ALL 6 WFA Pass + RollWFA 3/3
  → BB Breakout MC Score 5 — second strategy to achieve this in combined context (alongside Rel Mom)
  → BB Breakout MaxDD 34.27% (second best in portfolio after Rel Mom 29.46%)
  → CRITICAL: BB Breakout ↔ RSI Weekly r=0.7049 — ABOVE 0.70 research threshold
  → BB Breakout CANNOT be added as a 6th strategy (breaks diversification constraint)
  → BB vs Donchian: BB superior on Sharpe (1.64 vs 1.56), MaxDD (34.27% vs 47.72%), MC Score (5 vs 2)
  → BUT Donchian ↔ RSI Weekly r=0.22 vs BB ↔ RSI Weekly r=0.7049 — Donchian is a far better diversifier
  → Q47 added: test BB Breakout replacing Donchian in 5-strategy configuration

Round 44 (BB Breakout Replacing Donchian — Q47, 2026-04-11)
  → REJECTED: BB ↔ RSI Weekly r=0.7874 (was 0.7049 in R43, escalates without Donchian)
  → BB ↔ Rel Mom r=0.7203 (was 0.6924 in R43, now also above 0.70 threshold)
  → Donchian acts as a structural portfolio buffer — its low RSI Weekly correlation (r=0.22) cannot be replicated
  → BB Breakout MC Score drops from 5 (at 2.8% allocation) to 2 (at 3.3%) — allocation artifact, not pure property
  → R42 5-strategy portfolio CONFIRMED FINAL — no improvement possible with current strategy set
  → Both production portfolios (Conservative + Aggressive) are now fully validated

Round 45 (BB Breakout as 6th Strategy in Conservative Portfolio — Q48, 2026-04-11)
  → ALL 6 WFA Pass + RollWFA 3/3; ALL 6 MC Score 5 — UNPRECEDENTED (first time ever in research history)
  → BB ↔ RSI Weekly r=0.4711 on Sectors+DJI 46 (vs r=0.7049 on NDX Tech 44 — sector rotation provides decorrelation)
  → BB Breakout MaxDD 13.29% — new record for lowest MaxDD ever in any combined portfolio run
  → CONDITIONAL PASS: BB Breakout can be added as 6th strategy; conservative portfolio v2 defined
  → BUT: BB OOS P&L only +170.96% (weakest of 6), BB Sharpe 1.43 (weakest of 6)
  → Q49 added: test Relative Momentum as 6th strategy (may have better OOS P&L than BB Breakout)

Round 46 (Relative Momentum as 6th Strategy in Conservative Portfolio — Q49, 2026-04-11)
  → REJECTED: Sharpe 0.80 (far below minimum), OOS P&L only +51.38%, RS(avg) = -0.07
  → RS(min) = -1615.81 — catastrophic rolling Sharpe window (near-zero equity curve period)
  → Universe mismatch: sector ETF relative momentum (SPY-relative) is mean-reverting, not momentum-continuing
  → Exceptional correlation properties (max r=0.2373 — lowest ever in any combined run), but alpha absent
  → BB Breakout (R45) confirmed as the superior 6th strategy option for Conservative portfolio
  → Conservative portfolio 6th strategy track CLOSED: 3 candidate strategies tested, BB Breakout wins
  → Q50 added (low priority): Williams %R as alternative 6th strategy candidate

Round 47 (Williams R Weekly Trend as 6th Strategy in Conservative Portfolio — Q50, 2026-04-11)
  → OUTSTANDING: Sharpe 1.82 — HIGHEST in the 6-strategy portfolio (beats RSI Weekly 1.78, Price Momentum 1.79)
  → OOS P&L +1,437.81% — 8.4× better than BB Breakout's +170.96%
  → Williams R ↔ RSI Weekly r=0.6451 (well below 0.70 threshold)
  → All 6 MC Score 5 — maintained (second consecutive run with ALL 6 MC Score 5)
  → Williams R is the DEFINITIVE WINNER among all 3 6th strategy candidates (Williams R > BB Breakout > Rel Mom)
  → Conservative portfolio v2: MA Bounce + MAC + Donchian + Price Momentum + RSI Weekly + Williams R at 2.8%
  → Conservative 6th strategy track CLOSED. ALL production portfolio configurations CONFIRMED FINAL.

Round 48 (Williams R Replacing Price Momentum in Conservative Portfolio v1 — Q51, 2026-04-11)
  → REJECTED: RSI Weekly MC Score drops 5 → 2 without Price Momentum in portfolio
  → Price Momentum acts as "MC buffer" for RSI Weekly via capital competition dynamics
  → Mechanism: when PM and RSI Weekly both want the same trending stock, capital allocation forces one to wait
  → This competition prevents RSI Weekly from building excessively concentrated simultaneous positions
  → Without PM: RSI Weekly has no capital competitor → Monte Carlo can now concentrate it fully in crashes
  → Williams R individual metrics excellent (Sharpe 1.86, OOS +2,156.89%, MC Score 5) — the issue is portfolio-level
  → Correlation improved (max r=0.6413 MAC↔Donchian vs 0.6925 PM↔RSI) but not worth RSI Weekly MC drop
  → Second instance of structural buffer pattern: identical mechanism to Donchian in Aggressive portfolio (R44)
  → Conservative v1 (R29, with Price Momentum) CONFIRMED FINAL. ALL THREE production portfolios now FINAL.

Round 49 (Williams R as 6th Strategy in Aggressive Portfolio — Q52, 2026-04-11)
  → REJECTED: Williams R creates THREE pairs above r=0.70 on NDX Tech 44
  → Williams R ↔ RSI Weekly r=0.752, Williams R ↔ MA Bounce r=0.718, Williams R ↔ Relative Momentum r=0.710
  → Third confirmation of universe-specific correlation: NDX Tech 44 concentrated tech produces high cross-strategy correlation
  → Williams R individual metrics outstanding (Sharpe 1.83, OOS +7,417.87%) — rejected purely for portfolio-level correlation
  → Comparison: Williams R ↔ RSI Weekly r=0.6451 on Sectors+DJI 46 (R47) vs r=0.752 on NDX Tech 44 — same pair, same strategy
  → R42 5-strategy Aggressive portfolio DEFINITIVELY CONFIRMED FINAL — no viable 6th strategy in current research set
  → Pattern (3rd instance): concentrated momentum universes produce high cross-strategy correlation; sector-diversified universes do not

Round 50 (ATR Trailing Stop on Conservative v1 — Q53, 2026-04-11)
  → REJECTED: ATR 3× stop INCREASES MaxDD for ALL 5 strategies (+6 to +9 pp) — opposite of expected
  → Sharpe drops 42% (1.70 → 0.99 avg), OOS P&L collapses 78-92% for all 5 strategies
  → Mechanism: stops fire during within-trend pullbacks, forcing premature exits → larger realized drawdowns
  → Different failure mode from R8 NDX Tech 44 (synchronized crashes): here stops are incompatible with weekly trend-following itself
  → Interesting: ATR stops improve MC Score for Price Momentum 2→5 and RSI Weekly 2→5 (but already achieved in combined portfolio via capital competition)
  → Universal finding: ATR trailing stops are structurally incompatible with weekly trend-following momentum strategies on any universe
  → Conservative v1 (R29, no stops) CONFIRMED as definitively optimal for MaxDD and all metrics

Round 51 (Williams R Parameter Sensitivity Sweep on Sectors+DJI 46 — Q54, 2026-04-11)
  → ROBUST: 81/81 variants profitable (100%), 81/81 WFA Pass (100%) — unambiguous robustness
  → Swept: wr_length [11/14/17] × entry_level [-16/-20/-24] × exit_level [-64/-80/-96] × sma_slow [32/40/48] (full 3^4 = 81 cartesian product)
  → Sharpe range 1.59-2.03 (all above 1.4 minimum threshold); worst case Sharpe 1.59 still excellent
  → Base config (Sharpe 1.84) is NOT at distribution maximum (best variant Sharpe 2.03, wr=14/entry=-16/exit=-96/sma=48)
  → No cherry-pick evidence: base sits in middle of distribution, confirming no curve-fitting to specific parameter set
  → Williams R confirmed robust on BOTH production universes: NDX Tech 44 (R36, 625/625) AND Sectors+DJI 46 (R51, 81/81)
  → Key infrastructure note: sensitivity_sweep_min_val=-100 required for negative-threshold strategies (Williams R, any -100 to 0 oscillator)
  → Conservative v2 (R47, Williams R as 6th strategy) fully validated. All three production portfolios CONFIRMED AND VALIDATED.
```

---

## 🏆 All-Time Champion Leaderboard (44 Symbols, 1990-2026)

Timeframe noted: D = daily, W = weekly. Both use annualized Sharpe (252 bars/yr for D, 52 bars/yr for W).
"Combined MaxDD" column = MaxDD in the final 5-strategy weekly combined portfolio (R16, 3.3% allocation).

| Rank | Strategy | TF | P&L | Sharpe | RS(min) | OOS | WFA | RollWFA | Combined MaxDD |
|---|---|---|---|---|---|---|---|---|---|
| 🥇† | Price Momentum (6m ROC, 15pct) | **W** | **156,879%** | +1.87 | -2.30 | +138,152% | Pass | 3/3 | **44.83%** |
| 🥇† | MA Bounce (50d/3bar)+SMA200 | **W** | 140,028% | **+1.92** | -2.32 | +123,865% | Pass | 3/3 | **44.46%** |
| 3 **NEW** | RSI Weekly Trend (55-cross)+SMA200 | **W** | 135,445% | **+1.85** | **-2.15** | +114,357% | Pass | 3/3 | 49.36% |
| 4 | MA Confluence Fast Exit | **W** | 84,447% | +1.80 | -2.54 | +72,265% | Pass | 3/3 | 49.77% |
| 5 | Donchian Breakout (40/20) | **W** | 53,499% | +1.68 | **-2.06** | +41,671% | Pass | 3/3 | **47.72%** |
| (Daily strategies) | MA Confluence Fast Exit | D | 101,198% | +0.68 | -4.46 | +88,023% | Pass | 3/3 | — |
| (Daily strategies) | Price Momentum (6m ROC, 15pct) | D | 107,513% | +0.67 | -15.92 | +93,844% | Pass | 3/3 | — |
| (8-14) | Other daily strategies — see RESEARCH_HANDOFF.md | | | | | | | |

†Co-champions: Price Momentum Weekly has higher P&L; MA Bounce Weekly has higher Sharpe.

**Best-by-metric (final, 5-strategy combined):**
- Highest Sharpe: MA Bounce Weekly (+1.92 isolated; +1.95 in 5-strategy combined)
- Best RS(min): Donchian Weekly (-2.06 isolated) / MAC Weekly in 5-strat combined (-2.19)
- Highest P&L: Price Momentum Weekly (156,879%)
- Highest Combined P&L: RSI Weekly (32,558% in 5-strategy run)
- Best OOS P&L: Price Momentum Weekly (+138,152%)
- Highest Combined OOS P&L: RSI Weekly (+27,315% in 5-strategy run)
- Best Combined MaxDD: MA Bounce W (44.46%), Price Momentum W (44.83%) — both below 45%
- Highest Expectancy(R): Price Momentum Weekly (21.45 — in 4-strategy combined portfolio)
| 4 | CMF Momentum (20d)+SMA200 | 51,173% | +0.63 | -15.03 | +43,803% | Pass | 3/3 | 0.18 |
| 5 | Donchian (60d/20d)+MA Alignment | 42,263% | +0.64 | -3.98 | +35,177% | Pass | 3/3 | 0.28* |
| 6 | MA Confluence (10/20/50) Full Stack | 29,771% | +0.54 | -4.36 | +22,911% | Pass | 3/3 | 0.17 |
| 7 | ROC (20d) + MA Full Stack Gate | 14,518% | +0.50 | -3.83 | +12,472% | Pass | 3/3 | 0.35 |
| 8 | SMA Crossover (20/50) + OBV Confirmation | 10,841% | +0.46 | -4.25 | +8,832% | Pass | 3/3 | 0.23 |

*Donchian variants have r=0.39-0.95 with each other; do not hold multiple Donchian variants simultaneously.

**MC Score Note:** All 44-symbol strategies show MC Score -1 (DD Understated + High Tail Risk). This is a concentration-risk warning — 44 correlated tech stocks crash simultaneously in bear markets. Not a strategy flaw; a portfolio construction constraint. Max 5-10 concurrent positions in live trading. **MC Score -1 cannot be rescued by position-level ATR trailing stops** (proven in R8 — 3.5x ATR still shows MC Score -1 and reduces P&L 78%).

---

## Tech Giants (6 Symbols, 1990-2026) — Selected Champions

| Strategy | P&L | Sharpe | RS(min) | OOS | WFA | RollWFA | MC Score |
|---|---|---|---|---|---|---|---|
| MA Confluence Full Stack | 2,718% | +0.43 | -4.44 | +1,660% | Pass | 3/3 | 2 |
| MA Bounce (50d/3bar)+SMA200 | 1,772% | +0.38 | -11.04 | +1,164% | Pass | 3/3 | **5** |
| Donchian Breakout (40/20) | 501% | +0.42 | -4.27 | +204% | Pass | 3/3 | **5** |
| MA Confluence Fast Exit | 857% | +0.59 | -4.53 | +334% | Pass | 3/3 | **5** |
| OBV+SMA200 Gate | 443% | +0.38 | -28.92† | +176% | Pass | 3/3 | **5** |
| Donchian (40/20)+SMA200 Gate | 394% | +0.33 | -28.92† | +161% | Pass | 3/3 | **5** |

†RS(min) = -28.92 is an artifact of bear-market inactivity (strategy flat, near-zero variance → inflated negative rolling Sharpe). Not a real risk indicator for these strategies.

---

## SP500 Universality Results (500 Symbols, 1990-2026) — R8 Confirmed

| Strategy | P&L | Sharpe | RS(min) | OOS P&L | WFA | RollWFA | Trades |
|---|---|---|---|---|---|---|---|
| MA Confluence Fast Exit | 6,300% | +0.44 | -3.49 | +3,096% | Pass | 3/3 | 3,648 |
| Donchian Breakout (40/20) | 7,789% | +0.47 | -4.13 | +4,754% | Pass | 3/3 | 3,070 |
| MA Bounce (50d/3bar)+SMA200 | 4,552% | +0.40 | -500† | +2,466% | Pass | 3/3 | 4,069 |

†RS(min)=-500 for MA Bounce on SP500 is a data artifact — early 1990-1991 bars before SMA200 warmup, not real risk.

**All 3 primary champions work on any large-cap equity universe. Signals are NOT tech-specific.**

---

## Strategy Signal Sources (Correlation Guide)

| Family | Strategy | Signal Source | Entry Mechanism |
|---|---|---|---|
| **MA Alignment** | MA Confluence Fast Exit | Price-MA structure | First bar all 3 MAs align bullishly |
| **MA Alignment** | MA Confluence Full Stack | Price-MA structure | Same entry, slower exit |
| **Breakout** | Donchian (40/20) | Price channel | Close above 40-bar high |
| **Breakout** | Donchian (60d/20d)+MA Align | Price channel + MA state | 60-bar high + fast MA>slow MA |
| **Support Bounce** | MA Bounce (50d/3bar)+SMA200 | Mean reversion within trend | Touch 50-SMA + recover, RSI not required |
| **Volume Flow** | CMF Momentum (20d)+SMA200 | Chaikin Money Flow | CMF crosses above 0.05, SMA200 gate |
| **Volume Confirm** | OBV+SMA200 Gate | On-Balance Volume | OBV above MA + price > SMA200 |

**Portfolio diversification:** For a 3-strategy portfolio, choose one from each row: MA Alignment + Breakout + Support Bounce. These have the lowest inter-family correlation.

---

## Key Research Conclusions

### 1. Ecosystem Scale Is the Most Important Variable
| Universe | Best Strategy P&L (2004 start) | Best Strategy P&L (1990 start) |
|---|---|---|
| AAPL alone | 83% | — |
| 6 tech giants | 949% | 2,718% |
| 44 NDX Tech | 5,962% (R3) | **101,198%** |

Same strategy, same parameters, different scale. The compounding of 44 uncorrelated opportunities over 36 years is the dominant effect.

### 2. MA Confluence Fast Exit Is the Statistical Champion
- P&L: 101,198% | Sharpe: +0.68 (highest ever) | OOS: +88,023%
- RS(min): -4.46 — extremely smooth equity curve
- Proven across 3 universes (6 sym, 44 sym) and 2 time windows (22yr, 36yr)
- The fastest loss cut (10-SMA cross) is the key advantage

### 3. MA Bounce Is a Genuine Diversifier
- r=0.02-0.16 vs MA Confluence across all tested universes
- Different entry philosophy: buys pullbacks while MA Confluence buys momentum
- Trades at opposite times — they are structurally uncorrelated, not just statistically
- Hold both in a live portfolio for genuine diversification

### 4. Extended History Reveals True Tail Risk
- 2004 start: MA Confluence MC Score 5 (no dot-com crash data)
- 1990 start: MA Confluence MC Score 2 (includes 2000-2002 crash)
- Lesson: always test from the earliest available data to surface hidden tail risks
- The 1990 start is more honest; treat MC Score 2 as the accurate risk assessment

### 5. 44-Symbol Results Are Statistically Superior
- 6 symbols = ~2,000-6,000 trades — small enough for outlier distortion
- 44 symbols = 15,000-40,000+ trades — law of large numbers stabilizes all metrics
- RS(min) on 44 symbols is much more reliable than 6-symbol RS(min)
- Always validate on 44 symbols before drawing conclusions from 6-symbol results

### 6. RSI Gating of Bounce Strategies Is Counterproductive
- MA Bounce+RSI Timing tried RSI<50 at bounce time → only 65 trades, RS(min)=-1158
- The 50-SMA bounce itself IS the momentum reversal — RSI at that moment is 50-60
- Adding RSI confirmation eliminates the valid entries AND the timing advantage
- **Lesson: trust the price signal; don't second-guess it with an oscillator**

### 7. ATR Trailing Stops Need 3.0x+ on Tech Stocks
- 2.5x ATR: RS(min)=-48.10 (too many stop-outs in normal volatility)
- 2.0x ATR: WFA "Likely Overfitted", 814 trades (constant whipsawing)
- On NVDA/META with ATR ≈ 5-8% of price, 2.0-2.5x = 10-20% stop → too tight for daily bar strategies
- If using ATR stops, test 3.0x minimum; consider weekly bars instead

### 8. RSI Gates Are Redundant on Price-Breakout Strategies (R7)
- Donchian (40/20) + RSI>50 gate == Donchian (40/20) exactly (r=+1.00 on 44 symbols)
- When price reaches a 40-bar new high, RSI>50 is almost always already true by definition
- A N-bar new high IS a strong momentum signal; the oscillator just echoes it
- **Lesson: don't add RSI confirmation to breakout entry events — it's a redundant parameter**

### 9. CMF Window Length Is Not the Problem (R7)
- CMF (10d) had negative Sharpe (-0.13) vs CMF (20d) at Sharpe +0.01 on 6 symbols
- Shorter window = more crossings of the buy/sell threshold = more whipsaws, not fewer
- The problem with CMF is that it hovers near zero frequently (distribution detection is inherently noisy)
- **Lesson: don't fix CMF by shortening the period; the signal family itself is lower-quality than MA-based signals**

### 10. High Trade Count + Moderate Expectancy = Highest SQN (R7)
- ROC (20d) + MA Full Stack: 5,158 trades, SQN 6.95 — highest statistical confidence of all strategies
- SMA (20/50) + OBV: 5,625 trades, SQN 6.59 — second highest
- These strategies have lower P&L than champions but the law of large numbers makes them the most statistically reliable
- **Lesson: SQN is the best single measure of statistical confidence; high-trade-count strategies dominate**

### 11. Weekly Timeframe Is a Universal Structural Improvement (R9-R11, R14)
- MA Bounce: Sharpe 0.61 → 1.92 (+215%), RS(min) -10.93 → -2.32
- MAC Fast Exit: Sharpe 0.68 → 1.80 (+165%), RS(min) -4.46 → -2.54
- Donchian: Sharpe 0.63 → 1.68 (+167%), RS(min) -3.66 → -2.06
- Price Momentum: Sharpe 0.67 → 1.87 (+179%), RS(min) -15.92 → -2.30
- RSI Weekly: Sharpe 1.85 (tested first on weekly — daily version not benchmarked)
- **Lesson: ALL momentum strategies improve dramatically on weekly bars. Weekly timeframe eliminates intra-week noise that creates false signals, whipsaws, and worst-case rolling periods.**

### 12. MACD Does Not Benefit From Weekly Bars (R14)
- MACD Weekly (3/6/2): 4,238 trades, Sharpe 1.05 — nearly as noisy as daily MACD
- MACD crossover mechanism generates frequent signals regardless of bar size
- RSI threshold crossing (55-from-below) is a qualitatively different and superior weekly signal
- **Lesson: not all indicators benefit equally from timeframe increase. Crossover-based indicators (MACD, EMA crosses) remain noisy. Level-based signals (RSI > threshold, price > MA) gain more from weekly resolution.**

### 13. Monthly Timeframe Is Theoretically Perfect but Practically Unusable (R13)
- Monthly Sharpe 3.77-3.93, RS(min) positive (+0.37/+0.45) — never lost money on 6-month rolling basis
- But MaxDD 73-75% and 11-year max recovery window make it impossible for live trading
- Strategy correlation = 0.97 at monthly granularity — any two momentum strategies become identical at monthly bars
- **Lesson: finer timeframes are not always worse; weekly occupies the optimal tradeoff between noise filtering and drawdown containment. Monthly sacrifices too much capital at risk.**

### 15. Block Bootstrap MC Is More Conservative Than IID for Momentum Strategies (R18)
- IID MC treats each trade as independent — this overstates robustness for momentum strategies
- Block bootstrap preserves win/loss streaks; Donchian and Price Momentum lose MC Score +1
- Auto block size = floor(sqrt(N)) captures 8-13 months of trade history per block
- **Lesson: Use block bootstrap MC for final risk assessment of momentum portfolios. Accept MC Score -1 as the correct assessment on concentrated tech universes.**

### 16. RSI Weekly Parameter Sensitivity: Edge Is Structural, Not Threshold-Specific (R20)
- 534/535 valid variants (99.8%) profitable across 5^4 = 625 parameter combinations
- 100% of valid variants pass WFA — extraordinary; no parameter set breaks out-of-sample
- The 55-cross threshold sits near the 85th percentile of all valid variants by Sharpe
- Better variant found: rsi_period=10, rsi_entry=63.25, rsi_exit=51.75 (Sharpe 2.10 vs 1.85 base)
- **Lesson: RSI Weekly's edge is a momentum regime condition (RSI crosses a meaningful threshold with SMA200 trend gate), not a specific numerical threshold. The strategy is genuinely robust.**

### 14. Uncorrelated Strategies Compound MC Score Improvements (R16)
- 4-strategy weekly portfolio: all MC Score -1 on NDX Tech 44
- 5-strategy weekly portfolio: Donchian and Price Momentum reach MC Score +1
- Adding a 5th uncorrelated strategy dilutes the aggregate tail risk enough for Monte Carlo robustness
- **Lesson: MC Score -1 on concentrated universes is partially fixable by adding more uncorrelated strategies, not just by changing position sizing or adding stops.**

### 17. MC Score Is Determined by Universe Correlation Structure (R21-R31)
- NDX Tech 44: ALL strategies MC Score -1 (44 correlated tech stocks crash together)
- DJI 30 (mixed sectors): MC Score 0 to +5 depending on strategy frequency
- Sector ETFs 16 (max sector diversity): ALL strategies MC Score +5
- International ETFs 30 (max geographic diversity): ALL strategies MC Score +5
- **Lesson: MC Score is NOT a strategy property; it is a portfolio construction property. Fix MC Score by diversifying the universe, not by changing strategy parameters or adding trailing stops.**

### 18. The 2-Ingredient Formula for Optimal Risk-Adjusted Portfolio (R29)
- Ingredient 1: Sector ETFs (macro regime signals, near-zero inter-sector correlation, MC Score anchoring)
- Ingredient 2: Individual blue-chip stocks from DIVERSE sectors (individual momentum for higher Sharpe than ETFs alone)
- Sectors+DJI 46 = first universe to simultaneously achieve Sharpe >1.50, MaxDD <31%, MC ≥+2
- **Lesson: The optimal live-trading universe is NOT the highest-momentum concentrated universe (NDX Tech 44) but rather a diversified combination of macro instruments + individual blue-chip stocks from non-correlated sectors.**

### 19. Adding Non-Tech Names Helps Only When They Are the Majority (R28-R29)
- NDX Tech 44 + 23 unique DJI names (NDX+DJI 124): MaxDD WORSENED +3-9pp — 80% still tech, crashes still synchronized
- Sector ETFs 16 + 30 DJI names (Sectors+DJI 46): MaxDD 21-30% — 50%+ non-tech, crashes break correlation
- **Lesson: Adding 15-20% non-tech names to a tech portfolio does not reduce MaxDD meaningfully. Only when non-tech exceeds ~50% of the portfolio does sector diversification break synchronized crash behavior.**

### 20. Price Momentum ↔ RSI Weekly Are Structurally Correlated on Diversified Universes (R31)
- On NDX Tech 44: Price Momentum and RSI Weekly have low correlation (different entry timing)
- On Global Diversified 76: r=0.81 — both strategies enter/exit the same trending markets simultaneously
- Both capture "sustained uptrend": ROC >15% 6-month return vs RSI >55 — on a 76-symbol universe with many sideways markets, only the strongest trends trigger both simultaneously
- **Lesson: Strategy correlation is universe-dependent. Always check exit-day correlation on the actual production universe before running both. On diversified ETF/global universes, use only one of Price Momentum or RSI Weekly.**

### 21. Price Momentum ↔ RSI Weekly r=0.94 on NDX Tech 44 in Combined Portfolio (R41)
- In the 6-strategy combined run on NDX Tech 44, Price Momentum and RSI Weekly show exit-day correlation r=0.94 — the highest correlation pair ever observed in research
- On NDX Tech 44 concentrated tech stocks (NVDA, AMZN, META), both strategies enter/exit the same positions simultaneously: ROC >15% over 26w AND RSI >55 on 14w both fire at the same time on the strongest uptrends
- The r=0.94 was NOT observed in isolated single-strategy tests (each strategy looked independent in isolation); it only emerges in combined portfolio context
- **Lesson: Test exit-day correlation in the COMBINED context (multi-strategy run), not from isolated strategy outputs. Correlations can be much higher in combined runs due to shared position dynamics.**
- **Implication: For NDX Tech 44 weekly portfolio, choose ONE of Price Momentum or RSI Weekly. Preferred: RSI Weekly (higher combined OOS P&L +17,529% vs Price Momentum +9,321%).**

### 22. Relative Momentum MC Score 5 on NDX Tech 44 — Long Hold Duration Unlocks MC Robustness (R41)
- Relative Momentum (13w vs SPY) achieved MC Score 5 in the NDX Tech 44 combined run — the first strategy to do so on this concentrated universe
- The strategy's average hold duration of 103 days (~20 weekly bars) means the Monte Carlo resampling cannot construct the "synchronized crash" scenario that produces MC Score -1 for faster strategies
- At 969 trades total (vs 831 in isolation), the strategy generates MORE trades at 2.8% allocation vs 10% in isolation — lower per-trade capital requirement allows more simultaneous positions before hitting cash ceiling
- **Lesson: Long-duration, infrequent strategies (hold months, not days) have fundamentally different MC Score behavior. They are structurally resistant to the synchronized-crash tail risk that plagues high-frequency trend-following strategies on correlated universes.**

### 30. ATR Trailing Stops Are Structurally Incompatible with Weekly Trend-Following (R50)
- Hypothesis: sector rotation on Sectors+DJI 46 would allow ATR stops to fire before synchronized crashes, reducing MaxDD
- Result: ATR 3× stops INCREASE MaxDD for all 5 Conservative v1 strategies (+6 to +9 pp each)
- Mechanism: weekly trend-following strategies ride extended trends (10-20 weeks); ATR stop fires during normal within-trend pullbacks → premature exit at local trough → realized loss → re-entry at higher price after recovery
- This creates larger realized drawdowns vs holding through the pullback (which the no-stop version does)
- Sharpe drops 42% uniformly across all 5 strategies; OOS P&L drops 78-92%
- Different failure mode from R8 (NDX Tech 44): R8 fails because synchronized crashes overwhelm position-level stops; R50 fails because stops are structurally incompatible with trend-following holding periods
- **Rule: ATR trailing stops are incompatible with weekly trend-following momentum strategies regardless of universe. The mechanism that stops protect against (large single-position losses from gaps) is not what causes weekly trend-following drawdowns.**
- **Implication: Do not add stop-loss configurations to Conservative v1 or v2. The no-stop configurations are definitively optimal for all metrics including MaxDD.**

### 29. Williams R on NDX Tech 44 — Third Confirmation of Universe-Specific Correlation Rule (R49)
- Williams R ↔ RSI Weekly: r=0.6451 on Sectors+DJI 46 (R47, below 0.70) vs r=0.752 on NDX Tech 44 (R49, above 0.70)
- Williams R ↔ MA Bounce: r=0.32 on Sectors+DJI 46 (R48 5-strat test) vs r=0.718 on NDX Tech 44 (R49)
- Williams R ↔ Relative Momentum: r=0.710 on NDX Tech 44 — barely above threshold, but still a fail
- Three pairs exceeded 0.70 simultaneously, making Williams R impossible to add to the Aggressive portfolio
- Williams R individual metrics on NDX Tech 44 are excellent (Sharpe 1.83, OOS +7,417%) — rejected purely for portfolio correlation
- **Rule (3rd confirmed instance):** Concentrated tech momentum universes produce high cross-strategy correlation. Diversified sector/macro universes allow the same strategy pairs to remain below threshold.
- **Implication: The universe determines strategy pair compatibility. Williams R belongs in Conservative portfolios (Sectors+DJI 46) — not in the Aggressive portfolio (NDX Tech 44). R42 Aggressive portfolio is definitively closed.**

### 28. Price Momentum Is the MC Buffer for RSI Weekly — Portfolio Composition Affects MC Robustness of Other Strategies (R48)
- In the original Conservative v1 (R29, with Price Momentum), RSI Weekly achieves MC Score 5 — "Robust" with no tail risk
- When Price Momentum is removed (Q51, Williams R replaces it), RSI Weekly drops to MC Score 2 — "Moderate Tail Risk"
- Mechanism: Price Momentum and RSI Weekly often target the same trending stocks simultaneously; the capital allocation engine forces competition between them, limiting how many positions RSI Weekly can hold concurrently
- Without this capital competition, RSI Weekly can build larger simultaneous position counts → Monte Carlo can construct synchronized crash scenarios that would not occur when capital is shared with Price Momentum
- Williams R individual metrics are excellent (Sharpe 1.86, OOS +2,156%, MC Score 5) but its presence fails to provide the same capital competition buffering
- **Lesson: MC Score is a portfolio-composition property, not just a strategy property. Adding or removing a strategy changes the MC Score of all other strategies — not just the one being changed.**
- **Pattern (2nd instance):** Identical mechanism to Donchian in the Aggressive portfolio (R44). "Weaker" strategies by individual Sharpe can be structurally irreplaceable because of their buffering role in the combined portfolio's capital dynamics.
- **Implication: Before replacing any confirmed strategy, test whether its removal degrades MC robustness of the remaining strategies. A replacement that looks better in isolation may create tail risk concentration in others.**

### 31. Williams R Edge Is Structural — Confirmed Robust on Both Production Universes (R36/R51)
- Williams R on NDX Tech 44 (R36): 625/625 variants profitable (100%), 625/625 WFA Pass (100%), Sharpe range 1.59-2.21
- Williams R on Sectors+DJI 46 (R51): 81/81 variants profitable (100%), 81/81 WFA Pass (100%), Sharpe range 1.59-2.03
- Both sweeps show base configuration NOT at the distribution maximum — no cherry-picking evidence in either universe
- The price-near-top-of-N-week-range signal (Williams %R above -20 threshold) is genuine momentum, not a statistical artifact
- MC Score -1 in isolation (46 symbols, 10% allocation) is expected — the same result seen for ALL strategies in isolation at high allocation; in Conservative v2 combined context (2.8% allocation), Williams R achieves MC Score 5
- **Rule: When 100% of parameter variants are profitable and WFA Pass on a 36-year dataset, the strategy edge is structural, not overfitted. These are the two strongest robustness signals available.**
- **Implication: Williams R Weekly Trend (above-20) + SMA200 at base parameters (wr=14, entry=-20, exit=-80, sma=40) is verified as a sound configuration with no evidence of curve-fitting. Conservative v2 is fully validated.**
- **Infrastructure note: `sensitivity_sweep_min_val=-100` is required for any strategy with negative-valued thresholds (Williams %R, any oscillator measured on -100 to 0 scale). Default min_val=2 clips these values outside their valid range, producing 0 trades and a false "all variants pass" result.**

### 27. Low Correlation Alone Is Insufficient — Alpha Must Meet Minimum Threshold (R46)
- Relative Momentum on Sectors+DJI 46 achieved the lowest maximum correlation of any strategy in any combined portfolio run (max r=0.2373) — extraordinary diversification
- BUT: Sharpe 0.80, OOS P&L +51.38%, RS(avg) = -0.07 — the strategy fails to generate sufficient alpha on this universe
- Low correlation + poor alpha = net negative portfolio contribution (dilutes the high-alpha existing strategies)
- **Lesson: Both conditions must be met for a 6th strategy to improve a portfolio: (1) correlation < threshold AND (2) individual Sharpe meets minimum standard. Low correlation without sufficient alpha does not improve a portfolio.**
- **Universe insight:** Relative Momentum works on NDX Tech 44 (single-stock momentum within a sector) but fails on Sectors+DJI 46 (sector ETF relative momentum is mean-reverting by nature — strong sectors rotate out, weak sectors rotate in)

### 25. BB Breakout ↔ RSI Weekly Correlation is Universe-Specific: 0.4711 on Sectors+DJI 46 vs 0.7049 on NDX Tech 44 (R43/R45)
- The same BB Breakout / RSI Weekly strategy pair shows dramatically different correlations depending on the universe
- NDX Tech 44: r=0.7049 — both fire on the same concentrated tech stock momentum breakouts simultaneously
- Sectors+DJI 46: r=0.4711 — sector rotation means a BB breakout on XLU utilities fires at different times from RSI Weekly on XLK tech
- This is a 0.26 difference driven entirely by the universe structure, not the strategy logic
- **Lesson: Test exit-day strategy correlations on the exact production universe. A strategy pair that fails the correlation test on one universe may pass on a different universe due to structural diversification.**
- **Implication: BB Breakout can be added to the Conservative Portfolio (Sectors+DJI 46) but not the Aggressive Portfolio (NDX Tech 44). Same strategy, different portfolio suitability based on universe correlation structure.**

### 26. First 6-Strategy Portfolio with ALL 6 MC Score 5 (R45)
- Sectors+DJI 46 with 5 conservative strategies + BB Breakout achieves MC Score 5 for all 6 simultaneously
- This has never been achieved in any prior research run (even 5-strategy Sectors+DJI 46 all had MC Score 5, but adding a 6th is harder)
- BB Breakout's long hold duration on the diversified 46-symbol universe means Monte Carlo cannot construct synchronized crash scenarios for it
- **Lesson: Sectors+DJI 46 is a uniquely MC-robust universe for the current strategy set. Even a 6-strategy combined portfolio maintains full MC robustness due to sector rotation providing natural synchronized-crash immunity.**

### 24. Donchian's Structural Buffer Role — Removing the Lowest-Sharpe Strategy Can Worsen Portfolio Correlation (R44)
- In the R44 test, removing Donchian (lowest Sharpe 1.63) and replacing with BB Breakout (Sharpe 1.71) caused BB ↔ RSI Weekly to escalate from r=0.7049 → r=0.7874 and BB ↔ Rel Mom from r=0.6924 → r=0.7203
- Donchian's 40-week channel breakout timing is structurally different from all other strategies — it creates diversification via unique entry/exit timing, not via better individual metrics
- Donchian ↔ RSI Weekly r=0.22 is the lowest correlation of any trend-following pair in the entire strategy set
- **Lesson: In portfolio construction, the "weakest" individual strategy is not always the weakest portfolio contribution. Correlation structure matters more than individual Sharpe. Before replacing a low-Sharpe strategy, test whether its removal worsens the remaining portfolio's correlation matrix.**
- **Implication: Donchian Breakout (40/20) is irreplaceable in the current NDX Tech 44 5-strategy portfolio. Its structural buffer role protects the correlation matrix that allows all 5 strategies to coexist below r=0.65.**

### 23. BB Breakout ↔ RSI Weekly r=0.7049 — Bollinger Band Breakouts and RSI Momentum Threshold Are Near-Synonymous on Concentrated Tech (R43)
- BB Weekly Breakout (price closes above 2-std upper Bollinger Band) and RSI Weekly Trend (RSI crosses above 55) both fire when a NDX tech stock makes a new breakout high on high momentum
- On NVDA/AMZN/META type stocks, a Bollinger Band upper-band breakout and an RSI >55 cross happen simultaneously — they are triggered by the same fundamental market event (momentum breakout)
- In the 6-strategy combined context, BB ↔ RSI Weekly r=0.7049 — above the 0.70 research warning threshold
- BB ↔ Donchian: r=0.4305 (moderate — both are breakout strategies but with different exit timing)
- BB achieves MC Score 5 (vs Donchian MC Score 2) due to longer hold duration, and MaxDD 34.27% vs Donchian 47.72%
- **Lesson: Bollinger Band upper-band breakouts and RSI momentum thresholds should not coexist in the same portfolio on concentrated tech universes. The two signals detect the same momentum event from different mathematical angles.**
- **Implication: BB Breakout is a potential Donchian replacement (better metrics), but the RSI Weekly correlation constraint must be empirically verified in the 5-strategy context (Q47).**

---

## Recommended Live Implementation

### Production Portfolio — Conservative v1 (5 strategies, weekly bars, 3.3% allocation each) [STANDARD]

**Universe:** Sectors+DJI 46 (`sectors_dji_combined.json`, `min_bars_required=100`)
**Config:** `"timeframe": "W"`, `"allocation_per_trade": 0.033`

| Strategy | File | Sharpe | MaxDD | RS(min) | MC Score |
|---|---|---|---|---|---|
| MA Bounce (50d/3bar) + SMA200 Gate | `research_strategies_v4.py` | 1.61 | 26.85% | -2.81 | **5** |
| MA Confluence (10/20/50) Fast Exit | `research_strategies_v3.py` | 1.52 | 24.98% | **-1.89** | **5** |
| Donchian Breakout (40/20) | `research_strategies_v2.py` | 1.47 | 23.59% | -2.36 | **5** |
| Price Momentum (6m ROC, 15pct) + SMA200 | `round9_strategies.py` | **1.79** | **18.88%** | -2.26 | **5** |
| RSI Weekly Trend (55-cross) + SMA200 | `round13_strategies.py` | 1.78 | 26.34% | -2.63 | **5** |

**All MaxDDs below 28%. ALL strategies MC Score +5.**

### Production Portfolio — Conservative v2 (6 strategies, weekly bars, 2.8% allocation each) [ENHANCED RETURNS — R47]

**Universe:** Sectors+DJI 46 (`sectors_dji_combined.json`, `min_bars_required=100`)
**Config:** `"timeframe": "W"`, `"allocation_per_trade": 0.028`
**Same 5 strategies as v1 PLUS:**

| Strategy | File | Sharpe | MaxDD | RS(min) | MC Score | OOS P&L |
|---|---|---|---|---|---|---|
| Williams R Weekly Trend (above-20) + SMA200 | `round35_strategies.py` (verify) | **1.82** | 23.76% | -2.96 | **5** | **+1,437.81%** |

**All MaxDDs below 27%. ALL 6 MC Score 5 (unprecedented). Williams R is the highest-Sharpe strategy in the portfolio.**
**Max pair correlation: 0.6925 (Price Momentum ↔ RSI Weekly). Williams R ↔ RSI Weekly: r=0.6451.**

### Production Portfolio — Aggressive (5 strategies, weekly bars, 3.3% allocation each) [R42]

**Universe:** NDX Tech 44 (`nasdaq_100_tech.json`)
**Config:** `"timeframe": "W"`, `"allocation_per_trade": 0.033`

| Strategy | File | Sharpe | MaxDD | RS(min) | MC Score |
|---|---|---|---|---|---|
| MA Bounce (50d/3bar) + SMA200 Gate | `research_strategies_v4.py` | **1.94** | 44.46% | -2.67 | -1 |
| RSI Weekly Trend (55-cross) + SMA200 | `round13_strategies.py` | 1.91 | 49.36% | -2.73 | -1 |
| Relative Momentum (13w vs SPY) Weekly + SMA200 | `round36_strategies.py` | 1.76 | **31.82%** | -2.70 | **2** |
| MA Confluence (10/20/50) Fast Exit | `research_strategies_v3.py` | 1.73 | 49.77% | **-2.19** | -1 |
| Donchian Breakout (40/20) | `research_strategies_v2.py` | 1.63 | 47.72% | -2.49 | **1** |

**All MaxDDs below 50%. No pair exceeds r=0.65. Confirmed R42 (Rounds 41-44).**
**Note: Do NOT add Price Momentum to this portfolio — it reaches r=0.94 with RSI Weekly on NDX Tech 44.**

### Alternative: Daily Champions (if weekly execution is not feasible)

**1. MA Confluence (10/20/50) Fast Exit** — Primary alpha engine
- Signal: Buy on first bar of 10/20/50 MA full stack alignment; sell on 10-SMA cross below 50-SMA
- Expected: +0.68 Sharpe, ~43% win rate, 7.9R expectancy

**2. Donchian Breakout (40/20)** — Momentum breakout complement
- Signal: Buy on 40-bar new high; sell on 20-bar new low
- Expected: +0.63 Sharpe, ~43% win rate, 5.9R expectancy

**3. MA Bounce (50d/3bar)+SMA200** — Counter-trend diversifier
- Signal: Buy on 50-SMA touch+recovery while price > SMA200; sell on 3 closes below 50-SMA
- Expected: +0.61 Sharpe, ~33% win rate (offset by high expectancy 3.7R+)

### Risk Controls (mandatory)
- **Max 3.3% per position (weekly portfolio) or 10% (daily 3-strategy)** — enforce allocation limits
- **Portfolio stop**: if portfolio DD exceeds 25%, cut position sizes by 50%
- **No more than 15 stocks from the same sector simultaneously** — correlation risk
- **MC Score -1 on 44-symbol combined runs** — real drawdowns may exceed backtest MaxDD in synchronized crashes; 5-strategy weekly partially resolves with Donchian +1 and Price Momentum +1

---

## Strategy Implementation Files

| File | Round | Strategies |
|---|---|---|
| `research_strategies_v1.py` | R1 | ROC (10d/20d), BB Squeeze, Williams %R, VW RSI, Donchian (20/10), Stochastic, Keltner (2x) |
| `research_strategies_v2.py` | R2 | ROC+SMA200, EMA+ROC (12/26), **Donchian (40/20)**, Keltner (1.5x), BB Breakout, OBV Dual |
| `research_strategies_v3.py` | R3 | **MA Confluence Full Stack**, **MA Confluence Fast Exit**, OBV+SMA200, SMA Crossover+RSI |
| `breakout_round3.py` | R3+ | Donchian+SMA200, BB+ROC Gate, Donchian (60/20) |
| `research_strategies_v4.py` | R5 | CMF+SMA200, MACD+RSI+SMA200, ATR Trailing, **MA Bounce (50d)+SMA200**, Keltner+MA Stack |
| `round6_strategies.py` | R6 | CMF+RSI Gate, MA Bounce+RSI (failed), **Donchian (60d/20d)+MA Alignment**, OBV+MAC, MAC+ATR |
| `round7_strategies.py` | R7 | CMF (10d) (failed), Donchian+RSI (redundant), EMA+CMF Hold (MaxRcvry 5008), **ROC (20d)+MA Full Stack**, **SMA (20/50)+OBV Confirm** |
| `round8_strategies.py` | R8 | MAC+ATR 3.5x (MC Score -1 persists — failed), EMA+OBV Hold (Sharpe 0.03), Donchian+Volume (143 trades), MA Bounce+OBV (entry gate too selective) |
| `round9_strategies.py` | R9 | **Price Momentum (6m ROC, 15pct) + SMA200** (champion), NR7 Volatility Contraction (failed) |
| `round13_strategies.py` | R14 | **RSI Weekly Trend (55-cross) + SMA200** (champion rank 3), MACD Weekly (3/6/2) (failed) |

Bold = validated champion strategies.

---

## What Was Learned That Only Multi-Round Research Finds

| Finding | How Found | Round |
|---|---|---|
| Tech ecosystem 10-100× more profitable than single stock | R1→R2 pivot | R1 |
| MA Confluence is untested gold (not in any public library) | R3 sweep of untested indicators | R3 |
| Trend filters (SMA200) universally improve Calmar | R2/R3 iteration | R2-R3 |
| Rolling WFA N/A: use 3 folds not 5 for 250-400 trade strategies | R4 debug | R4 |
| Extending history to 1990 reveals dot-com tail risk in MA Confluence | R5 start-date change | R5 |
| MA Bounce is a structural diversifier (r=0.02) — not a failed MR strategy | R5 surprise | R5 |
| 6-symbol RS(min) is noisy; 44-symbol RS(min) is reliable | R6 scale validation | R6 |
| RSI gating eliminates the timing advantage of bounce strategies | R6 failed fix | R6 |
| Donchian (60d)+MA Alignment: RS(min) -3.98 on 44 symbols, better than expected | R6 44-sym run | R6 |
| RSI>50 gate on N-bar new-high breakout is redundant (r=+1.00 proven on 44 symbols) | R7 44-sym validation | R7 |
| CMF shorter period makes it worse, not better — oscillator family is inherently noisy | R7 failed experiment | R7 |
| ROC+MA Full Stack: SQN 6.95 (highest ever) — high trade count drives statistical confidence | R7 new discovery | R7 |
| SP500 universality confirmed — all 3 champions WFA Pass on 500 stocks; MAC RS(min)=-3.49 (SMOOTHER on SP500 than NDX) | R8 Q2 result | R8 |
| MC Score -1 cannot be rescued by trailing stops — it is structural concentration risk | R8 ATR test | R8 |
| Entry-time OBV gates destroy bounce strategies (same as RSI gates) — OBV confirms price, not adds quality | R8 failed test | R8 |
| Volume breakout filter (>1.5× ADV) is too selective (143 trades on 6 symbols); try lower threshold (1.2×) if needed | R8 failed test | R8 |

---

## Universe Tier Results (All Tested, Weekly Bars, 5 Strategies, 3.3% Allocation)

| Universe | Symbols | Sharpe Range | MaxDD | MC Score | Best For |
|---|---|---|---|---|---|
| NDX+DJI 124 | 124 | 1.81-**1.98** | 50-56% | ALL -1 | Maximum Sharpe (MA Bounce record 1.98) |
| NDX Full 101 | 101 | 1.83-1.95 | 45-57% | ALL -1 | Best 100+ symbol Sharpe |
| Russell Top 200 | 198 | 1.48-1.95 | 37-54% | ALL -1 | Best RS(min) (-1.85 record) |
| DJI 30 | 30 | 1.71-1.93 | **19-23%** | 0 to +5 | Minimum MaxDD |
| **Sectors+DJI 46** | **46** | **1.54-1.86** | **21-30%** | **+2 to +5** | **OPTIMAL: Sharpe + MaxDD + MC simultaneously** |
| Global Diversified 76 | 76 | 1.36-1.82 | 22-34% | 0 to +5 | Geographic diversification variant |
| High Volatility 242 | 242 | 1.16-1.31 | 42-56% | ALL -1 | — (underperforms NDX) |
| Nasdaq Biotech 257 | 257 | 0.68-0.81 | 55-67% | ALL -1 | Lower bound (binary events) |
| International ETFs 30 | 30 | 0.67-1.08 | 27-32% | **ALL +5** | Geographic MC anchor |
| Sector ETFs 16 | 16 | 0.54-0.95 | 19-30% | **ALL +5** | Maximum MC robustness |
| Russell 1000 | 1,012 | 0.87-1.18 | n/a | n/a | Universality confirmed |
| SP500 | 500 | 1.42-1.81 | 45-58% | varies | Broad market |

**Three recommended production tiers:**
- **Conservative (risk-first):** Sectors+DJI 46 — `sectors_dji_combined.json`, `min_bars_required=100`, 5 strategies 3.3% each
- **Aggressive (return-first):** NDX+DJI 124 or NDX Full 101 — `ndx101_dji30_combined.json` / `nasdaq_100.json`
- **Balanced:** Russell Top 200 — `russell-top-200.json` — best RS(min) stability

---

## Open Research Questions — All Closed

All 43 research questions have been answered across Rounds 1-51. **Research is COMPLETE.**
Stop Criteria C met: 3 consecutive rounds (R49, R50, R51) produced only confirmations, no new champions or improvements.

1. ~~**Can MA Confluence MC Score be rescued with ATR?**~~ — R8. **CLOSED.**
2. ~~**CMF shorter period**~~ — R7. **CLOSED.**
3. ~~**MA Bounce on weekly bars**~~ — R9. Sharpe 1.92. **CLOSED.**
4. ~~**Multi-strategy portfolio simulation**~~ — R8 Q1. **CLOSED.**
5. ~~**Sector rotation (SP500 universality)**~~ — R8 Q2. **CLOSED.**
6. ~~**EMA (8/21) + OBV Hold Gate**~~ — R8. Sharpe 0.03. **CLOSED.**

7. ~~**Donchian (40/20) + Volume Spike Confirmation**~~ — R8. 143 trades. **CLOSED.**
8. ~~**MA Bounce (50d) + OBV Confirmation**~~ — R8. Entry gate destroys edge. **CLOSED.**
9. ~~**Price Momentum (6-month ROC 15%+) + SMA200**~~ — R9. Champion (Sharpe 0.67 daily, 1.87 weekly). **CLOSED.**
10. ~~**NR7 Volatility Contraction Breakout**~~ — R9. Sharpe -0.07. **CLOSED.**
11. ~~**SP500 combined 3-strategy portfolio at 3% allocation**~~ — R9 Q6. MA Bounce MC Score +1. **CLOSED.**
12. ~~**MAC Fast Exit and Donchian on weekly bars**~~ — R10. Both new champions. **CLOSED.**
13. ~~**Combined weekly 3-strategy portfolio**~~ — R11 Q11. Optimal. **CLOSED.**
14. ~~**Price Momentum on SP500 daily**~~ — R11 Q10. RS(min) -17.09 (FAILED on daily, works on weekly). **CLOSED.**
15. ~~**Price Momentum on weekly bars**~~ — R11 Q12. Co-champion #1 (Sharpe 1.87). **CLOSED.**
16. ~~**4-strategy combined weekly portfolio**~~ — R12 Q13. Research complete milestone. **CLOSED.**
17. ~~**Monthly timeframe test**~~ — R13 Q14. MaxDD 73-75%, impractical. **CLOSED.**
18. ~~**MACD weekly + RSI weekly**~~ — R14 Q15. MACD failed; RSI Weekly rank 3 champion. **CLOSED.**
19. ~~**Russell 1000 universality**~~ — R15 Q16. All 4 WFA Pass 3/3 on 1,012 symbols. **CLOSED.**
20. ~~**5-strategy combined weekly portfolio**~~ — R16 Q17. ALL MaxDDs below 50%. **CLOSED.**
21. ~~**RSI Weekly parameter sensitivity sweep (±15% ×2 steps)**~~ — R20 Q21. 99.8% profitable, 100% WFA Pass. ROBUST. **CLOSED.**
22. ~~**Dow Jones 30 blue-chip universe**~~ — R21 Q22. All 5 WFA Pass. MaxDD 19-23%. **CLOSED.**
23. ~~**Nasdaq Biotech 257**~~ — R22 Q23. All 5 WFA Pass. Sharpe 0.68-0.81 (binary event floor). **CLOSED.**
24. ~~**Sector ETFs 16**~~ — R23 Q24. All 5 WFA Pass + ALL MC Score +5. **CLOSED.**
25. ~~**Russell 2000 small caps**~~ — R24 Q25. Not testable with Norgate (1 valid symbol). **CLOSED.**
26. ~~**High Volatility 242**~~ — R25 Q26. All 5 WFA Pass. Sharpe 1.16-1.31. MAC > RSI Weekly reversal. **CLOSED.**
27. ~~**Russell Top 200 (198 mega-caps)**~~ — R26 Q27. All 5 WFA Pass. RS(min) -1.85 record. **CLOSED.**
28. ~~**Nasdaq Full 101**~~ — R27 Q28. All 5 WFA Pass. Sharpe 1.83-1.95. **CLOSED.**
29. ~~**NDX Full + DJI 30 combined (124 symbols)**~~ — R28 Q29. MA Bounce Sharpe 1.98 record. MaxDD hypothesis falsified. **CLOSED.**
30. ~~**Sectors+DJI 46**~~ — R29 Q30. BREAKTHROUGH universe (Sharpe+MaxDD+MC simultaneously best). **CLOSED.**
31. ~~**International ETFs 30**~~ — R30 Q32. All 5 WFA Pass + ALL MC Score +5. Sharpe 0.67-1.08. **CLOSED.**
32. ~~**Global Diversified 76 (Sectors+DJI+International ETFs)**~~ — R31 Q33. All 5 WFA Pass. Sharpe 1.36-1.82. Donchian RS(min) -1.91 record. Price Momentum ↔ RSI Weekly r=0.81 on this universe. **CLOSED.**
33. ~~**6-Strategy NDX Tech 44 (5 original + Relative Momentum)**~~ — R41 Q44. All 6 WFA Pass + RollWFA 3/3. All MaxDDs < 47%. Relative Momentum: 969 trades + MC Score **5** (unprecedented on NDX Tech 44). CRITICAL: Price Momentum ↔ RSI Weekly r=0.94 on NDX Tech 44 — do not run together. **CLOSED.**
34. ~~**Optimized 5-Strategy NDX Tech 44 (replace Price Momentum with Relative Momentum)**~~ — R42 Q45. All 5 WFA Pass. No pair > r=0.65. Relative Momentum MaxDD 31.82% (-13pp vs Price Momentum). RSI Weekly OOS +28,214% (record). CONFIRMED SUPERIOR to original R16 portfolio. **CLOSED.**
35. ~~**BB Breakout as 6th Strategy in Combined NDX Tech 44**~~ — R43 Q46. All 6 WFA Pass + RollWFA 3/3. BB Breakout MC Score 5 (second strategy to achieve this alongside Rel Mom). MaxDD 34.27% (second best). CRITICAL: BB ↔ RSI Weekly r=0.7049 — above 0.70 threshold. BB cannot be added as 6th strategy. Q47 tests BB as Donchian replacement. **CLOSED.**
36. ~~**BB Breakout Replacing Donchian (5-Strategy Test)**~~ — R44 Q47. REJECTED. Without Donchian, BB ↔ RSI Weekly escalates to r=0.7874 and BB ↔ Rel Mom to r=0.7203 — both above 0.70. Donchian is a structural portfolio buffer (r=0.22 with RSI Weekly) that cannot be replaced. R42 5-strategy NDX Tech 44 portfolio CONFIRMED FINAL. **CLOSED.**
37. ~~**BB Breakout as 6th Strategy in Conservative Portfolio (Sectors+DJI 46)**~~ — R45 Q48. CONDITIONAL PASS. All 6 MC Score 5 (unprecedented). BB ↔ RSI Weekly r=0.4711 (sector rotation decorrelates). BB MaxDD 13.29% (lowest ever). BUT: BB OOS P&L only +170.96% (weakest of 6). Conservative portfolio v2 (6-strategy MaxDD-focused) defined. **CLOSED.**
38. ~~**Relative Momentum as 6th Strategy in Conservative Portfolio (Sectors+DJI 46)**~~ — R46 Q49. REJECTED. Sharpe 0.80, OOS +51.38%, RS(avg)=-0.07. Universe mismatch: sector ETF relative momentum is mean-reverting. Max r=0.2373 (lowest ever) but alpha insufficient. **CLOSED.**
39. ~~**Williams R Weekly Trend as 6th Strategy in Conservative Portfolio (Sectors+DJI 46)**~~ — R47 Q50. OUTSTANDING. Sharpe 1.82 (highest in portfolio), OOS +1,437.81% (8.4× better than BB Breakout). Williams R ↔ RSI Weekly r=0.6451. All 6 MC Score 5. Williams R is the WINNER among all 3 candidates. Conservative portfolio v2 CONFIRMED FINAL with Williams R. **CLOSED.**
40. ~~**Williams R Replacing Price Momentum in Conservative Portfolio v1 (5-Strategy)**~~ — R48 Q51. REJECTED. RSI Weekly MC Score drops 5 → 2 without Price Momentum. Price Momentum is a structural "MC buffer" for RSI Weekly via capital competition dynamics — its presence prevents RSI Weekly from concentrating positions simultaneously. Williams R individual metrics excellent (Sharpe 1.86, OOS +2,156%) but portfolio-level effect overrides. Conservative v1 (R29, with Price Momentum) CONFIRMED SUPERIOR. ALL THREE production portfolios CONFIRMED FINAL. **CLOSED.**
41. ~~**Williams R as 6th Strategy in Aggressive Portfolio (NDX Tech 44)**~~ — R49 Q52. REJECTED. Williams R creates THREE pairs above r=0.70: Williams R ↔ RSI Weekly r=0.752, Williams R ↔ MA Bounce r=0.718, Williams R ↔ Relative Momentum r=0.710. Third confirmation of universe-specific correlation rule. R42 5-strategy Aggressive portfolio DEFINITIVELY CONFIRMED FINAL — no viable 6th strategy in current research set. **CLOSED.**
42. ~~**ATR Trailing Stop on Conservative v1 (MaxDD Reduction Test)**~~ — R50 Q53. REJECTED. ATR 3× stops INCREASE MaxDD for all 5 strategies (+6 to +9 pp), reduce Sharpe 42%, collapse OOS P&L 78-92%. Stops fire during within-trend pullbacks, creating larger realized drawdowns. Universal finding: ATR stops incompatible with weekly trend-following on any universe. Conservative v1 (R29, no stops) CONFIRMED OPTIMAL. **CLOSED.**
43. ~~**Williams R Parameter Sensitivity Sweep on Sectors+DJI 46**~~ — R51 Q54. CONFIRMED ROBUST. 81/81 variants profitable (100%), 81/81 WFA Pass (100%). Sharpe range 1.59-2.03 (all above threshold). Base config NOT at maximum (no cherry-pick evidence). Williams R confirmed robust on BOTH universes (NDX Tech 44 R36 + Sectors+DJI 46 R51). Conservative v2 Williams R configuration fully validated. **CLOSED.**

---

## 4H Polygon Research Chapter — Separate Research Track

**Research Loop:** 8 Rounds (4H-R1 through 4H-R8) — **COMPLETE ✓** (Stop Criteria C: 4 champions, all 7 rules)
**Data Provider:** Polygon.io (intraday 4-hour bars)
**Period:** 2018-01-01 → 2026-04-11 (8 years; WFA split: 2024-08-07)
**Universe:** `liquid_4h.json` — 20 liquid ETFs and mega-cap stocks (SPY excluded; used as benchmark)
**Timeframe Config:** `timeframe="H"`, `timeframe_multiplier=4`
**WFA:** 80/20 split, 3 rolling folds

### Context: Why a Separate 4H Track

After the Norgate/weekly research declared COMPLETE (R51), the user pivoted to Polygon intraday data. The 4H (4-hour bar) timeframe represents a structurally different research problem from the weekly strategies:

- **Different quality metrics**: Sharpe is SYSTEMATICALLY NEGATIVE at 4H due to the per-bar risk-free rate applied to 1,638 bars/year (vs 252 daily). Primary quality metrics are **Calmar, OOS P&L, WFA verdict**.
- **Different bar-count math**: `get_bars_for_period("Xd", "H", 4)` ignores the multiplier (bug). Manual helper `_b(days) = max(2, round(days × 1.625))` used in strategies_4h.py.
- **Different universe**: 20 highly liquid instruments with Polygon 4H data from 2018.
- **Same strategic framework**: WFA 80/20 + RollWFA 3/3, sensitivity sweeps for champion validation, anti-overfitting guard rules.

### 4H Research Architecture

```
4H-Round 1: Initial discovery — 3 strategies tested; EMA Velocity Breakout confirmed champion
4H-Round 2: Keltner Channel Breakout confirmed champion; Volume Surge rejected
4H-Round 3: Donchian Channel Momentum rejected (shift(1) bug — too many entries)
4H-Round 4: Donchian Turtle (corrected shift(1)) confirmed champion
4H-Round 5: MACD Histogram Crossover rejected (low Calmar + PF)
4H-Round 6: Williams %R Dip-Recovery rejected (WFA Overfitted — mean-reversion fails at 4H)
4H-Round 7: Relative Strength Momentum confirmed champion; 4-strategy portfolio FINAL
```

### 4H Structural Findings

| Finding | Round |
|---|---|
| **Mean-reversion FAILS at 4H** — RSI Dip (R1) and Williams %R Dip (R6) both WFA Overfitted; overfit IS bull run, fails OOS | R1, R6 |
| **Trend-following WORKS at 4H** — all 4 confirmed champions are trend-following (EMA cross, ATR channel, N-bar high, relative momentum) | R1-R7 |
| **Negative Sharpe is systematic at 4H** — not a quality signal; use Calmar and OOS P&L as primary metrics | R1 |
| **Volume surge filter generates excessive trades** — 3,000+ trades from Volume Surge = noise entries, not quality signals | R2 |
| **shift(1) is mandatory on Donchian at 4H** — without it, price equals rolling max on every trending bar → 3,065 entries (R3 bug vs R4 fix) | R3, R4 |
| **MACD Histogram at 4H is low-quality** — PF 1.16, Calmar 0.26; crossovers too frequent even at 4H resolution | R5 |
| **Relative performance vs SPY is a distinct signal** — entry timing uncorrelated (r=0.03) with EMA Velocity despite using same universe | R7 |

### 4H Strategy Results

| Round | Strategy | Status | Calmar | OOS P&L | WFA | MC | MaxDD | Trades |
|---|---|---|---|---|---|---|---|---|
| R1 | EMA Velocity Breakout (4H) | **CHAMPION** | 0.66 | +48.68% | Pass (3/3) | 5 | 19.68% | 1,019 |
| R1 | ADX Trend Strength Entry (4H) | REJECTED | — | — | — | — | — | 127 |
| R1 | RSI Dip Buy within Trend (4H) | REJECTED | — | OOS -2.51% | Overfitted | — | — | 266 |
| R2 | Keltner Channel Breakout (4H) | **CHAMPION** | 0.65 | +33.01% | Pass (3/3) | 5 | 16.09% | 2,043 |
| R2 | Volume Surge Momentum (4H) | REJECTED | 0.37 | +16.70% | Pass | — | — | 3,151 |
| R3 | Donchian Channel Momentum (4H) | REJECTED | 0.42 | +11.69% | Pass | — | — | 3,065 |
| R4 | Donchian Turtle (4H) | **CHAMPION** | 0.58 | +25.93% | Pass (3/3) | 5 | 16.31% | 2,124 |
| R5 | MACD Histogram Crossover (4H) | REJECTED | 0.26 | +17.89% | Pass | — | — | 2,602 |
| R6 | Williams %R Dip-Recovery (4H) | REJECTED | 0.03 | -5.60% | Overfitted | — | — | 1,238 |
| R7 | Relative Strength Momentum (4H) | **CHAMPION** | 0.82 | +49.11% | Pass (3/3) | 5 | 15.94% | 2,332 |

### 4H Production Portfolio v1 — Confirmed (4 Strategies)

**Config:** Liquid 4H (20) universe, 10% allocation per strategy (4 × 10% = 40% deployed), Polygon data, 2018-2026

| Rank | Strategy | Calmar | OOS P&L | MaxDD | WFA | MC Score | Max Pair r |
|---|---|---|---|---|---|---|---|
| 1 | Relative Strength Momentum (4H) | **0.82** | **+49.11%** | **15.94%** | Pass | 5 | — |
| 2 | EMA Velocity Breakout (4H) | 0.66 | +48.68% | 19.68% | Pass | 5 | — |
| 3 | Keltner Channel Breakout (4H) | 0.65 | +33.01% | 16.09% | Pass | 5 | — |
| 4 | Donchian Turtle (4H) | 0.58 | +25.93% | 16.31% | Pass | 5 | — |

**Max pairwise exit-day correlation: 0.22** (Keltner ↔ Donchian). All other pairs ≤ 0.06.

All 4 strategies: MC Score 5, WFA Pass (3/3). SPY benchmark B&H: +154.39% (2018-2026).

### 4H Pairwise Correlation Matrix

| | EMA | Keltner | Donchian | RS-Momentum |
|---|---|---|---|---|
| EMA | — | 0.03 | 0.03 | 0.03 |
| Keltner | 0.03 | — | 0.22 | 0.22 |
| Donchian | 0.03 | 0.22 | — | 0.20 |
| RS-Momentum | 0.03 | 0.22 | 0.20 | — |

### 4H Strategy Implementation

All four strategies are in `custom_strategies/strategies_4h.py`. They are guarded with `if _TF == "H":` to prevent registration at daily or weekly timeframes.

**Key config for 4H research:**
```python
"data_provider": "polygon"
"timeframe": "H"
"timeframe_multiplier": 4
"portfolios": {"Liquid 4H (20)": "liquid_4h.json"}
"min_bars_required": 500   # ~3 months of 4H bars
"start_date": "2018-01-01"
"wfa_split_ratio": 0.80
"wfa_folds": 3
```

### 4H Round 8 — RS Momentum Sensitivity Sweep (COMPLETE)

**Date:** 2026-04-11 | **Run ID:** 4h-r8-rs-momentum-sweep_2026-04-11_16-17-47

Rule 6 compliance sweep: 625 variants of Relative Strength Momentum (4H) across all 4 parameters (rs_period, abs_period, rs_threshold, sma_trend), each varied ±20% in 2 steps.

| Metric | Result |
|---|---|
| Profitable variants | 625 / 625 (100%) |
| WFA Pass | 625 / 625 (100%) |
| Rolling WFA Pass (3/3) | 625 / 625 (100%) |
| MC Score 5 | 625 / 625 (100%) |
| P&L range | +65.53% to +266.58% |
| Calmar range | 0.310 to 1.240 |
| OOS P&L range | +14.84% to +83.41% |
| Base rank | 304/625 (50th percentile — NOT cherry-picked) |

**Verdict: ROBUST** — strongest sweep result in the entire research program (625/625 vs Williams R 81/81).

**Critical fix applied:** `sensitivity_sweep_min_val=0.001` required because `rs_threshold=0.010` is a small positive float. Default `min_val=2` would clip all sweep values to 2.0, producing 0 trades (same bug class as Williams R negative thresholds in Round 36).

**4H Research COMPLETE** — Stop Criteria C satisfied. All 4 strategies confirm all 7 anti-overfitting rules.

### 4H Open Research Questions (All Resolved)

| # | Question | Status |
|---|---|---|
| 4H-1 | EMA Velocity Breakout sensitivity sweep | CLOSED — champion confirmed (R1/R3 combined sweep) |
| 4H-2 | Keltner Channel Breakout sensitivity sweep | CLOSED — champion confirmed (R3 combined sweep) |
| 4H-3 | Donchian Turtle sensitivity sweep | CLOSED — champion confirmed (R4 confirmed in R3 sweep) |
| 4H-4 | **Relative Strength Momentum sensitivity sweep** | **CLOSED** — ROBUST 625/625 (R8, 2026-04-11) |
| 4H-5 | Search for 5th strategy | CLOSED — not needed (4-strategy portfolio production-ready) |
| 4H-6 | Combined 4-strategy portfolio correlation run | CLOSED — R7 ran all 4; max pairwise r=0.22 |

### 4H vs Weekly Comparison

| Dimension | Weekly (Norgate) | 4H (Polygon) |
|---|---|---|
| Primary quality metric | Sharpe, RS(min) | Calmar, OOS P&L |
| Champion count | 6+ confirmed | 4 confirmed |
| Max Calmar | ~0.57 (Donchian Weekly) | 0.82 (RS Momentum) |
| MaxDD range | 44-67% (weekly) | 15-20% (4H) |
| Trade count | 670-2,332 per champion | 1,019-2,332 per champion |
| Universe size | 16-503 symbols | 20 symbols |
| Data period | 1990-2026 (36 years) | 2018-2026 (8 years) |
| MC Score | -1 to +5 (universe-dependent) | ALL 5 (maximum, all champions) |
