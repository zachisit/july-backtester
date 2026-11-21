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
  eligible session after the trade (T+2, then T+1 from 2024-05-28). Only
  settled cash buys; receivables count in NAV but cannot be spent. Eligible
  sessions are the data's own trading sessions minus US federal (bank)
  holidays. Days when the exchange is open but banks are closed (Columbus Day,
  Veterans Day) therefore do not settle. This is the conservative
  cash-account assumption, not a certified broker clearing calendar.
  `portfolio_settlement: "immediate"` reuses proceeds at the same open and is
  reported only as a benchmark.
* **Stale intentions never execute.** Each open re-reads the latest prior-close target.
* **Costs** are in bps of traded notional on every sale and purchase,
  including the initial cash-sleeve buy. Units are fractional, there are no
  minimum commissions, and positions are not liquidated at the end.
* **Distributions** are carried by adjusted (total-return) prices, i.e.
  reinvested in the unit price, not booked as payment-date cash. No cash
  interest is added beyond the cash-sleeve product's own return.

## Config / CLI

| Key | Default | Meaning |
|---|---|---|
| `portfolio_strategy` | `None` | Name of a `@register_target_weight` plugin; `None` = normal run. CLI `--portfolio-strategy` |
| `portfolio_settlement` | `"settled_only"` | or `"immediate"` (benchmark) |
| `portfolio_settlement_rules` | `[["1900-01-01", 2], ["2024-05-28", 1]]` | `[effective_date, lag]` |
| `portfolio_rebalance_band` | `None` | override the plugin's band |
| `portfolio_cost_bps` | `None` | per-symbol override, e.g. stress `{"VIXY": 20, "SVXY": 20, "SGOV": 5}` |
| `portfolio_symbol_map` | `{}` | provider ticker remap, e.g. `{"vix": "$VIX", "vix3m": "$VIX3M"}` for a Norgate-named corpus |
| `portfolio_benchmark_ticker` | `"SPY"` | buy-and-hold comparison (`None`/`""` disables); the cash sleeve is always shown too |
| `portfolio_benchmark_cost_bps` | `5.0` | one-time benchmark entry cost |

Evaluation sessions are every bar of any product or the benchmark in
`[start_date, end_date]`. The run is refused, with the offending dates listed,
when any of these holds:

- a product, the cash sleeve or the benchmark starts after the first session,
  ends before the last one, or misses a session in between. Pre-inception
  history is never synthesised and the window is never silently shortened;
- a signal input misses a session, or has no history before the first
  session (e.g. a provider history cap such as Polygon's `I:VIX` from
  2023-02-14);
- the timeframe is anything other than daily (`timeframe="D"`, multiplier 1).

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
     ledger.csv  fills.csv  signals.csv  daily_returns.csv  annual_returns.csv
     settlement_calendar.csv  metrics.json
```

`python report.py --all output/runs/<run_id>` (or single-file mode on the
fills CSV) writes `detailed_reports/<Portfolio>/<Strategy>/<Strategy>.pdf`
and `.md`. Every figure is built from the **portfolio NAV ledger**:

1. KPIs, NAV vs SPY / cash sleeve / immediate-settlement benchmark, and drawdown.
2. Holdings (products, cash sleeve, unsettled receivables), target vs executed
   signed exposure (with sessions where the target was not reached at the
   open), and signal inputs/state.
3. Metrics per period (full period plus the plugin's `report_periods`),
   calendar-year returns, and costs by symbol.
4. Rebalance activity, recent fills, validation results and assumptions.

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

Result on the frozen data: all **194/194** checks pass. The largest
differences come from the reference CSV's rounding: ledger 5.0e-12,
immediate-settlement returns 5.0e-14, SPY returns 4.7e-13, metrics ≤ 1.6e-11.
The settlement calendar, the 90 unfilled-target sessions and the session count
(1,483) are identical.

### Differences and limitations

* **Settlement calendar source.** The study builds eligible days from the
  `exchange_calendars` XNYS calendar. The engine uses the data's own sessions
  and does not add that dependency. Settlement lags must be >= 1 session. Both remove federal holidays. On this
  sample the two calendars are identical (checked by the parity script). A
  data set with a missing session is refused, so the two cannot drift
  silently. Settlement dates after the last session use business days. They
  cannot affect results, because receivables count in NAV either way.
* **Staged OHLCV.** The frozen panel carries only Open/Close. The staging
  script sets High/Low to max/min(Open, Close) and Volume to 0 to fit the
  provider schema. The engine reads only Open and Close.
* **Evidence limits, unchanged from the study.** Adjusted-price
  distribution treatment, a conservative rather than broker-certified
  settlement calendar, fractional units, no independent holdout, no
  walk-forward or Monte Carlo validation. This is research only: no paper
  or live activation.
