"""scripts/composite_candidate_scorer.py

Composite portfolio scorer for the Opus agent's primary recommendation:
treat existing champions as a sleeve library and score *additions* by
orthogonality (regime + correlation), not standalone P&L.

Inputs
------
A consolidated ``ml_features.parquet`` (or any per-trade table with
``Strategy``, ``Portfolio``, ``Symbol``, ``EntryDate``, ``ExitDate``, ``Profit``,
``Shares``, ``EntryPrice``) plus a sleeve spec describing weights:

    sleeves = [
        ("EC-VIX-27: WR70 SMA120 ...", "NDX+Energy+Defense", 0.45),
        ("Williams R Weekly Trend (above-20) + SMA200", "Nasdaq 100", 0.45),
        ("Kalman β Gold Rotation", "Gold", 0.10),
    ]

For each sleeve, builds a daily equity curve normalized to start at 1.0
(cumulative Profit / initial_capital, forward-filled between exit dates).
Composite curve is the weighted-average of sleeve curves.

Reports
-------
- Per-sleeve: total return, MaxDD, max recovery (calendar days), Sharpe
- Composite: same metrics
- Pairwise daily-return Pearson correlations
- Regime overlap: % of days where each sleeve is in drawdown AND composite
  is in drawdown — proxy for how much the sleeve adds vs duplicates existing
  drawdown exposure (lower = more orthogonal coverage)
- Composite delta when last sleeve is treated as the candidate

Usage
-----
    rtk .venv/bin/python scripts/composite_candidate_scorer.py \\
        path/to/ml_features.parquet \\
        --sleeve "EC-VIX-27: WR70 SMA120 minimal-entry-25 vix-95th VIX-pct" \\
            "NDX+Energy+Defense" 0.45 \\
        --sleeve "Williams R Weekly Trend (above-20) + SMA200" \\
            "Nasdaq 100" 0.45 \\
        --sleeve "Kalman β Gold Rotation" "Gold" 0.10 \\
        [--initial-capital 100000] \\
        [--output-dir output/composite_baseline]

Notes
-----
- Single-strategy ml_features.parquet files (one trade log per file) also
  work: pass the path to the file and a sleeve spec with the matching
  Strategy+Portfolio pair.
- Equity curves are built from realized trade exits only. Open positions at
  end-of-backtest contribute their unrealized P&L on the ExitDate (which
  in the export is the last bar's date — already handled by the engine).
- Composite assumes rebalancing is *not* enforced — sleeve weights set the
  initial dollar allocation, and each sleeve compounds independently. This
  matches the typical "buy and never rebalance" overlay framing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_trades(path: str) -> pd.DataFrame:
    p = Path(path)
    if p.suffix == ".parquet":
        df = pd.read_parquet(p)
    else:
        df = pd.read_csv(p)
    df["EntryDate"] = pd.to_datetime(df["EntryDate"], errors="coerce", utc=True)
    df["ExitDate"]  = pd.to_datetime(df["ExitDate"],  errors="coerce", utc=True)
    df = df.dropna(subset=["EntryDate", "ExitDate"]).copy()
    return df


def _sleeve_equity_curve(trades: pd.DataFrame, initial_capital: float,
                         calendar: pd.DatetimeIndex) -> pd.Series:
    """Build a daily equity curve normalized to start at 1.0 from trade exits.

    Equity at date D = 1 + cumulative(Profit) / initial_capital for all
    trades with ExitDate <= D. Between exits the curve is flat. Open
    positions are not marked-to-market here — only realized profits move
    the curve. Use _load_mtm_equity_curve for daily MTM (preferred).
    """
    if trades.empty:
        return pd.Series(1.0, index=calendar, name="equity")

    grp = trades.groupby(trades["ExitDate"].dt.normalize())["Profit"].sum()
    grp.index = grp.index.tz_localize(None) if grp.index.tz is not None else grp.index
    daily_pnl = grp.reindex(calendar, fill_value=0.0)
    equity = 1.0 + daily_pnl.cumsum() / initial_capital
    equity.name = "equity"
    return equity


def _load_mtm_equity_curve(run_dir: Path, portfolio: str, strategy: str,
                           calendar: pd.DatetimeIndex) -> pd.Series:
    """Load the engine's daily mark-to-market equity curve from a run's
    analyzer_csvs/<Portfolio>/<Strategy>_equity.csv file.

    Engine sanitizes folder/file names with: spaces → _, ( ) and : stripped.
    Falls back to a flat 1.0 series if the file is missing or empty.
    """
    # Find the portfolio folder via case-insensitive substring matching
    analyzer_root = run_dir / "analyzer_csvs"
    if not analyzer_root.exists():
        return pd.Series(1.0, index=calendar, name="equity")

    target_port_sig = portfolio.replace(" ", "_")
    port_dir = None
    for child in analyzer_root.iterdir():
        if child.is_dir() and child.name == target_port_sig:
            port_dir = child; break
        if child.is_dir() and child.name == portfolio:
            port_dir = child; break
    if port_dir is None:
        return pd.Series(1.0, index=calendar, name="equity")

    # Find the strategy file via prefix matching
    target_strat_sig = (strategy
                        .replace(" ", "_")
                        .replace("(", "").replace(")", "")
                        .replace(":", "")
                        .replace("/", "_"))
    eq_path = None
    for child in port_dir.glob("*_equity.csv"):
        stem = child.stem[:-len("_equity")]
        if stem == target_strat_sig:
            eq_path = child; break
        if stem.startswith(target_strat_sig[:30]):
            eq_path = child  # don't break — exact match preferred
    if eq_path is None or not eq_path.exists():
        return pd.Series(1.0, index=calendar, name="equity")

    eq = pd.read_csv(eq_path, parse_dates=["Date"])
    eq["Date"] = eq["Date"].dt.tz_localize(None) if eq["Date"].dt.tz is not None else eq["Date"]
    eq = eq.set_index("Date")["Equity"]
    initial = eq.iloc[0] if eq.iloc[0] > 0 else 100_000.0
    eq_norm = (eq / initial).reindex(calendar, method="ffill").fillna(1.0)
    eq_norm.name = "equity"
    return eq_norm


def _composite_calendar(*sleeves: pd.DataFrame) -> pd.DatetimeIndex:
    starts, ends = [], []
    for s in sleeves:
        if not s.empty:
            starts.append(s["EntryDate"].min())
            ends.append(s["ExitDate"].max())
    if not starts:
        raise ValueError("no trades in any sleeve")
    start = min(starts).tz_localize(None) if min(starts).tz is not None else min(starts)
    end = max(ends).tz_localize(None) if max(ends).tz is not None else max(ends)
    return pd.bdate_range(start=start.normalize(), end=end.normalize())


def _metrics(equity: pd.Series) -> dict:
    if equity.empty or len(equity) < 2:
        return {"total_return_pct": 0.0, "max_dd_pct": 0.0,
                "max_recovery_days": 0, "sharpe": 0.0, "n_bars": int(len(equity))}
    daily_ret = equity.pct_change().fillna(0.0)
    cummax = equity.cummax()
    dd = (equity - cummax) / cummax  # negative numbers
    max_dd = float(dd.min())

    # max recovery in calendar days: longest underwater stretch
    underwater = (dd < 0)
    max_rcvry = 0
    cur_start = None
    last_peak_date = None
    for date, is_uw in underwater.items():
        if is_uw:
            if cur_start is None:
                cur_start = date
        else:
            if cur_start is not None:
                gap = (date - cur_start).days
                max_rcvry = max(max_rcvry, gap)
                cur_start = None
    if cur_start is not None:  # still underwater at end
        gap = (equity.index[-1] - cur_start).days
        max_rcvry = max(max_rcvry, gap)

    total_ret = float(equity.iloc[-1] - 1.0)
    sharpe = float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)) \
             if daily_ret.std() > 0 else 0.0
    return {
        "total_return_pct": total_ret * 100,
        "max_dd_pct": max_dd * 100,
        "max_recovery_days": int(max_rcvry),
        "sharpe": sharpe,
        "n_bars": int(len(equity)),
    }


def _drawdown_mask(equity: pd.Series) -> pd.Series:
    cummax = equity.cummax()
    dd = (equity - cummax) / cummax
    return dd < -1e-9


def _regime_overlap(s: pd.Series, base: pd.Series) -> float:
    """Fraction of `s`'s drawdown days that ALSO are drawdown days for `base`."""
    s_dd = _drawdown_mask(s)
    base_dd = _drawdown_mask(base.reindex(s.index, method="ffill"))
    if not s_dd.any():
        return 0.0
    return float((s_dd & base_dd).sum() / s_dd.sum())


def _correlations(equities: dict[str, pd.Series]) -> pd.DataFrame:
    rets = pd.DataFrame({k: v.pct_change() for k, v in equities.items()}).dropna()
    return rets.corr()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("parquet_path", nargs="?", help="path to ml_features.parquet (one or more)")
    p.add_argument("--from-files", nargs="+", default=None,
                   help="alternative: list of per-strategy parquet/csv files")
    p.add_argument("--sleeve", action="append", nargs=3,
                   metavar=("STRATEGY", "PORTFOLIO", "WEIGHT"),
                   help="repeat: strategy name, portfolio name, weight (decimal)")
    p.add_argument("--initial-capital", type=float, default=100000.0)
    p.add_argument("--output-dir", default="output/composite_score")
    p.add_argument("--candidate-index", type=int, default=None,
                   help="treat sleeve at this index (0-based) as the CANDIDATE — "
                        "report composite-with vs composite-without metrics")
    p.add_argument("--equity-from-runs", nargs="+", default=None,
                   help="list of output/runs/<run_id>/ directories to load daily MTM "
                        "equity curves from instead of trade-log cumulative profit (preferred — "
                        "captures intra-trade MTM and open-position drawdowns).")
    args = p.parse_args()

    if not args.sleeve:
        sys.exit("--sleeve required at least once")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sources: list[pd.DataFrame] = []
    if args.parquet_path:
        sources.append(_load_trades(args.parquet_path))
    if args.from_files:
        for f in args.from_files:
            sources.append(_load_trades(f))
    if not sources:
        sys.exit("provide parquet_path or --from-files")
    all_trades = pd.concat(sources, ignore_index=True)

    sleeve_specs: List[Tuple[str, str, float]] = [
        (s, p, float(w)) for s, p, w in args.sleeve
    ]
    if not np.isclose(sum(w for _, _, w in sleeve_specs), 1.0):
        print(f"[warn] sleeve weights sum to {sum(w for _,_,w in sleeve_specs):.4f}, not 1.0")

    sleeve_trade_dfs = []
    for strat, port, w in sleeve_specs:
        sel = all_trades[(all_trades["Strategy"] == strat) &
                         (all_trades["Portfolio"] == port)]
        if sel.empty:
            print(f"[warn] no trades found for ({strat!r}, {port!r})")
        sleeve_trade_dfs.append(sel)

    cal = _composite_calendar(*sleeve_trade_dfs)

    sleeve_equities = {}
    sleeve_metrics_out = []
    run_dirs = [Path(p) for p in (args.equity_from_runs or [])]
    for (strat, port, w), trades in zip(sleeve_specs, sleeve_trade_dfs):
        eq = None
        if run_dirs:
            for run_dir in run_dirs:
                cand_eq = _load_mtm_equity_curve(run_dir, port, strat, cal)
                # accept the first non-flat curve we find (MTM moves day-to-day)
                if cand_eq.std() > 1e-9:
                    eq = cand_eq
                    break
        if eq is None:
            eq = _sleeve_equity_curve(trades, args.initial_capital, cal)
            source = "TRADE-LOG"
        else:
            source = "MTM-CSV"
        label = f"{strat[:40]} | {port}"
        sleeve_equities[label] = eq
        m = _metrics(eq)
        m["sleeve"] = label
        m["weight"] = w
        m["n_trades"] = int(len(trades))
        m["source"] = source
        sleeve_metrics_out.append(m)
        print(f"\n=== sleeve: {label} (weight {w:.0%}, n_trades={len(trades)}, source={source}) ===")
        print(f"  total return:    {m['total_return_pct']:>10,.1f}%")
        print(f"  max drawdown:    {m['max_dd_pct']:>10,.2f}%")
        print(f"  max recovery:    {m['max_recovery_days']:>10} days")
        print(f"  sharpe:          {m['sharpe']:>10.2f}")

    # Composite (full): weighted sum of all sleeves
    weights = np.array([w for _, _, w in sleeve_specs])
    sleeve_matrix = np.column_stack([e.values for e in sleeve_equities.values()])
    composite_full = pd.Series(sleeve_matrix @ weights, index=cal, name="composite")
    comp_full_m = _metrics(composite_full)
    print(f"\n=== COMPOSITE (full, weights {weights.tolist()}) ===")
    print(f"  total return:    {comp_full_m['total_return_pct']:>10,.1f}%")
    print(f"  max drawdown:    {comp_full_m['max_dd_pct']:>10,.2f}%")
    print(f"  max recovery:    {comp_full_m['max_recovery_days']:>10} days")
    print(f"  sharpe:          {comp_full_m['sharpe']:>10.2f}")

    # Pairwise correlations of daily returns
    print(f"\n=== PAIRWISE DAILY-RETURN CORRELATIONS ===")
    corr = _correlations(sleeve_equities)
    print(corr.round(3).to_string())

    candidate_block = None
    if args.candidate_index is not None and 0 <= args.candidate_index < len(sleeve_specs):
        ci = args.candidate_index
        cand_label = list(sleeve_equities.keys())[ci]
        cand_w = sleeve_specs[ci][2]

        # Composite WITHOUT candidate, renormalized weights
        kept = [(i, w) for i, (_, _, w) in enumerate(sleeve_specs) if i != ci]
        kept_total = sum(w for _, w in kept)
        renorm_w = np.array([w / kept_total for _, w in kept])
        kept_eq = np.column_stack([list(sleeve_equities.values())[i].values for i, _ in kept])
        composite_no_cand = pd.Series(kept_eq @ renorm_w, index=cal, name="composite_no_cand")
        m_no_cand = _metrics(composite_no_cand)

        cand_eq = sleeve_equities[cand_label]
        overlap_vs_base = _regime_overlap(cand_eq, composite_no_cand)

        print(f"\n=== CANDIDATE: {cand_label} (weight {cand_w:.0%}) ===")
        print(f"  composite WITHOUT candidate:")
        print(f"    total return:  {m_no_cand['total_return_pct']:>10,.1f}%")
        print(f"    max drawdown:  {m_no_cand['max_dd_pct']:>10,.2f}%")
        print(f"    max recovery:  {m_no_cand['max_recovery_days']:>10} days")
        print(f"    sharpe:        {m_no_cand['sharpe']:>10.2f}")
        print(f"  composite WITH candidate (renorm gives back to {cand_w:.0%}):")
        print(f"    total return:  {comp_full_m['total_return_pct']:>10,.1f}%   "
              f"delta {comp_full_m['total_return_pct']-m_no_cand['total_return_pct']:+.1f}pp")
        print(f"    max drawdown:  {comp_full_m['max_dd_pct']:>10,.2f}%   "
              f"delta {comp_full_m['max_dd_pct']-m_no_cand['max_dd_pct']:+.2f}pp")
        print(f"    max recovery:  {comp_full_m['max_recovery_days']:>10} days  "
              f"delta {comp_full_m['max_recovery_days']-m_no_cand['max_recovery_days']:+d}d")
        print(f"    sharpe:        {comp_full_m['sharpe']:>10.2f}   "
              f"delta {comp_full_m['sharpe']-m_no_cand['sharpe']:+.2f}")
        print(f"  regime overlap (cand DD days that are also composite-base DD days): "
              f"{overlap_vs_base*100:.1f}%")

        candidate_block = {
            "candidate_label": cand_label,
            "candidate_weight": cand_w,
            "composite_without": m_no_cand,
            "composite_with":    comp_full_m,
            "delta_total_return_pp":   comp_full_m["total_return_pct"] - m_no_cand["total_return_pct"],
            "delta_max_dd_pp":         comp_full_m["max_dd_pct"] - m_no_cand["max_dd_pct"],
            "delta_max_recovery_days": comp_full_m["max_recovery_days"] - m_no_cand["max_recovery_days"],
            "delta_sharpe":            comp_full_m["sharpe"] - m_no_cand["sharpe"],
            "regime_overlap_pct":      overlap_vs_base * 100,
        }

    # write outputs
    out = {
        "sleeve_specs":      [{"strategy": s, "portfolio": p, "weight": w}
                              for s, p, w in sleeve_specs],
        "sleeve_metrics":    sleeve_metrics_out,
        "composite_full":    comp_full_m,
        "pairwise_corr":     corr.round(4).to_dict(),
        "candidate_block":   candidate_block,
    }
    with open(out_dir / "composite_score.json", "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    pd.DataFrame({k: v for k, v in sleeve_equities.items()}).assign(
        composite_full=composite_full
    ).to_csv(out_dir / "equity_curves.csv")
    print(f"\n[info] wrote {out_dir}/composite_score.json and equity_curves.csv")


if __name__ == "__main__":
    main()
