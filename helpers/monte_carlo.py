# helpers/monte_carlo.py

import pandas as pd
import numpy as np
from tqdm import tqdm

def run_monte_carlo_simulation(trade_pnl_list, initial_equity, num_simulations=1000):
    """
    Runs a Monte Carlo simulation on a list of trade P&L values.
    """
    if not isinstance(trade_pnl_list, list) or len(trade_pnl_list) < 5:
        return None

    trade_pnl_array = np.array(trade_pnl_list)
    num_trades = len(trade_pnl_array)
    
    final_equities = np.zeros(num_simulations)
    max_drawdowns = np.zeros(num_simulations)

    for i in range(num_simulations):
        sampled_trades = np.random.choice(trade_pnl_array, size=num_trades, replace=True)
        equity_path = np.concatenate(([initial_equity], initial_equity + np.cumsum(sampled_trades)))
        
        running_max = np.maximum.accumulate(equity_path)
        valid_mask = running_max > 1e-9
        drawdown = np.zeros_like(running_max)
        if np.any(valid_mask):
            drawdown[valid_mask] = (running_max[valid_mask] - equity_path[valid_mask]) / running_max[valid_mask]
        
        max_drawdowns[i] = np.max(drawdown)
        final_equities[i] = equity_path[-1]

    return {
        "final_equities": final_equities,
        "max_drawdowns": max_drawdowns
    }

def analyze_mc_results(historical_metrics, mc_results):
    """
    FINAL CORRECTED VERSION: Analyzes Monte Carlo results against historical performance.
    This version ensures the scoring logic is robust and matches manual analysis.
    """
    if mc_results is None:
        return {"mc_verdict": "N/A (Low Trades)", "mc_score": 0}

    mc_5th_pnl = np.percentile(mc_results['final_equities'], 5) - historical_metrics['initial_capital']
    mc_median_dd = np.percentile(mc_results['max_drawdowns'], 50)
    mc_95th_dd = np.percentile(mc_results['max_drawdowns'], 95)

    historical_pnl = historical_metrics['pnl_percent'] * historical_metrics['initial_capital']
    historical_dd = historical_metrics['max_drawdown']

    # --- REVISED SCORING LOGIC ---
    score = 0
    verdicts = []

    # 1. Performance Robustness Test
    if historical_pnl >= mc_5th_pnl:
        score += 2
    else:
        score -= 1
        verdicts.append("Perf. Outlier")
    
    # 2. Drawdown Realism Test
    if historical_dd >= mc_median_dd:
        # Historical DD was worse than or equal to the median, which is a good sign of realism
        score += 1
    else:
        # Historical DD was better than the median, which is a warning sign of being lucky
        score -= 1
        verdicts.append("DD Understated")

    # 3. Tail Risk Test
    if mc_95th_dd < 0.50:
        score += 2 # Worst-case scenarios are manageable
    elif mc_95th_dd < 0.80:
        score -= 1 # Worst-case scenarios show moderate risk
        verdicts.append("Moderate Tail Risk")
    else: # mc_95th_dd >= 0.80
        score -= 2 # Worst-case scenarios show high risk of ruin
        verdicts.append("High Tail Risk")

    # Final Verdict String
    if not verdicts:
        verdict_str = "Robust"
    else:
        verdict_str = ", ".join(verdicts)

    return {"mc_verdict": verdict_str, "mc_score": score}
