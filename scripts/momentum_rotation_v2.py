"""
Momentum Rotation v2 — Standalone Backtest
===========================================
Cross-sectional 60-day momentum rotation on NASDAQ 100.

Cannot run via main.py — requires all symbols' data simultaneously for
weekly cross-sectional ranking. This script implements the full logic.

Run:
    python scripts/momentum_rotation_v2.py

Strategy:
    - Universe  : NASDAQ 100
    - Signal    : RS_60d = (Close[t] / Close[t-60]) - 1
    - Regime    : QQQ close[t-1] > QQQ 200-day SMA[t-1]  (Friday signal day)
    - Rebalance : Every Monday (signal on Friday close, execute at Monday open)
    - Selection : Hold top-5 stocks; keep if still in top-15, replace if fell below
    - Sizing    : 20% of current equity per NEW position only (existing ride)
    - Stop      : None — exit only on rank drop or regime OFF
    - Slippage  : +10 bps buys, -10 bps sells
    - Commission: $0.002 per share
"""

import sys
import os
import json
import math
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — avoids Tkinter memory exhaustion on long runs

import numpy as np
import pandas as pd
from collections import defaultdict
from config import CONFIG

# ── Strategy constants ────────────────────────────────────────────────────────
INITIAL_CAPITAL    = 100_000.0
ALLOCATION_PCT     = 0.20          # 20% of current equity per new position
MAX_POSITION_SIZE  = 50_000.0      # hard dollar cap per position; None = no cap
MAX_POSITIONS      = 5
SELL_BUFFER_RANK   = 15            # sell if rank drops below this
MOMENTUM_LOOKBACK  = 60            # trading days for RS_60d
REGIME_MA_PERIOD   = 200           # QQQ SMA period
SLIPPAGE_BUY       = 0.0010        # 10 bps added to buy price
SLIPPAGE_SELL      = 0.0010        # 10 bps subtracted from sell price
COMMISSION_PER_SHR = 0.002         # $0.002 per share each way
MIN_PRICE          = 5.0           # skip stocks below $5

START_DATE         = "1990-01-01"
END_DATE           = datetime.now().strftime("%Y-%m-%d")
TICKER_FILE        = "tickers_to_scan/nasdaq_100.json"
REGIME_TICKER      = "QQQ"
RISK_FREE_RATE     = 0.05


# ── Data loading ──────────────────────────────────────────────────────────────

def load_all_data() -> dict:
    """Fetch OHLCV for all NASDAQ 100 tickers + QQQ via the configured service."""
    with open(TICKER_FILE) as f:
        tickers = json.load(f)

    if REGIME_TICKER not in tickers:
        tickers = [REGIME_TICKER] + list(tickers)

    from services import get_data_service
    fetcher = get_data_service()

    all_data = {}
    print(f"  Fetching {len(tickers)} symbols ({START_DATE} → {END_DATE})...")

    for i, sym in enumerate(tickers):
        df = fetcher(sym, START_DATE, END_DATE, CONFIG)
        if df is None or df.empty:
            continue

        df = df.copy()
        # Flatten MultiIndex columns (yfinance sometimes returns ticker-level headers)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(-1)
        # Deduplicate columns, then index
        df = df.loc[:, ~df.columns.duplicated(keep="first")]
        # Normalise index to tz-naive UTC midnight for consistent date lookup
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        df.index = df.index.normalize()
        df = df[~df.index.duplicated(keep="last")]

        if len(df) < MOMENTUM_LOOKBACK + 10:
            continue

        all_data[sym] = df

        if (i + 1) % 20 == 0 or (i + 1) == len(tickers):
            print(f"    {i+1}/{len(tickers)} loaded", flush=True)

    print(f"  Loaded {len(all_data)} symbols OK\n")
    return all_data


# ── Price helpers ─────────────────────────────────────────────────────────────

def get_price(df: pd.DataFrame, target_date, col: str = "Close") -> float:
    """Return df[col] on target_date. NaN if date not in index."""
    target = pd.Timestamp(target_date).normalize()
    if target not in df.index:
        return np.nan
    return float(df.at[target, col])


# ── Rebalance calendar ────────────────────────────────────────────────────────

def build_rebalance_pairs(all_data: dict) -> list:
    """
    Returns [(signal_date, exec_date), ...] for every week.
      signal_date = last trading day of the PRIOR week  (Friday equiv)
      exec_date   = first trading day of the CURRENT week (Monday equiv)
    """
    all_dates = set()
    for df in all_data.values():
        all_dates.update(df.index.tolist())

    trading_dates = sorted(all_dates)

    week_map = defaultdict(list)
    for d in trading_dates:
        key = (d.isocalendar()[0], d.isocalendar()[1])
        week_map[key].append(d)

    sorted_weeks = sorted(week_map.keys())
    pairs = []
    for i in range(1, len(sorted_weeks)):
        signal_date = week_map[sorted_weeks[i - 1]][-1]  # last day of prior week
        exec_date   = week_map[sorted_weeks[i]][0]        # first day of current week
        pairs.append((signal_date, exec_date))

    return pairs


# ── Regime filter ─────────────────────────────────────────────────────────────

def is_regime_on(qqq_df: pd.DataFrame, signal_date) -> bool:
    """True if QQQ close > 200-day SMA on signal_date."""
    target = pd.Timestamp(signal_date).normalize()
    if target not in qqq_df.index:
        return False

    iloc_pos = qqq_df.index.get_loc(target)
    if iloc_pos < REGIME_MA_PERIOD - 1:
        return False

    close_now = float(qqq_df["Close"].iloc[iloc_pos])
    ma_200    = float(qqq_df["Close"].iloc[iloc_pos - REGIME_MA_PERIOD + 1: iloc_pos + 1].mean())
    return close_now > ma_200


# ── RS_60d ───────────────────────────────────────────────────────────────────

def compute_rs60_all(all_data: dict, qqq_df: pd.DataFrame, signal_date) -> dict:
    """
    Returns {symbol: rs_60d} for all stocks with valid data on signal_date.
    QQQ is excluded from the ranking universe.
    """
    target   = pd.Timestamp(signal_date).normalize()
    rs_scores = {}

    for sym, df in all_data.items():
        if sym == REGIME_TICKER:
            continue
        if target not in df.index:
            continue

        iloc_pos = df.index.get_loc(target)
        if iloc_pos < MOMENTUM_LOOKBACK:
            continue

        close_now  = float(df["Close"].iloc[iloc_pos])
        close_prev = float(df["Close"].iloc[iloc_pos - MOMENTUM_LOOKBACK])

        if close_prev > 0 and not np.isnan(close_now) and not np.isnan(close_prev):
            rs_scores[sym] = (close_now / close_prev) - 1

    return rs_scores


# ── Simulation ────────────────────────────────────────────────────────────────

def run_backtest(all_data: dict, qqq_df: pd.DataFrame, rebalance_pairs: list):
    cash      = INITIAL_CAPITAL
    positions = {}   # {sym: {shares, entry_price, entry_date, cost_basis}}
    trade_log = []
    equity_log = []

    def mtm_equity(price_date):
        total = cash
        for sym, pos in positions.items():
            p = get_price(all_data[sym], price_date, "Close")
            if np.isnan(p):
                p = pos["entry_price"]
            total += pos["shares"] * p
        return total

    def do_sell(sym, exec_date, reason):
        nonlocal cash
        pos      = positions[sym]
        raw_open = get_price(all_data[sym], exec_date, "Open")
        if np.isnan(raw_open) or raw_open <= 0:
            return
        exit_price = raw_open * (1 - SLIPPAGE_SELL)
        shares     = pos["shares"]
        commission = shares * COMMISSION_PER_SHR
        proceeds   = shares * exit_price - commission
        pnl        = proceeds - pos["cost_basis"]
        trade_log.append({
            "Symbol":     sym,
            "EntryDate":  pos["entry_date"],
            "ExitDate":   exec_date,
            "EntryPrice": round(pos["entry_price"], 4),
            "ExitPrice":  round(exit_price, 4),
            "Shares":     shares,
            "PnL":        round(pnl, 2),
            "PnLPct":     round(pnl / pos["cost_basis"] * 100, 2) if pos["cost_basis"] > 0 else 0.0,
            "HoldDays":   (exec_date - pos["entry_date"]).days,
            "ExitReason": reason,
        })
        cash += proceeds
        del positions[sym]

    def do_buy(sym, exec_date, alloc_equity) -> bool:
        nonlocal cash
        df = all_data.get(sym)
        if df is None:
            return False
        raw_open = get_price(df, exec_date, "Open")
        if np.isnan(raw_open) or raw_open < MIN_PRICE:
            return False
        entry_price    = raw_open * (1 + SLIPPAGE_BUY)
        position_value = alloc_equity * ALLOCATION_PCT
        if MAX_POSITION_SIZE is not None:
            position_value = min(position_value, MAX_POSITION_SIZE)
        shares         = math.floor(position_value / entry_price)
        if shares <= 0:
            return False
        commission = shares * COMMISSION_PER_SHR
        total_cost = shares * entry_price + commission
        if total_cost > cash:
            return False
        cash -= total_cost
        positions[sym] = {
            "shares":      shares,
            "entry_price": entry_price,
            "entry_date":  exec_date,
            "cost_basis":  total_cost,
        }
        return True

    print(f"  Simulating {len(rebalance_pairs)} rebalance weeks...")

    for signal_date, exec_date in rebalance_pairs:

        equity_log.append((signal_date, mtm_equity(signal_date)))

        regime_on = is_regime_on(qqq_df, signal_date)
        if not regime_on:
            for sym in list(positions.keys()):
                do_sell(sym, exec_date, "Regime OFF")
            continue

        rs_scores = compute_rs60_all(all_data, qqq_df, signal_date)
        if not rs_scores:
            continue

        ranked  = sorted(rs_scores, key=rs_scores.get, reverse=True)
        rank_of = {sym: i + 1 for i, sym in enumerate(ranked)}

        alloc_equity = mtm_equity(signal_date)

        for sym in list(positions.keys()):
            r = rank_of.get(sym, 9_999)
            if r > SELL_BUFFER_RANK:
                do_sell(sym, exec_date, f"Rank {r} > {SELL_BUFFER_RANK}")

        slots = MAX_POSITIONS - len(positions)
        for sym in ranked:
            if slots <= 0:
                break
            if sym not in positions:
                if do_buy(sym, exec_date, alloc_equity):
                    slots -= 1

    if rebalance_pairs:
        last_exec = rebalance_pairs[-1][1]
        for sym in list(positions.keys()):
            do_sell(sym, last_exec, "End of backtest")

    equity_log.append((rebalance_pairs[-1][1], cash))
    return trade_log, equity_log


# ── Results ───────────────────────────────────────────────────────────────────

def print_results(trade_log: list, equity_log: list):
    if not trade_log:
        print("  No trades generated — check data and regime filter.")
        return

    df_t = pd.DataFrame(trade_log)
    df_e = (
        pd.DataFrame(equity_log, columns=["Date", "Equity"])
        .drop_duplicates("Date")
        .sort_values("Date")
        .set_index("Date")
    )
    df_e.index = pd.to_datetime(df_e.index)

    init_eq   = INITIAL_CAPITAL
    final_eq  = df_e["Equity"].iloc[-1]
    total_ret = (final_eq - init_eq) / init_eq
    start     = df_e.index[0]
    end       = df_e.index[-1]
    years     = (end - start).days / 365.25
    cagr      = (final_eq / init_eq) ** (1 / years) - 1 if years > 0 else 0.0

    hwm    = df_e["Equity"].cummax()
    dd     = (df_e["Equity"] - hwm) / hwm
    max_dd = dd.min()

    daily_ret = df_e["Equity"].pct_change().dropna()
    excess    = daily_ret - (RISK_FREE_RATE / 252)
    sharpe    = excess.mean() / excess.std() * (252 ** 0.5) if excess.std() > 0 else 0.0

    wins       = (df_t["PnL"] > 0).sum()
    win_rate   = wins / len(df_t)
    gross_win  = df_t[df_t["PnL"] > 0]["PnL"].sum()
    gross_loss = df_t[df_t["PnL"] < 0]["PnL"].abs().sum()
    pf         = gross_win / gross_loss if gross_loss > 0 else float("inf")

    print("\n" + "=" * 62)
    print("  MOMENTUM ROTATION v2 — RESULTS")
    print("=" * 62)
    print(f"  Period           : {start.date()} → {end.date()} ({years:.1f}y)")
    print(f"  Initial Capital  : ${init_eq:>12,.2f}")
    print(f"  Final Equity     : ${final_eq:>12,.2f}")
    print(f"  Net Return       : {total_ret:>+.1%}")
    print(f"  CAGR             : {cagr:>+.2%}")
    print(f"  Max Drawdown     : {max_dd:.2%}")
    print(f"  Sharpe (daily)   : {sharpe:.2f}")
    print(f"  Total Trades     : {len(df_t)}")
    print(f"  Win Rate         : {win_rate:.1%}")
    print(f"  Profit Factor    : {pf:.2f}")
    print(f"  Avg Hold (days)  : {df_t['HoldDays'].mean():.0f}")
    print("=" * 62)

    print("\n  Top 5 by total P&L:")
    by_sym = df_t.groupby("Symbol")["PnL"].sum().sort_values(ascending=False)
    for sym, pnl in by_sym.head(5).items():
        print(f"    {sym:<8}  ${pnl:>10,.0f}")

    print("\n  Bottom 5 by total P&L:")
    for sym, pnl in by_sym.tail(5).items():
        print(f"    {sym:<8}  ${pnl:>10,.0f}")

    print("\n  Exit breakdown:")
    for reason, cnt in df_t["ExitReason"].value_counts().items():
        print(f"    {reason:<40}  {cnt}")


# ── Signal file (for main.py integration) ────────────────────────────────────

def generate_signal_file(all_data: dict, qqq_df: pd.DataFrame, rebalance_pairs: list):
    """
    Generates a CSV of per-stock buy/sell signals so main.py can run the
    full pipeline (MC, WFA, PDF report) on this strategy.

    Signal is placed on the FRIDAY (signal_date) so the engine, which fills
    at next-day open, executes on Monday — matching the strategy's intent.

    Output: output/mr_v2_signals.csv  [Date, Symbol, Signal]
    """
    rows      = []
    positions = set()   # currently held symbols (for tracking only)

    for signal_date, _ in rebalance_pairs:
        regime_on = is_regime_on(qqq_df, signal_date)

        if not regime_on:
            for sym in list(positions):
                rows.append({"Date": signal_date, "Symbol": sym, "Signal": -1})
            positions.clear()
            continue

        rs_scores = compute_rs60_all(all_data, qqq_df, signal_date)
        if not rs_scores:
            continue

        ranked  = sorted(rs_scores, key=rs_scores.get, reverse=True)
        rank_of = {sym: i + 1 for i, sym in enumerate(ranked)}

        # Sells: held stocks that fell below buffer rank
        for sym in list(positions):
            if rank_of.get(sym, 9_999) > SELL_BUFFER_RANK:
                rows.append({"Date": signal_date, "Symbol": sym, "Signal": -1})
                positions.discard(sym)

        # Buys: fill empty slots
        slots = MAX_POSITIONS - len(positions)
        for sym in ranked:
            if slots <= 0:
                break
            if sym not in positions:
                rows.append({"Date": signal_date, "Symbol": sym, "Signal": 1})
                positions.add(sym)
                slots -= 1

    # Close all remaining at last signal date
    if rebalance_pairs:
        last_signal = rebalance_pairs[-1][0]
        for sym in list(positions):
            rows.append({"Date": last_signal, "Symbol": sym, "Signal": -1})

    os.makedirs("output", exist_ok=True)
    signal_path = "output/mr_v2_signals.csv"
    df_sig = pd.DataFrame(rows)
    df_sig["Date"] = pd.to_datetime(df_sig["Date"])
    df_sig.to_csv(signal_path, index=False)
    print(f"  Signal file  → {signal_path}  ({len(df_sig)} rows)")
    return signal_path


# ── MAE / MFE computation ─────────────────────────────────────────────────────

def compute_mae_mfe(trade_log: list, all_data: dict) -> pd.DataFrame:
    """
    Compute Maximum Adverse Excursion (MAE) and Maximum Favorable Excursion
    (MFE) for each trade using intraday high/low across the holding period.

    MAE = max drawdown from entry during the hold  (negative %, e.g. -5.2)
    MFE = max run-up from entry during the hold    (positive %, e.g. +12.3)
    """
    rows = []
    for trade in trade_log:
        sym        = trade["Symbol"]
        entry_date = pd.Timestamp(trade["EntryDate"]).normalize()
        exit_date  = pd.Timestamp(trade["ExitDate"]).normalize()
        entry_px   = trade["EntryPrice"]
        df         = all_data.get(sym)

        mae = np.nan
        mfe = np.nan

        if df is not None and entry_px > 0:
            # Normalise index
            idx = df.index
            if hasattr(idx, "tz") and idx.tz is not None:
                idx_naive = idx.tz_localize(None).normalize()
            else:
                idx_naive = idx.normalize()

            mask = (idx_naive >= entry_date) & (idx_naive <= exit_date)
            if mask.any():
                period = df.loc[mask]
                low_min  = period["Low"].min()
                high_max = period["High"].max()
                mae = (low_min  - entry_px) / entry_px * 100   # negative
                mfe = (high_max - entry_px) / entry_px * 100   # positive

        row = dict(trade)
        row["MAE"] = round(mae, 2) if not np.isnan(mae) else np.nan
        row["MFE"] = round(mfe, 2) if not np.isnan(mfe) else np.nan
        rows.append(row)

    return pd.DataFrame(rows)


# ── PDF report (Option B) ─────────────────────────────────────────────────────

def generate_pdf_report(df_t: pd.DataFrame, all_data: dict = None, run_dir: str = "output"):
    """
    Adapts the trade log to the analyzer's expected column schema and
    generates a full PDF tearsheet via trade_analyzer — all sections enabled.
    """
    from trade_analyzer.analyzer import generate_trade_report

    # Compute MAE/MFE if we have OHLCV data
    if all_data is not None:
        print("  Computing MAE/MFE...")
        df_t = compute_mae_mfe(df_t.to_dict("records"), all_data)

    # Rename script columns → analyzer expected names
    report_df = df_t.rename(columns={
        "PnL":      "Profit",
        "PnLPct":   "ProfitPct",   # data_handler maps ProfitPct → % Profit
        "HoldDays": "HoldDuration",
    })

    # Ensure dates are proper Timestamps
    report_df["EntryDate"] = pd.to_datetime(report_df["EntryDate"])
    report_df["ExitDate"]  = pd.to_datetime(report_df["ExitDate"])

    output_dir  = os.path.join(run_dir, "detailed_reports")
    report_name = "Momentum_Rotation_v2"
    os.makedirs(output_dir, exist_ok=True)

    print(f"\n  Generating PDF report → {output_dir}/")
    generate_trade_report(
        trades_df   = report_df,
        output_dir  = output_dir,
        report_name = report_name,
        config_params = {
            "INITIAL_EQUITY":    INITIAL_CAPITAL,
            "WFA_SPLIT_RATIO":   0.69,        # IS ~69% / OOS ~31% — enables WFA section
            "MC_SIMULATIONS":    1000,
            "BENCHMARK_TICKER":  "QQQ",
            "RISK_FREE_RATE":    RISK_FREE_RATE,
        },
    )
    print(f"  Standalone PDF saved to: {output_dir}/")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print("=" * 62)
    print("  Momentum Rotation v2 — Standalone Backtest")
    print("=" * 62)

    all_data = load_all_data()
    qqq_df   = all_data.pop(REGIME_TICKER, None)

    if qqq_df is None:
        print("ERROR: QQQ data unavailable. Check data_provider in config.py.")
        return

    if len(all_data) < 10:
        print(f"ERROR: Only {len(all_data)} symbols loaded — too few to rank.")
        return

    rebalance_pairs = build_rebalance_pairs({**all_data, REGIME_TICKER: qqq_df})
    print(f"  {len(rebalance_pairs)} rebalance weeks built\n")

    trade_log, equity_log = run_backtest(all_data, qqq_df, rebalance_pairs)
    print_results(trade_log, equity_log)

    run_id  = datetime.now().strftime("momentum-rotation-v2_%Y-%m-%d_%H-%M-%S")
    run_dir = os.path.join("output", "runs", run_id)
    os.makedirs(run_dir, exist_ok=True)

    print(f"\n  Generating PDF tearsheet → output/runs/{run_id}/detailed_reports/")
    generate_pdf_report(pd.DataFrame(trade_log), all_data=all_data, run_dir=run_dir)

    print("\n  Done.")
    print(f"  PDF : output/runs/{run_id}/detailed_reports/Momentum_Rotation_v2.pdf")


if __name__ == "__main__":
    main()
