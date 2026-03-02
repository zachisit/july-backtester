# main_single_asset.py

import os
import shutil
import time
import pandas as pd

from config import CONFIG
from helpers.indicators import *
from helpers.simulations import run_simulation, apply_stop_loss
from helpers.summary import generate_single_asset_summary_report, generate_final_summary
from helpers.monte_carlo import run_monte_carlo_simulation, analyze_mc_results
import norgatedata
from tqdm import tqdm
from datetime import datetime

def get_norgate_data(symbol, timeframe, start_date, end_date):
    print(f"  -> Fetching '{symbol}' {timeframe} data from Norgate...")
    try:
        df = norgatedata.price_timeseries(
            symbol, interval=timeframe, start_date=start_date, end_date=end_date,
            stock_price_adjustment_setting=CONFIG["price_adjustment"],
            padding_setting=norgatedata.PaddingType.NONE,
            timeseriesformat='pandas-dataframe'
        )
        if df is None or df.empty:
            print(f"  -> WARNING: No data returned for '{symbol}'."); return None
        df.columns = [col.capitalize() for col in df.columns]; df.index.name = 'Datetime'
        print(f"  -> OK: Loaded {len(df)} daily bars.")
        return df
    except Exception as e:
        print(f"  -> ERROR fetching data for '{symbol}': {e}"); return None

def main():
    print("\n---> SINGLE-ASSET STRATEGY ANALYZER <---")
    start_time = time.monotonic()
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    trades_folder = "trades"
    if os.path.exists(trades_folder):
        shutil.rmtree(trades_folder)
    os.makedirs(trades_folder)

    STRATEGIES = {
        "SMA Crossover (20/50)": lambda df: sma_crossover_logic(df, 20, 50),
        "SMA Crossover (50/200)": lambda df: sma_crossover_logic(df, 50, 200),
        "RSI Mean Reversion (14/30)": lambda df: rsi_logic(df, 14, 30, 50),
        "RSI Mean Reversion (7/20)": lambda df: rsi_logic(df, 7, 20, 50),
        "MACD Crossover (12/26/9)": lambda df: macd_crossover_logic(df, 12, 26, 9),
        "Bollinger Band Fade (20/2)": lambda df: bollinger_band_logic(df, 20, 2),
        "Stochastic Oscillator (14/3)": lambda df: stochastic_logic(df, 14, 3, 20, 50),
        "Bollinger Band Breakout (20/2)": lambda df: bollinger_breakout_logic(df, 20, 2),
        "OBV Trend (20-period MA) - BASELINE": 
        lambda df: obv_logic(df, ma_length=20),
        "OBV Trend w/ Price Confirm (20/20) - V2": 
        lambda df: obv_price_confirmation_logic(df, obv_ma_length=20, price_ma_length=20),
        "OBV Trend w/ 2-Day Confirm - V3": 
        lambda df: obv_confirmation_period_logic(df, ma_length=20, confirmation_days=2),
        "MACD+RSI Confirmation": lambda df: macd_rsi_filter_logic(df, 12, 26, 9, 14),
        "MA20 Bounce": lambda df: ma_bounce_logic(df, ma_length=20, filter_bars=2),
        "SMA 200 Trend Filter": lambda df: sma_trend_filter_logic(df, 200),
        "Donchian Breakout (20/10)": lambda df: donchian_channel_breakout_logic(df, 20, 10),
        "ATR Trailing Stop (14/3)": lambda df: atr_trailing_stop_logic(df, 14, 3.0),
        "M-Th Overnight Hold": m_th_overnight_logic,
        "Weekend Hold": weekend_hold_logic,
        "Keltner Channel Breakout (20/2)": lambda df: keltner_channel_breakout_logic(df, 20, 20, 2.0),
        "Chaikin Money Flow (20)": lambda df: chaikin_money_flow_logic(df, 20, 0.05, -0.05),
    }
    
    # --- Fetch SPY Benchmark ---
    print(f"\nFetching benchmark data for SPY...")
    spy_benchmark_df = get_norgate_data('SPY', 'D', CONFIG["start_date"], CONFIG["end_date"])
    spy_benchmark_result = None
    spy_buy_and_hold_return = 0.0
    if spy_benchmark_df is not None:
        spy_logic_df = buy_and_hold_logic(spy_benchmark_df.copy())
        spy_benchmark_result = run_simulation(spy_logic_df, CONFIG["initial_capital"], 'SPY')
        if spy_benchmark_result:
            spy_buy_and_hold_return = spy_benchmark_result.get('pnl_percent', 0.0)
            print(f"SPY Buy & Hold Return ({CONFIG['start_date']} to {CONFIG['end_date']}): {spy_buy_and_hold_return:.2%}")
    else:
        print("Could not calculate benchmark return. SPY data not available.")

    # --- ADDED: Fetch QQQ Benchmark ---
    print(f"\nFetching benchmark data for QQQ...")
    qqq_benchmark_df = get_norgate_data('QQQ', 'D', CONFIG["start_date"], CONFIG["end_date"])
    qqq_benchmark_result = None
    qqq_buy_and_hold_return = 0.0
    if qqq_benchmark_df is not None:
        qqq_logic_df = buy_and_hold_logic(qqq_benchmark_df.copy())
        qqq_benchmark_result = run_simulation(qqq_logic_df, CONFIG["initial_capital"], 'QQQ')
        if qqq_benchmark_result:
            qqq_buy_and_hold_return = qqq_benchmark_result.get('pnl_percent', 0.0)
            print(f"QQQ Buy & Hold Return ({CONFIG['start_date']} to {CONFIG['end_date']}): {qqq_buy_and_hold_return:.2%}")
    else:
        print("Could not calculate benchmark return. QQQ data not available.")

    all_symbols_results = []
    for symbol in CONFIG['symbols_to_test']:
        print(f"\n\n{'='*25} PROCESSING SYMBOL: {symbol} {'='*25}\n")
        
        symbol_trades_folder = os.path.join(trades_folder, symbol)
        os.makedirs(symbol_trades_folder, exist_ok=True)
        
        primary_df = get_norgate_data(symbol, CONFIG["timeframe"], CONFIG["start_date"], CONFIG["end_date"])
        if primary_df is None: continue
        
        print(f"--- Running All Simulations for {symbol} ---")
        symbol_results = []

        strategy_definitions = list(STRATEGIES.items())
        for threshold in CONFIG['roc_thresholds']:
            strategy_definitions.append(
                (f"ROC Momentum (Thresh={threshold})", lambda df, t=threshold: roc_logic(df, 12, t))
            )
        
        for name, logic_func in strategy_definitions:
            base_df = logic_func(primary_df.copy())
            
            for stop_config in CONFIG['stop_loss_configs']:
                strat_name = name
                if stop_config['type'] == 'percentage':
                    strat_name = f"{name} w/ {stop_config['value']:.0%} SL"
                elif stop_config['type'] == 'atr':
                    strat_name = f"{name} w/ {stop_config['multiplier']}x ATR({stop_config['period']}) SL"

                print(f"  -> Testing: {strat_name}")
                
                test_df = apply_stop_loss(base_df.copy(), stop_config)
                result = run_simulation(test_df, CONFIG["initial_capital"], symbol)
                
                if result:
                    result['Strategy'] = strat_name
                    result['Asset'] = symbol
                    # Add both benchmark comparisons
                    result['vs_spy_benchmark'] = result['pnl_percent'] - spy_buy_and_hold_return
                    result['vs_qqq_benchmark'] = result['pnl_percent'] - qqq_buy_and_hold_return
                    
                    if result['Trades'] >= CONFIG['min_trades_for_mc']:
                        mc_sim_results = run_monte_carlo_simulation(
                            result['trade_pnl_list'],
                            CONFIG['initial_capital'],
                            CONFIG['num_mc_simulations']
                        )
                        mc_analysis = analyze_mc_results(result, mc_sim_results)
                        result.update(mc_analysis)
                    else:
                        result.update({"mc_verdict": "N/A (Low Trades)", "mc_score": 0})
                        
                    symbol_results.append(result)
        
        # Pass both benchmark results to the summary function
        generate_single_asset_summary_report(symbol_results, spy_benchmark_result, qqq_benchmark_result, symbol, symbol_trades_folder, run_id)
        all_symbols_results.extend(symbol_results)
    
    duration_seconds = time.monotonic() - start_time
    generate_final_summary(all_symbols_results, duration_seconds, run_id)
    print("\n\nAll single-asset simulations complete.")

if __name__ == "__main__":
    main()