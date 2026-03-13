import pandas as pd
import numpy as np
from config import CONFIG
from .simulations import calculate_advanced_metrics

def run_portfolio_simulation(portfolio_data, signals, initial_capital, allocation_pct, spy_df, vix_df, tnx_df, stop_config):
    """
    Runs a portfolio simulation with integrated stop-loss handling and logs 
    a rich set of features for each trade for future machine learning analysis.
    (Version hardened against KeyError from misaligned dates).
    """
    execution_time = CONFIG.get("execution_time", "open").lower()
    
    cash = initial_capital
    positions = {}
    all_dates = sorted(list(set(date for df in portfolio_data.values() for date in df.index)))
    portfolio_timeline = pd.Series(index=all_dates, dtype=float)
    trade_log = []
    trade_counter = 0
    cumulative_profit = 0.0

    prev_trading_dates = { symbol: df.index.to_series().shift(1) for symbol, df in portfolio_data.items() }

    for date in portfolio_timeline.index:
        # --- EQUITY CALCULATION ---
        current_market_value = 0.0
        for symbol, pos in positions.items():
            # <-- NEW CHECK: Make sure the date exists for this symbol before getting its price
            if date in portfolio_data[symbol].index:
                close_price = portfolio_data[symbol].loc[date]['Close']
                if pd.notna(close_price):
                    current_market_value += pos['shares'] * close_price
            else:
                # If date doesn't exist, use the last known price for a more stable equity curve
                # This is an edge case, but good practice.
                last_valid_date = portfolio_data[symbol].index[portfolio_data[symbol].index < date][-1]
                close_price = portfolio_data[symbol].loc[last_valid_date]['Close']
                current_market_value += pos['shares'] * close_price

        total_equity = cash + current_market_value
        portfolio_timeline[date] = total_equity

        # --- POSITION MANAGEMENT (EXITS) ---
        exited_symbols = []
        for symbol, pos in list(positions.items()):
            # <-- NEW CHECK: The most important check. If the current date doesn't exist for this stock,
            # we can't possibly check for signals or get prices. Skip to the next stock.
            if date not in portfolio_data[symbol].index:
                continue

            raw_exit_price, exit_date, exit_reason = np.nan, pd.NaT, "Strategy Exit"
            
            # --- STOP-LOSS CHECK ---
            if stop_config.get("type") != "none" and pd.notna(pos.get('stop_loss_level')):
                current_low = portfolio_data[symbol].loc[date].get('Low')
                if pd.notna(current_low) and current_low <= pos['stop_loss_level']:
                    raw_exit_price = pos['stop_loss_level']
                    exit_date = date
                    exit_reason = f"Stop Loss ({stop_config['type']})"

            # --- STRATEGY-BASED EXIT ---
            if pd.isna(raw_exit_price):
                signal_date_to_check = prev_trading_dates[symbol].get(date) if execution_time == 'open' else date
                if pd.notna(signal_date_to_check) and signal_date_to_check in signals[symbol].index:
                    signal_value = signals[symbol].loc[signal_date_to_check]
                    if signal_value < 0:
                        raw_exit_price = portfolio_data[symbol].loc[date].get('Open' if execution_time == 'open' else 'Close')
                        exit_date = date
            
            # --- TRAIL THE STOP AND CONTINUE IF NOT EXITING ---
            if pd.isna(raw_exit_price):
                if stop_config.get("type") == "atr" and pd.notna(pos.get('stop_loss_level')):
                    current_close = portfolio_data[symbol].loc[date].get('Close')
                    current_atr = portfolio_data[symbol].loc[date].get('ATR') 
                    if pd.notna(current_close) and pd.notna(current_atr):
                        new_stop_level = current_close - (current_atr * stop_config.get("multiplier", 3.0))
                        pos['stop_loss_level'] = max(pos['stop_loss_level'], new_stop_level)
                continue

            # --- TRADE EXIT AND LOGGING LOGIC ---
            trade_df = portfolio_data[symbol].loc[pos['entry_date']:exit_date]
            mae_pct, mfe_pct = 0.0, 0.0
            if not trade_df.empty:
                lowest_price = trade_df['Low'].min()
                mae_pct = (lowest_price - pos['entry_price']) / pos['entry_price']
                highest_price = trade_df['High'].max()
                mfe_pct = (highest_price - pos['entry_price']) / pos['entry_price']
                
            trade_counter += 1
            exit_price = raw_exit_price * (1 - CONFIG['slippage_pct'])
            commission = pos['shares'] * CONFIG['commission_per_share']
            cash += (pos['shares'] * exit_price) - commission
            net_pnl = ((exit_price - pos['entry_price']) * pos['shares']) - (2 * commission)
            cumulative_profit += net_pnl
            duration = (exit_date - pos['entry_date']).days
            position_value = pos['shares'] * pos['entry_price']

            # --- Initial Risk and R-Multiple ---
            _initial_sl = pos.get('initial_stop_loss_level')
            if pd.notna(_initial_sl) and _initial_sl > 0 and _initial_sl < pos['entry_price']:
                _initial_risk_per_share = pos['entry_price'] - _initial_sl
            else:
                _initial_risk_per_share = pos['entry_price'] * 0.01
            _r_multiple = (net_pnl / (_initial_risk_per_share * pos['shares'])
                           if _initial_risk_per_share > 0 and pos['shares'] > 0 else None)

            log_entry = {
                'Symbol': symbol, 'Trade': f"Long {trade_counter}",
                'EntryDate': pos['entry_date'].strftime('%Y-%m-%d'), 'EntryPrice': pos['entry_price'],
                'ExitDate': exit_date.strftime('%Y-%m-%d'), 'ExitPrice': exit_price,
                'Profit': net_pnl, 'ProfitPct': net_pnl / position_value if position_value > 0 else 0,
                'is_win': 1 if net_pnl > 0 else 0,
                'HoldDuration': duration,
                'MAE_pct': mae_pct, 'MFE_pct': mfe_pct,
                'ExitReason': exit_reason,
                'InitialRisk': _initial_risk_per_share,
                'RMultiple': _r_multiple,
            }
            log_entry.update(pos.get('features', {}))
            trade_log.append(log_entry)
            exited_symbols.append(symbol)

        for symbol in exited_symbols: del positions[symbol]
        
        # --- POSITION ENTRY LOGIC ---
        for symbol, df in portfolio_data.items():
            # <-- NEW CHECK: If the current date doesn't exist for this stock,
            # we cannot possibly enter a position.
            if date not in df.index:
                continue

            if symbol in positions: continue
            raw_entry_price, entry_exec_date = np.nan, pd.NaT
            signal_date = prev_trading_dates[symbol].get(date) if execution_time == 'open' else date
            if pd.notna(signal_date) and signal_date in signals[symbol].index and signals[symbol].loc[signal_date] == 1:
                raw_entry_price = df.loc[date].get('Open' if execution_time == 'open' else 'Close')
                entry_exec_date = date

            if pd.isna(raw_entry_price): continue
            
            entry_price = raw_entry_price * (1 + CONFIG['slippage_pct'])
            
            # Determine max capital to allocate for this single trade
            capital_to_allocate = total_equity * allocation_pct
            
            # You cannot allocate more for the principal than your available cash
            capital_to_allocate = min(capital_to_allocate, cash)
            
            if entry_price > 0 and capital_to_allocate > 0:
                # Calculate ideal shares based on the capital allocation
                shares = capital_to_allocate / entry_price
                
                # Calculate the total cost including commission for this ideal share size
                commission_cost = shares * CONFIG['commission_per_share']
                total_cost = (shares * entry_price) + commission_cost

                # If the total cost is more than our available cash, we must reduce the share size.
                # This can happen if cash is low and commission pushes us over the limit.
                if total_cost > cash:
                    # Robustly calculate the absolute maximum number of shares we can possibly afford
                    shares = cash / (entry_price + CONFIG['commission_per_share'])
                    if shares <= 0: continue # Cannot afford even a fraction of a share
                    # Recalculate final total cost with the affordable share size
                    total_cost = (shares * entry_price) + (shares * CONFIG['commission_per_share'])

                # Final check: Ensure we can afford the trade and it's a meaningful size
                if cash >= total_cost and shares > 0.001: 
                    # --- CAPTURE FEATURES AT ENTRY ---
                    features = {}
                    try:
                        features['entry_RSI_14'] = df.loc[entry_exec_date, 'RSI_14']
                        features['entry_ATR_14_pct'] = df.loc[entry_exec_date, 'ATR_14_pct']
                        features['entry_SMA200_dist_pct'] = df.loc[entry_exec_date, 'SMA200_dist_pct']
                        features['entry_Volume_Spike'] = df.loc[entry_exec_date, 'Volume_Spike']
                        features['entry_SPY_RSI_14'] = spy_df.loc[entry_exec_date, 'RSI_14']
                        features['entry_SPY_SMA200_dist_pct'] = spy_df.loc[entry_exec_date, 'SMA200_dist_pct']
                        features['entry_VIX_Close'] = vix_df.loc[entry_exec_date, 'Close']
                        if tnx_df is not None:
                            features['entry_TNX_Close'] = tnx_df.loc[entry_exec_date, 'Close']
                    except KeyError:
                        pass
                    
                    # --- STRATEGIC DECISION: ATR TRAILING STOP CALCULATION METHOD ---
                    #
                    # This system implements a "Next Day Activation" model for ATR trailing stops,
                    # which aligns with a realistic, end-of-day trading workflow. This is a deliberate
                    # choice over other interpretations.
                    #
                    # INTERPRETATION A (The Implemented Logic):
                    #   - PURPOSE: To model a trader who analyzes the market after the close and sets
                    #     orders for the NEXT trading session. It strictly avoids look-ahead bias.
                    #   - INITIAL STOP: Calculated using the CLOSE and ATR from the day BEFORE entry (the signal day).
                    #     This value becomes the active stop for the entire entry day.
                    #   - TRAILING STOP: The active stop for any given day (Day D) is the value that was
                    #     calculated at the close of the PREVIOUS day (Day D-1). A new potential stop is
                    #     calculated at the close of Day D, which will then become active on Day D+1.
                    #   - CHECK: The Low of Day D is compared against the stop calculated on Day D-1.
                    #
                    # INTERPRETATION B (Alternative, Not Used Here):
                    #   - LOGIC: The stop is calculated and updated using the current day's data
                    #     (e.g., `entry_price - (ATR_on_entry_day * multiplier)`).
                    #   - REASON FOR REJECTION: While this simulates setting a stop immediately after a
                    #     fill, it introduces a slight look-ahead bias in a daily-bar backtest, as
                    #     the full day's ATR (which depends on the day's High and Low) would not be
                    #     known at the market open. Interpretation A is a more conservative and
                    #     academically rigorous approach for daily-bar systems.
                    #
                    # By adhering strictly to Interpretation A, this code ensures that all stop-loss
                    # decisions are based only on information that would have been available *before*
                    # the trading session in which the stop is active.
                    # ---
                    # --- SET INITIAL STOP LOSS ONCE ENTRY PRICE IS KNOWN ---
                    stop_loss_level = np.nan
                    if stop_config.get("type") == 'percentage':
                        stop_loss_level = entry_price * (1.0 - stop_config.get("value", 0.05))
                    
                    elif stop_config.get("type") == 'atr':
                        # Get the data from the day BEFORE entry (the signal day)
                        day_before_entry = prev_trading_dates[symbol].get(entry_exec_date)
                        
                        if pd.notna(day_before_entry) and day_before_entry in df.index:
                            day_before_data = df.loc[day_before_entry]
                            atr_before_entry = day_before_data.get('ATR')
                            close_before_entry = day_before_data.get('Close')
                            
                            if pd.notna(atr_before_entry) and pd.notna(close_before_entry):
                                # The initial stop is based on the previous day's data,
                                # matching the "Next Day Activation" spec.
                                stop_loss_level = close_before_entry - (atr_before_entry * stop_config.get("multiplier", 3.0))

                    positions[symbol] = {
                        'shares': shares, 'entry_price': entry_price,
                        'entry_date': entry_exec_date, 'features': features,
                        'stop_loss_level': stop_loss_level,
                        'initial_stop_loss_level': stop_loss_level,
                    }
                    cash -= total_cost
    
    # --- START: MARK-TO-MARKET LOGIC ---
    # After the main loop, check for any positions that are still open.
    last_date = all_dates[-1]
    if positions:
        for symbol, pos in list(positions.items()):
            # Get the closing price on the very last day of the backtest
            last_price = portfolio_data[symbol]['Close'].get(last_date)
            if pd.notna(last_price):
                exit_date = last_date
                exit_reason = "End of Backtest"
                
                # --- This is the same logging logic from the main loop ---
                trade_df = portfolio_data[symbol].loc[pos['entry_date']:exit_date]
                mae_pct = (trade_df['Low'].min() - pos['entry_price']) / pos['entry_price'] if not trade_df.empty else 0.0
                mfe_pct = (trade_df['High'].max() - pos['entry_price']) / pos['entry_price'] if not trade_df.empty else 0.0
                trade_counter += 1
                exit_price = last_price * (1 - CONFIG['slippage_pct'])
                commission = pos['shares'] * CONFIG['commission_per_share']
                # We don't add to cash as this is a hypothetical close
                net_pnl = ((exit_price - pos['entry_price']) * pos['shares']) - (2 * commission)

                # --- Initial Risk and R-Multiple ---
                _initial_sl = pos.get('initial_stop_loss_level')
                if pd.notna(_initial_sl) and _initial_sl > 0 and _initial_sl < pos['entry_price']:
                    _initial_risk_per_share = pos['entry_price'] - _initial_sl
                else:
                    _initial_risk_per_share = pos['entry_price'] * 0.01
                _r_multiple = (net_pnl / (_initial_risk_per_share * pos['shares'])
                               if _initial_risk_per_share > 0 and pos['shares'] > 0 else None)

                log_entry = {'Symbol': symbol, 'Trade': f"Long {trade_counter}", 'EntryDate': pos['entry_date'].strftime('%Y-%m-%d'), 'EntryPrice': pos['entry_price'], 'ExitDate': exit_date.strftime('%Y-%m-%d'), 'ExitPrice': exit_price, 'Profit': net_pnl, 'ProfitPct': net_pnl / (pos['shares'] * pos['entry_price']), 'is_win': 1 if net_pnl > 0 else 0, 'HoldDuration': (exit_date - pos['entry_date']).days, 'MAE_pct': mae_pct, 'MFE_pct': mfe_pct, 'ExitReason': exit_reason, 'InitialRisk': _initial_risk_per_share, 'RMultiple': _r_multiple, **pos.get('features', {})}
                trade_log.append(log_entry)
    # --- END: MARK-TO-MARKET LOGIC ---

    pnl_list = [t['Profit'] for t in trade_log]
    if not pnl_list: return None
    
    duration_list = [t['HoldDuration'] for t in trade_log]
    final_pnl_percent = (portfolio_timeline.dropna().iloc[-1] / initial_capital) - 1
    metrics = calculate_advanced_metrics(pnl_list, portfolio_timeline.dropna(), duration_list)

    return {**metrics, "pnl_percent": final_pnl_percent, "Trades": len(pnl_list), 
            "trade_pnl_list": pnl_list, "trade_log": trade_log, "initial_capital": initial_capital}