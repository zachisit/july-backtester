# custom_strategies/rsi_strategies.py
"""RSI strategy plugins.

Covers all RSI-based configurations from the legacy _STATIC_STRATEGIES dict:
  - RSI Mean Reversion (standard and aggressive thresholds)
  - RSI with SMA-200 trend filter
  - RSI Extreme Fade (sub-daily / scalping)

All strategies are registered automatically when this module is imported
via ``load_strategies("custom_strategies")``.  No edits to any core file
are required to add, remove, or rename them.
"""

from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import rsi_logic, rsi_with_trend_filter_logic, rsi_scalping_logic
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ---------------------------------------------------------------------------
# Standard RSI Mean Reversion
# ---------------------------------------------------------------------------

@register_strategy(
    name="RSI Mean Reversion (14/30)",
    dependencies=[],
    params={
        "length":      get_bars_for_period("14d", _TF, _MUL),
        "oversold":    30,
        "exit_level":  50,
    },
)
def rsi_mean_reversion_14_30(df, **kwargs):
    """RSI mean reversion: buy when RSI crosses back above 30, exit above 50.

    Classic oversold-bounce strategy. The 14-bar RSI period is timeframe-agnostic
    via ``get_bars_for_period`` so this works equally on daily, hourly, or minute data.
    """
    return rsi_logic(
        df,
        length=kwargs["length"],
        oversold=kwargs["oversold"],
        exit_level=kwargs["exit_level"],
    )


@register_strategy(
    name="RSI Mean Reversion (7/20)",
    dependencies=[],
    params={
        "length":      get_bars_for_period("7d", _TF, _MUL),
        "oversold":    20,
        "exit_level":  50,
    },
)
def rsi_mean_reversion_7_20(df, **kwargs):
    """Aggressive RSI mean reversion: shorter period and lower oversold threshold.

    The tighter thresholds produce fewer but potentially higher-conviction signals
    than the standard 14/30 configuration.
    """
    return rsi_logic(
        df,
        length=kwargs["length"],
        oversold=kwargs["oversold"],
        exit_level=kwargs["exit_level"],
    )


# ---------------------------------------------------------------------------
# RSI with SMA-200 trend filter
# ---------------------------------------------------------------------------

@register_strategy(
    name="RSI (14d) w/ SMA200 Filter",
    dependencies=[],
    params={
        "rsi_length":  get_bars_for_period("14d", _TF, _MUL),
        "oversold":    30,
        "exit_level":  50,
        "ma_length":   get_bars_for_period("200d", _TF, _MUL),
    },
)
def rsi_sma200_filter(df, **kwargs):
    """RSI mean reversion, only taken when the asset is above its 200-bar SMA.

    The trend filter prevents buying into confirmed downtrends — RSI oversold
    readings in a bear market are often "value traps".
    """
    return rsi_with_trend_filter_logic(
        df,
        rsi_length=kwargs["rsi_length"],
        oversold=kwargs["oversold"],
        exit_level=kwargs["exit_level"],
        ma_length=kwargs["ma_length"],
    )


# ---------------------------------------------------------------------------
# Sub-daily / scalping RSI strategy  (only registered when timeframe is MIN)
# ---------------------------------------------------------------------------

if _TF == "MIN":
    @register_strategy(
        name="1m RSI Extreme Fade (14/20/80)",
        dependencies=[],
        params={
            "rsi_length":       get_bars_for_period("14min", _TF, _MUL),
            "oversold_level":   20,
            "overbought_level": 80,
        },
    )
    def rsi_extreme_fade_1m(df, **kwargs):
        """Sub-daily RSI extreme-level fade strategy.

        Designed for minute-level bars (set ``timeframe = "MIN"`` in config).
        Buys when RSI crosses up from below 20; exits at the 50 midline.
        Uses extreme thresholds (20/80) rather than the standard 30/70 to reduce
        false signals on noisy intraday data.

        Note: ``get_bars_for_period("14min", TF, MUL)`` resolves to 14 bars on
        1-minute data, 7 bars on 2-minute, etc., keeping the period consistent
        regardless of multiplier.
        """
        return rsi_scalping_logic(
            df,
            rsi_length=kwargs["rsi_length"],
            oversold_level=kwargs["oversold_level"],
            overbought_level=kwargs["overbought_level"],
        )
