# RSI–Price Divergence Strategy — Research Results

**Origin:** Built live on stream — https://lightwaterdispatch.com/dispatch/rsi-divergence-strategy-livestream/
**Runs:** 2026-07-21 (Polygon, weekly & daily, Nasdaq 100)
**Status:** Research / negative result. **Do not trade.** Both variants lag SPY & QQQ buy-and-hold once data is properly adjusted.

---

## The idea

Classic regular RSI/price divergence, long-only:

- **v1 (`RSI Divergence (14)`)** — buy on a confirmed *bullish* divergence (price lower low, RSI higher low); exit on the opposite *bearish* divergence. Fractal-pivot confirmation makes it look-ahead safe.
- **v2 (`RSI Divergence v2 (Trend+Confirm)`)** — three fixes over v1: (1) no exit-on-strength — ride a **2.0× ATR(14) trailing stop** + a trend-break backstop (`close < SMA`); (2) only enter when **SPY > its 200-day/40-week SMA** (regime filter); (3) require a **breakout above the intervening swing high** before entering.

## Test setup (livestream config)

| Setting | Value |
|---|---|
| Data provider | Polygon |
| Universe | Nasdaq 100 (current members — see caveats) |
| Timeframe | Weekly (`W`) primary; daily (`D`) cross-check |
| Configured period | 2003-01-01 → 2026-12-31 |
| **Actual data period** | **2021-07-31 → 2026** (Polygon plan cap — see caveat #2) |
| Initial capital | $100,000 |
| **Position sizing** | **Fixed — 10% of equity per position** (`allocation_per_trade: 0.10`, `position_sizing_method: fixed`) |
| **Stop / exit** | **2.0× ATR(14) trailing stop** (no fixed take-profit) |
| Execution | Signal on bar N, filled at next bar's **open** |
| Price adjustment | `total_return` (split + dividend adjusted) |
| Survivorship | `include_delisted: false` |

## Headline results (weekly, total-return adjusted — the trustworthy run)

Benchmarks over the **actual** (2021-07 → 2026) period: **SPY B&H +70.2%**, **QQQ B&H +92.7%**.

| Strategy | P&L | vs SPY | vs QQQ | Max DD | Sharpe | Calmar | Profit Factor | Win % | Trades | MC |
|---|---|---|---|---|---|---|---|---|---|---|
| v1 — RSI Divergence (14) | **+13.7%** | −56.5pp | −79.0pp | 36.9% | 0.01 | 0.07 | 1.10 | 35.5% | 290 | Robust (5) |
| v2 — Trend+Confirm | **+29.6%** | −40.6pp | −63.2pp | 12.2% | 0.08 | 0.43 | 1.66 | 38.6% | 88 | Robust (5) |

**Verdict:** v2's fixes are real improvements — DD cut from 37% → 12%, profit factor 1.10 → 1.66, Calmar 0.07 → 0.43 — but **neither beats buy-and-hold.** You gave up ~40–80pp of return for a smoother-but-still-losing ride. Daily timeframe is worse (v1 −25%, v2 +19%, both deeply lagging).

## ⚠️ Data-integrity finding (why you cannot trust the raw number)

The **first** weekly run (before `price_adjustment: total_return` was switched on) reported **+444%, beating SPY by +374pp.** That number is an artifact: on raw/split-only prices the engine takes **phantom split-jump trades** — a 4:1 split looks like a −75% crash and a buy-the-dip strategy "buys" it. Turning on total-return adjustment collapsed the same strategy to **+13.7%.**

| Run | Price adjustment | v1 P&L | vs SPY |
|---|---|---|---|
| `weekly_nq100_13-32-31` | none / split-only | **+444.4%** | +374pp |
| `weekly_ADJ_14-09-41` | total_return | **+13.8%** | −56pp |

A **30× swing** from one config flag. This is the single most important lesson from the stream: **always run on total-return-adjusted data.**

## Caveats — can you trust the rest of the data?

1. **Survivorship bias.** Universe = *today's* Nasdaq 100 members (`include_delisted: false`). Dropped/delisted names are absent, so results are biased upward. Not corrected here.
2. **Polygon plan history cap.** Config says 2003, but Polygon only returned data from **2021-07-31**. The equity-curve x-axis reads 2022→2026 *not* because of a code bug but because that's all the history the plan provides. Any "20-year backtest" claim is really a ~4.5-year one.
3. **Small sample.** ~4.5 years, one regime cluster (2022 bear → 2023–25 bull). v2 has only 88 trades. WFA "Pass" and MC "Robust" are encouraging but thin.
4. **Both smoothness verdicts = ROUGH.** Equity curves are choppy.

## Files

- `results/weekly_v1_vs_v2_summary.csv` — canonical weekly head-to-head (adjusted)
- `results/weekly_v1_UNADJUSTED_summary.csv` vs `results/weekly_v1_total_return_ADJ_summary.csv` — the 444% → 14% collapse
- `results/daily_v1_vs_v2_summary.csv` — daily cross-check
- `results/detailed_report_v1_weekly.md`, `results/detailed_report_v2_weekly.md` — full tearsheets
- `results/weekly_v1_vs_v2_config_snapshot.json` — exact config
- `results/weekly_v1_vs_v2_llm_verdict.json` — machine verdict + equity curve (starts 2021-07-31)
