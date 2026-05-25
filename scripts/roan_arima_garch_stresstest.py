"""
scripts/roan_arima_garch_stresstest.py

Multi-ticker, multi-window stress test of Roan's ARIMA(1,0,1)+GARCH(1,1) system.

Adds:
- Transaction cost knob (default 5 bps round-trip, applied whenever signed
  position changes — i.e. flip from long to short pays full cost on the
  abs(delta_position) leg)
- Buy-and-hold benchmark comparison
- Aggregate CSV output for the receipts table

Usage:
    python scripts/roan_arima_garch_stresstest.py --tickers SPY,QQQ,AAPL --periods 5y,10y --cost_bps 5
"""
import argparse
import sys
import os
import time
import json
import numpy as np
import pandas as pd
import yfinance as yf
from statsmodels.tsa.arima.model import ARIMA
from arch import arch_model
from statsmodels.tsa.stattools import adfuller
import warnings
warnings.filterwarnings('ignore')


def fetch_returns(ticker, period):
    data = yf.Ticker(ticker).history(period=period)
    if data.empty:
        return None, None
    prices = data['Close']
    returns = (np.log(prices / prices.shift(1)) * 100).dropna()
    return prices, returns


def generate_signals(returns, lookback=252):
    """Roan's exact signal generator."""
    sigs = []
    for i in range(lookback, len(returns)):
        window = returns.iloc[i - lookback:i]
        try:
            arima = ARIMA(window, order=(1, 0, 1)).fit()
            forecast = arima.forecast(steps=1).iloc[0]  # his [0] raises KeyError on modern statsmodels
            garch = arch_model(arima.resid, vol='Garch', p=1, q=1).fit(disp='off')
            vol_forecast = float(np.sqrt(garch.forecast(horizon=1).variance.values[-1][0]))
            signal = 1 if forecast > 0 else -1
            position_size = min(1.0, 1.0 / max(vol_forecast, 0.1))
            scaled = signal * position_size
        except Exception:
            scaled = 0.0
        sigs.append({'date': returns.index[i], 'signal': scaled})
    return pd.DataFrame(sigs).set_index('date')


def run_one(ticker, period, cost_bps=5.0, lookback=252):
    t0 = time.time()
    prices, returns = fetch_returns(ticker, period)
    if returns is None or len(returns) < lookback + 50:
        return None

    sigs = generate_signals(returns, lookback=lookback)
    pos = sigs['signal']
    realised = returns.loc[sigs.index]

    # Strategy returns: lagged position × realised return (Roan's formula)
    gross = (pos.shift(1) * realised).dropna()

    # Cost model: apply cost_bps × |Δposition| each day a flip/resize happens.
    # cost_bps is per UNIT of position change (i.e. 5 bps == 0.05% on a full
    # 1-unit position change).
    pos_change = pos.shift(1).diff().abs().fillna(0)
    cost_pct = pos_change * (cost_bps / 100.0)  # convert bps→%
    net = gross - cost_pct.loc[gross.index]

    # Buy & hold over same window
    bh = realised.loc[gross.index]
    bh_cum = (1 + bh / 100).cumprod()
    bh_sharpe = bh.mean() / bh.std() * np.sqrt(252) if bh.std() > 0 else 0.0
    bh_total = bh_cum.iloc[-1] - 1
    bh_dd = ((bh_cum - bh_cum.cummax()) / bh_cum.cummax()).min()

    def metrics(rets):
        cum = (1 + rets / 100).cumprod()
        sharpe = rets.mean() / rets.std() * np.sqrt(252) if rets.std() > 0 else 0.0
        total = cum.iloc[-1] - 1
        dd = ((cum - cum.cummax()) / cum.cummax()).min()
        return sharpe, total, dd

    gross_sharpe, gross_total, gross_dd = metrics(gross)
    net_sharpe, net_total, net_dd = metrics(net)

    long_frac = (pos > 0).mean()
    short_frac = (pos < 0).mean()
    flip_pct = (np.sign(pos).diff().abs() > 0).sum() / len(pos)
    mean_abs_pos = pos.abs().mean()

    return {
        "ticker": ticker,
        "period": period,
        "n_days": len(gross),
        "lookback": lookback,
        "cost_bps": cost_bps,
        "gross_sharpe": gross_sharpe,
        "gross_total": gross_total,
        "gross_dd": gross_dd,
        "net_sharpe": net_sharpe,
        "net_total": net_total,
        "net_dd": net_dd,
        "bh_sharpe": bh_sharpe,
        "bh_total": bh_total,
        "bh_dd": bh_dd,
        "long_frac": long_frac,
        "short_frac": short_frac,
        "flip_pct": flip_pct,
        "mean_abs_pos": mean_abs_pos,
        "elapsed_s": round(time.time() - t0, 1),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", default="SPY,QQQ,AAPL,NVDA,GLD,TLT")
    p.add_argument("--periods", default="5y,10y")
    p.add_argument("--cost_bps", type=float, default=5.0,
                   help="One-way cost in bps per UNIT of position change")
    p.add_argument("--out", default="output/roan_stresstest_results.csv")
    args = p.parse_args()

    tickers = args.tickers.split(",")
    periods = args.periods.split(",")

    rows = []
    for ticker in tickers:
        for period in periods:
            print(f"\n=== {ticker} | {period} ===", flush=True)
            try:
                r = run_one(ticker, period, cost_bps=args.cost_bps)
            except Exception as e:
                print(f"FAILED: {e}")
                continue
            if r is None:
                print("SKIPPED (insufficient data)")
                continue
            print(json.dumps(r, default=float, indent=2))
            rows.append(r)

    if not rows:
        print("\nNo rows produced.")
        sys.exit(1)

    df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    df.to_csv(args.out, index=False)
    print(f"\nWrote {len(df)} rows to {args.out}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
