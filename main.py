# main_portfolio.py (Cleaned up and fully refactored)

from datetime import datetime
import logging
import os
import sys
import time
import argparse
import numpy as np
import pandas as pd
from config import CONFIG
from services import get_data_service
from helpers.indicators import calculate_sma, calculate_rsi, calculate_atr
from helpers.registry import get_active_strategies
from helpers.portfolio_simulations import run_portfolio_simulation
from helpers.summary import generate_portfolio_summary_report, generate_per_portfolio_summary, generate_sensitivity_report
from helpers.sensitivity import build_param_grid, is_sweep_enabled, label_for_params
from helpers.correlation import run_correlation_analysis, DEFAULT_THRESHOLD
from helpers.monte_carlo import run_monte_carlo_simulation, analyze_mc_results
from tqdm import tqdm
from multiprocessing import Pool, cpu_count
import orjson
from helpers.caching import CACHE_DIR
from helpers.noise import inject_price_noise

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------
# --- WORKER INITIALIZER FOR MULTIPROCESSING ---
# --------------------------------------------------------------------
def init_worker(spy, vix, tnx, portfolio_data_for_worker, delisting_dates_for_worker):
    """
    Initializer for the multiprocessing pool.
    Makes large dataframes AND the current portfolio's data globally
    available to each worker process.
    """
    global spy_df_global, vix_df_global, tnx_df_global, portfolio_data_global, delisting_dates_global
    spy_df_global = spy
    vix_df_global = vix
    tnx_df_global = tnx
    portfolio_data_global = portfolio_data_for_worker
    delisting_dates_global = delisting_dates_for_worker

# --------------------------------------------------------------------

def run_single_simulation(args):
    """
    Function to run one combination of (portfolio, strategy, stop-loss).
    This version now uses globally initialized dataframes AND portfolio_data.
    """
    # Access ALL globally initialized data
    global spy_df_global, vix_df_global, tnx_df_global, portfolio_data_global, delisting_dates_global

    # 1. Unpack the arguments. `portfolio_data` has been REMOVED from the tuple.
    portfolio_name, name, logic_func, dependencies, stop_config, \
    spy_buy_and_hold_return, qqq_buy_and_hold_return, strategy_params, wfa_split_date, \
    spy_actual_start, spy_actual_end = args
    
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
            spy_df_global, vix_df_global, tnx_df_global, stop_config, delisting_dates_global
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

            # --- WFA ---
            if wfa_split_date and result.get('trade_log'):
                from helpers.wfa import split_trades as _split_trades, evaluate_wfa as _evaluate_wfa
                _is, _oos = _split_trades(result['trade_log'], wfa_split_date)
                result.update(_evaluate_wfa(_is, _oos, result['initial_capital']))
            else:
                result.update({'oos_pnl_pct': None, 'wfa_verdict': 'N/A'})

            # --- Rolling WFA ---
            _wfa_folds = CONFIG.get("wfa_folds")
            if _wfa_folds and int(_wfa_folds) >= 2 and result.get('trade_log') \
                    and spy_actual_start and spy_actual_end:
                from helpers.wfa_rolling import (
                    get_fold_dates as _get_fold_dates,
                    evaluate_rolling_wfa as _eval_rolling_wfa,
                )
                _min_fold = CONFIG.get("wfa_min_fold_trades", 5)
                _fold_dates = _get_fold_dates(spy_actual_start, spy_actual_end, int(_wfa_folds))
                result.update(_eval_rolling_wfa(
                    result['trade_log'], _fold_dates, result['initial_capital'], _min_fold
                ))
            else:
                result.update({'wfa_rolling_verdict': 'N/A'})

            # --- Expectancy and SQN (from R-Multiples) ---
            _r_vals = [t['RMultiple'] for t in result.get('trade_log', [])
                       if t.get('RMultiple') is not None]
            if len(_r_vals) >= 2:
                _exp = float(np.mean(_r_vals))
                _std = float(np.std(_r_vals, ddof=1))
                result['expectancy'] = _exp
                result['sqn'] = (_exp / _std) * np.sqrt(len(_r_vals)) if _std > 0 else 0.0
            else:
                result['expectancy'] = None
                result['sqn'] = None

            # --- Rolling Sharpe ---
            from helpers.simulations import calculate_rolling_sharpe as _rs
            _tl = result.get("portfolio_timeline")
            _w  = CONFIG.get("rolling_sharpe_window", 126)
            if _tl is not None and _w and len(_tl) > _w:
                _series = _rs(_tl, window=_w)
                _valid  = _series.dropna()
                result["rolling_sharpe_mean"]  = float(_valid.mean())  if len(_valid) >= 2 else None
                result["rolling_sharpe_min"]   = float(_valid.min())   if len(_valid) >= 2 else None
                result["rolling_sharpe_final"] = float(_valid.iloc[-1]) if len(_valid) >= 1 else None
            else:
                result["rolling_sharpe_mean"] = result["rolling_sharpe_min"] = result["rolling_sharpe_final"] = None

            # --- Regime Heatmap ---
            from helpers.regime import build_regime_heatmap as _build_heatmap
            result["regime_heatmap"] = _build_heatmap(
                result.get("trade_log", []),
                vix_df_global,
                result.get("initial_capital", CONFIG["initial_capital"]),
            )

            return result
            
    except Exception:
        import traceback
        tqdm.write(f"\n--- FATAL ERROR IN WORKER ---\nStrategy: {name}\nPortfolio: {portfolio_name}\nTraceback:\n{traceback.format_exc()}\n---------------------------\n")
        return None

def main():
    # --- INIT WIZARD ---
    import argparse as _argparse
    _parser = _argparse.ArgumentParser(add_help=False)
    _parser.add_argument("--init", action="store_true")
    _parser.add_argument("--dry-run", action="store_true")
    _parser.add_argument("--all", action="store_true")
    _known, _ = _parser.parse_known_args()
    if _known.init:
        from helpers.init_wizard import run_init_wizard
        run_init_wizard()
        return
    # --- END INIT WIZARD ---

    # --- S1: API KEY CHECK ---
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    if CONFIG.get("data_provider", "polygon").lower() == "polygon":
        api_key = os.environ.get("POLYGON_API_KEY")
        if not api_key:
            print(
                "\n[ERROR] POLYGON_API_KEY is not set.\n"
                "  1. Copy .env.example to .env in the project root\n"
                "  2. Add your key: POLYGON_API_KEY=your_key_here\n"
                "  Or set it as a system environment variable.\n"
            )
            sys.exit(1)
    # --- END S1 ---

    # --- S2: CONFIG VALIDATION ---
    errors = []

    from datetime import datetime as _dt
    try:
        start = _dt.strptime(CONFIG["start_date"], "%Y-%m-%d")
        end = _dt.strptime(CONFIG["end_date"], "%Y-%m-%d")
        if start >= end:
            errors.append(f"  - start_date ({CONFIG['start_date']}) must be before end_date ({CONFIG['end_date']})")
    except ValueError as e:
        errors.append(f"  - Invalid date format in config: {e}")

    alloc = CONFIG.get("allocation_per_trade", 0)
    if not (0 < alloc <= 1.0):
        errors.append(f"  - allocation_per_trade ({alloc}) must be between 0 (exclusive) and 1.0 (inclusive)")

    if not CONFIG.get("portfolios") and not CONFIG.get("symbols_to_test"):
        errors.append("  - portfolios is empty. Add at least one portfolio entry to run.")

    if errors:
        print("\n[ERROR] Invalid configuration in config.py:")
        for e in errors:
            print(e)
        print()
        sys.exit(1)
    # --- END S2 ---

    # --- ARGUMENT PARSING & FOLDER SETUP (No changes) ---
    parser = argparse.ArgumentParser(description="Portfolio Backtester")
    parser.add_argument("--name", type=str, help="An optional name for the backtest run, used as a prefix for the report folder.")
    parser.add_argument("--dry-run", action="store_true", help="Validate config and print run summary without fetching data or running simulations.")
    parser.add_argument("--verbose", action="store_true", help="Show all table columns in the summary (default: compact 7-column view).")
    args = parser.parse_args()
    CONFIG["verbose_output"] = args.verbose
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_folder_name = f"{args.name}_{timestamp}" if args.name else timestamp
    start_time = time.monotonic()

    run_base_dir = os.path.join("output", "runs", run_folder_name)
    os.makedirs(os.path.join(run_base_dir, "logs"), exist_ok=True)

    # --- C1: CONFIG SNAPSHOT ---
    import json as _json
    def _config_serializer(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return str(obj)

    try:
        _snapshot_path = os.path.join(run_base_dir, "config_snapshot.json")
        with open(_snapshot_path, "w", encoding="utf-8") as _f:
            _json.dump(CONFIG, _f, indent=2, default=_config_serializer)
    except Exception as _e:
        print(f"[WARNING] Could not write config_snapshot.json: {_e}")
    # --- END C1 ---

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(run_base_dir, "logs", f"run_{timestamp}.log")),
        ],
    )

    # --- Single-asset mode: wrap symbols_to_test as a synthetic portfolio ---
    _portfolios = CONFIG.get("portfolios") or {}
    if not _portfolios and CONFIG.get("symbols_to_test"):
        _portfolios = {"Single Asset": CONFIG["symbols_to_test"]}

    # --- U1: RUN SUMMARY ---
    total_stop_configs = len(CONFIG.get("stop_loss_configs", []))
    total_strategies = len(get_active_strategies())

    # Count total symbols across all portfolios to estimate task count
    _symbol_counts = {}
    for _pname, _pvalue in _portfolios.items():
        if isinstance(_pvalue, list):
            _symbol_counts[_pname] = len(_pvalue)
        elif isinstance(_pvalue, str) and _pvalue.endswith(".json"):
            try:
                import orjson as _orjson
                with open(os.path.join("tickers_to_scan", _pvalue), "rb") as _f:
                    _symbol_counts[_pname] = len(_orjson.loads(_f.read()))
            except Exception:
                _symbol_counts[_pname] = "?"
        elif isinstance(_pvalue, str) and _pvalue.startswith("norgate:"):
            _symbol_counts[_pname] = "? (Norgate)"
        else:
            _symbol_counts[_pname] = "?"

    _total_symbols = sum(v for v in _symbol_counts.values() if isinstance(v, int))
    _total_tasks = (
        _total_symbols * total_strategies * total_stop_configs
        if isinstance(_total_symbols, int) else "?"
    )

    logger.info("=" * 60)
    logger.info("  RUN SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Run ID        : {run_folder_name}")
    logger.info(f"  Data provider : {CONFIG.get('data_provider', 'polygon')}")
    logger.info(f"  Period Selected : {CONFIG['start_date']} -> {CONFIG['end_date']}")
    logger.info(f"  Timeframe     : {CONFIG.get('timeframe', 'D')} x {CONFIG.get('timeframe_multiplier', 1)}")
    logger.info(f"  Strategies    : {total_strategies}")
    logger.info(f"  Stop configs  : {total_stop_configs}")
    logger.info("-" * 60)
    for _pname, _count in _symbol_counts.items():
        logger.info(f"  Portfolio     : {_pname} ({_count} symbols)")
    logger.info("-" * 60)
    logger.info(f"  Total symbols : {_total_symbols}")
    logger.info(f"  Total tasks   : {_total_tasks}  (symbols x strategies x stop configs)")
    logger.info("=" * 60)
    _noise_pct = CONFIG.get("noise_injection_pct", 0.0)
    if _noise_pct > 0:
        logger.info("")
        logger.info("*" * 60)
        logger.info(f"  [STRESS TEST MODE] Injecting {_noise_pct:.1%} random noise into OHLC price data")
        logger.info("  High/Low bounds are enforced after noise — no invalid candlesticks")
        logger.info("*" * 60)
    # --- END U1 ---

    if args.dry_run:
        logger.info("[DRY RUN] Exiting before data fetch. No simulations will run.")
        sys.exit(0)

    # --- D1: STALE CACHE WARNING ---
    import glob
    from datetime import timedelta
    _cache_dir = "data_cache"
    _stale_threshold = timedelta(days=7)
    _now = datetime.now()

    # Ensure the directory exists before globbing to avoid errors in clean environments
    if os.path.exists(_cache_dir):
        _stale = [
            f for f in glob.glob(os.path.join(_cache_dir, "*.parquet"))
            if _now - datetime.fromtimestamp(os.path.getmtime(f)) > _stale_threshold
        ]
        if _stale:
            logger.warning(
                f"  -> STALE CACHE: {len(_stale)} file(s) in '{_cache_dir}' are older than 7 days. "
                "Delete data_cache/ to force a fresh fetch."
            )
    # --- END D1 ---

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
        _spy_actual_start = spy_df.index.min().strftime("%Y-%m-%d")
        _spy_actual_end   = spy_df.index.max().strftime("%Y-%m-%d")
        logger.info("-" * 60)
        logger.info(f"  Actual Data Period : {_spy_actual_start} -> {_spy_actual_end}  (via SPY)")
        logger.info("-" * 60)
        logger.info(f"SPY B&H: {spy_buy_and_hold_return:.2%}, QQQ B&H: {qqq_buy_and_hold_return:.2%}")
    except Exception as e:
        logger.error(f"FATAL: Could not fetch dependency data: {e}")
        return

    # --- WFA SPLIT DATE ---
    _wfa_ratio = CONFIG.get("wfa_split_ratio")
    wfa_split_date = None
    if _wfa_ratio and 0 < float(_wfa_ratio) < 1:
        from helpers.wfa import get_split_date as _get_split_date
        # Pass spy_df and CONFIG for intraday bar-count splitting (Phase 2)
        wfa_split_date = _get_split_date(_spy_actual_start, _spy_actual_end, float(_wfa_ratio), df=spy_df, config=CONFIG)
        logger.info(
            f"  WFA split date   : {wfa_split_date}  "
            f"(IS: {_spy_actual_start} -> {wfa_split_date} | OOS: {wfa_split_date} -> {_spy_actual_end})"
        )
    else:
        logger.info("  WFA              : disabled (wfa_split_ratio not set)")
    # --- END WFA SPLIT DATE ---

    # --- START OF MODIFIED LOGIC ---

    all_portfolio_results = [] # To gather results from all portfolios

    logger.info("=" * 25 + " PROCESSING PORTFOLIOS " + "=" * 25)
    noise_data_saved = False  # Save one noise sample CSV per run (first symbol with noise > 0)
    # Loop through each portfolio sequentially
    for portfolio_name, value in _portfolios.items():
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

        MIN_BARS = CONFIG.get("min_bars_required", 250)
        skipped_symbols = []
        portfolio_data = {}
        for symbol in tqdm(symbols, desc="  -> Fetching & Preparing Data", unit=" symbols"):
            df = data_fetcher(symbol, CONFIG["start_date"], CONFIG["end_date"], CONFIG)
            if df is not None and not df.empty:
                if len(df) < MIN_BARS:
                    skipped_symbols.append((symbol, len(df)))
                    continue
                # --- NOISE INJECTION (stress test) ---
                _noise_pct = CONFIG.get("noise_injection_pct", 0.0)
                if _noise_pct > 0:
                    df_noisy = inject_price_noise(df, _noise_pct)
                    if not noise_data_saved:
                        _sample_clean = df[["Open", "High", "Low", "Close"]].tail(30).copy()
                        _sample_noisy = df_noisy[["Open", "High", "Low", "Close"]].tail(30).copy()
                        _sample_clean.columns = [f"Clean_{c}" for c in _sample_clean.columns]
                        _sample_noisy.columns = [f"Noisy_{c}" for c in _sample_noisy.columns]
                        _noise_sample = pd.concat([_sample_clean, _sample_noisy], axis=1)
                        _noise_sample.insert(0, "Symbol", symbol)
                        _noise_csv_path = os.path.join(run_base_dir, "noise_sample_data.csv")
                        _noise_sample.to_csv(_noise_csv_path)
                        noise_data_saved = True
                    df = df_noisy
                # --- FEATURE ENGINEERING ---
                # These columns are captured at trade entry time for each
                # position and stored in the trade log for later analysis.
                # All calculations use .shift(1) where needed to ensure
                # no look-ahead bias — indicators are based only on data
                # available at the close of the previous bar.

                # RSI (14-period)
                _delta = df['Close'].diff()
                _gain = _delta.where(_delta > 0, 0).ewm(alpha=1/14, adjust=False).mean()
                _loss = (-_delta.where(_delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
                df['RSI_14'] = 100 - (100 / (1 + (_gain / _loss)))

                # ATR (14-period) as % of close
                _hl = df['High'] - df['Low']
                _hc = (df['High'] - df['Close'].shift()).abs()
                _lc = (df['Low'] - df['Close'].shift()).abs()
                _atr = pd.concat([_hl, _hc, _lc], axis=1).max(axis=1)
                df['ATR_14'] = _atr.ewm(alpha=1/14, adjust=False).mean()
                df['ATR_14_pct'] = df['ATR_14'] / df['Close']

                # Distance from 200-day SMA as % of close
                df['SMA200_dist_pct'] = (df['Close'] - df['Close'].rolling(200).mean()) / df['Close'].rolling(200).mean()

                # Volume spike: today's volume vs 20-day average volume
                df['Volume_Spike'] = df['Volume'] / df['Volume'].rolling(20).mean()

                # --- END FEATURE ENGINEERING ---
                portfolio_data[symbol] = df

        if skipped_symbols:
            logger.warning(
                f"  -> Skipped {len(skipped_symbols)} symbol(s) with fewer than {MIN_BARS} bars: "
                + ", ".join(f"{s} ({n} bars)" for s, n in skipped_symbols)
            )

        if not portfolio_data:
            logger.warning(f"Could not fetch data for any symbols in '{portfolio_name}'. Skipping.")
            continue

        # --- FETCH DELISTING DATES (if survivorship bias handling is enabled) ---
        delisting_dates = {}
        if CONFIG.get("include_delisted", False):
            from helpers.survivorship import get_delisting_dates
            logger.info(f"  -> Fetching delisting dates for {len(symbols)} symbols...")
            delisting_dates = get_delisting_dates(symbols, CONFIG["data_provider"], CONFIG)
            if delisting_dates:
                logger.info(f"  -> Found {len(delisting_dates)} delisted symbols: {', '.join(list(delisting_dates.keys())[:10])}{'...' if len(delisting_dates) > 10 else ''}")
            else:
                logger.info(f"  -> No delisted symbols found (or provider doesn't support delisting data).")

        # --- Generate tasks for THIS portfolio, WITHOUT the large `portfolio_data` ---
        tasks_for_this_portfolio = []
        for strat_name, strategy_config in get_active_strategies().items():
            base_params = strategy_config.get("params", {})
            param_variants = build_param_grid(base_params) if is_sweep_enabled() and base_params else [base_params]

            for variant_params in param_variants:
                if len(param_variants) > 1:
                    display_name = f"{strat_name} [{label_for_params(base_params, variant_params)}]"
                else:
                    display_name = strat_name

                for stop_config in CONFIG['stop_loss_configs']:
                    task_args = (
                        portfolio_name, display_name, strategy_config["logic"],
                        strategy_config.get("dependencies", []),
                        stop_config, spy_buy_and_hold_return, qqq_buy_and_hold_return,
                        variant_params,
                        wfa_split_date,
                        _spy_actual_start, _spy_actual_end,
                    )
                    tasks_for_this_portfolio.append(task_args)

        if not tasks_for_this_portfolio:
            logger.warning(f"No tasks generated for {portfolio_name}.")
            continue

        # --- Create a NEW Pool initialized with THIS portfolio's data ---
        logger.info("=" * 15 + f" RUNNING SIMULATIONS FOR '{portfolio_name}' " + "=" * 15)
        logger.info(f"Found {len(tasks_for_this_portfolio)} tasks. Using up to {cpu_count()} CPU cores.")
        
        # Pass `portfolio_data` and `delisting_dates` during initialization, not with each task
        init_args = (spy_df, vix_df, tnx_df, portfolio_data, delisting_dates)

        with Pool(processes=cpu_count(), initializer=init_worker, initargs=init_args) as p:
            import time as _time
            _results = []
            _start_pool = _time.monotonic()
            _total = len(tasks_for_this_portfolio)
            _checkpoints = {max(1, int(_total * pct)) for pct in [0.1, 0.25, 0.5, 0.75, 0.9]}

            for _i, _r in enumerate(tqdm(p.imap(run_single_simulation, tasks_for_this_portfolio), total=_total, desc="  -> Running sims"), start=1):
                _results.append(_r)
                if _i in _checkpoints:
                    _elapsed = _time.monotonic() - _start_pool
                    _rate = _i / _elapsed
                    _remaining = (_total - _i) / _rate if _rate > 0 else 0
                    logger.info(f"  -> Progress: {_i}/{_total} tasks done | Elapsed: {_elapsed:.0f}s | ETA: {_remaining:.0f}s remaining")

            results_this_portfolio = _results
        
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
        # --- Strategy Correlation Analysis (run first so matrix is available for summary) ---
        portfolio_name_safe = p_name.replace(" ", "_")
        corr_csv_path = os.path.join(
            "output", "runs", run_folder_name,
            f"{portfolio_name_safe}_strategy_correlation.csv"
        )
        corr_matrix = None
        try:
            corr_matrix, high_pairs = run_correlation_analysis(p_results, corr_csv_path)
            logger.info(f"  Correlation matrix saved: {corr_csv_path}")
            if high_pairs:
                border = "!" * 70
                logger.warning(border)
                logger.warning(f"  HIGH CORRELATION ALERT  |  Portfolio: {p_name}")
                logger.warning(f"  Threshold: |r| > {DEFAULT_THRESHOLD:.2f} — strategies below may overlap significantly")
                logger.warning(border)
                for strat_a, strat_b, corr_val in high_pairs:
                    logger.warning(
                        f"    '{strat_a}' <-> '{strat_b}'  r={corr_val:+.2f}"
                        "  [HIGH OVERLAP — consider removing one]"
                    )
                logger.warning(border)
        except Exception as _corr_err:
            logger.warning(f"  Correlation analysis skipped for '{p_name}': {_corr_err}")

        generate_per_portfolio_summary(p_results, p_name, spy_buy_and_hold_return, qqq_buy_and_hold_return, run_folder_name, corr_matrix=corr_matrix)

        from helpers.regime import print_regime_heatmap as _print_heatmap
        for _r in p_results:
            if _r.get("regime_heatmap") is not None:
                _print_heatmap(_r["regime_heatmap"], _r.get("Strategy", "Unknown"))

    duration_seconds = time.monotonic() - start_time
    generate_portfolio_summary_report(all_portfolio_results, duration_seconds, run_folder_name)
    generate_sensitivity_report(all_portfolio_results, run_folder_name)

    if CONFIG.get("export_ml_features", False):
        from helpers.ml_export import export_trade_features as _ml_export
        _ml_path = os.path.join("output", "runs", run_folder_name, "ml_features.parquet")
        _n_rows = _ml_export(all_portfolio_results, _ml_path)
        if _n_rows > 0:
            logger.info(f"  ML feature export: {_n_rows} trades -> {_ml_path}")

    mins, secs = divmod(duration_seconds, 60)
    logger.info(f"All portfolio simulations complete in {int(mins)}m {secs:.2f}s.")

if __name__ == "__main__":
    main()