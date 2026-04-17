# EC-R13: Smooth Architecture Test — SMA200 Filter, Low-Vol MA Bounce, EMA Trend
**Date:** 2026-04-17
**Run ID:** ec-r13-verbose_2026-04-17_14-44-41
**Universe:** Sectors+DJI 46, 2004-2026, 5% allocation (20 positions max)
**Hypothesis:** Eliminate high-volatility stock selection (not just reduce position size) to fix jagged curves.

## Results

| Strategy | Calmar | MaxDD | MaxRcvry | Sharpe | RS(avg) | OOS P&L | Trades |
|---|---|---|---|---|---|---|---|
| SMA200 Universe Filter + SPY SMA96 Gate | 0.61 | 16.72% | 892d | 0.48 | 0.45 | +519% | 2616 |
| MA Bounce + Low-Vol ATR Filter + SPY SMA96 | 0.47 | 19.49% | 1151d | 0.88 | 0.06 | +179% | 4089 |
| EMA21/63 Trend + SMA200 + SPY SMA96 Gate | 0.55 | 16.42% | 903d | 0.63 | 0.41 | +472% | 2812 |

All 3: MC Score 5, WFA Pass (3/3).

Note: SMA200 Filter and EMA21/63 Trend show r=0.96 correlation — nearly identical strategies.

## Visual Assessment (PDF Tearsheets)

**SMA200 Universe Filter** — Still shows staircase pattern with large vertical jumps, especially 2020 COVID recovery and 2023/2025 big months. Not smooth. The strategy holds all above-SMA200 names but "all names above SMA200" move together during market rallies → correlated jumps.

**EMA21/63 Trend** — Nearly identical to SMA200 filter visually (r=0.96 confirmed). Discard as redundant. Same staircase problem.

**MA Bounce + Low-Vol ATR Filter** — **BEST VISUAL RESULT SO FAR.** The curve is noticeably more gradual with smaller step sizes:
- Avg winning trade $551 vs $1,316 for SMA200 filter (3x smaller per-trade impact)
- Sharpe 0.88 (highest in all EC research) — daily P&L consistency IS visual smoothness
- 2016-2021 section is a clean, steady upward slope
- Remaining issues: 2015-2016 has a 1055-day drawdown plateau, and a few outlier trades (BA +145%) still cause occasional jumps
- Post-2021: some roughness but much less than momentum strategies

## Key EC-R13 Finding

**The Sharpe ratio (annualized, portfolio-level) is the best metric proxy for visual smoothness.** MA Bounce + Low-Vol has Sharpe 0.88 — the highest of all EC strategies — and the visually smoothest curve.

Previous research optimized for Calmar (CAGR/MaxDD), but Calmar misses day-to-day roughness. The Sharpe at portfolio-level captures daily variance, which directly corresponds to visual jitter.

**Future EC research should target: Sharpe > 1.0 at portfolio level** (not just trade-level).

## Structural Insights

**Why MA Bounce + Low-Vol is smoother:**
- Avg winning trade $551 vs $1,639 (PM v3 at 10%) — 3x smaller individual impact
- 4,089 trades over 21 years = 190/year = ~16/month = very distributed profit recognition
- Low-vol filter excludes NVDA-type explosive names: top symbols by profit are AAPL, CAT, AMZN, GS, BA — all relatively stable blue chips
- Mean-reversion logic (bouncing to 50d MA) captures modest recoveries, not explosive breakouts

**Why SMA200 Filter is still jagged despite high position count:**
- When all 46 symbols rise above SMA200 simultaneously (strong bull market), ALL enter at once
- Their correlated gains produce the same "staircase" pattern — just more diversified, not more gradual
- The market regime switch (all-in vs all-out) dominates over individual stock smoothness

## Direction for EC-R14

**Primary hypothesis:** Combine SMA200 Universe Filter entry logic with the Low-Vol ATR filter.
- Entry: symbol above SMA200 AND ATR_14/Close < 2.5% AND SPY > SMA96
- This retains high position count benefit while excluding high-vol names that cause correlated spikes
- Expected: removes NVDA, GDX, XOP, XLE (high-vol) while retaining XLU, XLI, JNJ, WMT (low-vol)

**Secondary hypothesis:** MA Bounce + lower ATR threshold (1.5% instead of 2.5%).
- Hypothesis: current 2.5% still admits enough volatile names for occasional jumps
- Tighter filter may improve smoothness further at cost of fewer trades

**Also test:** MA Bounce + Low-Vol on ETF-only universe (no individual stocks).
- 16 sector ETFs are inherently diversified instruments
- Should eliminate BA/GS/NVDA single-stock outlier trades entirely

## Research Decision

EC-R13 winner: **MA Bounce + Low-Vol ATR Filter** — confirmed as architecturally correct approach.
Target for EC-R14: **Sharpe > 1.0** at portfolio level (new primary metric, replaces Calmar-only focus).
Next run: EC-R14 with SMA200+LowVol combined strategy, and MA Bounce + tighter ATR threshold.
