# Autonomous Strategy Research — Handoff File
# Branch: research/autonomous-strategy-loop

---

## HOW TO USE THIS FILE

**You are a Claude agent picking up an ongoing strategy research loop.**

1. Read this entire file first — it is the source of truth, not the conversation history.
2. Check the SESSION LOG at the bottom to see what the last agent ran and found.
3. Pop the first uncompleted item from THE RESEARCH QUEUE.
4. Run it using the EXECUTION PROTOCOL below.
5. Record results using the ROUND RECORDING FORMAT below.
6. Update this file: mark queue item done, add new discoveries or anti-patterns, append to SESSION LOG.
7. If time permits, pop the next queue item and repeat.
8. Stop when you hit SUCCESS/STOP CRITERIA or when your context window is getting full.

**The goal is autonomous iteration — do not wait for human approval between rounds. Run, record, advance.**

---

## THE GOAL

Find technical trading strategies that generate genuine alpha on US equities — not overfit noise.

Validation bar (ALL must pass before a strategy is declared a champion):
- WFA verdict: **Pass** (not "Likely Overfitted" or "N/A")
- Rolling WFA: **2/3 folds minimum**, 3/3 preferred
- OOS P&L: **positive and substantial** (not just +5%)
- RS(min): **better than -20** on 44-symbol universe (rolling Sharpe stress test)
- Trades: **500+ on 44-symbol universe** (law of large numbers — fewer than 500 trades cannot be trusted)
- MC Score: -1 is acceptable on 44 tech symbols (concentration correlation artifact — not a strategy flaw); -1 on 6 symbols or on non-tech sectors IS a problem

Secondary goal: find strategies that are **uncorrelated with existing champions** (Corr < 0.35 vs MA Confluence Fast Exit) for portfolio diversification.

---

## CURRENT STATE — VALIDATED CHAMPIONS (as of Round 6)

All tested on: `nasdaq_100_tech.json` (44 symbols), 1990-2026, Norgate total-return data.
All use: daily bars ("D"), wfa_split_ratio=0.80, wfa_folds=3.

| Rank | Strategy | Registered Name (exact) | File | P&L | Sharpe | RS(min) | OOS P&L | WFA | RollWFA | Corr vs MAC |
|---|---|---|---|---|---|---|---|---|---|---|
| 🥇 | MA Confluence Fast Exit | `MA Confluence (10/20/50) Fast Exit` | `research_strategies_v3.py` | 101,198% | +0.68 | -4.46 | +88,023% | Pass | 3/3 | — |
| 🥈 | Donchian Breakout (40/20) | `Donchian Breakout (40/20)` | `research_strategies_v2.py` | 48,426% | +0.63 | -3.66 | +41,665% | Pass | 3/3 | 0.39* |
| 🥉 | MA Bounce (50d/3bar)+SMA200 | `MA Bounce (50d/3bar)+SMA200` | `research_strategies_v4.py` | 45,283% | +0.61 | -10.93 | +40,519% | Pass | 3/3 | 0.02 |
| 4 | CMF Momentum (20d)+SMA200 | `CMF Momentum (20d)+SMA200` | `research_strategies_v4.py` | 51,173% | +0.63 | -15.03 | +43,803% | Pass | 3/3 | 0.18 |
| 5 | Donchian (60d/20d)+MA Align | `Donchian (60d/20d)+MA Alignment` | `round6_strategies.py` | 42,263% | +0.64 | -3.98 | +35,177% | Pass | 3/3 | 0.28* |
| 6 | MA Confluence Full Stack | `MA Confluence (10/20/50) Full Stack` | `research_strategies_v3.py` | 29,771% | +0.54 | -4.36 | +22,911% | Pass | 3/3 | 0.17 |

*Donchian variants correlate 0.39-0.95 with each other — do not hold multiple Donchian variants in the same live portfolio.

**MC Score -1 note:** All 44-symbol results show MC Score -1. This is expected — 44 correlated tech stocks crash simultaneously. Not a disqualifier. Treat it as a portfolio-construction constraint (max 5-10 concurrent positions in live trading).

### 6-Symbol Results (tech_giants.json — 1990-2026) for reference

| Strategy | P&L | Sharpe | RS(min) | WFA | RollWFA | MC Score |
|---|---|---|---|---|---|---|
| MA Confluence Full Stack | 2,718% | +0.43 | -4.44 | Pass | 3/3 | 2 |
| MA Bounce+SMA200 | 1,772% | +0.38 | -11.04 | Pass | 3/3 | 5 |
| MA Confluence Fast Exit | 857% | +0.59 | -4.53 | Pass | 3/3 | 5 |
| Donchian (40/20) | 501% | +0.42 | -4.27 | Pass | 3/3 | 5 |
| CMF Momentum (20d)+SMA200 | 943% | +0.22 | -16.59 | Pass | 3/3 | 5 |

Note: 6-symbol RS(min) is statistically noisy (300-700 trades). Only 44-symbol RS(min) is reliable.

---

## WHAT HAS BEEN PROVEN TO FAIL — DO NOT RETRY THESE

These consumed compute and taught us something. Do not re-run them in any variation without a fundamentally different approach.

| What Failed | Why | Lesson |
|---|---|---|
| RSI < 50 gate on MA Bounce | RSI is 50-60 when price touches 50-SMA in uptrend — filter eliminates 90% of valid entries, RS(min)=-1158 | Never gate bounce entries on RSI. The bounce IS the momentum signal. |
| ATR trailing stop 2.0x on tech | WFA "Likely Overfitted", 814 trades (constant whipsaw). NVDA/META ATR ≈ 5-8% of price → 10-16% stop is too tight | ATR stops on tech need 3.0x minimum. 2.0-2.5x guarantees overfit. |
| ATR trailing stop 2.5x on tech | RS(min)=-48.10 — excessive stop-outs in normal volatility | Same lesson as 2.0x |
| OBV + MA Confluence dual gate | 266 trades only, MaxRcvry 4894 days (13 years). Over-engineered entry | Two-filter combos on entry drastically over-select. One entry signal is enough. |
| CMF + RSI exit gate | RS(min) worsened from -16 to -37. CMF hovers near zero → many small churn round-trips | RSI exit gates create churn, they do not smooth equity curves |
| Single-symbol testing (AAPL only) | R1 showed AAPL results are misleading. Best strategy on AAPL: +83%. Same strategy on 44 symbols: +101,198% | Never draw conclusions from fewer than 20 symbols. Always validate on 44-symbol universe. |
| Keltner (20d/1.5x) + MA Stack | Sharpe -0.02 on 6 symbols. Keltner gate delays entries past optimal entry point | Keltner as an ENTRY gate is too delayed. Works better as an exit or filter. |
| MACD+RSI+SMA200 triple gate | Sharpe -0.23 on 6 symbols. Three conditions simultaneously is too selective | Three entry conditions = over-filtered. Max 2 conditions for entry. |
| 5-fold rolling WFA on <300 trades | Produced N/A verdicts — not enough OOS trades per fold | Use 3 folds for strategies with 250-400 trades. 5 folds needs 1000+ trades. |

---

## THE RESEARCH QUEUE

**Pop from top. Mark done. Add new items based on what you find.**

Items marked [DONE] should not be re-run.

---

### QUEUE ITEM 1 — Multi-Strategy Portfolio Simulation [PRIORITY: CRITICAL]
**Status: TODO**

**Why this matters:** We know each champion's individual stats. We don't know what happens when you run all 3 simultaneously as a real portfolio. This is the bridge between research and live trading. If combined MaxDD is catastrophic, the correlation assumptions are wrong.

**What to do:**
1. Edit `config.py`:
   - `"portfolios": {"NDX Tech 44": "nasdaq_100_tech.json"}`
   - `"strategies": ["MA Confluence (10/20/50) Fast Exit", "Donchian Breakout (40/20)", "MA Bounce (50d/3bar)+SMA200"]`
   - `"allocation_per_trade": 0.05` (5% per position, allows up to 20 concurrent)
   - `"start_date": "1990-01-01"`
   - `"wfa_split_ratio": 0.80`
   - `"wfa_folds": 3`
   - `"verbose_output": True`
   - Leave all other settings at current values

2. Run: `rtk python main.py --name "portfolio-sim-3strategy"`

3. Record in `research_results/round_7.md`:
   - Each strategy's P&L/Sharpe/MaxDD in this combined run (confirm no degradation from isolation)
   - Total portfolio equity curve description (did it compound smoothly or did crashes cluster?)
   - Peak concurrent positions observed
   - Worst single calendar year P&L
   - Best single calendar year P&L
   - Combined MaxDD vs individual strategy MaxDDs

**Success criteria:** Each strategy individually still shows WFA Pass + positive OOS. Combined portfolio Sharpe implied by compounding > 0.65. No single strategy's RS(min) dramatically worsened vs isolated testing.

**Failure criteria:** Any strategy shows WFA "Likely Overfitted" in the combined run (means correlation is creating interference). Combined effective MaxDD > 80%.

**After this:** Move to Queue Item 2 regardless of result. Record what changed.

---

### QUEUE ITEM 2 — Universality Test: Champions on S&P 500 [PRIORITY: HIGH]
**Status: TODO**

**Why this matters:** All current champions were found on NDX tech (44 stocks). MC Score -1 is a known concentration risk. If MA Confluence Fast Exit and Donchian (40/20) also work on the broader S&P 500, we can diversify away from pure tech concentration and fix the MC Score issue.

**What to do:**
1. Edit `config.py`:
   - `"portfolios": {"SP500": "sp-500.json"}`
   - `"strategies": ["MA Confluence (10/20/50) Fast Exit", "Donchian Breakout (40/20)", "MA Bounce (50d/3bar)+SMA200"]`
   - `"allocation_per_trade": 0.10`
   - `"start_date": "1990-01-01"`
   - `"wfa_split_ratio": 0.80`
   - `"wfa_folds": 3`
   - `"verbose_output": True`

2. Run: `rtk python main.py --name "universality-sp500"`

3. Record in `research_results/round_7.md` section "SP500 Universality":
   - P&L, Sharpe, RS(min), WFA verdict, RollWFA, OOS P&L for each strategy
   - Trade count (critical — need 1000+ per strategy to be meaningful on 500 stocks)
   - Compare these results vs the NDX-tech results

**Success criteria:** WFA Pass + RollWFA 2/3+ + Sharpe > 0.45 on all 3 strategies. This means the signals are universal, not tech-regime specific.

**Failure criteria:** WFA "Likely Overfitted" on 2+ strategies → signals are tech-specific. Record this finding explicitly — it means live trading should stay tech-only.

**After this:** If universality holds → proceed to Queue Item 5 (cross-sector diversified combined portfolio). If fails → record tech-only conclusion and move to Queue Item 3.

---

### QUEUE ITEM 3 — CMF Faster Period (10d vs 20d) [PRIORITY: MEDIUM]
**Status: TODO**

**Why this matters:** CMF (20d)+SMA200 has RS(min)=-15.03 on 44 symbols. The hypothesis is that 10d CMF responds faster to distribution phases, cutting positions earlier and improving the worst rolling Sharpe windows.

**What to do:**
1. Create or add to `custom_strategies/research_strategies_v5.py`:
   - Copy the CMF Momentum (20d)+SMA200 strategy
   - Change period from 20 to 10
   - Register as `"CMF Momentum (10d)+SMA200"`

2. Edit `config.py`:
   - `"portfolios": {"NDX Tech 44": "nasdaq_100_tech.json"}`
   - `"strategies": ["CMF Momentum (10d)+SMA200", "CMF Momentum (20d)+SMA200"]`
   - `"start_date": "1990-01-01"`, `"wfa_split_ratio": 0.80`, `"wfa_folds": 3`
   - `"verbose_output": True`

3. Run: `rtk python main.py --name "cmf-fast-10d"`

4. Record: Compare 10d vs 20d on all metrics. Does RS(min) improve past -10? Does Sharpe hold above 0.60?

**Success criteria:** 10d version shows RS(min) > -10 AND Sharpe > 0.60 AND WFA Pass → upgrade CMF to 10d champion.

**After this:** Move to Queue Item 4.

---

### QUEUE ITEM 4 — MA Bounce on Weekly Bars [PRIORITY: MEDIUM]
**Status: TODO**

**Why this matters:** The 50-SMA bounce is a well-known institutional pattern. Weekly bars reduce noise and false signals. Hypothesis: higher win rate (>40% vs 33% on daily), cleaner equity curve, potentially higher RS(min).

**What to do:**
1. Edit `config.py`:
   - `"timeframe": "W"` (weekly bars)
   - `"portfolios": {"NDX Tech 44": "nasdaq_100_tech.json"}`
   - `"strategies": ["MA Bounce (50d/3bar)+SMA200"]` — same strategy, weekly bars = different bar count
   - `"start_date": "1990-01-01"`, `"wfa_split_ratio": 0.80`, `"wfa_folds": 3`
   - `"verbose_output": True`

2. Run: `rtk python main.py --name "ma-bounce-weekly"`

3. **IMPORTANT:** Reset `"timeframe": "D"` in config.py after the run.

4. Record: Win rate, trade count, Sharpe, RS(min), MaxDD, WFA verdict vs the daily baseline.

**Success criteria:** Win rate > 38% AND RS(min) > -8 AND WFA Pass. If win rate improves but RS(min) worsens, it's a wash — not a champion upgrade.

**After this:** Move to Queue Item 5.

---

### QUEUE ITEM 5 — Five New Strategy Families (Round 7 Design) [PRIORITY: MEDIUM]
**Status: TODO**

**Why this matters:** The current champions are all found. To expand alpha, we need genuinely new signal families. Avoid all indicators already tested (RSI gates, OBV combos, ATR trailing).

**What to do:**
1. Create `custom_strategies/research_strategies_v5.py` with these 5 strategies:

   **Strategy A: ROC (20d) + RSI Rising Gate**
   - Entry: ROC(20) > 0 AND RSI(14) crossed above 45 from below (rising from oversold midzone)
   - Exit: ROC(20) < 0 OR price crosses below SMA200
   - Hypothesis: dual momentum (price rate + momentum indicator both confirming) reduces false breakouts

   **Strategy B: EMA Crossover (8/21) + CMF Positive Gate**
   - Entry: EMA(8) crosses above EMA(21) AND CMF(10) > 0.05 (positive money flow)
   - Exit: EMA(8) crosses below EMA(21)
   - Hypothesis: fast EMA cross confirmed by volume flow — avoids crossing into distribution

   **Strategy C: Donchian (40/20) + RSI Momentum Confirm**
   - Entry: Close > 40-bar high AND RSI(14) > 50
   - Exit: Close < 20-bar low
   - Hypothesis: breakout only when momentum is already above midline — eliminates weak breakouts

   **Strategy D: Price Momentum (6-month ROC) + SMA200**
   - Entry: ROC(126) > 15% (6-month return > 15%) AND price > SMA200
   - Exit: ROC(126) < 0% OR price < SMA200
   - Hypothesis: simple relative strength — buy what's already working vs the trend

   **Strategy E: Volatility Contraction + Breakout (NR7)**
   - Entry: Today's range is the narrowest of the last 7 days AND price closes above yesterday's high AND SMA200 > SMA200[20] (trending up)
   - Exit: Close below SMA50
   - Hypothesis: volatility contraction before expansion is a classic institutional accumulation signal

2. Edit `config.py`:
   - `"portfolios": {"Tech Giants": "tech_giants.json"}` (6 symbols first — quick validation)
   - `"strategies": "all"` but only run the v5 file (temporarily move or disable other strategy files, or use strategies list)
   - `"start_date": "1990-01-01"`, `"wfa_split_ratio": 0.80`, `"wfa_folds": 3`, `"verbose_output": True`

3. Run 6-symbol first: `rtk python main.py --name "r7-new-strategies-6sym"`

4. Any strategy with Sharpe > 0.30 and WFA Pass on 6 symbols → immediately run on 44 symbols.

5. Run 44-symbol: `rtk python main.py --name "r7-new-strategies-44sym"` (for survivors only)

6. Record everything in `research_results/round_7.md` section "New Strategy Families".

**Success criteria:** Any new strategy achieves WFA Pass + RollWFA 2/3+ + RS(min) > -15 on 44 symbols AND Corr vs MA Confluence Fast Exit < 0.35 → new champion.

---

### QUEUE ITEM 6 — Cross-Sector Diversified Portfolio [PRIORITY: LOW — do after Item 2]
**Status: TODO — only if Queue Item 2 (SP500 universality) PASSES**

**What to do:**
If Item 2 shows champions work on SP500, run a combined portfolio:
- `"portfolios": {"Diversified": "sp-500.json"}`
- `"strategies": ["MA Confluence (10/20/50) Fast Exit", "Donchian Breakout (40/20)", "MA Bounce (50d/3bar)+SMA200"]`
- `"allocation_per_trade": 0.03` (3% — allows more concurrent positions on 500-stock universe)

This tests whether a non-tech-concentrated portfolio still delivers alpha and fixes MC Score -1.

---

### QUEUE ITEM 7 — ATR Trailing Stop 3.0x on MA Confluence [PRIORITY: LOW]
**Status: TODO**

2.0x and 2.5x ATR failed on tech stocks. If you have spare compute, try 3.0x.

- Same MA Confluence entry logic
- Exit: 10-SMA cross below 50-SMA (original) OR price drops 3.0x ATR below highest close since entry
- Run on 6 symbols first. If WFA Pass + fewer trades than 2.0x version → run on 44 symbols.
- Success: WFA Pass AND trades count < 500 (not whipsawing) AND RS(min) > -6 on 44 symbols.

---

## EXECUTION PROTOCOL

### Commands (always prefix with `rtk` — project rule)
```bash
# Standard run
rtk python main.py --name "descriptive-run-name" --verbose

# Dry run to verify strategies load
rtk python main.py --dry-run

# Check what strategies are registered
rtk python main.py --dry-run 2>&1 | head -30
```

### Config Change Workflow
1. `Read config.py` to see current state
2. Use `Edit config.py` to make targeted changes (do NOT rewrite the whole file)
3. Run the backtest
4. Restore any temporary changes (timeframe, strategies list) after the run

### Key config keys to change per run
```python
"portfolios": {"Name": "ticker_file.json"}   # or inline list
"strategies": "all"                            # or ["Exact Name 1", "Exact Name 2"]
"start_date": "1990-01-01"                    # always use 1990 for full history
"allocation_per_trade": 0.10                   # 0.05 for combined portfolio runs
"wfa_split_ratio": 0.80
"wfa_folds": 3                                # always 3, never 5 (insufficient trades)
"verbose_output": True                         # always True to get extended metrics
"timeframe": "D"                              # reset to "D" after any weekly test
```

### Available ticker files
- `nasdaq_100_tech.json` — 44 NDX tech stocks (primary research universe)
- `tech_giants.json` — 6 stocks: AAPL, MSFT, GOOG, AMZN, NVDA, META (quick validation)
- `sp-500.json` — 500 stocks (universality test)
- `nasdaq_100.json` — full NDX 100 (includes non-tech NDX)
- `russell_1000.json` — 1000 large/mid caps (broad market)

### Interpreting Results — Quick Reference
| Metric | Green | Yellow | Red |
|---|---|---|---|
| WFA verdict | Pass | N/A | Likely Overfitted |
| RollWFA | 3/3 | 2/3 | 1/3 or 0/3 |
| RS(min) on 44 symbols | > -8 | -8 to -20 | < -20 |
| Sharpe | > 0.60 | 0.40-0.60 | < 0.40 |
| Trade count (44 symbols) | > 1000 | 500-1000 | < 500 |
| OOS P&L | > 100% of IS | 50-100% of IS | < 50% of IS |
| MC Score | 5 | 2-4 | -1 (only ok on 44 tech) |

---

## ROUND RECORDING FORMAT

When you complete a run, create or append to `research_results/round_7.md` using this format:

```markdown
# Research Round 7 — [Section Name]

**Date:** [date]
**Run ID:** [from output folder name]
**Symbols:** [file used and count]
**Period:** 1990-2026
**WFA:** 80/20 split, 3 rolling folds

## Results

| Strategy | P&L | Sharpe | MaxDD | RS(min) | OOS P&L | WFA | RollWFA | MC Score |
|---|---|---|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... | ... | ... | ... |

## Extended Metrics

| Strategy | Calmar | RS(avg) | PF | WinRate | Trades | Expct(R) | SQN | Corr vs MAC |
|---|---|---|---|---|---|---|---|---|
| ... |

## Key Findings

[What was learned. What surprised you. What hypothesis was confirmed or rejected.]

## Updated Anti-Patterns (if any)

[Add any new "do not retry" lessons here, then copy them to the main ANTI-PATTERNS table above]

## New Queue Items (if any)

[If a finding opens a new research direction, add it here, then add it to THE RESEARCH QUEUE above]
```

---

## SUCCESS / STOP CRITERIA

### Research is COMPLETE when ANY of these conditions are met:

**Condition A — Combined portfolio validated:**
- Queue Items 1 AND 2 are done
- Combined 3-strategy portfolio shows Sharpe > 0.65 AND MaxDD < 60% on 44-symbol OOS period
- Universality test passes on SP500 (2 of 3 strategies WFA Pass)

**Condition B — New uncorrelated champion found:**
- A new strategy from Queue Item 5 shows Corr < 0.20 vs MA Confluence Fast Exit AND achieves champion-level stats (WFA Pass, RollWFA 3/3, RS(min) > -12 on 44 symbols)
- This expands the portfolio from 3 to 4 strategies

**Condition C — 10+ rounds without breakthrough:**
- If 3 consecutive queue items produce no new champion-level strategy and no meaningful improvement to existing ones, declare the research complete and document final recommendations

### Do NOT keep researching if:
- You're only making tiny tweaks to existing champions (period from 20→18→22 etc.) — that is p-hacking
- Every new strategy you try scores worse than the existing 5 champions
- You're running more than 3 variations of the same indicator family

### The existing champions ARE ready for forward testing now.
The open questions (combined portfolio, universality) are about optimizing position sizing and diversification for live trading, not about whether the strategies work.

---

## SESSION LOG

**Append your session here when done. Include: date, what you ran, key finding, next recommended action.**

---

### Session 1 — 2026-04-10 (Rounds 1-6 completed)
**Agent:** Original research session
**Ran:** 6 rounds of strategy discovery on AAPL → tech_giants (6) → NDX Tech (44 symbols)
**Key findings:**
- MA Confluence Fast Exit is the dominant champion (101,198% / Sharpe +0.68 / RS(min) -4.46 on 44 symbols)
- MA Bounce is a genuine structural diversifier (r=0.02 vs MAC)
- Extending history to 1990 reveals dot-com tail risk — always use 1990 start
- RSI gates destroy bounce strategies — proven definitively in R6
- 6-symbol RS(min) is noise — only 44-symbol RS(min) is reliable
- ATR trailing stops need 3.0x+ on tech — 2.0/2.5x guarantees overfit
**Next recommended action:** Queue Item 1 (multi-strategy portfolio simulation) — this is the critical missing piece before any live trading decision

---

_[Next agent: append your session below this line]_
