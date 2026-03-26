# Coverage Improvement Session — Handoff

**Branch:** `chore/improve-coverage-helpers-services`
**Session date:** 2026-03-26
**Starting coverage:** 64% (648 tests)
**Last measured coverage:** 74% (994 tests) — 4 more test files added since, ~88 additional tests
**Estimated current coverage:** ~76-78% (not measured — full suite times out in CI tool)

> **Note on running coverage:** `python -m pytest tests/ --cov=. ...` takes ~3 minutes with 1000+ tests.
> Run locally with `timeout` or use: `python -m pytest tests/ --cov=. --cov-report=term -q --tb=no`

---

## What Was Accomplished (13 commits total)

### Session 1 (8 commits — baseline 64% → 74%)

| File | Tests | Focus |
|------|-------|-------|
| `tests/test_trade_analyzer_calculations.py` | 73 | Sharpe, Sortino, CAGR, Calmar, Alpha/Beta, VaR/CVaR, drawdown, streaks |
| `tests/test_timeframe_utils.py` | 22 | `get_bars_for_period()` all branches D/H/MIN |
| `tests/test_aws_utils.py` | 7 | `upload_file_to_s3` (mocked boto3), `get_secret` |
| `tests/test_caching.py` | 15 | Cache miss, round-trip, TTL expiry, corrupt file, symbol sanitization |
| `tests/test_services_factory.py` | 11 | Factory functions: polygon/yahoo/csv/norgate, invalid provider |
| `tests/test_monte_carlo_analysis.py` | 17 | `helpers/monte_carlo.py` scoring rubric all branches |
| `tests/test_data_handler.py` | 32 | Column remapping, string cleaning, NaN drops, derived columns |
| `tests/test_summary_functions.py` | 22 | `format_duration`, sensitivity report, save CSV, guard conditions |
| `tests/test_custom_strategy_execution.py` | 140 | 35 daily strategies × 4 assertions (parametrized) |
| `tests/test_services_caching_wrapper.py` | 7 | `services/services.py` cache hit/miss, None/empty not cached |

### Session 2 (4 commits — continuing from 74%)

| File | Tests | Focus |
|------|-------|-------|
| `tests/test_trade_analyzer_monte_carlo.py` | 35 | `run_monte_carlo_simulation`: guard clauses, output structure, ruin detection, % returns mode, drawdown_as_negative flag |
| `tests/test_data_handler_extended.py` | 20 | Missing optional cols, Return_Frac branches, `Cum. Profit` fallback, `calculate_daily_returns` edge cases, yfinance mock paths |
| `tests/test_analyzer.py` | 9 | `generate_trade_report` config restore lifecycle, `_run_analysis` guards (< 2 trades, OSError mkdir) |
| `tests/test_simulations.py` | 24 | `calculate_advanced_metrics` (win rate, profit factor, drawdown, Calmar, recovery time), `calculate_rolling_sharpe` |

**Total tests added this branch: ~417**

---

## Remaining Coverage Gaps

### High-value, feasible to test next

| Module | Gap Description |
|--------|-----------------|
| `helpers/portfolio_simulations.py` | `run_portfolio_simulation` — large function, heavily coupled to external data (spy_df, vix_df, tnx_df). Mock the data inputs. |
| `trade_analyzer/analyzer.py` lines 130–413 | The main `_run_analysis` body past the guard clauses — WFA section, report section generation loop, MC section. Requires stubbing `report_generator`, `plotting`, `calculations`. |
| `helpers/noise.py` | Noise generation helpers — likely pure math, no tests exist. |
| `helpers/regime.py` | Regime detection — likely pure math, no tests exist. |

### Intentionally skipped (low value or untestable in isolation)

| Module | Reason |
|--------|--------|
| `trade_analyzer/plotting.py` | matplotlib rendering — no meaningful assertions without visual comparison |
| `trade_analyzer/report_generator.py` | PDF via WeasyPrint — requires browser engine, fragile in CI |
| `helpers/init_wizard.py` | Interactive CLI wizard — requires stdin simulation |
| `services/norgate_service.py` | Requires licensed Norgate Data installation |

---

## Key Gotchas (save for future sessions)

1. **`generate_sensitivity_report` uses `from config import CONFIG` inside the function body** → `patch("helpers.summary.CONFIG")` has no effect. Use `patch.dict("config.CONFIG", {...})` instead.

2. **`run_monte_carlo_simulation` in `trade_analyzer/calculations.py` is a separate implementation** from `helpers/monte_carlo.py`. Both exist. Tests for one don't cover the other.

3. **MC percentile testing: use uniform arrays.** `[0.30]*190 + [0.85]*10` does NOT give 95th pct = 0.85 due to numpy interpolation. Use `[0.85]*200` for exact result.

4. **`services/services.py` caching wrapper reads `timeframe` from the per-call config dict** (last positional arg), not global `CONFIG`.

5. **`clean_trades_data` requires a `Profit` column** — the Win computation at line 178 crashes with `KeyError` if it's absent, making the `Return_Frac` fallback branches effectively dead code.

6. **`_run_analysis` in `analyzer.py` stubs need to cover ~12 downstream callables** to avoid matplotlib/PDF/yfinance side effects. See `_stub_downstream()` in `tests/test_analyzer.py` for the pattern.

7. **Full test suite takes ~3 minutes.** Never run `python -m pytest tests/ --cov=...` during the inner loop. Only run the specific new test file: `python -m pytest tests/test_new_file.py -v --tb=short`. Run full suite once at the end.

---

## How to Resume

```bash
git checkout chore/improve-coverage-helpers-services

# Verify new tests pass (fast — ~2s each)
python -m pytest tests/test_simulations.py tests/test_analyzer.py -v

# Run full suite ONCE for final coverage number (takes ~3 min)
python -m pytest tests/ --cov=. --cov-report=term -q --tb=no

# Recommended next targets (read the file, write tests, run only that file):
# 1. helpers/noise.py
# 2. helpers/regime.py
# 3. helpers/portfolio_simulations.py (mock spy_df/vix_df/tnx_df)
```
