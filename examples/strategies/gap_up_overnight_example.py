# examples/strategies/gap_up_overnight_example.py
"""
EXAMPLE STRATEGY: Gap-Up Overnight Hold with SPY Trend Filter
==============================================================
Difficulty: Beginner-to-Intermediate

Buys at the close when the stock gapped up at the open (Open > prior Close)
by at least 1%, then exits at the next bar. This captures overnight
continuation momentum after a strong gap day.

A SPY trend filter is layered on top: we only take entries when SPY is
above its 200-day SMA (bull market regime).

This example demonstrates:
    - How to declare dependencies (SPY data)
    - How the engine injects spy_df into **kwargs automatically
    - How to align external data to the primary symbol's index

How to use:
    Copy this file into custom_strategies/ and run:
        python main.py --dry-run
"""

import numpy as np
import pandas as pd
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


@register_strategy(
    name="Gap-Up Overnight Hold (Example)",

    # --- Dependencies ---
    # Declaring "spy" here tells the engine to fetch SPY data and pass it
    # into **kwargs as kwargs["spy_df"]. You can also use "vix" for VIX data
    # (injected as kwargs["vix_df"]), or both: ["spy", "vix"].
    dependencies=["spy"],

    params={
        "gap_pct": 0.01,        # Minimum gap size (1%)
        "regime_ma": get_bars_for_period("200d", _TF, _MUL),
    },
)
def gap_up_overnight_example(df, **kwargs):
    """
    Buy after a 1%+ gap-up day, only during a SPY bull regime. Exit next bar.

    Parameters (via **kwargs)
    -------------------------
    gap_pct : float
        Minimum open-to-prior-close gap as a fraction (0.01 = 1%).
    regime_ma : int
        SMA lookback for the SPY trend filter.
    spy_df : pd.DataFrame
        SPY price data — injected automatically because we declared
        dependencies=["spy"] in the decorator.
    """
    gap_pct   = kwargs["gap_pct"]
    regime_ma = kwargs["regime_ma"]
    spy_df    = kwargs["spy_df"]   # Injected by the engine

    # --- Part 1: Detect gap-up days ---
    # A gap-up means today's Open is at least gap_pct above yesterday's Close.
    prior_close = df['Close'].shift(1)
    gap_size = (df['Open'] - prior_close) / prior_close
    is_gap_up = gap_size >= gap_pct

    # --- Part 2: SPY regime filter ---
    # Calculate SPY's moving average and align it to our symbol's dates.
    spy_sma = spy_df['Close'].rolling(regime_ma).mean()

    # Create an aligned DataFrame to handle date mismatches gracefully.
    # The primary symbol might have different trading dates than SPY
    # (e.g., different listing date), so we reindex and forward-fill.
    regime_df = pd.DataFrame(index=df.index)
    regime_df['spy_close'] = spy_df['Close']
    regime_df['spy_sma']   = spy_sma
    regime_df.ffill(inplace=True)

    is_bull_market = regime_df['spy_close'] > regime_df['spy_sma']

    # --- Part 3: Combine into signals ---
    # Buy (1) on a gap-up day during a bull market.
    # Since we want a 1-bar hold, we exit (-1) on the very next bar.
    # We do this by setting the buy signal, then shifting exit by 1 bar.
    buy_signal = is_gap_up & is_bull_market

    # Start with all zeros, mark buy days as 1
    df['Signal'] = np.where(buy_signal, 1, 0)

    # For every buy signal, place an exit signal one bar later.
    # shift(-1) looks ahead one bar — on daily data, that means
    # "the next trading day". This gives us a 1-day hold.
    buy_shifted = buy_signal.shift(1).infer_objects(copy=False).fillna(False)
    df.loc[buy_shifted, 'Signal'] = -1

    # Forward-fill to maintain state between signals
    df['Signal'] = df['Signal'].replace(0, np.nan).ffill().fillna(0)

    return df
