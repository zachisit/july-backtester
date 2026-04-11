# custom_strategies/strategies_4h.py
"""
4-Hour Timeframe Research Strategies — Polygon Data

Round 7 update: Williams %R Dip-Recovery rejected (WFA Overfitted, OOS -5.60%).
Mean-reversion fails at 4H consistently (RSI Dip R1, Williams R R6 — same pattern).
Added Relative Strength Momentum (4H) as new 4th candidate: measures symbol's
return vs SPY return — relative outperformance as entry signal.

Strategy 1 (kept R1): EMA Velocity Breakout — EMA(10d/30d) cross + SMA(200d)
Strategy 2 (kept R2): Keltner Channel Breakout — Close > EMA(20d)+2×ATR(10d) upper
Strategy 3 (kept R4): Donchian Turtle — shift(1) N-bar high entry, N-bar low exit
Strategy 4 (new  R7): Relative Strength Momentum — symbol return > SPY return + SMA gate

Key differences from R1-R51 weekly/daily library:
  - Keltner channels were never used in any round (ATR-envelope breakout)
  - Donchian Turtle at 4H: 20 bars = ~12 calendar days; weekly Donchian spanned
    20 weeks = 140 days — structurally different breakout horizon and hold duration
  - The trailing N-bar-low exit is mathematically distinct from SMA/EMA exits
    used in all R1-R51 strategies

Bar-count helper (_b):
  get_bars_for_period("Xd", "H", 4) ignores the multiplier → wrong.
  Manual: 1 trading day = 6.5 h / 4 h per bar = 1.625 4H bars
    _b(10)  = round(10  × 1.625) =  16 bars
    _b(20)  = round(20  × 1.625) =  33 bars
    _b(25)  = round(25  × 1.625) =  41 bars
    _b(30)  = round(30  × 1.625) =  49 bars
    _b(50)  = round(50  × 1.625) =  81 bars
    _b(200) = round(200 × 1.625) = 325 bars

Only registered when timeframe == "H".
"""

import numpy as np
import pandas as pd
from helpers.registry import register_strategy
from helpers.indicators import calculate_sma
from config import CONFIG

_TF  = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)

# ── 4H bar-count helper ────────────────────────────────────────────────────────
# At H timeframe: 1 day = 6.5 / multiplier bars.
_BARS_PER_DAY = (6.5 / _MUL) if _TF == "H" else 1.0


def _b(days: int) -> int:
    """Translate calendar days → 4H bar count."""
    return max(2, round(days * _BARS_PER_DAY))


# ── ATR helper (Wilder smoothing) ─────────────────────────────────────────────
def _calc_atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Average True Range using Wilder's exponential smoothing."""
    h, l, c = df["High"], df["Low"], df["Close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    alpha = 1.0 / period
    return tr.ewm(alpha=alpha, adjust=False).mean()


if _TF == "H":

    # ══════════════════════════════════════════════════════════════════════════
    # STRATEGY 1 — EMA Velocity Breakout (4H)  [KEPT FROM ROUND 1]
    #
    # Round 1 result: P&L +175.85%, WFA Pass (3/3), OOS +48.68%, MC Score 5,
    # MaxDD 19.68%, 1019 trades. Clear leader — kept unchanged.
    #
    # Entry : EMA(10d) crosses above EMA(30d)  AND  price > SMA(200d)
    # Hold  : while EMA(10d) > EMA(30d)  AND  price > SMA(200d)
    # Exit  : EMA(10d) crosses below EMA(30d)  OR  price < SMA(200d)
    # ══════════════════════════════════════════════════════════════════════════
    @register_strategy(
        name="EMA Velocity Breakout (4H)",
        dependencies=[],
        params={
            "ema_fast":  _b(10),   # ~16 bars  ≈ 10 trading days
            "ema_slow":  _b(30),   # ~49 bars  ≈ 30 trading days
            "sma_trend": _b(200),  # ~325 bars ≈ 200 trading days
        },
    )
    def ema_velocity_breakout_4h(df, **kwargs):
        ema_fast  = kwargs["ema_fast"]
        ema_slow  = kwargs["ema_slow"]
        sma_trend = kwargs["sma_trend"]

        ema_f = df["Close"].ewm(span=ema_fast,  adjust=False).mean()
        ema_s = df["Close"].ewm(span=ema_slow,  adjust=False).mean()
        df    = calculate_sma(df, sma_trend)
        sma_col = f"SMA_{sma_trend}"

        is_trend = df["Close"] > df[sma_col]
        above    = ema_f > ema_s
        cross_up = above & ~above.shift(1).fillna(False)

        signals = []
        in_pos  = False
        for i in range(len(df)):
            if pd.isna(ema_s.iloc[i]) or pd.isna(df[sma_col].iloc[i]):
                signals.append(-1)
                continue
            if not in_pos:
                if cross_up.iloc[i] and is_trend.iloc[i]:
                    in_pos = True
                    signals.append(1)
                else:
                    signals.append(-1)
            else:
                if not above.iloc[i] or not is_trend.iloc[i]:
                    in_pos = False
                    signals.append(-1)
                else:
                    signals.append(1)

        df["Signal"] = signals
        df.drop(columns=[sma_col], errors="ignore", inplace=True)
        return df


    # ══════════════════════════════════════════════════════════════════════════
    # STRATEGY 2 — Keltner Channel Breakout (4H)  [NEW — Round 2]
    #
    # Keltner Channels = EMA(N) ± multiplier × ATR(M). The upper band acts as
    # a dynamic resistance level; closing ABOVE it signals that price has broken
    # out of its normal volatility range — a genuine momentum event.
    #
    # Keltner channels were never used in R1–R51 on any timeframe. They differ
    # from Bollinger Bands (which use std-dev) and from plain EMA crossovers in
    # that they explicitly incorporate daily range (ATR) rather than closing-
    # price dispersion. At 4H this gives a tighter, more responsive channel.
    #
    # Entry : Close > Keltner upper (EMA(20d) + 2 × ATR(10d))
    #         AND price > SMA(200d)
    # Hold  : while Close > Keltner middle (EMA midline)
    #         AND price > SMA(200d)
    # Exit  : Close < Keltner middle  OR  price < SMA(200d)
    # ══════════════════════════════════════════════════════════════════════════
    @register_strategy(
        name="Keltner Channel Breakout (4H)",
        dependencies=[],
        params={
            "ema_period": _b(20),  # ~33 bars ≈ 20 trading days — channel midline
            "atr_period": _b(10),  # ~16 bars ≈ 10 trading days — ATR for width
            "atr_mult":   2.0,     # upper band = EMA + 2 × ATR
            "sma_trend":  _b(200), # ~325 bars ≈ 200 trading days — macro gate
        },
    )
    def keltner_channel_breakout_4h(df, **kwargs):
        ema_period = kwargs["ema_period"]
        atr_period = kwargs["atr_period"]
        atr_mult   = kwargs["atr_mult"]
        sma_trend  = kwargs["sma_trend"]

        ema_mid = df["Close"].ewm(span=ema_period, adjust=False).mean()
        atr     = _calc_atr(df, atr_period)

        keltner_upper = ema_mid + atr_mult * atr

        df      = calculate_sma(df, sma_trend)
        sma_col = f"SMA_{sma_trend}"

        is_trend      = df["Close"] > df[sma_col]
        above_upper   = df["Close"] > keltner_upper
        above_mid     = df["Close"] > ema_mid

        signals = []
        in_pos  = False
        for i in range(len(df)):
            if pd.isna(ema_mid.iloc[i]) or pd.isna(atr.iloc[i]) or pd.isna(df[sma_col].iloc[i]):
                signals.append(-1)
                continue
            if not in_pos:
                if above_upper.iloc[i] and is_trend.iloc[i]:
                    in_pos = True
                    signals.append(1)
                else:
                    signals.append(-1)
            else:
                if not above_mid.iloc[i] or not is_trend.iloc[i]:
                    in_pos = False
                    signals.append(-1)
                else:
                    signals.append(1)

        df["Signal"] = signals
        df.drop(columns=[sma_col], errors="ignore", inplace=True)
        return df


    # ══════════════════════════════════════════════════════════════════════════
    # STRATEGY 3 — Donchian Turtle (4H)  [NEW — Round 4]
    #
    # Classic Turtle / Donchian breakout adapted for 4H bars. The key fix vs
    # R3's "Donchian Channel Momentum": use shift(1) so entry fires ONLY when
    # today's close exceeds the HIGHEST close of the prior N bars (not today).
    # Without shift(1), price equals the rolling max on every trending bar,
    # causing continuous entries (3065 trades in R3 — excessive churn).
    #
    # Entry : Close > max(Close over PREVIOUS 20d)   [shift(1) applied]
    #         AND price > SMA(200d)
    # Hold  : while price > SMA(200d)
    # Exit  : Close < min(Close over PREVIOUS 10d)   [shift(1) applied — trailing stop]
    #         OR  price < SMA(200d)
    #
    # The N-bar trailing low exit is structurally different from all EMA/SMA exits
    # used in R1-R51; it acts as a price-action stop rather than an average.
    # At 4H: 20 bars ≈ 12 days (entry), 10 bars ≈ 6 days (exit stop).
    # ══════════════════════════════════════════════════════════════════════════
    @register_strategy(
        name="Donchian Turtle (4H)",
        dependencies=[],
        params={
            "entry_period": _b(20),  # ~33 bars ≈ 20 trading days — breakout lookback
            "exit_period":  _b(10),  # ~16 bars ≈ 10 trading days — trailing low exit
            "sma_trend":    _b(200), # ~325 bars ≈ 200 trading days — macro gate
        },
    )
    def donchian_turtle_4h(df, **kwargs):
        entry_period = kwargs["entry_period"]
        exit_period  = kwargs["exit_period"]
        sma_trend    = kwargs["sma_trend"]

        # Entry: Close > prior N-bar high (shift(1) = look at yesterday's window only)
        prior_high = df["Close"].shift(1).rolling(
            window=entry_period, min_periods=entry_period
        ).max()
        new_high = df["Close"] > prior_high

        # Exit: Close < prior N-bar low (trailing stop — price falls below recent support)
        prior_low = df["Close"].shift(1).rolling(
            window=exit_period, min_periods=exit_period
        ).min()
        above_low = df["Close"] > prior_low

        df      = calculate_sma(df, sma_trend)
        sma_col = f"SMA_{sma_trend}"

        is_trend = df["Close"] > df[sma_col]

        signals = []
        in_pos  = False
        for i in range(len(df)):
            if pd.isna(prior_high.iloc[i]) or pd.isna(prior_low.iloc[i]) or pd.isna(df[sma_col].iloc[i]):
                signals.append(-1)
                continue
            if not in_pos:
                if new_high.iloc[i] and is_trend.iloc[i]:
                    in_pos = True
                    signals.append(1)
                else:
                    signals.append(-1)
            else:
                if not above_low.iloc[i] or not is_trend.iloc[i]:
                    in_pos = False
                    signals.append(-1)
                else:
                    signals.append(1)

        df["Signal"] = signals
        df.drop(columns=[sma_col], errors="ignore", inplace=True)
        return df


    # ══════════════════════════════════════════════════════════════════════════
    # STRATEGY 4 — Williams %R Dip-Recovery (4H)  [REJECTED — Round 6]
    # WFA Overfitted, OOS -5.60%, RollWFA Fail (1/3). Replaced in Round 7.
    # ══════════════════════════════════════════════════════════════════════════
    # STRATEGY 4 — Relative Strength Momentum (4H)  [NEW — Round 7]
    #
    # Measures each symbol's return RELATIVE TO SPY over a rolling 20-day window.
    # "Relative strength" = (symbol 20d return) − (SPY 20d return).
    # A positive value means the symbol is currently outperforming the market.
    #
    # This is fundamentally different from the existing trio:
    #   - EMA Velocity: absolute price momentum (fast EMA vs slow EMA)
    #   - Keltner: absolute volatility breakout (price vs ATR-based channel)
    #   - Donchian: absolute new-high breakout (price vs N-bar historical max)
    #   - Relative Strength: RELATIVE performance vs market benchmark
    #
    # At 4H, the 20-day window = 33 4H bars. The relative signal updates every
    # 4 hours instead of daily, making it more responsive to short-term leadership
    # rotations — institutional flows into outperforming names are visible at 4H
    # before they show up in daily data.
    #
    # Daily/weekly Relative Momentum was tested in R42 (NDX Tech 44 portfolio)
    # but at daily bars. At 4H the update frequency changes the signal character:
    # a stock can "turn on" relative outperformance intraday on earnings, news,
    # or sector rotation — impossible to detect at daily resolution.
    #
    # Entry : symbol 20d return > SPY 20d return + 1% threshold
    #         AND symbol 10d return > 0 (also trending up in absolute terms)
    #         AND price > SMA(200d)
    # Hold  : while symbol return > SPY return (positive relative strength)
    #         AND price > SMA(200d)
    # Exit  : relative strength turns negative (symbol underperforms SPY)
    #         OR price < SMA(200d)
    # ══════════════════════════════════════════════════════════════════════════
    @register_strategy(
        name="Relative Strength Momentum (4H)",
        dependencies=["spy"],
        params={
            "rs_period":    _b(20),   # ~33 bars ≈ 20 trading days — relative comparison
            "abs_period":   _b(10),   # ~16 bars ≈ 10 trading days — absolute momentum gate
            "rs_threshold": 0.01,     # symbol must outperform SPY by ≥ 1% to enter
            "sma_trend":    _b(200),  # ~325 bars ≈ 200 trading days — macro gate
        },
    )
    def relative_strength_momentum_4h(df, **kwargs):
        spy_df      = kwargs["spy_df"]
        rs_period   = kwargs["rs_period"]
        abs_period  = kwargs["abs_period"]
        rs_threshold = kwargs["rs_threshold"]
        sma_trend   = kwargs["sma_trend"]

        # Symbol returns
        symbol_ret = df["Close"].pct_change(rs_period)
        abs_ret    = df["Close"].pct_change(abs_period)

        # SPY aligned to symbol's index via forward-fill
        spy_close = spy_df["Close"].reindex(df.index, method="ffill")
        spy_ret   = spy_close.pct_change(rs_period)

        # Relative strength: symbol outperformance vs SPY
        rs = symbol_ret - spy_ret  # positive = outperforming market

        df      = calculate_sma(df, sma_trend)
        sma_col = f"SMA_{sma_trend}"

        is_trend    = df["Close"] > df[sma_col]
        outperform  = rs >= rs_threshold   # symbol beats SPY by threshold
        abs_pos     = abs_ret > 0          # absolute positive momentum gate
        rs_positive = rs > 0              # hold condition (weaker than entry)

        signals = []
        in_pos  = False
        for i in range(len(df)):
            if pd.isna(rs.iloc[i]) or pd.isna(abs_ret.iloc[i]) or pd.isna(df[sma_col].iloc[i]):
                signals.append(-1)
                continue
            if not in_pos:
                if outperform.iloc[i] and abs_pos.iloc[i] and is_trend.iloc[i]:
                    in_pos = True
                    signals.append(1)
                else:
                    signals.append(-1)
            else:
                if not rs_positive.iloc[i] or not is_trend.iloc[i]:
                    in_pos = False
                    signals.append(-1)
                else:
                    signals.append(1)

        df["Signal"] = signals
        df.drop(columns=[sma_col], errors="ignore", inplace=True)
        return df
