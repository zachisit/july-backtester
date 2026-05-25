"""
scripts/roan_arima_garch_replication.py

Verbatim replication of Roan (@RohOnChain)'s "How To Build A Time Series Model
To Win Every Single Trade (Quant Framework)" code, plus the metrics he prints
at the bottom — Sharpe and max drawdown.

His framework:
- yfinance SPY 5y daily
- log returns × 100
- Walk-forward: at each step refit ARIMA(1,0,1) on prior 252 days, then
  GARCH(1,1) on ARIMA residuals
- Signal = sign(forecast); position size = min(1.0, 1.0 / max(vol_forecast, 0.1))
- Strategy return = lagged_signal × realised return

No transaction costs, no slippage, no commission — exactly what he posted.
"""
import numpy as np
import pandas as pd
import yfinance as yf
from statsmodels.tsa.arima.model import ARIMA
from arch import arch_model
from statsmodels.tsa.stattools import adfuller
import warnings
warnings.filterwarnings('ignore')

# === HIS CLASS VERBATIM ===
class TimeSeriesTradingSystem:
    def __init__(self, ticker, period="5y"):
        self.ticker = ticker
        self.period = period

    def fetch_and_prepare(self):
        data = yf.Ticker(self.ticker).history(period=self.period)
        self.prices = data['Close']
        self.returns = np.log(self.prices / self.prices.shift(1)).dropna() * 100
        return self.returns

    def check_stationarity(self, series):
        result = adfuller(series.dropna())
        print(f"ADF Statistic: {result[0]:.4f}")
        print(f"P-value: {result[1]:.4f}")
        print(f"Stationary: {result[1] < 0.05}")
        return result[1] < 0.05

    def fit_arima_garch(self, returns, arima_order=(1, 0, 1), garch_order=(1, 1)):
        arima = ARIMA(returns, order=arima_order)
        arima_result = arima.fit()
        residuals = arima_result.resid

        garch = arch_model(residuals, vol='Garch', p=garch_order[0], q=garch_order[1])
        garch_result = garch.fit(disp='off')

        return arima_result, garch_result

    def generate_signals(self, returns, lookback=252):
        signals = []

        for i in range(lookback, len(returns)):
            window = returns.iloc[i - lookback:i]

            try:
                arima = ARIMA(window, order=(1, 0, 1)).fit()
                # NOTE: His code says `arima.forecast(steps=1)[0]` which raises
                # KeyError in current statsmodels (forecast() returns a Series
                # with integer index starting at len(window), not 0). Using
                # .iloc[0] is the obvious fix that matches his intent.
                forecast = arima.forecast(steps=1).iloc[0]

                garch = arch_model(arima.resid, vol='Garch', p=1, q=1).fit(disp='off')
                vol_forecast = np.sqrt(garch.forecast(horizon=1).variance.values[-1][0])

                signal = 1 if forecast > 0 else -1
                position_size = min(1.0, 1.0 / max(vol_forecast, 0.1))
                scaled_signal = signal * position_size

            except Exception:
                scaled_signal = 0

            signals.append({
                'date': returns.index[i],
                'signal': scaled_signal
            })

        return pd.DataFrame(signals).set_index('date')


def run(ticker="SPY", period="5y"):
    system = TimeSeriesTradingSystem(ticker, period=period)
    returns = system.fetch_and_prepare()

    print(f"\n=== {ticker} | period={period} | n_bars={len(returns)} ===")
    print("Checking stationarity of returns:")
    system.check_stationarity(returns)

    arima_result, garch_result = system.fit_arima_garch(returns)
    print(f"\nARIMA AIC: {arima_result.aic:.2f}")
    print(f"GARCH Log-likelihood: {garch_result.loglikelihood:.2f}")

    signals = system.generate_signals(returns)
    strategy_returns = signals['signal'].shift(1) * returns.loc[signals.index]

    # Drop the first NaN from .shift(1)
    strategy_returns = strategy_returns.dropna()

    sharpe = strategy_returns.mean() / strategy_returns.std() * np.sqrt(252)
    cumulative = (1 + strategy_returns / 100).cumprod()
    max_dd = ((cumulative - cumulative.cummax()) / cumulative.cummax()).min()
    total_return = cumulative.iloc[-1] - 1

    # Buy-and-hold benchmark
    bh = system.returns.loc[signals.index].dropna()
    bh_cum = (1 + bh / 100).cumprod()
    bh_sharpe = bh.mean() / bh.std() * np.sqrt(252)
    bh_total = bh_cum.iloc[-1] - 1
    bh_dd = ((bh_cum - bh_cum.cummax()) / bh_cum.cummax()).min()

    print(f"\n--- ROAN'S SYSTEM ({ticker}, {period}) ---")
    print(f"Annualized Sharpe: {sharpe:.4f}")
    print(f"Maximum Drawdown: {max_dd:.4f}")
    print(f"Total Return:     {total_return:.4f}")
    print(f"N traded days:    {len(strategy_returns)}")

    print(f"\n--- BUY & HOLD ({ticker}, {period}) ---")
    print(f"Annualized Sharpe: {bh_sharpe:.4f}")
    print(f"Maximum Drawdown: {bh_dd:.4f}")
    print(f"Total Return:     {bh_total:.4f}")

    # Signal stats
    signs = signals['signal'].apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    flip_count = (signs.diff().abs() > 0).sum()
    long_frac = (signs > 0).mean()
    print(f"\n--- SIGNAL STATS ---")
    print(f"% days long:      {long_frac:.2%}")
    print(f"Sign flips:       {flip_count} / {len(signs)} ({flip_count/len(signs):.2%})")
    print(f"Mean |position|:  {signals['signal'].abs().mean():.4f}")

    return {
        "ticker": ticker, "period": period,
        "strategy_sharpe": sharpe, "strategy_dd": max_dd, "strategy_total": total_return,
        "bh_sharpe": bh_sharpe, "bh_dd": bh_dd, "bh_total": bh_total,
        "n_days": len(strategy_returns),
        "long_frac": long_frac, "flip_pct": flip_count / len(signs),
        "strategy_returns": strategy_returns,
        "bh_returns": bh,
    }


if __name__ == "__main__":
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "SPY"
    period = sys.argv[2] if len(sys.argv) > 2 else "5y"
    run(ticker, period)
