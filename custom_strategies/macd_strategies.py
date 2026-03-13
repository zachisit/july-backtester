# custom_strategies/macd_strategies.py
"""MACD and EMA crossover strategy plugins.

Covers all signal-crossover / momentum configurations from the legacy
_STATIC_STRATEGIES dict:
  - MACD Crossover (12/26/9)
  - MACD + RSI Confirmation
  - EMA Crossover — Unfiltered, SPY-only, VIX-only, and full SPY+VIX regime
  - EMA Scalping (sub-daily)

All strategies are registered automatically when this module is imported
via ``load_strategies("custom_strategies")``.  No edits to any core file
are required to add, remove, or rename them.
"""

from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import (
    macd_crossover_logic,
    macd_rsi_filter_logic,
    ema_crossover_unfiltered_logic,
    ema_crossover_spy_only_logic,
    ema_crossover_vix_only_logic,
    ema_regime_crossover_logic,
    ema_scalping_logic,
)
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ---------------------------------------------------------------------------
# MACD Crossover
# ---------------------------------------------------------------------------

@register_strategy(
    name="MACD Crossover (12/26/9)",
    dependencies=[],
    params={
        "fast":   get_bars_for_period("12d", _TF, _MUL),
        "slow":   get_bars_for_period("26d", _TF, _MUL),
        "signal": get_bars_for_period("9d",  _TF, _MUL),
    },
)
def macd_crossover_12_26_9(df, **kwargs):
    """Classic MACD crossover: buy when MACD line crosses above the signal line.

    Standard 12/26/9 configuration.  Bar counts are timeframe-agnostic via
    ``get_bars_for_period``, so this works on daily, hourly, or minute data.
    """
    return macd_crossover_logic(
        df,
        fast=kwargs["fast"],
        slow=kwargs["slow"],
        signal=kwargs["signal"],
    )


# ---------------------------------------------------------------------------
# MACD + RSI Confirmation
# ---------------------------------------------------------------------------

@register_strategy(
    name="MACD+RSI Confirmation",
    dependencies=[],
    params={
        "macd_fast":   get_bars_for_period("12d", _TF, _MUL),
        "macd_slow":   get_bars_for_period("26d", _TF, _MUL),
        "macd_signal": get_bars_for_period("9d",  _TF, _MUL),
        "rsi_length":  get_bars_for_period("14d", _TF, _MUL),
    },
)
def macd_rsi_confirmation(df, **kwargs):
    """MACD crossover gated by RSI > 50 confirmation.

    Reduces false positives by requiring the RSI to be above the midline
    when the MACD bullish crossover fires — filters out weak/diverging signals.
    """
    return macd_rsi_filter_logic(
        df,
        macd_fast=kwargs["macd_fast"],
        macd_slow=kwargs["macd_slow"],
        macd_signal=kwargs["macd_signal"],
        rsi_length=kwargs["rsi_length"],
    )


# ---------------------------------------------------------------------------
# EMA Crossover — Unfiltered
# ---------------------------------------------------------------------------

@register_strategy(
    name="EMA Crossover (Unfiltered)",
    dependencies=[],
    params={
        "fast_ema": get_bars_for_period("20d", _TF, _MUL),
        "slow_ema": get_bars_for_period("50d", _TF, _MUL),
    },
)
def ema_crossover_unfiltered(df, **kwargs):
    """Pure EMA crossover with no regime filter.

    Fastest-reacting variant — enters and exits purely on 20-bar / 50-bar EMA
    crossovers with no external market conditions applied.
    """
    return ema_crossover_unfiltered_logic(
        df,
        fast_ema=kwargs["fast_ema"],
        slow_ema=kwargs["slow_ema"],
    )


# ---------------------------------------------------------------------------
# EMA Crossover — SPY trend filter only
# ---------------------------------------------------------------------------

@register_strategy(
    name="EMA Crossover w/ SPY-Only Filter",
    dependencies=["spy"],
    params={
        "fast_ema": get_bars_for_period("20d", _TF, _MUL),
        "slow_ema": get_bars_for_period("50d", _TF, _MUL),
    },
)
def ema_crossover_spy_only(df, **kwargs):
    """EMA crossover, buy signals gated by SPY being above its 200-bar SMA.

    Allows buys only when the broad market is in a long-term uptrend.
    Sell signals are unfiltered so exits remain timely.
    ``spy_df`` is injected automatically by the engine (declared in dependencies).
    """
    return ema_crossover_spy_only_logic(
        df,
        spy_df=kwargs["spy_df"],
        fast_ema=kwargs["fast_ema"],
        slow_ema=kwargs["slow_ema"],
    )


# ---------------------------------------------------------------------------
# EMA Crossover — VIX volatility filter only
# ---------------------------------------------------------------------------

@register_strategy(
    name="EMA Crossover w/ VIX-Only Filter",
    dependencies=["vix"],
    params={
        "fast_ema": get_bars_for_period("20d", _TF, _MUL),
        "slow_ema": get_bars_for_period("50d", _TF, _MUL),
    },
)
def ema_crossover_vix_only(df, **kwargs):
    """EMA crossover, buy signals gated by VIX being below 30.

    Avoids entries during high-fear environments even if the SPY trend is up.
    ``vix_df`` is injected automatically by the engine (declared in dependencies).
    """
    return ema_crossover_vix_only_logic(
        df,
        vix_df=kwargs["vix_df"],
        fast_ema=kwargs["fast_ema"],
        slow_ema=kwargs["slow_ema"],
    )


# ---------------------------------------------------------------------------
# EMA Crossover — Full SPY + VIX regime filter
# ---------------------------------------------------------------------------

@register_strategy(
    name="EMA Crossover w/ SPY+VIX Filter",
    dependencies=["spy", "vix"],
    params={
        "fast_ema": get_bars_for_period("20d", _TF, _MUL),
        "slow_ema": get_bars_for_period("50d", _TF, _MUL),
    },
)
def ema_crossover_spy_vix(df, **kwargs):
    """EMA crossover gated by the full "Bull-Quiet" regime: SPY above 200 SMA AND VIX < 30.

    The most selective of the EMA variants — both market trend AND volatility must
    be favourable before a buy is taken.  Sell signals are never filtered.
    ``spy_df`` and ``vix_df`` are injected automatically by the engine.
    """
    return ema_regime_crossover_logic(
        df,
        spy_df=kwargs["spy_df"],
        vix_df=kwargs["vix_df"],
        fast_ema=kwargs["fast_ema"],
        slow_ema=kwargs["slow_ema"],
    )


# ---------------------------------------------------------------------------
# Sub-daily / scalping EMA strategy  (only registered when timeframe is MIN)
# ---------------------------------------------------------------------------

if _TF == "MIN":
    @register_strategy(
        name="1m EMA Scalp (5/15/50)",
        dependencies=[],
        params={
            "fast_ema_period":  get_bars_for_period("5min",  _TF, _MUL),
            "slow_ema_period":  get_bars_for_period("15min", _TF, _MUL),
            "trend_ema_period": get_bars_for_period("50min", _TF, _MUL),
        },
    )
    def ema_scalp_1m(df, **kwargs):
        """Sub-daily EMA crossover scalp with a long-period trend filter.

        Designed for minute-level bars (set ``timeframe = "MIN"`` in config).
        Buys when the 5-bar EMA crosses above the 15-bar EMA, only when price
        is above the 50-bar EMA.  Exits on the reverse crossover.

        ``get_bars_for_period("5min", ...)`` resolves to 5 bars on 1-minute data,
        1 bar on 5-minute data, etc.  Ensure the timeframe/multiplier matches the
        intended bar frequency before enabling.
        """
        return ema_scalping_logic(
            df,
            fast_ema_period=kwargs["fast_ema_period"],
            slow_ema_period=kwargs["slow_ema_period"],
            trend_ema_period=kwargs["trend_ema_period"],
        )
