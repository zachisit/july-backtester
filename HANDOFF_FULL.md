# Autonomous Strategy Loop — FULL Handoff

**Date written**: 2026-05-23 (session ended due to mid-session sandbox lockout)
**Branch (parent repo)**: `autoresearch/poc`
**Branch (private submodule)**: `research/autonomous-strategy-loop`
**Resume point**: Session 3, iter034 composite scoring (1 of 3 iters left in Session 3, then Sessions 4–12 follow)

This document is a comprehensive reconstruction of the entire autonomous strategy-research loop the operator set up across an 8+h session. It is written from in-context memory because the sandbox locked filesystem reads mid-session and I could not refresh from `AUTONOMOUS_LOG.md` before writing. Where this conflicts with `AUTONOMOUS_LOG.md`, **trust `AUTONOMOUS_LOG.md`**.

> Companion file: `HANDOFF.md` (in same directory) covers only the iter031/032/034 thread. This file is the broader history + resume plan.

---

## 1 — Operator Intent (verbatim, in `AUTONOMOUS_GOAL.md`)

> Use the previous strategy and knowledge context in the repo to try various strategy concepts to find a smooth and upward EC strategy that is not overfit. Varying range of ideas as you progress. Less indicators the better. Relying on other areas of the market to drive buy/sell signals the better. Rely on long only. Check with the LLM verdict. Commit and push before/during/and after each iteration to have repo up to date as you progress. Utilize the findings and data prior to this session to help shape your research. You are a quant tasked with finding the alpha in the markets and you have the tool and the token spend to figure this out. Utilize haiku and sonnet models for their ideal purpose to reduce token spend, and a QA opus model for judgement. You are the orchestrator. Also save this prompt to a local md file.

Follow-on operator commitment for sustained run: **"continue this for 10 more sessions. commit/push to the repo after each iteration, updating the central knowledge file for new sessions to learn from. I will step away from computer."**

---

## 2 — Workflow contract (confirmed via AskUserQuestion)

| Term | Value |
|------|-------|
| **Session unit** | 1 full QA-driven cycle ≈ **3 iters/session** |
| **Total budget** | **30 iterations** across **10 sessions** |
| **Stop condition** | **Only** when Opus QA declares **"search space exhausted"** |
| **Champion auto-port** | Open MR in `signaldeckapi` + run `/qa-cycle`. **Never merge** without operator review. |
| **Commit cadence** | After every iteration, push both repos |
| **Knowledge file** | `custom_strategies/private/AUTONOMOUS_LOG.md` — append every iter |
| **Model assignment** | Opus = QA + judgment; Sonnet = strategy implementation; Haiku = trivial tooling |
| **Direction constraint** | long-only, fewer indicators preferred, cross-asset signals preferred |

---

## 3 — Hard-won technical knowledge (anti-patterns from this and prior sessions)

### 3.1 Engine pyramiding bug — single-symbol shorts compound uncontrollably
- Demonstrated by ALT 1 strategy: produced **48 trillion %** P&L at allocation 1.0.
- The backtester per-symbol engine compounds short positions on the same symbol without sizing controls.
- **Rule**: **long-only ALWAYS** unless engine is fixed. Any short signal must be in a different symbol (e.g. defensive switch SPY→TLT).

### 3.2 Parquet data conventions
- Norgate indices use `$` prefix: `$VIX.parquet`, `$TNX.parquet`
- ETF symbols are plain: `SPY.parquet`, `TLT.parquet`, `HYG.parquet`, `IEF.parquet`, `GDX.parquet`, `GLD.parquet`
- v1.8.0 had a regression that aliased Polygon `O:` prefixes broadly and broke `$VIX → VIX` lookup. Fixed in v1.8.1 with a Polygon-prefix-only strip.

### 3.3 Engine dep injection
- Only `spy_df`, `vix_df`, `tnx_df` are injected as named kwargs into strategies.
- Other cross-asset series (HYG, GDX, etc.) must be loaded by the strategy directly via parquet, using `_load_close()` and `_identify_symbol()` helpers (pattern in `defensive_switch.py`).

### 3.4 State-machine signal pattern (used in defensive-switch strategies)
```
state = "flat"
for i in range(len(df)):
    w = bool(want_long.iloc[i])
    if state == "flat":
        if w: signals.append(1); state = "long"
        else: signals.append(0)
    else:  # long
        if not w: signals.append(-1); state = "flat"
        else: signals.append(0)
```
Emit `1` (long-entry), `0` (hold), `-1` (exit). Never emit -1 as short — the engine pyramid bug will fire.

### 3.5 Composite scorer methodology
- Located: `scripts/composite_candidate_scorer.py`
- Uses **MTM equity curves** (`equity_curve.csv` per run), NOT trade-log P&L
- Sweeps weight combinations across N sleeves
- Outputs: composite TotalRet, MaxDD, MaxRcvry, Sharpe, pairwise correlations, regime-overlap %
- **Regime overlap > 60% = KILL** (drawdown days coincide → no diversification value even at low correlation)
- Composite output dir: `custom_strategies/private/iter_data/iterNNN_composite_<weights>/`

### 3.6 Long-vol overlay data gap
- VXX, UVXY, VIXM all start **post-2010** → cannot backtest the GFC plateau (2008–2010).
- Disqualifies most long-vol overlay ideas for full-history validation.

### 3.7 4-Gate Champion criteria
| Gate | Threshold |
|------|-----------|
| R1 | Beats SPY B&H (TotalRet & risk-adjusted) |
| R2 | LLM smooth_verdict ≥ **ACCEPTABLE** |
| R3 | MaxRcvry **< 365 days** |
| R4 | WFA **Pass** + MC score **≥ 4** |

---

## 4 — Infrastructure prerequisites (already in place; do not reinvent)

### 4.1 Backtester v1.8.0/v1.8.1 — LLM verdict surfacing
Released earlier this session. Adds:
- `smooth_verdict`, `mc_verdict`, `wfa_verdict`, `wfa_rolling_verdict` in `llm_verdict.json`
- `build_strategy_verdict_page()` in `helpers/_pdf_pages.py` — renders verdict on PDF tearsheet
- Terminal "STRATEGY VERDICTS" block at end of run
- **This is what makes the autonomous loop possible.** Each iter prints a machine-readable verdict that QA Opus + the orchestrator can parse without re-reading the PDF.

### 4.2 Engine output structure (per run)
```
output/runs/<run-name>_<timestamp>/
├── llm_verdict.json
├── equity_curve.csv          (MTM equity timeseries — composite scorer input)
├── ml_features.parquet       (only if export_ml_features=True in config)
├── raw_trades/               (trade logs per strategy)
└── tearsheets/               (PDF reports)
```
- **Must set `export_ml_features=True` in `config.py`** for composite scoring downstream.
- Set `allocation_per_trade=1.0` (full notional) so composite weights are clean.

### 4.3 signaldeckapi forward-tester deployment pattern
- Repo: `/Users/zach/Desktop/gitlab/signaldeckapi/`
- Pattern: champion strategies are ported to `scanner/helpers/<name>_logic.py` + registered in scanner registry
- Prior champions:
  - **MR !588 (v1.0.52)** — three gold champions (gold-rotation strategies; gone through QA, currently in forward test)
  - **MR !??? (iter030)** — `defswitch_logic.py` (HYG-gated SPY/TLT), refactored out of `gold_regime_logic.py` after misplacement bug
- After port: run `/qa-cycle` on the MR. **Do not merge without operator approval.**

### 4.4 /qa-cycle gap fix (in progress, independent of strategy loop)
- Bug: my iter030 port was initially misplaced in `gold_regime_logic.py` (a gold-themed file, not a defensive-switch file). `/qa-cycle` returned 0/0/0 and missed the misplacement.
- Tickets opened:
  - **Issue #1004** — bug report with full history
  - **Issue #1005** — Opus review of `/qa-cycle` implementation
  - **MR !651** — adds **"Domain coherence / file placement"** audit category to `/qa-cycle` (mechanical filename-token + symbol-body match check)
- Status as of session end: MR !651 open; not blocking the autonomous loop.

### 4.5 Opus QA agent invocation pattern
Each iteration ends with a QA gate. Spin up an Opus subagent (`general-purpose`, `model=opus`) with:
- Current champion roster + their metrics
- The new iter's full verdict (terminal block + composite scoring output if applicable)
- All prior KILL reasons in this session
- Request: (a) verdict on this iter, (b) prescribed next-iter experiment with explicit kill criteria, (c) declare "search exhausted" if no remaining productive direction.

The orchestrator (this Claude instance) treats Opus QA verdicts as authoritative. Do NOT second-guess them.

---

## 5 — Strategy iteration ledger

### 5.1 Pre-session iterations (iter003–029)
Lived in `AUTONOMOUS_LOG.md`. Summary from memory:
- Many iterations of single-indicator equity strategies, VIX overlays, TLT overlays.
- Multiple Sonnet-written candidates failed R1 (didn't beat SPY) or R2 (jagged EC) or both.
- The Earnings-Catalyst VIX-27 (EC27) was the first sleeve to consistently survive R1 + R4. Used as the composite anchor since.
- Engine pyramid bug discovered, anti-pattern codified.

### 5.2 iter030 — **CHAMPION (CONFIRMED)**
- Strategy: `def030_hyg_gated_spy_tlt` in `custom_strategies/private/defensive_switch.py`
- Logic: long SPY when HYG > HYG.SMA50, else long TLT. One indicator (HYG.SMA50), cross-asset (HYG → SPY/TLT routing), long-only.
- **Verdict**: BEATS SPY +796pp (+1394% total), Smooth ACCEPTABLE, WFA Pass + Rolling 5/5, MC OK.
- Composite (40/60 EC27/iter030): TotalRet 2050%+, MaxRcvry 562d (down from standalone 941d, -40% compression). **Still > 365d R3 gate**, so composite fails R3 but is closest to passing of anything tried.
- **Ported to signaldeckapi** via separate MR (after misplacement bug fix).
- **Status**: confirmed champion at the sleeve level; the open question for Sessions 3+ is whether **adding a 3rd sleeve** can push composite MaxRcvry below 365d.

### 5.3 iter031 — KILL (OR-gate variant)
- Strategy: `def031_or_gated_spy_tlt` — same as iter030 but SPY entry on `(HYG > HYG.SMA50) OR (SPY > SPY.SMA200)`.
- Hypothesis: OR-gate would reduce 2013-style HYG-chop plateaus.
- Result: KILL. OR-gate added entries during chop without reducing drawdown DURATION. Confirms anti-pattern: **OR-gating two trend signals does not soften a plateau**.

### 5.4 iter032 — KILL (GDX-trend 3rd sleeve)
- Strategy: `def032_gdx_trend_filter` in `custom_strategies/private/gold_miners_sleeve.py`
- Logic: long GDX when GDX > GDX.SMA200, else flat.
- Composite tested at **35/50/15 (EC27/iter030/GDX)**.
- Result: KILL on **regime overlap 85.1%** (> 60% gate) and **MaxRcvry unchanged at 562d**.
- Correlations PASSED (GDX vs EC27 = 0.219, GDX vs iter030 = 0.134; both well under 0.40 gate).
- Sharpe + TotalRet PASSED.
- **Lesson codified**: low correlation ≠ regime diversification. GDX's drawdown DAYS coincided 85% with composite drawdown days. **Use regime overlap as the binding gate, not correlation.**

### 5.5 iter034 — IMPLEMENT + STANDALONE (composite PENDING)
- Strategy: `def034_hyg_gated_spy_ief` in `custom_strategies/private/defensive_switch.py` (lines 191–224)
- Logic: identical to iter030 but **IEF replaces TLT** (7yr duration vs 17yr).
- Hypothesis: directly attack 2022 dual-bear constraint. TLT fell -31% in 2022 (the 562d plateau driver); IEF fell only -15%.
- **Standalone verdict** (captured from terminal output before sandbox lockout):
  - BEATS SPY by **+328.52pp**
  - WFA: **Pass | Rolling: Pass (5/5)**
  - Smoothness: **ACCEPTABLE** (29-month plateau)
  - MC: DD Understated, High Tail Risk (score: -1)
- **Composite EC27 + iter034 NOT YET SCORED** — sandbox blocked reads from `output/runs/` before I could copy the parquet/equity CSV into `iter_data/` for the composite scorer.
- iter034 standalone is NOT a champion (29-mo plateau ≈ 880d > 365d R3 gate), but the **composite-MaxRcvry compression** is the open question. Possible that IEF compresses MaxRcvry from 562d below 365d.

### 5.6 iter033 — backup (not run; only if iter034 composite fails)
- Strategy: GLD-trend filter (same shape as iter032 but gold bullion instead of miners).
- Likely fails on same regime-overlap reason as iter032 (gold and equities both struggle in 2012–2019 plateau).

### 5.7 iter035–037 — backup queue (per Opus QA prior prescription)
- **iter035** — TLT→AGG (Aggregate Bond Index, ~6yr duration, diversified)
- **iter036** — iter034 + GDX 10% sleeve (combine two best 2022-defenses; revisit GDX with lower-duration defensive)
- **iter037** — Replace HYG-trend gate with credit-spread gate (HYG/LQD ratio)

---

## 6 — Session-by-session progress

| Session | Iters | Status | Outcome |
|---------|-------|--------|---------|
| 1 (pre-loop) | iter030 | ✓ complete | iter030 declared CHAMPION; composite MaxRcvry 562d still > R3 |
| 2 | iter031, iter032, iter034-impl | ✓ complete | iter031 KILL, iter032 KILL, iter034 implemented + standalone |
| **3 (current)** | iter032-composite ✓, iter034-standalone ✓, **iter034-composite PENDING** | **in_progress** | Sandbox locked before composite scoring could run |
| 4 | TBD by Opus QA | pending | depends on iter034 composite outcome |
| 5–12 | TBD chained | pending | continue until "search exhausted" |

---

## 7 — Where this session stopped (sandbox lockout)

Mid-session, macOS TCC began denying filesystem reads for:
- `output/runs/*` (where the iter034 backtest output lives)
- `.venv/bin/python` (couldn't run python at all)
- `custom_strategies/private/*` (couldn't read AUTONOMOUS_LOG.md or any iter_data)
- `git` from any cwd inside the project (couldn't commit or check status)

What was confirmed-committed before the lockout (from terminal output):
- Private submodule, `research/autonomous-strategy-loop`:
  - `autonomous: iter032 KILL — GDX-trend 3rd sleeve…` (4 files, 6447 insertions, pushed ✓)
  - `autonomous: iter034 IMPLEMENT — DefSwitch-034 SPY/IEF variant…` (1 file, 62 insertions, pushed ✓)

What is uncommitted at session end (status unknown due to sandbox):
- Parent repo `config.py` — portfolio key swapped to `DefSwitch_SPY_IEF` and strategy list updated for iter034. Either commit as iter034 run-config or revert.

What never got captured:
- iter034 backtest output (`output/runs/auto-iter034-spy-ief-switch_2026-05-23_22-03-01/`) never copied into `custom_strategies/private/iter_data/iter034_run/`.

---

## 8 — Resume plan for new session

### Step 0 — Verify sandbox cleared
```bash
rtk ls output/runs/ | head -3
rtk .venv/bin/python --version
rtk git -C custom_strategies/private status
rtk git status
```
If any fail with EPERM, the sandbox didn't clear — exit and have operator restart the session.

### Step 1 — Reconcile pending state
```bash
# Parent repo: decide whether to commit config.py iter034 swap or revert
rtk git diff config.py
# If keeping: commit as "autonomous: iter034 run-config switch (TLT→IEF portfolio)"
# If reverting: revert and restore DefSwitch_SPY_TLT config

# Private submodule: confirm iter032 + iter034 commits landed on remote
rtk git -C custom_strategies/private log --oneline -5
```

### Step 2 — Copy iter034 backtest into iter_data
```bash
cp -r output/runs/auto-iter034-spy-ief-switch_2026-05-23_22-03-01 \
      custom_strategies/private/iter_data/iter034_run/
```

### Step 3 — Score iter034 composite (the work that got blocked)
Find the canonical EC27 run (the same one used for iter032 composite scoring — look for `iter030-rerun-for-parquet_2026-05-23_22-01-14/` or similar with `ml_features.parquet`). Then run `scripts/composite_candidate_scorer.py` with weight sweep:
- **Primary**: 50/50 EC27 / iter034 (matches iter030's composite recipe)
- **Sweep**: 40/60, 50/50, 60/40 EC27 / iter034
- **Optional 3-sleeve**: 35/50/15 EC27 / iter034 / GDX-trend (revisit GDX with shorter-duration defensive)

### Step 4 — Apply iter034 composite kill criteria
| Gate | Threshold |
|------|-----------|
| MaxRcvry | < 365d to PASS R3 (the prize); ≥ 365d to KILL |
| Pairwise correlation r(iter034, EC27) | < 0.40 to PASS |
| Composite Sharpe | ≥ 1.10 to PASS |
| Composite TotalRet | ≥ 2× SPY to PASS |
| Regime overlap | < 60% to PASS |

**If all PASS → iter034 is a co-champion alongside iter030.** Trigger auto-port to signaldeckapi (MR + `/qa-cycle`, no merge).

**If composite fails on MaxRcvry only**: Opus QA prescribes next iter (likely iter035 AGG swap or iter036 IEF+GDX combo).

### Step 5 — Update AUTONOMOUS_LOG.md
Append entries for iter031 KILL, iter032 KILL, iter034 IMPLEMENT + standalone + composite verdict.

### Step 6 — Commit + push both repos
```bash
rtk git -C custom_strategies/private add iter_data/iter034_run/ iter_data/iter034_composite_*/ AUTONOMOUS_LOG.md
rtk git -C custom_strategies/private commit -m "autonomous: iter034 composite verdict + Session 3 log"
rtk git -C custom_strategies/private push origin research/autonomous-strategy-loop

# Parent repo: commit any pending changes
rtk git add config.py HANDOFF.md HANDOFF_FULL.md
rtk git commit -m "autonomous: Session 3 handoff + iter034 run-config"
rtk git push origin autoresearch/poc
```

### Step 7 — Get fresh Opus QA direction
Spin up Opus QA subagent with:
- Updated champion roster
- iter034 composite verdict
- KILL ledger (iter031, iter032, iter034 if killed)
- Request: Session 4 plan (3 iters with explicit hypotheses + kill criteria each)

### Step 8 — Continue Sessions 4–12
Chain iter execution: plan → implement (Sonnet) → backtest → commit → QA judgment (Opus) → log update. Three iters = one session. After each session, fresh Opus QA direction. Stop only when QA declares "search space exhausted."

---

## 9 — Where the rest of the context lives

| Resource | What's in it |
|----------|-------------|
| `custom_strategies/private/AUTONOMOUS_LOG.md` | Full iter-by-iter log (31+ iters), CHAMPION DECLARED section, anti-patterns, all previous KILL reasons. **Authoritative if it conflicts with this file.** |
| `AUTONOMOUS_GOAL.md` (parent repo) | Operator goal verbatim + distillation |
| `MEMORY.md` (`~/.claude/projects/.../memory/MEMORY.md`) | Auto-loaded memory index, pointers to project context |
| Git log on `research/autonomous-strategy-loop` (private submodule) | Every committed iter, including KILLs |
| Git log on `autoresearch/poc` (parent repo) | Engine + scorer changes, config evolution |
| `scripts/composite_candidate_scorer.py` | Composite scorer source (MTM-equity methodology) |
| `scripts/blowoff_check.py`, `scripts/anchoryx_shortlist_*.md` | Earlier session artifacts (not part of loop) |
| signaldeckapi repo (`/Users/zach/Desktop/gitlab/signaldeckapi/`) | Forward-test deployments: MR !588 (gold champions), iter030 port MR, MR !651 (`/qa-cycle` Domain coherence fix) |
| signaldeckapi `.claude/commands/qa-cycle.md` | Updated `/qa-cycle` command with new audit category |
| `output/runs/` (gitignored) | Every backtest run output; rotates. Copy interesting ones into `iter_data/`. |

---

## 10 — Things the orchestrator MUST do (learned from this session)

1. **Commit after every single iter.** Operator was clear. Don't batch.
2. **Always copy run output into `iter_data/` before relying on it** — `output/runs/` is gitignored and may be inaccessible later.
3. **Treat Opus QA verdict as final.** Don't argue, don't second-guess. Implement the prescribed experiment.
4. **Update AUTONOMOUS_LOG.md within each iter's commit**, not in batch — so the central knowledge file is always current for the next session.
5. **For champions, auto-port to signaldeckapi as MR + `/qa-cycle`, but NEVER merge.** Operator approves merges.
6. **Place ported logic in a domain-coherent file.** iter030 misplaced in `gold_regime_logic.py` triggered MR !651. New convention: filename token must match symbol/strategy theme.
7. **Long-only ALWAYS.** Engine pyramid bug is still unfixed at engine level.
8. **Use regime overlap (< 60%), not correlation (< 0.40), as the binding composite gate.** Correlation can be deceptively low while drawdown days coincide.
9. **Use Sonnet for strategy writing**, Opus for QA, Haiku for trivial tasks. Don't burn Opus tokens on code generation.
10. **Resume from `AUTONOMOUS_LOG.md` first**, then this handoff. Log is the truth.

---

## 11 — Quick-start prompt for the next session

Paste this into a fresh Claude Code session in this repo:

> Resume the autonomous strategy-research loop from `HANDOFF_FULL.md`. First verify sandbox is clear (Step 0). Read `custom_strategies/private/AUTONOMOUS_LOG.md` for the authoritative iter history. Then execute Steps 1–8: reconcile pending git state, copy iter034 backtest into iter_data, score iter034 composite vs EC27 with the weight sweep, apply the composite kill criteria, update AUTONOMOUS_LOG.md, commit + push both repos, get fresh Opus QA direction for Session 4, then chain Sessions 4–12. Commit after every iter. Auto-port any champion to signaldeckapi (MR + /qa-cycle, no merge). Stop only when Opus QA declares "search space exhausted." Long-only always.
