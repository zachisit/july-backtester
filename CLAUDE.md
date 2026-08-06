# CLAUDE.md — july-backtester

> **RTK RULE — NON-NEGOTIABLE**: Every terminal command MUST be prefixed with `rtk`. No exceptions. This includes `rtk git`, `rtk grep`, `rtk pytest`, `rtk ls`, `rtk read`, etc. Bare `grep`, `git`, `pytest`, `find` etc. are FORBIDDEN in this project.

## What This Is
Python backtesting engine for US equities. Tests 20+ technical strategies across single symbols or large portfolios (Nasdaq, S&P 500, etc.) with Monte Carlo robustness scoring.

## Entry Points
- `main.py` — runs all entries in `portfolios`; a single-ticker basket like `"My Symbols": ["AAPL"]` replaces the old single-asset mode
- `main.py --name "run-name"` — optional prefix for report folder and S3 path
- `main.py --verbose` — print two additional tables beneath the default Core Performance table: Extended Metrics (RS(avg/min/last), MaxRcvry, AvgRcvry, Calmar, PF, WinRate, Trades, Expct(R), SQN) and Robustness (OOS P&L, WFA Verdict, RollWFA, Corr, MC, MC Score). Default output shows Core Performance only.

## Versioning

The app version lives in **`version.py`** at the project root (`__version__ = "x.y.z"`). This is the single source of truth — update it whenever a release goes out. It surfaces via `python main.py --version`.

**On every release:** bump `version.py` to the new version string before merging to `main`.

## Key Files
```
version.py                         # Single source of truth for the app version — bump on every release
config.py                          # All settings — edit this before running
main.py                            # Single entry point (--name, --verbose, --dry-run, --init)
helpers/indicators.py              # All strategy signal logic — do not touch
helpers/registry.py                # Strategy registry: register_strategy decorator, load_strategies, get_active_strategies
helpers/simulations.py             # Single-asset trade simulation engine
helpers/portfolio_simulations.py   # Multi-asset portfolio simulation engine
helpers/monte_carlo.py             # Monte Carlo robustness scoring
helpers/summary.py                 # Report generation, S3 upload; dynamic benchmark columns via _build_benchmark_columns(); _get_t1_cols()/_get_t2_cols()/_T3_COLS/_VERBOSE_SHORT_NAMES control tiered table layout; _print_table() handles all bordered terminal output
helpers/wfa.py                     # Walk-Forward Analysis (get_split_date, split_trades, evaluate_wfa)
helpers/wfa_rolling.py             # Rolling multi-fold WFA (get_fold_dates, evaluate_rolling_wfa)
helpers/ml_export.py               # ML trade feature export (export_trade_features)
helpers/sensitivity.py             # Parameter sensitivity sweep (build_param_grid, label_for_params, is_sweep_enabled)
helpers/regime.py                  # VIX regime heatmap (build_regime_heatmap, print_regime_heatmap, classify_vix_regime)
helpers/point_in_time.py           # Point-in-time index universe resolver for portfolios like "pit:nq100" and "pit:sp500"
helpers/init_wizard.py             # First-time setup wizard invoked via python main.py --init
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
"portfolios": {"My Symbols": ["AAPL"]}             # single ticker (replaces old symbols_to_test)
"portfolios": {"Nasdaq 100": "nasdaq_100.json"}  # pre-built JSON list
"portfolios": {"Nasdaq 100 PIT": "pit:nq100"}    # point-in-time members as of start_date
"portfolios": {"S&P 500 PIT": "pit:sp500"}       # requires PIT YAML files or SP500_DATA_ROOT
"allocation_per_trade": 0.10       # 10% equity per position
"position_sizing_method": "fixed"  # "fixed"|"kelly"|"vol_parity"|"risk_parity"|"risk_pct_capped"|"fixed_contracts"
"fixed_contracts_per_trade": 1     # contracts/trade when position_sizing_method="fixed_contracts"
"trading_hours_per_day": 6.5       # session hours for annualization; set 24 for 24h futures
"stop_loss_configs": [{"type": "none"}]  # or {"type":"percentage","value":0.05}
"slippage_pct": 0.0005
"commission_per_share": 0.002
"min_trades_for_mc": 50
"num_mc_simulations": 1000
"wfa_split_ratio": 0.80          # 0.80 = 80% IS / 20% OOS; None or 0 = disabled
"wfa_folds": None                # None = rolling WFA disabled; int >= 2 = number of folds
"wfa_min_fold_trades": 5         # min OOS trades per fold to score it (rolling WFA only)
"export_ml_features": False      # True = write ml_features.parquet after the run (requires pyarrow)
"verbose_output": False          # True = print Extended Metrics + Robustness tables; --verbose overrides at runtime
"noise_injection_pct": 0.0       # 0.0 = disabled (default, stress testing is opt-in). Set to e.g. 0.01 for ±1% stress test.
"risk_free_rate": 0.05           # annual, used in Sharpe calculation (default 5% — US T-bill proxy)
"sensitivity_sweep_enabled": False  # opt-in parameter fragility sweep
"sensitivity_sweep_pct": 0.20    # ±20% per step
"sensitivity_sweep_steps": 2     # 2 steps each side → 5 values per param
"sensitivity_sweep_min_val": 2   # floor for generated values (prevents SMA period = 0)
"rolling_sharpe_window": 126     # rolling Sharpe window in trading days; 0 or None = disable
"htb_rate_annual": 0.02          # annual hard-to-borrow rate debited daily on short positions
"mc_sampling": "iid"             # "iid" = independent; "block" = block-bootstrap; "auto" = block for concentrated_futures profile else iid
"mc_block_size": None            # block size for block-bootstrap; None = auto floor(sqrt(N))
"smoothness_profile": "auto"     # smoothness-verdict thresholds: "auto"|"equity"|"concentrated_futures"
"volume_impact_coeff": 0.0       # square-root market impact coefficient; 0.0 = disabled
```

## Architecture Notes

**Multiprocessing design:** `init_worker` passes large DataFrames (SPY, VIX, TNX, portfolio data) into each worker process as globals at pool creation time. Tasks are small tuples — they do NOT contain DataFrames. Do not change this pattern; it avoids pickling large objects.

**Signal convention:** Strategy functions return a DataFrame with a `Signal` column: `1` = enter/hold long, `-1` = exit/flat, `0` = no change.

**Caching:** `helpers/caching.py` stores Parquet files in `data_cache/` keyed by `{symbol}_{start}_{end}_{timeframe}_{multiplier}.parquet`. TTL is 24h. Delete the folder to force a fresh fetch.

**API key resolution order** (in `helpers/aws_utils.py`): environment variable → `.env` file. No AWS Secrets Manager.

**Data fetcher signature:** `fetcher(symbol, start_date, end_date, config) -> pd.DataFrame | None`. Columns must be `Open, High, Low, Close, Volume` with a `Datetime` index.

**Dynamic benchmark columns:** `helpers/summary.py` uses `_build_benchmark_columns(benchmark_returns)` to generate column names, display names, format specs, and short names dynamically from the `benchmark_returns` dict passed to summary functions. This allows summary reports to display arbitrary benchmark tickers (not just hardcoded SPY/QQQ). All 4 summary functions (`generate_per_portfolio_summary`, `generate_single_asset_summary_report`, `generate_final_summary`, `generate_portfolio_summary_report`) accept a `benchmark_returns` dict parameter (e.g., `{"SPY": 0.12, "QQQ": 0.15, "XLF": 0.08}`) and dynamically build result keys like `vs_spy_benchmark`, `vs_qqq_benchmark`, `vs_xlf_benchmark`. The first benchmark appears in Table 1 (Core Performance), remaining benchmarks appear in Table 2 (Extended Metrics). Filtering logic supports backward compatibility: the first two benchmarks respect `min_performance_vs_spy` and `min_performance_vs_qqq` config keys; additional benchmarks default to `-9999.0` threshold (show all).

**Datetime index normalization (Phase 4 of #55):** All data providers return `pd.DatetimeIndex` regardless of timeframe. Daily data (`timeframe="D"`) is normalized to midnight timestamps (00:00:00 UTC) via `.normalize()` to ensure consistent datetime handling across timeframes. Intraday data (`timeframe="H"` or `"MIN"`) preserves hour/minute precision. Trade logs store `EntryDate` and `ExitDate` as ISO 8601 strings (`.isoformat()`) supporting both date-only (`"2024-01-15"`) and datetime (`"2024-01-15T10:30:00"`) formats. WFA functions convert these strings to `pd.Timestamp` for chronological comparisons, ensuring robust datetime handling for mixed daily/intraday backtests.

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

## PDF Tearsheet Layouts (`report.py --layout`)

`report.py` produces one of two PDF layouts, selected with `--layout` (default `v3`):

- **`v3`** (default, new in v1.12.0) — a dense, institutional **2-page** report in the house navy/gold identity (navy title bar + gold rule, bordered gold-accented KPI tiles, navy section headers with gold underlines). Deliberately **not** a clone of any vendor sheet: our own labels/grouping, no imitation "LIVE" pill or copied disclaimer. Page 1: navy title bar (strategy name + "STRATEGY TEARSHEET" eyebrow + version/date) → HEADLINE row of 5 bordered tiles (Net P&L, Return/DD, Sharpe, Max Drawdown, Win Rate) → two-column FULL METRICS (Performance / Periodic Returns | Risk & Shape / Trade Stats). Page 2: TRAILING RETURNS tiles (1M/3M/6M/YTD/1Y/ITD), a trailing-8-month **$ P&L strip** (TOTAL = sum of shown cells), then six small-multiple charts — Equity Curve (Net), Equity In-Sample vs Live (OOS region shaded from `wfa_split_date`), Drawdown ($), Deepest Drawdowns, 6-Month Rolling Sharpe, 6-Month Rolling Volatility. Serenity carries a `*` footnote pointing at its documented proxy definition.
- **`classic`** — the full multi-page (14) deep-dive tearsheet (`trade_analyzer/_pdf_pages.py::generate_tearsheet_pdf`): MAE/MFE, per-symbol, MC fan, WFA split, appendices. Rebranded to the same house identity as v3 — every page carries the navy title bar + gold rule (`_house_navy_bar`), and KPI tiles delegate to v3's `_draw_kpi_tile` so both layouts stay visually identical. The footer stamp is name·date·page only (no top-edge header text). **Bug fix (issue #248):** `build_cover_page`/`build_executive_summary_page`/`_add_page_title` previously called `axis("off")` on their navy strips, which hid the fill on modern matplotlib (white banners + invisible titles) — now they keep the patch visible and suppress ticks/spines manually.

**Files:**
- `trade_analyzer/metrics_v3.py` — pure, stateless institutional metrics computed from the daily equity/return series + trades: Omega, Gain/Pain (Omega = Gain/Pain + 1 at threshold 0), Ulcer Index, % Time in DD, Serenity (documented Ulcer×tail-CVaR-penalized return proxy — reproducible, not vendor-exact), Recovery Factor / Ret-DD (net profit ÷ max DD $), annualized volatility, skewness/excess-kurtosis, payoff ratio, R-expectancy, period returns, monthly $ P&L strip, best/worst day-month-year, positive months/years, and 126-day rolling Sharpe/volatility. Entry point `compute_v3_metrics(...)`.
- `trade_analyzer/_pdf_v3.py` — the 2-page builders (`build_v3_page1`, `build_v3_page2`) + `generate_tearsheet_v3(report_data, output_path)`. Renders in the existing `default_config.THEME` (navy/gold) with matplotlib only — no new dependencies.

**Wiring:** `report.py` passes `LAYOUT` in `config_params`; `analyzer.py::_run_analysis` branches on it (`generate_tearsheet_v3` vs `generate_tearsheet_pdf`) and adds `trading_days` to `report_data`. Transaction fees are best-effort (summed from any recognised fee column, else `$0` since engine `Profit` is already net). **Tests:** `tests/test_metrics_v3.py` (hand-computed metric values), `tests/test_pdf_v3.py` (2-page smoke, in-range OOS split, empty-trades guard).

## Do Not Touch
- `helpers/indicators.py` strategy **logic** (all working correctly) — docstring additions and documentation improvements are permitted provided no signal logic, parameter handling, imports, or formatting is changed
- `helpers/simulations.py` and `helpers/portfolio_simulations.py` simulation engines — **the execution core was deliberately refactored for futures support (issue #229): every cost/sizing/accounting site now routes through the instrument-metadata layer (`helpers/instruments.py`). The equity path is protected byte-for-byte by the golden-master suite (`tests/test_engine_characterization.py`) — any change here MUST keep that suite green.**
- `helpers/monte_carlo.py`
- `tickers_to_scan/` JSON files
- The multiprocessing architecture (`init_worker`, `run_single_simulation`, `Pool`)

> **`helpers/summary.py`** — can be touched; actively maintained. `save_only_filtered_trades` now correctly filters by the display criteria captured in Step 2 of `generate_per_portfolio_summary` (see Known Issues Fixed below).

## Futures Support / Instrument Metadata (issue #229)

The engine is instrument-aware: **`helpers/instruments.py`** resolves a per-symbol `Instrument` (`resolve_instrument(symbol, config)`) carrying `point_value` ($/point), `tick_size`, `margin_mode`, `commission_model`/value, `slippage_model`/value, `integer_units`, `borrow_applies`, `calendar`. **Equities are the default and reproduce the pre-#229 arithmetic byte-for-byte** (point_value=1, `cash_full` margin, per-share commission, %-slippage). Futures opt in via a contract-month ticker (e.g. `ESM6`) or `config["instruments"]["overrides"]`.

- **Cost/accounting helpers** in `instruments.py` (`commission`, `apply_slippage`, `round_units`, `market_value`, `margin_required`, `unrealized_pnl`, `borrow_cost_per_bar`, `stop_level`, `atr_stop_level`, `atr_stop_distance_pct`) replace the formerly hard-coded sites in `portfolio_simulations.py`.
- **Futures execution:** margin accounting (entry reserves initial margin, not full notional; equity = cash + unrealized P&L; `reserved_margin` tracks buying power), integer contracts, `$/point` P&L, point-capped stop `{"type":"points","value":N}`, no borrow on futures shorts.
- **Margin-based futures sizing (#238):** for margined instruments (`margin_mode == INITIAL_MARGIN`) contract count derives from `margin_required()`, not target-notional / `point_value` (which increasingly floored to 0 contracts as price appreciated, silently under-sizing/skipping late trades). The gate is `margin_mode`-first (checked before `point_value != 1.0`), so a futures instrument with `point_value == 1.0` still sizes on margin. Equity sizing (`CASH_FULL`) is unchanged. Applies to both long and short entry paths.
- **Stop anchoring (#238):** `percentage`/`points` stop levels anchor to the **raw pre-slippage entry price for margined futures only** — `_stop_anchor = raw_entry_price if inst.margin_mode == INITIAL_MARGIN else entry_price`. Equities (`CASH_FULL`) keep the pre-PR slipped-fill anchor **byte-for-byte** (golden master unchanged). *Caveat:* the `trailing_atr` stop path anchors its initial stop/target/breakeven-floor to `raw_entry_price` **unconditionally** (not yet `margin_mode`-gated) — harmless today (trailing_atr is a futures-only mechanic with no equity consumer and no golden-master coverage), tracked as a follow-up. So "equities restore pre-PR behavior" holds for `percentage`/`points` stops, not `trailing_atr`.
- **Sizing methods (#238):** `config["position_sizing_method"]` selects `fixed` (default) | `kelly` | `vol_parity` | `risk_parity` | `risk_pct_capped` (risk-based sizing with a hard cap) | `fixed_contracts` (a fixed count via `fixed_contracts_per_trade`); wired on both long and short paths. `trading_hours_per_day` (default 6.5) sets the session-hours divisor for annualization of non-RTH / 24h instruments. All three keys are read via `CONFIG.get(...)` with defaults and registered in `config_validator.KNOWN_KEYS`; defaults preserve existing behavior.
- **Scaled exits:** a fractional exit signal `-1 < s < 0` scales OUT `abs(s)` of the position; full exit remains `s <= -1`.
- **Sub-bar resolution (opt-in):** `config["intrabar_resolution"]=True` + `intrabar_data` passed to `run_portfolio_simulation` refines stop fills via `helpers/intrabar.py` (gap-through-stop fills at the sub-bar open). Off by default → unchanged. `main.py::_build_intrabar_data` fetches finer bars per symbol via the data provider; an optional `config["intrabar_parquet_source"]` overrides that with one 1-min OHLC parquet. That path is resolved **portably** — `~`/`$ENV` expansion + relative paths resolved against the project root via `_resolve_intrabar_source` — and if the file is absent the run **warns and falls back to the provider fetch** rather than silently disabling sub-bar resolution (no more contributor-local absolute-path dependency).
- **Data path:** `services/futures_service.py` (Polygon dedicated `/futures/v1/aggs`), plus CSV/Parquet for pre-built continuous series; `services/__init__.py` dispatches futures tickers to the futures endpoint. `helpers/continuous_contract.py` builds back-adjusted continuous series (panama/ratio + volume-roll). `helpers/data_quality.py` missing-bar check is calendar-aware (skipped for `CME_ETH`).
- **Config:** SECTION 27 `instruments` (asset-class defaults, per-root point-value/tick tables, per-symbol overrides), SECTION 28 `intrabar_resolution`/`intrabar_timeframe`/`intrabar_multiplier`, SECTION 29 `maintenance_margin_pct`.
- **Exit configs (v1.11.0, issue #234):**
  - `{"type":"trailing_atr","stop_mult":..,"trail_mult":..,"t1_mult":..,"point_cap":N,"floor":"breakeven"}` — Sleeve A mechanic: ATR **locked at the breakout bar** (the signal bar, `prev_trading_dates[entry_exec_date]` — assumes `execution_time="open"`); initial stop `entry - min(stop_mult*atr, point_cap)`; arms the trail when price reaches `entry + eff_stop_dist*(t1_mult/stop_mult)` (target is R:R off the *capped* stop); post-arm ratchets `running-max High - trail_mult*atr_locked` (trail leg uncapped), floored at literal entry. **Bidirectional** — `side="long"`/`"short"` mirror in `_update_trailing_atr_stop`; the short entry/cover loops wire the full stop/target/trail + margin-call + real InitialRisk/RMultiple, and open shorts are marked-to-market at end-of-backtest.
    - Known conservative assumptions (issue #234 review): on a bar hitting both init-stop and target, the engine resolves stop-first (pre-arm); maintenance-margin uses entry-price notional (calls marginally early).
  - `{"type":"atr","multiplier":..,"point_cap":N}` — ATR stop distance clipped at `N` points per trade (`instruments.atr_stop_level(point_cap=)`).
  - `maintenance_margin_pct` (SECTION 29): per-bar force-liquidation of a futures position when `margin + unrealized_pnl < notional*pct`, logged `ExitReason "Margin Call"`. `0.0` = disabled.
  - Futures data resolution is dynamic (`services/futures_service._resolution`): `MIN×5→"5min"`, `H×2→"2hour"`, `D→"1session"`.
  - `continuous_contract.rolls_spanned(entry, exit, roll_dates)` flags a held position crossing a roll (long-horizon guard).
- **Regression guard:** `tests/test_engine_characterization.py` (golden master) + `test_instruments.py`, `test_futures_engine.py`, `test_futures_service.py`, `test_continuous_contract.py`, `test_scaled_exits.py`, `test_intrabar.py`, `test_intrabar_wiring.py`, `test_data_quality_calendar.py`, `test_futures_234.py`.

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

### Polygon API Plan Limitation & Cache Validation Bug

**Plan history caps**: Polygon limits available history based on plan tier. A starter plan capped at ~2021; a paid plan extends that (confirmed: ~2016 on current plan). The `Actual Data Period` line in the run summary shows the true start Polygon returned — if it lags the configured `start_date`, the plan tier is the constraint. There is no pagination bug in `polygon_service.py` — the single page with 50,000-bar limit returns all available bars correctly.

**Cache validation bug (issue #123)**: The local Parquet cache keys data by *requested* date range, not actual returned range. If Polygon returns plan-capped data (e.g. 2016–now) for a 2004 request, the cache stores that truncated result under a key named `SPY_2004-01-01_..._day_1.parquet`. After a plan upgrade, subsequent runs still serve the old capped data from cache — silently — until the cache entry is manually deleted or expires. **Fix**: add start-date validation in the `helpers/caching.py` read path; if `df.index.min()` lags the requested start by >30 days, treat as a cache miss and re-fetch. See issue #123 for the full implementation spec.

**Index history cap is separate and tighter than the equities cap (issue #261)**: `I:VIX` and `I:TNX` (the two comparison-ticker dependencies most strategies rely on for regime gates) only return data from **2023-02-14 onward** on the current plan — confirmed for both symbols directly against the API, independent of the equities ~5yr rolling cap described above. Requesting an earlier `start_date` returns an empty result (HTTP 200, zero bars), not an error. Because `spy_df`/`vix_df` are injected as `None` when the fetch fails, and the None-guards added for issue-empty-comparison-tickers make `None` a *silent no-op* rather than a crash, any strategy whose regime/filter logic ANDs on `vix_df` (e.g. `MA Confluence (Full Stack) w/ Regime Filter`) will fail its gate closed for the whole requested window — **zero trades, no error, no warning** prior to this fix. `main.py`'s comparison-ticker fetch loop now logs an explicit warning when a failed fetch backs an active dependency (see the `dep_keys` check next to the `Failed to fetch data for comparison ticker` warning), but the underlying data-availability gap is a Polygon plan-tier limit, not a bug in this codebase — **use `data_provider = "yahoo"` (`^VIX`/`^TNX`, full history) for any backtest whose window starts before 2023-02-14 and depends on VIX/TNX-gated strategies.**

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
- **VIX timezone handling**: Yahoo Finance returns tz-aware UTC timestamps. `classify_vix_regime()` strips timezone info from both the series index and the lookup date before comparison to ensure correct alignment regardless of data provider. Without this, `pd.concat` raises `TypeError` (caught silently), every trade returns `REGIME_UNK`, and all heatmap cells show 0.0%.
- **Tests**: `tests/test_regime_heatmap.py` — 18 tests covering boundary VIX values, forward-fill, None guards, DataFrame shape, fractional P&L values, multi-year rows, stdout content, and tz-aware index handling.

## Init Wizard (--init)

```bash
rtk python main.py --init
```

Interactive four-step wizard for first-time setup. Writes `config_starter.py` to the project root.

**Four steps:**
1. **Data provider** — choose `yahoo` / `csv` / `polygon` / `norgate`. If Polygon is selected, optionally enter the API key (appended to `.env`).
2. **Capital & dates** — `initial_capital` (default 100 000), `start_date` (default 2010-01-01). End date is always a dynamic `datetime.now()` expression in the written file.
3. **What to test** — `single` (comma-separated tickers → written as `"My Symbols": [...]` in `portfolios`) or `portfolio` (nasdaq100 JSON or custom named list → `portfolios`).
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
| `mc_sampling` | `"iid"` | `"iid"` = independent resampling (original behaviour); `"block"` = block-bootstrap; `"auto"` = block for a `concentrated_futures` smoothness profile, else iid |
| `mc_block_size` | `None` | Trades per block. `None` = auto: `floor(sqrt(N))` (Politis-Romano rule of thumb) |

- **`"iid"` (default)**: trades are resampled independently, each with equal probability. Fast and statistically clean for strategies with no autocorrelation.
- **`"block"`**: consecutive blocks of `block_size` trades are sampled as a unit, preserving win/loss streaks and regime clustering. Use when the strategy shows known regime dependency (e.g., consistently loses only during bear markets / high-VIX periods identified by the Regime Heatmap).
- **`"auto"` (issue #243)**: resolved per strategy in `main.py::run_single_simulation` via `helpers.smoothness_profiles.resolve_mc_sampling` — a `concentrated_futures` profile (single-instrument regime-dependent strategy, e.g. Sleeve A) gets `"block"`, everything else `"iid"`. This calibrates the MC **"DD-Understated"** verdict, which i.i.d. resampling structurally trips for that strategy class. Applied via a **scoped `CONFIG["mc_sampling"]` override** (restored in a `finally`) around the MC call — `helpers/monte_carlo.py` is Do-Not-Touch, so the effective method is chosen at the caller. The effective value is stored on the result as `mc_sampling_effective` and feeds `mc_sampling_caveat` (so the "consider block" note stays silent once block is actually used). Default stays `"iid"` → opt-in, no change to existing runs.
- **Auto block size**: `max(1, int(N ** 0.5))`. For 100 trades → blocks of 10; for 400 trades → blocks of 20.
- **Circular wrap**: blocks that extend past the end of the trade list wrap around — no trades are omitted and edge blocks are not under-represented.
- **No caller changes**: `run_monte_carlo_simulation` signature is unchanged. The refactor extracted a `_equity_and_drawdown` helper used by both branches.
- **Tests**: `tests/test_mc_block_bootstrap.py` — 9 tests: config defaults, output shapes, auto block size resolution, streak divergence (>1% std difference), small trade guard, i.i.d. seed match, and no-key default.

## Smoothness Verdict Profiles (asset-class-aware)

The curve-smoothness verdict (`compute_smoothness` in `helpers/llm_verdict.py`) grades an equity curve **SMOOTH / ACCEPTABLE / ROUGH** by counting how many of five failure conditions trip. Those five thresholds were originally hard-coded constants chosen for a steadily-compounding, many-name **equity** book. A concentrated, event-driven strategy (e.g. a single-instrument futures breakout sleeve — one instrument, long dead stretches between edges, risk-based sizing producing occasional big months) structurally trips `plateau >= 12` and `upthrust > 2` **when working exactly as intended** — that is what its curve looks like, not instability. Judging it against equity-book thresholds mislabels correct behaviour as ROUGH.

**`helpers/smoothness_profiles.py`** — pure, stateless module making the thresholds a named **profile**:

- `SMOOTHNESS_PROFILES` — `"equity"` (default; the legacy constants **byte-for-byte**) and `"concentrated_futures"` (looser: `r2_min` 0.70, `positive_months_min` 45, `longest_flat_max` 24, `upthrust_max` 6, `worst_month_min` -20).
- `get_thresholds(profile)` — `None` → equity defaults (no-regression); a name → that profile (unknown → equity + `[WARNING]`); a `dict` → partial/full override merged over equity defaults.
- `resolve_profile_name(symbols, config)` — precedence: (1) explicit `config["smoothness_profile"]` if not `"auto"`; (2) `"auto"` → derive from the portfolio's instrument **asset class** via `resolve_instrument` (all symbols futures → `concentrated_futures`, else `equity`); (3) `equity` fallback.
- `mc_sampling_caveat(mc_verdict, profile, mc_sampling)` — reporting-layer note folding in the MC **"DD Understated"** flag: fires only for a non-equity profile with a "DD Understated" verdict under `mc_sampling="iid"`, recommending `mc_sampling="block"` (block-bootstrap preserves the streak clustering these strategies live on). **Never touches `helpers/monte_carlo.py` or the MC score.**

**Config**: `smoothness_profile` (SECTION 18b, default `"auto"`) — `"auto"` | `"equity"` | `"concentrated_futures"`.

**Wiring**: `compute_smoothness(timeline, profile=None)` gains an optional profile (None = byte-identical equity default) and echoes the applied profile back in the `"profile"` result key. The worker (`main.py::run_single_simulation`) resolves the profile from `portfolio_data` symbols + `CONFIG`, stores `result["smoothness_profile"]` and (when applicable) `result["mc_sampling_note"]`, and passes the profile to `compute_smoothness`. The verdict is surfaced with its profile tag in **all** existing surfaces: `llm_verdict.json` (`smoothness_profile` + `curve_smoothness.profile` + `mc_sampling_note`), the terminal STRATEGY VERDICTS block (`helpers/verdict_format.py`), the PDF tearsheet (`trade_analyzer/report_generator.py`), and the verbose summary tables (`helpers/summary.py` — new `Smooth Prof.` column, short name `Prof`).

**No-regression guarantee**: default runs (`smoothness_profile="auto"` with equity portfolios, or `profile=None`) produce the exact legacy grades — `smooth_verdict` stays the raw `SMOOTH/ACCEPTABLE/ROUGH` string.

**Tests**: `tests/test_smoothness_profiles.py` — profile thresholds, dict-override merge, `resolve_profile_name` (explicit/auto/mixed/empty), byte-identical equity default, looser-profile-never-adds-failures invariant, and the MC caveat gating.

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

### ADV Window Was 20 *Bars*, Not 20 Trading Days (issues #264, #268 — fixed 2026-08-05)

Both ADV-based mechanics — the `max_pct_adv` liquidity cap (on by default at `0.05`) and the `volume_impact_coeff` market-impact model — computed "20-day average daily volume" as `rolling(window=20).mean()` over raw bars. Correct on daily data (20 bars == 20 trading days); wrong by orders of magnitude on intraday data, where 20 bars is ~100 minutes of 5-minute volume. This was the root cause of intraday backtests diverging from daily runs of the same strategy and of returns shifting non-proportionally with `initial_capital` (bigger capital → bigger share counts → hit the mis-scaled cap sooner).

Fixed in two parts:

1. **#264/#265 — window horizon + per-bar-vs-per-day rescale.** All four ADV call sites in `helpers/portfolio_simulations.py` (entry cap, entry impact, normal exit impact, intrabar same-bar close) now route through a single `_daily_adv()` closure, so they cannot drift independently again. The window spans 20 real sessions and the per-bar mean is rescaled into a daily figure. The correctness identity is `mean(20*bpd bars) * bpd == sum(window)/20`.
2. **#268 — exact, not truncated, bars-per-day.** That identity only holds while the window genuinely spans 20 days, so the rescale must use `get_bars_per_day_exact()` (float) rather than the truncated bar count. `get_bars_per_day()` truncates `6.5 / multiplier`, which cost 1H/2H/MIN60 7.7% and 4H 38.5% of their true ADV — leaving #264 closed only for `D`/`W`/`M` and `MIN` 5/15/30.

**Which helper to use:** `get_bars_per_day_exact(config) -> float` for any *scaling factor*; `get_bars_per_day(config) -> int` (which now delegates to it) only where a genuine bar *count* is needed. Both honour `timeframe_multiplier`, unlike `get_bars_for_period()` — whose H-timeframe multiplier bug is separate and tracked in #267.

**Direction of the old error:** understated ADV made the cap bind *earlier* and impact charge *more*, so affected runs looked worse than reality, never better.

`trading_hours_per_day <= 0` now raises on intraday timeframes instead of silently producing a zero ADV that rejected every trade.

D/W/M resolve to exactly `1.0`, so the window stays 20 and the rescale is `×1.0` — byte-for-byte no-op, golden master unaffected.

### Per-Symbol Session Length (issue #270)

`trading_hours_per_day` is one process-wide number, but instruments already resolve per symbol. A book mixing equities (6.5h RTH) with 24h futures therefore gets the wrong bars-per-day for one side of it whatever the global says — feeding the 20-day ADV window above.

`helpers/instruments.py::resolve_session_hours(symbol, config)` resolves it per symbol, in this precedence:

1. `instruments.overrides[SYMBOL]["session_hours"]` — explicit, always wins. **An override dict is authoritative for asset class**, so a futures symbol must spell out `{"asset_class": "future", "session_hours": 23}` — the contract-month auto-detection that recognises `ESM6` as a future is only consulted when the symbol has *no* override, and omitting `asset_class` silently resolves it as a cash equity (point_value 1.0, `cash_full` margin, fractional units, borrow charged, NYSE calendar). Pre-existing `resolve_instrument` precedence from #229; pinned by `TestOverrideKeepsFuturesClassification`.
2. `instruments.session_hours_from_calendar: True` — opt-in; derives from the instrument's calendar via `CALENDAR_SESSION_HOURS` (NYSE 6.5, CME_ETH **23.0** — CME electronic trading is Sun 17:00 → Fri 16:00 CT with a 60-minute daily maintenance break, so a session is 23h, not 24)
3. `trading_hours_per_day` — the existing global
4. `6.5`

Steps 3–4 are exactly the pre-#270 behaviour, so **a run that sets neither an override nor the opt-in flag is unaffected**. `get_bars_per_day_exact(config, session_hours=...)` takes the resolved value; `run_portfolio_simulation` computes `(window_bars, bars_per_day)` per symbol and caches them alongside the ADV memo.

**Scope decision — annualization stays global.** `get_bars_per_year()` shares the same session assumption but was deliberately left process-wide. Moving it per-symbol changes reported Sharpe/CAGR on existing futures runs, which is a reporting-comparability decision rather than a correctness fix; the ADV path has a concrete correctness impact and #265 had already isolated its call sites. Tracked as an open question on #270.

**Tests**: `tests/test_per_symbol_session_hours.py` — precedence ladder, opt-in defaults off, engine-level mixed-book cap divergence, and the no-regression default path.

### ADV Fix Tests

**Tests**: `tests/test_adv_liquidity_intraday.py` (window/cap/impact end-to-end on 5-min bars), `tests/test_bars_per_day_exact.py` (exact bars-per-day, delegation, 20-day-span invariant, plus `test_engine_end_to_end_uses_exact_bars_per_day` — a 4H simulation that is what actually pins the engine to the exact helper; the span-invariant tests reimplement the window formula and so cannot detect engine drift on their own).

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
