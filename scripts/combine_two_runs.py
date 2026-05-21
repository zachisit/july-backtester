"""Combine equity curves from two separate run directories into an equal-
weight portfolio. Useful when the two strategies were tested on different
universes (cross-run combination).

Usage:
    python scripts/combine_two_runs.py <eq_csv_a> <eq_csv_b> <weight_a> <out_stem>

<weight_a> is the fraction for strategy A (0-1). Strategy B gets 1-<weight_a>.
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
    if len(sys.argv) < 5:
        print("Usage: python scripts/combine_two_runs.py <eq_a> <eq_b> <weight_a> <out_stem>")
        sys.exit(2)

    pa, pb, wa, out_stem = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
    wb = 1.0 - wa
    initial = 100_000.0

    eq_a = _load(Path(pa))
    eq_b = _load(Path(pb))
    common = eq_a.index.intersection(eq_b.index)
    if len(common) == 0:
        raise SystemExit("ERROR: no overlapping dates between the two curves")
    eq_a = eq_a.reindex(common)
    eq_b = eq_b.reindex(common)
    cap_a = initial * wa / eq_a.iloc[0]
    cap_b = initial * wb / eq_b.iloc[0]
    combined = eq_a * cap_a + eq_b * cap_b

    print(f"Period: {common.min().date()} -> {common.max().date()}")
    print(f"Weight A: {wa:.2f}  Weight B: {wb:.2f}")
    print()

    for eq, label in [(eq_a, "A " + Path(pa).stem), (eq_b, "B " + Path(pb).stem), (combined, "COMBINED")]:
        m = _metrics(eq, label)
        verdict, fails = _smooth_verdict(m)
        print(f"--- {label} ---")
        print(f"  P&L={m['total_return_pct']:>10.2f}%  CAGR={m['cagr_pct']:>5.2f}%  Sharpe={m['sharpe']:.2f}  Sharpe(5%RF)={m['sharpe_rf5']:.2f}")
        print(f"  MaxDD={m['max_dd_pct']:>5.2f}%  Calmar={m['calmar']:.2f}  Plateau={m['plateau_months']:.1f}m  PosMo={m['positive_months_pct']:.1f}%  WorstMo={m['worst_month_pct']:.2f}%  Upthrust={m['upthrust']}")
        print(f"  smooth_verdict={verdict}  fails={fails}")
        print()

    # Write combined CSV
    combined.to_frame("Equity").to_csv(f"{out_stem}_equity.csv")
    print(f"Wrote {out_stem}_equity.csv")

    # Chart: 3 lines (A, B, COMBINED) + SPY + drawdown banner
    spy_path = Path("/Users/zach/Desktop/github/july-backtester/parquet_data/data/SPY.parquet")
    spy = pd.read_parquet(spy_path)["Close"]
    spy.index = spy.index.tz_localize(None) if spy.index.tz else spy.index
    spy = spy.reindex(common, method="ffill").dropna()
    spy_norm = spy * (initial / spy.iloc[0])
    a_norm = eq_a * cap_a / wa
    b_norm = eq_b * cap_b / wb

    peak = combined.cummax()
    dd = (combined - peak) / peak * 100

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(14, 7), dpi=150,
        gridspec_kw={"height_ratios": [3, 1]}, sharex=True
    )

    ax1.plot(combined.index, combined.values, label=f"COMBINED ({wa:.0%}/{wb:.0%})", color="#1f77b4", linewidth=1.8)
    ax1.plot(a_norm.index, a_norm.values, label=f"A: {Path(pa).stem.split('_')[0]} alone", color="#ff7f0e", linewidth=1.0, alpha=0.7)
    ax1.plot(b_norm.index, b_norm.values, label=f"B: {Path(pb).stem.split('_')[0]} alone", color="#2ca02c", linewidth=1.0, alpha=0.7)
    ax1.plot(spy_norm.index, spy_norm.values, label="SPY B&H", color="gray", linestyle="--", linewidth=1.0)
    ax1.set_yscale("log")
    ax1.set_ylabel("Equity ($, log scale)")
    ax1.legend(loc="upper left")
    ax1.grid(True, which="both", alpha=0.3)
    ax1.set_title(f"50/50 Portfolio — {common.min().date()} → {common.max().date()}")

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
