"""
simulate_circuit_breaker.py — analytical pass of the self-aware circuit breaker

Two optional post-processing rules applied to an existing realized trade log:
  1. Self-aware position-size scaler (rolling-N win-rate gate with hysteresis)
  2. 60-day hold-period time stop (truncates long holds, pro-rates P&L linearly
     over the shortened hold — approximation of "exit at day N at current price")

Usage:
    python scripts/simulate_circuit_breaker.py <run_dir>
        [window=20] [halt_pct=0.40] [resume_pct=0.55] [time_stop_days=0]

    time_stop_days=0 disables the time stop (backward-compatible Round 1 behavior).

Read-only aside from its own output under custom_strategies/private/research_results/.
"""

import os
import sys
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages


INITIAL_EQUITY = 100_000.0


def find_trade_log(run_dir):
    raw_root = os.path.join(run_dir, "raw_trades")
    for portfolio_dir in sorted(os.listdir(raw_root)):
        pd_path = os.path.join(raw_root, portfolio_dir)
        if not os.path.isdir(pd_path):
            continue
        for fname in sorted(os.listdir(pd_path)):
            if fname.endswith(".csv"):
                return os.path.join(pd_path, fname), portfolio_dir, fname
    raise FileNotFoundError(f"No trade log in {raw_root}")


def apply_circuit_breaker(trades, window, halt_pct, resume_pct, size_discount=0.25):
    """Walk trades by EntryDate. For each, compute rolling win rate of the N trades
    that CLOSED strictly before the current EntryDate. Apply SIZE DISCOUNT to the
    P&L of trades taken when win rate < halt_pct. Restore full size when win rate
    returns above resume_pct. Hysteresis prevents oscillation.

    Crucially: EVERY trade still happens (so the rolling window keeps sampling
    genuine conditions and the gate can self-correct). Only P&L is scaled down
    during low-win-rate regimes — simulating a position-size reduction rule.

    Returns (adjusted_df, gate_state_df).
    """
    trades = trades.sort_values("EntryDate").reset_index(drop=True).copy()
    in_low_regime = False
    adjusted_rows = []
    gate_states = []

    closed_pool = trades.sort_values("ExitDate").reset_index(drop=True)
    for _, row in trades.iterrows():
        prior = closed_pool[closed_pool["ExitDate"] < row["EntryDate"]]
        if len(prior) >= window:
            recent = prior.tail(window)
            wr = (recent["Profit"] > 0).mean()
            if (not in_low_regime) and wr < halt_pct:
                in_low_regime = True
            elif in_low_regime and wr > resume_pct:
                in_low_regime = False
            rolling_wr = wr
        else:
            rolling_wr = None  # warm-up

        scale = size_discount if in_low_regime else 1.0
        adjusted = row.copy()
        # Scale Profit in dollars. The rolling window uses the ORIGINAL Profit
        # (via closed_pool reference) — so its SIGN doesn't change even at reduced
        # size, which keeps the win-rate feedback loop intact.
        adjusted["Profit"] = row["Profit"] * scale
        adjusted["SizeScale"] = scale
        adjusted_rows.append(adjusted)

        gate_states.append({
            "EntryDate":     row["EntryDate"],
            "rolling_wr":    rolling_wr,
            "size_scale":    scale,
            "in_low_regime": in_low_regime,
        })

    adjusted_df = pd.DataFrame(adjusted_rows)
    gates = pd.DataFrame(gate_states)
    return adjusted_df, gates


def equity_curve(closed_df, start_date, end_date):
    if closed_df.empty:
        idx = pd.date_range(start_date, end_date, freq="B")
        return pd.Series(INITIAL_EQUITY, index=idx)
    daily_pnl = closed_df.groupby("ExitDate")["Profit"].sum().sort_index()
    eq = INITIAL_EQUITY + daily_pnl.cumsum()
    idx = pd.date_range(start_date, end_date, freq="B")
    return eq.reindex(idx).ffill().fillna(INITIAL_EQUITY)


def drawdown_metrics(eq):
    peak = eq.cummax()
    dd = (eq - peak) / peak * 100
    # Max recovery: longest time under water
    max_rec_days = 0
    in_dd = False
    dd_start = None
    for dt, v in dd.items():
        if v < 0 and not in_dd:
            in_dd = True
            dd_start = dt
        elif v >= 0 and in_dd:
            in_dd = False
            max_rec_days = max(max_rec_days, (dt - dd_start).days)
    if in_dd:
        max_rec_days = max(max_rec_days, (eq.index[-1] - dd_start).days)
    return {
        "final_equity":     eq.iloc[-1],
        "max_dd_pct":       dd.min(),
        "max_recovery_d":   max_rec_days,
        "dd_series":        dd,
    }


def distribution_metrics(closed_df):
    if closed_df.empty or closed_df["Profit"].sum() <= 0:
        return {"top1_pct": None, "top5_pct": None, "n_trades": len(closed_df)}
    total = closed_df["Profit"].sum()
    return {
        "top1_pct": closed_df["Profit"].max() / total * 100,
        "top5_pct": closed_df["Profit"].nlargest(5).sum() / total * 100,
        "n_trades": len(closed_df),
    }


def plot_comparison(baseline_eq, filtered_eq, baseline_dd, filtered_dd,
                    baseline_metrics, filtered_metrics, gates_df, output_pdf):
    os.makedirs(os.path.dirname(output_pdf), exist_ok=True)
    with PdfPages(output_pdf) as pdf:
        # Page 1: Equity curves
        fig, axes = plt.subplots(2, 1, figsize=(12, 9), gridspec_kw={"height_ratios": [2, 1]})
        ax1 = axes[0]
        ax1.plot(baseline_eq.index, baseline_eq / 1000, label="Baseline (EC-R51 Option-3)", color="red", alpha=0.7, linewidth=1.4)
        ax1.plot(filtered_eq.index, filtered_eq / 1000, label="With Circuit Breaker", color="green", alpha=0.85, linewidth=1.6)
        ax1.set_ylabel("Equity ($k)")
        ax1.set_title("Williams R Weekly + SMA200 on Nasdaq 100 (2.5%) — Circuit Breaker Analytical Simulation", fontsize=11)
        ax1.legend(loc="upper left", fontsize=10)
        ax1.grid(True, alpha=0.3)

        # Highlight low-regime (size-reduced) windows
        gate_closed_dates = gates_df[gates_df["in_low_regime"]]["EntryDate"]
        if not gate_closed_dates.empty:
            # Bin into contiguous windows
            gc = gate_closed_dates.sort_values().reset_index(drop=True)
            start = gc.iloc[0]
            prev = gc.iloc[0]
            for dt in gc.iloc[1:]:
                if (dt - prev).days > 30:
                    ax1.axvspan(start, prev, alpha=0.08, color="grey")
                    start = dt
                prev = dt
            ax1.axvspan(start, prev, alpha=0.08, color="grey", label="Size reduced")

        ax2 = axes[1]
        ax2.fill_between(baseline_dd.index, baseline_dd, 0, color="red", alpha=0.4, label="Baseline DD")
        ax2.fill_between(filtered_dd.index, filtered_dd, 0, color="green", alpha=0.5, label="Circuit Breaker DD")
        ax2.set_ylabel("Drawdown (%)")
        ax2.axhline(-12, color="black", linestyle="--", alpha=0.3)
        ax2.axhline(-25, color="black", linestyle=":", alpha=0.2)
        ax2.legend(loc="lower left", fontsize=9)
        ax2.grid(True, alpha=0.3)

        plt.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)

        # Page 2: Metrics comparison table
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.axis("off")
        rows = [
            ["Metric",                  "Baseline",                                                  "Circuit Breaker"],
            ["Final equity ($)",        f"${baseline_metrics['final_equity']:>12,.0f}",             f"${filtered_metrics['final_equity']:>12,.0f}"],
            ["P&L % (realized)",        f"{(baseline_metrics['final_equity']/INITIAL_EQUITY - 1)*100:>11.2f}%", f"{(filtered_metrics['final_equity']/INITIAL_EQUITY - 1)*100:>11.2f}%"],
            ["Max Drawdown",            f"{baseline_metrics['max_dd_pct']:>11.2f}%",                f"{filtered_metrics['max_dd_pct']:>11.2f}%"],
            ["Max Recovery (days)",     f"{baseline_metrics['max_recovery_d']:>12d}",               f"{filtered_metrics['max_recovery_d']:>12d}"],
            ["Number of trades",        f"{baseline_metrics['n_trades']:>12d}",                     f"{filtered_metrics['n_trades']:>12d}"],
            ["Top-1 trade / P&L",       f"{baseline_metrics['top1_pct']:>11.2f}%" if baseline_metrics['top1_pct'] else "N/A",
                                        f"{filtered_metrics['top1_pct']:>11.2f}%" if filtered_metrics['top1_pct'] else "N/A"],
            ["Top-5 trades / P&L",      f"{baseline_metrics['top5_pct']:>11.2f}%" if baseline_metrics['top5_pct'] else "N/A",
                                        f"{filtered_metrics['top5_pct']:>11.2f}%" if filtered_metrics['top5_pct'] else "N/A"],
        ]
        tbl = ax.table(cellText=rows, loc="center", cellLoc="left", colWidths=[0.35, 0.35, 0.3])
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(11)
        tbl.scale(1, 1.6)
        for i, cell in enumerate(tbl.get_celld()):
            row, col = cell
            if row == 0:
                tbl[cell].set_facecolor("#d9d9d9")
                tbl[cell].set_text_props(weight="bold")
        ax.set_title("Circuit Breaker vs Baseline — Realized Metrics", fontsize=12, pad=20)
        pdf.savefig(fig)
        plt.close(fig)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    run_dir        = sys.argv[1].rstrip("/").rstrip("\\")
    window         = int(sys.argv[2])    if len(sys.argv) > 2 else 20
    halt_pct       = float(sys.argv[3])  if len(sys.argv) > 3 else 0.40
    resume_pct     = float(sys.argv[4])  if len(sys.argv) > 4 else 0.55
    time_stop_days = int(sys.argv[5])    if len(sys.argv) > 5 else 0

    trade_log_path, portfolio, _ = find_trade_log(run_dir)
    print(f"Reading trade log: {trade_log_path}")
    df = pd.read_csv(trade_log_path)
    df["EntryDate"] = pd.to_datetime(df["EntryDate"])
    df["ExitDate"]  = pd.to_datetime(df["ExitDate"])
    closed = df[df["ExitReason"] != "End of Backtest"].copy()

    print(f"  Total trades:    {len(df)}")
    print(f"  Realized trades: {len(closed)}")
    print(f"  Circuit breaker: window={window}, halt_pct={halt_pct}, resume_pct={resume_pct}")
    print(f"  Time stop:       {time_stop_days} days ({'ENABLED' if time_stop_days > 0 else 'disabled'})")

    # Apply time stop BEFORE circuit breaker. ASYMMETRIC rule (cut losers short,
    # let winners run): for LOSING trades with hold > time_stop_days, truncate ExitDate
    # to EntryDate + time_stop_days and pro-rate the loss linearly. Winners are untouched.
    # Rationale: if a Williams R bounce hasn't played out in 60 days, the thesis is dead;
    # if it IS working (Profit > 0 at exit), let the trend run to its natural exit signal.
    if time_stop_days > 0:
        hold_days = (closed["ExitDate"] - closed["EntryDate"]).dt.days.clip(lower=1)
        overlong_losers = (hold_days > time_stop_days) & (closed["Profit"] < 0)
        n_truncated = int(overlong_losers.sum())
        if n_truncated:
            scale = (time_stop_days / hold_days).where(overlong_losers, 1.0)
            closed = closed.copy()
            closed["Profit"] = closed["Profit"] * scale
            new_exit = closed["EntryDate"] + pd.Timedelta(days=time_stop_days)
            closed["ExitDate"] = closed["ExitDate"].where(~overlong_losers, new_exit)
            print(f"  Losers truncated by time stop: {n_truncated} ({n_truncated/len(closed)*100:.1f}%)")
            print(f"  Winners preserved in full:     {int(~overlong_losers.sum() if False else (closed['Profit'] >= 0).sum())}")
        else:
            print(f"  Losers truncated by time stop: 0")

    kept, gates = apply_circuit_breaker(closed, window, halt_pct, resume_pct, size_discount=0.25)
    reduced_count = gates["in_low_regime"].sum()
    print(f"  Trades at reduced size: {reduced_count} ({reduced_count/len(closed)*100:.1f}%)")
    print(f"  Size discount during low-regime: 25% of baseline (75% reduction)")
    print()

    # Full timeline
    start = closed["ExitDate"].min()
    end   = closed["ExitDate"].max()

    base_eq      = equity_curve(closed, start, end)
    filt_eq      = equity_curve(kept, start, end)
    base_metrics = {**drawdown_metrics(base_eq), **distribution_metrics(closed)}
    filt_metrics = {**drawdown_metrics(filt_eq), **distribution_metrics(kept)}
    base_dd = base_metrics.pop("dd_series")
    filt_dd = filt_metrics.pop("dd_series")

    # Print summary
    spy_bh_pct = 729.0  # for 2004-2025-06 period from EC-R51 Option 3 summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"{'Metric':<26}{'Baseline':>22}{'Circuit Breaker':>22}")
    print(f"{'Final equity':<26}${base_metrics['final_equity']:>20,.0f}${filt_metrics['final_equity']:>20,.0f}")
    print(f"{'P&L % (realized)':<26}{(base_metrics['final_equity']/INITIAL_EQUITY - 1)*100:>22.2f}%{(filt_metrics['final_equity']/INITIAL_EQUITY - 1)*100:>21.2f}%")
    print(f"{'vs SPY (+'+str(spy_bh_pct)+'%)':<26}{(base_metrics['final_equity']/INITIAL_EQUITY - 1)*100 - spy_bh_pct:>21.1f}pp{(filt_metrics['final_equity']/INITIAL_EQUITY - 1)*100 - spy_bh_pct:>21.1f}pp")
    print(f"{'Max Drawdown':<26}{base_metrics['max_dd_pct']:>22.2f}%{filt_metrics['max_dd_pct']:>21.2f}%")
    print(f"{'Max Recovery (days)':<26}{base_metrics['max_recovery_d']:>22d}{filt_metrics['max_recovery_d']:>22d}")
    print(f"{'# realized trades':<26}{base_metrics['n_trades']:>22d}{filt_metrics['n_trades']:>22d}")
    print(f"{'Top-1 / P&L':<26}{base_metrics['top1_pct'] or 0:>22.2f}%{filt_metrics['top1_pct'] or 0:>21.2f}%")
    print(f"{'Top-5 / P&L':<26}{base_metrics['top5_pct'] or 0:>22.2f}%{filt_metrics['top5_pct'] or 0:>21.2f}%")
    print()

    # Output
    out_dir = os.path.join("custom_strategies", "private", "research_results", "pdfs", "ec_daily")
    os.makedirs(out_dir, exist_ok=True)
    suffix = f"_ts{time_stop_days}" if time_stop_days > 0 else ""
    output_pdf = os.path.join(out_dir, f"EC-R53_Circuit_Breaker_Analytical_Comparison{suffix}.pdf")
    plot_comparison(base_eq, filt_eq, base_dd, filt_dd, base_metrics, filt_metrics, gates, output_pdf)
    print(f"Comparison PDF: {output_pdf}")

    # Also save filtered trade log
    kept_csv = os.path.join(out_dir, f"EC-R53_Circuit_Breaker_filtered_trades{suffix}.csv")
    kept.to_csv(kept_csv, index=False)
    print(f"Filtered trade log: {kept_csv}")


if __name__ == "__main__":
    main()
