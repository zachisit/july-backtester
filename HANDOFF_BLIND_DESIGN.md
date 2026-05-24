# Autonomous Strategy Loop v2 — Blind-Design + Engine Fix

**Date written**: 2026-05-24
**Author**: Claude Opus 4.7 (orchestrator)
**Audience**: Brand-new Claude Code session with zero prior context. Operator will not be present.
**Repos**: parent `/Users/zach/Desktop/github/july-backtester` (branch `autoresearch/poc`), private submodule `custom_strategies/private` (branch TBD — you will create it).

This handoff is **self-contained**. Do not assume any prior conversation context.

---

## 0 — Pre-flight (do this first, do not skip)

Before any work:

```bash
rtk ls custom_strategies/private/AUTONOMOUS_LOG.md      # must exist
rtk ls /Users/zach/Desktop/gitlab/signaldeckapi          # must exist
rtk .venv/bin/python --version                           # must be 3.12.x
rtk git status                                           # parent should be clean
rtk git -C custom_strategies/private status              # private should be clean
```

If any of these fails, STOP and write a short status note. Do not improvise around a missing repo or broken venv.

**RTK PREFIX RULE — NON-NEGOTIABLE**: Every shell command in this project MUST be prefixed with `rtk`. No exceptions. Bare `git`, `grep`, `pytest`, `find`, `ls` are FORBIDDEN. This is enforced by the CLAUDE.md in the project root.

Read these files in this order before doing anything:
1. `/Users/zach/Desktop/github/july-backtester/CLAUDE.md` — project conventions
2. `/Users/zach/Desktop/github/july-backtester/custom_strategies/private/AUTONOMOUS_LOG.md` — full history of the v1 loop (41 iterations, 4 sessions, declared SEARCH SPACE EXHAUSTED at iter041)
3. `/Users/zach/Desktop/github/july-backtester/custom_strategies/private/GOLD_STRATEGY_LINKEDIN_THREAD.md` — public pressure-test that motivated this round
4. This handoff document

---

## 1 — Operator intent (verbatim from the conversation that produced this handoff)

The v1 autonomous loop (Sessions 1–4, iters 001–041) declared search-space exhausted. Champion: composite **EC-VIX-27 (40%) + DefSwitch-030 (60%)**, 2,137% TotalRet over ~21yrs, but **R3 gate (MaxRcvry < 365d) is not met** — empirical floor is 562d driven by the 2022 dual-bear regime overlap.

Public LinkedIn discussion surfaced one critique that no amount of new backtesting can answer: **spec-level lookahead**. Every existing strategy was designed with full 2004–2025 history visible. WFA validates parameters within a chosen rule shape; it cannot validate the rule shape itself when that shape was designed with the crisis it's meant to catch already visible.

**This round = "Blind-Design + Engine Fix" (Option A in the conversation).** Two parallel commitments:

1. **Engine fix**: repair the short-position pyramiding bug in `helpers/portfolio_simulations.py` so inverse ETFs (SH, PSQ, SDS) and other true defensive shorts become long-only-compatible building blocks. Per Opus QA's exhaustion verdict, this is the highest-leverage single change available.

2. **Blind-design protocol**: establish a held-out era (2023-01-01 onward, ~2.5 years of post-design data). Never query that window during research. Iterate new strategies on 2004-01-01 → 2022-12-31 only. Unlock the held-out era exactly once as a one-shot verification at the end of the round.

The existing v1 champions (gold trio, iter030, EC27, the EC27+iter030 composite) are **frozen as the v1 shipping config**. Do not modify, retune, or "improve" them. They continue toward forward-testing in parallel (signaldeckapi MR !652 / signaldeckapi production scanner). They are the control group; this round produces a v2 candidate set.

---

## 2 — Workflow contract

| Term | Value |
|------|-------|
| Session unit | ≈ 3 iters/session |
| Total budget | 30 iterations across ~10 sessions (matches v1 loop) |
| Stop condition | (a) Opus QA declares search exhausted at the BLIND data layer, OR (b) a new champion passes all 4 R-gates on the BLIND iteration period (2004-2022), at which point execute the unlock + verify on 2023+ |
| Commit cadence | Commit + push after every iteration. Both repos. |
| Knowledge file | `custom_strategies/private/AUTONOMOUS_LOG_V2.md` (new file — DO NOT append to v1's AUTONOMOUS_LOG.md, which is the v1 historical record) |
| Model assignment | Opus = QA + judgment; Sonnet = strategy implementation; Haiku = trivial tooling |
| Champion handling | Auto-port to signaldeckapi via MR + `/qa-cycle`. **Never merge without operator review.** |

---

## 3 — The blind-design protocol

### 3.1 The cutoff

**Blind cutoff date**: `2023-01-01`. All research, iteration, parameter selection, and QA judgment happens on data with `EntryDate < 2023-01-01`. Data from 2023-01-01 onward is the **held-out verification era**.

This cutoff was chosen because:
- It's the natural boundary after the 2022 dual-bear (the spec-lookahead concern centers on 2022)
- It gives ~2.5 years of post-design data for the one-shot verification
- It cleanly excludes COVID recovery dynamics that have been heavily reasoned about publicly

### 3.2 Enforcement: data-cutoff guard

You MUST implement a guard at the data-loading layer of the backtester. This is the first concrete task of this round.

**Location**: a new module `helpers/blind_design_guard.py`.

**Mechanism**:
- Read `BLIND_DESIGN_CUTOFF` from `config.py` (add this key; default `None` = guard disabled)
- When set (e.g., `"2023-01-01"`), the guard wraps every data-loading function (`get_price_data`, `_load_close`, `_load_mtm_equity_curve`, parquet readers) so they raise `BlindDesignViolation` if any returned data crosses the cutoff
- An override flag `BLIND_DESIGN_UNLOCK=True` must be set to bypass the guard (used only for the one-shot verification at end of round)
- All v2 research runs MUST set `BLIND_DESIGN_CUTOFF="2023-01-01"`, `BLIND_DESIGN_UNLOCK=False`

**Tests**: write `tests/test_blind_design_guard.py` covering:
- Loading SPY 2004-2022 succeeds with cutoff set
- Loading SPY 2004-2024 raises `BlindDesignViolation`
- Setting `BLIND_DESIGN_UNLOCK=True` allows past-cutoff loads
- Guard is no-op when `BLIND_DESIGN_CUTOFF=None`

**Public commitment**: write `BLIND_DESIGN_PROTOCOL.md` at the project root that documents the cutoff date, the guard mechanism, and the unlock procedure. Commit this BEFORE writing any v2 strategy code. This is the publishable methodology that answers Dmitrii's critique.

### 3.3 What's allowed vs forbidden during v2 research

**Allowed (blind-safe):**
- Textbook indicators (RSI, SMA, EMA, ATR, Williams %R, MACD, Bollinger Bands, etc.) — invented decades ago, not tainted
- Engine primitives (simulation loop, WFA, MC, regime heatmap, composite scorer) — infrastructure
- The short-pyramid engine fix (Phase 2) — infrastructure, not strategy spec
- New rule shapes never tried in the v1 KILL ledger
- Long-only and now long-inverse-ETF (after engine fix) positioning
- Cross-asset signals (HYG, GLD, XLE, AGG, IEF, TLT, LQD, VIX, TNX — all blind-safe pre-2023)
- The full v1 anti-pattern ledger as constraints on the search (these are "don't do this" rules; they shrink the space, they don't fit to data)

**Forbidden (would re-introduce spec-lookahead):**
- Re-using any existing rule shape from v1 with new params (HYG-trend gating, OR-gates, credit-spread gates, VIX-level binary gates, etc. — see v1 anti-pattern list in AUTONOMOUS_LOG.md)
- Reasoning aloud or in code about specific post-2022 events (e.g., "we need a sleeve that handles 2023 banking stress", "the strategy should catch the 2024 NVDA rally")
- Tuning thresholds to known v1 outcomes (no `hyg_sma_len=50` because v1 used it; no `tnx_panic_rise=0.08` because v1 used it)
- Querying the held-out era during research — the guard will enforce this, but be vigilant in PR descriptions too

### 3.4 Anti-pattern ledger (carry-over constraints from v1)

These are inherited from `AUTONOMOUS_LOG.md`. Do not attempt them again — they're already triangulated dead ends.

1. Single-symbol shorts via signal `-2` on the same ticker as the long sleeve → engine pyramid bug (THIS IS WHAT YOU ARE FIXING IN PHASE 2; until fixed, do not use)
2. OR-gating two trend signals (iter031)
3. Lower-duration bond swaps as defensive sleeve (iter034, IEF; iter035, AGG implied)
4. Gold/gold-miner 3rd sleeves (iter032 GDX, iter033 GLD-trend implied)
5. Energy trend 3rd sleeves (iter039 XLE)
6. VIX-level binary gates (iter040)
7. Credit-spread gating at any single-SMA resolution (iter038 SMA60, iter041 SMA20)
8. More than 3 sleeves in a composite (regime overlap floor is structural)
9. Backtest window extensions (does not address binding constraint)
10. EC-family weight optimization (v1 already found local optimum at 40/60)

If your hypothesis falls into any of these, STOP and pick a different one.

---

## 4 — Phase 1: Setup (1 session)

### 4.1 Create the v2 branch in the private submodule

```bash
rtk git -C custom_strategies/private checkout research/autonomous-strategy-loop
rtk git -C custom_strategies/private pull origin research/autonomous-strategy-loop
rtk git -C custom_strategies/private checkout -b research/blind-design-v2
```

This is the working branch for all v2 work. Push it to remote immediately.

### 4.2 Implement the blind-design guard

Files to create:
- `helpers/blind_design_guard.py` — the guard module (~80 lines)
- `tests/test_blind_design_guard.py` — 4+ tests (see 3.2)
- `BLIND_DESIGN_PROTOCOL.md` — public methodology doc at project root
- `custom_strategies/private/AUTONOMOUS_LOG_V2.md` — new knowledge file for v2 (template structure: mirror v1's AUTONOMOUS_LOG.md sections)

Config changes in `config.py`:
- Add `BLIND_DESIGN_CUTOFF`: default `None`, set to `"2023-01-01"` for v2 runs
- Add `BLIND_DESIGN_UNLOCK`: default `False`

Wire the guard into `services/__init__.py` and into the parquet reader in `helpers/caching.py`. Every data-loading code path must respect the guard.

**Commit + push parent + private after this phase.**

### 4.3 Verify the guard works

Run a sanity backtest with the cutoff set and verify:
- Existing long-only strategies still run (using only pre-2023 data — they will produce slightly different metrics than v1, which is fine; this is the new control)
- Any attempt to load 2023+ data raises `BlindDesignViolation`
- Setting `BLIND_DESIGN_UNLOCK=True` bypasses cleanly

If the guard is broken, fix it before proceeding. Do not start Phase 2 with a broken guard.

---

## 5 — Phase 2: Engine fix (2–4 sessions)

### 5.1 The bug

Reference: `AUTONOMOUS_LOG.md` section "Engine pyramiding bug — single-symbol shorts compound uncontrollably". Demonstrated by ALT 1 strategy: produced **48 trillion %** P&L at allocation 1.0. The per-symbol engine compounds short positions on the same symbol without sizing controls.

### 5.2 The fix scope

Locate the bug:
- `helpers/portfolio_simulations.py` — daily loop, short-entry block
- Search for `short_positions` and signal `-2` handling

The fix:
- A symbol must hold at most ONE short position at a time, just like longs (already true for longs via `if symbol in positions: skip`)
- Add: `if symbol in short_positions: skip` to the short-entry block
- Position-sizing: `min(total_equity × allocation_pct, cash)` already exists for shorts but verify it works correctly with simultaneous long positions
- Add a regression test that runs a known short-heavy strategy at `allocation_per_trade=1.0` and asserts P&L does not exceed a sane multiple of buy-and-hold (e.g., < 100×)

### 5.3 Inverse-ETF compatibility

The engine fix also needs to support a cleaner pattern: **long inverse ETFs** (SH, PSQ, SDS) as long-only-compatible defensive instruments. These don't require the short-mechanism at all — they're just long positions on a different symbol.

Verify:
- Parquet data for SH, PSQ, SDS exists in `parquet_data/data/` (if not, fetch via the existing parquet pipeline)
- A simple test strategy "long SH when VIX > 30, flat otherwise" runs end-to-end without error
- The strategy uses signal `1`/`-1`/`0` (not `-2`)

### 5.4 Regression suite

Before declaring Phase 2 done, run the existing test suite:
```bash
rtk .venv/bin/pytest tests/ -x -q --tb=short 2>&1 | tail -50
```

All existing tests must pass. New tests must cover the short-fix.

Commit each meaningful change separately (guard, fix, tests, inverse-ETF support). Push after every commit.

---

## 6 — Phase 3: Strategy iteration (~6–8 sessions, ~20–25 iters)

### 6.1 Iteration mechanics

Each iter follows the v1 pattern:
1. Hypothesis (one paragraph)
2. Strategy spec (executable detail)
3. Implement (delegate to Sonnet subagent for the code; do not generate yourself)
4. Run backtest with `BLIND_DESIGN_CUTOFF="2023-01-01"` set
5. Capture verdict + ml_features.parquet
6. Composite scoring if applicable (use `scripts/composite_candidate_scorer.py`)
7. Commit + push per iter (both repos)
8. Append to `AUTONOMOUS_LOG_V2.md`

### 6.2 Per-session Opus QA gate

After every ~3 iters, spawn an Opus QA subagent (`subagent_type=general-purpose`, `model=opus`) with:
- Current champion roster (v2 only)
- Verdicts from the latest iters
- All v2 KILL reasons
- Request: (a) verdict on each iter, (b) next 3 iters with explicit hypotheses + kill criteria, (c) declare "v2 search exhausted" if no productive direction remains.

Treat Opus QA verdicts as authoritative. Do not second-guess.

### 6.3 Hypothesis source guidance

Start with the directions Opus QA flagged in v1's exhaustion verdict (these are blind-safe categories, not specific rule shapes — you still need to invent the rules):

- **Inverse-ETF defensive sleeves** — long SH/PSQ/SDS triggered by a NEW gate mechanism not in the v1 KILL ledger
- **Managed-futures/trend-following ETFs** (DBMF launched 2019; check data availability pre-2023)
- **Dynamic position-weighting** — regime-conditional sleeve weights instead of fixed 40/60 (requires a *leading* regime indicator that's not in the v1 KILL ledger)
- **Options-overlay alternative**: synthetic protective puts via inverse ETFs (e.g., 5% in SH continuously, rebalanced)

Note: the EC27+iter030 composite shape is forbidden as a starting point because it's frozen as v1 control. But the *concept* of multi-sleeve composites is blind-safe.

### 6.4 Champion criteria (unchanged from v1)

4-gate champion: R1 beats SPY, R2 smooth ≥ ACCEPTABLE, R3 MaxRcvry < 365d, R4 WFA Pass + MC ≥ 4.

5-gate composite co-champion: MaxRcvry < 365d, pairwise r < 0.40, Sharpe ≥ 1.10, TotalRet ≥ 2× SPY, regime overlap < 60%.

R3 is the gate v1 could not crack. The point of v2 is to crack it with the engine fix unlocking inverse-ETF defensive sleeves.

---

## 7 — Phase 4: Unlock + verify (1 session)

### 7.1 Trigger conditions

Execute Phase 4 only when:
- (a) Opus QA declares the BLIND search exhausted, OR
- (b) A v2 candidate has passed all 4 R-gates (or all 5 composite gates) on the 2004-2022 BLIND window

Do NOT unlock early. Do NOT unlock to "just peek" if things look promising. The whole point is that the unlock is a one-shot verification.

### 7.2 Unlock procedure

1. Set `BLIND_DESIGN_UNLOCK=True` in a dedicated config branch
2. Re-run the candidate(s) over the full 2004 → present window
3. Compute metrics for the held-out 2023+ window specifically
4. Apply the same R-gate or composite-gate criteria to the held-out window ALONE
5. PASS or FAIL — there is no third option
6. Commit the unlock event as a single labeled commit: `BLIND-UNLOCK: <candidate> on 2023+`
7. Append the unlock outcome to `AUTONOMOUS_LOG_V2.md`
8. Append the outcome to `GOLD_STRATEGY_LINKEDIN_THREAD.md` under a new section
9. Update `BLIND_DESIGN_PROTOCOL.md` with the outcome
10. Push both repos

### 7.3 Champion port

If PASS: open a signaldeckapi MR (pattern matches v1: scanner_config entry + stop_config + portfolio JSON + CHAMPION_COMPOSITE_V2.md). Run `/qa-cycle`. **DO NOT MERGE** without operator approval.

If FAIL: document the failure in `AUTONOMOUS_LOG_V2.md` and `BLIND_DESIGN_PROTOCOL.md`. Both v1 and v2 frozen at v1 shipping config. The honest scientific outcome.

---

## 8 — Stop conditions (when to halt and wait for operator)

Halt and write a status note (don't keep iterating) if:
1. Engine fix breaks any existing regression test that can't be cleanly resolved within 1 session
2. The blind-design guard cannot be cleanly wired into the data layer after 1 session of attempts
3. Opus QA declares v2 search exhausted before any candidate passes (no need to unlock — just document and stop)
4. You discover a v2 strategy idea that mechanically resembles a v1 KILL ledger entry that you didn't catch upfront
5. Any commit-push fails repeatedly (auth, hooks, etc.) — do not skip hooks with `--no-verify`
6. You hit a question that requires operator judgment (e.g., "is DBMF a reasonable instrument given its 2019 inception?")

When you halt, write a `HANDOFF_RESUME_v2_<date>.md` at project root with the current state and the question/blocker. Commit + push. Stop work.

---

## 9 — Commit message conventions

Parent repo (`autoresearch/poc`):
- `v2-setup: <thing>` — Phase 1 setup work
- `v2-engine: <thing>` — Phase 2 engine fix
- `v2-iter<NNN>: <thing>` — Phase 3 strategy iterations
- `v2-unlock: <outcome>` — Phase 4 unlock event

Private submodule (`research/blind-design-v2` branch):
- Same prefixes
- `AUTONOMOUS_LOG_V2.md` updates included in the iter's commit, never batched

All commits should be signed `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` (orchestrator) or `Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>` when delegating to Sonnet subagent for implementation.

---

## 10 — Where context lives (canonical references)

| Resource | What's in it |
|----------|-------------|
| `CLAUDE.md` (project root) | Project conventions, RTK rule, config reference |
| `custom_strategies/private/AUTONOMOUS_LOG.md` | v1 loop history (frozen — read only) |
| `custom_strategies/private/GOLD_STRATEGY_LINKEDIN_THREAD.md` | Public pressure-test that motivated v2 |
| `custom_strategies/private/AUTONOMOUS_LOG_V2.md` | v2 working log (you create + maintain) |
| `BLIND_DESIGN_PROTOCOL.md` (project root) | v2 public methodology (you create) |
| `helpers/blind_design_guard.py` | The cutoff guard (you create) |
| `helpers/portfolio_simulations.py` | Engine to patch in Phase 2 |
| `scripts/composite_candidate_scorer.py` | Composite scorer (unchanged from v1) |
| `output/runs/` (gitignored) | Run outputs; copy interesting ones into `iter_data/` per iter |
| `signaldeckapi` repo `/Users/zach/Desktop/gitlab/signaldeckapi/` | Forward-test deployment target |
| `signaldeckapi` MR !652 | v1 composite recipe MR (already open, awaiting operator review) |

---

## 11 — Quick-start prompt for a fresh session

Paste this into a new Claude Code session in this repo:

> Resume the v2 autonomous strategy loop from `HANDOFF_BLIND_DESIGN.md`. Execute pre-flight (Section 0), then Phases 1–4 in order. Operator is not present. Commit + push after every iter (both repos). Use Sonnet subagents for strategy implementation; Opus subagents for QA gates after every ~3 iters. Treat Opus QA verdicts as authoritative. Stop only when Phase 4 completes OR a halt condition fires (Section 8). Never merge to main on either repo without operator approval. RTK prefix on every shell command, no exceptions.

---

## 12 — Final notes on autonomy

You are running with the operator's full delegation. That is a trust posture, not a license. Specifically:

- **Be honest about negative results.** If a v2 candidate fails the gates, log it as a KILL with the full reasoning. The v1 KILL ledger has ~30 entries and was the strongest defense against the "cherry-pick" critique in the LinkedIn thread. Continue that discipline.
- **Do not "fix" the held-out era**. If the unlock fails, the unlock fails. Documenting an honest negative result is more valuable than fitting a positive one.
- **Do not rationalize past-cutoff awareness**. If you find yourself thinking "well I know 2023 had a banking crisis", that thought is itself contamination. Do not let it influence the rule shape. The protocol works only if you respect it.
- **Use the model tiers per operator's stated preference.** Opus is expensive — reserve for QA gates and judgment calls. Sonnet writes strategy code. Haiku handles trivial tooling (formatting, simple lookups).
- **If you're unsure, halt and write a resume note.** Better to wait for the operator than guess on a decision they care about.

This protocol is the operator's response to a real public critique. Executing it cleanly — including potentially producing a negative result — is the deliverable. Producing a positive result that the operator can't defend in front of the next Dmitrii is worse than producing nothing.

Good luck.
