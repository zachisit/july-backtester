"""ORB stock-selection research — Stage 2: intraday 5-min ORB backtest.

Faithful to Zarattini/Barbon/Aziz (2024). Consumes Stage 1's daily "stocks in
play" selections (orb_selection_stage1.csv) and runs the intraday opening-range
breakout with risk-based sizing, a 10R target / EOD exit, commissions + slippage,
compounded into an equity curve, benchmarked vs SPY & QQQ buy-and-hold.

Mechanics per (session, symbol):
  * Opening range = FIRST 5-min candle (09:30-09:35 ET, RTH only).
  * Direction: bullish candle (close>open) -> long on break of OR high;
    bearish -> short on break of OR low; |body| < DOJI_FRAC*range -> skip.
  * Entry fill at the breakout level (or the triggering bar's open if it gapped
    through), + slippage.
  * Stop = opposite extreme of the OR candle. Risk/share = |entry - stop|.
  * Size: risk RISK_PCT of equity per trade; shares = risk$ / risk_per_share,
    capped so notional <= LEVERAGE*equity / TOP_N (even split of buying power).
  * Exit: first of {stop hit, 10R target, EOD close}. Stop checked before target
    within a bar (conservative). Commissions both sides + slippage both sides.

Run: rtk .venv/bin/python scripts/orb_stage2_backtest.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from config import CONFIG
from services.polygon_service import get_price_data

HERE = os.path.dirname(os.path.abspath(__file__))
SEL_CSV = os.path.join(HERE, "orb_selection_stage1.csv")

# --- ORB parameters (paper defaults) ---
INITIAL_EQUITY = 25_000.0     # PDT-account scale (paper uses $25k)
RISK_PCT = 0.01               # risk 1% of equity per trade
LEVERAGE = 4.0                # max buying power (Reg-T intraday)
TOP_N = 20                    # picks/day (buying power split)
TARGET_R = 10.0               # 10R profit target
DOJI_FRAC = 0.10              # skip if |body| < 10% of candle range
COMMISSION_PS = float(os.environ.get("ORB_COMMISSION_PS", 0.0005))  # $/share each side (IBKR-like)
SLIPPAGE_PCT = float(os.environ.get("ORB_SLIPPAGE_PCT", 0.0005))     # each side on volatile names
OR_MINUTES = 5                # opening-range = first 5-min candle
START = "2021-07-12"
END = "2026-06-15"


def _fetch_5min(sym):
    cfg = dict(CONFIG)
    cfg["timeframe"] = "MIN"
    cfg["timeframe_multiplier"] = 5
    try:
        df = get_price_data(sym, START, END, cfg)
        if df is None or df.empty:
            return None
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy().sort_index()
        # Normalize to US/Eastern and keep regular trading hours only.
        idx = df.index
        if idx.tz is None:
            idx = idx.tz_localize("UTC")
        df.index = idx.tz_convert("America/New_York")
        df = df.between_time("09:30", "15:59")
        return df
    except Exception as e:
        print(f"  5min fetch err {sym}: {str(e)[:60]}")
        return None


def _simulate_trade(day_df, equity):
    """Return realized P&L ($) for one symbol-session, or None if no trade."""
    if len(day_df) < 3:
        return None
    o = day_df.iloc[0]
    or_high, or_low, or_open, or_close = o["High"], o["Low"], o["Open"], o["Close"]
    rng = or_high - or_low
    if rng <= 0:
        return None
    body = abs(or_close - or_open)
    if body < DOJI_FRAC * rng:
        return None  # doji -> no conviction

    long = or_close > or_open
    rest = day_df.iloc[1:]
    entry = stop = None
    entry_i = None
    for i in range(len(rest)):
        bar = rest.iloc[i]
        if long and bar["High"] >= or_high:
            entry = max(or_high, bar["Open"]) * (1 + SLIPPAGE_PCT)
            stop = or_low
            entry_i = i
            break
        if (not long) and bar["Low"] <= or_low:
            entry = min(or_low, bar["Open"]) * (1 - SLIPPAGE_PCT)
            stop = or_high
            entry_i = i
            break
    if entry is None:
        return None  # no breakout this session

    risk_ps = abs(entry - stop)
    if risk_ps <= 0:
        return None
    target = entry + TARGET_R * risk_ps if long else entry - TARGET_R * risk_ps

    shares = (RISK_PCT * equity) / risk_ps
    max_notional = LEVERAGE * equity / TOP_N
    if shares * entry > max_notional:
        shares = max_notional / entry
    if shares <= 0:
        return None

    # Scan from entry bar onward: stop (priority) then target, else EOD close.
    exit_px = None
    for j in range(entry_i, len(rest)):
        bar = rest.iloc[j]
        if long:
            if bar["Low"] <= stop:
                exit_px = stop * (1 - SLIPPAGE_PCT); break
            if bar["High"] >= target:
                exit_px = target * (1 - SLIPPAGE_PCT); break
        else:
            if bar["High"] >= stop:
                exit_px = stop * (1 + SLIPPAGE_PCT); break
            if bar["Low"] <= target:
                exit_px = target * (1 + SLIPPAGE_PCT); break
    if exit_px is None:
        exit_px = rest.iloc[-1]["Close"] * (1 - SLIPPAGE_PCT if long else 1 + SLIPPAGE_PCT)

    gross = shares * (exit_px - entry) * (1 if long else -1)
    commission = 2 * shares * COMMISSION_PS
    return gross - commission


def _metrics(daily_ret, equity_curve, label):
    dr = daily_ret.dropna()
    n = len(dr)
    if n < 2:
        return
    ann = 252
    total = equity_curve.iloc[-1] / equity_curve.iloc[0] - 1
    years = n / ann
    cagr = (equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (1 / years) - 1 if years > 0 else np.nan
    vol = dr.std() * np.sqrt(ann)
    sharpe = (dr.mean() * ann - 0.04) / vol if vol > 0 else np.nan
    roll_max = equity_curve.cummax()
    dd = (equity_curve / roll_max - 1).min()
    calmar = cagr / abs(dd) if dd < 0 else np.nan
    print(f"  {label:20s} CAGR {cagr*100:7.2f}%  Sharpe {sharpe:5.2f}  MaxDD {dd*100:7.2f}%  "
          f"Calmar {calmar:5.2f}  Total {total*100:8.1f}%")


def main():
    picks = pd.read_csv(SEL_CSV, parse_dates=["date"])
    names = sorted(picks["sym"].unique())
    print(f"Loaded {len(picks):,} selections over {picks['date'].nunique()} sessions, {len(names)} unique names.")
    print(f"Fetching 5-min bars for {len(names)} names (cached)...")

    bars = {}
    for i, s in enumerate(names):
        df = _fetch_5min(s)
        if df is not None and not df.empty:
            df["d"] = df.index.normalize().tz_localize(None)
            bars[s] = df
        if (i + 1) % 40 == 0:
            print(f"  fetched {i+1}/{len(names)}...")
    print(f"Have 5-min data for {len(bars)}/{len(names)} names.\n")

    # Group picks by day; simulate; compound.
    picks["d"] = picks["date"].dt.tz_localize(None).dt.normalize()
    trades = []
    equity = INITIAL_EQUITY
    eq_rows = []
    n_trades = 0
    for d, grp in picks.groupby("d"):
        day_pnl = 0.0
        for sym in grp["sym"]:
            bdf = bars.get(sym)
            if bdf is None:
                continue
            day_df = bdf[bdf["d"] == d]
            if day_df.empty:
                continue
            pnl = _simulate_trade(day_df, equity)
            if pnl is None:
                continue
            n_trades += 1
            day_pnl += pnl
            trades.append((d, sym, pnl, pnl / (RISK_PCT * equity)))  # R-multiple approx
        equity += day_pnl
        eq_rows.append((d, equity, day_pnl / (equity - day_pnl) if (equity - day_pnl) != 0 else 0.0))

    eq = pd.DataFrame(eq_rows, columns=["date", "equity", "ret"]).set_index("date")
    tr = pd.DataFrame(trades, columns=["date", "sym", "pnl", "R"])
    print(f"=== ORB STOCK-SELECTION BACKTEST ({eq.index.min().date()} -> {eq.index.max().date()}) ===")
    print(f"Trading days: {len(eq)}  |  total trades: {n_trades}  |  avg trades/day: {n_trades/len(eq):.1f}")
    wins = (tr["pnl"] > 0).sum()
    print(f"Win rate: {wins/len(tr)*100:.1f}%  |  avg R: {tr['R'].mean():.3f}  |  "
          f"profit factor: {tr.loc[tr.pnl>0,'pnl'].sum()/abs(tr.loc[tr.pnl<0,'pnl'].sum()):.2f}")
    print(f"Final equity: ${equity:,.0f}  (from ${INITIAL_EQUITY:,.0f})\n")

    print("Performance (ann. Rf=4%):")
    _metrics(eq["ret"], eq["equity"], "ORB (1% risk, 10R)")

    # Benchmarks over the same dates.
    for bsym in ("SPY", "QQQ"):
        cfg = dict(CONFIG); cfg["timeframe"] = "D"; cfg["timeframe_multiplier"] = 1
        b = get_price_data(bsym, START, END, cfg)
        if b is None or b.empty:
            continue
        b = b.sort_index(); b.index = b.index.tz_localize(None).normalize()
        b = b[b.index.isin(eq.index)]
        bret = b["Close"].pct_change()
        beq = INITIAL_EQUITY * (1 + bret.fillna(0)).cumprod()
        _metrics(bret, beq, f"{bsym} buy & hold")

    eq.to_csv(os.path.join(HERE, "orb_stage2_equity.csv"))
    tr.to_csv(os.path.join(HERE, "orb_stage2_trades.csv"), index=False)
    print(f"\nWrote equity + trades CSVs to {HERE}/")


if __name__ == "__main__":
    main()
