# custom_strategies/bull_flag.py
"""Bull Flag Breakout strategy plugin.

Pattern definition (daily bars)
-------------------------------
1. FLAGPOLE  — a sharp advance: >= ``pole_min_gain`` (default 12%) from the
   lowest low to the highest high within ``pole_max_bars`` (default 15).
2. FLAG      — a short, shallow rest after the pole: ``flag_min_bars`` to
   ``flag_max_bars`` (default 3-15) bars, holding above
   ``pole_high - flag_max_retrace * pole_height`` (default 40% retrace max),
   with average flag volume not exceeding
   ``flag_vol_contraction`` x average pole volume (default 1.0 — the flag
   must not expand volume relative to the pole).
3. BREAKOUT  — today's Close clears the flag high on expanding volume
   (>= ``breakout_vol_mult`` x ``vol_ma_bars``-bar average volume; default
   1.1x — note the rolling average is already inflated by pole volume).

Defaults were tuned once from a gate-funnel diagnostic on 10 momentum names
(2018-2026): the original 18%/12-bar pole, 0.75 contraction, and 1.5x
breakout-volume gates yielded 3 trades in 8.5 years, with the volume gate
alone rejecting 47 of 50 otherwise-valid breakouts.

Entry is detected on the bar CLOSE (end-of-day knowable, no intrabar
lookahead — see the warning on ``atr_trailing_stop_logic_breakout_entry``
in helpers/indicators.py). The simulation engine handles the fill.

Exits (checked on Close, in order):
- stop:      Close <= flag low ("the flag failed")
- target:    Close >= flag high + pole height (classic measured move)
- time stop: position older than ``time_stop_bars`` (default 20)

Quality filters at entry: Close above the ``trend_ma_bars`` SMA (markup
phase only), Close >= ``min_price``, and average dollar volume
>= ``min_dollar_volume``.

In Wyckoff terms this is a short re-accumulation inside markup — distinct
from longer consolidation bases (the flag window is capped at 15 bars).

To run only this strategy, set in config.py:
    "strategies": ["Bull Flag Breakout"]

All pattern logic is self-contained in this file. Only the frozen helpers
(``calculate_sma``) are imported from helpers/indicators.py — nothing in
that file is modified.
"""

import numpy as np
import pandas as pd

from helpers.registry import register_strategy
from helpers.indicators import calculate_sma
from helpers.timeframe_utils import get_bars_for_period
from config import CONFIG

_TF = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


@register_strategy(
    name="Bull Flag Breakout",
    dependencies=[],
    params={
        "pole_min_gain": 0.12,
        "pole_max_bars": get_bars_for_period("15d", _TF, _MUL),
        "flag_min_bars": get_bars_for_period("3d", _TF, _MUL),
        "flag_max_bars": get_bars_for_period("15d", _TF, _MUL),
        "flag_max_retrace": 0.40,
        "flag_vol_contraction": 1.0,
        "breakout_vol_mult": 1.1,
        "vol_ma_bars": get_bars_for_period("20d", _TF, _MUL),
        "trend_ma_bars": get_bars_for_period("50d", _TF, _MUL),
        "time_stop_bars": get_bars_for_period("20d", _TF, _MUL),
        "min_price": 5.0,
        "min_dollar_volume": 5_000_000.0,
    },
)
def bull_flag_breakout(df, **kwargs):
    """Buy flag breakouts after a momentum pole; exit on stop/target/time.

    Signal convention (see helpers/registry.py):
      1 = enter / hold long, -1 = exit / flat, 0 = no change.
    """
    pole_min_gain = kwargs["pole_min_gain"]
    pole_max_bars = int(kwargs["pole_max_bars"])
    flag_min_bars = int(kwargs["flag_min_bars"])
    flag_max_bars = int(kwargs["flag_max_bars"])
    flag_max_retrace = kwargs["flag_max_retrace"]
    flag_vol_contraction = kwargs["flag_vol_contraction"]
    breakout_vol_mult = kwargs["breakout_vol_mult"]
    vol_ma_bars = int(kwargs["vol_ma_bars"])
    trend_ma_bars = int(kwargs["trend_ma_bars"])
    time_stop_bars = int(kwargs["time_stop_bars"])
    min_price = kwargs["min_price"]
    min_dollar_volume = kwargs["min_dollar_volume"]

    # --- Indicators ------------------------------------------------------
    df = calculate_sma(df, trend_ma_bars)
    trend_ma = df[f"SMA_{trend_ma_bars}"].to_numpy(dtype=float)
    vol_ma = (
        df["Volume"].rolling(window=vol_ma_bars).mean().to_numpy(dtype=float)
    )

    highs = df["High"].to_numpy(dtype=float)
    lows = df["Low"].to_numpy(dtype=float)
    closes = df["Close"].to_numpy(dtype=float)
    volumes = df["Volume"].to_numpy(dtype=float)

    n = len(df)
    lookback = flag_max_bars + pole_max_bars
    warmup = max(lookback + 1, vol_ma_bars, trend_ma_bars)

    # --- Safety check (mirrors the pattern used across the repo) ---------
    if n <= warmup:
        df["Signal"] = 0
        return df

    # --- Stateful scan ----------------------------------------------------
    signals = [0] * warmup
    in_position = False
    stop_level = 0.0
    target_level = 0.0
    bars_held = 0

    for i in range(warmup, n):
        # --- CHECK FOR EXIT FIRST (all on Close, end-of-day knowable) ----
        if in_position:
            bars_held += 1
            if (
                closes[i] <= stop_level
                or closes[i] >= target_level
                or bars_held >= time_stop_bars
            ):
                in_position = False
                stop_level = 0.0
                target_level = 0.0
                bars_held = 0

        # --- CHECK FOR ENTRY ---------------------------------------------
        if not in_position:
            setup = _detect_flag_breakout(
                i,
                highs,
                lows,
                closes,
                volumes,
                trend_ma,
                vol_ma,
                lookback=lookback,
                pole_max_bars=pole_max_bars,
                pole_min_gain=pole_min_gain,
                flag_min_bars=flag_min_bars,
                flag_max_bars=flag_max_bars,
                flag_max_retrace=flag_max_retrace,
                flag_vol_contraction=flag_vol_contraction,
                breakout_vol_mult=breakout_vol_mult,
                min_price=min_price,
                min_dollar_volume=min_dollar_volume,
            )
            if setup is not None:
                flag_high, flag_low, pole_height = setup
                in_position = True
                stop_level = flag_low
                target_level = flag_high + pole_height  # measured move
                bars_held = 0

        signals.append(1 if in_position else 0)

    # --- Convert position series to engine Signal convention --------------
    final_signals = pd.Series(signals, index=df.index, dtype=float)
    df["Signal"] = np.where(final_signals.diff() == -1, -1, final_signals)
    df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)

    return df


def _detect_flag_breakout(
    i,
    highs,
    lows,
    closes,
    volumes,
    trend_ma,
    vol_ma,
    *,
    lookback,
    pole_max_bars,
    pole_min_gain,
    flag_min_bars,
    flag_max_bars,
    flag_max_retrace,
    flag_vol_contraction,
    breakout_vol_mult,
    min_price,
    min_dollar_volume,
):
    """Return (flag_high, flag_low, pole_height) if bar ``i`` is a valid
    bull-flag breakout, else None.

    The swing high of the lookback window anchors the structure: bars up to
    and including it are the pole, bars strictly between it and ``i`` are
    the flag.
    """
    if np.isnan(vol_ma[i]) or np.isnan(trend_ma[i]):
        return None

    # --- Liquidity / trend filters (cheap, check first) -------------------
    if closes[i] < min_price:
        return None
    if vol_ma[i] * closes[i] < min_dollar_volume:
        return None
    if closes[i] <= trend_ma[i]:
        return None

    # --- Anchor: swing high inside the lookback window --------------------
    win_start = i - lookback
    window_highs = highs[win_start:i]
    idx_high = win_start + int(np.argmax(window_highs))

    flag_len = i - idx_high - 1
    if not (flag_min_bars <= flag_len <= flag_max_bars):
        return None

    # --- Pole: lowest low within pole_max_bars ending at the swing high ---
    pole_start = max(0, idx_high - pole_max_bars + 1)
    pole_high = highs[idx_high]
    pole_low = float(np.min(lows[pole_start : idx_high + 1]))
    pole_height = pole_high - pole_low
    if pole_low <= 0 or pole_height <= 0:
        return None
    if (pole_height / pole_low) < pole_min_gain:
        return None

    # --- Flag: shallow, tight rest after the pole --------------------------
    flag_highs = highs[idx_high + 1 : i]
    flag_lows = lows[idx_high + 1 : i]
    flag_vols = volumes[idx_high + 1 : i]

    flag_high = float(np.max(flag_highs))
    flag_low = float(np.min(flag_lows))

    if flag_low < pole_high - flag_max_retrace * pole_height:
        return None  # pullback too deep — not a flag

    pole_vol_avg = float(np.mean(volumes[pole_start : idx_high + 1]))
    flag_vol_avg = float(np.mean(flag_vols))
    if pole_vol_avg <= 0 or flag_vol_avg > flag_vol_contraction * pole_vol_avg:
        return None  # volume did not dry up — looks like distribution

    # --- Breakout trigger on the current bar's Close ----------------------
    if closes[i] <= flag_high:
        return None
    if volumes[i] < breakout_vol_mult * vol_ma[i]:
        return None  # breakout without volume is suspect

    return flag_high, flag_low, pole_height
