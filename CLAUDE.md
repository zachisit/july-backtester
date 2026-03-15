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
helpers/ml_export.py               # ML trade feature export (export_trade_features)
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
"wfa_folds": None                # None = rolling WFA disabled; int >= 2 = number of folds
"wfa_min_fold_trades": 5         # min OOS trades per fold to score it (rolling WFA only)
"export_ml_features": False      # True = write ml_features.parquet after the run (requires pyarrow)
"noise_injection_pct": 0.0       # 0.0 = disabled (default, stress testing is opt-in). Set to e.g. 0.01 for ±1% stress test.
"risk_free_rate": 0.05           # annual, used in Sharpe calculation (default 5% — US T-bill proxy)
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

> **`helpers/summary.py`** — can be touched; actively maintained. `save_only_filtered_trades` now correctly filters by the display criteria captured in Step 2 of `generate_per_portfolio_summary` (see Known Issues Fixed below).

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
- **Known Limitations**: Correlation is measured on **exit-date P&L only**, not daily mark-to-market. Two strategies that hold the same stock simultaneously but exit on different days will appear uncorrelated (or even negatively correlated), so the matrix is a **lower bound on true correlation** — it systematically understates relatedness for overlapping concurrent positions. `run_correlation_analysis` logs a `WARNING` once per call documenting this bias.

## Walk-Forward Analysis (WFA)

- **`helpers/wfa.py`** — pure, stateless module: `get_split_date`, `split_trades`, `evaluate_wfa`.
- **Split date source**: computed from `spy_df` actual start/end dates (not `config.start_date`) in `main.py` after the SPY fetch. Stored as a plain `str` and passed as the last element of each task tuple so Windows spawn workers receive it.
- **Placement in pipeline**: `run_single_simulation` in `main.py` calls `evaluate_wfa` after Monte Carlo, before `return result`. Adds `oos_pnl_pct` and `wfa_verdict` to the result dict.
- **"Likely Overfitted" triggers**: (1) IS P&L > 0 and OOS P&L < 0 (sign flip); (2) OOS annualised return degraded > 75% vs IS annualised return. Both require `_MIN_OOS_TRADES = 5` minimum OOS trades; fewer → "N/A".
- **Annualised return now uses CAGR formula (compound), not simple division**: `(1 + total_pnl_frac) ** (1/years) - 1`. Guard: if `(1 + total_pnl_frac) <= 0` (bust), returns `None`.
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

## Annual Turnover & After-Tax CAGR Metrics

Added to the **Overall Performance Metrics** section of the PDF tearsheet (and text output).

### Annual Turnover %

`Annual Turnover % = (Σ(Price × Shares) / initial_equity) / duration_years × 100`

- Requires `Price` (entry price) and `Shares` columns in `trades_df`; shows `N/A` if absent.
- Zero duration or zero initial equity also yields `N/A`.

### Estimated After-Tax CAGR (30% flat tax)

- If `total_profit > 0`: `after_tax_profit = total_profit × 0.70`
- If `total_profit ≤ 0`: `after_tax_profit = total_profit` (losses pass through unchanged)
- `after_tax_equity = initial_equity + after_tax_profit`
- CAGR computed via the standard `calculations.calculate_cagr()` on the after-tax equity.
- Placed immediately below the gross CAGR line.

### Implementation

`trade_analyzer/report_generator.py` — `generate_overall_metrics_summary()`, in the Duration/CAGR block after the `CAGR:` line.

### Tests

`tests/test_new_metrics.py` — 14 tests across two classes:

- `TestAnnualTurnover` — exact value, single trade, duration scaling, 100% rotation, missing-column and zero-duration guards.
- `TestAfterTaxCagr` — positive profit (tax applied), negative profit (no haircut), zero profit, after-tax < gross, 1-year exact, zero duration, explicit 30% arithmetic.

## Underwater Plot (Drawdown Visualisation)

Added to the PDF tearsheet immediately after the combined `Equity Curve and Drawdown` chart.

### What it is

A short, wide banner figure (`figsize=(10, 3), dpi=150`) that shows the full drawdown history as a red-filled area descending below a zero baseline. Depth = how far equity fell from the prior peak. Width = how long the drawdown lasted.

### Implementation

- **`trade_analyzer/plotting.py`** — `plot_underwater(trades_df, equity_dd_percent)`.
  - Receives the same `equity_dd_percent` series (positive, 0–100 scale) that feeds the lower subplot of the existing equity+drawdown chart.
  - Negates the series internally (`underwater = -equity_dd_percent`) so the curve descends below zero.
  - `fill_between(x, underwater, 0, color='red', alpha=0.3)` fills the "underwater" area.
  - Y-axis formatted with `PercentFormatter(xmax=100.0, decimals=1)` → labels like `-10.0%`, `-25.0%`.
  - Black dashed `axhline` at `y=0` as the baseline.
- **`trade_analyzer/analyzer.py`** — called right after `plot_equity_and_drawdown`; result appended to `report_sections` with title `"Underwater Plot (Drawdown & Duration)"`.

### Underwater Plot Tests

`tests/test_underwater_plot.py` — 12 tests across two classes:

- `TestHighWaterMark` — verifies `cummax()` logic (rising, declining, flat, single-element equity curves).
- `TestDrawdownPct` — verifies `(equity - hwm) / hwm` fractional values against hand-computed exact results for `[100, 110, 90, 105, 120]` and edge cases (always-rising, full recovery, trough fraction, single-element).

## Parameter Sensitivity Sweep

- **`helpers/sensitivity.py`** — pure, stateless module. Public entry points: `build_param_grid`, `label_for_params`, `is_sweep_enabled`.
- **Purpose**: detects p-hacking by varying each numeric param in a strategy's `@register_strategy(params={...})` dict by ±pct across ±steps steps and printing a fragility verdict.
- **How it works**: `build_param_grid` takes a base params dict and returns the cartesian product of all per-param value ranges. Only `int`/`float` values are varied; strings, bools, and `None` pass through unchanged. Values are floored at `sensitivity_sweep_min_val`.
- **Config keys**:

  | Key | Default | Description |
  | --- | --- | --- |
  | `sensitivity_sweep_enabled` | `False` | Opt-in — disabled by default |
  | `sensitivity_sweep_pct` | `0.20` | ±20% per step |
  | `sensitivity_sweep_steps` | `2` | 2 steps each side → 5 values per param |
  | `sensitivity_sweep_min_val` | `2` | Floor prevents e.g. SMA period = 0 |

- **Strategy naming convention**: when enabled, each variant is named `StrategyName [(base)]` for the base params and `StrategyName [fast=16]` for changed keys. Only changed keys appear in the label.
- **Fragility threshold**: `< 30%` of variants profitable → `*** FRAGILE ***` printed in the sensitivity report. ≥ 30% → `Robust`.
- **Performance note**: 2 params × `steps=2` produces 25 grid points (5² cartesian). Keep disabled for normal runs; enable only for targeted fragility checks.
- **No-regression guarantee**: when `sensitivity_sweep_enabled: False` (default), `param_variants = [base_params]` — identical to pre-sweep behaviour. The existing task-building loop runs exactly as before.
- **Tests**: `tests/test_sensitivity.py` — covers `build_param_grid` (12 tests), `label_for_params`, and the no-regression default path.

## Rolling Sharpe (126-Day)

- **`calculate_rolling_sharpe(portfolio_timeline, window, risk_free_rate)`** in `helpers/simulations.py` — computes a rolling annualised Sharpe using excess returns (daily return minus `rf_daily`).
- **Config key**: `rolling_sharpe_window` (default: `126` trading days ≈ 6 months). Set to `0` or `None` to disable.
- **Three scalar columns** added to all summary tables and the overall portfolio CSV:

  | Column | Key | Meaning |
  | --- | --- | --- |
  | `Roll.Sharpe(avg)` | `rolling_sharpe_mean` | Mean of all valid 126-day Sharpe windows |
  | `Roll.Sharpe(min)` | `rolling_sharpe_min` | Worst 126-day window — regime stress indicator |
  | `Roll.Sharpe(last)` | `rolling_sharpe_final` | Most recent 126-day window — current momentum |

- **Interpretation**: `Roll.Sharpe(min) < -0.5` indicates a prolonged losing streak even if the overall (single-number) Sharpe looks healthy — a red flag for regime dependency.
- **Shows `N/A`** when the equity curve has fewer bars than `rolling_sharpe_window` (insufficient history) or when the window is disabled.
- **NaN mechanics**: `pct_change()` produces NaN at index 0, so the first valid rolling value appears at index `window` (not `window - 1`) of the equity curve.
- **Tests**: `tests/test_rolling_sharpe.py` — 9 tests covering output length, NaN boundary at correct index, uptrend direction, rf-rate effect, and window-size comparison.

## Short Selling & Borrow Cost

**Signal convention** — all existing strategies use 1/0/−1 and are fully unaffected:

| Signal | Meaning |
| --- | --- |
| `1` | Enter long |
| `0` | No change |
| `-1` | Exit long **or** cover short |
| `-2` | Enter short |

- **Borrow cost**: `htb_rate_annual` (config, default `0.02`) converted to a daily compound rate `(1 + annual)^(1/252) - 1` and debited from cash each day a short is held. Set to `0.0` to disable.
- **Three new blocks in the daily loop** (all additive — no long-path code changed):
  1. **Borrow cost debit**: iterates `short_positions`, subtracts `notional × htb_rate_daily` from cash and accumulates `spos['total_borrow_cost']`.
  2. **Short cover**: on signal `< 0` for a held short, fills at Open/Close + slippage, deducts commission both sides, nets `total_borrow_cost` out of profit, logs to `trade_log`.
  3. **Short entry**: on signal `== -2`, skips if `symbol in positions or symbol in short_positions`, allocates `min(total_equity × allocation_pct, cash)`, receives proceeds into cash.
- **Short trades in `trade_log`**: `Trade: "Short N"`, `ExitReason: "Short Cover"`. `RMultiple` is `None` for shorts (initial risk undefined without a stop).
- **Equity MTM for shorts**: `current_market_value += (shares × entry_price) − (shares × current_close)` — profit when price falls.
- **Backward compatibility**: all existing 1/0/−1 strategies skip all three new blocks entirely (`short_positions` is always empty for them).
- **Tests**: `tests/test_short_selling.py` — 7 tests covering config defaults, daily-rate arithmetic, 30-day cost estimate, and no-regression empty-shorts loop.

## Regime Heatmap

`helpers/regime.py` — pure reporting layer; no engine changes, no strategy signals modified.

**VIX buckets**:

| Bucket | Condition | Constant |
| --- | --- | --- |
| Low | VIX < 15 | `REGIME_LOW` |
| Mid | 15 ≤ VIX ≤ 25 | `REGIME_MID` |
| High | VIX > 25 | `REGIME_HIGH` |
| Unknown | No prior data | `REGIME_UNK` |

- **Classification date**: each trade's `EntryDate` is used for regime lookup (not an average over the hold period).
- **Forward-fill**: weekends and holidays inherit the most recent prior VIX close. The lookup date is unioned into the series as NaN then `ffill()` is applied, so no date is ever artificially inserted into real data.
- **`build_regime_heatmap(trade_log, vix_df, initial_capital)`**: returns a `year × regime` DataFrame where each cell is `sum(Profit) / initial_capital`. Returns `None` if `trade_log` is empty, `vix_df` is None/empty, or `initial_capital ≤ 0`. All three regime columns are always present even when no trades fall in a bucket.
- **`print_regime_heatmap(heatmap, strategy_name)`**: prints a formatted year × bucket table to stdout. Silent when `heatmap` is None.
- **`main.py` integration**: `result["regime_heatmap"]` set in `run_single_simulation`; printed per-strategy in the `main()` loop after `generate_per_portfolio_summary`.
- **Tests**: `tests/test_regime_heatmap.py` — 16 tests covering boundary VIX values, forward-fill, None guards, DataFrame shape, fractional P&L values, multi-year rows, and stdout content.

## Init Wizard (--init)

```bash
rtk python main.py --init
```

Interactive four-step wizard for first-time setup. Writes `config_starter.py` to the project root.

**Four steps:**
1. **Data provider** — choose `yahoo` / `csv` / `polygon` / `norgate`. If Polygon is selected, optionally enter the API key (appended to `.env`).
2. **Capital & dates** — `initial_capital` (default 100 000), `start_date` (default 2010-01-01). End date is always a dynamic `datetime.now()` expression in the written file.
3. **What to test** — `single` (comma-separated tickers → `symbols_to_test`) or `portfolio` (nasdaq100 JSON or custom named list → `portfolios`).
4. **Confirm & write** — shows a file list, asks for explicit `y/n` confirmation before writing anything.

**Design constraints:**
- Stdlib only (`sys`, `os`, `pathlib`, `textwrap`, `datetime`, `argparse`) — zero new dependencies.
- No network calls.
- Nothing written without explicit user confirmation at Step 4.
- Will not overwrite `config.py` if it already exists; warns and instructs the user to copy sections manually.
- Polygon API key appended to `.env` only if `POLYGON_API_KEY=` is not already present.

**Interactive prompt functions** (`_ask`, `_confirm`) require a TTY and are not unit-tested. `_build_config` and colour helpers are fully unit-tested.

**Tests:** `tests/test_init_wizard.py` — 13 tests covering `_build_config` for all four providers, required keys, mode branching, and colour helper behaviour with/without TTY.

## MC Block-Bootstrap

Controlled by two config keys (SECTION 18):

| Key | Default | Description |
| --- | --- | --- |
| `mc_sampling` | `"iid"` | `"iid"` = independent resampling (original behaviour); `"block"` = block-bootstrap |
| `mc_block_size` | `None` | Trades per block. `None` = auto: `floor(sqrt(N))` (Politis-Romano rule of thumb) |

- **`"iid"` (default)**: trades are resampled independently, each with equal probability. Fast and statistically clean for strategies with no autocorrelation.
- **`"block"`**: consecutive blocks of `block_size` trades are sampled as a unit, preserving win/loss streaks and regime clustering. Use when the strategy shows known regime dependency (e.g., consistently loses only during bear markets / high-VIX periods identified by the Regime Heatmap).
- **Auto block size**: `max(1, int(N ** 0.5))`. For 100 trades → blocks of 10; for 400 trades → blocks of 20.
- **Circular wrap**: blocks that extend past the end of the trade list wrap around — no trades are omitted and edge blocks are not under-represented.
- **No caller changes**: `run_monte_carlo_simulation` signature is unchanged. The refactor extracted a `_equity_and_drawdown` helper used by both branches.
- **Tests**: `tests/test_mc_block_bootstrap.py` — 9 tests: config defaults, output shapes, auto block size resolution, streak divergence (>1% std difference), small trade guard, i.i.d. seed match, and no-key default.

## Recovery Time

`max_recovery_days` and `avg_recovery_days` are computed inside `calculate_advanced_metrics` in `helpers/simulations.py` and surface in all four summary functions.

- **`max_recovery_days`**: longest calendar-day gap from any drawdown trough back to the prior equity peak.
- **`avg_recovery_days`**: mean calendar days across all completed recoveries (rounded to 1 decimal).
- Both are `None` when the equity curve ends in an open drawdown (never fully recovered to its prior peak). `fillna('N/A')` in the summary display pipeline shows them as `N/A` in that case.
- **Algorithm**: linear scan with two pointers — outer loop finds the start of each drawdown period; inner loop scans forward to the first bar that reaches or exceeds the peak value at drawdown start. Only completed recoveries (where `j < n`) contribute to the list. A recovery of 0 calendar days (same-bar artefact) is excluded.
- **No config keys**: always computed when the equity curve has ≥ 2 bars.
- **Tests**: `tests/test_recovery_time.py` — 6 tests: flat/uptrend → None, single dip-and-recover, open drawdown at end → None, max ≥ avg, known calendar-day value, and summary column presence.

## Volume-Based Market Impact Slippage

Controlled by `volume_impact_coeff` in config (SECTION 19). Default `0.0` = disabled.

**Formula**: `impact_additional = volume_impact_coeff × sqrt(shares / adv_20)`

Applied on top of the flat `slippage_pct`:

- **Entry**: `entry_price = raw_entry_price × (1 + slippage_pct) × (1 + impact_additional)`
- **Exit**: `exit_price = raw_exit_price × (1 - slippage_pct) × (1 - impact_additional)`

**Three independent slippage controls:**

| Config key | What it models |
| --- | --- |
| `slippage_pct` | Flat bid/ask spread cost on every trade (default 0.05%) |
| `max_pct_adv` | Position size cap — no order may exceed X% of ADV (default 5%) |
| `volume_impact_coeff` | Square-root market impact — larger orders relative to ADV cost more (default 0.0 = off) |

**Typical values**: `0.1` = mild (institutional estimate); `0.5` = aggressive (small-cap / illiquid).

**Example** (coeff=0.1, order consumes 1% of ADV): additional slippage = 0.1 × √0.01 = **1 bp**. At 5% of ADV: **~2.2 bp**.

**`VolumeImpact_bps` field** in trade log: entry impact bps + exit impact bps, rounded to 1 decimal place. Zero when `volume_impact_coeff=0.0`. Useful for identifying which trades were most penalised by market impact.

**Guard**: only fires when `Volume` column is present in the symbol's DataFrame and `adv_20 > 0`. Silent no-op otherwise.

**Tests**: `tests/test_volume_impact.py` — 7 tests: config defaults, sqrt formula at 1%/5% ADV, zero coeff produces zero, monotonicity, and no-regression entry price unchanged at coeff=0.

## WFA Rolling Folds

Controlled by two config keys in SECTION 11 (opt-in — keep disabled for normal runs):

| Key | Default | Description |
| --- | --- | --- |
| `wfa_folds` | `None` | `None` or `0` = rolling WFA disabled; `int >= 2` = number of equal-width OOS folds |
| `wfa_min_fold_trades` | `5` | Minimum OOS trades required to score a fold |

- **Single-split WFA is unchanged**: `wfa_split_ratio` and the `oos_pnl_pct` / `wfa_verdict` result keys continue to work exactly as before. Rolling folds is purely additive.
- **How it works**: the full period is divided into *k* equal-width OOS windows. For fold *i*, IS = all trades with `ExitDate < oos_start`. A fold is *scorable* when its OOS trade count ≥ `wfa_min_fold_trades`. Folds with fewer OOS trades are skipped.
- **Verdict logic**: "Pass" when ≥ 60% of scorable folds pass `evaluate_wfa()` individually. "Fail" otherwise. "N/A" when fewer than 2 folds are scorable.
- **`helpers/wfa_rolling.py`** — `get_fold_dates(actual_start, actual_end, k)` and `evaluate_rolling_wfa(trade_log, fold_dates, initial_capital, min_fold_trades=5)`.
- **`main.py` task tuple**: `spy_actual_start` and `spy_actual_end` are the last two elements of every task tuple (appended after `wfa_split_date`). They are passed at task-creation time from the `_spy_actual_start` / `_spy_actual_end` variables computed after the SPY fetch.
- **Result key**: `wfa_rolling_verdict` → summary column `Rolling WFA`, placed after `WFA Verdict` in all four summary functions.
- **Tests**: `tests/test_wfa_rolling.py` — 11 tests across 3 classes: `TestConfigDefaults`, `TestGetFoldDates`, `TestEvaluateRollingWfa`.

## ML Trade Feature Export

Controlled by `export_ml_features` in config (SECTION 20). Default `False` = disabled.

**Output**: `output/runs/<run_id>/ml_features.parquet` — one row per trade, all strategies and portfolios consolidated.

**ML target column**: `is_win` (int8, 1 = profitable trade, 0 = loss).

**Column schema** (canonical order): `Strategy`, `Portfolio`, `Symbol`, `EntryDate` (Timestamp), `ExitDate` (Timestamp), `HoldDuration`, `EntryPrice`, `ExitPrice`, `Profit`, `ProfitPct`, `Shares`, `is_win` (int8), `RMultiple`, `MAE_pct`, `MFE_pct`, `ExitReason`, `InitialRisk`, then all `entry_*` feature columns (`entry_RSI_14`, `entry_ATR_14_pct`, `entry_SMA200_dist_pct`, `entry_Volume_Spike`, `entry_SPY_RSI_14`, `entry_SPY_SMA200_dist_pct`, `entry_VIX_Close`, `entry_TNX_Close`), then any remaining columns.

The internal `Trade` counter column is always dropped.

**Dependency**: `pyarrow` or `fastparquet` required for Parquet output. If neither is installed, logs a warning and writes a CSV fallback to the same path with a `.csv` extension.

**`helpers/ml_export.py`** — `export_trade_features(all_results, output_path) -> int`. Returns the number of rows written (0 if no trades found).

**Tests**: `tests/test_ml_export.py` — 8 tests: empty results (returns 0), row count, `is_win` presence, Strategy/Portfolio injection, readable Parquet, `Trade` column dropped, CSV fallback on ImportError, config default False.

## Common Pitfalls
- `get_bars_for_period('14d', TIMEFRAME, MULTIPLIER)` — always use this for indicator periods, not raw integers, so strategies work across timeframes
- Stop-loss config is a dict `{"type": "none"}` or `{"type": "percentage", "value": 0.05}` — not a float
- `apply_stop_loss(df, stop_config)` takes the dict, not a percentage float
- Norgate portfolios use `"norgate:WatchlistName"` string prefix; JSON files use `"filename.json"`; inline lists use a Python list
- `execution_time: "open"` means signals are generated on day N and filled at day N+1 open — the simulator handles the 1-day lag via `prev_trading_dates`

## Known Issues Fixed

### ATR Column Name Mismatch (fixed 2026-03-13)

`main.py` writes the 14-period ATR column as `ATR_14`, but `helpers/portfolio_simulations.py` had two `.get('ATR')` calls that silently returned `NaN`:

1. **Entry path** (initial stop calculation): `day_before_data.get('ATR')` — stop was never set, making all ATR stop configs behave identically to `{"type": "none"}`.
2. **Daily trailing loop**: `portfolio_data[symbol].loc[date].get('ATR')` — even if the initial stop had been set by some other means, the trailing update would never fire.

**Fix**: both calls changed to `.get('ATR_14')` to match the column written by `main.py`.

**Regression test**: `tests/test_atr_logic.py::TestSimulationAtrColumnName::test_atr_stop_triggered_on_crash` — builds a portfolio_data dict with `ATR_14` populated (no `ATR` column), runs a simulation with `stop_config={"type": "atr", ...}`, and asserts the trade exits with `"Stop Loss"` when price crashes below the ATR stop. This test failed before the fix and passes after.

### `save_only_filtered_trades` saved all trades, not filtered ones (fixed 2026-03-13)

In `helpers/summary.py::generate_per_portfolio_summary()`, Step 4b's `save_only_filtered_trades` branch rebuilt `display_df` from the raw `portfolio_results` list (overwriting the already-filtered Step 2 `display_df`), so all strategies were saved regardless of whether they passed the display filters (max drawdown, min P&L, min MC score, etc.).

**Fix**: after Step 2 produces the filtered `display_df`, capture `passed_display_filter = set(display_df['Strategy'].tolist())`. Step 4b now filters via `[r for r in portfolio_results if r['Strategy'] in passed_display_filter]` — no DataFrame rebuild needed.

**Regression tests**: `tests/test_save_filtered_trades.py::TestSaveOnlyFilteredTrades` — three tests confirm `save_trades_to_csv` is called exactly once (the passing strategy) when `save_only_filtered_trades=True` and one result fails `min_pandl_to_show_in_summary`, and called twice when the flag is `False`.
