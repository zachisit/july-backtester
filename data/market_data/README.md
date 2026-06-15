# Unified Market Data (Norgate history + Polygon daily patch)

**One clean source the backtester reads:** `data/market_data/merged/{symbol}.parquet`.
Norgate is authoritative through **2026-04-22**; Polygon patches **2026-04-23 →**.
Every row is total-return (Option A) and carries provenance. Full design:
[MERGE_SPEC.md](MERGE_SPEC.md) · adjustment policy: [metadata/price_adjustment_policy.md](metadata/price_adjustment_policy.md).

## Reading the data (backtester)

```python
from src.data.unified_market_data_provider import UnifiedMarketDataProvider
p = UnifiedMarketDataProvider()
df = p.get_price_data("AAPL", "2004-01-01", "2026-06-05")   # Open/High/Low/Close/Volume, Datetime index
prov = p.get_with_provenance("AAPL")                         # + source / adjustment_factor / method / status
```

`get_price_data` is a drop-in for the engine's `fetcher(symbol, start, end, config)` contract.

## Build from scratch (one-time)

```bash
# 1. classify the universe (reuses the cached Norgate scan + Polygon reference)
python -m src.data.pipeline.classification
# 2. pull Polygon (grouped daily 2026-04-08→latest + splits + dividends)
python -c "from src.data.pipeline import polygon_io as p, paths; p.pull_range(paths.OVERLAP_START,'YYYY-MM-DD'); p.pull_splits(); p.pull_dividends()"
# 3. build per-ticker patch + calibration (handled inside the daily updater too)
# 4. merge everything -> merged/
python scripts/build_merged_dataset.py
# 5. audit + approval report
python scripts/audit_merged_dataset.py
```

## Daily update (idempotent, safe to rerun)

```bash
python scripts/update_market_data.py --asof latest
```
Re-pulls a trailing 5-day window (catches Polygon revisions) + any new days, rebuilds
patch + affected merged tickers, runs the completeness gate + full audit, and writes
`audit/final_approval_report.md`. Exit code 0 = APPROVED, 1 = FAILED (fail-closed).

## Layout

| Folder | Contents |
|---|---|
| `polygon_raw/` | immutable API responses (`YYYY-MM-DD.json`, `corporate_actions/`, `indices/`) |
| `polygon_patch/` | per-ticker canonical patch (total-return adjusted), 2026-04-23 → |
| `merged/` | **the backtester source** — one file per symbol |
| `metadata/` | `symbol_classification.csv`, per-bucket lists, `price_adjustment_policy.md`, `merge_summary.json` |
| `audit/` | calibration, completeness gate, OHLC/duplicate/spike reports, `final_approval_report.md` |
| `logs/` | per-run logs |

## Provenance columns (in patch & merged)

`source` (norgate/polygon/local) · `adjustment_factor` · `adjustment_method`
(norgate_native / none / split / dividend / split+dividend) · `data_quality_status`
(ok / flagged / review_no_patch / identity_review / insufficient_history).
Raw Polygon price is recoverable as `close / adjustment_factor`.
