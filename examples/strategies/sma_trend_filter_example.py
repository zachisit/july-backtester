# examples/strategies/sma_trend_filter_example.py
"""
EXAMPLE STRATEGY: Price Above 200-Day SMA Trend Filter
=======================================================
Difficulty: Beginner

This is one of the simplest possible strategies. It stays long whenever
the closing price is above the 200-day simple moving average, and goes
flat (exits) whenever price drops below it.

How to use:
    Copy this file into custom_strategies/ and run:
        python main.py --dry-run
    You should see "SMA 200 Trend Filter (Example)" in the strategy count.

Signal convention (used by all strategies in this engine):
    1  = enter or hold a long position
   -1  = exit / go flat
    0  = no change (the engine forward-fills the previous signal)
"""

# --- Step 1: Import the required pieces ---

# The decorator that registers your function with the engine.
from helpers.registry import register_strategy

# Converts human-readable periods ("200d") into bar counts for any timeframe.
# Always use this instead of hardcoding integers — it makes your strategy
# work on daily, hourly, or minute bars without any code changes.
from helpers.timeframe_utils import get_bars_for_period

# We reuse the existing SMA trend filter logic from indicators.py.
# You can also write your logic inline (see the signal section below).
from helpers.indicators import sma_trend_filter_logic

# Read the current timeframe settings so get_bars_for_period can do its job.
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")       # e.g. "D" for daily
_MUL = CONFIG.get("timeframe_multiplier", 1)  # e.g. 1 for 1x daily bars


# --- Step 2: Register the strategy ---
#
# The @register_strategy decorator tells the engine:
#   - name:         what to call this strategy in reports and CSVs
#   - dependencies: external data it needs ([] = none, ["spy"] = SPY data,
#                   ["vix"] = VIX data, ["spy", "vix"] = both)
#   - params:       keyword arguments that get passed to your function
#                   at runtime via **kwargs

@register_strategy(
    name="SMA 200 Trend Filter (Example)",
    dependencies=[],        # This strategy only needs the symbol's own data
    params={
        "ma_length": get_bars_for_period("200d", _TF, _MUL),
        # On daily bars this resolves to 200.
        # On 5-minute bars it would resolve to a much larger number
        # (200 days × 78 bars/day = 15,600 bars).
    },
)
def sma_200_trend_filter_example(df, **kwargs):
    """
    Stay long when Close > 200-bar SMA, go flat when Close < 200-bar SMA.

    Parameters (via **kwargs)
    -------------------------
    ma_length : int
        Number of bars for the SMA calculation. Set in the params dict above.

    Returns
    -------
    pd.DataFrame
        The input DataFrame with a 'Signal' column added.
    """
    # Extract the parameter. The engine merges the params dict into kwargs.
    ma_length = kwargs["ma_length"]

    # Call the shared logic function from helpers/indicators.py.
    # This calculates the SMA, then sets Signal = 1 when Close > SMA,
    # and Signal = -1 when Close <= SMA.
    return sma_trend_filter_logic(df, ma_length=ma_length)


# --- That's it! ---
# To test: copy this file to custom_strategies/ and run:
#   python main.py --dry-run
#
# You should see the strategy count increase by 1.
# Then run a quick backtest:
#   python main.py
