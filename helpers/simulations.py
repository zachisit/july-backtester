# helpers/simulations.py

import pandas as pd
import numpy as np
from config import CONFIG

def calculate_advanced_metrics(pnl_list, portfolio_timeline, duration_list):
    metrics = {"max_drawdown": 0, "profit_factor": 0, "win_rate": 0, "sharpe_ratio": 0, "calmar_ratio": 0, "avg_trade_duration": 0}
    if not pnl_list: return metrics
    
    wins = [p for p in pnl_list if p > 0]
    losses = [p for p in pnl_list if p < 0]
    
    metrics["win_rate"] = len(wins) / len(pnl_list) if pnl_list else 0
    metrics["profit_factor"] = sum(wins) / abs(sum(losses)) if losses else np.inf
    
    if duration_list:
        metrics["avg_trade_duration"] = np.mean(duration_list)

    if not portfolio_timeline.empty and len(portfolio_timeline) > 1:
        daily_returns = portfolio_timeline.pct_change().dropna()
        if len(daily_returns) > 1:
            rf_daily = (1 + CONFIG.get("risk_free_rate", 0.05)) ** (1 / 252) - 1
            excess_returns = daily_returns - rf_daily
            metrics["sharpe_ratio"] = (excess_returns.mean() / excess_returns.std()) * np.sqrt(252) if excess_returns.std() > 0 else 0
        
        running_peak = portfolio_timeline.expanding(min_periods=1).max()
        drawdown = (portfolio_timeline - running_peak) / running_peak
        metrics["max_drawdown"] = abs(drawdown.min())
        
        duration_years = (portfolio_timeline.index[-1] - portfolio_timeline.index[0]).days / 365.25
        if duration_years > 0:
            annual_return = (portfolio_timeline.iloc[-1] / portfolio_timeline.iloc[0]) ** (1 / duration_years) - 1
            metrics["calmar_ratio"] = annual_return / metrics["max_drawdown"] if metrics["max_drawdown"] > 0 else np.inf
            
    return metrics