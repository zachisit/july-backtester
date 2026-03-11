# custom_strategies/sma_crossovers.py
"""SMA Crossover strategy plugin.

Both variants are registered automatically when this module is imported
via ``load_strategies("custom_strategies")``.  No edits to ``strategies.py``
or ``main.py`` are needed to add, remove, or rename them.

To add another SMA pair, copy one of the functions below, change the
decorator arguments, and adjust the ``fast``/``slow`` params — done.
"""

from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import sma_crossover_logic
from config import CONFIG

_TIMEFRAME  = CONFIG.get("timeframe", "D")
_MULTIPLIER = CONFIG.get("timeframe_multiplier", 1)


@register_strategy(
    name="SMA Crossover (20d/50d)",
    dependencies=[],
    params={
        "fast": get_bars_for_period("20d", _TIMEFRAME, _MULTIPLIER),
        "slow": get_bars_for_period("50d", _TIMEFRAME, _MULTIPLIER),
    },
)
def sma_crossover_20_50(df, **kwargs):
    """SMA crossover: 20-bar fast MA vs 50-bar slow MA.

    Timeframe-agnostic — bar counts are resolved from the config at import
    time via ``get_bars_for_period``, so the strategy works identically on
    daily, hourly, or minute data without any code changes.

    Signal convention: 1 = long (fast > slow), -1 = exit (fast < slow).
    """
    return sma_crossover_logic(df, fast=kwargs["fast"], slow=kwargs["slow"])


@register_strategy(
    name="SMA Crossover (50d/200d)",
    dependencies=[],
    params={
        "fast": get_bars_for_period("50d", _TIMEFRAME, _MULTIPLIER),
        "slow": get_bars_for_period("200d", _TIMEFRAME, _MULTIPLIER),
    },
)
def sma_crossover_50_200(df, **kwargs):
    """SMA crossover: 50-bar fast MA vs 200-bar slow MA (Golden/Death Cross).

    Timeframe-agnostic — bar counts are resolved from the config at import
    time via ``get_bars_for_period``.
    """
    return sma_crossover_logic(df, fast=kwargs["fast"], slow=kwargs["slow"])
