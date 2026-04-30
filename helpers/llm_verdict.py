import json
import os
from datetime import datetime, timezone

from config import CONFIG


def generate_llm_verdict(all_results, benchmark_returns, run_id=None, output_dir=None, benchmark_dfs=None):
    """Write llm_verdict.json so LLMs and interns can determine whether each
    strategy beats its benchmark without reading PDF equity-curve images.

    Includes a monthly normalized equity curve and annual returns per strategy
    so a language model can "see" the curve shape in data form.

    Parameters
    ----------
    benchmark_dfs : dict, optional
        {label: DataFrame} with a 'Close' column — same labels as benchmark_returns.
        When provided, benchmark equity curves are embedded alongside each strategy curve.
    """
    if output_dir is None:
        if run_id:
            output_dir = os.path.join("output", "runs", run_id)
        else:
            output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    primary_label = next(iter(benchmark_returns), None)
    primary_key = f"beats_{primary_label.lower().replace(' ', '_')}" if primary_label else "beats_benchmark"
    label_order = list(benchmark_returns.keys())

    strategy_entries = []
    for result in all_results:
        if not result.get("Trades", 0):
            continue

        pnl_frac = result.get("pnl_percent", 0.0) or 0.0

        benchmarks_detail = {}
        for label, bh_frac in benchmark_returns.items():
            result_key = f'vs_{label.lower().replace(" ", "_")}_benchmark'
            margin_frac = result.get(result_key, pnl_frac - bh_frac)
            margin_pp = round(margin_frac * 100, 4)
            beats = margin_pp > 0
            direction = f"+{margin_pp:.2f}pp" if beats else f"{margin_pp:.2f}pp"
            benchmarks_detail[label] = {
                "bh_return_pct": round(bh_frac * 100, 4),
                "beats": beats,
                "outperformance_pp": margin_pp,
                "verdict": f"BEATS {label} by {direction}" if beats else f"LAGS {label} by {direction}",
            }

        primary_detail = benchmarks_detail.get(primary_label, {}) if primary_label else {}
        beats_primary = primary_detail.get("beats", None)
        primary_verdict = primary_detail.get("verdict", "No benchmark configured")

        timeline = result.get("portfolio_timeline")
        curve, annual = _build_equity_curve(timeline, benchmark_dfs, label_order)
        smoothness = _compute_smoothness(timeline)

        entry = {
            "strategy": result.get("Strategy", ""),
            "portfolio": result.get("Portfolio", ""),
            primary_key: beats_primary,
            "verdict": primary_verdict,
            "strategy_return_pct": round(pnl_frac * 100, 4),
            "benchmarks": benchmarks_detail,
            "sharpe_ratio": _fmt(result.get("sharpe_ratio")),
            "calmar_ratio": _fmt(result.get("calmar_ratio")),
            "max_drawdown_pct": _fmt_pct(result.get("max_drawdown")),
            "win_rate_pct": _fmt_pct(result.get("win_rate")),
            "trades": result.get("Trades"),
            "mc_score": result.get("mc_score"),
            "mc_verdict": result.get("mc_verdict"),
            "wfa_verdict": result.get("wfa_verdict"),
            "wfa_rolling_verdict": result.get("wfa_rolling_verdict"),
            "equity_curve": curve,
            "annual_returns": annual,
            "curve_smoothness": smoothness,
        }
        strategy_entries.append(entry)

    strategy_entries.sort(
        key=lambda e: e.get("benchmarks", {}).get(primary_label, {}).get("outperformance_pp", -9999)
        if primary_label else e.get("strategy_return_pct", -9999),
        reverse=True,
    )
    for i, e in enumerate(strategy_entries, 1):
        e["rank"] = i

    beats_count = sum(1 for e in strategy_entries if e.get(primary_key) is True)
    total = len(strategy_entries)

    payload = {
        "run_id": run_id or "",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {
            "start": CONFIG.get("start_date", ""),
            "end": CONFIG.get("end_date", "") or "today",
        },
        "benchmarks": {k: round(v * 100, 4) for k, v in benchmark_returns.items()},
        "summary": {
            "total_strategies_with_trades": total,
            f"{primary_key}_count": beats_count,
            f"{primary_key}_pct": round(beats_count / total * 100, 1) if total else 0.0,
        },
        "strategies": strategy_entries,
    }

    path = os.path.join(output_dir, "llm_verdict.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)

    label_str = primary_label or "benchmark"
    print(f"  LLM verdict written to '{path}' ({beats_count}/{total} beat {label_str})")
    return path


def _build_equity_curve(timeline, benchmark_dfs, label_order):
    """Return (curve_dict, annual_returns_list) from a daily equity Series.

    curve_dict keys: 'frequency', 'normalized_start', 'dates', 'strategy',
    plus one key per benchmark label.  All equity series are normalized so the
    first month = 100, making them directly comparable by inspection.

    annual_returns_list: [{year, strategy_pct, <label>_pct, ...}, ...]
    """
    import pandas as pd

    if timeline is None or not hasattr(timeline, 'resample') or len(timeline) < 10:
        return {}, []

    try:
        monthly = timeline.resample('ME').last().dropna()
    except Exception:
        try:
            monthly = timeline.resample('M').last().dropna()  # pandas < 2.2 fallback
        except Exception:
            return {}, []

    if len(monthly) < 2:
        return {}, []

    base = monthly.iloc[0]
    if base <= 0:
        return {}, []

    dates = [d.strftime("%Y-%m-%d") for d in monthly.index]
    curve = {
        "frequency": "monthly",
        "normalized_start": 100,
        "dates": dates,
        "strategy": (monthly / base * 100).round(2).tolist(),
    }

    for label in label_order:
        bm_df = (benchmark_dfs or {}).get(label)
        if bm_df is None or bm_df.empty or "Close" not in bm_df.columns:
            continue
        try:
            bm_in_range = bm_df["Close"].loc[
                (bm_df.index >= timeline.index[0]) & (bm_df.index <= timeline.index[-1])
            ]
            if len(bm_in_range) < 2:
                continue
            try:
                bm_monthly = bm_in_range.resample('ME').last().dropna()
            except Exception:
                bm_monthly = bm_in_range.resample('M').last().dropna()
            # Align to the strategy's month-end dates
            bm_aligned = bm_monthly.reindex(monthly.index).ffill().bfill()
            bm_base = bm_aligned.iloc[0]
            if bm_base <= 0:
                continue
            curve[label] = (bm_aligned / bm_base * 100).round(2).tolist()
        except Exception:
            pass

    # Annual returns
    annual = []
    try:
        years = sorted(set(timeline.index.year))
        for year in years:
            yr_data = timeline[timeline.index.year == year]
            if len(yr_data) < 2:
                continue
            strat_ret = round((yr_data.iloc[-1] / yr_data.iloc[0] - 1) * 100, 2)
            entry = {"year": int(year), "strategy_pct": strat_ret}
            for label in label_order:
                bm_df = (benchmark_dfs or {}).get(label)
                if bm_df is None or "Close" not in bm_df.columns:
                    continue
                try:
                    bm_yr = bm_df["Close"][bm_df.index.year == year]
                    if len(bm_yr) >= 2:
                        entry[f"{label}_pct"] = round((bm_yr.iloc[-1] / bm_yr.iloc[0] - 1) * 100, 2)
                except Exception:
                    pass
            annual.append(entry)
    except Exception:
        pass

    return curve, annual


def _compute_smoothness(timeline):
    """
    Compute curve smoothness metrics from a daily (or monthly) equity Series.
    Resamples to monthly internally. Returns None when < 12 months of data.

    Thresholds:
        SMOOTH     — 0 failures
        ACCEPTABLE — 1 failure
        ROUGH      — 2+ failures

    Failure conditions:
        R² < 0.90 | positive_months < 60% | longest_flat >= 12 |
        upthrust_count > 2 | max_monthly_dd < -10%
    """
    import numpy as np
    import pandas as pd

    if timeline is None or not hasattr(timeline, "resample") or len(timeline) < 2:
        return None

    try:
        monthly = timeline.resample("ME").last().dropna()
    except Exception:
        try:
            monthly = timeline.resample("M").last().dropna()
        except Exception:
            return None

    if len(monthly) < 12:
        return None

    vals = monthly.values.astype(float)
    n = len(vals)

    # R² of log(equity) vs OLS linear trend
    log_eq = np.log(vals)
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    y_mean = log_eq.mean()
    ss_tot = float(((log_eq - y_mean) ** 2).sum())
    if ss_tot == 0:
        r2 = 1.0
    else:
        slope = float(((x - x_mean) * (log_eq - y_mean)).sum() / ((x - x_mean) ** 2).sum())
        y_pred = y_mean + slope * (x - x_mean)
        ss_res = float(((log_eq - y_pred) ** 2).sum())
        r2 = max(0.0, min(1.0, 1.0 - ss_res / ss_tot))
    r2 = round(r2, 4)

    monthly_rets = monthly.pct_change().dropna()
    std_val = float(monthly_rets.std()) if len(monthly_rets) > 1 else 0.0
    std_pct = round(std_val * 100, 4)
    pos_pct = round(float((monthly_rets > 0).mean() * 100), 4) if len(monthly_rets) > 0 else 0.0
    max_dd_pct = round(float(monthly_rets.min() * 100), 4) if len(monthly_rets) > 0 else 0.0

    # Longest streak of months NOT making a strictly new equity high
    hwm = -float("inf")
    longest_flat = 0
    current_flat = 0
    for v in vals:
        if v > hwm:
            hwm = v
            current_flat = 0
        else:
            current_flat += 1
            longest_flat = max(longest_flat, current_flat)

    # Upthrust: months more than 3σ above the mean return (Z-score > 3).
    # Guard against near-zero std (stable growth) triggering false positives.
    if std_val > 1e-6:
        mean_ret = float(monthly_rets.mean())
        upthrust_count = int((monthly_rets > mean_ret + 3 * std_val).sum())
    else:
        upthrust_count = 0

    failures = []
    if r2 < 0.90:
        failures.append(f"r2: {r2:.2f} below 0.90 threshold")
    if pos_pct < 60.0:
        failures.append(f"positive_months: {pos_pct:.1f}% below 60% threshold")
    if longest_flat >= 12:
        failures.append(f"plateau: {longest_flat} consecutive months without new high")
    if upthrust_count > 2:
        failures.append(f"upthrust: {upthrust_count} outlier months detected")
    if max_dd_pct < -10.0:
        failures.append(f"drawdown: {max_dd_pct:.1f}% worst month exceeds -10% threshold")

    n_fail = len(failures)
    verdict = "SMOOTH" if n_fail == 0 else ("ACCEPTABLE" if n_fail == 1 else "ROUGH")

    return {
        "smoothness_r2": r2,
        "monthly_return_std_pct": std_pct,
        "positive_months_pct": pos_pct,
        "max_monthly_drawdown_pct": max_dd_pct,
        "longest_flat_streak_months": longest_flat,
        "upthrust_count": upthrust_count,
        "smooth_verdict": verdict,
        "smooth_notes": failures,
    }


def _fmt(val, decimals=4):
    if val is None:
        return None
    try:
        return round(float(val), decimals)
    except (TypeError, ValueError):
        return val


def _fmt_pct(val):
    """Convert a fractional value (0.18) to a rounded percentage float (18.0)."""
    if val is None:
        return None
    try:
        return round(float(val) * 100, 4)
    except (TypeError, ValueError):
        return val
