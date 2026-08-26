#!/usr/bin/env python3
"""Tearsheet for a completed run: equity, drawdown, annual bars, distribution.

Reads the DAILY equity curve from analyzer_csvs (2,765 rows on the Donchian
headline run), not the monthly one in llm_verdict.json -- calendar-year figures
derived from monthly points don't line up with year boundaries, which is what
made an earlier reconciliation attempt unreliable (see #299).

Usage:
  python scripts/make_tearsheet.py output/runs/<run_id> [out_dir]
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


def load_equity(run: Path) -> pd.Series:
    hits = sorted(glob.glob(str(run / "analyzer_csvs" / "**" / "*_equity.csv"), recursive=True))
    if not hits:
        sys.exit(f"no *_equity.csv under {run}")
    df = pd.read_csv(hits[0])
    idx = pd.to_datetime(df.iloc[:, 0], utc=True, errors="coerce").dt.tz_localize(None)
    s = pd.Series(pd.to_numeric(df.iloc[:, 1], errors="coerce").to_numpy(), index=idx)
    return s.dropna().sort_index()


def stats(eq: pd.Series, rf: float, bars_per_year: int = 252) -> dict:
    """Sharpe here mirrors helpers/simulations.py:25-27 exactly -- EXCESS over a
    per-bar risk-free rate from the run's own config_snapshot. Computing it
    against zero instead gives 0.68 where the engine reports 0.28 on the same
    curve, so a tearsheet that assumes rf=0 silently contradicts its own PR."""
    r = eq.pct_change().dropna()
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    dd = eq / eq.cummax() - 1.0
    rf_per_bar = (1 + rf) ** (1 / bars_per_year) - 1
    ex = r - rf_per_bar
    sd_ex = ex.std(ddof=1)
    sd = r.std(ddof=1)
    rf_bar = (1 + rf) ** (1 / 252) - 1          # matches helpers/simulations.py
    ex = r - rf_bar
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else np.nan
    return {
        "start": eq.index[0].date(), "end": eq.index[-1].date(), "bars": len(eq),
        "risk_free_rate": rf,
        "total_pct": (eq.iloc[-1] / eq.iloc[0] - 1) * 100,
        "cagr_pct": cagr * 100,
        "sharpe": float(ex.mean() / sd_ex * np.sqrt(bars_per_year)) if sd_ex > 0 else np.nan,
        "sharpe_rf0": float(r.mean() / sd * np.sqrt(bars_per_year)) if sd > 0 else np.nan,
        "vol_pct": float(sd * np.sqrt(252) * 100),
        "max_dd_pct": float(dd.min() * 100),
        "calmar": float(cagr / abs(dd.min())) if dd.min() < 0 else np.nan,
        "worst_day_pct": float(r.min() * 100), "best_day_pct": float(r.max() * 100),
        "pct_up_days": float((r > 0).mean() * 100),
        "skew": float(r.skew()), "kurt": float(r.kurt()),
    }


def annual(eq: pd.Series) -> pd.DataFrame:
    """Calendar-year returns from the DAILY curve, using the last bar of each
    year as the boundary. Compounding these reproduces the total exactly --
    stated because the engine's own annual_returns block does not (#299)."""
    ye = eq.groupby(eq.index.year).last()
    prev = pd.concat([pd.Series([eq.iloc[0]], index=[ye.index[0] - 1]), ye]).sort_index()
    out = (ye / prev.shift(1).reindex(ye.index) - 1) * 100
    return pd.DataFrame({"year": out.index, "return_pct": out.to_numpy()}).dropna()


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("usage: make_tearsheet.py output/runs/<run_id> [out_dir]")
    run = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else run
    out.mkdir(parents=True, exist_ok=True)

    snap = run / "config_snapshot.json"
    rf = 0.05
    if snap.exists():
        try:
            rf = float(json.loads(snap.read_text()).get("risk_free_rate", 0.05))
        except Exception:
            pass
    eq = load_equity(run)
    st = stats(eq, rf)
    ann = annual(eq)

    print(f"\n{'='*62}\n  TEARSHEET -- {run.name}\n{'='*62}")
    for k, v in st.items():
        print(f"  {k:<16}: {v:.2f}" if isinstance(v, float) else f"  {k:<16}: {v}")
    comp = float(np.prod(1 + ann["return_pct"].to_numpy() / 100) - 1) * 100
    print(f"\n  Sharpe {st['sharpe']:.2f} is EXCESS over rf={rf:.1%} (engine convention,")
    print(f"  helpers/simulations.py:25-27). Against rf=0 the same curve gives "
          f"{st['sharpe_rf0']:.2f}.")
    print(f"\n  annual returns compound to {comp:.2f}% vs total {st['total_pct']:.2f}% "
          f"(diff {comp - st['total_pct']:+.4f}pp)")
    print("\n  " + "  ".join(f"{int(y)}:{v:+.1f}%" for y, v in
                             zip(ann['year'], ann['return_pct'])))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(3, 1, figsize=(11, 12),
                           gridspec_kw={"height_ratios": [2.2, 1, 1]})
    ax[0].plot(eq.index, eq.to_numpy(), lw=1.3, color="black")
    ax[0].set_yscale("log")
    ax[0].set_title(f"{run.name} — equity (log)   "
                    f"total {st['total_pct']:.1f}%  CAGR {st['cagr_pct']:.1f}%  "
                    f"Sharpe {st['sharpe']:.2f} (excess, rf={rf:.0%})  "
                    f"MaxDD {st['max_dd_pct']:.1f}%")
    ax[0].grid(alpha=0.25)
    dd = (eq / eq.cummax() - 1) * 100
    ax[1].fill_between(dd.index, dd.to_numpy(), 0, color="0.3")
    ax[1].set_title("drawdown (%)")
    ax[1].grid(alpha=0.25)
    ax[2].bar(ann["year"].astype(int), ann["return_pct"],
              color=["0.25" if v >= 0 else "0.6" for v in ann["return_pct"]])
    ax[2].axhline(0, color="black", lw=0.8)
    ax[2].set_title("calendar-year returns (%) — from the daily curve")
    ax[2].grid(alpha=0.25, axis="y")
    fig.tight_layout()
    png = out / f"tearsheet_{run.name}.png"
    fig.savefig(png, dpi=125)
    plt.close(fig)

    (out / f"tearsheet_{run.name}.json").write_text(
        json.dumps({"stats": {k: (str(v) if not isinstance(v, float) else round(v, 4))
                              for k, v in st.items()},
                    "annual_pct": {int(y): round(v, 4) for y, v in
                                   zip(ann["year"], ann["return_pct"])},
                    "annual_compounded_pct": round(comp, 4)}, indent=2))
    print(f"\n  wrote {png.name} and tearsheet_{run.name}.json\n")


if __name__ == "__main__":
    main()
