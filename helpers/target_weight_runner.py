"""helpers/target_weight_runner.py

Run a registered **target-weight** portfolio strategy through the normal
``main.py`` CLI/config/run-directory flow and write its run artifacts
(issue #487).

Selected by ``CONFIG["portfolio_strategy"]`` (or ``--portfolio-strategy``).
When unset, main.py never imports this module and the single-asset path is
unchanged.

Run-directory artifacts (``output/runs/<run_id>/``)::

    config_snapshot.json                          (written by main.py)
    overall_portfolio_summary.csv                 one row: the strategy
    llm_verdict.json                              strategy vs SPY / cash-sleeve verdict
    analyzer_csvs/<Portfolio>/<Strategy>.csv      executed fills (not round-trip trades)
    analyzer_csvs/<Portfolio>/<Strategy>_equity.csv   daily portfolio NAV
    analyzer_csvs/<Portfolio>/<Strategy>.portfolio.json  marker -> report.py portfolio mode
    portfolio_runs/<Portfolio>/<Strategy>/
        ledger.csv            daily NAV, cash, receivables, shares, weights, costs
        comparison_ledger.csv the same ledger under the other settlement mode
        fills.csv             every sale / purchase with settlement date
        signals.csv           strategy diagnostics (inputs, state, target weights)
        daily_returns.csv     strategy, immediate-settlement benchmark, cash sleeve, SPY
        annual_returns.csv
        settlement_calendar.csv
        metrics.json          metrics per period, costs, activity, validation, provenance
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime

import numpy as np
import pandas as pd

from helpers import target_weight_portfolio as twp

logger = logging.getLogger(__name__)

#: Config keys read by this runner (registered in helpers/config_validator.py).
CONFIG_DEFAULTS = {
    "portfolio_strategy": None,
    "portfolio_settlement": twp.SETTLED_ONLY,
    "portfolio_settlement_rules": [list(r) for r in twp.DEFAULT_SETTLEMENT_RULES],
    "portfolio_rebalance_band": None,       # None = the strategy's registered band
    "portfolio_cost_bps": None,             # None = the strategy's registered costs
    "portfolio_symbol_map": {},             # {ticker_or_role: provider_ticker}
    "portfolio_benchmark_ticker": "SPY",
    "portfolio_benchmark_cost_bps": 5.0,
}

MARKER_SUFFIX = ".portfolio.json"
MODE = "target_weight_portfolio"


class PortfolioDataError(ValueError):
    """The fetched data cannot support a funded multi-asset run (missing sessions etc.)."""


class PortfolioConfigError(ValueError):
    """A ``portfolio_*`` config value (or the timeframe) is invalid for a target-weight run."""


def _benchmark(config: dict):
    """Benchmark ticker; an explicit None or "" disables it."""
    if "portfolio_benchmark_ticker" in config:
        return config["portfolio_benchmark_ticker"] or None
    return CONFIG_DEFAULTS["portfolio_benchmark_ticker"]


def _cfg(config: dict, key: str):
    value = config.get(key)
    return CONFIG_DEFAULTS[key] if value is None else value


def resolve_strategy(config: dict) -> tuple[str, dict]:
    """``(name, registry entry)`` for ``config["portfolio_strategy"]``."""
    from helpers.registry import get_target_weight_strategies
    name = config.get("portfolio_strategy")
    available = get_target_weight_strategies()
    if name not in available:
        raise KeyError(f"portfolio_strategy {name!r} is not a registered target-weight strategy. "
                       f"Available: {sorted(available)}")
    return name, available[name]


def resolve_settings(entry: dict, config: dict) -> dict:
    """Validated run settings: settlement mode and rules, band, costs, symbol map.

    Every problem raises :class:`PortfolioConfigError`. In particular a cost
    override keyed by anything other than one of the strategy's products is
    refused: merging and ignoring it would run at the registered cost while
    the log shows the override.
    """
    tf, mult = config.get("timeframe", "D"), config.get("timeframe_multiplier", 1)
    if str(tf).upper() != "D" or int(mult or 1) != 1:
        raise PortfolioConfigError(f"Target-weight portfolios run on daily bars only (timeframe='D', "
                                   f"multiplier 1); got timeframe={tf!r}, multiplier={mult!r}")
    settlement = _cfg(config, "portfolio_settlement")
    if settlement not in (twp.SETTLED_ONLY, twp.IMMEDIATE):
        raise PortfolioConfigError(f"portfolio_settlement must be 'settled_only' or 'immediate', "
                                   f"got {settlement!r}")
    raw_rules = _cfg(config, "portfolio_settlement_rules")
    try:
        rules = []
        for effective, lag in raw_rules:
            when = pd.Timestamp(effective)
            if pd.isna(when) or isinstance(lag, bool) or int(lag) != lag or int(lag) < 1:
                raise ValueError(f"bad rule {[effective, lag]!r}")
            rules.append((str(effective), int(lag)))
        if not rules:
            raise ValueError("no rules")
    except (TypeError, ValueError) as exc:
        raise PortfolioConfigError(
            "portfolio_settlement_rules must be a list of [effective_date, lag_sessions >= 1] pairs, "
            "e.g. [['1900-01-01', 2], ['2024-05-28', 1]]; " + f"got {raw_rules!r} ({exc})") from exc
    band = config.get("portfolio_rebalance_band")
    if band is None:
        band = entry["band"]
    try:
        band = float(band)
    except (TypeError, ValueError):
        band = float("nan")
    if not (np.isfinite(band) and band >= 0):
        raise PortfolioConfigError(f"portfolio_rebalance_band must be a finite number >= 0 "
                                   f"(0.02 = 2 percentage points); got {config.get('portfolio_rebalance_band')!r}")
    products = list(entry["symbols"]) + [entry["cash_symbol"]]
    override = config.get("portfolio_cost_bps") or {}
    if not isinstance(override, dict):
        raise PortfolioConfigError(f"portfolio_cost_bps must be a mapping of product ticker to bps; "
                                   f"got {override!r}")
    unknown = sorted(str(k) for k in override if k not in products)
    if unknown:
        raise PortfolioConfigError(f"portfolio_cost_bps has keys that are not products of this strategy: "
                                   f"{unknown}. Valid keys (case-sensitive): {products}")
    cost_bps = dict(entry["cost_bps"])
    cost_bps.update(override)
    try:
        twp._validate_costs(cost_bps, products)
    except ValueError as exc:
        raise PortfolioConfigError(f"portfolio_cost_bps / registered costs invalid: {exc}") from exc
    symbol_map = _cfg(config, "portfolio_symbol_map")
    if not isinstance(symbol_map, dict) or not all(isinstance(k, str) and isinstance(v, str) and v
                                                   for k, v in symbol_map.items()):
        raise PortfolioConfigError("portfolio_symbol_map must map a ticker or signal role to a provider "
                                   "ticker, e.g. {'vix': '$VIX'}; " + f"got {symbol_map!r}")
    try:
        bench_cost = float(_cfg(config, "portfolio_benchmark_cost_bps"))
    except (TypeError, ValueError):
        bench_cost = float("nan")
    if not (np.isfinite(bench_cost) and 0 <= bench_cost < 10000):
        raise PortfolioConfigError("portfolio_benchmark_cost_bps must be finite, >= 0 and < 10000 bps")
    return {"settlement": settlement, "rules": rules, "band": band, "cost_bps": cost_bps,
            "symbol_map": dict(symbol_map), "benchmark_cost_bps": bench_cost}


def _naive_daily(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    df.index = idx.normalize()
    if df.index.has_duplicates:
        raise PortfolioDataError("Duplicate daily input dates")
    df = df.sort_index()
    return df


def _frame_digest(df: pd.DataFrame) -> str:
    cols = [c for c in ("Open", "Close") if c in df.columns]
    payload = pd.util.hash_pandas_object(df[cols], index=True).to_numpy().tobytes()
    return hashlib.sha256(payload).hexdigest()


def fetch_inputs(entry: dict, config: dict, fetcher) -> tuple[dict, dict]:
    """Fetch every product, signal input and the benchmark, with warm-up history.

    Returns ``(data, provenance)``. ``data`` is keyed by product ticker for
    products and the benchmark, and by role for signal inputs.
    """
    symbol_map = dict(_cfg(config, "portfolio_symbol_map") or {})
    start = pd.Timestamp(config["start_date"])
    warmup = int(config.get("pit_warmup_days", 400) or 0)
    fetch_start = (start - pd.Timedelta(days=max(warmup, 60))).strftime("%Y-%m-%d")
    end = config.get("end_date") or datetime.now().strftime("%Y-%m-%d")
    requests = {}
    for s in list(entry["symbols"]) + [entry["cash_symbol"]]:
        requests[s] = symbol_map.get(s, s)
    for role, ticker in entry["signal_symbols"].items():
        requests[role] = symbol_map.get(role, symbol_map.get(ticker, ticker))
    bench = _benchmark(config)
    if bench and bench not in requests:
        requests[bench] = symbol_map.get(bench, bench)
    data, provenance = {}, {}
    for key, ticker in requests.items():
        df = fetcher(ticker, fetch_start, end, config)
        if df is None or len(df) == 0:
            raise PortfolioDataError(f"No data for {key!r} (requested as {ticker!r}) "
                                     f"between {fetch_start} and {end}")
        df = _naive_daily(df)
        data[key] = df
        provenance[key] = {"ticker": ticker, "first": str(df.index[0].date()),
                           "last": str(df.index[-1].date()), "rows": int(len(df)),
                           "open_close_sha256": _frame_digest(df)}
    return data, provenance


def build_sessions(data: dict, products: list, cash_symbol: str, benchmark: str | None,
                   start: str, end: str | None, signal_roles=()) -> pd.DatetimeIndex:
    """Evaluation sessions: every bar of any product or the benchmark in [start, end].

    Every product (including the cash sleeve) and the benchmark must trade on
    every session with positive Open/Close, and every signal input must have a
    bar on every session and history before the first one. A product that
    starts after the first session, or ends before the last, refuses the run:
    no pre-inception history is synthesised and the window is never silently
    shortened.
    """
    lo = pd.Timestamp(start)
    hi = pd.Timestamp(end) if end else None
    tradables = list(products) + ([benchmark] if benchmark else [])
    union = pd.DatetimeIndex([])
    for s in tradables:
        idx = data[s].index
        union = union.union(idx[(idx >= lo) & ((idx <= hi) if hi is not None else True)])
    if union.empty:
        raise PortfolioDataError(f"No product bars between {start} and {end}")
    sessions = twp.xnys_sessions(lo, hi if hi is not None else union[-1])
    if sessions.empty or len(union.difference(sessions)):
        raise PortfolioDataError("Portfolio data contains dates outside XNYS trading sessions")
    problems = []
    for s in tradables:
        df = data[s]
        if df.index.min() > sessions[0]:
            problems.append(f"{s} starts {df.index.min().date()}, after the first session "
                            f"{sessions[0].date()}; set start_date >= {df.index.min().date()}")
            continue
        if df.index.max() < sessions[-1]:
            problems.append(f"{s} ends {df.index.max().date()}, before the last session "
                            f"{sessions[-1].date()}; set end_date <= {df.index.max().date()}")
            continue
        missing = sessions.difference(df.index)
        if len(missing):
            problems.append(f"{s} is missing {len(missing)} session(s), e.g. "
                            f"{[str(d.date()) for d in missing[:5]]}")
            continue
        px = df.loc[sessions, ["Open", "Close"]]
        if not np.isfinite(px.to_numpy(dtype=float)).all() or (px <= 0).any().any():
            problems.append(f"{s} has missing or non-positive Open/Close on a session")
    for role in signal_roles:
        df = data[role]
        if df.index.min() >= sessions[0]:
            problems.append(f"signal input {role!r} starts {df.index.min().date()}, with no history "
                            f"before the first session {sessions[0].date()} (provider history cap?)")
            continue
        missing = sessions.difference(df.index)
        if len(missing):
            problems.append(f"signal input {role!r} is missing {len(missing)} session(s), e.g. "
                            f"{[str(d.date()) for d in missing[:5]]}")
        elif not np.isfinite(df.loc[sessions, "Close"].to_numpy(dtype=float)).all():
            problems.append(f"signal input {role!r} has a missing Close on a session")
    if problems:
        raise PortfolioDataError("Target-weight run refused; the data cannot support a funded "
                                 "multi-asset ledger:\n  - " + "\n  - ".join(problems))
    return sessions


def compute_targets(entry: dict, data: dict, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    """Run the strategy on the full history and align its targets to *sessions*."""
    params = dict(entry["params"])
    raw = entry["logic"](data, **params)
    if not isinstance(raw, pd.DataFrame):
        raise TypeError("A target-weight strategy must return a DataFrame")
    raw = raw.copy()
    raw.index = pd.DatetimeIndex(raw.index).normalize()
    if raw.index.tz is not None:
        raw.index = raw.index.tz_localize(None)
    aligned = raw.reindex(sessions)
    weights = aligned[list(entry["symbols"])]
    if weights.isna().any().any():
        bad = weights.index[weights.isna().any(axis=1)]
        raise PortfolioDataError(f"Strategy produced no target for {len(bad)} session(s), e.g. "
                                 f"{[str(d.date()) for d in bad[:5]]}")
    return aligned


def _period_masks(sessions: pd.DatetimeIndex, periods: dict) -> dict:
    masks = {"Full period": np.ones(len(sessions), dtype=bool)}
    for label, (lo, hi) in (periods or {}).items():
        m = sessions >= pd.Timestamp(lo)
        if hi:
            m &= sessions <= pd.Timestamp(hi)
        if m.sum() >= 2:
            masks[label] = m
    return masks


def run_target_weight_backtest(config: dict, run_dir: str, run_id: str, fetcher) -> dict:
    """Execute ``config["portfolio_strategy"]`` and write all run artifacts.

    Returns a summary dict (also stored in ``metrics.json``).
    """
    from helpers.summary import _safe_strategy_name, safe_path_component

    name, entry = resolve_strategy(config)
    settings = resolve_settings(entry, config)
    settlement, rules, band = settings["settlement"], settings["rules"], settings["band"]
    cost_bps, bench_cost = settings["cost_bps"], settings["benchmark_cost_bps"]
    capital = float(config.get("initial_capital", 100000.0))
    if not (np.isfinite(capital) and capital > 0):
        raise PortfolioConfigError(f"initial_capital must be positive and finite; got {capital!r}")
    bench = _benchmark(config)
    products = list(entry["symbols"]) + [entry["cash_symbol"]]
    cash_symbol = entry["cash_symbol"]

    logger.info("=" * 60)
    logger.info("  TARGET-WEIGHT PORTFOLIO RUN (issue #487)")
    logger.info(f"  Strategy   : {name}")
    logger.info(f"  Products   : {entry['symbols']} + cash sleeve {cash_symbol}")
    logger.info(f"  Settlement : {settlement}   band: {band:.2%}   costs (bps): {cost_bps}")
    logger.info("=" * 60)

    data, provenance = fetch_inputs(entry, config, fetcher)
    sessions = build_sessions(data, products, cash_symbol, bench,
                              config["start_date"], config.get("end_date"),
                              signal_roles=list(entry["signal_symbols"]))
    signals = compute_targets(entry, data, sessions)
    opens = pd.DataFrame({s: data[s]["Open"].reindex(sessions) for s in products})
    closes = pd.DataFrame({s: data[s]["Close"].reindex(sessions) for s in products})
    targets = signals[list(entry["symbols"])].astype(float)
    settle_map = twp.settlement_dates(sessions, rules)
    common = dict(exposure=entry["exposure"], band=band, cost_bps=cost_bps,
                  settle_map=settle_map, settlement_rules=rules, initial_capital=capital)

    result = twp.simulate_target_weights(opens, closes, targets, entry["symbols"], cash_symbol,
                                         settlement=settlement, **common)
    other = twp.IMMEDIATE if settlement == twp.SETTLED_ONLY else twp.SETTLED_ONLY
    alt = twp.simulate_target_weights(opens, closes, targets, entry["symbols"], cash_symbol,
                                      settlement=other, **common)
    zero = pd.DataFrame(0.0, index=sessions, columns=list(entry["symbols"]))
    cash_only = twp.simulate_target_weights(opens, closes, zero, entry["symbols"], cash_symbol,
                                            settlement=twp.SETTLED_ONLY, **common)
    cash_ref = closes[cash_symbol].pct_change(fill_method=None)
    cash_ref.iloc[0] = closes[cash_symbol].iloc[0] / opens[cash_symbol].iloc[0] - 1

    series = {"Strategy": result.returns,
              f"Strategy ({other} settlement)": alt.returns,
              f"{cash_symbol} (cash sleeve)": cash_only.returns}
    if bench:
        series[bench] = twp.buy_and_hold_returns(data[bench]["Open"].reindex(sessions),
                                                 data[bench]["Close"].reindex(sessions), bench_cost)
    daily = pd.DataFrame(series)

    masks = _period_masks(sessions, entry.get("report_periods"))
    period_metrics = {}
    for label, m in masks.items():
        period_metrics[label] = {}
        for col in daily.columns:
            period_metrics[label][col] = twp.performance_metrics(daily[col][m], cash_ref[m])
        led = result.ledger[m]
        period_metrics[label]["Strategy"].update({
            "mean_cash_sleeve_weight": float(led[f"{cash_symbol}_weight"].mean()),
            "mean_unsettled_weight": float(led["unsettled_weight"].mean()),
            "unfilled_target_days": int(led["target_unfilled_at_open"].sum()),
            "turnover_sum": float(led["turnover"].sum()),
            "cost_sum": float(led["cost"].sum()),
        })

    ledger = result.ledger
    fills = result.fills
    cost_by_symbol = (fills.groupby("Symbol")["Cost"].sum().reindex(products, fill_value=0.0)
                      if not fills.empty else pd.Series(0.0, index=products))
    notional_by_symbol = (fills.groupby("Symbol")["Notional"].sum().reindex(products, fill_value=0.0)
                          if not fills.empty else pd.Series(0.0, index=products))
    validation = {
        "sessions": int(len(sessions)),
        "start": str(sessions[0].date()), "end": str(sessions[-1].date()),
        "min_cash": float(ledger["cash"].min()),
        "min_unsettled": float(ledger["unsettled"].min()),
        "min_shares": float(ledger[[f"{s}_shares" for s in products]].min().min()),
        "cash_or_holdings_negative": bool(ledger["cash"].min() < 0
                                          or (ledger[[f"{s}_shares" for s in products]] < 0).any().any()),
        "borrowing": 0.0,
        "share_shorting": False,
        "self_financing_checked_each_session": True,
        "signal_timing": "target decided at close t-1, executed at open t; session 0 starts in the cash sleeve",
        "cash_interest_added": False,
        "distribution_treatment": "Adjusted total-return prices; distributions modelled as reinvested in the unit price, not as payment-date cash",
        "settlement_calendar": "XNYS sessions minus US federal (bank) holidays; conservative, not a certified broker clearing calendar",
    }
    states = signals["state"].value_counts().to_dict() if "state" in signals.columns else {}
    final_nav = float(ledger["nav"].iloc[-1])
    full = period_metrics["Full period"]
    rebalance_fills = fills[fills["Reason"] == "rebalance"]
    summary = {
        "mode": MODE,
        "run_id": run_id,
        "strategy": name,
        "portfolio": entry["portfolio_name"],
        "description": entry.get("description", ""),
        "symbols": list(entry["symbols"]),
        "cash_symbol": cash_symbol,
        "signal_symbols": dict(entry["signal_symbols"]),
        "exposure": entry["exposure"],
        "cost_bps": cost_bps,
        "band": band,
        "settlement": settlement,
        "settlement_rules": [list(r) for r in rules],
        "benchmark": bench,
        "benchmark_cost_bps": bench_cost,
        "initial_capital": capital,
        "final_nav": final_nav,
        "params": dict(entry["params"]),
        "periods": period_metrics,
        "costs": {"total": float(ledger["cost"].sum()),
                  "by_symbol": {k: float(v) for k, v in cost_by_symbol.items()},
                  "traded_notional_by_symbol": {k: float(v) for k, v in notional_by_symbol.items()}},
        # "rebalance_sessions" counts sessions where the rule fired; while sale
        # proceeds are unsettled it can fire without trading, so the sessions
        # that executed a rebalance fill are reported separately.
        "activity": {"rebalance_sessions": int(ledger["rebalanced"].sum()),
                     "rebalance_sessions_traded": int(rebalance_fills["Date"].nunique()),
                     "fills": int(len(fills)),
                     "rebalance_fills": int(len(rebalance_fills)),
                     "unfilled_target_days": int(ledger["target_unfilled_at_open"].sum()),
                     "signal_state_sessions": {str(k): int(v) for k, v in states.items()}},
        "validation": validation,
        "provenance": {"data_provider": config.get("data_provider"),
                       "parquet_data_dir": config.get("parquet_data_dir"),
                       "csv_data_dir": config.get("csv_data_dir"),
                       "inputs": provenance},
        "not_evaluated": ["walk-forward analysis", "Monte Carlo resampling", "independent holdout"],
    }

    portfolio_dir = safe_path_component(entry["portfolio_name"])
    stem = _safe_strategy_name(name)
    art_dir = os.path.join(run_dir, "portfolio_runs", portfolio_dir, stem)
    csv_dir = os.path.join(run_dir, "analyzer_csvs", portfolio_dir)
    os.makedirs(art_dir, exist_ok=True)
    os.makedirs(csv_dir, exist_ok=True)

    ledger.to_csv(os.path.join(art_dir, "ledger.csv"), index_label="date", float_format="%.17g")
    alt.ledger.to_csv(os.path.join(art_dir, "comparison_ledger.csv"), index_label="date", float_format="%.17g")
    fills.to_csv(os.path.join(art_dir, "fills.csv"), index=False, float_format="%.17g")
    signals.to_csv(os.path.join(art_dir, "signals.csv"), index_label="date", float_format="%.17g")
    daily.to_csv(os.path.join(art_dir, "daily_returns.csv"), index_label="date", float_format="%.17g")
    ((1 + daily).groupby(sessions.year).prod() - 1).to_csv(
        os.path.join(art_dir, "annual_returns.csv"), index_label="year")
    pd.Series(settle_map, name="settlement_date").to_csv(
        os.path.join(art_dir, "settlement_calendar.csv"), index_label="trade_date")
    with open(os.path.join(art_dir, "metrics.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)

    fills.to_csv(os.path.join(csv_dir, f"{stem}.csv"), index=False, float_format="%.17g")
    ledger["nav"].rename("Equity").to_csv(os.path.join(csv_dir, f"{stem}_equity.csv"),
                                          index_label="Date", float_format="%.17g")
    marker = {"mode": MODE, "strategy": name, "portfolio": entry["portfolio_name"],
              "artifacts": os.path.relpath(art_dir, csv_dir)}
    with open(os.path.join(csv_dir, f"{stem}{MARKER_SUFFIX}"), "w", encoding="utf-8") as fh:
        json.dump(marker, fh, indent=2)

    s = full["Strategy"]
    row = {"Strategy": name, "Portfolio": entry["portfolio_name"], "Mode": MODE,
           "Start": s["start"], "End": s["end"], "Sessions": s["observations"],
           "Total Return": s["total_return"], "CAGR": s["cagr"], "Max Drawdown": s["max_drawdown"],
           "Volatility": s["volatility"], "Sharpe vs cash sleeve": s.get("sharpe_cash_reference"),
           "Sharpe (rf=2%)": s["sharpe_rf2"], "Calmar": s["calmar"],
           "Total Cost": summary["costs"]["total"], "Rebalance Sessions": summary["activity"]["rebalance_sessions"],
           "Unfilled Target Days": summary["activity"]["unfilled_target_days"]}
    for col in daily.columns[1:]:
        row[f"{col} Total Return"] = full[col]["total_return"]
        row[f"{col} CAGR"] = full[col]["cagr"]
    pd.DataFrame([row]).to_csv(os.path.join(run_dir, "overall_portfolio_summary.csv"), index=False)

    _write_verdict(run_dir, run_id, summary, ledger["nav"], daily)
    logger.info(f"  Strategy  CAGR {s['cagr']:+.2%}  MaxDD {s['max_drawdown']:.2%}  "
                f"Sharpe vs {cash_symbol} {s.get('sharpe_cash_reference') or float('nan'):.3f}")
    for col in daily.columns[1:]:
        logger.info(f"  {col:<28} CAGR {full[col]['cagr']:+.2%}  MaxDD {full[col]['max_drawdown']:.2%}")
    logger.info(f"  Artifacts: {art_dir}")
    logger.info(f"  Report   : python report.py --all {run_dir}")
    return summary


def _write_verdict(run_dir, run_id, summary, nav, daily):
    """llm_verdict.json in the shape report.py/LLM tooling already read."""
    full = summary["periods"]["Full period"]
    strat = full["Strategy"]
    benchmarks = {}
    for col in daily.columns[1:]:
        if "settlement" in col:
            continue
        bh = full[col]["total_return"]
        margin_pp = round((strat["total_return"] - bh) * 100, 4)
        beats = margin_pp > 0
        label = col.replace(" (cash sleeve)", "")
        direction = f"+{margin_pp:.2f}pp" if beats else f"{margin_pp:.2f}pp"
        benchmarks[label] = {"bh_return_pct": round(bh * 100, 4), "beats": bool(beats),
                             "outperformance_pp": margin_pp,
                             "cagr_pct": round(full[col]["cagr"] * 100, 4),
                             "max_drawdown_pct": round(full[col]["max_drawdown"] * 100, 4),
                             "verdict": (f"BEATS {label} by {direction}" if beats
                                         else f"LAGS {label} by {direction}")}
    primary = summary.get("benchmark")
    primary_detail = benchmarks.get(primary, {})
    try:
        from helpers.llm_verdict import compute_smoothness
        smooth = compute_smoothness(nav)
    except Exception as exc:  # noqa: BLE001 - verdict extras must not fail the run
        smooth = {"error": str(exc)}
    entry = {
        "strategy": summary["strategy"], "portfolio": summary["portfolio"], "mode": MODE,
        "total_return_pct": round(strat["total_return"] * 100, 4),
        "cagr_pct": round(strat["cagr"] * 100, 4),
        "max_drawdown_pct": round(strat["max_drawdown"] * 100, 4),
        "sharpe_vs_cash_sleeve": strat.get("sharpe_cash_reference"),
        "benchmarks": benchmarks,
        f"beats_{(primary or 'benchmark').lower()}": primary_detail.get("beats"),
        "verdict": primary_detail.get("verdict", "No benchmark configured"),
        "mc_verdict": "Not run (target-weight portfolio mode)",
        "wfa_verdict": "Not run (target-weight portfolio mode)",
        "curve_smoothness": smooth,
    }
    with open(os.path.join(run_dir, "llm_verdict.json"), "w", encoding="utf-8") as fh:
        json.dump({"run_id": run_id, "mode": MODE, "strategies": [entry]}, fh, indent=2, default=str)
