# main_portfolio.py (Cleaned up and fully refactored)

from datetime import datetime
from functools import partial
import logging
import os
import json
import time
from datetime import datetime
import argparse
from config import CONFIG
from services import get_data_service
from helpers.indicators import (
    # --- Feature calculation helpers (used in portfolio data prep loop) ---
    calculate_sma, calculate_rsi, calculate_atr,
    # --- Active STRATEGIES ---
    sma_crossover_logic,
    # --- Wrapper bodies (always compiled, even when strategy is commented out) ---
    ema_regime_crossover_logic,
    ema_crossover_unfiltered_logic,
    ema_crossover_spy_only_logic,
    ema_crossover_vix_only_logic,
    bollinger_fade_with_regime_filter_logic,
    weekday_overnight_with_vix_filter_logic,
    weekday_overnight_with_trend_filter_logic,
    weekday_overnight_with_rsi_filter_logic,
    ma_confluence_with_regime_filter_logic,
    # --- Commented-out STRATEGIES (imported so uncommenting needs no import changes) ---
    ma_confluence_logic,
    rsi_logic,
    macd_crossover_logic,
    stochastic_logic,
    obv_logic,
    ma_bounce_logic,
    sma_trend_filter_logic,
    macd_rsi_filter_logic,
    atr_trailing_stop_with_trend_filter_logic,
    bollinger_band_logic,
    bollinger_breakout_logic,
    bollinger_band_squeeze_logic,
    chaikin_money_flow_logic,
    donchian_channel_breakout_logic,
    keltner_channel_breakout_logic,
    atr_trailing_stop_logic,
    rsi_with_trend_filter_logic,
    hold_the_week_logic,
    weekend_hold_logic,
    ema_scalping_logic,
    rsi_scalping_logic,
)
from helpers.portfolio_simulations import run_portfolio_simulation
from helpers.summary import generate_portfolio_summary_report, generate_per_portfolio_summary
from helpers.monte_carlo import run_monte_carlo_simulation, analyze_mc_results
from tqdm import tqdm
from multiprocessing import Pool, cpu_count
import orjson
from helpers.caching import CACHE_DIR
from helpers.timeframe_utils import get_bars_for_period

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------
# --- STRATEGY WRAPPER FUNCTIONS (PICKLE-SAFE) ---
# This is for strategies that need external dataframes (e.g., spy_df, vix_df).
# --------------------------------------------------------------------
def strategy_ema_regime(df, **kwargs):
    """Wrapper for the EMA Regime strategy."""
    return ema_regime_crossover_logic(
        df,
        spy_df=kwargs.get('spy_df'),
        vix_df=kwargs.get('vix_df'),
        fast_ema=kwargs.get('fast_ema'),
        slow_ema=kwargs.get('slow_ema')
    )

def strategy_bollinger_fade_regime(df, **kwargs):
    """Wrapper for the Bollinger Band Fade with SPY Trend Filter strategy."""
    return bollinger_fade_with_regime_filter_logic(
        df,
        spy_df=kwargs.get('spy_df'),
        length=kwargs.get('length'),
        std_dev=kwargs.get('std_dev')
    )

# --- This wrapper only needs a dataframe, but the **kwargs signature makes it robust ---
def strategy_weekday_overnight_vix(df, **kwargs):
    """Wrapper for the weekday overnight strategy with VIX filter."""
    return weekday_overnight_with_vix_filter_logic(df, kwargs.get('vix_df'))

# --- These wrappers don't use external data, but the flexible signature is good practice ---
def strategy_weekday_overnight_trend(df, **kwargs):
    return weekday_overnight_with_trend_filter_logic(df)

def strategy_weekday_overnight_rsi(df, **kwargs):
    return weekday_overnight_with_rsi_filter_logic(df)

def strategy_ma_confluence_regime(df, **kwargs):
    """Wrapper for the MA Confluence with SPY+VIX Regime Filter strategy."""
    return ma_confluence_with_regime_filter_logic(
        df,
        spy_df=kwargs.get('spy_df'),
        vix_df=kwargs.get('vix_df'),
        ma_fast=kwargs.get('ma_fast'),
        ma_medium=kwargs.get('ma_medium'),
        ma_slow=kwargs.get('ma_slow')
        # regime_ma and vix_threshold use their defaults (200, 30) from the function definition
    )


def strategy_ema_unfiltered(df, **kwargs):
    """Wrapper for the pure EMA Crossover strategy."""
    return ema_crossover_unfiltered_logic(
        df,
        fast_ema=kwargs.get('fast_ema'),
        slow_ema=kwargs.get('slow_ema')
    )

def strategy_ema_spy_only(df, **kwargs):
    """Wrapper for the EMA Crossover with SPY-only filter."""
    return ema_crossover_spy_only_logic(
        df,
        spy_df=kwargs.get('spy_df'),
        fast_ema=kwargs.get('fast_ema'),
        slow_ema=kwargs.get('slow_ema')
    )

def strategy_ema_vix_only(df, **kwargs):
    """Wrapper for the EMA Crossover with VIX-only filter."""
    return ema_crossover_vix_only_logic(
        df,
        vix_df=kwargs.get('vix_df'),
        fast_ema=kwargs.get('fast_ema'),
        slow_ema=kwargs.get('slow_ema')
    )
# --------------------------------------------------------------------

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

# --- DEFINE STRATEGIES WITH DEPENDENCIES (Fully Refactored for Multiprocessing) ---
TIMEFRAME = CONFIG.get("timeframe", "D")
MULTIPLIER = CONFIG.get("timeframe_multiplier", 1)
STRATEGIES = {
        ## CHAMPION
        # The most aggressive version (fast entry AND fast exit)
        # "MA Confluence (Fast Entry & Exit)": {
        #     "logic": partial(ma_confluence_logic, 
        #                      ma_fast=10, 
        #                      ma_medium=20,
        #                      ma_slow=50,
        #                      entry_rule="fast_only",
        #                      exit_rule="fast_cross"),
        #     "dependencies": []
        # },



        # The original, most conservative version (default entry and exit)
        # "MA Confluence (Full Stack)": {
        #     "logic": partial(ma_confluence_logic, 
        #                      ma_fast=10, 
        #                      ma_medium=20,
        #                      ma_slow=50),
        #     "dependencies": []
        # },

        # # The aggressive exit version
        # "MA Confluence (Fast MA Exit)": {
        #     "logic": partial(ma_confluence_logic, 
        #                      ma_fast=10, 
        #                      ma_medium=20,
        #                      ma_slow=50,
        #                      exit_rule="fast_cross"),
        #     "dependencies": []
        # },

        # # The NEW, aggressive entry version
        # "MA Confluence (Fast Entry)": {
        #     "logic": partial(ma_confluence_logic, 
        #                      ma_fast=10, 
        #                      ma_medium=20,
        #                      ma_slow=50,
        #                      entry_rule="fast_only"), # <-- We specify the new entry rule
        #     "dependencies": []
        # },

        
        # # --- THIS IS THE NEW "SUPER STRATEGY" ---
        # "MA Confluence (Full Stack) w/ Regime Filter": {
        #     "logic": strategy_ma_confluence_regime,
        #     "dependencies": ['spy', 'vix'],
        #     "params": {
        #         "ma_fast": get_bars_for_period('10d', TIMEFRAME, MULTIPLIER),
        #         "ma_medium": get_bars_for_period('20d', TIMEFRAME, MULTIPLIER),
        #         "ma_slow": get_bars_for_period('50d', TIMEFRAME, MULTIPLIER)
        #     }
        # },
        
    #     "MA Confluence (Medium MA Exit)": {
    #         "logic": partial(ma_confluence_logic, 
    #                          ma_fast=get_bars_for_period('10d', TIMEFRAME, MULTIPLIER), 
    #                          ma_medium=get_bars_for_period('20d', TIMEFRAME, MULTIPLIER),
    #                          ma_slow=get_bars_for_period('50d', TIMEFRAME, MULTIPLIER),
    #                          exit_rule="medium_cross"), # <-- We specify the new rule here
    #         "dependencies": []
    #     },


    "SMA Crossover (20d/50d)": {
        "logic": partial(sma_crossover_logic, fast=get_bars_for_period('20d', TIMEFRAME, MULTIPLIER), slow=get_bars_for_period('50d', TIMEFRAME, MULTIPLIER)),
        "dependencies": []
    },
    "SMA Crossover (50d/200d)": {
        "logic": partial(sma_crossover_logic, fast=get_bars_for_period('50d', TIMEFRAME, MULTIPLIER), slow=get_bars_for_period('200d', TIMEFRAME, MULTIPLIER)),
        "dependencies": []
    },
    # "RSI Mean Reversion (14/30)": {
    #     "logic": partial(rsi_logic, length=get_bars_for_period('14d', TIMEFRAME, MULTIPLIER), oversold=30, exit_level=50),
    #     "dependencies": []
    # },
    # "RSI Mean Reversion (7/20)": {
    #     "logic": partial(rsi_logic, length=get_bars_for_period('7d', TIMEFRAME, MULTIPLIER), oversold=20, exit_level=50),
    #     "dependencies": []
    # },
    # "MACD Crossover (12/26/9)": {
    #     "logic": partial(macd_crossover_logic, fast=get_bars_for_period('12d', TIMEFRAME, MULTIPLIER), slow=get_bars_for_period('26d', TIMEFRAME, MULTIPLIER), signal=get_bars_for_period('9d', TIMEFRAME, MULTIPLIER)),
    #     "dependencies": []
    # },
    # "Stochastic Oscillator (14d)": {
    #     "logic": partial(stochastic_logic, length=get_bars_for_period('14d', TIMEFRAME, MULTIPLIER), k_smooth=3, oversold=20, exit_level=50),
    #     "dependencies": []
    # },
    # "OBV Trend (20d MA)": {
    #     "logic": partial(obv_logic, ma_length=get_bars_for_period('20d', TIMEFRAME, MULTIPLIER)),
    #     "dependencies": []
    # },
    # "MA20 Bounce (20d)": {
    #     "logic": partial(ma_bounce_logic, ma_length=get_bars_for_period('20d', TIMEFRAME, MULTIPLIER), filter_bars=2),
    #     "dependencies": []
    # },
    # "SMA 200 Trend Filter (200d)": {
    #     "logic": partial(sma_trend_filter_logic, ma_length=get_bars_for_period('200d', TIMEFRAME, MULTIPLIER)),
    #     "dependencies": []
    # },
    # "MACD+RSI Confirmation": {
    #     "logic": partial(
    #         macd_rsi_filter_logic, 
    #         macd_fast=get_bars_for_period('12d', TIMEFRAME, MULTIPLIER), 
    #         macd_slow=get_bars_for_period('26d', TIMEFRAME, MULTIPLIER), 
    #         macd_signal=get_bars_for_period('9d', TIMEFRAME, MULTIPLIER), 
    #         rsi_length=get_bars_for_period('14d', TIMEFRAME, MULTIPLIER)
    #     ),
    #     "dependencies": []
    # },

    # "ATR Trailing Stop w/ Trend Filter": {
    #     "logic": partial(
    #         atr_trailing_stop_with_trend_filter_logic, 
    #         entry_period=get_bars_for_period('20d', TIMEFRAME, MULTIPLIER), 
    #         atr_period=get_bars_for_period('14d', TIMEFRAME, MULTIPLIER), 
    #         atr_multiplier=3.0, 
    #         ma_length=get_bars_for_period('200d', TIMEFRAME, MULTIPLIER)
    #     ),
    #     "dependencies": []
    # },

    # # --- Bollinger Band Strategies ---
    
    # "Bollinger Band Fade (20d/2.0)": {
    #     "logic": partial(
    #         bollinger_band_logic, 
    #         length=get_bars_for_period('20d', TIMEFRAME, MULTIPLIER), 
    #         std_dev=2.0
    #     ), 
    #     "dependencies": []
    # },"Bollinger Band Fade (20d/2.5)": {
    #     "logic": partial(
    #         bollinger_band_logic, 
    #         length=get_bars_for_period('20d', TIMEFRAME, MULTIPLIER), 
    #         std_dev=2.5
    #     ), 
    #     "dependencies": []
    # },
    # "Bollinger Band Breakout (20d)": {"logic": partial(bollinger_breakout_logic, length=get_bars_for_period('20d', TIMEFRAME, MULTIPLIER), std_dev=2), "dependencies": []},
    # "Bollinger Band Squeeze (20d/40d)": {"logic": partial(bollinger_band_squeeze_logic, length=get_bars_for_period('20d', TIMEFRAME, MULTIPLIER), std_dev=2.0, squeeze_length=get_bars_for_period('40d', TIMEFRAME, MULTIPLIER)), "dependencies": []},
    
    # # # --- Chaikin Money Flow Strategies ---
    # "Chaikin Money Flow (10d)": {"logic": partial(chaikin_money_flow_logic, length=get_bars_for_period('10d', TIMEFRAME, MULTIPLIER), buy_threshold=0.00, sell_threshold=-0.05), "dependencies": []},
    # "Chaikin Money Flow (20d/0.05/0.05)": {
    #     "logic": partial(
    #         chaikin_money_flow_logic, 
    #         length=get_bars_for_period('20d', TIMEFRAME, MULTIPLIER), 
    #         buy_threshold=0.05, 
    #         sell_threshold=-0.05
    #         ), 
    #     "dependencies": []
    # },
    
    # # # --- Channel & ATR Strategies ---
    # "Donchian Breakout (20d/10d)": {"logic": partial(donchian_channel_breakout_logic, entry_period=get_bars_for_period('20d', TIMEFRAME, MULTIPLIER), exit_period=get_bars_for_period('10d', TIMEFRAME, MULTIPLIER)), "dependencies": []},
    # "Keltner Channel Breakout (20d)": {"logic": partial(keltner_channel_breakout_logic, ema_length=get_bars_for_period('20d', TIMEFRAME, MULTIPLIER), atr_length=get_bars_for_period('20d', TIMEFRAME, MULTIPLIER), atr_multiplier=2.0), "dependencies": []},
    # "ATR Trailing Stop (14/3)": {
    #     "logic": partial(
    #         atr_trailing_stop_logic, 
    #         atr_period=get_bars_for_period('14d', TIMEFRAME, MULTIPLIER), 
    #         atr_multiplier=3.0
    #     ), 
    #     "dependencies": []
    # },
    
    # # --- Strategies with Trend Filters ---
    #     "RSI (14d) w/ SMA200d Filter": {"logic": partial(rsi_with_trend_filter_logic, rsi_length=get_bars_for_period('14d', TIMEFRAME, MULTIPLIER), oversold=30, exit_level=50, ma_length=get_bars_for_period('200d', TIMEFRAME, MULTIPLIER)), "dependencies": []},
    #     "MACD+RSI Confirmation": {"logic": partial(macd_rsi_filter_logic, macd_fast=12, macd_slow=26, macd_signal=9, rsi_length=14), "dependencies": []},
    
    
    # "Bollinger Band Fade w/ SPY Trend Filter (20d/2.0)": {
    #     "logic": strategy_bollinger_fade_regime,
    #     "dependencies": ['spy'],
    #     "params": {
    #         "length": get_bars_for_period('20d', TIMEFRAME, MULTIPLIER),
    #         "std_dev": 2.0
    #     }
    # },
    # "Daily Overnight Hold (no weekend) w/ VIX Filter": {
    #     "logic": strategy_weekday_overnight_vix,
    #     "dependencies": ['vix']
    # },

    # # --- Calendar-Based Strategies (Unaffected by timeframe lookback) ---
    # "Hold The Week (Tue-Fri)": {"logic": hold_the_week_logic, "dependencies": []},
    # "Weekend Hold (Fri-Mon)": {"logic": weekend_hold_logic, "dependencies": []},


    # --- Lower Time Period Scalping Strategies
    # "1m EMA Scalp (5/15/50)": {
    #     "logic": partial(ema_scalping_logic, 
    #                     fast_ema_period=get_bars_for_period('5min', TIMEFRAME, MULTIPLIER), 
    #                     slow_ema_period=get_bars_for_period('15min', TIMEFRAME, MULTIPLIER),
    #                     trend_ema_period=get_bars_for_period('50min', TIMEFRAME, MULTIPLIER)),
    #     "dependencies": []
    # },
    # "1m RSI Extreme Fade (14/20/80)": {
    #     "logic": partial(rsi_scalping_logic, 
    #                     rsi_length=get_bars_for_period('14min', TIMEFRAME, MULTIPLIER), 
    #                     oversold_level=20, 
    #                     overbought_level=80),
    #     "dependencies": []
    # },
    # "1m BB Squeeze (10/2.0) / 20 period squeeze": {
    #         "logic": partial(bollinger_band_squeeze_logic, 
    #                          length=get_bars_for_period('10min', TIMEFRAME, MULTIPLIER), 
    #                          std_dev=2.0, 
    #                          squeeze_length=get_bars_for_period('20min', TIMEFRAME, MULTIPLIER)), 
    #         "dependencies": []
    #     },

    #     "1m BB Squeeze (20/2.0) / 50 period squeeze": {
    #         "logic": partial(bollinger_band_squeeze_logic, 
    #                          length=get_bars_for_period('20min', TIMEFRAME, MULTIPLIER), 
    #                          std_dev=2.0, 
    #                          squeeze_length=get_bars_for_period('50min', TIMEFRAME, MULTIPLIER)), 
    #         "dependencies": []
    #     },


    # -- Versions of EMA Crossover
    # --- FULL REGIME FILTER (Original) ---
    # "EMA Crossover w/ SPY+VIX Filter": {
    #     "logic": strategy_ema_regime,
    #     "dependencies": ['spy', 'vix'],
    #     "params": {
    #         "fast_ema": get_bars_for_period('20d', TIMEFRAME, MULTIPLIER),
    #         "slow_ema": get_bars_for_period('50d', TIMEFRAME, MULTIPLIER)
    #     }
    # },

    # # --- VARIATION 1: UNFILTERED ---
    # "EMA Crossover (Unfiltered)": {
    #     "logic": strategy_ema_unfiltered,
    #     "dependencies": [], # No dependencies
    #     "params": {
    #         "fast_ema": get_bars_for_period('20d', TIMEFRAME, MULTIPLIER),
    #         "slow_ema": get_bars_for_period('50d', TIMEFRAME, MULTIPLIER)
    #     }
    # },

    # # --- VARIATION 2: SPY-ONLY FILTER ---
    # "EMA Crossover w/ SPY-Only Filter": {
    #     "logic": strategy_ema_spy_only,
    #     "dependencies": ['spy'], # Only depends on SPY
    #     "params": {
    #         "fast_ema": get_bars_for_period('20d', TIMEFRAME, MULTIPLIER),
    #         "slow_ema": get_bars_for_period('50d', TIMEFRAME, MULTIPLIER)
    #     }
    # },

    # # --- VARIATION 3: VIX-ONLY FILTER ---
    # "EMA Crossover w/ VIX-Only Filter": {
    #     "logic": strategy_ema_vix_only,
    #     "dependencies": ['vix'], # Only depends on VIX
    #     "params": {
    #         "fast_ema": get_bars_for_period('20d', TIMEFRAME, MULTIPLIER),
    #         "slow_ema": get_bars_for_period('50d', TIMEFRAME, MULTIPLIER)
    #     }
    # },
}

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