# main.py

import os
import shutil
import pandas as pd

from config import CONFIG
from helpers.indicators import *
from helpers.simulations import run_simulation, apply_stop_loss
from helpers.summary import generate_single_asset_summary_report, generate_final_summary
from helpers.monte_carlo import run_monte_carlo_simulation, analyze_mc_results
import norgatedata

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
    print("\n---> SINGLE-ASSET STRATEGY ANALYZER (v7.3 - Final Stable) <---")

    trades_folder = CONFIG['trades_folder']
    if os.path.exists(trades_folder):
        shutil.rmtree(trades_folder)
    os.makedirs(trades_folder)

    # --- RESTORED: Full list of strategies ---
    STRATEGIES = {
        "SMA Crossover (20/50)": lambda df: sma_crossover_logic(df, 20, 50),
        "SMA Crossover (50/200)": lambda df: sma_crossover_logic(df, 50, 200),
        "RSI Mean Reversion (14/30)": lambda df: rsi_logic(df, 14, 30, 50),
        "RSI Mean Reversion (7/20)": lambda df: rsi_logic(df, 7, 20, 50),
        "MACD Crossover (12/26/9)": lambda df: macd_crossover_logic(df, 12, 26, 9),
        "Bollinger Band Fade (20/2)": lambda df: bollinger_band_logic(df, 20, 2),
        "Stochastic Oscillator (14/3)": lambda df: stochastic_logic(df, 14, 3, 20, 50),
        "Bollinger Band Breakout (20/2)": lambda df: bollinger_breakout_logic(df, 20, 2),
        "OBV Trend (20-period MA)": lambda df: obv_logic(df, 20),
        "MACD+RSI Confirmation": lambda df: macd_rsi_filter_logic(df, 12, 26, 9, 14),
        "MA20 Bounce": lambda df: ma_bounce_logic(df, ma_length=20, filter_bars=2),
        "SMA 200 Trend Filter": lambda df: sma_trend_filter_logic(df, 200),
        "Donchian Breakout (20/10)": lambda df: donchian_channel_breakout_logic(df, 20, 10),
        "ATR Trailing Stop (14/3)": lambda df: atr_trailing_stop_logic(df, 14, 3.0),
    }
    
    benchmark_df = get_norgate_data(CONFIG['benchmark_symbol'], 'D', CONFIG["start_date"], CONFIG["end_date"])
    benchmark_result = None
    if benchmark_df is not None:
        benchmark_logic_df = buy_and_hold_logic(benchmark_df.copy())
        benchmark_result = run_simulation(benchmark_logic_df, CONFIG["initial_capital"], CONFIG['benchmark_symbol'])
        if benchmark_result:
            benchmark_result['Asset'] = CONFIG['benchmark_symbol']
            benchmark_result['Strategy'] = "Buy & Hold"

    all_symbols_results = []
    for symbol in CONFIG['symbols_to_test']:
        print(f"\n\n{'='*25} PROCESSING SYMBOL: {symbol} {'='*25}\n")
        
        symbol_trades_folder = os.path.join(trades_folder, symbol)
        os.makedirs(symbol_trades_folder, exist_ok=True)
        
        primary_df = get_norgate_data(symbol, CONFIG["timeframe"], CONFIG["start_date"], CONFIG["end_date"])
        if primary_df is None: continue
        
        print(f"\n--- Running All Simulations for {symbol} ---")
        symbol_results = []

        strategy_definitions = list(STRATEGIES.items())
        for threshold in CONFIG['roc_thresholds']:
            strategy_definitions.append(
                (f"ROC Momentum (Thresh={threshold})", lambda df, t=threshold: roc_logic(df, 12, t))
            )

        for name, logic_func in strategy_definitions:
            base_df = logic_func(primary_df.copy())
            for sl_pct in CONFIG['stop_loss_levels']:
                strat_name = f"{name} w/ {sl_pct:.0%} SL" if sl_pct > 0 else name
                print(f"  -> Testing: {strat_name}")
                
                test_df = apply_stop_loss(base_df.copy(), sl_pct) if sl_pct > 0 else base_df.copy()
                result = run_simulation(test_df, CONFIG["initial_capital"], symbol)
                
                if result:
                    result['Strategy'] = strat_name
                    result['Asset'] = symbol
                    
                    if result['Trades'] >= CONFIG['min_trades_for_mc']:
                        print(f"    - Running Monte Carlo ({result['Trades']} trades)...")
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
        
        generate_single_asset_summary_report(symbol_results, benchmark_result, symbol, symbol_trades_folder)
        all_symbols_results.extend(symbol_results)
    
    generate_final_summary(all_symbols_results)
    print("\n\nAll single-asset simulations complete.")

if __name__ == "__main__":
    main()
