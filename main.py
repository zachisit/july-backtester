# main_portfolio.py (Cleaned up and fully refactored)

from datetime import datetime
import logging
import os
import sys
import time
import numpy as np
import pandas as pd
from config import CONFIG
from services import get_data_service
from helpers.indicators import calculate_sma, calculate_rsi, calculate_atr
from helpers.registry import get_active_strategies
from helpers.portfolio_simulations import run_portfolio_simulation
from helpers.summary import generate_portfolio_summary_report, generate_per_portfolio_summary, generate_sensitivity_report
from helpers.llm_verdict import generate_llm_verdict
from helpers.sensitivity import build_param_grid, is_sweep_enabled, label_for_params
from helpers.correlation import run_correlation_analysis, DEFAULT_THRESHOLD
from helpers.monte_carlo import run_monte_carlo_simulation, analyze_mc_results
from tqdm import tqdm
from multiprocessing import Pool, cpu_count
import orjson
from helpers.caching import CACHE_DIR
from helpers.noise import inject_price_noise

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

logger = logging.getLogger(__name__)


def _dependency_warning_for_failed_fetch(symbol: str, dependencies: dict) -> str | None:
    """Build a warning explaining a failed comparison-ticker fetch's downstream impact.

    Returns ``None`` when *symbol* isn't a strategy dependency (e.g. a
    benchmark-only ticker like QQQ) -- a plain fetch-failure warning already
    covers that case. When it *is* a dependency (e.g. I:VIX backing
    ``vix_df``), a failed fetch means the strategy receives ``None`` for that
    kwarg and any regime/filter gate ANDed on it fails closed (zero trades)
    rather than raising -- easy to misread as "no edge" instead of "no data".
    """
    dep_keys = [k for k, v in dependencies.items() if v == symbol]
    if not dep_keys:
        return None
    return (
        f"  -> '{symbol}' backs the {'/'.join(dep_keys)}_df dependency. Any active "
        f"strategy declaring dependencies={dep_keys} will receive {dep_keys[0]}_df=None "
        "and its regime/filter gates fail CLOSED (zero trades) rather than raising — "
        "check for a silently-empty result before concluding the strategy has no edge."
    )


def _pick_reference_df(comparison_dfs: dict) -> pd.DataFrame:
    """Return the reference DataFrame used to derive the actual data period.

    Prefers SPY when present.  Falls back to the first available ticker.
    Uses an explicit ``is None`` check to avoid the ``bool(DataFrame)``
    ambiguity error that arises from the ``or`` operator on DataFrames.
    """
    spy = comparison_dfs.get("SPY")
    if spy is not None:
        return spy
    return next(iter(comparison_dfs.values()))


# Module-level defaults so workers can reference these globals safely even in
# test contexts where init_worker was never called.
comparison_dfs_global = None
benchmark_returns_global = None
dependency_map_global = None
portfolio_data_global = None
delisting_dates_global = None
pit_member_masks_global = None
intrabar_data_global = None

# --------------------------------------------------------------------
# --- WORKER INITIALIZER FOR MULTIPROCESSING ---
# --------------------------------------------------------------------
def init_worker(comparison_dfs_dict, benchmark_returns_dict, dependency_map_dict, portfolio_data_for_worker, delisting_dates_for_worker=None, pit_member_masks_dict=None, intrabar_data_for_worker=None):
    """
    Initializer for the multiprocessing pool.
    Makes comparison ticker DataFrames, benchmark returns, dependency symbol map,
    the current portfolio's data, delisting dates, optional PIT membership masks,
    and optional intraday (sub-bar) data globally available to each worker process.
    """
    global comparison_dfs_global, benchmark_returns_global, dependency_map_global, portfolio_data_global, delisting_dates_global, pit_member_masks_global, intrabar_data_global
    comparison_dfs_global = comparison_dfs_dict
    benchmark_returns_global = benchmark_returns_dict
    dependency_map_global = dependency_map_dict
    portfolio_data_global = portfolio_data_for_worker
    delisting_dates_global = delisting_dates_for_worker
    pit_member_masks_global = pit_member_masks_dict
    intrabar_data_global = intrabar_data_for_worker


def _resolve_intrabar_source(path):
    """Resolve ``intrabar_parquet_source`` to a portable absolute path.

    Expands ``~`` and environment variables, and resolves a relative path
    against the project root — so a config can point at a repo-relative file
    (e.g. ``"data/nq_1min.parquet"``) or a ``$ENV``/``~`` path that works on any
    machine, instead of a contributor-local absolute path (e.g. a Windows
    ``C:\\Users\\...`` path that silently breaks everywhere else).
    """
    resolved = os.path.expanduser(os.path.expandvars(str(path)))
    if not os.path.isabs(resolved):
        resolved = os.path.join(os.path.dirname(os.path.abspath(__file__)), resolved)
    return resolved


def _build_intrabar_data(portfolio_data, config):
    """Fetch finer-resolution (intraday) bars per symbol for sub-bar stop resolution.

    Returns ``{symbol: intraday_df}`` for symbols whose provider can serve intraday
    data; symbols that can't (or error) are omitted and the engine simply no-ops for
    them. Heavy and provider/plan-limited, so only called when ``intrabar_resolution``
    is enabled. Uses ``intrabar_timeframe`` / ``intrabar_multiplier`` (default MIN/1).

    If ``intrabar_parquet_source`` is set, bypasses the normal per-symbol data-provider
    fetch entirely and instead loads one 1-minute OHLC parquet file directly, applying
    it to every symbol in the portfolio. This is for single-symbol research (e.g. the
    Sleeve A NQ reconciliation) where the CSV provider has no notion of timeframe (it
    always re-reads the same daily-bar file regardless of `timeframe`/`timeframe_multiplier`)
    and the real sub-minute source lives outside `csv_data_dir` as a parquet file.

    The path is resolved portably via :func:`_resolve_intrabar_source` (``~`` /
    ``$ENV`` expansion, relative paths resolved against the project root). If the
    resolved file does not exist, the run warns and falls back to the per-symbol
    provider fetch instead of silently disabling intrabar resolution.
    """
    parquet_source = config.get("intrabar_parquet_source")
    resolved_source = _resolve_intrabar_source(parquet_source) if parquet_source else None
    if resolved_source and not os.path.exists(resolved_source):
        # Portability guard: a config pointing at a missing/contributor-local
        # file (e.g. a Windows absolute path on another machine) no longer
        # silently disables intrabar resolution -- warn and fall through to the
        # normal per-symbol data-provider fetch below.
        logger.warning(
            f"  -> intrabar_parquet_source '{parquet_source}' (resolved: '{resolved_source}') "
            f"not found; falling back to the per-symbol data provider for intraday bars. "
            f"Point it at a repo-relative or $ENV/~ path for a portable config.")
        resolved_source = None
    if resolved_source:
        try:
            raw = pd.read_parquet(resolved_source).sort_index()
            idx = raw.index
            idx_naive = idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx
            idf = pd.DataFrame({
                "Open": raw["open"].to_numpy(), "High": raw["high"].to_numpy(),
                "Low": raw["low"].to_numpy(), "Close": raw["close"].to_numpy(),
            }, index=idx_naive)
            idf.index.name = "Datetime"
        except Exception as e:
            # Covers read failures AND a mismatched column schema (e.g. "Open"
            # instead of "open") -- both are non-fatal here: the caller treats
            # an empty dict as "no intrabar data available" and no-ops.
            logger.warning(f"  -> intrabar_parquet_source failed to load '{resolved_source}': {e}")
            return {}
        out = {symbol: idf for symbol in portfolio_data}
        if len(portfolio_data) > 1:
            logger.warning(
                f"  -> intrabar_parquet_source applies the SAME single-symbol parquet file "
                f"to all {len(portfolio_data)} symbols in this portfolio ({len(portfolio_data)} "
                f"symbols); this path is intended for single-symbol research runs only.")
        logger.info(f"  -> Sub-bar resolution: loaded 1-min parquet source ({len(idf)} rows) "
                    f"for {len(out)} symbol(s)")
        return out

    tf = config.get("intrabar_timeframe", "MIN")
    mult = config.get("intrabar_multiplier", 1)
    intra_cfg = {**config, "timeframe": tf, "timeframe_multiplier": mult}
    fetcher = get_data_service()
    out = {}
    for symbol in portfolio_data:
        try:
            idf = fetcher(symbol, config["start_date"], config["end_date"], intra_cfg)
        except Exception as e:
            logger.warning(f"  -> intrabar fetch failed for '{symbol}': {e}")
            idf = None
        if idf is not None and not idf.empty:
            out[symbol] = idf
    if out:
        logger.info(f"  -> Sub-bar resolution: loaded intraday data for {len(out)}/{len(portfolio_data)} symbols")
    else:
        logger.warning("  -> intrabar_resolution enabled but no intraday data available; stop fills unchanged")
    return out

# --------------------------------------------------------------------

def _build_strat_name(name, stop_config):
    """Build the display name for a strategy given its stop-loss config.

    Percentage and ATR stops get a descriptive suffix; every other stop
    type (``none``, ``points``, ``signal_bar``, ``trailing_atr`` …) — and a
    config with no ``type`` key at all — leaves the base name unchanged,
    matching the engine, which resolves the type via ``.get("type", "none")``.

    This helper must never raise on a config the *engine* would happily run,
    otherwise the label crashes the worker before the simulation starts and
    the whole run completes with zero results (issue #309). It therefore
    mirrors the engine's own defaults for every key it reads:

    - ATR ``period`` defaults to 14 — the engine always uses the ``ATR_14``
      column; the documented shape ``{"type": "atr", "multiplier": 2.0}``
      carries no ``period`` (only the CLI shorthand ``atr:14:3.0`` injects
      one). Reading ``stop_config['period']`` unconditionally was the #309
      crash.
    - ATR ``multiplier`` defaults to 3.0 (``portfolio_simulations`` uses the
      same default at its sizing/stop-level sites).
    - percentage ``value`` defaults to 0.05 (ditto).
    """
    stop_type = stop_config.get('type')
    if stop_type == 'percentage':
        return f"{name} w/ {stop_config.get('value', 0.05):.0%} SL"
    if stop_type == 'atr':
        multiplier = stop_config.get('multiplier', 3.0)
        period = stop_config.get('period', 14)
        return f"{name} w/ {multiplier}x ATR({period}) SL"
    return name

# --------------------------------------------------------------------

def run_single_simulation(args):
    """
    Function to run one combination of (portfolio, strategy, stop-loss).
    This version now uses globally initialized dataframes AND portfolio_data.
    """
    # Access ALL globally initialized data
    global comparison_dfs_global, benchmark_returns_global, dependency_map_global, portfolio_data_global, delisting_dates_global, pit_member_masks_global, intrabar_data_global

    # 1. Unpack the arguments. `portfolio_data` has been REMOVED from the tuple.
    portfolio_name, name, logic_func, dependencies, stop_config, \
    strategy_params, wfa_split_date, spy_actual_start, spy_actual_end = args

    # Assign the global data to a local variable for clarity
    portfolio_data = portfolio_data_global

    # Extract individual DataFrames for run_portfolio_simulation (legacy signature)
    spy_df_local = comparison_dfs_global.get(dependency_map_global.get("spy"))
    vix_df_local = comparison_dfs_global.get(dependency_map_global.get("vix"))
    tnx_df_local = comparison_dfs_global.get(dependency_map_global.get("tnx"))

    try:
        strat_name = _build_strat_name(name, stop_config)

        base_signals_with_dfs = {}
        for symbol, df in portfolio_data.items():
            kwargs = {}

            # Always inject the ticker being processed so per-symbol /
            # event-driven strategies (e.g. one keyed on a per-ticker
            # earnings-date table) can identify which symbol's DataFrame
            # they are evaluating. Backward-compatible: existing strategies
            # take (df, **kwargs) and ignore unknown keys.
            kwargs["symbol"] = symbol

            # Dynamic dependency injection
            for dep_key in dependencies:
                dep_symbol = dependency_map_global.get(dep_key)
                if dep_symbol and dep_symbol in comparison_dfs_global:
                    dep_df = comparison_dfs_global[dep_symbol]
                    kwargs[f'{dep_key}_df'] = dep_df.reindex(df.index, method='ffill')

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

        # --- PIT SIGNAL GATING ---
        # When the portfolio was built from a ``pit:`` universe, apply two filters:
        # 1. Block long entries (Signal==1) on dates when the symbol is not an index member.
        # 2. Inject exit signals (Signal==-1) on the first trading day after a symbol
        #    is removed from the index, so open positions are closed promptly.
        # This runs per-simulation but mask computation is O(1) per date (precomputed).
        if pit_member_masks_global is not None:
            for symbol, sig in list(final_signals.items()):
                mask = pit_member_masks_global.get(symbol)
                if mask is None:
                    continue
                aligned = mask.reindex(sig.index, fill_value=False)
                new_sig = sig.copy()
                new_sig.loc[(sig == 1) & ~aligned] = 0
                was_member = aligned.shift(1, fill_value=False)
                removal_days = ~aligned & was_member
                new_sig.loc[removal_days] = -1
                final_signals[symbol] = new_sig
        # --- END PIT SIGNAL GATING ---

        # Call the simulation, passing the stop_config and using the global dataframes.
        result = run_portfolio_simulation(
            portfolio_data, final_signals, CONFIG["initial_capital"], CONFIG["allocation_per_trade"],
            spy_df_local, vix_df_local, tnx_df_local, stop_config,
            delisting_dates=delisting_dates_global,
            intrabar_data=intrabar_data_global,
        )
        
        if result is None: return None
        
        if result and result.get('trade_pnl_list'):
            result['Strategy'] = strat_name
            result['Portfolio'] = portfolio_name
            
            if result.get('Trades', 0) > 0:
                if result['Trades'] >= CONFIG.get("min_trades_for_mc", 10):
                    # MC resampling: "auto" ties the method to the strategy's
                    # asset-class smoothness profile (concentrated_futures ->
                    # block-bootstrap, which preserves the streak clustering those
                    # strategies live on; else i.i.d.). Explicit "iid"/"block" pass
                    # through unchanged. Applied via a scoped CONFIG override because
                    # run_monte_carlo_simulation reads CONFIG["mc_sampling"] directly
                    # (helpers/monte_carlo.py is Do-Not-Touch).
                    from helpers.smoothness_profiles import (
                        resolve_profile_name as _rpn, resolve_mc_sampling as _rms,
                    )
                    _mc_profile = _rpn(list(portfolio_data.keys()), CONFIG)
                    _eff_sampling = _rms(CONFIG.get("mc_sampling", "iid"), _mc_profile)
                    result["mc_sampling_effective"] = _eff_sampling
                    _saved_sampling = CONFIG.get("mc_sampling", "iid")
                    try:
                        CONFIG["mc_sampling"] = _eff_sampling
                        mc_sim_results = run_monte_carlo_simulation(
                            result['trade_pnl_list'], initial_equity=result['initial_capital'],
                            num_simulations=CONFIG["num_mc_simulations"]
                        )
                    finally:
                        CONFIG["mc_sampling"] = _saved_sampling
                    mc_analysis = analyze_mc_results(result, mc_sim_results)
                    result.update(mc_analysis)
                else:
                    result.update({"mc_verdict": "N/A (few trades)", "mc_score": -999})
            else:
                result.update({"mc_verdict": "N/A (no trades)", "mc_score": -999, "max_drawdown": 0, "calmar_ratio": 0, "sharpe_ratio": 0, "profit_factor": 0, "win_rate": 0, "avg_trade_duration": 0})

            # Dynamic benchmark comparisons
            for benchmark_label, benchmark_return in benchmark_returns_global.items():
                result[f'vs_{benchmark_label.lower().replace(" ", "_")}_benchmark'] = result.get('pnl_percent', 0.0) - benchmark_return

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
                vix_df_local,
                result.get("initial_capital", CONFIG["initial_capital"]),
            )

            # --- Smoothness verdict (surfaced in summary tables, terminal verdict block,
            # PDF tearsheet) — same compute as helpers/llm_verdict.compute_smoothness.
            # The profile is chosen per strategy from the portfolio's instrument asset
            # class (or an explicit config["smoothness_profile"]) so concentrated /
            # futures strategies are judged against the right baseline, not equities. ---
            from helpers.llm_verdict import compute_smoothness as _compute_smoothness
            from helpers.smoothness_profiles import resolve_profile_name, mc_sampling_caveat
            _profile = resolve_profile_name(list(portfolio_data.keys()), CONFIG)
            result["smoothness_profile"] = _profile
            _smooth = _compute_smoothness(result.get("portfolio_timeline"), _profile)
            if _smooth:
                result["smooth_verdict"] = _smooth.get("smooth_verdict", "N/A")
                result["smooth_notes"] = _smooth.get("smooth_notes", []) or []
            else:
                result["smooth_verdict"] = "N/A"
                result["smooth_notes"] = []

            # Fold in the MC "DD Understated" caveat (reporting-layer only; no change
            # to monte_carlo.py or the MC score).
            _mc_note = mc_sampling_caveat(
                result.get("mc_verdict"), _profile,
                result.get("mc_sampling_effective", CONFIG.get("mc_sampling", "iid"))
            )
            if _mc_note:
                result["mc_sampling_note"] = _mc_note

            return result
            
    except Exception:
        import traceback
        tqdm.write(f"\n--- FATAL ERROR IN WORKER ---\nStrategy: {name}\nPortfolio: {portfolio_name}\nTraceback:\n{traceback.format_exc()}\n---------------------------\n")
        return None

def main():
    # --- ARGUMENT PARSING (full parser, applied before any CONFIG reads) ---
    from helpers.cli_config import build_parser, apply_overrides, print_help_config
    parser = build_parser()
    args = parser.parse_args()

    # Init wizard (early exit, no CONFIG reads needed)
    if args.init:
        from helpers.init_wizard import run_init_wizard
        run_init_wizard()
        return

    # Guided help (early exit; reads CONFIG for current-value display)
    if args.help_config is not None:
        print_help_config(CONFIG, args.help_config)
        return

    # Apply all CLI overrides to CONFIG before any downstream code reads it
    apply_overrides(CONFIG, args)
    # --- END ARGUMENT PARSING ---

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
        # PR #187 Fix — end_date=None guard (review item: S2 validation crashed on None)
        # end_date=None is a valid "run to today" sentinel; strptime(None) raised TypeError.
        # Only validate the ordering when an explicit date string is set.
        _end_date_str = CONFIG.get("end_date")
        if _end_date_str is not None:
            end = _dt.strptime(_end_date_str, "%Y-%m-%d")
            if start >= end:
                errors.append(f"  - start_date ({CONFIG['start_date']}) must be before end_date ({_end_date_str})")
    except ValueError as e:
        errors.append(f"  - Invalid date format in config: {e}")

    alloc = CONFIG.get("allocation_per_trade", 0)
    if not (0 < alloc <= 1.0):
        errors.append(f"  - allocation_per_trade ({alloc}) must be between 0 (exclusive) and 1.0 (inclusive)")

    if not CONFIG.get("portfolios"):
        errors.append("  - portfolios is empty. Add at least one entry to run, e.g. \"My Symbols\": [\"AAPL\"].")

    # PR #187 Fix 6 — validator consolidation (review item: duplicate module)
    # validate_config lives in the single canonical helpers/config_validator.py;
    # the duplicate config_validators.py (plural) was removed entirely.
    from helpers.config_validator import validate_config
    for _warn in validate_config(CONFIG):  # warns on typo'd / unknown config keys
        logger.warning(_warn)


    if errors:
        print("\n[ERROR] Invalid configuration in config.py:")
        for e in errors:
            print(e)
        print()
        sys.exit(1)
    # --- END S2 ---

    # --- FOLDER SETUP ---
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
            logging.FileHandler(os.path.join(run_base_dir, "logs", f"run_{timestamp}.log"), encoding="utf-8"),
        ],
    )

    _portfolios = CONFIG.get("portfolios") or {}

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
        elif isinstance(_pvalue, str) and _pvalue.startswith("pit:"):
            _symbol_counts[_pname] = f"? ({_pvalue} - resolved at runtime)"
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

    # --- FETCHING DEPENDENCY & BENCHMARK DATA ---
    from helpers.comparison_tickers import parse_comparison_tickers
    from helpers.ticker_normalizer import normalize_ticker

    try:
        comparison_config = parse_comparison_tickers(CONFIG)
        comparison_dfs = {}
        benchmark_returns = {}
        benchmark_dfs = {}

        # Fetch all comparison tickers (benchmarks + dependencies)
        for symbol in comparison_config["all_symbols"]:
            normalized = normalize_ticker(symbol, CONFIG["data_provider"])
            df = data_fetcher(normalized, CONFIG["start_date"], CONFIG["end_date"], CONFIG)
            if df is not None and not df.empty:
                comparison_dfs[symbol] = df
            else:
                logger.warning(f"Failed to fetch data for comparison ticker '{symbol}' (normalized: '{normalized}')")
                dep_warning = _dependency_warning_for_failed_fetch(symbol, comparison_config["dependencies"])
                if dep_warning:
                    logger.warning(dep_warning)

        # Derive actual data period from comparison ticker data if available,
        # otherwise fall back to config dates (valid when comparison_tickers = [])
        if comparison_dfs:
            spy_df = _pick_reference_df(comparison_dfs)
            _spy_actual_start = spy_df.index.min().strftime("%Y-%m-%d")
            _spy_actual_end   = spy_df.index.max().strftime("%Y-%m-%d")
            logger.info("-" * 60)
            logger.info(f"  Actual Data Period : {_spy_actual_start} -> {_spy_actual_end}")
            logger.info("-" * 60)
        else:
            spy_df = None
            _spy_actual_start = CONFIG["start_date"]
            _spy_actual_end   = CONFIG.get("end_date") or datetime.now().strftime("%Y-%m-%d")
            logger.info("-" * 60)
            logger.info(f"  Data Period (config): {_spy_actual_start} -> {_spy_actual_end}  (no comparison tickers)")
            logger.info("-" * 60)

        # Calculate benchmark returns
        for bm in comparison_config["benchmarks"]:
            symbol = bm["symbol"]
            label = bm["label"]
            if symbol in comparison_dfs:
                df = comparison_dfs[symbol]
                bnh_return = (df['Close'].iloc[-1] - df['Close'].iloc[0]) / df['Close'].iloc[0]
                benchmark_returns[label] = bnh_return
                benchmark_dfs[label] = df
                logger.info(f"{label} B&H: {bnh_return:.2%}")
            else:
                logger.warning(f"Benchmark '{label}' (symbol: {symbol}) not available — skipping")
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

        # PR #187 Fix 3 — legacy PIT keyword normalisation (review item: minor nit)
        # The original docs and .env.example showed "sp500_pit" / "nq100_pit" as valid
        # portfolio values, but the resolver only understood the "pit:" prefix form.
        # Silently rewrite both legacy spellings so old configs continue to work.
        if isinstance(value, str) and value == "sp500_pit":
            value = "pit:sp500"
            logger.info(f"  -> '{portfolio_name}': normalised 'sp500_pit' → 'pit:sp500'")
        elif isinstance(value, str) and value == "nq100_pit":
            value = "pit:nq100"
            logger.info(f"  -> '{portfolio_name}': normalised 'nq100_pit' → 'pit:nq100'")

        # Reset each portfolio. Set for pit: portfolios (index membership) AND
        # for rule: portfolios (periodic liquidity re-basing) — both emit the
        # same [(date, frozenset)] shape, so both feed the masking below.
        _current_membership_schedule = None

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
        elif isinstance(value, str) and value.lower().startswith("rule:"):
            # Rule-based point-in-time universe (#70). Needs no index-membership
            # data: the investable set is derived from observable liquidity over
            # the delisted-inclusive Parquet corpus, so it is survivorship-free
            # by construction.
            #
            # Resolved PERIODICALLY, not once. Resolving only at start_date and
            # freezing the result reintroduced a selection bias of the same shape
            # as the survivorship bug this feature removes, pointing the other
            # way: a 2004-2024 run would never trade NVDA, TSLA, META or GOOGL,
            # because none were top-500-liquidity names in 2004. Yields the same
            # (union, schedule) pair as the pit: branch below, so it reuses the
            # existing per-bar membership masking with no engine change.
            from helpers.rule_based_universe import build_rule_schedule
            # .lower() because rebase_dates() lowercases before dispatching, so
            # "None"/"NONE" already FREEZE the universe. Comparing verbatim here
            # meant those spellings froze it while skipping the warning AND
            # leaving the mask built from the frozen snapshot rather than
            # disabled -- i.e. it failed in exactly the case the warning exists
            # for: a user who deliberately opted into freezing.
            _rebase = str(CONFIG.get("universe_rebase", "annual") or "annual").lower()
            try:
                symbols, _current_membership_schedule = build_rule_schedule(
                    value, CONFIG["start_date"], CONFIG["end_date"], CONFIG,
                    progress=lambda i, n, d, k: logger.info(
                        f"     re-base {i}/{n} @ {d}: {k} securities"),
                )
                if _rebase == "none":
                    _current_membership_schedule = None   # opt out of masking
                    logger.warning(
                        f"  -> universe_rebase='none': '{value}' is frozen at "
                        f"{CONFIG['start_date']} for the whole run. Securities "
                        f"that become investable later will NEVER be traded."
                    )
                logger.info(
                    f"  -> Resolved {len(symbols)} securities from '{value}' "
                    f"across {CONFIG['start_date']}..{CONFIG['end_date']} "
                    f"(rebase={_rebase}, survivorship-free; NOT an index)"
                )
            except Exception as e:
                logger.error(f"  -> ERROR resolving rule universe '{value}': {e}")
                continue
        elif isinstance(value, str) and value.startswith("pit:"):
            from helpers.point_in_time import tickers_union_for_period as _pit_union, build_membership_schedule as _pit_schedule_build
            _pit_index_name = value.split(":", 1)[1]
            try:
                symbols = _pit_union(_pit_index_name, CONFIG["start_date"], CONFIG["end_date"], CONFIG)
                _current_membership_schedule = _pit_schedule_build(_pit_index_name, CONFIG["start_date"], CONFIG["end_date"], CONFIG)
            except Exception as e:
                logger.error(f"  -> ERROR resolving PIT portfolio '{value}' for '{portfolio_name}': {e}")
                continue
            logger.info(
                f"  -> {value} full historical union ({CONFIG['start_date']} to {CONFIG['end_date']}): "
                f"{len(symbols)} tickers (PIT membership enforced during simulation)"
            )
        
        if not symbols:
            logger.warning(f"No symbols found for '{portfolio_name}'. Skipping.")
            continue

        # --- SURVIVORSHIP: merge delisted symbols into universe ---
        if CONFIG.get("include_delisted", False):
            delisted_file = CONFIG.get("delisted_symbols_file")
            if delisted_file:
                delisted_path = os.path.join("tickers_to_scan", delisted_file) if not os.path.isabs(delisted_file) else delisted_file
                if os.path.exists(delisted_path):
                    with open(delisted_path, "rb") as _f:
                        extra_symbols = orjson.loads(_f.read())
                    before = len(symbols)
                    symbols = list(dict.fromkeys(symbols + extra_symbols))
                    logger.info(f"  -> Merged {len(symbols) - before} delisted symbols from '{delisted_file}' (universe: {len(symbols)} total)")
                else:
                    logger.warning(f"  -> [WARNING] delisted_symbols_file '{delisted_file}' not found — universe contains survivors only")
            else:
                logger.warning(
                    "  -> [WARNING] include_delisted=True but no delisted_symbols_file configured. "
                    "Universe contains survivors only. Set 'delisted_symbols_file' to a JSON ticker list "
                    "(e.g. tickers_to_scan/nasdaq_100_delisted.json) to include historically delisted stocks."
                )

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
                # Each column reflects its own bar's close/volume; the engine
                # captures them from the SIGNAL bar (the bar before the fill
                # under execution_time="open"), so no look-ahead reaches the
                # entry_* features — see the capture sites in
                # helpers/portfolio_simulations.py (issue #310).

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

        # --- DATA QUALITY VALIDATION ---
        if CONFIG.get("data_quality_checks", True):
            from helpers.data_quality import quality_report
            logger.info(f"  -> Running data quality checks on {len(symbols)} symbols...")
            # config is passed so futures symbols resolve their calendar (CME_ETH)
            # and skip the NYSE missing-bar estimate (see helpers/data_quality.py).
            quality_df = quality_report(symbols, portfolio_data, CONFIG.get("timeframe", "D"),
                                        config=CONFIG)

            # Display quality report
            threshold = CONFIG.get("data_quality_threshold", 80)
            low_quality = quality_df[quality_df["score"] < threshold]

            if not low_quality.empty:
                logger.warning(f"  -> {len(low_quality)} symbol(s) have quality score < {threshold}")
                print("\n" + "=" * 80)
                print(f"DATA QUALITY REPORT: {portfolio_name}".center(80))
                print("=" * 80)
                # Show only low-quality symbols in detail
                print(low_quality[["symbol", "score", "issues"]].to_string(index=False))
                print("=" * 80 + "\n")

                if CONFIG.get("strict_data_quality", False):
                    raise ValueError(
                        f"Data quality check failed: {len(low_quality)} symbol(s) below threshold {threshold}. "
                        f"Set strict_data_quality=False to continue with warnings."
                    )
            else:
                logger.info(f"  -> All symbols passed quality checks (min score: {quality_df['score'].min():.1f})")
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

        # --- MEMBERSHIP MASKS (precomputed once per portfolio) ---
        # Build a boolean Series per symbol marking which trading dates the
        # symbol was a member of the tradeable universe.  Workers apply this
        # mask to gate entry signals and inject exit signals — zero
        # per-simulation overhead beyond a vectorised lookup.
        #
        # Two producers, one shape:
        #   pit:  -> index membership from the PIT YAML
        #   rule: -> periodic liquidity re-basing (annual by default)
        # The rule: case is what stops a liquidity universe being frozen at
        # start_date, which would bar every name that qualified later.
        if _current_membership_schedule is not None:
            from helpers.point_in_time import pit_members_on as _pit_members_on
            from helpers.pit_enforcement import (
                build_member_mask as _pit_build_member_mask,
                build_forced_exit_mask as _pit_build_forced_exit_mask,
                membership_intervals as _pit_membership_intervals,
            )
            _pit_member_masks: dict[str, object] = {}
            for _sym, _df in portfolio_data.items():
                _dates = _df.index
                _date_strs = [str(d)[:10] for d in _dates]
                _pit_member_masks[_sym] = pd.Series(
                    [_sym in _pit_members_on(_current_membership_schedule, d) for d in _date_strs],
                    index=_dates,
                    dtype=bool,
                )
            _n_with_history = sum(m.any() for m in _pit_member_masks.values())
            logger.info(f"  -> PIT masks built: {_n_with_history}/{len(_pit_member_masks)} symbols have at least one membership day")

            # PR #187 Fix 2 — wire pit_enforcement columns into portfolio_data (major review item)
            # pit_enforcement.py (build_member_mask, build_forced_exit_mask) was tested in
            # isolation but never connected to the engine: _pit_flag() in portfolio_simulations.py
            # always returned the column's default (False) because main.py never populated
            # _pit_member or _pit_force_exit.  The two column writes below close that gap.
            #
            # _pit_member  → True on bars when the symbol IS an index member.
            #                 The simulator skips entries and fires "PIT Membership Exit"
            #                 on the first non-member bar after an open long.
            # _pit_force_exit → True on the LAST available member bar when no timely
            #                 next-bar exists after index removal (e.g. sudden delisting).
            #                 The simulator closes at that bar's Close rather than waiting.
            _pit_intervals = _pit_membership_intervals(value, CONFIG)
            _exit_buffer = CONFIG.get("pit_exit_buffer_days", 10)
            _backtest_end = CONFIG.get("end_date") or str(pd.Timestamp.now().normalize().date())
            _n_forced = 0
            for _sym, _mask in _pit_member_masks.items():
                _df = portfolio_data[_sym]
                _df["_pit_member"] = _mask.reindex(_df.index, fill_value=False)
                _sym_intervals = _pit_intervals.get(_sym, [])
                if _sym_intervals:
                    _force_mask = _pit_build_forced_exit_mask(
                        _df.index, _sym_intervals, _backtest_end, _exit_buffer
                    )
                else:
                    _force_mask = pd.Series(False, index=_df.index)
                _df["_pit_force_exit"] = _force_mask
                if _force_mask.any():
                    _n_forced += 1
            logger.info(f"  -> PIT columns written to portfolio_data: {_n_forced} symbols have forced-exit bars")
        else:
            _pit_member_masks = None
        # --- END PIT MEMBERSHIP MASKS ---

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
                        stop_config,
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
        _n_workers = min(cpu_count(), len(tasks_for_this_portfolio))
        logger.info(f"Found {len(tasks_for_this_portfolio)} tasks. Using up to {_n_workers} CPU cores.")

        # Sub-bar resolution: fetch intraday data per symbol only when enabled.
        _intrabar_data = (_build_intrabar_data(portfolio_data, CONFIG)
                          if CONFIG.get("intrabar_resolution", False) else None)

        # Pass comparison data, portfolio data, delisting dates, PIT masks, and
        # optional intraday data during initialization
        init_args = (comparison_dfs, benchmark_returns, comparison_config["dependencies"], portfolio_data, delisting_dates, _pit_member_masks, _intrabar_data)

        # _n_workers caps at the actual task count (not always cpu_count()): with
        # intrabar_resolution on, each worker gets its own pickled copy of the full
        # 1-minute intrabar dataframe (5M+ rows) at spawn time via initargs. On a
        # memory-constrained Windows box, spawning idle extra workers that only
        # duplicate that payload without doing any work has been observed to trigger
        # an intermittent `OSError: [Errno 22] Invalid argument` from
        # multiprocessing's spawn pickling (a low-memory condition, not a task bug).
        with Pool(processes=_n_workers, initializer=init_worker, initargs=init_args) as p:
            import time as _time
            _results = []
            _start_pool = _time.monotonic()
            _total = len(tasks_for_this_portfolio)
            _checkpoints = {max(1, int(_total * pct)) for pct in [0.1, 0.25, 0.5, 0.75, 0.9]}

            for _i, _r in enumerate(tqdm(p.imap(run_single_simulation, tasks_for_this_portfolio), total=_total, desc="  -> Running sims"), start=1):
                _results.append(_r)
                if _i in _checkpoints:
                    # PR #187 follow-up — ZeroDivisionError guard (test: test_progress_tracking.py)
                    # On fast machines / CI, the first checkpoint fires within nanoseconds
                    # of pool start, making elapsed=0.0 and raising ZeroDivisionError.
                    # Clamping to 1e-9 s is indistinguishable from "instant" in the display
                    # ({elapsed:.0f}s still shows "0s") but prevents the crash.
                    _elapsed = max(_time.monotonic() - _start_pool, 1e-9)
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

        generate_per_portfolio_summary(p_results, p_name, benchmark_returns, run_folder_name, corr_matrix=corr_matrix)

        from helpers.regime import print_regime_heatmap as _print_heatmap
        for _r in p_results:
            if _r.get("regime_heatmap") is not None:
                _print_heatmap(_r["regime_heatmap"], _r.get("Strategy", "Unknown"))

    duration_seconds = time.monotonic() - start_time
    generate_portfolio_summary_report(all_portfolio_results, benchmark_returns, duration_seconds, run_folder_name)

    from helpers.verdict_format import print_strategy_verdicts as _print_verdicts
    _print_verdicts(all_portfolio_results, benchmark_returns)

    generate_llm_verdict(all_portfolio_results, benchmark_returns, run_folder_name, benchmark_dfs=benchmark_dfs)
    generate_sensitivity_report(all_portfolio_results, run_folder_name)

    if CONFIG.get("export_ml_features", False):
        from helpers.ml_export import export_trade_features as _ml_export
        _ml_path = os.path.join("output", "runs", run_folder_name, "ml_features.parquet")
        _n_rows = _ml_export(all_portfolio_results, _ml_path)
        if _n_rows > 0:
            logger.info(f"  ML feature export: {_n_rows} trades -> {_ml_path}")

    mins, secs = divmod(duration_seconds, 60)
    logger.info(f"All portfolio simulations complete in {int(mins)}m {secs:.2f}s.")
    _print_report_hint(run_folder_name)


def _print_report_hint(run_folder_name: str) -> None:
    """Log a copy-paste ready report command at the end of a run."""
    run_path = f"output/runs/{run_folder_name}"
    cmd = f"python report.py --all {run_path}"
    bar = "━" * len(cmd)
    logger.info(bar)
    logger.info(f"  Run report:  {cmd}")
    logger.info(bar)

if __name__ == "__main__":
    main()
