# custom_strategies/btc_strategies_v3.py
"""Bitcoin new signal family strategies (BTC-R8/R9/R10).

Three signal families not yet tested on Bitcoin daily:

  1. CMF (Chaikin Money Flow) — volume-flow signal
     BTC-R1 showed CMF had RS(min) = -3.14 (best tail risk of all tested strategies).
     Volume flow naturally avoids bear market entry due to selling pressure.
     Two variants: standard (20d) and optimized shorter (14d with SMA120 gate).

  2. Price Momentum (ROC) — rate-of-change momentum
     BTC-R1 failed with ROC > 15% (16 trades / 9 years — too sparse).
     Fix: lower threshold to 5%, test 90-day and 180-day lookbacks.
     SMA200 gate prevents bear-market entries.

  3. BB Breakout (Bollinger Band upper-band breakout) — volatility breakout
     Existing BB strategy is a FADE (buy lower band). This is the OPPOSITE:
     buy when price breaks ABOVE upper band (momentum/volatility signal).
     Exit when price falls back below the middle band.
     Two variants: tight (20d/2.5σ) and looser (30d/2.0σ).

All use existing helpers/indicators.py functions. No SPY/VIX dependencies.
"""

import numpy as np
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import (
    chaikin_money_flow_logic,
    calculate_bollinger_bands,
    calculate_sma,
)
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ===========================================================================
# SIGNAL FAMILY 1 — CMF (Chaikin Money Flow) + SMA Gate
# ===========================================================================

@register_strategy(
    name="BTC CMF Trend (20d/0.05) + SMA200",
    dependencies=[],
    params={
        "cmf_length":       get_bars_for_period("20d", _TF, _MUL),
        "buy_threshold":    0.05,
        "sell_threshold":  -0.05,
        "gate_length":      get_bars_for_period("200d", _TF, _MUL),
    },
)
def btc_cmf_trend_20_sma200(df, **kwargs):
    """CMF(20) crossover above 0.05 with SMA(200) uptrend gate; exit on CMF < -0.05.

    Entry logic: CMF crosses from below 0.05 to above (net buying pressure confirmed)
    AND price is above SMA(200) (macro uptrend).

    CMF > 0.05 means ~5% more volume flowed in on up-bars than down-bars over 20 days.
    This is a meaningful threshold — noise in BTC often produces CMF oscillation near zero.

    SMA200 gate prevents buying into bear-market volume spikes (e.g., dead-cat bounces
    in 2018 and 2022 where CMF may briefly spike positive).

    Exit: CMF crosses below -0.05 (selling pressure confirmed) — unconditional.
    """
    cmf_length      = kwargs["cmf_length"]
    buy_threshold   = kwargs["buy_threshold"]
    sell_threshold  = kwargs["sell_threshold"]
    gate_length     = kwargs["gate_length"]

    # Compute CMF column via existing function (Signal output overridden below)
    df = chaikin_money_flow_logic(df, length=cmf_length,
                                   buy_threshold=buy_threshold,
                                   sell_threshold=sell_threshold)

    # Add SMA gate
    df = calculate_sma(df, length=gate_length)
    sma_col = f'SMA_{gate_length}'
    is_uptrend = df["Close"] > df[sma_col]

    # Gated entry: CMF crossover AND uptrend
    buy_signal  = (df['CMF'].shift(1) < buy_threshold) & (df['CMF'] >= buy_threshold) & is_uptrend
    sell_signal = (df['CMF'].shift(1) > sell_threshold) & (df['CMF'] <= sell_threshold)

    df["Signal"] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
    return df


@register_strategy(
    name="BTC CMF Trend (14d/0.05) + SMA120",
    dependencies=[],
    params={
        "cmf_length":       get_bars_for_period("14d", _TF, _MUL),
        "buy_threshold":    0.05,
        "sell_threshold":  -0.05,
        "gate_length":      get_bars_for_period("120d", _TF, _MUL),
    },
)
def btc_cmf_trend_14_sma120(df, **kwargs):
    """CMF(14) crossover above 0.05 with SMA(120) uptrend gate; exit on CMF < -0.05.

    Optimized variant informed by RSI Trend research: shorter indicator period
    (14 vs 20) + shorter gate (SMA120 vs SMA200) = earlier entries in bull markets.

    CMF(14) is more responsive than CMF(20) — detects buying pressure shifts 6 bars
    earlier. The SMA(120) gate confirms uptrend ~80 bars earlier than SMA(200).
    Combined: this variant should capture more of each Bitcoin bull run.

    Risk: more responsive = potentially noisier in sideways/volatile conditions.
    The CMF threshold (0.05) acts as a filter; pure noise rarely sustains CMF > 0.05.
    """
    cmf_length      = kwargs["cmf_length"]
    buy_threshold   = kwargs["buy_threshold"]
    sell_threshold  = kwargs["sell_threshold"]
    gate_length     = kwargs["gate_length"]

    df = chaikin_money_flow_logic(df, length=cmf_length,
                                   buy_threshold=buy_threshold,
                                   sell_threshold=sell_threshold)

    df = calculate_sma(df, length=gate_length)
    sma_col = f'SMA_{gate_length}'
    is_uptrend = df["Close"] > df[sma_col]

    buy_signal  = (df['CMF'].shift(1) < buy_threshold) & (df['CMF'] >= buy_threshold) & is_uptrend
    sell_signal = (df['CMF'].shift(1) > sell_threshold) & (df['CMF'] <= sell_threshold)

    df["Signal"] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
    return df


# ===========================================================================
# SIGNAL FAMILY 2 — Price Momentum (ROC) + SMA Gate
# ===========================================================================

@register_strategy(
    name="BTC Price Momentum (54d/5%) + SMA200",
    dependencies=[],
    params={
        "roc_length":       get_bars_for_period("54d", _TF, _MUL),
        "roc_threshold":    5.0,
        "gate_length":      get_bars_for_period("200d", _TF, _MUL),
    },
)
def btc_price_momentum_54_sma200(df, **kwargs):
    """~2-month ROC > 5% with SMA(200) gate; exit on ROC turning negative.

    Derived from BTC-R9 sweep of Price Momentum (90d/5%). The roc_length=54
    zone (sweep -2 step from 90) achieves:
    - Calmar 1.29 (vs base 90d Calmar 0.84)
    - MaxDD 45.2% (vs base 64.89%) — 20pp improvement
    - 25/25 variants profitable, 23/24 WFA pass (92%)

    54 days ≈ 7.7 weeks. This roughly corresponds to Bitcoin's ~6-8 week
    momentum cycles within bull markets. A 54-day new high indicates sustained
    upward pressure over a meaningful time horizon — not a short-term spike.

    The 90-day base was too long: it enters momentum positions AFTER the best
    gains (90 days into a run), leading to high drawdowns when the run ends.
    54 days captures the momentum earlier while still filtering daily noise.
    """
    roc_length      = kwargs["roc_length"]
    roc_threshold   = kwargs["roc_threshold"]
    gate_length     = kwargs["gate_length"]

    df['ROC'] = df['Close'].pct_change(periods=roc_length) * 100
    df = calculate_sma(df, length=gate_length)
    sma_col = f'SMA_{gate_length}'
    is_uptrend = df["Close"] > df[sma_col]

    buy_signal  = (df['ROC'] > roc_threshold) & is_uptrend
    sell_signal = df['ROC'] < 0.0

    df["Signal"] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
    return df


@register_strategy(
    name="BTC Price Momentum (90d/5%) + SMA200",
    dependencies=[],
    params={
        "roc_length":       get_bars_for_period("90d", _TF, _MUL),
        "roc_threshold":    5.0,
        "gate_length":      get_bars_for_period("200d", _TF, _MUL),
    },
)
def btc_price_momentum_90_sma200(df, **kwargs):
    """3-month ROC > 5% with SMA(200) uptrend gate; exit on ROC turning negative.

    BTC-R1 used 6-month ROC > 15% — produced only 16 trades (too sparse).
    Fix: 90-day ROC (3-month) with a 5% threshold.

    ROC(90) > 5%: price is at least 5% higher than it was 90 days ago — sustained
    3-month positive momentum. This filters out short-term noise.

    SMA200 gate: prevents entering on momentum spikes in bear markets.

    Exit: ROC turns negative (3-month price change turns negative = structural
    momentum failure, not just a short-term dip).
    """
    roc_length      = kwargs["roc_length"]
    roc_threshold   = kwargs["roc_threshold"]
    gate_length     = kwargs["gate_length"]

    df['ROC'] = df['Close'].pct_change(periods=roc_length) * 100

    df = calculate_sma(df, length=gate_length)
    sma_col = f'SMA_{gate_length}'
    is_uptrend = df["Close"] > df[sma_col]

    buy_signal  = (df['ROC'] > roc_threshold) & is_uptrend
    sell_signal = df['ROC'] < 0.0

    df["Signal"] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
    return df


@register_strategy(
    name="BTC Price Momentum (180d/5%) + SMA200",
    dependencies=[],
    params={
        "roc_length":       get_bars_for_period("180d", _TF, _MUL),
        "roc_threshold":    5.0,
        "gate_length":      get_bars_for_period("200d", _TF, _MUL),
    },
)
def btc_price_momentum_180_sma200(df, **kwargs):
    """6-month ROC > 5% with SMA(200) uptrend gate; exit on ROC turning negative.

    6-month lookback: aligns with Bitcoin's ~6-month accumulation/distribution
    cycles within each halving cycle. ROC(180) > 5% indicates a sustained
    6-month uptrend (filters all bear market months and choppy sideways periods).

    ROC(180) generates fewer entries than ROC(90) — more selective, higher conviction.
    Risk: fewer trades = less WFA statistical power.
    """
    roc_length      = kwargs["roc_length"]
    roc_threshold   = kwargs["roc_threshold"]
    gate_length     = kwargs["gate_length"]

    df['ROC'] = df['Close'].pct_change(periods=roc_length) * 100

    df = calculate_sma(df, length=gate_length)
    sma_col = f'SMA_{gate_length}'
    is_uptrend = df["Close"] > df[sma_col]

    buy_signal  = (df['ROC'] > roc_threshold) & is_uptrend
    sell_signal = df['ROC'] < 0.0

    df["Signal"] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
    return df


# ===========================================================================
# SIGNAL FAMILY 3 — BB Breakout (upper band breakout) + SMA Gate
# ===========================================================================

@register_strategy(
    name="BTC BB Breakout (20d/2.5σ) + SMA200",
    dependencies=[],
    params={
        "bb_length":        get_bars_for_period("20d", _TF, _MUL),
        "std_dev":          2.5,
        "gate_length":      get_bars_for_period("200d", _TF, _MUL),
    },
)
def btc_bb_breakout_20_25(df, **kwargs):
    """Price closes ABOVE Bollinger upper band (20d/2.5σ) with SMA200 gate; exit below mid-band.

    OPPOSITE of the standard BB Fade strategy (which buys at lower band).
    This is a BREAKOUT strategy: upper band touch = price escaped the normal
    volatility range = momentum continuation signal.

    2.5σ upper band: on daily data, a close above the 2.5σ band occurs ~1.2% of
    the time in a normal distribution. For Bitcoin, this means genuine momentum
    breakouts — not just routine volatility.

    Exit: price falls back below the middle band (20-day SMA). The middle band
    is the trend mean; a close below it means the breakout momentum has failed.

    SMA200 gate: prevents buying breakouts during bear market bounces.
    """
    bb_length   = kwargs["bb_length"]
    std_dev     = kwargs["std_dev"]
    gate_length = kwargs["gate_length"]

    df = calculate_bollinger_bands(df, length=bb_length, std_dev=std_dev)
    df = calculate_sma(df, length=gate_length)
    sma_col = f'SMA_{gate_length}'
    mid_band = f'SMA_{bb_length}'

    is_uptrend  = df["Close"] > df[sma_col]
    buy_signal  = (df["Close"] > df["UpperBand"]) & is_uptrend
    sell_signal = df["Close"] < df[mid_band]

    df["Signal"] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
    return df


@register_strategy(
    name="BTC BB Breakout (30d/2.0σ) + SMA200",
    dependencies=[],
    params={
        "bb_length":        get_bars_for_period("30d", _TF, _MUL),
        "std_dev":          2.0,
        "gate_length":      get_bars_for_period("200d", _TF, _MUL),
    },
)
def btc_bb_breakout_30_20(df, **kwargs):
    """Price closes ABOVE Bollinger upper band (30d/2.0σ) with SMA200 gate; exit below mid-band.

    Wider lookback (30d vs 20d) + tighter band (2.0σ vs 2.5σ):
    - 30-day SMA and StdDev: smoother, less reactive to short-term spikes
    - 2.0σ: fires more frequently than 2.5σ (upper band crossed ~2.3% of the time
      in a normal distribution vs 1.2% at 2.5σ) — more trades, potentially noisier

    This variant trades the frequency/precision tradeoff differently than the 20d/2.5σ.
    30d lookback aligns better with Bitcoin's monthly cycle patterns.

    Same exit and gate logic as the 20d/2.5σ variant.
    """
    bb_length   = kwargs["bb_length"]
    std_dev     = kwargs["std_dev"]
    gate_length = kwargs["gate_length"]

    df = calculate_bollinger_bands(df, length=bb_length, std_dev=std_dev)
    df = calculate_sma(df, length=gate_length)
    sma_col = f'SMA_{gate_length}'
    mid_band = f'SMA_{bb_length}'

    is_uptrend  = df["Close"] > df[sma_col]
    buy_signal  = (df["Close"] > df["UpperBand"]) & is_uptrend
    sell_signal = df["Close"] < df[mid_band]

    df["Signal"] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
    return df
