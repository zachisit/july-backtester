"""Out-of-sample validation harness for single-symbol GOOG strategy candidates.

WRITTEN BEFORE ANY CANDIDATE WAS SEEN. The pass/fail thresholds below are fixed
in advance on purpose: a validation gate that gets adjusted after you look at
the results is not a gate, it is a rationalisation.

Protocol
--------
Stage 1 (a separate agent, in-sample 2004-08-19..2017-12-31) searches freely.
Stage 2 (this file, out-of-sample 2018-01-01..2026-09-11) evaluates ONCE.

The OOS window gets one shot per candidate. Re-running a tweaked variant here
burns the holdout -- each additional look is another trial and inflates the
best observed result exactly the way the in-sample search does.

What a candidate must clear (all of them, on OOS):
  1. Beat GOOGL buy-and-hold on Calmar AND on Sharpe.
  2. Retain >= 60% of buy-and-hold CAGR (a strategy that sidesteps the
     drawdown by sidestepping the compounding has not solved anything).
  3. Deflated Sharpe Ratio > 0.95 given the FULL Stage-1 trial count.
  4. >= 30 OOS trades (fewer is an anecdote, not a strategy).
  5. PAIRED block-bootstrap: resampling the same blocks from the strategy and
     from buy-and-hold, the 5th percentile of (strategy Calmar - B&H Calmar)
     must be > 0. Paired because both series ride the same market path; an
     unpaired test would compare a percentile against a point estimate and
     reject almost everything.

Execution realism
-----------------
Signals are computed on the close of bar t and filled at the OPEN of bar t+1,
which makes fills gap-aware by construction: an overnight gap is paid, not
skipped. Costs are charged on every change in exposure.
"""

import numpy as np
import pandas as pd
from scipy import stats as sps

IS_START, IS_END = "2004-08-19", "2017-12-31"
OOS_START, OOS_END = "2018-01-01", "2026-09-11"

SLIPPAGE_BPS = 5.0
COMMISSION_PER_SHARE = 0.002
RISK_FREE = 0.04

# Fixed acceptance thresholds -- do not edit after seeing results.
MIN_CAGR_RETENTION = 0.60
MIN_DSR = 0.95
MIN_TRADES = 30
BOOTSTRAP_PCTILE = 5


# --------------------------------------------------------------------------
def load_goog(symbol="GOOGL"):
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ema200_bounce_study import load
    return load(symbol, "splice")


def run_positions(df, pos, slippage_bps=SLIPPAGE_BPS,
                  commission=COMMISSION_PER_SHARE, capital=100_000.0):
    """Execute a target-exposure series. pos[t] is decided at the close of bar t
    and filled at the open of bar t+1. Returns (equity, n_trades, exposure)."""
    pos = pd.Series(pos, index=df.index).fillna(0.0).clip(0.0, 1.0)
    target = pos.shift(1).fillna(0.0)          # what we hold entering bar t+1

    o = df["Open"].values
    c = df["Close"].values
    tgt = target.values
    n = len(df)

    equity = np.empty(n)
    eq = capital
    held = 0.0        # current exposure fraction
    shares = 0.0
    cash = capital

    for i in range(n):
        if not np.isfinite(o[i]) or o[i] <= 0:
            equity[i] = eq
            continue
        # rebalance at the open toward the target exposure
        if abs(tgt[i] - held) > 1e-9:
            mark = cash + shares * o[i]
            want_shares = (tgt[i] * mark) / o[i]
            d = want_shares - shares
            slip = o[i] * (slippage_bps / 10_000.0) * (1 if d > 0 else -1)
            fill = o[i] + slip
            cash -= d * fill + abs(d) * commission
            shares = want_shares
            held = tgt[i]
        eq = cash + shares * c[i]
        equity[i] = eq

    n_trades = int((target.diff().abs() > 1e-9).sum())
    return pd.Series(equity, index=df.index), n_trades, target


def perf(equity, rf=RISK_FREE):
    r = equity.pct_change().dropna()
    yrs = (equity.index[-1] - equity.index[0]).days / 365.25
    if yrs <= 0 or equity.iloc[0] <= 0:
        return {}
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(252)
    sharpe = (r.mean() * 252 - rf) / vol if vol > 0 else np.nan
    mdd = float((equity / equity.cummax() - 1).min())
    return dict(cagr=cagr, sharpe=sharpe, mdd=mdd,
                calmar=cagr / abs(mdd) if mdd < 0 else np.nan,
                vol=vol, years=yrs, skew=float(r.skew()),
                kurt=float(r.kurtosis()), n=len(r))


def deflated_sharpe(sr_ann, n_trials, n_obs, skew, excess_kurt, periods=252):
    """Bailey & Lopez de Prado DSR: probability the observed Sharpe is real
    after accounting for how many configurations were tried to find it."""
    sr = sr_ann / np.sqrt(periods)                      # per-period
    gamma = 0.5772156649
    if n_trials < 2:
        n_trials = 2
    # expected maximum Sharpe under the null across n_trials
    e_max = (sps.norm.ppf(1 - 1 / n_trials) * (1 - gamma)
             + sps.norm.ppf(1 - 1 / (n_trials * np.e)) * gamma)
    sr0 = e_max / np.sqrt(n_obs - 1)                    # null threshold
    denom = 1 - skew * sr + ((excess_kurt) / 4.0) * sr ** 2
    if denom <= 0:
        return np.nan, sr0 * np.sqrt(periods)
    z = (sr - sr0) * np.sqrt(n_obs - 1) / np.sqrt(denom)
    return float(sps.norm.cdf(z)), float(sr0 * np.sqrt(periods))


def _path_stats(path, yrs):
    eq = np.cumprod(1 + path)
    cagr = eq[-1] ** (1 / yrs) - 1
    mdd = (eq / np.maximum.accumulate(eq) - 1).min()
    vol = path.std() * np.sqrt(252)
    return (cagr,
            cagr / abs(mdd) if mdd < 0 else np.nan,
            (path.mean() * 252 - RISK_FREE) / vol if vol > 0 else np.nan)


def paired_block_bootstrap(equity, bh_equity, n_iter=2000, block=21, seed=20260912):
    """Resample block starts ONCE per iteration and apply the identical blocks to
    both the strategy and buy-and-hold. Both ride the same market path, so the
    quantity with a meaningful confidence interval is the DIFFERENCE, not either
    series on its own."""
    rs = equity.pct_change().dropna().values
    rb = bh_equity.pct_change().dropna().values
    n = min(len(rs), len(rb))
    rs, rb = rs[:n], rb[:n]
    if n < block * 3:
        return {}
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(n / block))
    yrs = n / 252.0
    out = {"cagr": [], "calmar": [], "sharpe": [],
           "d_cagr": [], "d_calmar": [], "d_sharpe": []}
    for _ in range(n_iter):
        starts = rng.integers(0, n - block, size=nb)
        sl = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        sc, sk, ss = _path_stats(rs[sl], yrs)
        bc, bk, bs = _path_stats(rb[sl], yrs)
        out["cagr"].append(sc); out["calmar"].append(sk); out["sharpe"].append(ss)
        out["d_cagr"].append(sc - bc)
        out["d_calmar"].append(sk - bk)
        out["d_sharpe"].append(ss - bs)
    return {k: np.nanpercentile(v, [5, 50, 95]) for k, v in out.items()}


# --------------------------------------------------------------------------
def validate(name, df, pos, n_trials, window="oos", verbose=True):
    """Run one candidate through the full gate. n_trials = Stage-1 search size."""
    lo, hi = (OOS_START, OOS_END) if window == "oos" else (IS_START, IS_END)
    d = df.loc[lo:hi]
    p = pd.Series(pos, index=df.index).loc[lo:hi]

    eq, trades, expo = run_positions(d, p)
    bh, _, _ = run_positions(d, pd.Series(1.0, index=d.index))

    s, b = perf(eq), perf(bh)
    dsr, sr0 = deflated_sharpe(s["sharpe"], n_trials, s["n"], s["skew"], s["kurt"])
    boot = paired_block_bootstrap(eq, bh)

    checks = {
        "beats B&H Calmar": s["calmar"] > b["calmar"],
        "beats B&H Sharpe": s["sharpe"] > b["sharpe"],
        f"keeps >={MIN_CAGR_RETENTION:.0%} of B&H CAGR": s["cagr"] >= MIN_CAGR_RETENTION * b["cagr"],
        f"DSR > {MIN_DSR}": (dsr is not np.nan) and dsr > MIN_DSR,
        f">= {MIN_TRADES} trades": trades >= MIN_TRADES,
        "paired boot p5 dCalmar > 0": bool(len(boot)) and boot["d_calmar"][0] > 0,
    }

    if verbose:
        print(f"\n{'='*84}\n  {name}   [{window.upper()} {lo} -> {hi}]   trials={n_trials:,}\n{'='*84}")
        print(f"  {'':<10}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}{'vol':>8}{'trades':>8}")
        print(f"  {'strategy':<10}{s['cagr']:>9.2%}{s['sharpe']:>9.2f}{s['mdd']:>9.1%}"
              f"{s['calmar']:>9.2f}{s['vol']:>8.1%}{trades:>8}")
        print(f"  {'B&H':<10}{b['cagr']:>9.2%}{b['sharpe']:>9.2f}{b['mdd']:>9.1%}"
              f"{b['calmar']:>9.2f}{b['vol']:>8.1%}{'-':>8}")
        print(f"  avg exposure {expo.mean():.1%} | DSR {dsr:.3f} (null Sharpe hurdle {sr0:.2f})")
        if boot:
            print(f"  bootstrap CAGR p5/50/95 {boot['cagr'][0]:+.1%}/{boot['cagr'][1]:+.1%}/{boot['cagr'][2]:+.1%}")
            print(f"  paired vs B&H  dCalmar p5/50/95 {boot['d_calmar'][0]:+.2f}/{boot['d_calmar'][1]:+.2f}/{boot['d_calmar'][2]:+.2f}"
                  f" | dSharpe p5 {boot['d_sharpe'][0]:+.2f}")
        print("  " + "-"*40)
        for k, v in checks.items():
            print(f"   {'PASS' if v else 'FAIL'}  {k}")
        print(f"  VERDICT: {'ACCEPT' if all(checks.values()) else 'REJECT'}")

    return dict(name=name, window=window, trades=trades, dsr=dsr,
                strat=s, bh=b, boot=boot, checks=checks,
                passed=all(checks.values()))


def validate_returns(name, ret, bh_ret, n_trials, window="oos", verbose=True,
                     n_trades=None):
    """Same gate, but driven by a pre-computed return series.

    Needed for strategies whose exposure is not constant across a daily bar --
    the overnight leg (hold close_t -> open_t+1, flat intraday) cannot be
    written as a daily target-exposure series, so its returns are supplied
    directly. Costs must already be embedded in `ret`.
    """
    lo, hi = (OOS_START, OOS_END) if window == "oos" else (IS_START, IS_END)
    r = ret.loc[lo:hi].dropna()
    rb = bh_ret.loc[lo:hi].dropna()
    idx = r.index.intersection(rb.index)
    r, rb = r.loc[idx], rb.loc[idx]

    eq = (1 + r).cumprod() * 100_000.0
    bh = (1 + rb).cumprod() * 100_000.0
    trades = n_trades if n_trades is not None else len(r)

    s_, b_ = perf(eq), perf(bh)
    dsr, sr0 = deflated_sharpe(s_["sharpe"], n_trials, s_["n"], s_["skew"], s_["kurt"])
    boot = paired_block_bootstrap(eq, bh)

    checks = {
        "beats B&H Calmar": s_["calmar"] > b_["calmar"],
        "beats B&H Sharpe": s_["sharpe"] > b_["sharpe"],
        f"keeps >={MIN_CAGR_RETENTION:.0%} of B&H CAGR": s_["cagr"] >= MIN_CAGR_RETENTION * b_["cagr"],
        f"DSR > {MIN_DSR}": (dsr is not np.nan) and dsr > MIN_DSR,
        f">= {MIN_TRADES} trades": trades >= MIN_TRADES,
        "paired boot p5 dCalmar > 0": bool(len(boot)) and boot["d_calmar"][0] > 0,
    }
    if verbose:
        print(f"\n{'='*84}\n  {name}   [{window.upper()} {lo} -> {hi}]   trials={n_trials:,}\n{'='*84}")
        print(f"  {'':<10}{'CAGR':>9}{'Sharpe':>9}{'MaxDD':>9}{'Calmar':>9}{'vol':>8}{'trades':>8}")
        print(f"  {'strategy':<10}{s_['cagr']:>9.2%}{s_['sharpe']:>9.2f}{s_['mdd']:>9.1%}"
              f"{s_['calmar']:>9.2f}{s_['vol']:>8.1%}{trades:>8}")
        print(f"  {'B&H':<10}{b_['cagr']:>9.2%}{b_['sharpe']:>9.2f}{b_['mdd']:>9.1%}"
              f"{b_['calmar']:>9.2f}{b_['vol']:>8.1%}{'-':>8}")
        print(f"  DSR {dsr:.3f} (null Sharpe hurdle {sr0:.2f})")
        if boot:
            print(f"  paired vs B&H  dCalmar p5/50/95 {boot['d_calmar'][0]:+.2f}/{boot['d_calmar'][1]:+.2f}/{boot['d_calmar'][2]:+.2f}"
                  f" | dSharpe p5 {boot['d_sharpe'][0]:+.2f}")
        print("  " + "-"*40)
        for k, v in checks.items():
            print(f"   {'PASS' if v else 'FAIL'}  {k}")
        print(f"  VERDICT: {'ACCEPT' if all(checks.values()) else 'REJECT'}")
    return dict(name=name, passed=all(checks.values()), strat=s_, bh=b_,
                dsr=dsr, boot=boot, checks=checks)


if __name__ == "__main__":
    df = load_goog()
    print(f"loaded {len(df)} bars {df.index.min().date()} -> {df.index.max().date()}")
    print(f"IS  {IS_START}..{IS_END}  |  OOS {OOS_START}..{OOS_END}")
    # sanity: buy-and-hold against itself must tie, not beat
    bh = pd.Series(1.0, index=df.index)
    validate("BUY & HOLD (control)", df, bh, n_trials=1, window="oos")
