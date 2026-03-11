# CLAUDE.md — july-backtester

> **RTK RULE — NON-NEGOTIABLE**: Every terminal command MUST be prefixed with `rtk`. No exceptions. This includes `rtk git`, `rtk grep`, `rtk pytest`, `rtk ls`, `rtk read`, etc. Bare `grep`, `git`, `pytest`, `find` etc. are FORBIDDEN in this project.

## What This Is
Python backtesting engine for US equities. Tests 20+ technical strategies across single symbols or large portfolios (Nasdaq, S&P 500, etc.) with Monte Carlo robustness scoring.

## Entry Points
- `main.py` — portfolio mode (default), multiprocessing across all CPU cores
- `main.py --mode single` — single-asset mode, all strategies vs `symbols_to_test`
- `main.py --name "run-name"` — optional prefix for report folder and S3 path

## Key Files
```
config.py                          # All settings — edit this before running
main.py                            # Single entry point (--mode portfolio|single --name)
helpers/indicators.py              # All strategy logic — add new strategies here
helpers/simulations.py             # Single-asset trade simulation engine
helpers/portfolio_simulations.py   # Multi-asset portfolio simulation engine
helpers/monte_carlo.py             # Monte Carlo robustness scoring
helpers/summary.py                 # Report generation, S3 upload
helpers/caching.py                 # Local Parquet cache (24h TTL)
helpers/aws_utils.py               # S3 upload helper (upload_file_to_s3); reads API key from env or .env via get_secret
helpers/timeframe_utils.py         # Converts '200d' → bar count for given timeframe
services/services.py               # Data provider factory (caching wrapper)
services/polygon_service.py        # Polygon.io REST API
services/norgate_service.py        # Norgate Data local API
services/yahoo_service.py          # Yahoo Finance via yfinance (no API key)
services/csv_service.py            # Local CSV files ({csv_data_dir}/{SYMBOL}.csv)
tickers_to_scan/                   # JSON ticker lists (nasdaq_100.json, sp-500.json, etc.)
```

## Config Quick Reference
```python
"data_provider": "polygon"         # or "norgate", "yahoo", "csv"
"csv_data_dir": "csv_data"         # only used when data_provider = "csv"
"polygon_api_secret_name": "POLYGON_API_KEY"  # AWS secret name OR .env key
"start_date": "2004-01-01"
"initial_capital": 100000.0
"timeframe": "D"                   # D, H, MIN, W, M
"timeframe_multiplier": 1          # e.g. 5 for 5-min bars
"symbols_to_test": ["AAPL"]        # single-asset mode
"portfolios": {"Nasdaq 100": "nasdaq_100.json"}  # portfolio mode
"allocation_per_trade": 0.10       # 10% equity per position
"stop_loss_configs": [{"type": "none"}]  # or {"type":"percentage","value":0.05}
"slippage_pct": 0.0005
"commission_per_share": 0.002
"min_trades_for_mc": 50
"num_mc_simulations": 1000
```

## Architecture Notes

**Multiprocessing design:** `init_worker` passes large DataFrames (SPY, VIX, TNX, portfolio data) into each worker process as globals at pool creation time. Tasks are small tuples — they do NOT contain DataFrames. Do not change this pattern; it avoids pickling large objects.

**Signal convention:** Strategy functions return a DataFrame with a `Signal` column: `1` = enter/hold long, `-1` = exit/flat, `0` = no change.

**Caching:** `helpers/caching.py` stores Parquet files in `data_cache/` keyed by `{symbol}_{start}_{end}_{timeframe}_{multiplier}.parquet`. TTL is 24h. Delete the folder to force a fresh fetch.

**API key resolution order** (in `helpers/aws_utils.py`): environment variable → `.env` file. No AWS Secrets Manager.

**Data fetcher signature:** `fetcher(symbol, start_date, end_date, config) -> pd.DataFrame | None`. Columns must be `Open, High, Low, Close, Volume` with a `Datetime` index.

## Adding a Strategy
1. Add a function to `helpers/indicators.py` that accepts a DataFrame and returns it with a `Signal` column.
2. Register it in the `STRATEGIES` dict in `main.py` (or the portfolio runner):
```python
"My Strategy Name": {
    "logic": my_strategy_logic,        # or partial(fn, param=value)
    "dependencies": [],                # add 'spy' or 'vix' if needed
    "params": {}                       # passed as **kwargs to logic func
}
```
3. If the strategy uses SPY or VIX data, add a wrapper function following the `strategy_ema_regime` pattern (accepts `df, **kwargs`) so it's pickle-safe for multiprocessing.

## Output Structure (Run-First / Experiment Tracking)

Every backtest produces a single run folder under `output/runs/`:

```text
output/
└── runs/
    └── <run_id>/                     # e.g. 2026-03-02_15-12-32 or myname_2026-03-02_15-12-32
        ├── logs/                     # Execution log: run_<timestamp>.log
        ├── raw_trades/               # Per-portfolio raw trade CSVs (save_individual_trades=True)
        │   └── <Portfolio_Name>/
        ├── analyzer_csvs/            # Renamed + mapped CSVs ready for report.py
        │   └── <Portfolio_Name>/
        ├── detailed_reports/         # PDFs / Markdown generated by report.py
        └── overall_portfolio_summary.csv
```

- `output/` is git-ignored.
- `report.py` auto-detects the run's `detailed_reports/` directory when given a path inside `analyzer_csvs/`. Pass `--output-dir` to override.
- S3 uploads (if configured) use the same `<run_id>/` prefix as the key root.

## Do Not Touch
- `helpers/indicators.py` strategy logic (all working correctly)
- `helpers/simulations.py` and `helpers/portfolio_simulations.py` simulation engines
- `helpers/monte_carlo.py`
- `tickers_to_scan/` JSON files
- The multiprocessing architecture (`init_worker`, `run_single_simulation`, `Pool`)

## Data Providers

### Yahoo Finance (`data_provider = "yahoo"`)

- **New file**: `services/yahoo_service.py` — uses `yfinance` (lazy import inside `get_price_data` so the library is optional for non-Yahoo users)
- **Dependency**: `yfinance` added to `requirements.txt`
- **Interval building**: `_build_interval(config)` maps `timeframe`/`timeframe_multiplier` → yfinance interval string (`"1d"`, `"1h"`, `"5m"`, `"1wk"`, `"1mo"`). Multiplier >1 on D/W/M falls back to base interval with a warning.
- **No API key** needed — free data, but quality/availability varies.
- **Mock pattern** in tests: yfinance is imported *inside* `get_price_data()` via `import yfinance as yf`, so patching `sys.modules["yfinance"]` in `patch.dict` intercepts the import on every call without needing to reload the module.

### CSV (`data_provider = "csv"`)

- **New file**: `services/csv_service.py` — reads `{csv_data_dir}/{SYMBOL}.csv` (case-insensitive).
- **Config key**: `csv_data_dir` (default `"csv_data"`, relative to project root). Add to `config.py` when switching providers.
- **Column normalisation**: case-insensitive; `Adj Close` / `Adjusted Close` → `Close`. Duplicate column names after rename (e.g. both `Close` and `Adj Close` present) are deduplicated by keeping the first occurrence: `df.loc[:, ~df.columns.duplicated(keep="first")]`.
- **Date parsing**: `pd.to_datetime()` with no explicit format — handles ISO, US slash format, and datetime strings with time components. Index is always converted to UTC.
- **Date filter**: rows outside `[start_date, end_date]` are dropped; returns `None` if result is empty.
- **Tests**: `tests/test_csv_service.py` — 32 tests, all using `tmp_path` real-file fixtures (no mocking of I/O).

### Wiring

Both providers are wired in `services/__init__.py` (`get_data_service` factory — the one actually used by `main.py`) and `services/services.py` (the caching wrapper, not currently called by main but kept consistent). New `elif provider == "yahoo"` and `elif provider == "csv"` branches import from the new modules via lazy local imports.

## Common Pitfalls
- `get_bars_for_period('14d', TIMEFRAME, MULTIPLIER)` — always use this for indicator periods, not raw integers, so strategies work across timeframes
- Stop-loss config is a dict `{"type": "none"}` or `{"type": "percentage", "value": 0.05}` — not a float
- `apply_stop_loss(df, stop_config)` takes the dict, not a percentage float
- Norgate portfolios use `"norgate:WatchlistName"` string prefix; JSON files use `"filename.json"`; inline lists use a Python list
- `execution_time: "open"` means signals are generated on day N and filled at day N+1 open — the simulator handles the 1-day lag via `prev_trading_dates`