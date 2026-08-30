"""
Platform-default configuration for july-backtester.

Edit the values below before running.  Every key is documented; do NOT rename
or remove keys — the engine validates against a known allowlist in
helpers/config_validator.py and will warn on typos.

Research-specific presets (e.g. config_weekly_rsi.py) should NOT be committed
to the repo. Keep experiment configs locally and copy values into this file
temporarily when reproducing an experiment, then restore before committing.
"""
import os

CONFIG = {
    # ============================================================
    # SECTION 1: DATA PROVIDER
    # ============================================================
    # "polygon" | "norgate" | "yahoo" | "csv"
    # polygon_api_secret_name: name of the env-var / .env key that holds the key.
    "data_provider": "polygon",
    "polygon_api_secret_name": "POLYGON_API_KEY",
    # Only used when data_provider = "csv":
    "csv_data_dir": "csv_data",
    # Only used when data_provider = "merged" — root of the built unified
    # Norgate+Polygon store (see src/data/unified_market_data_provider.py).
    # Empty string / unset falls back to data/market_data/merged/. Build the
    # store with `python scripts/build_merged_dataset.py` before switching to
    # "merged"; the provider raises at startup if this path doesn't exist.
    "merged_data_root": os.environ.get("MERGED_DATA_ROOT", ""),

    # ============================================================
    # SECTION 2: BACKTEST PERIOD & CAPITAL
    # ============================================================
    "start_date": "2004-01-01",
    "end_date": "2026-12-31",  # update this or set to today's date before running
    "initial_capital": 100000.0,

    # ============================================================
    # SECTION 3: TIMEFRAME
    # ============================================================
    # "D" = daily  |  "W" = weekly  |  "M" = monthly
    # "H" = hourly  |  "MIN" = minute-level
    "timeframe": "D",
    "timeframe_multiplier": 1,

    # ============================================================
    # SECTION 4: PRICE ADJUSTMENT & BENCHMARKS
    # ============================================================
    # comparison_tickers drives which symbols are downloaded alongside your
    # portfolio.  role="benchmark" → buy-and-hold return column in summary.
    # role="dependency" → available to strategies (spy_df, vix_df).
    # role="both" → benchmark + dependency.
    # Use split/dividend-adjusted prices by default. "none" returns raw bars and
    # creates phantom jump trades across splits (e.g. AMZN 20-for-1).
    "price_adjustment": "total_return",
    "benchmark_symbol": "SPY",
    "comparison_tickers": [
        {"symbol": "SPY",   "role": "both"},
        {"symbol": "QQQ",   "role": "benchmark"},
        {"symbol": "I:VIX", "role": "dependency"},
        {"symbol": "I:TNX", "role": "dependency"},
    ],

    # ============================================================
    # SECTION 5: FILE OUTPUT
    # ============================================================
    "save_individual_trades": True,

    # ============================================================
    # SECTION 6: SUMMARY FILTERING
    # ============================================================
    # Strategies below these thresholds are omitted from the printed table.
    # Platform default: show everything (-9999 = no filter). Tighten once you
    # know which strategies are worth following.
    "mc_score_min_to_show_in_summary": -9999,
    "min_pandl_to_show_in_summary": -9999,
    "max_acceptable_drawdown": 1.0,
    "min_performance_vs_spy": -9999.0,
    "min_performance_vs_qqq": -9999.0,
    "save_only_filtered_trades": False,
    "show_qqq_losers": True,

    # ============================================================
    # SECTION 7: PORTFOLIO
    # ============================================================
    # A single ticker:        {"My Run": ["AAPL"]}
    # Pre-built JSON list:    {"Nasdaq 100": "nasdaq_100.json"}
    # PIT universe:           {"NQ100 PIT": "pit:nq100"}  or  "pit:sp500"
    # Norgate watchlist:      {"My WL": "norgate:WatchlistName"}
    "min_bars_required": 200,
    "portfolios": {
        "My Symbols": ["AAPL"],
    },

    # ============================================================
    # SECTION 8: ALLOCATION & EXECUTION
    # ============================================================
    "allocation_per_trade": 0.10,   # fraction of equity per position
    "max_pct_adv": 0.05,            # max order size as % of 20-day avg daily volume
    "execution_time": "open",       # "open" = next-day open fill
    "roc_thresholds": [0.0, 0.5],

    # ============================================================
    # SECTION 9: STOP LOSS
    # ============================================================
    # {"type": "none"} | {"type": "percentage", "value": 0.05}
    # | {"type": "atr", "multiplier": 2.0}
    # | {"type": "signal_bar", "buffer": 0.005, "bars_back": 0}
    #     Structural stop at the SIGNAL bar's extreme rather than a distance from
    #     entry: long stops under that bar's Low, short stops above its High.
    #     "buffer" (fraction, default 0.0) pads the level away from the printed
    #     extreme so noise doesn't graze it. Static — it does not trail.
    #     "bars_back" (default 0) walks the anchor further back: 1 = the bar
    #     BEFORE the trigger, for setups that defend the level preceding the
    #     reversal bar rather than the reversal bar itself.
    "stop_loss_configs": [
        {"type": "none"},
    ],

    # ============================================================
    # SECTION 10: MONTE CARLO
    # ============================================================
    "min_trades_for_mc": 50,
    "num_mc_simulations": 1000,

    # ============================================================
    # SECTION 11: WALK-FORWARD ANALYSIS
    # ============================================================
    "wfa_split_ratio": 0.80,        # 0.80 = 80% IS / 20% OOS; None = disabled
    "wfa_folds": None,              # None = rolling WFA disabled; int >=2 = folds
    "wfa_min_fold_trades": 5,

    # ============================================================
    # SECTION 12: TRADING COSTS
    # ============================================================
    "slippage_pct": 0.0005,         # 5 bps flat bid/ask spread per trade
    "commission_per_share": 0.002,  # $0.002 per share
    "risk_free_rate": 0.05,         # annual, used in Sharpe (US T-bill proxy)

    # ============================================================
    # SECTION 13: STRESS TESTING
    # ============================================================
    "noise_injection_pct": 0.0,     # 0.0 = disabled; 0.01 = ±1% price noise

    # ============================================================
    # SECTION 14: STRATEGY SELECTION
    # ============================================================
    # "all" = run every registered plugin.
    # Or a list of exact names: ["RSI Mean Reversion (14/30)", "MACD Crossover"]
    "strategies": "all",

    # ============================================================
    # SECTION 15: SENSITIVITY SWEEP
    # ============================================================
    "sensitivity_sweep_enabled": False,
    "sensitivity_sweep_pct": 0.20,
    "sensitivity_sweep_steps": 2,
    "sensitivity_sweep_min_val": 2,

    # ============================================================
    # SECTION 16: ROLLING SHARPE
    # ============================================================
    "rolling_sharpe_window": 126,   # trading days; 0 or None = disable

    # ============================================================
    # SECTION 17: SHORT SELLING BORROW COST
    # ============================================================
    "htb_rate_annual": 0.0,         # 0.0 = disabled (long-only default); set to e.g. 0.02 for short strategies

    # ============================================================
    # SECTION 18: MONTE CARLO SAMPLING
    # ============================================================
    "mc_sampling": "iid",           # "iid" = independent; "block" = block-bootstrap;
                                    # "auto" = block for a concentrated_futures smoothness
                                    # profile, else iid (calibrates the MC "DD-Understated"
                                    # verdict for single-instrument regime-dependent strategies)
    "mc_block_size": None,          # None = auto floor(sqrt(N))

    # ============================================================
    # SECTION 18b: CURVE-SMOOTHNESS VERDICT PROFILE
    # ============================================================
    # Which threshold set the SMOOTH/ACCEPTABLE/ROUGH verdict is judged against
    # (see helpers/smoothness_profiles.py). The equity thresholds assume a
    # steadily-compounding, many-name book; a concentrated / event-driven
    # strategy (e.g. a single-instrument futures breakout) structurally trips
    # them even when working as intended.
    #   "auto"                 -> derive per strategy from the portfolio's
    #                             instrument asset class (futures -> looser
    #                             "concentrated_futures" profile, else "equity").
    #   "equity"               -> force the legacy equity thresholds.
    #   "concentrated_futures" -> force the looser concentrated profile.
    "smoothness_profile": "auto",

    # ============================================================
    # SECTION 19: VOLUME-BASED MARKET IMPACT
    # ============================================================
    "volume_impact_coeff": 0.0,     # 0.0 = disabled; 0.1 = mild institutional

    # ============================================================
    # SECTION 20: MISC OUTPUT
    # ============================================================
    "export_ml_features": False,

    # ============================================================
    # SECTION 24: DETERMINISTIC ENTRY QUEUE (#160)
    # ============================================================
    # Controls the order in which symbols are evaluated for entry when multiple
    # signals fire on the same bar and capital can only fill a subset.
    # "alphabetical" (default) — A→Z, reproducible and Alpaca-replicable
    # "signal_date"            — earlier-signalling symbols get priority
    # "random_seed"            — shuffle with a fixed seed (sensitivity testing)
    "entry_priority": "alphabetical",
    "entry_random_seed": 42,

    # Whether a bar qualifies as an ENTRY at all.
    # "level" (default) — enter on any bar whose signal reads the entry value.
    #                     Strategies emitting a forward-filled state series make
    #                     every hold bar entry-eligible under this mode.
    # "edge"            — enter only on the transition INTO the entry state,
    #                     matching how the live scanner triggers. Opt-in: the
    #                     default is unchanged so existing results are stable.
    #
    # TWO CONSEQUENCES OF "edge" BEYOND THE LATE-ENTRY FIX, both intended:
    #   * A STOPPED-OUT POSITION DOES NOT RE-ENTER while the state signal is
    #     still held. Level mode re-enters on the next bar (the series still
    #     reads 1); edge mode waits for a transition that will not come until
    #     the strategy actually re-signals. A live scanner triggering on
    #     `last == 1 and prev != 1` behaves the same way, which is the point —
    #     but on a stopped strategy this moves results more than the capacity
    #     path this option was written for.
    #   * ON A CONTESTED BOOK IT RE-PLANS, IT DOES NOT ONLY SUBTRACT. Skipping
    #     a late entry frees the capital that entry would have consumed, and
    #     that capital goes to whatever else is competing on the bar — so a
    #     surviving trade can change SIZE, and a symbol can end up with MORE
    #     trades than level mode gave it. Measured over 80 randomised contested
    #     books (5 symbols x 120 bars): 20 of the 80 had at least one symbol
    #     trading more often under edge (25 of 400 book-symbol cells), while
    #     book totals fell 1564 -> 1434. Net subtraction, but not a filter.
    "entry_trigger": "level",

    # ============================================================
    # SECTION 21: VERBOSE SUMMARY TABLE
    # ============================================================
    # When False (default), terminal summary tables show a compact
    # 7-column view: Strategy, P&L (%), vs. SPY (B&H), Sharpe,
    # Max DD, MC Score, WFA Verdict.
    # When True, all 23 columns are displayed.
    # Override at runtime with: python main.py --verbose
    "verbose_output": False,
    "exclude_open_positions": False,
    "upload_to_s3": False,
    "s3_reports_bucket": "",

    # ============================================================
    # SECTION 23: SURVIVORSHIP BIAS
    # ============================================================
    # Include delisted/failed companies in backtests to avoid survivorship bias.
    # Only Norgate and Polygon support delisting data.
    # Yahoo and CSV providers will log a warning if enabled.
    "include_delisted": False,

    # How to price force-closed positions when a stock is delisted:
    # "last_close" — use the last known Close price (default, realistic)
    # "zero" — assume total loss (conservative, stress-test scenario)
    "delisting_price_assumption": "last_close",

    # Optional path to a JSON file of historically delisted symbols to merge
    # into the universe when include_delisted=True. Same format as nasdaq_100.json.
    # Relative paths resolve from tickers_to_scan/. Set to None to disable.
    # Without this, the universe still only contains surviving stocks even when
    # include_delisted=True — setting this is required for true survivorship
    # bias correction.
    # Example: "delisted_symbols_file": "nasdaq_100_delisted.json"
    "delisted_symbols_file": None,

    # ============================================================
    # SECTION 24: DATA QUALITY VALIDATION
    # ============================================================
    # Pre-flight data quality checks before backtest runs.
    # Detects: missing bars, price jumps, OHLC violations, negative prices, zero volume
    "data_quality_checks": True,

    # Minimum quality score (0-100) to proceed with backtest in strict mode
    "data_quality_threshold": 80,

    # When True, fail fast if any symbol has score < threshold
    # When False (default), log warnings and continue
    "strict_data_quality": False,

    # ============================================================
    # SECTION 25: POSITION SIZING
    # ============================================================
    # Position sizing method: "fixed", "kelly", "vol_parity", "risk_parity"
    "position_sizing_method": "fixed",

    # Fixed method: % of equity per trade (used by "fixed" method)
    # Already defined in SECTION 8, but listed here for reference
    # "allocation_per_trade": 0.10,

    # Kelly Criterion: fraction of full Kelly to use (conservative)
    # Full Kelly can be very aggressive, so we use 25% by default
    "kelly_fraction": 0.25,

    # Volatility/Risk Parity: target risk per trade (2% of equity)
    # This is the $ amount you're willing to lose if the trade hits your stop
    "target_risk_per_trade": 0.02,

    # Portfolio heat limit: max total $ risk across all open positions
    # 0.10 = 10% of equity can be at risk simultaneously
    # 1.0 = no limit (allow full portfolio risk)
    "max_portfolio_heat": 0.10,

    # ============================================================
    # SECTION 26: POINT-IN-TIME (PIT) MEMBERSHIP ENFORCEMENT
    # ============================================================
    # Only relevant for PIT portfolios ("pit:nq100" / "pit:sp500").
    # Each symbol is gated to its index-membership (pit_enforce_daily is the enable
    # flag, currently always-on for PIT portfolios):
    # spells: warm-up bars (kept for indicator continuity) and gap bars (while it
    # was out of the index) stay in the frame but are NEVER traded.
    # _pit_force_exit marks the last available member bar when no timely post-leave
    # bar exists, so the simulator can close at Close instead of waiting.
    "pit_enforce_daily": True,
    "pit_warmup_days": 400,              # calendar days of pre-join data for indicators
    "pit_exit_buffer_days": 10,          # grace-period bars after index removal
    "pit_coverage_tolerance_days": 7,

    # --- PIT Data Repo Paths (optional) ---
    # Absolute paths to local clones of the PIT ticker-history repos.
    # Leave as "" to fall back to the NQ100_DATA_ROOT / SP500_DATA_ROOT
    # environment variables (see .env.example), or drop the YAML files
    # directly under tickers_to_scan/point_in_time/{nq100,sp500}/.
    #   NQ100 -- https://github.com/shardul0701/NQ100-Survivorship-bias-data-2004-2026
    #   SP500 -- https://github.com/shardul0701/SP500-Survivorship-bias-data-2004-2026
    "nq100_pit_path": "",
    "sp500_pit_path": "",

    # ============================================================
    # SECTION 27: INSTRUMENT METADATA (equities / futures)
    # ============================================================
    # Per-symbol trading metadata resolved by helpers/instruments.py. Equities are
    # the default and reproduce prior behaviour exactly (point_value=1, full-notional
    # cash, per-share commission, %-slippage). Futures opt in either via a contract-
    # month ticker (e.g. "ESM6") or an explicit override below.
    "instruments": {
        # "future" makes EVERY symbol in the portfolio a futures contract; leave as
        # "equity" for mixed/equity runs and opt individual symbols in via overrides.
        "default_asset_class": "equity",

        # Futures defaults (used for any resolved futures instrument):
        "futures_initial_margin_pct": 0.10,   # fraction of notional posted at entry
        "futures_commission_per_contract": 2.50,  # $ per contract, one side
        "futures_slippage_ticks": 1.0,        # slippage in ticks per fill

        # Optional per-root overrides of the built-in seed tables:
        # "point_values": {"ES": 50.0, "NQ": 20.0},
        # "tick_sizes":   {"ES": 0.25, "NQ": 0.25},

        # Per-symbol session length (issue #270). `trading_hours_per_day`
        # (SECTION 26) is one process-wide number, so a book mixing equities
        # (6.5h RTH) with 24h futures gets the wrong bars-per-day for one side
        # of it -- which feeds the 20-day ADV window used by max_pct_adv and
        # volume_impact_coeff. Two ways to fix a mixed book, both opt-in so
        # existing runs are untouched:
        #   1. per-symbol, via an override below:
        #      {"asset_class": "future", "session_hours": 23}
        #      (spell out asset_class -- see the override note below)
        #   2. blanket, from each instrument's calendar (NYSE 6.5, CME_ETH 23):
        # "session_hours_from_calendar": True,

        # Explicit per-symbol overrides. Each dict may set "asset_class" and any
        # Instrument field (point_value, tick_size, initial_margin_pct, ...).
        #
        # An override dict is authoritative for asset class: the contract-month
        # auto-detection that would otherwise recognise "ESM6" as a future is
        # only consulted when a symbol has NO override. So always spell out
        # "asset_class": "future" when overriding a futures symbol -- omitting
        # it silently resolves the symbol as a cash equity (point_value 1.0,
        # cash_full margin, fractional units, borrow charged, NYSE calendar).
        # "overrides": {
        #     "NQ":  {"asset_class": "future", "point_value": 20.0, "tick_size": 0.25},
        #     "SI":  {"asset_class": "equity"},  # keep the Silvergate ticker as equity
        #     "ESM6": {"asset_class": "future", "session_hours": 23},  # 23h CME session
        # },
        "overrides": {},
    },

    # ============================================================
    # SECTION 28: SUB-BAR (INTRADAY) RESOLUTION
    # ============================================================
    # When True AND finer-resolution bars are supplied to the engine, stop fills are
    # resolved against the intraday series (a gap through the stop fills at the worse
    # sub-bar open instead of optimistically at the stop level). Opt-in; requires
    # 1-min data availability, so it is off by default.
    "intrabar_resolution": False,
    # Finer-resolution timeframe fetched per symbol when intrabar_resolution is on.
    "intrabar_timeframe": "MIN",     # "MIN" | "H"
    "intrabar_multiplier": 1,        # e.g. 5 for 5-minute sub-bars

    # ============================================================
    # SECTION 29: FUTURES MAINTENANCE MARGIN
    # ============================================================
    # Force-liquidate a futures position when posted margin + unrealized P&L falls
    # below notional * maintenance_margin_pct (logged as ExitReason "Margin Call").
    # 0.0 = disabled (default). Set below the instrument's initial_margin_pct, e.g.
    # 0.07 with a 0.10 initial. Equities (cash_full) are never margin-called.
    "maintenance_margin_pct": 0.0,
    # Reserved — the data-quality screen (provider.filter_universe) is NOT yet
    # wired into the backtest path; these merged_quality_filter_* keys are inert
    # until a future PR. See helpers/pit_enforcement.py "Integration status".
    "merged_quality_filter_enabled": True,
    "merged_exclude_statuses": [
        "insufficient_history", "review_no_patch", "identity_review", "flagged",
    ],
    "merged_min_avg_dollar_volume": 0.0,  # opt-in liquidity floor (0 = off)

    # ============================================================
    # SECTION 30: CROSS-SECTIONAL ROTATION (issue #294)
    # ============================================================
    # First-class rotation mechanism (helpers/rotation.py). A rotation strategy
    # is "a ranking function + this config": the framework owns top-N selection,
    # weighting, rebalance/trim/add mechanics and all cost/accounting (reusing
    # helpers/instruments.py); the plugin supplies only the ranking (the alpha).
    # DISABLED by default -> existing runs are completely unaffected.
    "rotation": {
        "enabled": False,          # master switch for the rotation capability
        "rank_strategy": None,     # name of a @register_rotation plugin to run
        "top_n": 5,                # number of names held at once
        "rebalance_days": 21,      # forced rebalance interval (trading days)
        "weighting": "equal",      # "equal" (1/top_n) | "fixed_alloc" (allocation_per_trade)
        "sell_buffer_rank": 0,     # hysteresis: keep a holding while its rank
                                   #   <= top_n + sell_buffer_rank (reduces churn)
        "drift_trim_pct": 0.0,     # trim a position only when its weight drifts
                                   #   more than this fraction above target (0 = always)
    },

    # Scale-invariant RELATIVE position cap (issue #293): the largest fraction of
    # equity any single rotation position may hold. 1.0 = no binding cap. There is
    # deliberately NO absolute-dollar cap default — a dollar cap is scale-dependent
    # and silently changes behaviour when initial_capital changes.
    "max_position_pct": 1.0,
}
