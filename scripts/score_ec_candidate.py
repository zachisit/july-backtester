"""
score_ec_candidate.py  —  Score any run against the four EC hard requirements.

The EC (Equity Curve) research has FOUR non-negotiable requirements. A strategy is
a champion only if it satisfies ALL FOUR SIMULTANEOUSLY:

  1. BEATS SPY      — strategy P&L% > SPY B&H P&L% over the same backtest period.
  2. SMOOTH CURVE   — no single trade dominates (top-5 trades < 15% of total P&L) AND
                      rolling 126d equity range doesn't show multi-month cliff-downs.
  3. NO LONG DD     — max drawdown recovery duration < 365 calendar days.
  4. PASSES GATES   — WFA Pass, Rolling WFA 3/3, MC Score >= 4, OOS P&L > 0.

Usage:
    python scripts/score_ec_candidate.py <run_dir>
    python scripts/score_ec_candidate.py output/runs/ec-r46-two-layer-gate_2026-04-23_18-15-20

Exits 0 if ALL strategies in the run pass all four requirements. Exits 1 otherwise.
Prints a clear pass/fail table per strategy per portfolio.

Read-only — makes no changes to any file.
"""

import os
import sys
import pandas as pd

# Put project root on sys.path so config imports work from scripts/.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _pct_to_float(s):
    """Convert '355.86%' or '-5.05%' (or already-numeric) to float fraction (355.86 -> 355.86)."""
    if isinstance(s, (int, float)):
        return float(s)
    return float(str(s).strip().rstrip('%'))


def _days_between(d1_str, d2_str):
    try:
        return (pd.Timestamp(d2_str) - pd.Timestamp(d1_str)).days
    except Exception:
        return None


def check_beats_spy(pnl_pct, vs_spy_pct):
    """Requirement 1: strategy P&L > SPY B&H P&L."""
    # vs_spy_pct is strategy_pnl - spy_bh_pnl. Positive = beats SPY.
    if vs_spy_pct is None:
        return None, "missing vs_spy"
    passes = vs_spy_pct > 0
    return passes, f"strategy {pnl_pct:+.2f}% vs SPY baseline ({'+' if vs_spy_pct >= 0 else ''}{vs_spy_pct:.2f}pp)"


def check_smooth_curve(trade_log_path, total_pnl_dollars):
    """Requirement 2: top-5 trades < 15% of total P&L AND no single trade > 3%."""
    if not os.path.exists(trade_log_path):
        return None, "no trade log found"
    try:
        df = pd.read_csv(trade_log_path)
    except Exception as e:
        return None, f"failed to read trade log: {e}"
    if 'Profit' not in df.columns or df.empty or total_pnl_dollars <= 0:
        return None, "insufficient trade data"
    top5 = df['Profit'].nlargest(5).sum()
    top1 = df['Profit'].max()
    pct_top5 = top5 / total_pnl_dollars * 100
    pct_top1 = top1 / total_pnl_dollars * 100
    passes_top1 = pct_top1 < 3.0
    passes_top5 = pct_top5 < 15.0
    passes = passes_top1 and passes_top5
    reason = f"top1={pct_top1:.2f}% (<3% req), top5={pct_top5:.2f}% (<15% req)"
    return passes, reason


def check_no_long_drawdown(max_rcvry_days):
    """Requirement 3: MaxRecovery < 365 days."""
    if max_rcvry_days is None:
        return None, "missing max recovery"
    try:
        mr = int(max_rcvry_days)
    except (ValueError, TypeError):
        return None, f"unparseable max recovery: {max_rcvry_days}"
    passes = mr < 365
    reason = f"max recovery = {mr} days (<365 req)"
    return passes, reason


def check_validation_gates(wfa, rolling_wfa, mc_score, oos_pnl_pct):
    """Requirement 4: WFA Pass, Rolling 3/3, MC >= 4, OOS > 0."""
    reasons = []
    passes = True
    if str(wfa).strip() != "Pass":
        passes = False
        reasons.append(f"WFA={wfa}")
    else:
        reasons.append("WFA=Pass")
    if "3/3" not in str(rolling_wfa):
        passes = False
        reasons.append(f"RollWFA={rolling_wfa}")
    else:
        reasons.append("RollWFA=3/3")
    try:
        mc = int(mc_score)
        if mc < 4:
            passes = False
            reasons.append(f"MC={mc}<4")
        else:
            reasons.append(f"MC={mc}")
    except (ValueError, TypeError):
        passes = False
        reasons.append(f"MC={mc_score}")
    try:
        oos = _pct_to_float(oos_pnl_pct)
        if oos <= 0:
            passes = False
            reasons.append(f"OOS={oos:+.2f}%")
        else:
            reasons.append(f"OOS={oos:+.2f}%")
    except Exception:
        passes = False
        reasons.append(f"OOS={oos_pnl_pct}")
    return passes, ", ".join(reasons)


def _find_trade_log(run_dir, portfolio, strategy_name):
    """Find the raw trades CSV for (portfolio, strategy). Matches by substring."""
    raw_trades_root = os.path.join(run_dir, 'raw_trades')
    if not os.path.isdir(raw_trades_root):
        return None
    # Match portfolio subdir by allowing any combination of space/underscore differences
    norm_target = portfolio.replace(' ', '').replace('_', '').lower()
    portfolio_dir = None
    for d in os.listdir(raw_trades_root):
        if d.replace(' ', '').replace('_', '').lower() == norm_target:
            portfolio_dir = os.path.join(raw_trades_root, d)
            break
    if portfolio_dir is None:
        return None
    # Match trade log by looking for a unique fragment of the strategy name
    # (strip any filename-invalid chars). Use the first ~25 chars of strategy
    # name up to a space as a unique fragment.
    fragment = strategy_name.split(':')[0].strip()  # "EC-R46" etc.
    for fname in os.listdir(portfolio_dir):
        if fragment in fname and fname.endswith('.csv'):
            return os.path.join(portfolio_dir, fname)
    return None


def score_run(run_dir):
    """Score every (portfolio, strategy) in the run. Returns (all_pass, rows)."""
    summary_csv = os.path.join(run_dir, 'overall_portfolio_summary.csv')
    if not os.path.exists(summary_csv):
        print(f"ERROR: no overall_portfolio_summary.csv in {run_dir}")
        return False, []

    df = pd.read_csv(summary_csv)
    rows = []
    all_pass = True

    for _, r in df.iterrows():
        portfolio = str(r.get('Portfolio', 'Unknown'))
        strategy = str(r.get('Strategy', 'Unknown'))

        pnl_pct = _pct_to_float(r.get('P&L (%)', 0))
        vs_spy = _pct_to_float(r.get('vs. SPY (B&H)', 0))
        max_rcvry = r.get('Max Rcvry (d)', None)
        wfa = r.get('WFA Verdict', '')
        rwfa = r.get('Rolling WFA', '')
        mc = r.get('MC Score', -1)
        oos = r.get('OOS P&L (%)', 0)

        # Find trade log for distribution check
        trade_log = _find_trade_log(run_dir, portfolio, strategy)
        total_dollars = None
        if trade_log and os.path.exists(trade_log):
            try:
                tl = pd.read_csv(trade_log)
                total_dollars = tl['Profit'].sum() if 'Profit' in tl.columns else None
            except Exception:
                pass

        r1_pass, r1_reason = check_beats_spy(pnl_pct, vs_spy)
        r2_pass, r2_reason = (None, "no trade log") if total_dollars is None else check_smooth_curve(trade_log, total_dollars)
        r3_pass, r3_reason = check_no_long_drawdown(max_rcvry)
        r4_pass, r4_reason = check_validation_gates(wfa, rwfa, mc, oos)

        all_four_pass = bool(r1_pass and r2_pass and r3_pass and r4_pass)
        if not all_four_pass:
            all_pass = False

        rows.append({
            'portfolio': portfolio,
            'strategy': strategy,
            'r1_beats_spy': r1_pass,
            'r1_reason': r1_reason,
            'r2_smooth': r2_pass,
            'r2_reason': r2_reason,
            'r3_no_long_dd': r3_pass,
            'r3_reason': r3_reason,
            'r4_gates': r4_pass,
            'r4_reason': r4_reason,
            'champion': all_four_pass,
        })

    return all_pass, rows


def _fmt(ok):
    if ok is None:
        return '?'
    return 'PASS' if ok else 'FAIL'


def print_report(run_dir, rows):
    print("=" * 100)
    print(f"EC CHAMPION SCORECARD — {os.path.basename(run_dir)}")
    print("=" * 100)
    print()
    for r in rows:
        verdict = 'CHAMPION' if r['champion'] else 'REJECTED'
        print(f"[{verdict}] {r['portfolio']} / {r['strategy']}")
        print(f"  1. Beats SPY:       {_fmt(r['r1_beats_spy'])}   {r['r1_reason']}")
        print(f"  2. Smooth curve:    {_fmt(r['r2_smooth'])}   {r['r2_reason']}")
        print(f"  3. No 12mo+ DD:     {_fmt(r['r3_no_long_dd'])}   {r['r3_reason']}")
        print(f"  4. Validation:      {_fmt(r['r4_gates'])}   {r['r4_reason']}")
        print()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    run_dir = sys.argv[1].rstrip('/').rstrip('\\')
    if not os.path.isdir(run_dir):
        print(f"ERROR: {run_dir} is not a directory")
        sys.exit(2)
    all_pass, rows = score_run(run_dir)
    print_report(run_dir, rows)
    champions = [r for r in rows if r['champion']]
    if champions:
        print(f"*** {len(champions)}/{len(rows)} CHAMPION(S) IDENTIFIED ***")
    else:
        print(f"*** 0/{len(rows)} candidates pass all four hard requirements ***")
    sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
