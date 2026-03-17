# helpers/monte_carlo.py

import pandas as pd
import numpy as np
from tqdm import tqdm
from config import CONFIG


def _equity_and_drawdown(sampled_trades, initial_equity):
    """Compute final equity and max drawdown for a single simulated path."""
    equity_path = np.concatenate(([initial_equity], initial_equity + np.cumsum(sampled_trades)))
    running_max = np.maximum.accumulate(equity_path)
    valid_mask = running_max > 1e-9
    drawdown = np.zeros_like(running_max)
    if np.any(valid_mask):
        drawdown[valid_mask] = (running_max[valid_mask] - equity_path[valid_mask]) / running_max[valid_mask]
    return equity_path[-1], np.max(drawdown)


def run_monte_carlo_simulation(trade_pnl_list, initial_equity, num_simulations=1000):
    """
    Runs a Monte Carlo simulation on a list of trade P&L values.

    Sampling method is controlled by CONFIG["mc_sampling"]:
      "iid"   — i.i.d. resampling (default). Fast; ignores autocorrelation.
      "block" — block-bootstrap. Samples consecutive blocks of trades,
                preserving win/loss streaks and regime clustering.
                Block size is CONFIG["mc_block_size"] or auto (sqrt of N).
    """
    if not isinstance(trade_pnl_list, list) or len(trade_pnl_list) < 5:
        return None

    trade_pnl_array = np.array(trade_pnl_list)
    num_trades = len(trade_pnl_array)

    final_equities = np.zeros(num_simulations)
    max_drawdowns = np.zeros(num_simulations)

    sampling = CONFIG.get("mc_sampling", "iid")

    if sampling == "block":
        block_size = CONFIG.get("mc_block_size") or max(1, int(num_trades ** 0.5))
        for i in range(num_simulations):
            n_blocks = int(np.ceil(num_trades / block_size))
            starts = np.random.randint(0, num_trades, size=n_blocks)
            sampled = np.concatenate([
                np.take(trade_pnl_array, range(s, s + block_size), mode='wrap')
                for s in starts
            ])[:num_trades]
            final_equities[i], max_drawdowns[i] = _equity_and_drawdown(sampled, initial_equity)
    else:
        # i.i.d. path — identical to the original implementation
        for i in range(num_simulations):
            sampled_trades = np.random.choice(trade_pnl_array, size=num_trades, replace=True)
            final_equities[i], max_drawdowns[i] = _equity_and_drawdown(sampled_trades, initial_equity)

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
