# strategies.py
# Portfolio-mode strategy definitions, extracted from main_portfolio.py.
#
# Active strategies live in custom_strategies/ and are loaded via
# load_strategies() at the bottom of this file.  Commented-out strategies
# below can be re-activated by un-commenting them and adding them to
# _STATIC_STRATEGIES (they stay in the old partial/wrapper format and are
# merged with the auto-discovered registry entries).

from functools import partial
from config import CONFIG
from helpers.timeframe_utils import get_bars_for_period
from helpers.registry import REGISTRY, load_strategies
from helpers.indicators import (
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

# --- STATIC / LEGACY STRATEGY DEFINITIONS ---
# Un-comment any entry here to reactivate it alongside auto-discovered ones.
# These stay in the old partial/wrapper format and are merged with REGISTRY.
TIMEFRAME = CONFIG.get("timeframe", "D")
MULTIPLIER = CONFIG.get("timeframe_multiplier", 1)
_STATIC_STRATEGIES = {
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


    # SMA Crossover strategies are now in custom_strategies/sma_crossovers.py.
    # Un-comment the entries below ONLY if you want to override the plugin versions.
    # "SMA Crossover (20d/50d)": {
    #     "logic": partial(sma_crossover_logic, fast=get_bars_for_period('20d', TIMEFRAME, MULTIPLIER), slow=get_bars_for_period('50d', TIMEFRAME, MULTIPLIER)),
    #     "dependencies": []
    # },
    # "SMA Crossover (50d/200d)": {
    #     "logic": partial(sma_crossover_logic, fast=get_bars_for_period('50d', TIMEFRAME, MULTIPLIER), slow=get_bars_for_period('200d', TIMEFRAME, MULTIPLIER)),
    #     "dependencies": []
    # },
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

# ---------------------------------------------------------------------------
# Auto-discovery: load all *.py plugins from custom_strategies/
# ---------------------------------------------------------------------------
# This triggers @register_strategy decorators in every file found there,
# populating helpers.registry.REGISTRY without touching any core files.
load_strategies("custom_strategies")

# Merge: static (legacy) entries take precedence only when a name collision
# occurs with a plugin entry.  In practice, keep names unique.
STRATEGIES = {**dict(REGISTRY), **_STATIC_STRATEGIES}
