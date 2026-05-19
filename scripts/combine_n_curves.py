"""Combine N equity curves into a weighted portfolio with smooth_verdict.

Usage:
    python scripts/combine_n_curves.py <out_stem> <weight_a:eq_csv_a> <weight_b:eq_csv_b> ...

Example:
    python scripts/combine_n_curves.py output/runs/3sleeve_test \
        0.45:run_r21/.../GR-A-09_..._equity.csv \
        0.45:run_ec27/.../EC-VIX-27_..._equity.csv \
        0.10:run_def/.../DEF-01_..._equity.csv

Weights must sum to ~1.0. Produces:
  <out_stem>_equity.csv     — combined equity curve
  <out_stem>.pdf / .png     — chart with each sleeve overlaid + drawdown
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


def _load(path):
    df = pd.read_csv(path, parse_dates=["Date"]).set_index("Date").sort_index()
    df.index = df.index.tz_localize(None) if df.index.tz else df.index
    return df["Equity"]


def _metrics(equity, label):
    daily_ret = equity.pct_change().fillna(0)
    monthly = equity.resample("ME").last().pct_change().dropna()
    total_return_pct = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    daily_mean, daily_std = daily_ret.mean(), daily_ret.std()
    sharpe = (daily_mean / daily_std) * np.sqrt(252) if daily_std > 0 else 0
    rf_daily = 0.05 / 252
    excess = daily_ret - rf_daily
    sharpe_rf = (excess.mean() / excess.std()) * np.sqrt(252) if excess.std() > 0 else 0
    peak = equity.cummax()
    dd = (equity - peak) / peak
    max_dd = abs(dd.min()) * 100
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else 0
    calmar = (cagr * 100) / max_dd if max_dd > 0 else 0
    new_high_dates = equity[equity == equity.cummax()].index
    if len(new_high_dates) > 1:
        gaps = (new_high_dates[1:] - new_high_dates[:-1]).days
        max_plateau_months = float(gaps.max()) / 30.44
    else:
        max_plateau_months = (equity.index[-1] - equity.index[0]).days / 30.44
    pos_months = (monthly > 0).sum() / len(monthly) * 100 if len(monthly) else 0
    worst_month = monthly.min() * 100 if len(monthly) else 0
    upthrust = (monthly > 0.15).sum()
    return dict(
        label=label, total_return_pct=total_return_pct, cagr_pct=cagr * 100,
        sharpe=sharpe, sharpe_rf5=sharpe_rf, max_dd_pct=max_dd,
        calmar=calmar, plateau_months=max_plateau_months,
        positive_months_pct=pos_months, worst_month_pct=worst_month,
        upthrust=int(upthrust),
    )


def _smooth_verdict(m):
    fails = []
    if m["positive_months_pct"] < 60:
        fails.append(f"pos_months {m['positive_months_pct']:.1f}% < 60%")
    if m["plateau_months"] >= 12:
        fails.append(f"plateau {m['plateau_months']:.1f}m >= 12m")
    if m["upthrust"] > 2:
        fails.append(f"upthrust {m['upthrust']} > 2")
    if m["worst_month_pct"] < -10:
        fails.append(f"worst_month {m['worst_month_pct']:.2f}% < -10%")
    if len(fails) == 0:
        return "SMOOTH", fails
    if len(fails) == 1:
        return "ACCEPTABLE", fails
    return "ROUGH", fails


def main():
    if len(sys.argv) < 4:
        print("Usage: python scripts/combine_n_curves.py <out_stem> <weight:eq_csv> <weight:eq_csv> ...")
        sys.exit(2)
    out_stem = sys.argv[1]
    pairs = sys.argv[2:]
    initial = 100_000.0

    weights = []
    paths = []
    for p in pairs:
        w_str, path = p.split(":", 1)
        weights.append(float(w_str))
        paths.append(Path(path))
    weights = np.array(weights)
    if not (0.98 < weights.sum() < 1.02):
        print(f"WARNING: weights sum to {weights.sum():.3f}, expected ~1.0")

    equities = [_load(p) for p in paths]
    common = equities[0].index
    for eq in equities[1:]:
        common = common.intersection(eq.index)
    if len(common) == 0:
        raise SystemExit("ERROR: no overlapping dates across all sleeves")

    print(f"Period: {common.min().date()} -> {common.max().date()}  ({len(common)} bars)")
    print()

    combined = pd.Series(0.0, index=common)
    norm_curves = []
    for w, eq, path in zip(weights, equities, paths):
        sub = eq.reindex(common)
        start_val = sub.iloc[0]
        scale = (initial * w) / start_val
        scaled = sub * scale
        combined = combined.add(scaled, fill_value=0)
        norm_curves.append((path.stem, sub * (initial / start_val), w))

    # Print per-sleeve metrics
    for stem, norm_curve, w in norm_curves:
        m = _metrics(norm_curve, f"{stem[:60]} (w={w:.2f})")
        v, fails = _smooth_verdict(m)
        print(f"--- {m['label']} ---")
        print(f"  P&L={m['total_return_pct']:>10.2f}%  Sharpe={m['sharpe']:.2f}  Sharpe(5%RF)={m['sharpe_rf5']:.2f}  MaxDD={m['max_dd_pct']:>5.2f}%  Calmar={m['calmar']:.2f}")
        print(f"  Plateau={m['plateau_months']:.1f}m  WorstMo={m['worst_month_pct']:.2f}%  Upthrust={m['upthrust']}  PosMo={m['positive_months_pct']:.1f}%")
        print(f"  smooth_verdict={v}  fails={fails}")
        print()

    # Combined metrics
    cm = _metrics(combined, f"COMBINED ({len(weights)}-sleeve)")
    cv, cf = _smooth_verdict(cm)
    print(f"--- {cm['label']} ---")
    print(f"  P&L={cm['total_return_pct']:>10.2f}%  Sharpe={cm['sharpe']:.2f}  Sharpe(5%RF)={cm['sharpe_rf5']:.2f}  MaxDD={cm['max_dd_pct']:>5.2f}%  Calmar={cm['calmar']:.2f}")
    print(f"  Plateau={cm['plateau_months']:.1f}m  WorstMo={cm['worst_month_pct']:.2f}%  Upthrust={cm['upthrust']}  PosMo={cm['positive_months_pct']:.1f}%")
    print(f"  smooth_verdict={cv}  fails={cf}")
    print()

    # Write combined equity
    combined.to_frame("Equity").to_csv(f"{out_stem}_equity.csv")
    print(f"Wrote {out_stem}_equity.csv")

    # Chart
    spy_path = Path("/Users/zach/Desktop/github/july-backtester/parquet_data/data/SPY.parquet")
    spy = pd.read_parquet(spy_path)["Close"]
    spy.index = spy.index.tz_localize(None) if spy.index.tz else spy.index
    spy = spy.reindex(common, method="ffill").dropna()
    spy_norm = spy * (initial / spy.iloc[0])

    peak = combined.cummax()
    dd = (combined - peak) / peak * 100

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(14, 7), dpi=150,
        gridspec_kw={"height_ratios": [3, 1]}, sharex=True
    )

    ax1.plot(combined.index, combined.values,
             label=f"COMBINED ({len(weights)}-sleeve)", color="#1f77b4", linewidth=2.0)
    colors = ["#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
    for i, (stem, norm_curve, w) in enumerate(norm_curves):
        scaled_for_chart = norm_curve * w  # display in combined frame
        ax1.plot(scaled_for_chart.index, scaled_for_chart.values,
                 label=f"{stem.split('_')[0]} (w={w:.0%})",
                 color=colors[i % len(colors)],
                 linewidth=1.0, alpha=0.7)
    ax1.plot(spy_norm.index, spy_norm.values, label="SPY B&H",
             color="gray", linestyle="--", linewidth=1.0)
    ax1.set_yscale("log")
    ax1.set_ylabel("Equity ($, log scale)")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(True, which="both", alpha=0.3)
    ax1.set_title(f"{len(weights)}-Sleeve Portfolio — {common.min().date()} → {common.max().date()}  ({cv})")

    ax2.fill_between(dd.index, dd.values, 0, color="red", alpha=0.3)
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Date")
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_locator(mdates.YearLocator(2))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)

    plt.tight_layout()
    plt.savefig(f"{out_stem}.pdf", bbox_inches="tight")
    plt.savefig(f"{out_stem}.png", bbox_inches="tight")
    plt.close()
    print(f"Wrote {out_stem}.pdf and .png")


if __name__ == "__main__":
    main()
