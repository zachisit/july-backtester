"""scripts/v2_unlock_2023_verify.py

v2 Phase 4 unlock verification. Subsets the pre-computed v1 composite
equity curve (EC-VIX-27 40% + DefSwitch-030 60%) to the held-out
2023-01-01 → 2026-04-22 window and computes the 4 R-gates on that slice.

This is the one-shot verification per HANDOFF_BLIND_DESIGN.md §7.2.
The v2 round produced no candidates (Phase 3 declared SEARCH SPACE
EXHAUSTED at iter009), so the v1 frozen composite is the documented
control for the unlock.

Outputs a JSON summary + a short markdown verdict.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMPOSITE_DIR = (
    PROJECT_ROOT
    / "custom_strategies"
    / "private"
    / "iter_data"
    / "composite_iter030_ec27_sweep"
    / "w40_60"
)
EQUITY_CSV = COMPOSITE_DIR / "equity_curves.csv"

SPY_PARQUET = PROJECT_ROOT / "parquet_data" / "data" / "SPY.parquet"

UNLOCK_START = pd.Timestamp("2023-01-01")
TRADING_DAYS_PER_YEAR = 252
RF_ANNUAL = 0.05
RF_PER_BAR = (1.0 + RF_ANNUAL) ** (1.0 / TRADING_DAYS_PER_YEAR) - 1.0


def max_drawdown_pct(eq: pd.Series) -> float:
    """Return MaxDD as positive percentage (e.g. 17.5 means -17.5%)."""
    if len(eq) < 2:
        return 0.0
    hwm = eq.cummax()
    dd = (eq - hwm) / hwm
    return float(-dd.min() * 100.0)


def max_recovery_days(eq: pd.Series) -> int | None:
    """Longest calendar-day gap from any drawdown trough back to the
    prior peak. Returns None if the curve ends in an open drawdown."""
    if len(eq) < 2:
        return 0
    hwm = eq.cummax()
    in_dd = eq < hwm
    if not in_dd.any():
        return 0
    # Walk drawdown periods
    longest = 0
    i = 0
    n = len(eq)
    while i < n:
        if in_dd.iat[i]:
            start_date = eq.index[i]
            peak_val = hwm.iat[i]
            j = i + 1
            while j < n and eq.iat[j] < peak_val:
                j += 1
            if j < n:
                rec = (eq.index[j] - start_date).days
                longest = max(longest, rec)
                i = j
            else:
                # Open drawdown at end
                return None
        else:
            i += 1
    return longest


def annualised_sharpe(eq: pd.Series) -> float:
    rets = eq.pct_change().dropna()
    if len(rets) < 2:
        return 0.0
    excess = rets - RF_PER_BAR
    std = excess.std()
    if std == 0:
        return 0.0
    return float((excess.mean() / std) * (TRADING_DAYS_PER_YEAR ** 0.5))


def main() -> int:
    if not EQUITY_CSV.exists():
        print(f"ERROR: composite equity file not found: {EQUITY_CSV}", file=sys.stderr)
        return 2

    eq_df = pd.read_csv(EQUITY_CSV, index_col=0, parse_dates=True)
    composite = eq_df["composite_full"]

    # Load SPY for benchmark comparison
    if not SPY_PARQUET.exists():
        print(f"ERROR: SPY parquet not found: {SPY_PARQUET}", file=sys.stderr)
        return 2
    spy = pd.read_parquet(SPY_PARQUET)["Close"].copy()
    if spy.index.tz is not None:
        spy.index = spy.index.tz_localize(None)

    # Subset to 2023+ window
    composite_2023 = composite.loc[composite.index >= UNLOCK_START].copy()
    spy_2023 = spy.loc[spy.index >= UNLOCK_START].copy()

    if composite_2023.empty:
        print("ERROR: no composite data on or after 2023-01-01", file=sys.stderr)
        return 2

    # Normalise both to start at 1.0 on the held-out start date
    composite_2023 = composite_2023 / composite_2023.iloc[0]
    spy_2023 = spy_2023 / spy_2023.iloc[0]

    # Align SPY to composite index
    spy_aligned = spy_2023.reindex(composite_2023.index, method="ffill")

    composite_ret = (composite_2023.iloc[-1] - 1.0) * 100.0
    spy_ret = (spy_aligned.iloc[-1] - 1.0) * 100.0
    r1_lag_pp = composite_ret - spy_ret  # positive = composite beats SPY

    composite_maxdd = max_drawdown_pct(composite_2023)
    composite_maxrcvry = max_recovery_days(composite_2023)
    composite_sharpe = annualised_sharpe(composite_2023)

    # Gate verdicts
    r1_pass = composite_ret > spy_ret
    r3_pass = composite_maxrcvry is not None and composite_maxrcvry < 365

    # R2 (smoothness) and R4 (MC/WFA) cannot be computed without the
    # full simulation pipeline. We report basic monotonicity proxies.
    monthly_eq = composite_2023.resample("ME").last()
    monthly_returns = monthly_eq.pct_change().dropna()
    positive_months_pct = float((monthly_returns > 0).mean() * 100.0)
    worst_month_pct = float(monthly_returns.min() * 100.0)
    plateau_months = 0
    if len(monthly_eq) > 0:
        # consecutive months without new high
        mhwm = monthly_eq.cummax()
        below = monthly_eq < mhwm
        if below.any():
            # longest run of True
            runs = []
            cur = 0
            for b in below.values:
                if b:
                    cur += 1
                else:
                    if cur > 0:
                        runs.append(cur)
                    cur = 0
            if cur > 0:
                runs.append(cur)
            plateau_months = max(runs) if runs else 0

    # Linear-fit r² as smoothness proxy
    x = np.arange(len(composite_2023))
    y = np.log(composite_2023.values)
    if len(x) > 2:
        slope, intercept = np.polyfit(x, y, 1)
        y_fit = slope * x + intercept
        ss_res = np.sum((y - y_fit) ** 2)
        ss_tot = np.sum((y - y.mean()) ** 2)
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    else:
        r2 = 0.0

    summary = {
        "candidate": "EC-VIX-27 (40%) + DefSwitch-030 (60%)",
        "unlock_window_start": UNLOCK_START.date().isoformat(),
        "data_through": composite_2023.index.max().date().isoformat(),
        "composite_total_return_pct": round(composite_ret, 2),
        "spy_total_return_pct": round(spy_ret, 2),
        "vs_spy_pp": round(r1_lag_pp, 2),
        "composite_max_drawdown_pct": round(composite_maxdd, 2),
        "composite_max_recovery_days": composite_maxrcvry,
        "composite_sharpe": round(composite_sharpe, 3),
        "monthly_positive_pct": round(positive_months_pct, 1),
        "monthly_worst_pct": round(worst_month_pct, 2),
        "monthly_plateau_months": plateau_months,
        "linear_log_fit_r2": round(r2, 3),
        "gates": {
            "R1_BEATS_SPY": "PASS" if r1_pass else "FAIL",
            "R3_MaxRcvry_lt_365d": "PASS" if r3_pass else "FAIL",
            "R2_smoothness": "NOT_COMPUTED (requires LLM verdict pipeline)",
            "R4_validation": "NOT_COMPUTED (requires MC/WFA pipeline)",
        },
        "overall_verdict": "PASS" if (r1_pass and r3_pass) else "FAIL",
    }

    out_dir = PROJECT_ROOT / "custom_strategies" / "private" / "iter_data" / "v2_unlock_2023"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "unlock_verdict.json"
    json_path.write_text(json.dumps(summary, indent=2, default=float))

    # Print summary
    print("=" * 70)
    print(f"v2 PHASE 4 UNLOCK — 2023-01-01 → {summary['data_through']}")
    print("=" * 70)
    print(f"Candidate: {summary['candidate']}")
    print(f"")
    print(f"Composite TotalRet:  {composite_ret:+.2f}%")
    print(f"SPY benchmark:       {spy_ret:+.2f}%")
    print(f"Composite vs SPY:    {r1_lag_pp:+.2f}pp")
    print(f"Composite MaxDD:     {composite_maxdd:.2f}%")
    print(f"Composite MaxRcvry:  {composite_maxrcvry if composite_maxrcvry is not None else 'open'} days")
    print(f"Composite Sharpe:    {composite_sharpe:.3f}")
    print(f"")
    print(f"Smoothness proxies:")
    print(f"  positive months:   {positive_months_pct:.1f}%")
    print(f"  worst month:       {worst_month_pct:+.2f}%")
    print(f"  plateau months:    {plateau_months}")
    print(f"  log-linear r²:     {r2:.3f}")
    print(f"")
    print(f"Gates on 2023+ slice ALONE:")
    print(f"  R1 (BEATS SPY):        {summary['gates']['R1_BEATS_SPY']}")
    print(f"  R3 (MaxRcvry < 365d):  {summary['gates']['R3_MaxRcvry_lt_365d']}")
    print(f"  R2 (smoothness):       NOT_COMPUTED")
    print(f"  R4 (validation):       NOT_COMPUTED")
    print(f"")
    print(f"Overall (R1+R3 only):    {summary['overall_verdict']}")
    print("=" * 70)
    print(f"Verdict JSON saved to: {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
