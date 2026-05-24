# Autonomous Strategy Loop — Session 2 Handoff (2026-05-23)

**Resume condition**: Mid-Session 3 of a 10-session autonomous run.
**Sandbox issue**: macOS TCC restricted my access mid-session — could not read `output/runs/`, run `.venv/bin/python`, or invoke `git`. New session should have clean access. **Verify before resuming**: `rtk ls output/runs/ | head -3`, `rtk .venv/bin/python --version`, `rtk git -C custom_strategies/private status`.

---

## What was done this session

### iter031 KILL (earlier this session)
- `def031_or_gated_spy_tlt` (OR-gate variant of iter030): HYG-strong OR SPY > SMA200 → SPY, else TLT.
- Failed composite gates; details in `AUTONOMOUS_LOG.md`.

### iter032 KILL — GDX-trend 3rd sleeve
- Strategy file: `custom_strategies/private/gold_miners_sleeve.py` (def032_gdx_trend_filter, 76 lines, committed + pushed earlier).
- Composite test: **EC27 (35%) / iter030 (50%) / GDX-trend (15%)**.
- Results saved to `custom_strategies/private/iter_data/iter032_composite_35_50_15/` (committed in commit `autonomous: iter032 KILL ...`).
- KILL reasons:
  - **Regime overlap 85.1% > 60% kill gate** (GDX drawdowns coincide with composite drawdowns)
  - **MaxRcvry unchanged at 562d** (still > 365d R3 gate, no improvement vs 2-sleeve baseline)
  - Correlations PASS (GDX vs EC27 = 0.219, GDX vs iter030 = 0.134; both < 0.40)
  - Sharpe PASS (1.17 > 1.10), TotalRet PASS (1734% > 2× SPY)
- GDX-trend standalone: -60.7% return, -78.12% MaxDD, 6975d recovery, Sharpe -0.07.

### iter034 IMPLEMENTED + STANDALONE TESTED (composite NOT YET run)
- Strategy: `def034_hyg_gated_spy_ief` — identical to iter030 but **IEF instead of TLT** (7yr duration vs 17yr — directly attacks 2022 dual-bear where TLT fell -31%, IEF fell -15%).
- File: `custom_strategies/private/defensive_switch.py` (appended at lines 191–224 alongside def030 and def031).
- Strategy committed + pushed to `research/autonomous-strategy-loop` in private submodule.
- Backtest run name: `auto-iter034-spy-ief-switch_2026-05-23_22-03-01` (in `output/runs/`).
- **Standalone verdict** (from terminal output, NOT yet copied into `iter_data/` because sandbox locked out):
  - **BEATS SPY by +328.52pp**
  - MC: DD Understated, High Tail Risk (score: -1)
  - WFA: **Pass | Rolling: Pass (5/5)**
  - Smoothness: **ACCEPTABLE** (29-month plateau)
- iter034 standalone is **NOT a champion** (29-month plateau ≈ 880d > 365d R3 gate), but the composite EC27+iter034 hasn't been scored yet — that is the key open question.

### Parent repo config (uncommitted as of session end, status unknown due to sandbox)
- `config.py` was edited:
  - Portfolio key: `"DefSwitch_SPY_TLT"` → `"DefSwitch_SPY_IEF"`
  - Strategies list: name pointing to DefSwitch-034.
- **Action needed in new session**: run `rtk git status` to verify; if dirty, decide whether to commit those config switches as iter034 run-config or revert.

---

## Immediate next steps (Session 3 completion)

### Step 1 — Verify environment
```bash
rtk ls output/runs/ | grep -E "iter034|iter030-rerun" | head -5
rtk git -C custom_strategies/private status
rtk git status
```

### Step 2 — Score iter034 composite vs EC27
Goal: replicate iter032 composite-scoring procedure but with iter034 replacing iter030's TLT leg.

```bash
# Copy iter034 run into iter_data
cp -r output/runs/auto-iter034-spy-ief-switch_2026-05-23_22-03-01 \
      custom_strategies/private/iter_data/iter034_run/

# Locate EC27 ml_features.parquet (use the existing canonical one used for iter032)
# It should be at: output/runs/<ec27 run>/ml_features.parquet
# (the same path used in the iter032 composite scoring run)
```

Then run the composite scorer (`scripts/composite_candidate_scorer.py`) with weights to sweep:
- **Primary**: 50/50 EC27 / iter034 (matches iter030's original composite recipe)
- **Sweep**: 40/60, 50/50, 60/40 EC27 / iter034
- Optionally 35/50/15 EC27 / iter034 / GDX-trend (revisit GDX with shorter-duration defensive)

### Step 3 — Kill criteria for iter034 composite (use these gates)
Per QA Opus prescription:
- Composite MaxRcvry ≥ 365d → KILL on R3
- Pairwise correlation r(iter034, EC27) > 0.40 → KILL on redundancy
- Composite Sharpe < 1.10 → KILL on quality
- Composite TotalRet < 2× SPY → KILL on alpha

If iter034 composite **passes all four**, it is a new **co-champion alongside iter030**. The crucial test is whether IEF (lower duration) compresses the 562d MaxRcvry — the 2022 binding constraint.

### Step 4 — Update `AUTONOMOUS_LOG.md`
Add iter031 KILL, iter032 KILL, iter034 IMPLEMENT + standalone, iter034 composite verdict (Step 2 output).

### Step 5 — Commit + push private submodule
```bash
rtk git -C custom_strategies/private add iter_data/iter034_run/ iter_data/iter034_composite_*/ AUTONOMOUS_LOG.md
rtk git -C custom_strategies/private commit -m "autonomous: iter034 composite verdict + log update"
rtk git -C custom_strategies/private push origin research/autonomous-strategy-loop
```

### Step 6 — Get fresh QA Opus direction
After iter034 composite verdict, spin up Opus QA agent (the same `opus-qa` agent pattern used throughout) with:
- Current champion roster (iter030 confirmed; iter034 TBD)
- All KILL data from iter031, iter032, iter034 (if killed)
- Request next 3-iter session plan

Then start **Session 4**.

---

## Backup iteration queue (if iter034 composite fails)

Per QA Opus's prior prescription, in priority order:
- **iter035** — TLT→AGG swap (Aggregate Bond Index, ~6yr duration, more diversified)
- **iter036** — TLT→IEF + GDX 10% sleeve (combine the two best 2022-defenses)
- **iter037** — HYG-trend gate replaced with credit-spread gate (HYG/LQD ratio)
- **iter033** — GLD-trend backup (likely fails like GDX-trend on regime overlap, but worth confirming as the conservative version)

---

## Champion ledger (as of handoff)

| Iter | Strategy | TotalRet | MaxDD | MaxRcvry | Smooth | WFA | MC | Status |
|------|----------|----------|-------|----------|--------|-----|-----|--------|
| iter030 | HYG-gated SPY/TLT | +1394% | — | 941d (562d in composite) | ACCEPTABLE | Pass | OK | **CHAMPION** |
| EC27 | Earnings-Catalyst VIX-27 | — | — | — | — | Pass | OK | Co-champion (used as composite anchor) |
| iter034 | HYG-gated SPY/IEF | +328pp vs SPY | — | (29mo plateau standalone) | ACCEPTABLE | Pass 5/5 | DD Understated | **PENDING composite** |

---

## Anti-patterns confirmed this session

1. **Adding more sleeves with high regime overlap does not improve MaxRcvry.** GDX-trend was lowly correlated (r=0.13–0.22) but its drawdown DAYS coincided 85% with composite drawdown days. The kill gate is **regime overlap < 60%**, not correlation.
2. **Single-symbol shorts pyramid in the engine** — proven iter001–002 (48 trillion % runaway). Long-only ALWAYS unless engine is fixed.
3. **OR-gating two trend signals does not soften a plateau** — iter031 confirmed OR-gate adds entries during chop without reducing drawdown duration.

---

## Open infrastructure tickets (informational; don't block Session 3)

- signaldeckapi MR !651 — adds "Domain coherence / file placement" audit category to `/qa-cycle` (from iter030 scanner port misplacement bug). Independent of this loop.
- Issues #1004, #1005 in signaldeckapi tracking the qa-cycle gap.

---

## Operator goal (verbatim, in `AUTONOMOUS_GOAL.md`)

> Find a smooth and upward EC strategy that is not overfit. Varying range of ideas as you progress. Less indicators the better. Relying on other areas of the market to drive buy/sell signals the better. Rely on long only. Check with the LLM verdict. Commit and push before/during/and after each iteration to have repo up to date as you progress.

Session unit: **1 full QA-driven cycle ~ 3 iters/session**. Total budget: **30 iters across 10 sessions**.
Stop condition: **only if Opus QA declares "search space exhausted"**.
Champion handling: **auto-port to signaldeckapi via MR + /qa-cycle, never merge without operator review**.

---

## How to resume in a new Claude Code session

Paste this:

> Resume autonomous strategy loop from HANDOFF.md. Verify env (output/runs accessible, .venv/bin/python works, git status clean in both repos). Then run Step 2 (iter034 composite scoring) immediately, then Steps 3–6. Then start Session 4 with fresh Opus QA direction.
