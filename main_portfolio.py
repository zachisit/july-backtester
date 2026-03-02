# main_portfolio.py (Cleaned up and fully refactored)

from datetime import datetime
import logging
import os
import time
import argparse
from config import CONFIG
from services import get_data_service
from helpers.indicators import calculate_sma, calculate_rsi, calculate_atr
from strategies import STRATEGIES
from helpers.portfolio_simulations import run_portfolio_simulation
from helpers.summary import generate_portfolio_summary_report, generate_per_portfolio_summary
from helpers.monte_carlo import run_monte_carlo_simulation, analyze_mc_results
from tqdm import tqdm
from multiprocessing import Pool, cpu_count
import orjson
from helpers.caching import CACHE_DIR

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------
# --- WORKER INITIALIZER FOR MULTIPROCESSING ---
# --------------------------------------------------------------------
def init_worker(spy, vix, tnx, portfolio_data_for_worker):
    """
    Initializer for the multiprocessing pool.
    Makes large dataframes AND the current portfolio's data globally 
    available to each worker process.
    """
    global spy_df_global, vix_df_global, tnx_df_global, portfolio_data_global
    spy_df_global = spy
    vix_df_global = vix
    tnx_df_global = tnx
    portfolio_data_global = portfolio_data_for_worker

# --------------------------------------------------------------------

def run_single_simulation(args):
    """
    Function to run one combination of (portfolio, strategy, stop-loss).
    This version now uses globally initialized dataframes AND portfolio_data.
    """
    # Access ALL globally initialized data
    global spy_df_global, vix_df_global, tnx_df_global, portfolio_data_global

    # 1. Unpack the arguments. `portfolio_data` has been REMOVED from the tuple.
    portfolio_name, name, logic_func, dependencies, stop_config, \
    spy_buy_and_hold_return, qqq_buy_and_hold_return, strategy_params = args
    
    # Assign the global data to a local variable for clarity
    portfolio_data = portfolio_data_global

    try:
        strat_name = name
        if stop_config['type'] == 'percentage':
            strat_name = f"{name} w/ {stop_config['value']:.0%} SL"
        elif stop_config['type'] == 'atr':
            strat_name = f"{name} w/ {stop_config['multiplier']}x ATR({stop_config['period']}) SL"

        base_signals_with_dfs = {}
        for symbol, df in portfolio_data.items():
            kwargs = {}
            if 'spy' in dependencies and spy_df_global is not None:
                kwargs['spy_df'] = spy_df_global.reindex(df.index, method='ffill')
            if 'vix' in dependencies and vix_df_global is not None:
                kwargs['vix_df'] = vix_df_global.reindex(df.index, method='ffill')

            if strategy_params:
                kwargs.update(strategy_params)

            if len(dependencies) > 0 and any(dep + '_df' not in kwargs for dep in dependencies):
                tqdm.write(f"\n-> WARNING for '{symbol}': Skipping strategy '{name}' due to missing dependency data.")
                base_signals_with_dfs[symbol] = df.copy().assign(Signal=0) 
                continue

            # - If there are dependencies, kwargs contains spy_df etc.
            # - If there are params, kwargs contains them.
            # - If there are neither, kwargs is empty, which is fine.
            base_signals_with_dfs[symbol] = logic_func(df.copy(), **kwargs)

        # The simulator now handles stop-loss logic internally.
        final_signals = {symbol: df['Signal'] for symbol, df in base_signals_with_dfs.items()}
        
        # Call the simulation, passing the stop_config and using the global dataframes.
        result = run_portfolio_simulation(
            portfolio_data, final_signals, CONFIG["initial_capital"], CONFIG["allocation_per_trade"],
            spy_df_global, vix_df_global, tnx_df_global, stop_config
        )
        
        if result is None: return None
        
        if result and result.get('trade_pnl_list'):
            result['Strategy'] = strat_name
            result['Portfolio'] = portfolio_name
            
            if result.get('Trades', 0) > 0:
                if result['Trades'] >= CONFIG.get("min_trades_for_mc", 10):
                    mc_sim_results = run_monte_carlo_simulation(
                        result['trade_pnl_list'], initial_equity=result['initial_capital'],
                        num_simulations=CONFIG["num_mc_simulations"]
                    )
                    mc_analysis = analyze_mc_results(result, mc_sim_results)
                    result.update(mc_analysis)
                else:
                    result.update({"mc_verdict": "N/A (few trades)", "mc_score": -999})
            else:
                result.update({"mc_verdict": "N/A (no trades)", "mc_score": -999, "max_drawdown": 0, "calmar_ratio": 0, "sharpe_ratio": 0, "profit_factor": 0, "win_rate": 0, "avg_trade_duration": 0})

            result['vs_spy_benchmark'] = result.get('pnl_percent', 0.0) - spy_buy_and_hold_return
            result['vs_qqq_benchmark'] = result.get('pnl_percent', 0.0) - qqq_buy_and_hold_return
            return result
            
    except Exception:
        import traceback
        tqdm.write(f"\n--- FATAL ERROR IN WORKER ---\nStrategy: {name}\nPortfolio: {portfolio_name}\nTraceback:\n{traceback.format_exc()}\n---------------------------\n")
        return None

def main():
    # --- ARGUMENT PARSING & FOLDER SETUP (No changes) ---
    parser = argparse.ArgumentParser(description="Portfolio Backtester")
    parser.add_argument("--name", type=str, help="An optional name for the backtest run, used as a prefix for the report folder.")
    args = parser.parse_args()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_folder_name = f"{args.name}_{timestamp}" if args.name else timestamp
    start_time = time.monotonic()

    os.makedirs("logs", exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(f"logs/run_{timestamp}.log"),
        ],
    )

    data_fetcher = get_data_service()
    logger.info("PORTFOLIO STRATEGY ANALYZER")

    # --- FETCHING DEPENDENCY & BENCHMARK DATA (No changes) ---
    # (Your existing code to fetch spy_df, vix_df, etc., and calculate benchmarks is correct)
    try:
        spy_df = data_fetcher('SPY', CONFIG["start_date"], CONFIG["end_date"], CONFIG)
        spy_buy_and_hold_return = (spy_df['Close'].iloc[-1] - spy_df['Close'].iloc[0]) / spy_df['Close'].iloc[0]
        qqq_df = data_fetcher('QQQ', CONFIG["start_date"], CONFIG["end_date"], CONFIG)
        qqq_buy_and_hold_return = (qqq_df['Close'].iloc[-1] - qqq_df['Close'].iloc[0]) / qqq_df['Close'].iloc[0]
        vix_df = data_fetcher("I:VIX", CONFIG["start_date"], CONFIG["end_date"], CONFIG) # Simplified
        tnx_df = data_fetcher("I:TNX", CONFIG["start_date"], CONFIG["end_date"], CONFIG) # Simplified
        logger.info(f"SPY B&H: {spy_buy_and_hold_return:.2%}, QQQ B&H: {qqq_buy_and_hold_return:.2%}")
    except Exception as e:
        logger.error(f"FATAL: Could not fetch dependency data: {e}")
        return

    # --- START OF MODIFIED LOGIC ---

    all_portfolio_results = [] # To gather results from all portfolios

    logger.info("=" * 25 + " PROCESSING PORTFOLIOS " + "=" * 25)
    # Loop through each portfolio sequentially
    for portfolio_name, value in CONFIG['portfolios'].items():
        logger.info(f"--> Preparing and running portfolio: {portfolio_name}")
        
        # --- Data fetching for the current portfolio (no changes) ---
        # (Your existing code to get symbols and build `portfolio_data` is perfect)
        symbols = []
        if isinstance(value, list):
            symbols = value
        elif isinstance(value, str) and value.startswith("norgate:"):
            watchlist_name = value.split(":", 1)[1]
            try:
                import norgatedata
                symbols = norgatedata.watchlist_symbols(watchlist_name)
                logger.info(f"  -> Loaded {len(symbols)} symbols from Norgate watchlist: '{watchlist_name}'")
            except ImportError:
                logger.warning(f"  -> SKIPPING Norgate watchlist '{portfolio_name}': norgatedata package not installed.")
                continue
            except Exception as e:
                logger.error(f"  -> ERROR loading Norgate watchlist '{watchlist_name}': {e}")
                continue
        elif isinstance(value, str) and value.endswith('.json'):
             file_path = os.path.join("tickers_to_scan", value)
             with open(file_path, 'rb') as f:
                 symbols = orjson.loads(f.read())
        
        if not symbols:
            logger.warning(f"No symbols found for '{portfolio_name}'. Skipping.")
            continue

        portfolio_data = {}
        for symbol in tqdm(symbols, desc="  -> Fetching & Preparing Data", unit=" symbols"):
            df = data_fetcher(symbol, CONFIG["start_date"], CONFIG["end_date"], CONFIG)
            if df is not None and not df.empty:
                # (Your existing feature calculation logic here)
                portfolio_data[symbol] = df

        if not portfolio_data:
            logger.warning(f"Could not fetch data for any symbols in '{portfolio_name}'. Skipping.")
            continue

        # --- Generate tasks for THIS portfolio, WITHOUT the large `portfolio_data` ---
        tasks_for_this_portfolio = []
        for strat_name, strategy_config in STRATEGIES.items():
            for stop_config in CONFIG['stop_loss_configs']:
                # This tuple is now much smaller because `portfolio_data` is removed
                task_args = (
                    portfolio_name, strat_name, strategy_config["logic"],
                    strategy_config.get("dependencies", []),
                    stop_config, spy_buy_and_hold_return, qqq_buy_and_hold_return,
                    strategy_config.get("params", {}) 
                )
                tasks_for_this_portfolio.append(task_args)

        if not tasks_for_this_portfolio:
            logger.warning(f"No tasks generated for {portfolio_name}.")
            continue

        # --- Create a NEW Pool initialized with THIS portfolio's data ---
        logger.info("=" * 15 + f" RUNNING SIMULATIONS FOR '{portfolio_name}' " + "=" * 15)
        logger.info(f"Found {len(tasks_for_this_portfolio)} tasks. Using up to {cpu_count()} CPU cores.")
        
        # Pass `portfolio_data` during initialization, not with each task
        init_args = (spy_df, vix_df, tnx_df, portfolio_data)

        with Pool(processes=cpu_count(), initializer=init_worker, initargs=init_args) as p:
            results_this_portfolio = list(tqdm(p.imap(run_single_simulation, tasks_for_this_portfolio), total=len(tasks_for_this_portfolio), desc="  -> Running sims"))
        
        # Add the results to the main list
        all_portfolio_results.extend([r for r in results_this_portfolio if r is not None])

    # --- FINAL REPORTING (No changes needed here) ---
    if not all_portfolio_results:
        logger.warning("No simulation tasks were generated or completed successfully.")
        return
        
    results_by_portfolio = {}
    for res in all_portfolio_results:
        p_name = res['Portfolio']
        if p_name not in results_by_portfolio: results_by_portfolio[p_name] = []
        results_by_portfolio[p_name].append(res)
    
    for p_name, p_results in results_by_portfolio.items():
         generate_per_portfolio_summary(p_results, p_name, spy_buy_and_hold_return, qqq_buy_and_hold_return, run_folder_name)

    duration_seconds = time.monotonic() - start_time
    generate_portfolio_summary_report(all_portfolio_results, duration_seconds, run_folder_name)
    
    mins, secs = divmod(duration_seconds, 60)
    logger.info(f"All portfolio simulations complete in {int(mins)}m {secs:.2f}s.")

if __name__ == "__main__":
    main()