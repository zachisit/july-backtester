# custom_strategies/research_strategies_v1.py
"""
Round 1 Research Strategies — autonomous multi-agent research loop.

8 diverse strategies spanning: momentum, mean-reversion, breakout, volume-flow,
and oscillator families.  All use existing helpers/indicators.py logic — no new
indicator code is needed.
"""

from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import (
    roc_logic,
    bollinger_band_squeeze_logic,
    atr_trailing_stop_logic_breakout_entry,
    williams_r_logic,
    volume_weighted_rsi_logic,
    donchian_channel_breakout_logic,
    stochastic_logic,
    keltner_channel_breakout_logic,
)
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ---------------------------------------------------------------------------
# 1. Rate-of-Change Momentum (short window)
# ---------------------------------------------------------------------------
@register_strategy(
    name="ROC Momentum (10d)",
    dependencies=[],
    params={
        "length":    get_bars_for_period("10d", _TF, _MUL),
        "threshold": 0.0,
    },
)
def roc_momentum_10(df, **kwargs):
    """Buy when 10-bar ROC turns positive; exit when it turns negative.

    Short-window momentum — catches quick directional bursts.
    """
    return roc_logic(df, length=kwargs["length"], threshold=kwargs["threshold"])


# ---------------------------------------------------------------------------
# 2. Rate-of-Change Momentum (longer window)
# ---------------------------------------------------------------------------
@register_strategy(
    name="ROC Momentum (20d)",
    dependencies=[],
    params={
        "length":    get_bars_for_period("20d", _TF, _MUL),
        "threshold": 0.0,
    },
)
def roc_momentum_20(df, **kwargs):
    """Buy when 20-bar ROC turns positive; exit when it turns negative.

    Medium-window momentum — smoother than 10d, fewer whipsaws.
    """
    return roc_logic(df, length=kwargs["length"], threshold=kwargs["threshold"])


# ---------------------------------------------------------------------------
# 3. Bollinger Band Squeeze Breakout
# ---------------------------------------------------------------------------
@register_strategy(
    name="BB Squeeze Breakout",
    dependencies=[],
    params={
        "length":         get_bars_for_period("20d", _TF, _MUL),
        "std_dev":        2.0,
        "squeeze_length": get_bars_for_period("40d", _TF, _MUL),
    },
)
def bb_squeeze_breakout(df, **kwargs):
    """Bollinger Band squeeze: enter when bands expand after a compression period.

    Low volatility (squeeze) followed by expansion often precedes a strong move.
    """
    return bollinger_band_squeeze_logic(
        df,
        length=kwargs["length"],
        std_dev=kwargs["std_dev"],
        squeeze_length=kwargs["squeeze_length"],
    )


# ---------------------------------------------------------------------------
# 4. ATR Breakout with Trailing Stop
# ---------------------------------------------------------------------------
@register_strategy(
    name="ATR Breakout Trailing Stop",
    dependencies=[],
    params={
        "entry_period":   get_bars_for_period("20d", _TF, _MUL),
        "atr_period":     get_bars_for_period("14d", _TF, _MUL),
        "atr_multiplier": 3.0,
    },
)
def atr_breakout_trailing(df, **kwargs):
    """Price-channel breakout with ATR-based trailing stop.

    Enters on a 20-bar high breakout; exits when price falls below the
    3×ATR trailing stop.  Designed to ride trends while cutting losses quickly.
    """
    return atr_trailing_stop_logic_breakout_entry(
        df,
        entry_period=kwargs["entry_period"],
        atr_period=kwargs["atr_period"],
        atr_multiplier=kwargs["atr_multiplier"],
    )


# ---------------------------------------------------------------------------
# 5. Williams %R Mean Reversion
# ---------------------------------------------------------------------------
@register_strategy(
    name="Williams %R (14d)",
    dependencies=[],
    params={
        "length":      get_bars_for_period("14d", _TF, _MUL),
        "oversold":    -80,
        "exit_level":  -50,
    },
)
def williams_r_14(df, **kwargs):
    """Williams %R oversold bounce.

    Buys when Williams %R crosses back above -80 (oversold); exits at -50 midline.
    Similar to RSI mean reversion but derived from price range extremes.
    """
    return williams_r_logic(
        df,
        length=kwargs["length"],
        oversold=kwargs["oversold"],
        exit_level=kwargs["exit_level"],
    )


# ---------------------------------------------------------------------------
# 6. Volume-Weighted RSI
# ---------------------------------------------------------------------------
@register_strategy(
    name="Volume-Weighted RSI (14d)",
    dependencies=[],
    params={
        "length":      get_bars_for_period("14d", _TF, _MUL),
        "oversold":    30,
        "exit_level":  55,
    },
)
def vw_rsi_14(df, **kwargs):
    """Volume-weighted RSI mean reversion.

    Weights RSI gains/losses by volume — high-volume moves carry more
    signal weight.  Exit is set slightly higher (55) to capture fuller bounces.
    """
    return volume_weighted_rsi_logic(
        df,
        length=kwargs["length"],
        oversold=kwargs["oversold"],
        exit_level=kwargs["exit_level"],
    )


# ---------------------------------------------------------------------------
# 7. Donchian Channel Breakout
# ---------------------------------------------------------------------------
@register_strategy(
    name="Donchian Breakout (20/10)",
    dependencies=[],
    params={
        "entry_period": get_bars_for_period("20d", _TF, _MUL),
        "exit_period":  get_bars_for_period("10d", _TF, _MUL),
    },
)
def donchian_20_10(df, **kwargs):
    """Donchian channel breakout (Turtle-style).

    Enters on a 20-bar high breakout; exits when price falls below the
    10-bar low.  Classic trend-following system.
    """
    return donchian_channel_breakout_logic(
        df,
        entry_period=kwargs["entry_period"],
        exit_period=kwargs["exit_period"],
    )


# ---------------------------------------------------------------------------
# 8. Stochastic Oscillator Mean Reversion
# ---------------------------------------------------------------------------
@register_strategy(
    name="Stochastic Mean Reversion (14d)",
    dependencies=[],
    params={
        "length":      get_bars_for_period("14d", _TF, _MUL),
        "k_smooth":    3,
        "oversold":    20,
        "exit_level":  50,
    },
)
def stochastic_mr_14(df, **kwargs):
    """Stochastic %K/%D oversold bounce.

    Buys when the smoothed %K crosses back above 20; exits at the 50 midline.
    The 3-bar smoothing reduces false signals from choppy price action.
    """
    return stochastic_logic(
        df,
        length=kwargs["length"],
        k_smooth=kwargs["k_smooth"],
        oversold=kwargs["oversold"],
        exit_level=kwargs["exit_level"],
    )


# ---------------------------------------------------------------------------
# 9. Keltner Channel Breakout
# ---------------------------------------------------------------------------
@register_strategy(
    name="Keltner Breakout (20d/2x)",
    dependencies=[],
    params={
        "ema_length":     get_bars_for_period("20d", _TF, _MUL),
        "atr_length":     get_bars_for_period("14d", _TF, _MUL),
        "atr_multiplier": 2.0,
    },
)
def keltner_breakout_20(df, **kwargs):
    """Keltner channel breakout — EMA-centred, ATR-width bands.

    Enters on a close above the upper Keltner band (EMA + 2×ATR).
    Keltner channels are tighter than Bollinger Bands, giving fewer but
    higher-conviction breakout signals.
    """
    return keltner_channel_breakout_logic(
        df,
        ema_length=kwargs["ema_length"],
        atr_length=kwargs["atr_length"],
        atr_multiplier=kwargs["atr_multiplier"],
    )
