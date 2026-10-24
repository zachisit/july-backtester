# Unified Market Data — Access Guide (for handoff to Codex / external tools)

One clean source for the backtester. Norgate history (≤ 2026-04-22) + Polygon daily
patch (2026-04-23 →), total-return forward-adjusted (Option A). Audited & APPROVED;
validated bit-identical to the Norgate master on history. See `audit/final_approval_report.md`
and `audit/reverification_report.md`.

## Location

```
C:\Users\shard\Light Water Internship\july-backtester\data\market_data\merged\
```
- **35,310 parquet files · 2.82 GB · one file per symbol**: `{SYMBOL}.parquet` (uppercase).
- Delisted symbols carry a date suffix, e.g. `ONCR-200807.parquet` (survivorship-bias-free set).
- Indices & required assets are in the SAME folder: `SPY QQQ IWM DIA XLF VIX TNX SPX NDX RUT DJI OEX VXN GLD SLV TLT IEF HYG LQD UUP`.

## Recency (as of 2026-06-05)

- Polygon patch window = **2026-04-23 → 2026-06-05** (31 trading days), the "recent" tail.
- **97.1%** of live names (11,513 / 11,853) have a bar on 2026-06-05. Examples:
  SPY 737.55 · QQQ 705.06 · AAPL 307.62 · NVDA 205.34 · GLD 396.24 · TLT 85.71 ·
  VIX 21.51 · TNX 45.36 (10y yield ×10) · SPX 7383.74 · NDX 28957.60.
- Symbols that delisted/halted inside the window end earlier (intended).

## Schema (each parquet)

Index: tz-naive `DatetimeIndex` at midnight. Columns:

| Column | Notes |
|---|---|
| `open high low close volume vwap` | **lowercase**, float64. `close` = total-return adjusted |
| `source` | `norgate` (≤2026-04-22) / `polygon` (after) / `local` |
| `adjustment_factor` | **raw price = `close / adjustment_factor`** |
| `adjustment_method` | `norgate_native / none / split / dividend / split+dividend` |
| `security_type` | granular Polygon type (`CS`/`ETF`/`ETV`/`ADRC`/`UNIT`/`WARRANT`/`PFD`/`FUND`…), or `equity_or_etf` for Norgate-only rows, or `index` for the 8 indices |
| `data_quality_status` | `ok / flagged / review_no_patch / identity_review / insufficient_history` |

⚠️ Raw parquet columns are **lowercase**. The project's strategies expect **Capitalized**
`Open/High/Low/Close/Volume` — rename (snippet below) or use the provider.

## Reading it — zero-dependency (only pandas + pyarrow)

```python
import os, pandas as pd
MERGED = r"C:\Users\shard\Light Water Internship\july-backtester\data\market_data\merged"

def load(symbol, start=None, end=None, capitalized=True, ohlcv_only=True):
    df = pd.read_parquet(os.path.join(MERGED, f"{symbol}.parquet"))
    if start: df = df[df.index >= pd.Timestamp(start)]
    if end:   df = df[df.index <= pd.Timestamp(end)]
    if ohlcv_only: df = df[["open","high","low","close","volume"]]
    if capitalized:
        df = df.rename(columns={"open":"Open","high":"High","low":"Low","close":"Close","volume":"Volume"})
        df.index.name = "Datetime"
    return df

aapl = load("AAPL", "2015-01-01")     # recent strategies: just set a start date
spy, vix = load("SPY"), load("VIX")
```

## Reading it — in-repo provider (drop-in, returns Capitalized OHLCV)

```python
from src.data.unified_market_data_provider import UnifiedMarketDataProvider
p = UnifiedMarketDataProvider()
df   = p.get_price_data("AAPL", "2015-01-01", "2026-06-05")  # engine fetcher contract
prov = p.get_with_provenance("AAPL")                          # + source/factor/method/status
syms = p.available_symbols()                                  # all 35,310
```

## Choosing a universe

`metadata/symbol_classification.csv` = every symbol + `bucket` + `polygon_ticker` + `security_type`.
`bucket == "common_to_both"` (11,853) is the **current** liquid set — fine for a *current* scan,
but **survivorship-biased if applied over history** (see next section). Pre-built lists live in
`tickers_to_scan/*.json` (`nasdaq_100.json`, `sp-500.json`, `dow-jones-industrial-average.json`, …)
— these too are **current snapshots only**.

```python
import pandas as pd, json
cls = pd.read_csv(r"...\data\market_data\metadata\symbol_classification.csv", keep_default_na=False, na_values=[""])
universe = cls[cls.bucket=="common_to_both"].symbol.tolist()
nas100   = json.load(open(r"...\tickers_to_scan\nasdaq_100.json"))
```

## Survivorship bias — TWO separate axes (read before backtesting indices)

This dataset removes **price** survivorship bias (22,402 delisted names are kept). It does
**not** by itself remove **index-membership** survivorship bias. They are different problems:

| Axis | Handled by | If you ignore it |
|---|---|---|
| Price (delisted names have data) | the merged set itself ✅ | backtest only ever sees winners that survived |
| Index membership (who was *in* NQ/SP on date X) | the PIT layer below ⬇ | you hold *today's* members back in 2010 |

⚠ The static `nasdaq_100.json` (101) / `sp-500.json` (503) are **current membership only**.
Using them over history is membership-biased — they omit **475** names that were S&P 500
members at some point 2004→now.

### Point-in-time (survivorship-bias-free) membership — real & wired into `main.py`

Set the portfolio *value* (in `config.py → portfolios`) to one of:

| Value | Meaning | Source it needs |
|---|---|---|
| `"sp500_pit"` | UNION of all S&P 500 members in `[start,end]` | `SP500-Survivorship-bias-data-2004-2026/` → `SP500_DATA_ROOT` in `.env` |
| `"nq100_pit"` | UNION of all Nasdaq-100 members in `[start,end]` | `data/nq100_membership.parquet` (bundled in repo) |
| `"pit:sp500"` / `"pit:nq100"` | members **as of** `start_date` (single snapshot) | same as above |

- S&P union 2004→2026 = **978** names; real changes through **2026-01-14** (not frozen).
- NQ100 union 2004→2026 = **287** names; daily snapshots through **2026-04-30**.
- **Price coverage of those members — two honest numbers** (verify with
  `python scripts/verify_pit_span_coverage.py`):

  | Metric | S&P 500 | NQ100 | What it means |
  |---|---|---|---|
  | `exists` | 99.2% | 98.6% | every membership spell resolves to a merged file |
  | `covers_start` | 98.0% | 95.7% | every resolved era begins by its spell's join date |
  | `covers_span` | **96.0%** | **94.3%** | every spell is covered at both ends — **use this** |

  ⚠ Do **not** quote the 99% `exists` figure as "coverage": a file resolving is not the
  same as it covering the right *period*. ~5% of members have a file that starts after they
  joined or is a recycled-ticker second era (e.g. SanDisk SNDK 2004–16 then 2025–, Crane CR).
  An old→new alias map (`helpers/point_in_time.py::PIT_TICKER_NORMALISATION`, e.g. UTX→RTX,
  ANTM→ELV, FB→META, YHOO→AABA) is applied in BOTH the snapshot and union paths
  (`helpers/pit_universe.py`); the provider resolves date-suffixed delisted files
  (`AABA-201910`), share-class dash/dot (`BRK-B`↔`BRK.B`), AND **picks the era whose data
  covers the requested window** for recycled tickers (date-aware `_resolve`). Names with **no
  merged file at all** (ENDP, JCP, SIVB, TUP, WIN, MMC, ATGE, PARA, MERQE, QRTEA, RHAT) cannot
  be recovered by any alias.

### Daily PIT enforcement — avoid "holding today's members back in 2010"

The union/as-of universe lists tell the engine *which* tickers to run, not *when* each was a
member. A naive cross-sectional strategy could pick a future constituent too early.
`pit_enforce_daily` defaults to `True`, and main.py refuses to run a PIT portfolio when it is
disabled or when membership intervals cannot be loaded:

- `helpers.pit_enforcement.membership_intervals(value, config)` → `{ticker: [(join, leave), …]}`
  contiguous spells, so a name that left and rejoined the index is two intervals (the gap is
  **not** silently filled).
- Each symbol gets a boolean `_pit_member` column (`build_member_mask`). The simulator checks it
  on the actual execution date, blocks entries outside membership, and liquidates an existing
  position at the first non-member open.
- Warm-up bars (`pit_warmup_days`, default 400) and a post-leave liquidation buffer
  (`pit_exit_buffer_days`, default 10) remain available. If no timely post-leave bar exists,
  `_pit_force_exit` closes the position on the last available member-day close.
- With `data_provider: "merged"`, each membership spell resolves independently and the selected
  parquet eras are combined. Recycled names such as SNDK, CEG, and DELL retain both eras.

### Raw (unadjusted) prices

`merged/` prices are total-return adjusted; after a post-anchor split/dividend they diverge from the
unadjusted print. To read the raw unadjusted price (e.g. for display or external comparison), use the
RAW interface, never `get_price_data`:

```python
p.get_raw_price_data("CVNA", "2026-05-01", "2026-06-05")  # = canonical / adjustment_factor
p.get_execution_price("CVNA", "2026-06-05")               # scalar raw close (e.g. 66.51, not 332.55)
```

### Quality / liquidity screen (quarantined + micro-cap data)

```python
kept, dropped = p.filter_universe(universe, min_bars=250, min_avg_dollar_volume=5_000_000)
# drops insufficient_history / review_no_patch / identity_review / flagged,
# short series, and illiquid micro-caps. p.quality_status(sym) returns the per-symbol flag.
```

`filter_universe` is a provider-level utility — it is **not yet wired into the backtest engine**.
main.py does not apply it automatically and writes no data-screen file yet; a fail-closed auto-screen
for `data_provider: "merged"` is reserved for a future integration PR (see helpers/pit_enforcement.py
"Integration status"). Until then, call `filter_universe` explicitly to pre-screen a universe.

### Authoritative counts — `metadata/dataset_manifest.json`

Use this (single ground-truth pass: timestamp + git commit) for any count. It supersedes
`merge_summary.json` (write-time return counts) and the standalone insufficient-history CSVs,
which came from different pipeline states and disagree. `classification_bucket_counts` = classified
rows; `bucket_counts_materialized` = what actually landed in `merged/`. Regenerate with
`python scripts/build_dataset_manifest.py` (or it's written atomically by the audit).

```python
# survivorship-bias-free S&P 500 universe + its prices from merged/
from helpers.pit_universe import get_sp500_tickers_in_period
SP500_REPO = r"C:\Users\shard\Light Water Internship\SP500-Survivorship-bias-data-2004-2026"
universe = get_sp500_tickers_in_period("2004-01-01", "2026-06-05", SP500_REPO)   # 978 names
frames = {t: load(t) for t in universe
          if os.path.exists(os.path.join(MERGED, f"{t}.parquet"))}              # ~937 have prices
```

> **Remote Codex:** membership cannot be reconstructed from `merged/` alone. Ship the merged
> subset **plus** the `SP500-Survivorship-bias-data-2004-2026/` repo and
> `data/nq100_membership.parquet`, or use the static current lists and accept the bias.

## Adjustment gotcha

Prices are forward-adjusted to the 2026-04-22 anchor, so a post-anchor split name (e.g. CVNA 5:1
on 05-08) shows a *scaled* canonical price vs a broker quote — correct for return continuity. The
actual traded price is always `close / adjustment_factor`. Returns/signals are unaffected by a
constant scale, so backtests are apples-to-apples.

## Packaging for a remote Codex

Same machine → point at the path above (no copy). Remote → subset to a universe + indices
(e.g. nasdaq_100 + sp-500 + SPY/QQQ/VIX/TNX ≈ a few hundred MB) and zip that rather than the full 2.82 GB.
