# Release History

## [1.3.0] — 2026-04-07

**Norgate → Parquet pipeline + private data submodule**

### Added
- **`--database` flag** in `norgate_to_parquet.py` — export every symbol in an entire Norgate database (`US Equities`, `US Equities Delisted`, `US Indices`) without needing a watchlist. Enables a complete 1:1 local dump of all 36,418 Norgate symbols in three commands.
- **`validate_norgate_export.py`** — cross-checks all three Norgate databases against local `parquet_data/` and reports missing symbols per-database. Run after export to confirm `STATUS: ALL PRESENT`.
- **`scripts/NORGATE_EXPORT.md`** — step-by-step guide for the full 3-step Norgate dump, data refresh workflow, validation, and targeted re-exports.
- **`parquet_data/` git submodule** — mounts `zachisit/july-backtester-norgate-data` (private, Git LFS) at `parquet_data/`. Interns clone the full 2.6 GB dataset with `git clone --recurse-submodules`. Follows the same pattern as the existing `custom_strategies/private` submodule.

### Fixed
- **Index symbol export failures** — `CANONICAL_INDEX_MAP` in `ticker_normalizer.py` had all Norgate entries set to Polygon's `I:` prefix instead of Norgate's native `$` prefix (`$VIX`, `$SPX`, `$DJI`, etc.). This caused 7 index symbols to fail during `US Indices` database export. All 1,615 indices now export cleanly.
- **`$VIX` filename preservation** — `_sanitize_filename()` correctly preserves the `$` prefix (not a Windows-illegal character), so Norgate index files land as `$VIX.parquet` rather than `I_VIX.parquet`.

### Notes
- `CON.parquet` and `PRN.parquet` excluded from the data submodule — Windows reserved device names cannot be tracked by git. Fix tracked in issue #108.
- Git LFS required to clone the data submodule (`git lfs install` before first clone).

---

## [1.2.0] — 2026-04-06

**Parquet data provider + config simplification**

### Added
- **Parquet data provider** — set `"data_provider": "parquet"` and point `"parquet_data_dir"` at a folder of per-symbol `.parquet` files. Recommended path for running against Norgate-exported data. No API key required.

### Changed
- **`symbols_to_test` removed** — all symbol lists now go through `portfolios`. Replace any `symbols_to_test: ["AAPL"]` in your config with `"portfolios": {"My Symbols": ["AAPL"]}`. The setup wizard (`python main.py --init`) already writes the new format.
- `comparison_tickers: []` is now valid — pure parquet runs with no SPY/VIX files no longer require a workaround.

### Fixed
- `ValueError: The truth value of a DataFrame is ambiguous` — FATAL crash at startup when SPY was a comparison ticker.
- `NameError: name 'spy_df' is not defined` — crash when `comparison_tickers: []` and WFA was enabled.
- `AttributeError` in simulation workers when `spy_df` or `vix_df` was `None` (empty comparison_tickers path).
- `NameError: name 'vix_df_global' is not defined` — leftover variable from old architecture.
- PDF report equity vs benchmark chart now correctly aligns dates when running with parquet data (timezone mismatch fixed).

---

## [1.1.0] — 2026-03-30

**Complete intraday support + new strategies**

### Added
- **Intraday backtesting** — hourly (`H`) and minute (`MIN`) timeframes with automatic metrics annualization (Sharpe, Sortino, HTB fees adjust based on bars-per-year).
- **WFA bar-count splitting** — Walk-Forward Analysis splits by trading bars for intraday, giving accurate 80/20 IS/OOS partitioning at any timeframe.
- **Datetime index normalization** — daily data normalized to midnight UTC; intraday preserves hour/minute precision; ISO 8601 trade log format.
- **3 new strategies** — Bollinger Band Mean Reversion w/ ATR stop, Williams %R Oversold Bounce, Volume-Weighted RSI.

### Fixed
- Default `data_provider` set to `"yahoo"` (free, no API key required out of the box).
- Init wizard now writes directly to `config.py`.

---

## [1.0.11] — 2026-03-24

**Tiered summary tables, Mermaid diagrams, config validation**

### Added
- Tiered terminal output — compact 7-column default view; `--verbose` flag unlocks all 23 columns (Extended Metrics + Robustness tables).
- Config key validation with "did you mean?" suggestions for typos.
- Mermaid flowcharts in README for quickstart and lifecycle diagrams.

---

## [1.0.10] — 2026-03-19

**Infrastructure**

### Added
- GitHub PR template with bonus work policy.

---

## [1.0.9] — 2026-03-17

**Tier 2 enhancements: Recovery Time, MC Block-Bootstrap, Volume Impact, Rolling WFA, ML Export**

### Added
- **Recovery time metrics** — `max_recovery_days` and `avg_recovery_days` in all summary tables.
- **MC block-bootstrap** — `mc_sampling: "block"` preserves win/loss streaks and regime clustering in Monte Carlo simulations.
- **Volume-based market impact slippage** — `volume_impact_coeff` applies square-root market impact on top of flat slippage.
- **Rolling multi-fold WFA** — `wfa_folds` splits the full period into k equal-width OOS windows for more robust walk-forward validation.
- **ML trade feature export** — `export_ml_features: true` writes a consolidated Parquet file of all trades with entry features for downstream ML work.

---

## [1.0.8] — 2026-03-17

**Tier 1 enhancements: Sensitivity Sweep, Rolling Sharpe, Short Selling, Regime Heatmap, Init Wizard**

### Added
- **Parameter sensitivity sweep** — `sensitivity_sweep_enabled: true` varies each strategy param by ±N% to detect p-hacking / fragile optimizations.
- **Rolling Sharpe (126-day)** — `Roll.Sharpe(avg/min/last)` columns in all summary tables.
- **Short selling** — signal `-2` enters a short; `htb_rate_annual` debits hard-to-borrow fees daily.
- **VIX regime heatmap** — per-strategy year × regime P&L table printed after each simulation.
- **Setup wizard** — `python main.py --init` interactive first-time config builder.

---

## [1.0.7] — 2026-03-13

**Pre-open-source bug fix pass**

### Fixed
- ATR column name mismatch (`ATR` → `ATR_14`) — ATR stop configs now trigger correctly.
- `save_only_filtered_trades` was saving all trades regardless of display filters — now correctly saves only strategies that passed the summary filters.

---

## [1.0.6] — 2026-03-13

**Advanced risk analytics, plugin library migration, liquidity filtering**

### Added
- R-Multiple, Expectancy, and SQN metrics in summary tables and PDF tearsheet.
- Underwater plot (drawdown duration banner) in PDF tearsheet.
- Volume-based liquidity filter (`max_pct_adv`) — caps position size as a fraction of 20-day ADV.
- Annual Turnover % and Estimated After-Tax CAGR in PDF overall metrics section.
- All legacy strategies migrated to plugin files in `custom_strategies/`.

---

## [1.0.5] — 2026-03-12

**Monte Carlo noise injection & robustness reporting**

### Added
- `noise_injection_pct` — injects random ±N% OHLC noise before running strategies for stress testing.
- MC block-bootstrap foundation and sampling infrastructure.
- `mc_score_min_to_show_in_summary` filter.

---

## [1.0.4] — 2026-03-11

**Data providers, correlation matrix, plugin architecture**

### Added
- **Yahoo Finance** data provider (`data_provider: "yahoo"`) — free, no API key.
- **CSV** data provider (`data_provider: "csv"`) — local per-symbol CSV files.
- Strategy correlation matrix — written to `<portfolio>_strategy_correlation.csv` per run.
- Plugin architecture — strategies live in `custom_strategies/`; no core files need editing to add a strategy.
- `comparison_tickers` config — flexible benchmark/dependency ticker configuration.

---

## [1.0.3] — 2026-03-05

**Test suite backfill and simulation progress visibility**

### Added
- Comprehensive test suite backfill across core modules.
- Progress logging during simulation runs.

---

## [1.0.2] — 2026-03-05

**S2 development cycle**

### Added
- S2 startup validation — catches bad config before fetching any data.
- `--dry-run` flag — validates config and prints run summary without fetching data.

---

## [1.0.1] — 2026-03-04

**Unified output architecture and trade analyzer integration**

### Added
- Run-first output structure: `output/runs/<run_id>/` with `logs/`, `raw_trades/`, `analyzer_csvs/`, `detailed_reports/`.
- `report.py` auto-detects run directory from any path inside `analyzer_csvs/`.

---

## [1.0.0] — 2026-03-04

**Initial release**

- Monte Carlo simulation (1,000-path, IID resampling).
- Walk-Forward Analysis (IS/OOS split by `wfa_split_ratio`).
- Polygon.io and Norgate data providers.
- Portfolio mode — test strategies across multi-symbol baskets (Nasdaq 100, S&P 500, custom JSON lists).
- PDF tearsheet generation via `report.py` — equity curve, drawdown, R-Multiple histogram, VIX regime heatmap.
- Summary table with Sharpe, Calmar, Win Rate, MC Score, WFA Verdict, SPY/QQQ outperformance.
