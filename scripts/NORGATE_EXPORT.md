# Norgate → Parquet Export Guide

## Full database dump (recommended)

To get a complete 1:1 copy of all Norgate data locally, run these three commands in order.
Use `--start-date 1990-01-01` — Norgate's earliest available data for most US equities.
Symbols with IPOs after 1990 automatically start from their first available date.

```bash
# Step 1 — All currently listed US equities (~13,930 symbols)
python scripts/norgate_to_parquet.py --database "US Equities" --output-dir parquet_data/data --start-date 1990-01-01

# Step 2 — All delisted / historical US equities (~20,873 symbols)
python scripts/norgate_to_parquet.py --database "US Equities Delisted" --output-dir parquet_data/data --start-date 1990-01-01 --skip-existing

# Step 3 — US and World indices (~1,615 symbols: VIX, SPX, TNX, sector indices, etc.)
python scripts/norgate_to_parquet.py --database "US Indices" --output-dir parquet_data/data --start-date 1990-01-01 --skip-existing
```

`--skip-existing` on Steps 2 and 3 skips any file already written — no duplicate work.

## Refreshing data

To update existing files with the latest bars, re-run without `--skip-existing`.
Omitting the flag overwrites every file with fresh data from Norgate.

```bash
python scripts/norgate_to_parquet.py --database "US Equities" --output-dir parquet_data/data --start-date 1990-01-01
```

## Other useful options

```bash
# Single watchlist (e.g. for a targeted refresh)
python scripts/norgate_to_parquet.py --watchlist "S&P 500" --output-dir parquet_data/data --start-date 1990-01-01

# Specific tickers only
python scripts/norgate_to_parquet.py --tickers AAPL MSFT NVDA --output-dir parquet_data/data --start-date 1990-01-01

# List all available databases
python -c "import norgatedata; print(norgatedata.databases())"

# List all available watchlists
python -c "import norgatedata; print(norgatedata.watchlists())"
```

## Validating the export

After running all three steps, verify that every Norgate symbol has a local Parquet file:

```bash
python scripts/validate_norgate_export.py
```

Reports per-database counts (Norgate vs local) and lists any missing symbols.
If anything is missing, fetch just those symbols:

```bash
python scripts/norgate_to_parquet.py --tickers AIMN DCBG --output-dir parquet_data/data --start-date 1990-01-01
```

Then re-run the validator to confirm `STATUS: ALL PRESENT`.

## Notes

- Output: one `.parquet` file per symbol in `parquet_data/data/` (e.g. `AAPL.parquet`, `$VIX.parquet`)
- Index symbols use Norgate's native `$` prefix (e.g. `$VIX`, `$SPX`) — no sanitization needed
- Each file has columns `Open, High, Low, Close, Volume` with a UTC DatetimeIndex
- Price adjustment: Total Return (split- and dividend-adjusted) — Norgate default
- To use the exported data: set `data_provider: "parquet"` in `config.py` (default dir is `parquet_data/data`)
