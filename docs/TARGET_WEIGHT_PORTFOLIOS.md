# Target-weight portfolio strategies (issue #487)

A **target-weight** strategy holds a fully funded *basket*: several products at
once plus an idle-cash sleeve, rebalanced toward portfolio weights its signal
chooses. The classic engine cannot express that: it simulates one independent
position per symbol and reports closed round trips. This is a separate,
explicit path. The single-asset path is unchanged: `main.py` only enters it
when `portfolio_strategy` is set, the registry never hands these plugins to the
per-symbol pipeline, and `report.py` only switches to the portfolio tearsheet
when a run wrote the portfolio marker file.

| Piece | File |
|---|---|
| Engine (NAV ledger, settlement, costs, invariants) | `helpers/target_weight_portfolio.py` |
| Plugin interface | `helpers/registry.py` → `register_target_weight`, `get_target_weight_strategies` |
| Run orchestration and artifacts | `helpers/target_weight_runner.py` |
| Portfolio tearsheet (PDF + Markdown) | `trade_analyzer/portfolio_report.py`, dispatched by `report.py` |
| VIX eVRP / VIX3M plugin | `custom_strategies/vix_evrp_sgov.py` |
| Frozen-input staging and parity check for PR #179 | `scripts/vix_evrp_stage_frozen_inputs.py`, `scripts/vix_evrp_parity.py` |
| Tests | `tests/test_target_weight_portfolio.py` |

## Writing a strategy

```python
from helpers.registry import register_target_weight

@register_target_weight(
    name="My Basket",
    symbols=["VIXY", "SVXY"],          # risk products, purchase-priority order
    cash_symbol="SGOV",                # gets every dollar of settled idle cash
    signal_symbols={"spy": "SPY"},     # inputs that are not traded, keyed by role
    exposure={"VIXY": 1.0, "SVXY": -0.5},  # signed exposure per unit value (for the band)
    cost_bps={"VIXY": 5, "SVXY": 5, "SGOV": 1},
    band=0.02,
    params={"window": 10},
)
def my_basket(data, window=10, **kwargs):
    # data["spy"], data["VIXY"], ... : full history incl. warm-up, OHLCV
    # return: one row per session close, one column per risk symbol (>= 0, sum <= 1)
    ...
```

Row `t` of the returned frame is decided at the close of session `t` and
executed at the **open of `t+1`**. The cash sleeve takes `1 - sum(weights)`.
Extra columns (signal inputs, a `state` label) are kept as diagnostics and
plotted in the report. Without `exposure`, the band applies to the largest
risk-weight drift instead of signed exposure.

## Accounting contract

* **Fully funded cash account.** No borrowing, negative cash, negative shares
  or short-sale proceeds. Inverse exposure comes from *holding* an inverse
  product. Violations raise `FundingViolation`, and every open is checked as
  self-financing (`value after = value before - costs`).
* **Timing.** Prior-close target, next-open execution. Session 0 starts 100%
  in the cash sleeve.
* **Rebalance rule.** Trade on the first session, when a held risk product's
  target is zero, when a targeted risk product is not held, when the sign of
  signed exposure changes, or when `|target - current| > band`.
* **Settlement.** Sales create receivables that settle on the `lag`-th
  eligible session after the trade (T+2, then T+1 from 2024-05-28).
  Receivables count in NAV. Eligible sessions are XNYS trading sessions minus
  US federal (bank) holidays. Days when the exchange is open but banks are
  closed (Columbus Day, Veterans Day) therefore do not settle, and
  `USFederalHolidayCalendar` also moves Saturday holidays to the Friday
  (2021-06-18, 2021-12-31, 2023-11-10), which the Fed does not observe. This
  is a conservative assumption, not a certified broker clearing calendar.
  Every run simulates three settlement modes and reports all of them;
  `portfolio_settlement` picks the headline:

  | Mode | Rule | Use |
  |---|---|---|
  | `settled_only` (default) | only settled cash buys | stricter than Regulation T; the PR #179 parity path |
  | `gfv_aware` | risk purchases may spend unsettled proceeds, but those shares are never sold before the proceeds settle; the cash sleeve buys with settled cash only | the Reg T cash-account rule (no good-faith violations) |
  | `immediate` | proceeds reused at the same open, unrestricted | upper bound; can commit good-faith violations, not executable |

  On the frozen PR #179 window the gap between `settled_only` (6.43% CAGR)
  and `gfv_aware` (8.84%) is mostly model conservatism. It is **not** a cost
  a real cash account pays. `immediate` gives 8.63%. The gfv_aware
  restrictions are written per lot to `gfv_restricted_lots.csv`, and each
  BUY fill records `UnsettledFunding` / `RestrictedUntil`.

  Only the receivable-funded part of a fill is restricted. There is one lot
  per receivable, freed on that receivable's settlement date; the part paid
  with settled cash is free at once. A whole-fill lock, where the entire fill
  stays locked until the latest receivable it used settles, is the stricter
  reading of the broker rule. It costs about 0.23 pp/yr on the frozen window
  (8.61% vs 8.84% CAGR, independently reproduced in the PR #489 review).
* **Missed targets are flagged two ways.** `target_unfilled_at_open` compares
  the aggregate (total risk weight, or signed exposure) with its target by
  more than the band; it is the flag the PR #179 parity checks.
  `product_unfilled_at_open` flags a rebalance session on which any single
  product's executed weight misses its own target by more than the band. It
  catches a blocked switch, e.g. 100% A to 100% B under `gfv_aware`, that
  still holds 100% A and so reads as filled in aggregate. The counts are
  `unfilled_target_days` and `unfilled_product_days`.
* **Stale intentions never execute.** Each open re-reads the latest prior-close target.
* **Costs** are in bps of traded notional on every sale and purchase,
  including the initial cash-sleeve buy. Units are fractional, there are no
  minimum commissions, and positions are not liquidated at the end.
* **Distributions** reach NAV only through total-return adjusted prices
  (reinvested in the unit price). The engine adds no cash flows and no cash
  interest beyond the cash-sleeve product's own return. The runner
  classifies the provider's prices (`validation.price_basis`) and derives the
  report's distribution text from it:

  | Provider (`price_adjustment="total_return"`) | `price_basis` |
  |---|---|
  | `norgate` | `total_return` |
  | `yahoo` (`auto_adjust=True`) | `total_return` |
  | `polygon` | `price_only`: `adjusted=true` is **split-only**, so dividends are lost (for SGOV, the whole T-bill yield) |
  | `parquet`, `csv` | `as_supplied`: the engine cannot verify your files |
  | any provider with `price_adjustment` other than `"total_return"` | `price_only` |

  A `price_only` run is refused unless `portfolio_allow_price_only=True`. In
  that case page 1 of the report carries a PRICE-ONLY flag.

## Config / CLI

| Key | Default | Meaning |
|---|---|---|
| `portfolio_strategy` | `None` | Name of a `@register_target_weight` plugin; `None` = normal run. CLI `--portfolio-strategy` |
| `portfolio_settlement` | `"settled_only"` | headline series: `"settled_only"`, `"gfv_aware"` or `"immediate"`; all three are always reported |
| `portfolio_settlement_rules` | `[["1900-01-01", 2], ["2024-05-28", 1]]` | `[effective_date, lag]` |
| `portfolio_rebalance_band` | `None` | override the plugin's band |
| `portfolio_cost_bps` | `None` | per-symbol override, e.g. stress `{"VIXY": 20, "SVXY": 20, "SGOV": 5}` |
| `portfolio_symbol_map` | `{}` | provider ticker remap, e.g. `{"vix": "$VIX", "vix3m": "$VIX3M"}` for a Norgate-named corpus. A remap to a *different* instrument (e.g. `{"SGOV": "BIL"}`) runs, but is recorded in `metrics.json["substitutions"]` and flagged on page 1, because the inception and coverage checks then apply to the substitute |
| `portfolio_benchmark_ticker` | `"SPY"` | buy-and-hold comparison (`None`/`""` disables); the cash sleeve is always shown too |
| `portfolio_benchmark_cost_bps` | `5.0` | one-time benchmark entry cost |
| `portfolio_allow_price_only` | `False` | run on `price_only` inputs anyway (see Distributions) |
| `portfolio_allow_benchmark_substitution` | `False` | A benchmark whose data would come from another ticker is refused by default. That happens through `portfolio_symbol_map`, or through a signal role with the benchmark's name, since roles, products and the benchmark share one data key space. `True` runs it anyway, with a warning and a page-1 flag |
| `risk_free_rate` | `0.05` | the repo-wide key; used for the tearsheet's rf Sharpe (`sharpe_rf`). `metrics.json` also keeps `sharpe_rf2` at a fixed 2% for parity with the study |

Invalid `portfolio_*` values refuse the run (`PortfolioConfigError`) before
any data is fetched:

- `portfolio_cost_bps` keys must be the strategy's own product tickers,
  case-sensitive. An unknown key (`"vixy"`) is an error, not an ignored
  entry, so a mistyped stress run cannot complete at the registered cost.
  Every cost must be finite, `>= 0` and `< 10000` bps; the engine enforces
  the same rule on its `cost_bps` argument.
- `portfolio_rebalance_band` must be finite and `>= 0`;
  `portfolio_settlement_rules` must be `[effective_date, lag >= 1]` pairs;
  `portfolio_symbol_map` must map strings to non-empty strings.

From the CLI, the three structured keys take JSON through `--set`:
`portfolio_cost_bps` and `portfolio_symbol_map` a JSON object,
`portfolio_settlement_rules` a JSON array, e.g.
`--set 'portfolio_symbol_map={"vix": "$VIX", "vix3m": "$VIX3M"}'`. Malformed
JSON, an invalid `portfolio_*` value and a data refusal all print one
`[ERROR]` line and exit with status 1. Engine invariant failures
(`FundingViolation`) still raise.

Evaluation sessions are every bar of any product or the benchmark in
`[start_date, end_date]`. The run is refused, with the offending dates listed,
when any of these holds:

- a product, the cash sleeve or the benchmark starts after the first session,
  ends before the last one, or misses a session in between. Pre-inception
  history is never synthesised and the window is never silently shortened;
- a signal input misses a session, or has no history before the first
  session (e.g. a provider history cap such as Polygon's `I:VIX` from
  2023-02-14);
- the timeframe is anything other than daily (`timeframe="D"`, multiplier 1);
- `start_date` is before the plugin's `valid_from` date. The VIX eVRP plugin
  declares `2018-02-28`, because SVXY was a -1x product before then and its
  `-0.5` exposure coefficient would be wrong.

All inputs are fetched `max(pit_warmup_days, 60)` calendar days before
`start_date` so that signals are warm.

With `exposure` set, every risk symbol needs a non-zero coefficient, and each
session may target at most one risk product. Otherwise signed exposure does
not identify the basket; use `exposure=None` (per-product weight band)
instead. A risk product with a positive target that is not held always
triggers a rebalance.

## Run artifacts

```
output/runs/<run_id>/
  config_snapshot.json, overall_portfolio_summary.csv, llm_verdict.json
  analyzer_csvs/<Portfolio>/<Strategy>.csv              executed fills (not round-trip trades)
  analyzer_csvs/<Portfolio>/<Strategy>_equity.csv       daily portfolio NAV
  analyzer_csvs/<Portfolio>/<Strategy>.portfolio.json   marker -> report.py portfolio tearsheet
  portfolio_runs/<Portfolio>/<Strategy>/
     ledger.csv  comparison_ledger.csv  comparison_ledger_<mode>.csv  gfv_restricted_lots.csv
     fills.csv  signals.csv  daily_returns.csv  annual_returns.csv  settlement_calendar.csv  metrics.json
```

`python report.py --all output/runs/<run_id>` (or single-file mode on the
fills CSV) writes `detailed_reports/<Portfolio>/<Strategy>/<Strategy>.pdf`
and `.md`. Every figure is built from the **portfolio NAV ledger**:

1. KPIs, NAV vs SPY / cash sleeve / the other two settlement series, and
   drawdown. PRICE-ONLY and SUBSTITUTED INPUT flags sit under the title.
2. Holdings (products, cash sleeve, unsettled receivables), target vs executed
   signed exposure (with sessions where the target was not reached at the
   open), and signal inputs/state.
3. Metrics per period (full period plus the plugin's `report_periods`),
   calendar-year returns, and costs by symbol.
4. Rebalance activity, recent fills, validation results and assumptions.

Reporting conventions worth knowing when reading the tearsheet:

- Activity separates sessions where the rebalance rule *fired*
  (`activity.rebalance_sessions`) from sessions that *executed* a rebalance
  fill (`activity.rebalance_sessions_traded`). While sale proceeds are
  unsettled the rule fires with nothing to trade. Purchases below the dust
  threshold (`1e-14 x capital`) are not written to the fills ledger, as for
  sales and cash parking; the NAV arithmetic is unchanged.
- The band is printed in percentage points (`2 pp`, `2.5 pp`).
- The cash sleeve's own "Sharpe vs cash sleeve" is shown as `—`: against
  itself it differs only by its entry fee. `metrics.json` keeps the raw value.
- With `portfolio_settlement: "immediate"` as the primary run, page 1, the
  Markdown header and the notes mark the result as a non-deployable
  benchmark, and the notes describe same-open reuse instead of settled cash.
- With the benchmark disabled, tiles and notes omit it.

The trade analyzer, Monte Carlo and WFA are not used for these runs. Basket
rebalance fills have no meaningful per-trade P&L, so the report says these
analyses were not run instead of showing numbers.

Metric conventions follow the PR #179 study: CAGR annualises by
`sessions / 252`; drawdown is measured from `max(initial capital, running
peak)`; "Sharpe vs cash sleeve" is annualised mean excess return over the
cash-sleeve product divided by excess volatility. The single-asset
tearsheet's calendar-day CAGR is not used here.

## Reproducing private-strategies PR #179

The frozen inputs are licensed and private. Stage them into the git-ignored
`output/` tree and never commit them.

```sh
STUDY=<private-strategies checkout>/research/vix_evrp_dual_signal

# 1. Stage the frozen CSV panels as per-symbol parquet (verifies SHA256SUMS first)
python scripts/vix_evrp_stage_frozen_inputs.py --study-dir "$STUDY"

# 2. Engine run through the normal CLI
python main.py --provider parquet --parquet-dir output/frozen_inputs/vix_evrp_pr179 \
  --start 2020-05-28 --end 2026-04-22 --capital 100000 \
  --portfolio-strategy "VIX eVRP Dual (SGOV funded)" --name vix-evrp-pr179

# 3. Native report
python report.py --all output/runs/vix-evrp-pr179_<timestamp>

# 4. Reference ledger from the study's own simulator, written to scratch
python "$STUDY/sgov_study.py" --output /tmp/vix_evrp_reference

# 5. Parity
python scripts/vix_evrp_parity.py --run-dir output/runs/vix-evrp-pr179_<timestamp> \
  --reference-dir /tmp/vix_evrp_reference
```

The parity script checks session dates, the settlement calendar, the daily
ledger (NAV, return, cash, receivables, shares and weights per product,
signed target, close exposure, cost, turnover, unfilled-target flag), the
immediate-settlement, SGOV and SPY return paths, and every period metric in
the study's `metrics.csv`. The reference ledgers are written with 12
significant digits, so ledger values are compared at `rtol = 1e-10`. Metrics
are recomputed at full precision and compared at `atol = 1e-9`. Booleans and
counts must match exactly.

Repeat the engine command with a different run name and
`--set 'portfolio_cost_bps={"VIXY":20,"SVXY":20,"SGOV":5}'` to produce the
stress run. Run the same report and parity commands on that directory. Each
run writes the primary ledger and the alternate settlement ledger
(`comparison_ledger.csv`). Same-open proceeds reuse is a non-deployable
benchmark for this cash account. At baseline, parity compares to
`dual_combined_settled_only_vol5_sgov1.csv` and
`dual_combined_immediate_benchmark_vol5_sgov1.csv`. At stress it selects
their `vol20_sgov5` twins. Both normalized NAV and daily returns use
`abs(error) <= 1e-10 + 1e-10 * abs(reference)`. The reference SGOV
buy-and-hold path includes only the baseline fee, so the parity checker
compares that benchmark only at baseline.

The frozen replay passes 211 checks at baseline and 173 under stress,
including the full daily ledger for both settlement modes at both fee levels.

### Differences and limitations

* **Settlement calendar.** XNYS sessions from `exchange-calendars` 4.10.1
  intersect US federal bank days, including beyond the end of the price
  history. The runner rejects missing market sessions, invalid signal targets,
  and duplicate dates. SPY warmup prices use consecutive XNYS sessions.
* **Staged OHLCV.** The frozen panel carries only Open/Close. The staging
  script sets High/Low to max/min(Open, Close) and Volume to 0 to fit the
  provider schema. The engine reads only Open and Close.
* **Evidence limits, unchanged from the study.** Adjusted-price
  distribution treatment, a conservative rather than broker-certified
  settlement calendar, fractional units, no independent holdout, no
  walk-forward or Monte Carlo validation. This is research only: no paper
  or live activation.
