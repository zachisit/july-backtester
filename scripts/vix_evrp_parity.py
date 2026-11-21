"""Compare an engine run of the VIX eVRP strategy with the PR #179 frozen ledger (issue #487).

Produce the reference with the study's own simulator, writing to a scratch
directory so the private review checkout is not modified::

    python <study>/sgov_study.py --output /tmp/vix_evrp_reference

then run the engine on the staged frozen inputs (see
docs/TARGET_WEIGHT_PORTFOLIOS.md) and compare::

    python scripts/vix_evrp_parity.py \\
        --run-dir output/runs/<run_id> --reference-dir /tmp/vix_evrp_reference

Checks (all must pass; exit status 1 otherwise):

* identical session dates and settlement calendar;
* daily NAV (normalised by initial capital), returns, cash, receivables,
  shares, weights, signed target and close exposure, per-session cost and
  turnover, and the unfilled-target flag — for the settled-cash primary path
  and the immediate-reinvestment benchmark;
* SGOV and SPY benchmark daily returns;
* every period metric the study reports.

Tolerances: the reference ledgers are written with 12 significant digits
(``%.12g``), so ledger values are compared at ``rtol=1e-10`` (with an absolute
floor of 1e-10 times capital for values that should be zero). Metrics come
from full-precision recomputation and are compared at ``atol=1e-9``. Booleans
and counts must match exactly. Results go to ``<run-dir>/parity/parity.json``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

STRATEGY_STEM = "VIX_eVRP_Dual_SGOV_funded"
PORTFOLIO_DIR = "VIXY-SVXY-SGOV"
REF_PRIMARY = "dual_combined_settled_only_vol5_sgov1"
REF_IMMEDIATE = "dual_combined_immediate_benchmark_vol5_sgov1"
PERIODS = {"full_sgov_history": "Full period", "2022_onward": "2022 onward",
           "t1_era": "T+1 era", "post_publication_seen": "Post publication"}
METRICS = ["total_return", "cagr", "volatility", "max_drawdown", "sharpe_rf0", "sharpe_rf2",
           "calmar", "sharpe_cash_reference", "annualized_excess_mean"]
STRATEGY_EXTRA = {"mean_sgov_weight": "mean_cash_sleeve_weight",
                  "mean_unsettled_weight": "mean_unsettled_weight",
                  "unfilled_target_days": "unfilled_target_days",
                  "turnover_sum": "turnover_sum"}
LEDGER_RTOL = 1e-10
METRIC_ATOL = 1e-9


def _compare(label, ours, ref, *, rtol=LEDGER_RTOL, atol=0.0, exact=False):
    ours = np.asarray(ours, dtype=float)
    ref = np.asarray(ref, dtype=float)
    if ours.shape != ref.shape:
        return {"check": label, "ok": False, "detail": f"shape {ours.shape} vs {ref.shape}"}
    diff = np.abs(ours - ref)
    if exact:
        ok = bool(np.array_equal(ours, ref))
    else:
        ok = bool(np.all(diff <= atol + rtol * np.abs(ref)))
    return {"check": label, "ok": ok, "max_abs_diff": float(diff.max()) if diff.size else 0.0,
            "max_rel_diff": float(np.max(diff / np.maximum(np.abs(ref), 1e-300))) if diff.size else 0.0}


def compare_ledger(tag, ours: pd.DataFrame, ref: pd.DataFrame, capital: float) -> list:
    out = [{"check": f"{tag}: session dates", "ok": bool(ours.index.equals(ref.index)),
            "sessions": int(len(ours))}]
    if not out[0]["ok"]:
        return out
    floor = 1e-10
    scaled = {"nav": "nav", "cash": "cash", "unsettled": "unsettled", "cost": "cost"}
    for ours_col, ref_col in scaled.items():
        out.append(_compare(f"{tag}: {ours_col}", ours[ours_col] / capital, ref[ref_col], atol=floor))
    for col in ["return", "target", "unsettled_weight", "turnover"]:
        out.append(_compare(f"{tag}: {col}", ours[col], ref[col], atol=floor))
    out.append(_compare(f"{tag}: index exposure at close", ours["exposure_close"],
                        ref["index_exposure_close"], atol=floor))
    for s in ["VIXY", "SVXY", "SGOV"]:
        out.append(_compare(f"{tag}: {s} shares", ours[f"{s}_shares"] / capital, ref[f"{s}_shares"], atol=floor))
        out.append(_compare(f"{tag}: {s} weight", ours[f"{s}_weight"], ref[f"{s}_weight"], atol=floor))
    out.append(_compare(f"{tag}: target unfilled at open",
                        ours["target_unfilled_at_open"].astype(bool),
                        ref["target_unfilled_at_open"].astype(bool), exact=True))
    return out


def compare_metrics(summary: dict, ref_metrics: pd.DataFrame) -> list:
    out = []
    cash = summary["cash_symbol"]
    names = {REF_PRIMARY: "Strategy", REF_IMMEDIATE: "Strategy (immediate settlement)",
             "SGOV": f"{cash} (cash sleeve)", "SPY": summary.get("benchmark") or "SPY"}
    for _, row in ref_metrics.iterrows():
        if row["name"] not in names or row["sample"] not in PERIODS:
            continue
        period = PERIODS[row["sample"]]
        ours = summary["periods"].get(period, {}).get(names[row["name"]])
        if ours is None:
            out.append({"check": f"metrics {row['name']}/{period}", "ok": False, "detail": "missing"})
            continue
        keys = list(METRICS) + ["observations"]
        if row["name"] == REF_PRIMARY:
            keys += list(STRATEGY_EXTRA)
        for k in keys:
            ref_v = row.get(k)
            our_v = ours.get(STRATEGY_EXTRA.get(k, k))
            if pd.isna(ref_v) and our_v is None:
                continue
            if pd.isna(ref_v) or our_v is None:
                out.append({"check": f"metrics {row['name']}/{period}/{k}", "ok": False,
                            "detail": f"{our_v!r} vs {ref_v!r}"})
                continue
            exact = k in ("observations", "unfilled_target_days")
            out.append(_compare(f"metrics {row['name']}/{period}/{k}", [our_v], [ref_v],
                                rtol=0.0, atol=0.0 if exact else METRIC_ATOL, exact=exact))
    return out


def run(run_dir: Path, ref_dir: Path) -> dict:
    art = run_dir / "portfolio_runs" / PORTFOLIO_DIR / STRATEGY_STEM
    summary = json.loads((art / "metrics.json").read_text())
    capital = float(summary["initial_capital"])
    ledger = pd.read_csv(art / "ledger.csv", index_col=0, parse_dates=True)
    daily = pd.read_csv(art / "daily_returns.csv", index_col=0, parse_dates=True)
    read = dict(index_col=0, parse_dates=True)
    checks = compare_ledger("settled-cash ledger", ledger,
                            pd.read_csv(ref_dir / "ledgers" / f"{REF_PRIMARY}.csv", **read), capital)
    # The immediate-settlement path is recomputed with the same engine and inputs.
    from helpers import target_weight_portfolio as twp
    ref_imm = pd.read_csv(ref_dir / "ledgers" / f"{REF_IMMEDIATE}.csv", **read)
    imm_returns = daily["Strategy (immediate settlement)"]
    checks.append(_compare("immediate benchmark: return", imm_returns, ref_imm["return"], atol=1e-10))
    ref_daily = pd.read_csv(ref_dir / "daily_returns.csv", **read)
    cash = summary["cash_symbol"]
    checks.append(_compare("cash-sleeve benchmark: return", daily[f"{cash} (cash sleeve)"],
                           ref_daily["SGOV"], atol=1e-10))
    checks.append(_compare("SPY benchmark: return", daily[summary.get("benchmark") or "SPY"],
                           ref_daily["SPY"], atol=1e-10))
    ref_cal = pd.read_csv(ref_dir / "settlement_calendar.csv", index_col=0,
                          parse_dates=["trade_date", "settlement_date"])
    our_cal = pd.read_csv(art / "settlement_calendar.csv", index_col=0,
                          parse_dates=["trade_date", "settlement_date"])
    checks.append({"check": "settlement calendar",
                   "ok": bool(our_cal.index.equals(ref_cal.index)
                              and our_cal["settlement_date"].equals(ref_cal["settlement_date"]))})
    checks += compare_metrics(summary, pd.read_csv(ref_dir / "metrics.csv"))
    nav_ratio = ledger["nav"].iloc[-1] / capital
    report = {"run_dir": str(run_dir), "reference_dir": str(ref_dir),
              "ledger_rtol": LEDGER_RTOL, "metric_atol": METRIC_ATOL,
              "passed": all(c["ok"] for c in checks), "n_checks": len(checks),
              "n_failed": sum(not c["ok"] for c in checks),
              "final_nav_per_unit_capital": float(nav_ratio),
              "app_version": __import__("version").__version__, "checks": checks}
    out = run_dir / "parity"
    out.mkdir(exist_ok=True)
    (out / "parity.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--reference-dir", type=Path, required=True,
                        help="sgov_study.py --output directory (contains ledgers/, metrics.csv)")
    args = parser.parse_args()
    report = run(args.run_dir, args.reference_dir)
    worst = {}
    for c in report["checks"]:
        if not c["ok"]:
            print(f"FAIL  {c}")
        group = c["check"].split(":")[0].split("/")[0]
        worst[group] = max(worst.get(group, 0.0), c.get("max_abs_diff", 0.0))
    print(f"{report['n_checks'] - report['n_failed']}/{report['n_checks']} checks passed")
    for group, diff in worst.items():
        print(f"  {group:<55} max |diff| {diff:.3e}")
    print(f"Written: {args.run_dir / 'parity' / 'parity.json'}")
    sys.exit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
