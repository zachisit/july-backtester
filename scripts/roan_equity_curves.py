"""
scripts/roan_equity_curves.py

Re-runs Roan's signal generator on a list of tickers and plots strategy
equity curves vs buy-and-hold. Outputs one PNG per ticker x period, plus
a grid summary PNG.

Usage:
    python scripts/roan_equity_curves.py --tickers SPY,QQQ,AAPL --period 5y --cost_bps 5
"""
import argparse
import os
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from statsmodels.tsa.arima.model import ARIMA
from arch import arch_model
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
warnings.filterwarnings('ignore')


def fetch_returns(ticker, period):
    data = yf.Ticker(ticker).history(period=period)
    if data.empty:
        return None
    prices = data['Close']
    return (np.log(prices / prices.shift(1)) * 100).dropna()


def signals(returns, lookback=252):
    sigs = []
    for i in range(lookback, len(returns)):
        window = returns.iloc[i - lookback:i]
        try:
            arima = ARIMA(window, order=(1, 0, 1)).fit()
            f = arima.forecast(steps=1).iloc[0]
            garch = arch_model(arima.resid, vol='Garch', p=1, q=1).fit(disp='off')
            vol = float(np.sqrt(garch.forecast(horizon=1).variance.values[-1][0]))
            sgn = 1 if f > 0 else -1
            size = min(1.0, 1.0 / max(vol, 0.1))
            scaled = sgn * size
        except Exception:
            scaled = 0.0
        sigs.append({'date': returns.index[i], 'signal': scaled})
    return pd.DataFrame(sigs).set_index('date')


def run_and_plot(ticker, period, cost_bps, outdir):
    returns = fetch_returns(ticker, period)
    if returns is None or len(returns) < 300:
        print(f"SKIP {ticker}/{period}: insufficient data")
        return None
    sigs = signals(returns)
    pos = sigs['signal']
    realised = returns.loc[sigs.index]
    gross = (pos.shift(1) * realised).dropna()
    pos_change = pos.shift(1).diff().abs().fillna(0)
    cost_pct = pos_change * (cost_bps / 100.0)
    net = gross - cost_pct.loc[gross.index]
    bh = realised.loc[gross.index]

    strat_cum = (1 + net / 100).cumprod()
    gross_cum = (1 + gross / 100).cumprod()
    bh_cum = (1 + bh / 100).cumprod()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(bh_cum.index, bh_cum.values, label=f"Buy & Hold {ticker}", lw=2, color="#0072B2")
    ax.plot(gross_cum.index, gross_cum.values, label="Roan strategy (no cost)", lw=1.5, color="#D55E00", ls="--")
    ax.plot(strat_cum.index, strat_cum.values, label=f"Roan strategy ({cost_bps:g}bps cost)", lw=2, color="#D55E00")
    ax.set_title(f"{ticker} — {period} — Roan ARIMA(1,0,1)+GARCH(1,1) vs Buy & Hold")
    ax.set_ylabel("Equity (×)")
    ax.set_xlabel("Date")
    ax.legend(loc="upper left")
    ax.grid(alpha=0.3)
    ax.axhline(1.0, color="black", lw=0.5)
    plt.tight_layout()
    path = os.path.join(outdir, f"{ticker}_{period}_eq.png")
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"Wrote {path}")
    return path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", default="SPY,QQQ")
    p.add_argument("--period", default="5y")
    p.add_argument("--cost_bps", type=float, default=5.0)
    p.add_argument("--outdir", default="output/roan_charts")
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    for t in args.tickers.split(","):
        run_and_plot(t.strip(), args.period, args.cost_bps, args.outdir)


if __name__ == "__main__":
    main()
