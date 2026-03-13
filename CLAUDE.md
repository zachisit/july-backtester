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
helpers/indicators.py              # All strategy signal logic — do not touch
helpers/registry.py                # Strategy registry: register_strategy decorator, load_strategies, get_active_strategies
helpers/simulations.py             # Single-asset trade simulation engine
helpers/portfolio_simulations.py   # Multi-asset portfolio simulation engine
helpers/monte_carlo.py             # Monte Carlo robustness scoring
helpers/summary.py                 # Report generation, S3 upload
helpers/wfa.py                     # Walk-Forward Analysis (get_split_date, split_trades, evaluate_wfa)
helpers/correlation.py             # Strategy correlation matrix (run_correlation_analysis, compute_avg_correlations)
helpers/caching.py                 # Local Parquet cache (24h TTL)
helpers/aws_utils.py               # S3 upload helper (upload_file_to_s3); reads API key from env or .env via get_secret
helpers/timeframe_utils.py         # Converts '200d' -> bar count for given timeframe
custom_strategies/                 # Plugin directory — drop *.py files here to add strategies
custom_strategies/sma_crossovers.py  # Active strategies: SMA Crossover (20d/50d) and (50d/200d)
services/services.py               # Data provider factory (caching wrapper)
services/polygon_service.py        # Polygon.io REST API
services/norgate_service.py        # Norgate Data local API
services/yahoo_service.py          # Yahoo Finance via yfinance (no API key)
services/csv_service.py            # Local CSV files ({csv_data_dir}/{SYMBOL}.csv)
tickers_to_scan/                   # JSON ticker lists (nasdaq_100.json, sp-500.json, etc.)
scripts/                           # One-off diagnostic and utility scripts (NOT part of the pipeline)
scripts/debug_data.py              # Compares Polygon vs Yahoo SPY data; run with: python scripts/debug_data.py
```

## Scripts Directory

`scripts/` houses temporary, diagnostic, and utility scripts that are not part of the main backtesting pipeline. Scripts here must add the project root to `sys.path` using `os.path.dirname(os.path.dirname(os.path.abspath(__file__)))` (one extra `dirname` level vs scripts at the root). Put any new debug tools, one-off data inspectors, or utility helpers here rather than at the project root.

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
"wfa_split_ratio": 0.80          # 0.80 = 80% IS / 20% OOS; None or 0 = disabled
```

## Architecture Notes

**Multiprocessing design:** `init_worker` passes large DataFrames (SPY, VIX, TNX, portfolio data) into each worker process as globals at pool creation time. Tasks are small tuples — they do NOT contain DataFrames. Do not change this pattern; it avoids pickling large objects.

**Signal convention:** Strategy functions return a DataFrame with a `Signal` column: `1` = enter/hold long, `-1` = exit/flat, `0` = no change.

**Caching:** `helpers/caching.py` stores Parquet files in `data_cache/` keyed by `{symbol}_{start}_{end}_{timeframe}_{multiplier}.parquet`. TTL is 24h. Delete the folder to force a fresh fetch.

**API key resolution order** (in `helpers/aws_utils.py`): environment variable → `.env` file. No AWS Secrets Manager.

**Data fetcher signature:** `fetcher(symbol, start_date, end_date, config) -> pd.DataFrame | None`. Columns must be `Open, High, Low, Close, Volume` with a `Datetime` index.

## Adding a Strategy (Plugin System)

`strategies.py` no longer exists. All active strategies live in `custom_strategies/`. No core files need editing.

1. Add signal logic to `helpers/indicators.py` (or inline it in the plugin file).
2. Create a `.py` file in `custom_strategies/` and decorate your function:

```python
# custom_strategies/my_strategy.py
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import my_logic_function
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)

@register_strategy(
    name="My Strategy Name",
    dependencies=[],          # add "spy" or "vix" if needed
    params={
        "length": get_bars_for_period("20d", _TF, _MUL),
    },
)
def my_strategy(df, **kwargs):
    return my_logic_function(df, length=kwargs["length"])
```

3. Run `python main.py --dry-run` — the strategy appears in `Strategies: N` with no other changes needed.

**If the strategy needs SPY or VIX data:** declare `dependencies=["spy"]` or `dependencies=["vix"]`. The engine injects `spy_df` / `vix_df` into `**kwargs` automatically. No wrapper function needed — the decorated function IS the wrapper.

**Active strategies public API:** `from helpers.registry import get_active_strategies` — returns `{name: {logic, dependencies, params}}`. This is what `main.py` uses instead of the old `STRATEGIES` dict.

**Strategy selection filter:** `CONFIG["strategies"]` controls which registered plugins are returned by `get_active_strategies()`. Set to `"all"` (default) to run everything, or a list of exact names to run a subset. Any requested name not found in the registry logs a `[WARNING]` and is skipped — a typo will not crash the run. Implemented via lazy `from config import CONFIG` inside `get_active_strategies()` to avoid a circular import.

**Sub-daily strategy guard:** Strategies using `get_bars_for_period("Nmin", ...)` are wrapped in `if _TF == "MIN":` at module level so they are not registered (and do not raise `ValueError`) when `timeframe = "D"`.

**Plugin library:** All legacy `_STATIC_STRATEGIES` entries have been migrated to:

- `custom_strategies/rsi_strategies.py` — RSI Mean Reversion (14/30), (7/20), w/ SMA200 Filter, 1m Extreme Fade
- `custom_strategies/macd_strategies.py` — MACD Crossover, MACD+RSI Confirmation, all EMA Crossover variants (Unfiltered, SPY-only, VIX-only, SPY+VIX), 1m EMA Scalp
- `custom_strategies/mean_reversion.py` — Bollinger Band family, Stochastic, CMF, OBV, MA Bounce, SMA Trend, all MA Confluence variants, Donchian, Keltner, ATR variants, calendar/overnight strategies

**Do Not Touch:** `helpers/indicators.py` strategy logic (all working correctly). The plugin system wraps around it.

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

### Index Ticker Normalisation (Yahoo only)

Yahoo Finance uses `^` prefix for index symbols (`^VIX`, `^TNX`), while Norgate and Polygon use `I:` (`I:VIX`, `I:TNX`) or `$I:` (`$I:VIX`). `_normalise_symbol(symbol)` in `yahoo_service.py` handles the mapping:

- `I:VIX` / `$I:VIX` → `^VIX`
- `I:TNX` / `$I:TNX` → `^TNX`
- `I:SPX` / `$I:SPX` → `^GSPC`
- Unknown `I:XYZ` → `^XYZ` (fallback)
- Plain tickers (`AAPL`, `SPY`) and `^VIX` pass through unchanged.
- Case-insensitive: `i:vix` → `^VIX`.

Called inside `get_price_data` before constructing `yf.Ticker(yahoo_symbol)`. Tests in `TestNormaliseSymbol` (19 tests) cover all cases.

### Run Summary UI Changes

`main.py` now emits two period-related lines:

1. **`Period Selected`** (in the startup `===` box) — config values `start_date` / `end_date`.
2. **`Actual Data Period`** (logged after SPY is fetched) — `spy_df.index.min()` / `spy_df.index.max()` rounded to date strings.

The `TestU1SummaryContent::test_period_selected_label_is_exact` test enforces that every log line containing "Period" also contains "Selected" (no bare `Period :` label remains).

### Polygon API Plan Limitation — Root Cause of 71% vs 814% Discrepancy

**Diagnostic (`debug_data.py`)**: Polygon returns 1,254 bars starting 2021-03-12. Yahoo returns 5,581 bars starting 2004-01-02. The SPY return difference (+742 pp) is 100% explained by the ~17-year start-date gap — Polygon's API plan (starter tier) limits history to roughly the last 5 years. There is NO pagination bug in `polygon_service.py` — the single page with 50,000-bar limit returns all available bars correctly. This is a hard server-side constraint; upgrading the Polygon plan is the only fix.

**Key implication**: When using Polygon, `Actual Data Period` in the run summary will show the true start, making it visible that the configured `start_date` of 2004 is not honoured.

### S1/S2 Test Robustness

`tests/test_startup_validation.py::TestS1ApiKeyCheck` and `tests/test_main_cli.py::TestMissingApiKey` now explicitly force `data_provider = "polygon"` via the config-patch wrapper before testing the `POLYGON_API_KEY` guard. This makes the tests pass regardless of which provider is configured in `config.py`. Pattern: always patch `data_provider` when testing provider-specific guards.

## Strategy Correlation Analysis

- **`helpers/correlation.py`** — pure, stateless module. Public entry point: `run_correlation_analysis(strategy_results, output_path, threshold=0.85)`.
- **Pipeline placement**: called in `main.py` inside the per-portfolio reporting loop, immediately after `generate_per_portfolio_summary`. Runs once per portfolio.
- **Input**: list of simulation result dicts (each with `"Strategy"` and `"trade_log"` keys). Trades are grouped by `ExitDate` and profits summed to build a daily P&L series per strategy.
- **Output CSV path**: `output/runs/<run_id>/<Portfolio_safe_name>_strategy_correlation.csv` — next to `overall_portfolio_summary.csv`, one file per portfolio.
- **Threshold**: default `0.85` (absolute Pearson). Pairs with `|r| > 0.85` are logged as `[WARNING]` lines via `logger.warning`.
- **Skipped silently** when fewer than 2 strategies have non-empty trade logs (returns empty DataFrame + empty list, no CSV written).
- **Tests**: `tests/test_correlation.py` — covers `_build_daily_pnl_series`, `build_daily_pnl_matrix`, `compute_correlation_matrix`, `find_high_correlation_pairs`, and `run_correlation_analysis` (with `tmp_path` file I/O). No network, no randomness.

## Walk-Forward Analysis (WFA)

- **`helpers/wfa.py`** — pure, stateless module: `get_split_date`, `split_trades`, `evaluate_wfa`.
- **Split date source**: computed from `spy_df` actual start/end dates (not `config.start_date`) in `main.py` after the SPY fetch. Stored as a plain `str` and passed as the last element of each task tuple so Windows spawn workers receive it.
- **Placement in pipeline**: `run_single_simulation` in `main.py` calls `evaluate_wfa` after Monte Carlo, before `return result`. Adds `oos_pnl_pct` and `wfa_verdict` to the result dict.
- **"Likely Overfitted" triggers**: (1) IS P&L > 0 and OOS P&L < 0 (sign flip); (2) OOS annualised return degraded > 75% vs IS annualised return. Both require `_MIN_OOS_TRADES = 5` minimum OOS trades; fewer → "N/A".
- **Summary columns**: `OOS P&L (%)` (formatted `{:+.2%}`) and `WFA Verdict` appear in all 4 summary functions in `helpers/summary.py`, placed before `MC Verdict`.
- **Tests**: `tests/test_wfa.py` — 39 tests, 5 test classes. No I/O, no network. All deterministic.

## R-Multiple, Expectancy, and SQN

### Per-Trade Fields (trade_log)

- **`InitialRisk`** (float, per share): captured in `helpers/portfolio_simulations.py` at trade close.
  - Formula: `entry_price - initial_stop_loss_level`
  - Fallback (no stop, stop is NaN/0, or stop ≥ entry): `entry_price * 0.01` (1% proxy)
  - `initial_stop_loss_level` is stored separately from `stop_loss_level` so trailing-stop updates don't corrupt it.
- **`RMultiple`** (float or None): `net_pnl / (InitialRisk * shares)`. `None` when InitialRisk or shares ≤ 0.
- Both fields appear in all trade_log entries, including mark-to-market closes at end-of-backtest.
- Both fields pass through to analyzer CSVs (not in `COLUMN_MAP`, so kept as-is).

### Per-Strategy Metrics (result dict)

Computed in `run_single_simulation` in `main.py` immediately after WFA:

- **`expectancy`**: `mean(R-Multiples)` — average R gained per trade risked. `None` if < 2 trades have a non-null RMultiple.
- **`sqn`**: `(expectancy / std(R-Multiples, ddof=1)) * sqrt(N)`. `0.0` if std is zero. `None` if < 2 trades.
- Both formatted in all 4 summary functions (`helpers/summary.py`): `expectancy → "{:.3f}"`, `sqn → "{:.2f}"`, column headers `Expectancy (R)` and `SQN`.

### PDF Report

`trade_analyzer/analyzer.py` checks for a `RMultiple` column after the profit distribution plot:

- Purple histogram (30 bins), red dashed breakeven line at 0R, green dashed expectancy line.
- Legend shows `Expectancy: X.XXXr | SQN: X.XX | n=N`.
- Section title: `"Risk Profile — R-Multiple Distribution"`.
- Skipped gracefully if column absent or fewer than 2 values.

### Tests

`tests/test_r_multiple.py` — 22 tests, 4 test classes:

- `TestInitialRisk` — correct risk with stop, 1% proxy for None/NaN/0/above-entry
- `TestRMultiple` — winning/losing/breakeven trades, ZeroDivisionError guards, proxy path
- `TestExpectancyAndSQN` — formula validation, 0/1/2 trade edge cases, std=0 guard, growth with N
- `TestTradeLogHasRMultipleFields` — integration: fields present in live simulation output, percentage stop sets correct InitialRisk

## Common Pitfalls
- `get_bars_for_period('14d', TIMEFRAME, MULTIPLIER)` — always use this for indicator periods, not raw integers, so strategies work across timeframes
- Stop-loss config is a dict `{"type": "none"}` or `{"type": "percentage", "value": 0.05}` — not a float
- `apply_stop_loss(df, stop_config)` takes the dict, not a percentage float
- Norgate portfolios use `"norgate:WatchlistName"` string prefix; JSON files use `"filename.json"`; inline lists use a Python list
- `execution_time: "open"` means signals are generated on day N and filled at day N+1 open — the simulator handles the 1-day lag via `prev_trading_dates`