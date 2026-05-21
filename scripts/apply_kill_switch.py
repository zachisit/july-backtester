"""Apply the regime-aware kill-switch overlay to an existing equity curve.

Reads an equity CSV (Date, Equity), pulls VIX from parquet, computes
trigger codes per bar, and writes:
  <out_stem>_overlay_equity.csv    — modified equity curve
  <out_stem>_overlay.pdf / .png    — chart of original vs overlay vs SPY
  <out_stem>_overlay_summary.json  — trigger counts and metric comparison

Usage:
    python scripts/apply_kill_switch.py <equity_csv> <out_stem> \
        [--dd 0.30] [--vix 60.0] [--plateau-months 18] \
        [--dd-factor 0.5] [--vix-factor 0.0]
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers.kill_switch import (
    KS_NONE, KS_DD, KS_VIX, KS_BOTH,
    compute_drawdown,
    detect_triggers,
    plateau_alerts,
    apply_overlay,
    summarize_triggers,
)


def _load_equity(path: Path) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["Date"]).set_index("Date").sort_index()
    df.index = df.index.tz_localize(None) if df.index.tz else df.index
    return df["Equity"]


def _load_vix() -> pd.Series:
    p = Path("/Users/zach/Desktop/github/july-backtester/parquet_data/data/$VIX.parquet")
    df = pd.read_parquet(p)
    df.index = df.index.tz_localize(None) if df.index.tz else df.index
    return df["Close"]


def _metrics(equity: pd.Series, label: str) -> dict:
    daily_ret = equity.pct_change().fillna(0)
    monthly = equity.resample("ME").last().pct_change().dropna()
    total_return_pct = (equity.iloc[-1] / equity.iloc[0] - 1) * 100
    daily_std = daily_ret.std()
    sharpe = (daily_ret.mean() / daily_std) * np.sqrt(252) if daily_std > 0 else 0
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
    if m["positive_months_pct"] < 60: fails.append(f"pos_months {m['positive_months_pct']:.1f}% < 60%")
    if m["plateau_months"] >= 12:     fails.append(f"plateau {m['plateau_months']:.1f}m >= 12m")
    if m["upthrust"] > 2:              fails.append(f"upthrust {m['upthrust']} > 2")
    if m["worst_month_pct"] < -10:     fails.append(f"worst_month {m['worst_month_pct']:.2f}% < -10%")
    if not fails: return "SMOOTH", fails
    if len(fails) == 1: return "ACCEPTABLE", fails
    return "ROUGH", fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("equity_csv")
    ap.add_argument("out_stem")
    ap.add_argument("--dd", type=float, default=0.30, help="Drawdown threshold (0.30 = 30%%)")
    ap.add_argument("--vix", type=float, default=60.0, help="VIX panic threshold")
    ap.add_argument("--plateau-months", type=int, default=18)
    ap.add_argument("--dd-factor", type=float, default=0.5, help="Exposure factor during DD trigger")
    ap.add_argument("--vix-factor", type=float, default=0.0, help="Exposure factor during VIX panic")
    args = ap.parse_args()

    eq = _load_equity(Path(args.equity_csv))
    vix = _load_vix()

    triggers = detect_triggers(eq, vix, dd_threshold=args.dd, vix_panic_threshold=args.vix)
    plateau = plateau_alerts(eq, plateau_threshold_months=args.plateau_months)
    overlay = apply_overlay(eq, triggers, dd_reduce_factor=args.dd_factor, vix_cash_factor=args.vix_factor)

    summary = summarize_triggers(triggers, plateau)

    # Metrics for both
    m_orig = _metrics(eq, "ORIGINAL")
    v_orig, f_orig = _smooth_verdict(m_orig)
    m_over = _metrics(overlay, "OVERLAY")
    v_over, f_over = _smooth_verdict(m_over)

    print(f"Period: {eq.index.min().date()} → {eq.index.max().date()}")
    print(f"\nTrigger params: dd={args.dd:.0%}, vix>{args.vix}, plateau>{args.plateau_months}m")
    print(f"  DD bars     : {summary['dd_bars']} ({summary['dd_pct']:.1f}%)")
    print(f"  VIX bars    : {summary['vix_bars']} ({summary['vix_pct']:.1f}%)")
    print(f"  BOTH bars   : {summary['both_bars']}")
    print(f"  Plateau bars: {summary['plateau_bars']} ({summary['plateau_pct']:.1f}%)")

    for m, v, fails in [(m_orig, v_orig, f_orig), (m_over, v_over, f_over)]:
        print(f"\n--- {m['label']} ---")
        print(f"  P&L={m['total_return_pct']:>10.2f}%  Sharpe={m['sharpe']:.2f}  Sharpe(5%RF)={m['sharpe_rf5']:.2f}")
        print(f"  MaxDD={m['max_dd_pct']:>5.2f}%  Calmar={m['calmar']:.2f}  Plateau={m['plateau_months']:.1f}m")
        print(f"  WorstMo={m['worst_month_pct']:.2f}%  Upthrust={m['upthrust']}  PosMo={m['positive_months_pct']:.1f}%")
        print(f"  smooth_verdict={v}  fails={fails}")

    # Write outputs
    overlay.to_frame("Equity").to_csv(f"{args.out_stem}_overlay_equity.csv")
    print(f"\nWrote {args.out_stem}_overlay_equity.csv")

    out_json = {
        "params": {"dd": args.dd, "vix_panic": args.vix, "plateau_months": args.plateau_months,
                   "dd_factor": args.dd_factor, "vix_factor": args.vix_factor},
        "trigger_summary": summary,
        "original": {**m_orig, "smooth_verdict": v_orig, "smooth_fails": f_orig},
        "overlay":  {**m_over, "smooth_verdict": v_over, "smooth_fails": f_over},
    }
    with open(f"{args.out_stem}_overlay_summary.json", "w") as f:
        json.dump(out_json, f, indent=2, default=str)
    print(f"Wrote {args.out_stem}_overlay_summary.json")

    # Chart: original vs overlay vs SPY
    spy_path = Path("/Users/zach/Desktop/github/july-backtester/parquet_data/data/SPY.parquet")
    spy = pd.read_parquet(spy_path)["Close"]
    spy.index = spy.index.tz_localize(None) if spy.index.tz else spy.index
    spy = spy.reindex(eq.index, method="ffill").dropna()
    spy_norm = spy * (eq.iloc[0] / spy.iloc[0])
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 7), dpi=150,
                                    gridspec_kw={"height_ratios": [3, 1]}, sharex=True)
    ax1.plot(eq.index, eq.values, label=f"Original ({v_orig})", color="#1f77b4", linewidth=1.5)
    ax1.plot(overlay.index, overlay.values, label=f"Kill-switch overlay ({v_over})", color="#d62728", linewidth=1.5)
    ax1.plot(spy_norm.index, spy_norm.values, label="SPY B&H", color="gray", linestyle="--", linewidth=1.0)
    # Shade kill-switch active regions
    dd_active = triggers.isin([KS_DD, KS_BOTH])
    vix_active = triggers.isin([KS_VIX, KS_BOTH])
    for active, color, label in [(dd_active, "#ff7f0e", "DD trigger"), (vix_active, "#9467bd", "VIX trigger")]:
        if active.sum() > 0:
            # Highlight bars where trigger was on
            ax1.fill_between(eq.index, eq.min(), eq.max(),
                             where=active.values, alpha=0.05, color=color)
    ax1.set_yscale("log")
    ax1.set_ylabel("Equity ($, log scale)")
    ax1.legend(loc="upper left")
    ax1.grid(True, which="both", alpha=0.3)
    ax1.set_title(f"Kill-switch overlay on {Path(args.equity_csv).stem[:50]}")

    dd = compute_drawdown(eq) * 100
    ax2.fill_between(dd.index, -dd.values, 0, color="red", alpha=0.3)
    ax2.axhline(-args.dd * 100, color="orange", linestyle="--", linewidth=1, label=f"DD trigger ({-args.dd*100:.0f}%)")
    ax2.set_ylabel("Drawdown (%)")
    ax2.set_xlabel("Date")
    ax2.legend(loc="lower left", fontsize=8)
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_locator(mdates.YearLocator(2))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45)
    plt.tight_layout()
    plt.savefig(f"{args.out_stem}_overlay.pdf", bbox_inches="tight")
    plt.savefig(f"{args.out_stem}_overlay.png", bbox_inches="tight")
    plt.close()
    print(f"Wrote {args.out_stem}_overlay.pdf and .png")


if __name__ == "__main__":
    main()
