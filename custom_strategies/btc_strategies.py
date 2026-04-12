# custom_strategies/btc_strategies.py
"""Bitcoin-specific strategy plugins (BTC-Q3).

Three strategies designed from first principles for Bitcoin's unique market
structure: 4-year halving cycles, 365-day trading, extreme volatility, and
high autocorrelation between bull/bear regimes.

  1. BTC SMA200 Pure Trend (3-day exit)
     Enters on SMA(200) cross-up. Exits only after 3 consecutive closes below
     SMA(200) — avoids whipsaw exits during normal intra-trend corrections.

  2. BTC Donchian Wider (52/13)
     52-bar new high entry (quarterly momentum), 13-bar new low exit (2-week low).
     Wider than the 40/20 equity Donchian: Bitcoin's slower trends need more room.

  3. BTC RSI Trend (14/60/40) + SMA200
     RSI(14) > 60 AND price > SMA(200) → enter (confirmed momentum in uptrend).
     RSI(14) < 40 → exit (momentum failure). Trend entry, not mean-reversion.

All use existing helpers/indicators.py functions or inline logic.
All use get_bars_for_period for timeframe compatibility.
No SPY/VIX dependencies — single-asset Bitcoin needs no external benchmark filter.
"""

import numpy as np
from helpers.registry import register_strategy
from helpers.timeframe_utils import get_bars_for_period
from helpers.indicators import (
    donchian_channel_breakout_logic,
    calculate_sma,
    calculate_rsi,
)
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


# ===========================================================================
# STRATEGY 1 — BTC SMA200 Pure Trend (3-day exit confirmation)
# ===========================================================================

@register_strategy(
    name="BTC SMA200 Pure Trend (3-day exit)",
    dependencies=[],
    params={
        "gate_length": get_bars_for_period("200d", _TF, _MUL),
        "exit_bars":   3,
    },
)
def btc_sma200_pure_trend(df, **kwargs):
    """SMA(200) crossover entry with 3-consecutive-close exit confirmation.

    Entry: Close crosses ABOVE SMA(200) — first bar where Close > SMA200
    AND the previous bar had Close <= SMA200.  Requires a confirmed crossover,
    not just being above the SMA (to avoid entering mid-trend).

    Exit: 3 consecutive closes BELOW SMA(200) confirms trend reversal.
    A single close below is NOT an exit — Bitcoin dips below the 200-bar SMA
    during corrections within ongoing bull markets (e.g., Sep 2021, Mar 2023).
    3 consecutive closes is a structural break signal.

    Rationale:
    - SMA(200) is THE most-watched Bitcoin indicator. Institutional flows,
      on-chain analysts, and retail all track this level. Crossovers create
      genuine coordinated momentum, not noise.
    - The 3-day exit prevents whipsaws from brief dips-and-recoveries while
      still catching the early phases of the 2018 and 2022 bear markets.
    - No other filter needed: the SMA200 IS the trend filter.
    """
    gate_length = kwargs["gate_length"]
    exit_bars   = kwargs["exit_bars"]

    df = calculate_sma(df, length=gate_length)
    sma_col = f'SMA_{gate_length}'

    is_above = df["Close"] > df[sma_col]
    was_above = is_above.shift(1).fillna(False)

    # Entry: fresh crossover above SMA200
    cross_up = is_above & ~was_above

    # Exit: N consecutive closes below SMA200
    is_below = ~is_above
    consecutive_below = is_below.rolling(window=exit_bars).sum()
    confirmed_below = consecutive_below == exit_bars

    df["Signal"] = np.where(cross_up, 1, np.where(confirmed_below, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
    return df


# ===========================================================================
# STRATEGY 2 — BTC Donchian Wider (52/13)
# ===========================================================================

@register_strategy(
    name="BTC Donchian Wider (52/13)",
    dependencies=[],
    params={
        "entry_period": get_bars_for_period("52d", _TF, _MUL),
        "exit_period":  get_bars_for_period("13d", _TF, _MUL),
    },
)
def btc_donchian_wider(df, **kwargs):
    """52-bar new high entry, 13-bar new low exit — wider Donchian for Bitcoin.

    Uses the standard Donchian breakout mechanism from indicators.py but with
    wider periods calibrated to Bitcoin's quarterly momentum cycle:

    - Entry at 52-bar new high (≈ 52 calendar days / ~7.5 weeks):
      Captures quarterly momentum. Bitcoin's bull runs typically re-establish
      new highs every 6-12 weeks during uptrends. The 52-bar high is selective
      enough to filter out minor local rallies.

    - Exit at 13-bar new low (≈ 13 calendar days / 2 weeks):
      A 2-week low is a meaningful support failure signal on Bitcoin.
      Tighter than the entry to give profits room; wider than daily noise.

    Rationale vs the 40/20 equity Donchian:
    - Equity Donchian (40/20) on Bitcoin had Calmar 0.83 = BTC B&H Calmar.
    - 52/13 captures the quarterly cycle more precisely for Bitcoin's
      365-day-per-year market structure where 40 bars = only 40 calendar days.
    - 52 bars on Bitcoin ≈ 40 bars on equities (252 trading days vs 365).
    """
    return donchian_channel_breakout_logic(
        df,
        entry_period=kwargs["entry_period"],
        exit_period=kwargs["exit_period"],
    )


# ===========================================================================
# STRATEGY 3 — BTC RSI Trend (14/60/40) + SMA200
# ===========================================================================

@register_strategy(
    name="BTC RSI Trend (14/60/40) + SMA200",
    dependencies=[],
    params={
        "rsi_length":    get_bars_for_period("14d", _TF, _MUL),
        "entry_level":   60,
        "exit_level":    40,
        "gate_length":   get_bars_for_period("200d", _TF, _MUL),
    },
)
def btc_rsi_trend(df, **kwargs):
    """RSI momentum entry (>60) in confirmed uptrend (>SMA200); exit on RSI<40.

    This is NOT a mean-reversion RSI strategy. It is a MOMENTUM strategy:
    - Entry: RSI(14) > 60 AND Close > SMA(200)
      RSI > 60 = confirmed upward momentum, not just a bounce.
      SMA200 gate = we are in a macro bull market structure.
    - Exit: RSI(14) < 40 (momentum failure) — unconditional, no SMA gate.

    Why RSI > 60 for entry (not the standard oversold RSI buy):
    - Standard RSI mean reversion (buy at RSI < 30) fails on Bitcoin
      because Bitcoin can stay "oversold" for months during bear markets.
    - RSI > 60 on DAILY bars means sustained buying pressure over 14 days.
      This distinguishes a genuine trend entry from a bear-market noise spike.
    - RSI < 40 for exit is the symmetric "momentum failure" signal.

    Why SMA200 gate:
    - RSI > 60 during a bear market can be a "dead cat bounce" signal.
    - Requiring Close > SMA(200) ensures the RSI momentum signal fires only
      in confirmed macro uptrends, filtering 2018 and 2022 bear market signals.

    Expected profile: fewer trades than SMA200 crossover strategy but higher
    conviction entries. Win rate > 50% expected. Complementary to MA Bounce
    (which buys on weakness/pullbacks to SMA50 — opposite entry logic).
    """
    rsi_length  = kwargs["rsi_length"]
    entry_level = kwargs["entry_level"]
    exit_level  = kwargs["exit_level"]
    gate_length = kwargs["gate_length"]

    # RSI calculation
    df = calculate_rsi(df, length=rsi_length)
    rsi_col = f'RSI_{rsi_length}'

    # SMA200 gate
    df = calculate_sma(df, length=gate_length)
    sma_col = f'SMA_{gate_length}'

    is_uptrend = df["Close"] > df[sma_col]
    rsi_above_entry = df[rsi_col] > entry_level
    rsi_below_exit  = df[rsi_col] < exit_level

    # Entry: RSI > entry_level AND in uptrend (SMA200 gate)
    buy_signal  = rsi_above_entry & is_uptrend
    # Exit: RSI < exit_level (unconditional — catches momentum failure)
    sell_signal = rsi_below_exit

    df["Signal"] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
    return df
