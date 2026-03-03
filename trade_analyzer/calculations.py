# calculations.py
import traceback
from typing import Tuple, Dict, Any, Optional

import numpy as np
import pandas as pd
from tqdm import tqdm

from . import default_config as config

def calculate_sharpe_ratio(
    daily_returns: pd.Series,
    risk_free_rate: float,
    trading_days_per_year: int
) -> float:
    """
    Calculates the annualized Sharpe Ratio.
    """
    if daily_returns.empty or len(daily_returns) < 2:
        if config.VERBOSE_DEBUG: print(f"[DEBUG SHARPE] Skipping Sharpe calculation: daily_returns empty or length < 2 (Length: {len(daily_returns)})")
        return np.nan
    try:
        daily_risk_free = (1 + risk_free_rate)**(1 / trading_days_per_year) - 1
        excess_daily_returns = daily_returns - daily_risk_free
        mean_excess_return = excess_daily_returns.mean()
        std_dev_excess_return = excess_daily_returns.std()
        if pd.isna(std_dev_excess_return) or std_dev_excess_return < 1e-10:
            if config.VERBOSE_DEBUG: print(f"[DEBUG SHARPE] Std Dev is zero or NaN ({std_dev_excess_return}). Returning NaN.")
            return np.nan
        sharpe_ratio_annualized = (mean_excess_return / std_dev_excess_return) * np.sqrt(trading_days_per_year)
        if config.VERBOSE_DEBUG: print(f"[DEBUG SHARPE] Calculation: mean={mean_excess_return:.6f}, std={std_dev_excess_return:.6f}, sqrt(days)={np.sqrt(trading_days_per_year):.2f} -> Sharpe={sharpe_ratio_annualized:.2f}")
        return sharpe_ratio_annualized
    except Exception as e:
        print(f"ERROR calculating Sharpe Ratio: {e}")
        traceback.print_exc()
        return np.nan

def calculate_sortino_ratio(
    daily_returns: pd.Series,
    risk_free_rate: float,
    trading_days_per_year: int
) -> float:
    """
    Calculates the annualized Sortino Ratio.
    """
    if daily_returns.empty or len(daily_returns) < 2:
         return np.nan
    try:
        mar_daily = (1 + risk_free_rate)**(1 / trading_days_per_year) - 1
        negative_returns = daily_returns[daily_returns < mar_daily]
        if negative_returns.empty:
             avg_daily_return_check = daily_returns.mean()
             return np.inf if avg_daily_return_check > mar_daily else np.nan
        downside_diff_sq = (negative_returns - mar_daily)**2
        downside_deviation = np.sqrt(downside_diff_sq.mean())
        if downside_deviation < 1e-10:
            avg_daily_return_check = daily_returns.mean()
            return np.inf if avg_daily_return_check > mar_daily else np.nan
        avg_daily_return = daily_returns.mean()
        sortino_daily = (avg_daily_return - mar_daily) / downside_deviation
        annualized_sortino = sortino_daily * np.sqrt(trading_days_per_year)
        return annualized_sortino
    except Exception as e:
        print(f"ERROR calculating Sortino Ratio: {e}")
        traceback.print_exc()
        return np.nan

def calculate_equity_drawdown(
    equity_series: pd.Series
) -> Tuple[pd.Series, pd.Series, float, float]:
    """
    Calculates drawdown amount and percent based on an equity series.
    Returns positive magnitudes for drawdown amount and percent.
    """
    if not isinstance(equity_series, pd.Series) or equity_series.empty:
        return pd.Series(dtype=float), pd.Series(dtype=float), 0.0, 0.0
    if not pd.api.types.is_numeric_dtype(equity_series):
         print("Warning: Equity series for drawdown calculation is not numeric. Returning defaults.")
         return pd.Series(dtype=float), pd.Series(dtype=float), 0.0, 0.0
    try:
        equity_series_filled = equity_series.ffill().bfill()
        if equity_series_filled.empty or equity_series_filled.isnull().any():
             print("Warning: Equity series became empty or contains NaNs after fill for drawdown calc. Returning defaults.")
             return pd.Series(dtype=float), pd.Series(dtype=float), 0.0, 0.0
        
        running_max_equity = equity_series_filled.cummax()
        drawdown_amount = (running_max_equity - equity_series_filled).clip(lower=0)
        
        drawdown_percent = pd.Series(np.zeros(len(equity_series_filled)), index=equity_series_filled.index)
        valid_mask = running_max_equity > 1e-9 
        drawdown_percent[valid_mask] = (drawdown_amount[valid_mask] / running_max_equity[valid_mask]) * 100
        
        initial_val = equity_series_filled.iloc[0]
        if (equity_series_filled <= 1e-9).any() and initial_val > 1e-9 :
            if running_max_equity.max() > 1e-9:
                 is_at_floor = equity_series_filled <= 1e-9
                 drawdown_percent[is_at_floor & (drawdown_amount > 0) ] = 100.0
        
        drawdown_percent = drawdown_percent.clip(lower=0, upper=100.0) 
        max_dd_amount = float(drawdown_amount.max() if not drawdown_amount.empty else 0.0)
        max_dd_percent = float(drawdown_percent.max() if not drawdown_percent.empty else 0.0)
        return drawdown_amount, drawdown_percent, max_dd_amount, max_dd_percent
    except Exception as e:
        print(f"ERROR calculating equity drawdown: {e}")
        traceback.print_exc()
        return pd.Series(dtype=float), pd.Series(dtype=float), 0.0, 0.0

def calculate_drawdown_details(
    cumulative_profit_series: pd.Series,
    dates_series: pd.Series
) -> Tuple[pd.Series, pd.Series, float, float, pd.DataFrame]:
    """
    Calculates drawdown amount, percent, max values, and detailed periods based on Cum Profit.
    """
    default_return = pd.Series(dtype=float), pd.Series(dtype=float), 0.0, 0.0, pd.DataFrame()
    if not isinstance(cumulative_profit_series, pd.Series) or cumulative_profit_series.empty or len(cumulative_profit_series) < 2:
         return default_return
    if not isinstance(dates_series, pd.Series) or not pd.api.types.is_datetime64_any_dtype(dates_series):
         return default_return
    if not dates_series.index.equals(cumulative_profit_series.index):
        try:
            dates_series_aligned = dates_series.reindex(cumulative_profit_series.index)
            if dates_series_aligned.isnull().all(): return default_return
            dates_series = dates_series_aligned
        except Exception: return default_return
    if not pd.api.types.is_numeric_dtype(cumulative_profit_series):
         return default_return
    try:
        cum_profit = cumulative_profit_series.ffill().bfill()
        if cum_profit.empty or cum_profit.isnull().any(): return default_return

        running_max = cum_profit.cummax()
        drawdown_amount = (running_max - cum_profit).clip(lower=0)
        drawdown_percent = pd.Series(np.zeros(len(cum_profit)), index=cum_profit.index)
        positive_peak_mask = running_max > 1e-9
        drawdown_percent[positive_peak_mask] = (drawdown_amount[positive_peak_mask] / running_max[positive_peak_mask]) * 100
        zero_peak_loss_mask = (running_max.abs() < 1e-9) & (cum_profit < -1e-9)
        drawdown_percent[zero_peak_loss_mask] = 100.0
        drawdown_percent = drawdown_percent.clip(lower=0, upper=100.0)
        max_dd_amount = float(drawdown_amount.max() if not drawdown_amount.empty else 0.0)
        max_dd_percent = float(drawdown_percent.max() if not drawdown_percent.empty else 0.0)

        drawdown_periods = []
        peak_index_loc, peak_value = (0, cum_profit.iloc[0]) if not cum_profit.empty else (0, 0)
        trough_index_loc, trough_value = peak_index_loc, peak_value
        in_drawdown, start_index_loc = False, 0
        
        for i in range(1, len(cum_profit)):
            current_profit, current_index_loc = cum_profit.iloc[i], i
            if current_profit >= peak_value:
                if in_drawdown:
                    start_idx_label, trough_idx_label, end_idx_label = cum_profit.index[start_index_loc], cum_profit.index[trough_index_loc], cum_profit.index[current_index_loc]
                    start_date, trough_date, end_date = dates_series.get(start_idx_label, pd.NaT), dates_series.get(trough_idx_label, pd.NaT), dates_series.get(end_idx_label, pd.NaT)
                    duration_days = (end_date - start_date).days if pd.notna(start_date) and pd.notna(end_date) else np.nan
                    recovery_days = (end_date - trough_date).days if pd.notna(trough_date) and pd.notna(end_date) else np.nan
                    drawdown_periods.append({
                        'Start_Index': start_index_loc, 'Trough_Index': trough_index_loc, 'End_Index': current_index_loc,
                        'Peak_Value': peak_value, 'Trough_Value': trough_value, 'End_Value': current_profit,
                        'Start_Date': start_date, 'Trough_Date': trough_date, 'End_Date': end_date,
                        'DD_Amount': peak_value - trough_value, 'Duration_Trades': current_index_loc - start_index_loc,
                        'Recovery_Trades': current_index_loc - trough_index_loc, 'Duration_Days': duration_days, 'Recovery_Days': recovery_days
                    })
                    in_drawdown = False
                peak_index_loc, peak_value = current_index_loc, current_profit
                trough_index_loc, trough_value = current_index_loc, current_profit
            else:
                if not in_drawdown:
                    in_drawdown, start_index_loc = True, peak_index_loc
                    trough_index_loc, trough_value = current_index_loc, current_profit
                elif current_profit < trough_value:
                    trough_index_loc, trough_value = current_index_loc, current_profit
        if in_drawdown:
            end_index_loc = len(cum_profit) - 1
            start_idx_label, trough_idx_label, end_idx_label = cum_profit.index[start_index_loc], cum_profit.index[trough_index_loc], cum_profit.index[end_index_loc]
            start_date, trough_date, end_date = dates_series.get(start_idx_label, pd.NaT), dates_series.get(trough_idx_label, pd.NaT), dates_series.get(end_idx_label, pd.NaT)
            duration_days = (end_date - start_date).days if pd.notna(start_date) and pd.notna(end_date) else np.nan
            drawdown_periods.append({
                'Start_Index': start_index_loc, 'Trough_Index': trough_index_loc, 'End_Index': np.nan,
                'Peak_Value': peak_value, 'Trough_Value': trough_value, 'End_Value': cum_profit.iloc[-1],
                'Start_Date': start_date, 'Trough_Date': trough_date, 'End_Date': pd.NaT,
                'DD_Amount': peak_value - trough_value, 'Duration_Trades': end_index_loc - start_index_loc + 1,
                'Recovery_Trades': np.nan, 'Duration_Days': duration_days, 'Recovery_Days': np.nan
            })
        drawdown_periods_df = pd.DataFrame(drawdown_periods)
        if 'DD_Amount' in drawdown_periods_df:
             drawdown_periods_df = drawdown_periods_df[drawdown_periods_df['DD_Amount'] > 1e-9]
        return drawdown_amount, drawdown_percent, max_dd_amount, max_dd_percent, drawdown_periods_df
    except Exception as e:
        print(f"ERROR calculating drawdown details: {e}")
        traceback.print_exc()
        return default_return

def calculate_cagr(initial_equity: float, final_equity: float, duration_years: float) -> float:
    """Calculates Compound Annual Growth Rate."""
    if pd.isna(duration_years) or duration_years < 1e-6: return np.nan
    if pd.isna(initial_equity) or pd.isna(final_equity): return np.nan
    if initial_equity <= 1e-9: return np.nan
    if final_equity <= 1e-9 and initial_equity > 1e-9: return -1.0
    try:
        value_ratio = float(final_equity) / float(initial_equity)
        if value_ratio < 0: return np.nan
        return (value_ratio ** (1.0 / float(duration_years))) - 1.0
    except (OverflowError, ValueError, ZeroDivisionError): return np.nan

def calculate_calmar(cagr: float, max_drawdown_percent: float) -> float: # RESTORED
    """Calculates Calmar Ratio (CAGR / Max Drawdown %). Max DD should be positive magnitude."""
    if pd.isna(cagr) or pd.isna(max_drawdown_percent): return np.nan
    # max_drawdown_percent is expected as a positive value, e.g., 25.0 for 25%
    if abs(max_drawdown_percent) < 1e-9: # Drawdown is effectively zero
         if cagr > 1e-9: return np.inf
         elif cagr < -1e-9: return -np.inf
         else: return np.nan # CAGR is also zero
    try:
        # Ensure drawdown is used as its positive magnitude for the ratio
        return float(cagr) / (abs(float(max_drawdown_percent)) / 100.0)
    except (ValueError, TypeError): return np.nan

def calculate_alpha_beta(
    strategy_daily_ret: pd.Series,
    benchmark_daily_ret: pd.Series,
    risk_free_rate: float,
    trading_days_per_year: int
) -> Tuple[float, float]:
    """Calculates annualized Alpha and Beta."""
    alpha, beta = np.nan, np.nan
    if not all(isinstance(s, pd.Series) and not s.empty and len(s) >= 2 for s in [strategy_daily_ret, benchmark_daily_ret]):
        return alpha, beta
    common_index = strategy_daily_ret.index.intersection(benchmark_daily_ret.index)
    if len(common_index) < 2: return alpha, beta
    combined = pd.DataFrame({'strat': strategy_daily_ret.loc[common_index], 'bench': benchmark_daily_ret.loc[common_index]}).dropna()
    if len(combined) < 2: return alpha, beta
    strat_final, bench_final = combined['strat'], combined['bench']
    try:
        covariance_matrix = np.cov(strat_final, bench_final)
        if covariance_matrix.shape == (2, 2):
             covariance, benchmark_variance = covariance_matrix[0, 1], covariance_matrix[1, 1]
             if benchmark_variance > 1e-10:
                  beta = covariance / benchmark_variance
                  avg_strat_daily_ret = (1 + strat_final).prod() ** (1 / len(strat_final)) - 1
                  avg_bench_daily_ret = (1 + bench_final).prod() ** (1 / len(bench_final)) - 1
                  annual_strategy_ret = (1 + avg_strat_daily_ret)**trading_days_per_year - 1
                  annual_benchmark_ret = (1 + avg_bench_daily_ret)**trading_days_per_year - 1
                  alpha = annual_strategy_ret - risk_free_rate - beta * (annual_benchmark_ret - risk_free_rate)
             else: beta, alpha = np.nan, np.nan
        else: alpha, beta = np.nan, np.nan
    except Exception as e:
        print(f"ERROR calculating Alpha/Beta: {e}")
        alpha, beta = np.nan, np.nan
    return float(alpha), float(beta)

def calculate_var_cvar(profit_series: pd.Series, level: float = 0.05) -> Tuple[float, float]:
    """Calculates Value at Risk (VaR) and Conditional VaR (CVaR)."""
    if not isinstance(profit_series, pd.Series) or profit_series.empty or profit_series.isna().all(): return np.nan, np.nan
    if not pd.api.types.is_numeric_dtype(profit_series): return np.nan, np.nan
    try:
        valid_profits = profit_series.dropna()
        if len(valid_profits) < 2: return np.nan, np.nan
        var = valid_profits.quantile(level)
        cvar_data = valid_profits[valid_profits <= var]
        cvar = cvar_data.mean() if not cvar_data.empty else var
        return float(var), float(cvar)
    except Exception as e:
        print(f"ERROR calculating VaR/CVaR: {e}")
        return np.nan, np.nan

def _calculate_consecutive_streaks(win_loss_series: pd.Series) -> Tuple[int, int]: # RESTORED
    """Helper to calculate max consecutive wins and losses."""
    if not isinstance(win_loss_series, pd.Series) or win_loss_series.empty: return 0, 0
    try: win_loss_bool = win_loss_series.astype(bool)
    except Exception: return 0, 0
    win_loss_bool = win_loss_bool.fillna(False)
    max_wins, max_losses = 0, 0
    groups = win_loss_bool.ne(win_loss_bool.shift()).cumsum()
    streaks = win_loss_bool.groupby(groups).transform('size')
    win_streaks = streaks[win_loss_bool]
    if not win_streaks.empty: max_wins = win_streaks.max()
    loss_streaks = streaks[~win_loss_bool]
    if not loss_streaks.empty: max_losses = loss_streaks.max()
    return int(max_wins), int(max_losses)

def calculate_core_metrics(trades_df: pd.DataFrame) -> Dict[str, Any]:
    """Calculates core trade statistics."""
    metrics: Dict[str, Any] = {}
    if not isinstance(trades_df, pd.DataFrame) or trades_df.empty: return metrics
    try:
        metrics['total_trades'] = len(trades_df)
        profit_col = trades_df.get('Profit')
        if profit_col is None or not pd.api.types.is_numeric_dtype(profit_col):
             metrics.update({'total_profit': np.nan, 'gross_profit': np.nan, 'gross_loss': np.nan,
                             'profit_factor': np.nan, 'avg_trade_profit': np.nan,
                             'avg_win': np.nan, 'avg_loss': np.nan, 'expectancy': np.nan})
             profit_col = pd.Series(dtype=float)
        else:
             metrics['total_profit'] = profit_col.sum()
             metrics['gross_profit'] = profit_col[profit_col > 0].sum()
             metrics['gross_loss'] = profit_col[profit_col <= 0].sum()
             metrics['avg_trade_profit'] = profit_col.mean()
             gross_profit, gross_loss = metrics['gross_profit'], metrics['gross_loss']
             if pd.notna(gross_loss) and abs(gross_loss) > 1e-9:
                 metrics['profit_factor'] = abs(gross_profit / gross_loss) if pd.notna(gross_profit) else np.nan
             elif pd.notna(gross_profit) and gross_profit > 1e-9: metrics['profit_factor'] = np.inf
             else: metrics['profit_factor'] = np.nan
        win_col = trades_df.get('Win')
        if win_col is None:
            metrics.update({'win_rate': np.nan, 'avg_win': np.nan, 'avg_loss': np.nan,
                            'max_consecutive_wins': 0, 'max_consecutive_losses': 0, 'expectancy': np.nan})
        else:
             try:
                  win_bool = win_col.fillna(False).astype(bool)
                  metrics['win_rate'] = win_bool.mean()
                  wins, losses = profit_col[win_bool], profit_col[~win_bool]
                  metrics['avg_win'] = wins.mean() if not wins.empty else 0.0
                  metrics['avg_loss'] = losses.mean() if not losses.empty else 0.0
                  # THIS IS WHERE THE ERROR OCCURRED, _calculate_consecutive_streaks IS NOW DEFINED
                  max_wins, max_losses = _calculate_consecutive_streaks(win_bool)
                  metrics['max_consecutive_wins'], metrics['max_consecutive_losses'] = max_wins, max_losses
                  win_rate, avg_win, avg_loss = metrics.get('win_rate', np.nan), metrics.get('avg_win', np.nan), metrics.get('avg_loss', np.nan)
                  if pd.notna(win_rate) and pd.notna(avg_win) and pd.notna(avg_loss):
                       metrics['expectancy'] = (win_rate * avg_win) - ((1.0 - win_rate) * abs(avg_loss))
                  else: metrics['expectancy'] = np.nan
             except Exception as e_win:
                  print(f"Error processing 'Win' column for metrics: {e_win}") # Error was here
                  metrics.update({'win_rate': np.nan, 'avg_win': np.nan, 'avg_loss': np.nan,
                                  'max_consecutive_wins': 0, 'max_consecutive_losses': 0, 'expectancy': np.nan})
    except Exception as e:
        print(f"ERROR calculating core metrics: {e}")
    expected_keys = ['total_trades', 'total_profit', 'gross_profit', 'gross_loss', 'profit_factor',
                    'win_rate', 'avg_win', 'avg_loss', 'avg_trade_profit', 'max_consecutive_wins',
                    'max_consecutive_losses', 'expectancy']
    for k in expected_keys:
         if k not in metrics:
             metrics[k] = np.nan if k not in ['total_trades', 'max_consecutive_wins', 'max_consecutive_losses'] else 0
    return metrics

def calculate_rolling_metrics(
    trades_df: pd.DataFrame,
    window: int,
    trades_per_year: float,
    risk_free_rate: float
) -> pd.DataFrame:
    """Calculates rolling Profit Factor and rolling Sharpe Ratio."""
    trades_df['Rolling_PF'] = np.nan
    trades_df['Rolling_Sharpe'] = np.nan
    try:
        if not isinstance(trades_df, pd.DataFrame) or trades_df.empty: return trades_df
        required_cols = ['Profit', 'Return_Frac']
        if not all(col in trades_df.columns and pd.api.types.is_numeric_dtype(trades_df[col]) for col in required_cols):
            return trades_df
        if len(trades_df) < window: return trades_df
        window = min(window, len(trades_df))
        min_calc_periods = max(2, int(window * 0.5))
        profit_col = trades_df['Profit'].fillna(0)
        rolling_gross_wins = profit_col.where(profit_col > 0, 0).rolling(window=window, min_periods=min_calc_periods).sum()
        rolling_gross_losses = profit_col.where(profit_col <= 0, 0).rolling(window=window, min_periods=min_calc_periods).sum()
        rolling_pf = rolling_gross_wins / rolling_gross_losses.abs().replace(0, np.nan)
        rolling_pf[(rolling_gross_losses.abs() < 1e-9) & (rolling_gross_wins > 1e-9)] = np.inf
        trades_df['Rolling_PF'] = rolling_pf
        return_frac_col = trades_df['Return_Frac'].fillna(0)
        rolling_mean_ret = return_frac_col.rolling(window=window, min_periods=min_calc_periods).mean()
        rolling_std_ret = return_frac_col.rolling(window=window, min_periods=min_calc_periods).std()
        if pd.isna(trades_per_year) or trades_per_year <= 1e-6:
            trades_df['Rolling_Sharpe'] = np.nan
        else:
            annualization_factor = np.sqrt(trades_per_year)
            mar_per_trade = 0.0 # Simplified for rolling per-trade Sharpe
            rolling_sharpe = ((rolling_mean_ret - mar_per_trade) / rolling_std_ret.replace(0, np.nan)) * annualization_factor
            trades_df['Rolling_Sharpe'] = rolling_sharpe
    except Exception as e:
        print(f"ERROR calculating rolling metrics: {e}")
    return trades_df

def run_monte_carlo_simulation(
    trade_data: pd.Series,
    num_simulations: int,
    num_trades_per_sim: int,
    initial_equity: float,
    duration_years: float,
    use_percentage_returns: bool = False,
    drawdown_as_negative: bool = False
) -> dict:
    results = {}
    if not isinstance(trade_data, pd.Series) or trade_data.empty or num_trades_per_sim < 1 or num_simulations < 1:
        print("MC Warning: Insufficient data or invalid parameters. Skipping simulation.")
        return results
    if initial_equity <= 0: # Changed from 1e-6 to 0, as ruin will be handled
         print("MC Warning: Initial equity must be strictly positive. Skipping simulation.")
         return results

    trade_values = trade_data.dropna().to_numpy()
    if len(trade_values) == 0:
         print("MC Warning: No valid trade values after dropping NaNs. Skipping.")
         return results

    all_equity_paths_list = []
    final_equities = np.zeros(num_simulations)
    max_dd_percentages = np.zeros(num_simulations)
    max_dd_amounts = np.zeros(num_simulations)
    cagrs = np.full(num_simulations, np.nan)
    lowest_equities = np.zeros(num_simulations)
    percentiles_to_calculate = config.MC_PERCENTILES

    for i in tqdm(range(num_simulations), desc="MC Simulations"):
        sampled_trades = np.random.choice(trade_values, size=num_trades_per_sim, replace=True)
        equity_path = np.zeros(num_trades_per_sim + 1)
        equity_path[0] = initial_equity
        current_equity = initial_equity
        lowest_equity_run = initial_equity
        path_ruined = False

        for j in range(num_trades_per_sim):
            if path_ruined: # If path is ruined, equity stays at 0 for remaining trades
                equity_path[j+1] = 0
                # lowest_equity_run is already 0 if path_ruined
                continue

            previous_equity_for_dd_calc = current_equity # For per-trade DD if needed

            if use_percentage_returns:
                # Ensure trade_data for % returns is e.g. 5.0 for 5%
                trade_return_fractional = sampled_trades[j] / 100.0
                current_equity *= (1 + trade_return_fractional)
            else: # Use $ profits
                current_equity += sampled_trades[j]

            if current_equity <= 0: # Check for ruin
                current_equity = 0
                lowest_equity_run = 0
                path_ruined = True
                equity_path[j+1] = 0 # Record ruin
                # Fill the rest of the path with 0 if ruined mid-way
                # This ensures the equity_path_series used for drawdown reflects this.
                for k_fill in range(j + 2, num_trades_per_sim + 1):
                    equity_path[k_fill] = 0
                break # Stop processing further trades for this ruined path
            else:
                equity_path[j+1] = current_equity
                lowest_equity_run = min(lowest_equity_run, current_equity)
        
        # If path wasn't ruined mid-loop but ended at <=0 (e.g. last trade caused ruin)
        if not path_ruined and current_equity <= 0:
            lowest_equity_run = min(lowest_equity_run, 0) # Ensure lowest can be 0
            # Final equity will be current_equity (<=0), which calculate_cagr handles for -100%

        all_equity_paths_list.append(equity_path)
        equity_path_series = pd.Series(equity_path) # This series now reflects early termination at $0 if ruined

        # Final equity for the path
        final_equity_path = equity_path_series.iloc[-1] # This will be 0 if path was ruined
        final_equities[i] = final_equity_path

        # Drawdown calculation on the potentially terminated path
        # calculate_equity_drawdown should handle paths that go to 0 correctly
        _, _, max_dd_amt_val, max_dd_pct_val = calculate_equity_drawdown(equity_path_series)

        max_dd_amounts[i] = -max_dd_amt_val if drawdown_as_negative else max_dd_amt_val
        # If path ruined, max_dd_pct_val should be 100% if initial equity was > 0 and peak was >0
        # The calculate_equity_drawdown function aims to return 100% if equity goes to 0 from a positive peak.
        max_dd_percentages[i] = -max_dd_pct_val if drawdown_as_negative else max_dd_pct_val
        
        lowest_equities[i] = lowest_equity_run # lowest_equity_run correctly captures 0 if ruined

        # CAGR calculation
        if final_equity_path <= 0 and initial_equity > 0: # Explicitly ruined or ended at zero/negative
            cagrs[i] = -1.0
        else:
            cagrs[i] = calculate_cagr(initial_equity, final_equity_path, duration_years)

    # ... (rest of the function: DataFrame conversion, percentile calculations, etc. remains the same) ...
    # Ensure that the metrics_to_analyze part correctly processes the potentially new distribution from ruin handling

    results['simulated_equity_paths'] = pd.DataFrame(all_equity_paths_list).T
    results['simulated_equity_paths'].columns = [f'Sim_{k+1}' for k in range(num_simulations)]
    results['final_equities'] = pd.Series(final_equities)
    results['max_drawdown_amounts'] = pd.Series(max_dd_amounts)
    results['max_drawdown_percentages'] = pd.Series(max_dd_percentages)
    results['lowest_equities'] = pd.Series(lowest_equities)
    results['cagrs'] = pd.Series(cagrs)

    detailed_stats = {}
    metrics_to_analyze = {'Final Equity': results['final_equities'], 'CAGR': results['cagrs'],
                        'Max Drawdown $': results['max_drawdown_amounts'],
                        'Max Drawdown %': results['max_drawdown_percentages'],
                        'Lowest Equity': results['lowest_equities']}
    for name, data_series in metrics_to_analyze.items():
        data_clean = data_series.dropna() # NaNs from CAGR calc if initial_equity was 0, or if duration was 0.
                                        # Should not have NaNs from sim if initial_equity > 0.
        # Ensure data_clean has enough points for percentile calculation
        if data_clean.empty or len(data_clean) < (100 / (100 - max(percentiles_to_calculate))) or len(data_clean) < (100 / min(percentiles_to_calculate)): # Heuristic for robust percentiles
            if config.VERBOSE_DEBUG or len(data_clean) < 2: print(f"MC Warning: Metric '{name}' has insufficient valid data ({len(data_clean)}) for robust percentile calculation. Using NaNs.")
            metric_percentiles = {f"{p}th": np.nan for p in percentiles_to_calculate}
        else:
            try:
                 # Filter out non-finite values that might arise from extreme calculations
                 if not np.all(np.isfinite(data_clean)):
                      if config.VERBOSE_DEBUG: print(f"MC Warning: Non-finite values found in MC metric '{name}' before percentile calc. Filtering.")
                      data_clean = data_clean[np.isfinite(data_clean)]
                 
                 if data_clean.empty or len(data_clean) < 2: # Re-check after filtering
                      if config.VERBOSE_DEBUG: print(f"MC Warning: Metric '{name}' has insufficient finite data after filtering for percentile calculation.")
                      metric_percentiles = {f"{p}th": np.nan for p in percentiles_to_calculate}
                 else:
                      calculated_p = np.percentile(data_clean, percentiles_to_calculate)
                      metric_percentiles = {f"{p}th": float(val) for p, val in zip(percentiles_to_calculate, calculated_p)}
            except Exception as p_err:
                 print(f"ERROR calculating percentiles for {name}: {p_err}")
                 traceback.print_exc()
                 metric_percentiles = {f"{p}th": np.nan for p in percentiles_to_calculate}
        detailed_stats[name] = metric_percentiles
    results['mc_detailed_percentiles'] = detailed_stats

    basic_stats = {}
    # Basic stats (Avg, Median, 5th, 95th) - ensure these are robust too
    # Using fixed percentiles [5, 95] for this summary
    summary_percentiles = [5, 50, 95] # Median is 50th
    summary_percentile_labels = {5: '5th Percentile', 50: 'Median', 95: '95th Percentile'}

    for name, data_series in metrics_to_analyze.items():
        data_clean = data_series.dropna()
        current_metric_stats = {'Average': np.nan, 'Median': np.nan, '5th Percentile': np.nan, '95th Percentile': np.nan}
        if not data_clean.empty:
            try:
                if not np.all(np.isfinite(data_clean)): # Filter non-finite
                    data_clean = data_clean[np.isfinite(data_clean)]
                
                if not data_clean.empty:
                    current_metric_stats['Average'] = float(data_clean.mean())
                    # Calculate summary percentiles
                    if len(data_clean) >= 2: # Need at least 2 points for percentile
                        p_values = np.percentile(data_clean, summary_percentiles)
                        for p, val in zip(summary_percentiles, p_values):
                            current_metric_stats[summary_percentile_labels[p]] = float(val)
                    else: # Not enough data for percentiles after cleaning
                        if config.VERBOSE_DEBUG: print(f"MC Warning: Not enough finite data for summary percentiles for '{name}'")

            except Exception as bs_err:
                  print(f"ERROR calculating basic stats for {name}: {bs_err}")
                  traceback.print_exc() # Keep for debugging
        basic_stats[name] = current_metric_stats
    results['mc_summary_statistics'] = basic_stats
    
    return results