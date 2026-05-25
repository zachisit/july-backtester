# Autonomous Loop Goal (set 2026-05-23)

## Goal

Use the previous strategy and knowledge context in the repo to try various strategy concepts to find a smooth and upward EC strategy that is not overfit. Varying range of ideas as you progress. Less indicators the better. Relying on other areas of the market to drive buy/sell signals the better. Rely on long only. Check with the LLM verdict. Commit and push before/during/and after each iteration to have repo up to date as you progress. Utilize the findings and data prior to this session to help shape your research. You are a quant tasked with finding the alpha in the markets and you have the tool and the token spend to figure this out. Utilize haiku and sonnet models for their ideal purpose to reduce token spend, and a QA opus model for judgement. You are the orchestrator. Also save this prompt to a local md file.

## Operational distillation

| Rule | What it means in practice |
|---|---|
| **Smooth & upward EC** | `smooth_verdict ∈ {SMOOTH, ACCEPTABLE}`. No multi-year plateaus. Up and to the right. |
| **Not overfit** | Prefer few parameters. Cross-asset signals over per-symbol indicators. Trade count ≥ ~50 so MC validates. Avoid `MC Verdict = N/A (few trades)`. |
| **Long only** | No signal=-2. Avoids the engine short-side pyramid (killed iter001/002). |
| **Cross-asset signals** | Buy X when Y does Z. e.g., long SPY when HYG/IEF ratio rising; long QQQ when TLT in uptrend. Symbol-A’s state drives Symbol-B’s entries. |
| **Few indicators** | Single trigger if possible. Two max. No 4+ filter stacks. |
| **LLM verdict gate** | Read `output/runs/<id>/llm_verdict.json` Strategy Verdict block after each run. Use as the authoritative pass/fail signal. |
| **Commit cadence** | Commit + push BEFORE strategy run (lock the plan), DURING (lock the code), AFTER (lock the data + verdict). Use the autonomous-strategy-loop branch on private submodule + autoresearch/poc on main. |
| **Sub-agent model selection** | Haiku → mechanical (file ops, reading CSVs, extracting numbers). Sonnet → strategy code, backtest analysis. Opus (me as orchestrator + spawned QA Opus when needed) → judgement, direction, kill/keep decisions. |

## Knowledge base to draw from

- `custom_strategies/private/AUTONOMOUS_LOG.md` — Session 1 (iter001-014). 14 KILLs. Key architectural findings recorded.
- `custom_strategies/private/RESEARCH_HANDOFF.md` — 5000-line history with EC champion development.
- `custom_strategies/private/research_results/composite_baseline_verdict.md` — composite scorer findings + R3 unbreakable conclusion.
- `custom_strategies/private/research_results/ec_final_champion.md` — declared daily-timeframe champion archetype.

## Initial iter queue

- **iter015 — Credit-risk-on:** Long SPY when HYG/IEF 60d ratio rising. Cross-asset (credit spreads → equity entry).
- **iter016 — Bond-uptrend gate on equities:** Long QQQ when TLT > TLT.SMA200. Cross-asset (bond momentum signal).
- **iter017 — Gold-vs-SPY ratio:** Long SPY when GLD/SPY < SMA200 of ratio (gold weak relative to equities = risk-on).
- **iter018 — Yield-curve proxy:** Long SPY when TNX > TNX.SMA200 AND TNX rising.
- **iter019 — VIX term-structure (if VIX3M data resolvable):** Long SPY when $VIX < $VIX3M (backwardation).
- **iter020 — Composite re-test:** best of {015-019} as a sleeve in the EC27+WR composite.

## Stopping

Same as Session 1 self-imposed: 8h wallclock OR 15 consecutive iterations without a novel finding, whichever first. The goal hook will block stopping until a smooth + upward + non-overfit strategy is found.
