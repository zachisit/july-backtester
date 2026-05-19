"""Combine equity curves from multiple strategy runs into a single
equal-weighted portfolio and compute diversified metrics.

Usage:
    python scripts/combine_strategies.py <run_dir> <strategy_substr>...

Reads <run_dir>/analyzer_csvs/<Portfolio>/<StrategyName>_equity.csv for
each strategy whose name contains one of the supplied substrings. Builds
an equal-weight combined portfolio (each strategy gets 1/N of initial
capital). Computes return, MaxDD, Sharpe, Calmar, monthly stats, and
longest plateau.

Compares against the best single strategy (highest standalone return).

Not gated/scored — produces a side-by-side metric comparison only.
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _find_equity_csvs(run_dir: Path, name_substrs: list[str]) -> dict[str, Path]:
    """For each substring, find one matching <*>_equity.csv file under analyzer_csvs/."""
    analyzer_root = run_dir / "analyzer_csvs"
    if not analyzer_root.is_dir():
        raise SystemExit(f"ERROR: {analyzer_root} not found")

    out: dict[str, Path] = {}
    for sub in name_substrs:
        match = None
        for portfolio_dir in analyzer_root.iterdir():
            if not portfolio_dir.is_dir():
                continue
            for f in portfolio_dir.glob("*_equity.csv"):
                if sub in f.name:
                    match = f
                    break
            if match:
                break
        if not match:
            raise SystemExit(f"ERROR: no equity CSV found matching '{sub}'")
        out[sub] = match
    return out


def _load_equity(path: Path) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["Date"])
    df = df.set_index("Date").sort_index()
    return df["Equity"]


def _build_combined(equities: dict[str, pd.Series], initial_capital_per: float) -> pd.Series:
    """Equal-weight portfolio. Each strategy starts at initial_capital_per
    and evolves on its own equity curve. Total portfolio equity = sum."""
    # Find common index — inner join of all strategies' dates
    common_idx = None
    for s in equities.values():
        common_idx = s.index if common_idx is None else common_idx.intersection(s.index)
    if common_idx is None or len(common_idx) == 0:
        raise SystemExit("ERROR: strategies have no common dates")

    # For each strategy, normalize its equity so it starts at initial_capital_per,
    # then sum across strategies for the combined portfolio
    n = len(equities)
    combined = pd.Series(0.0, index=common_idx)
    for s in equities.values():
        sub = s.reindex(common_idx)
        # Normalize: starting value = initial_capital_per
        start_val = sub.iloc[0]
        scaled = sub * (initial_capital_per / start_val)
        combined = combined.add(scaled, fill_value=0)
    return combined


def _equity_metrics(equity: pd.Series, label: str) -> dict:
    daily_ret = equity.pct_change().fillna(0)
    monthly = equity.resample("ME").last().pct_change().dropna()

    total_return_pct = (equity.iloc[-1] / equity.iloc[0] - 1) * 100

    # Annualized stats
    daily_mean = daily_ret.mean()
    daily_std = daily_ret.std()
    sharpe = (daily_mean / daily_std) * np.sqrt(252) if daily_std > 0 else 0.0

    # MaxDD
    peak = equity.cummax()
    dd = (equity - peak) / peak
    max_dd = abs(dd.min()) * 100

    # CAGR
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else 0
    calmar = (cagr * 100) / max_dd if max_dd > 0 else 0

    # Plateau (longest stretch without a new high)
    new_high_dates = equity[equity == equity.cummax()].index
    if len(new_high_dates) > 1:
        gaps = (new_high_dates[1:] - new_high_dates[:-1]).days
        max_plateau_days = int(gaps.max())
    else:
        max_plateau_days = int((equity.index[-1] - equity.index[0]).days)
    max_plateau_months = max_plateau_days / 30.44

    pos_months = (monthly > 0).sum() / len(monthly) * 100 if len(monthly) else 0
    worst_month = monthly.min() * 100 if len(monthly) else 0

    return {
        "label":             label,
        "total_return_pct":  total_return_pct,
        "cagr_pct":          cagr * 100,
        "sharpe":            sharpe,
        "max_dd_pct":        max_dd,
        "calmar":            calmar,
        "plateau_months":    max_plateau_months,
        "positive_months_pct": pos_months,
        "worst_month_pct":   worst_month,
    }


def _fmt_metric_row(m: dict) -> str:
    return (
        f"  {m['label']:50s}  "
        f"P&L={m['total_return_pct']:>8.1f}%  "
        f"Sharpe={m['sharpe']:>5.2f}  "
        f"MaxDD={m['max_dd_pct']:>5.1f}%  "
        f"Calmar={m['calmar']:>4.2f}  "
        f"Plateau={m['plateau_months']:>4.1f}m  "
        f"PosMo={m['positive_months_pct']:>4.1f}%  "
        f"WorstMo={m['worst_month_pct']:>5.1f}%"
    )


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/combine_strategies.py <run_dir> <substr1> <substr2> ...")
        sys.exit(2)

    run_dir = Path(sys.argv[1]).resolve()
    substrs = sys.argv[2:]

    paths = _find_equity_csvs(run_dir, substrs)
    equities = {k: _load_equity(p) for k, p in paths.items()}

    print(f"\nLoaded {len(equities)} equity curves from {run_dir.name}:")
    for k, p in paths.items():
        print(f"  '{k}': {p.name} ({len(equities[k])} bars)")

    # Single-strategy metrics
    print("\n--- Individual strategies (alloc=0.09 baseline) ---")
    indiv_metrics = []
    for k, eq in equities.items():
        m = _equity_metrics(eq, k)
        indiv_metrics.append(m)
        print(_fmt_metric_row(m))

    # Build combined: equal-weight, 100k/N starting each
    initial = 100000.0
    per = initial / len(equities)
    combined = _build_combined(equities, initial_capital_per=per)
    combined_m = _equity_metrics(combined, f"COMBINED ({len(equities)}-strat equal weight)")

    print("\n--- Combined portfolio (equal weight) ---")
    print(_fmt_metric_row(combined_m))

    # Comparison vs best single strategy
    best_indiv = max(indiv_metrics, key=lambda x: x["total_return_pct"])
    print(f"\n--- Combined vs best individual ({best_indiv['label']}) ---")
    keys = [
        ("total_return_pct",  "Total Return", "%", True),
        ("cagr_pct",          "CAGR",         "%", True),
        ("sharpe",            "Sharpe",       "",  True),
        ("max_dd_pct",        "MaxDD",        "%", False),
        ("calmar",            "Calmar",       "",  True),
        ("plateau_months",    "Plateau",      "m", False),
        ("positive_months_pct", "Pos Months", "%", True),
        ("worst_month_pct",   "Worst Mo",     "%", True),
    ]
    for k, label, unit, higher_better in keys:
        c = combined_m[k]
        b = best_indiv[k]
        diff = c - b
        sign = "+" if diff >= 0 else ""
        improved = (diff > 0) if higher_better else (diff < 0)
        marker = "✓" if improved else ("=" if abs(diff) < 1e-9 else "✗")
        print(f"  {label:14s} combined={c:>8.2f}{unit:1s}  best_indiv={b:>8.2f}{unit:1s}  Δ={sign}{diff:>+7.2f}  {marker}")

    print()


if __name__ == "__main__":
    main()
