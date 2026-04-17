# EC-R16: ETF-Only Universe Test — REGRESSION (Too Few Trades)
**Date:** 2026-04-17
**Run ID:** ec-r16-etf-only_2026-04-17_14-57-54

## Hypothesis
Use only 16 sector ETFs (no individual stocks): ITA, IYR, IBB, XLI, XLE, XLF, IHI, XLP,
XLB, XOP, XLU, XLY, XRT, ITB, GDX, XLK. ETFs are inherently diversified — no single-stock
outlier trades like BA +145% are possible.

## Results

| Strategy | Calmar | Sharpe | MaxDD | OOS P&L | Trades | WFA |
|---|---|---|---|---|---|---|
| MA Bounce + Low-Vol (2.5% ATR) @ ETF-16 | 0.14 | -0.61 | 11.17% | +7.80% | 1949 | Pass |
| SMA200 + Low-Vol (2.5% ATR) @ ETF-16 | 0.25 | -0.26 | 12.27% | +25.18% | 1920 | Pass |

Both MC Score 5, WFA Pass (3/3).

## Why EC-R16 Failed

**Insufficient trade count — same cash drag problem as EC-R15:**
- 16 ETFs vs 46 symbols → ~57% fewer symbols → ~52% fewer trades (1949 vs 4089)
- With ATR < 2.5% filter applied, fewer ETFs pass → even fewer valid setups
- Same cash drag issue: CAGR falls below 5% risk-free hurdle → negative Sharpe

**RS(min) anomaly (−878):** Some 126-bar windows have near-zero portfolio return variance
(e.g., no positions held), causing rolling Sharpe to blow up. This is a numerical artifact
of rolling Sharpe on low-activity periods, not a real strategy behavior.

**OOS P&L near-zero:** +7.80% OOS for MA Bounce is practically flat — the strategy barely
works out-of-sample on 16 ETFs.

**ETF volatility profile vs ATR filter mismatch:**
- Several ETFs in the 16-symbol universe are high-vol: GDX, XOP, XLE (energy/mining)
- ATR filter removes these, leaving only 8-10 ETFs at most as valid setups
- 8-10 symbols with MA Bounce gives too few concurrent opportunities

**Verdict:** ETF-only universe is too small. The individual stock diversity in the 46-symbol
universe (sectors+DJI) is what makes MA Bounce + Low-Vol work — 30 DJI stocks provide
most of the trade volume.

## Key Insight

**The 46-symbol (sectors+DJI) universe is correctly sized for this strategy:**
- 46 symbols + ATR filter → ~20-25 valid names at any time
- Enough for ~15-20 concurrent positions at 5% allocation (75-100% invested)
- ETF-only (16 → 8-10 after filter) leaves the portfolio chronically under-invested

## Direction

Keep the 46-symbol universe. Do not try narrower universes.
If single-stock outliers (BA, etc.) are the concern, address via position-level controls
rather than universe restriction.
