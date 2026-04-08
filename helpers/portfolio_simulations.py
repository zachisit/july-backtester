import pandas as pd
import numpy as np
from config import CONFIG
from .simulations import calculate_advanced_metrics
from helpers.position_sizing import calculate_position_size, check_portfolio_heat

def run_portfolio_simulation(portfolio_data, signals, initial_capital, allocation_pct, spy_df, vix_df, tnx_df, stop_config):
    """
    Runs a portfolio simulation with integrated stop-loss handling and logs
    a rich set of features for each trade for future machine learning analysis.
    (Version hardened against KeyError from misaligned dates).
    """
    from helpers.timeframe_utils import get_bars_per_year

    execution_time = CONFIG.get("execution_time", "open").lower()
    htb_rate_annual = CONFIG.get("htb_rate_annual", 0.0)

    # Dynamic HTB rate compounding based on timeframe (fixes issue #55)
    bars_per_year = get_bars_per_year(CONFIG)
    htb_rate_per_bar = (1.0 + htb_rate_annual) ** (1.0 / bars_per_year) - 1.0 if htb_rate_annual > 0 else 0.0

    short_positions: dict = {}

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

        for symbol, spos in short_positions.items():
            if date in portfolio_data[symbol].index:
                cur = portfolio_data[symbol].loc[date].get('Close')
                if pd.notna(cur):
                    current_market_value += (spos['shares'] * spos['entry_price']) - (spos['shares'] * cur)

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
                    current_atr = portfolio_data[symbol].loc[date].get('ATR_14')
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

            # --- VOLUME-BASED MARKET IMPACT (exit) ---
            exit_impact_bps = 0.0
            _exit_impact_coeff = CONFIG.get('volume_impact_coeff', 0.0)
            if _exit_impact_coeff > 0 and 'Volume' in portfolio_data[symbol].columns:
                _adv_exit = portfolio_data[symbol]['Volume'].rolling(window=20, min_periods=1).mean().get(date, np.nan)
                if pd.notna(_adv_exit) and _adv_exit > 0:
                    _order_pct = pos['shares'] / _adv_exit
                    _impact = _exit_impact_coeff * np.sqrt(_order_pct)
                    exit_price = exit_price * (1 - _impact)
                    exit_impact_bps = round(_impact * 10000, 1)

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
                'EntryDate': pos['entry_date'].isoformat(), 'EntryPrice': pos['entry_price'],
                'ExitDate': exit_date.isoformat(), 'ExitPrice': exit_price,
                'Profit': net_pnl, 'ProfitPct': net_pnl / position_value if position_value > 0 else 0,
                'Shares': pos['shares'],
                'is_win': 1 if net_pnl > 0 else 0,
                'HoldDuration': duration,
                'MAE_pct': mae_pct, 'MFE_pct': mfe_pct,
                'ExitReason': exit_reason,
                'InitialRisk': _initial_risk_per_share,
                'RMultiple': _r_multiple,
                'VolumeImpact_bps': round(pos.get('entry_impact_bps', 0.0) + exit_impact_bps, 1),
            }
            log_entry.update(pos.get('features', {}))
            trade_log.append(log_entry)
            exited_symbols.append(symbol)

        for symbol in exited_symbols: del positions[symbol]

        # --- BORROW COST DEBIT (shorts held overnight) ---
        for symbol, spos in list(short_positions.items()):
            if htb_rate_per_bar > 0:
                cost = spos['notional'] * htb_rate_per_bar
                cash -= cost
                spos['total_borrow_cost'] = spos.get('total_borrow_cost', 0.0) + cost

        # --- SHORT COVER (signal = -1 while short) ---
        short_exited = []
        for symbol, spos in list(short_positions.items()):
            if date not in portfolio_data[symbol].index:
                continue
            sig_date = prev_trading_dates[symbol].get(date) if execution_time == 'open' else date
            if pd.notna(sig_date) and sig_date in signals[symbol].index and signals[symbol].loc[sig_date] < 0:
                cover = portfolio_data[symbol].loc[date].get('Open' if execution_time == 'open' else 'Close')
                if pd.isna(cover):
                    continue
                cover_slip = cover * (1 + CONFIG['slippage_pct'])
                commission = spos['shares'] * CONFIG['commission_per_share']
                net_pnl = (spos['shares'] * spos['entry_price']) - (spos['shares'] * cover_slip) - (2 * commission) - spos.get('total_borrow_cost', 0.0)
                cash += spos['shares'] * (spos['entry_price'] - cover_slip) - commission
                trade_counter += 1
                trade_log.append({
                    'Symbol': symbol, 'Trade': f"Short {trade_counter}",
                    'EntryDate': spos['entry_date'].isoformat(), 'EntryPrice': spos['entry_price'],
                    'ExitDate': date.isoformat(), 'ExitPrice': cover_slip,
                    'Profit': net_pnl, 'ProfitPct': net_pnl / spos['notional'] if spos['notional'] > 0 else 0,
                    'Shares': spos['shares'], 'is_win': 1 if net_pnl > 0 else 0,
                    'HoldDuration': (date - spos['entry_date']).days,
                    'MAE_pct': 0.0, 'MFE_pct': 0.0, 'ExitReason': 'Short Cover',
                    'InitialRisk': 0.0, 'RMultiple': None,
                })
                short_exited.append(symbol)
        for symbol in short_exited:
            del short_positions[symbol]

        # --- SHORT ENTRY (signal = -2, not already in any position) ---
        for symbol, df in portfolio_data.items():
            if date not in df.index or symbol in positions or symbol in short_positions:
                continue
            sig_date = prev_trading_dates[symbol].get(date) if execution_time == 'open' else date
            if pd.notna(sig_date) and sig_date in signals[symbol].index and signals[symbol].loc[sig_date] == -2:
                ep = df.loc[date].get('Open' if execution_time == 'open' else 'Close')
                if pd.isna(ep) or ep <= 0:
                    continue
                alloc = min(total_equity * allocation_pct, cash)
                if alloc <= 0:
                    continue
                shares = alloc / ep
                commission = shares * CONFIG['commission_per_share']
                cash += shares * ep - commission   # short seller receives proceeds
                short_positions[symbol] = {
                    'entry_date': date, 'entry_price': ep,
                    'shares': shares, 'notional': shares * ep, 'total_borrow_cost': 0.0,
                }

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

            if entry_price > 0 and cash > 0:
                # --- POSITION SIZING ---
                sizing_method = CONFIG.get('position_sizing_method', 'fixed')
                sizing_kwargs = {}

                # For risk_parity: derive stop_distance_pct from the configured stop so
                # sizing uses the actual stop rather than always falling back to 3x ATR.
                if sizing_method == "risk_parity":
                    stop_type = stop_config.get("type", "none")
                    if stop_type == "percentage":
                        sizing_kwargs["stop_distance_pct"] = stop_config.get("value", 0.05)
                    elif stop_type == "atr":
                        _day_before = prev_trading_dates[symbol].get(entry_exec_date)
                        if _day_before is not None and _day_before in df.index and "ATR_14" in df.columns:
                            _atr = df.loc[_day_before, 'ATR_14']
                            _close = df.loc[_day_before, 'Close']
                            if pd.notna(_atr) and pd.notna(_close) and _close > 0:
                                sizing_kwargs["stop_distance_pct"] = (
                                    _atr * stop_config.get("multiplier", 3.0)
                                ) / _close

                # For kelly: compute rolling stats from completed trades so sizing
                # actually adapts to the strategy's live performance.
                if sizing_method == "kelly" and len(trade_log) >= 10:
                    _wins = [t for t in trade_log if t.get("is_win") == 1 and t.get("ProfitPct") is not None]
                    _losses = [t for t in trade_log if t.get("is_win") == 0 and t.get("ProfitPct") is not None]
                    if _wins and _losses:
                        sizing_kwargs["win_rate"] = len(_wins) / len(trade_log)
                        sizing_kwargs["avg_win"] = sum(t["ProfitPct"] for t in _wins) / len(_wins)
                        sizing_kwargs["avg_loss"] = sum(abs(t["ProfitPct"]) for t in _losses) / len(_losses)

                # Slice to current date to prevent look-ahead bias: vol_parity and
                # risk_parity use .iloc[-1] on the passed DataFrame, so passing the
                # full history would use a future ATR value on early simulation dates.
                shares = calculate_position_size(
                    method=sizing_method,
                    equity=total_equity,
                    price=entry_price,
                    symbol_data=df.loc[:date],
                    config=CONFIG,
                    **sizing_kwargs
                )

                # --- PORTFOLIO HEAT CHECK ---
                # Compute the dollar risk this position adds. For methods with a
                # known stop distance we use that; otherwise fall back to the
                # target_risk_per_trade parameter (which is what vol/risk parity
                # sized against anyway).
                _stop_dist = sizing_kwargs.get("stop_distance_pct") or CONFIG.get("target_risk_per_trade", 0.02)
                new_position_risk = shares * entry_price * _stop_dist
                max_heat = CONFIG.get("max_portfolio_heat", 1.0)
                if not check_portfolio_heat(positions, new_position_risk, total_equity, max_heat):
                    continue

                # Cash constraint
                capital_needed = shares * entry_price
                if capital_needed > cash:
                    shares = cash / entry_price

                # --- VOLUME-BASED LIQUIDITY FILTER ---
                max_pct_adv = CONFIG.get('max_pct_adv') or 0
                if max_pct_adv > 0 and 'Volume' in df.columns:
                    adv_20 = df['Volume'].rolling(window=20, min_periods=1).mean().get(entry_exec_date, np.nan)
                    if pd.notna(adv_20) and adv_20 > 0:
                        max_shares_allowed = adv_20 * max_pct_adv
                        if max_shares_allowed <= 0:
                            continue
                        shares = min(shares, max_shares_allowed)

                # --- VOLUME-BASED MARKET IMPACT ---
                entry_impact_bps = 0.0
                impact_coeff = CONFIG.get('volume_impact_coeff', 0.0)
                if impact_coeff > 0 and 'Volume' in df.columns:
                    adv_20_impact = df['Volume'].rolling(window=20, min_periods=1).mean().get(entry_exec_date, np.nan)
                    if pd.notna(adv_20_impact) and adv_20_impact > 0:
                        order_pct_of_adv = shares / adv_20_impact
                        impact_additional = impact_coeff * np.sqrt(order_pct_of_adv)
                        entry_price = entry_price * (1 + impact_additional)
                        entry_impact_bps = round(impact_additional * 10000, 1)

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
                        if spy_df is not None:
                            features['entry_SPY_RSI_14'] = spy_df.loc[entry_exec_date, 'RSI_14']
                            features['entry_SPY_SMA200_dist_pct'] = spy_df.loc[entry_exec_date, 'SMA200_dist_pct']
                        if vix_df is not None:
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
                            atr_before_entry = day_before_data.get('ATR_14')
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
                        'entry_impact_bps': entry_impact_bps,
                        'risk': new_position_risk,
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

                log_entry = {'Symbol': symbol, 'Trade': f"Long {trade_counter}", 'EntryDate': pos['entry_date'].isoformat(), 'EntryPrice': pos['entry_price'], 'ExitDate': exit_date.isoformat(), 'ExitPrice': exit_price, 'Profit': net_pnl, 'ProfitPct': net_pnl / (pos['shares'] * pos['entry_price']), 'Shares': pos['shares'], 'is_win': 1 if net_pnl > 0 else 0, 'HoldDuration': (exit_date - pos['entry_date']).days, 'MAE_pct': mae_pct, 'MFE_pct': mfe_pct, 'ExitReason': exit_reason, 'InitialRisk': _initial_risk_per_share, 'RMultiple': _r_multiple, **pos.get('features', {})}
                trade_log.append(log_entry)
    # --- END: MARK-TO-MARKET LOGIC ---

    pnl_list = [t['Profit'] for t in trade_log]
    if not pnl_list: return None
    
    duration_list = [t['HoldDuration'] for t in trade_log]
    final_pnl_percent = (portfolio_timeline.dropna().iloc[-1] / initial_capital) - 1
    metrics = calculate_advanced_metrics(pnl_list, portfolio_timeline.dropna(), duration_list)

    return {**metrics, "pnl_percent": final_pnl_percent, "Trades": len(pnl_list),
            "trade_pnl_list": pnl_list, "trade_log": trade_log, "initial_capital": initial_capital,
            "portfolio_timeline": portfolio_timeline.dropna()}