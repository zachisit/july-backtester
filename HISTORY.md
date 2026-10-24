# Release History

## [Unreleased]

- Position sizing reports per-run stop-input, proxy, cap, cash/margin, ADV, and heat conditions for every entry leg, including zero-trade runs. Tiny equity shorts now honor the same minimum size as longs (#387/#394).

- Futures short entries honor the ADV cap and adverse entry impact, report both impact legs, and recheck actual stop risk after impact; margin affordability uses the slipped/impacted fill (#468).

- Opening Kelly orders use only trades completed before the fill bar; closing orders retain same-bar completed outcomes (#466).

- Futures long heat uses its actual known stop risk, including a final market-impact check, rather than a sizing proxy (#467).

## [1.16.0] — Backtest-integrity epic (#424)

> **Results change.** Most fixes in this release remove optimistic biases, so headline numbers for
> existing configs will move (usually down). Each behaviour change has a config switch that restores
> the old behaviour, listed in brackets.

### Fixed — engine (fill realism)
- **Gap-through stops fill at the open**, not at the unreachable stop level (#425) [`stop_gap_fill: "level"`].
- **Stops are checked on the fill bar** under `execution_time="open"` (#426) [`entry_bar_stop_check: False`].
- **Equity curve recorded at end of bar**, so exits at the open show on the bar they happen (#438).
- **ADV cap / market impact use prior-bar volume** under open execution, with no same-bar look-ahead (#436).
- **Equity shorts reserve collateral** (Reg-T 50% by default), so gross short leverage is bounded (#430) [`short_margin_requirement: 0.0`].
- **Delisted positions are liquidated inside the daily loop**, so later sizing no longer uses phantom equity (#431; subsumes #149).

### Fixed — validation layer
- **WFA measures IS/OOS on window equity** and annualises over the window length; compounding no longer inflates OOS (#427).
- **Rolling WFA fold 0 / empty IS no longer auto-passes**; opt-in anchored fold layout (#428).
- **MC Score v2**: a bootstrap mean-edge test replaces the near-tautological performance test, and DD realism compares closed-trade DD with closed-trade DD. The legacy score is kept as `mc_score_legacy` (#429).

### Fixed — results & data
- **Zero-trade and errored strategies are accounted for** ("Not shown: N with 0 trades, M errored"), not silently dropped (#432).
- **Unique strategy names for every stop config**, plus `base_strategy` / `param_label` / `stop_label` metadata (#434).
- **Sensitivity report: one verdict per portfolio × strategy × stop config** (#435).
- **Short-lived names are kept in survivorship-aware universes**, and `pit_warmup_days` is now wired, so indicators warm up before `start_date` (#433) [`pit_warmup_days: 0`].
- **Polygon retries 429/5xx**, never caches partial pagination, and writes `fetch_failures.csv` (#437) [`polygon_max_retries`].
- **Optional `random_seed` / `--seed`** for reproducible MC, bootstrap and noise (#439).
- **`verbose_output` config is honoured**; new `--no-verbose` flag (#440).
- **Yahoo includes the `end_date` bar** (#441).

### RC audit follow-ups (#460)
- Keep seed-label component boundaries unambiguous, defer delisting prices from the current Close until after open entries, and preserve position-size metadata on delisting trades.
- Integrate configurable short sizing with collateral/commission budgets, and apply floating-point affordability corrections against free buying power.
- Fix UTC delisting liquidation, re-entry after delisting, future delistings leaking into earlier runs, and missing safety-net exit commissions.
- Refine fill-bar stops with intraday data and include entry commissions in short collateral sizing.
- Preserve warm-up signals, structural stop history and ADV through the first execution bar; warm strategy dependencies while keeping benchmark/WFA periods inside the selected window.
- Include the final day's trades and intraday equity in WFA; exclude N/A folds and infer anchored IS history correctly.
- Apply block sampling to the MC edge test when selected; distinguish fractional percentage stops, ATR caps and trailing floors in sensitivity labels.
- Pass resolved runtime settings to spawned workers so CLI overrides, including `--seed`, apply consistently on macOS and Windows.

### Fixed
- **`pit:` rosters: an unquoted `ON` parsed as a boolean (all data providers).** PyYAML reads an
  unquoted `- ON` as `True`, so in the NQ100 2023–2025 rosters ON Semiconductor became the ticker
  `TRUE` and a `pit:nq100` run traded TrueCar in its place, whichever `data_provider` was set.
  Rosters are now read with `load_roster_yaml()`, which keeps every entry a string. Shipped in #407.
- **`pit:` + `data_provider = "parquet"`: delisted members were dropped or swapped for another
  company.** Membership is now resolved to parquet security IDs (`TICKER-YYYYMM` for delisted
  securities) before the loader, so a dead member is no longer masked by a live file that reuses
  its ticker, or dropped when several dated files match. Runs abort, naming each member, if one
  cannot be resolved. Other providers are unchanged. #407.
- **Parquet span-index cache now rebuilds when the corpus changes** (#409).

## [1.3.0] — 2026-04-07

**Norgate → Parquet pipeline + private data submodule**

> **Superseded.** Everything in this release's "Added" section was removed from this
> repository in 2026-09: the Norgate export scripts, the export guide, and the
> `parquet_data/` submodule. The export tooling existed to maintain a specific
> private dataset rather than to serve this project, and the submodule made that
> dataset a hard dependency of a public repo.
>
> Note this does NOT apply to `custom_strategies/private`, which is deliberately
> retained even though it is also a private submodule: nothing here clones with
> `--recurse-submodules` unprompted (the README gates it behind "for interns with
> private strategies" and no workflow checks out submodules), and it holds
> strategies this project actually runs rather than tooling for maintaining a
> dataset.
> The Parquet data provider remains and is source-agnostic — supply your own
> directory of `{SYMBOL}.parquet` files via `parquet_data_dir` / `--parquet-dir`.
> This entry is left intact as a record of what shipped, not as instructions.

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
