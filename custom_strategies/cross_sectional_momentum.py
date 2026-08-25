# custom_strategies/cross_sectional_momentum.py
"""
Reference cross-sectional strategy — hold the top-N names by trailing momentum.

This is the worked example for ``@register_portfolio_strategy``. It is
deliberately simple: the point is to demonstrate the contract, not to propose an
edge. (Measured against equal-weight buy-and-hold of the same universe, plain
top-N momentum rotation is not obviously profitable — treat this as
infrastructure, and benchmark any variant against holding the universe.)

Why it cannot be a normal ``@register_strategy``
------------------------------------------------
Ranking requires comparing symbols against each other. A per-symbol strategy
receives one DataFrame at a time and can never see the rest of the universe, so
"top 5 of 100" is inexpressible there. This decorator hands the function the
whole ``{symbol: df}`` mapping instead, and the signals it returns run through
the same execution engine as everything else.

No look-ahead
-------------
Momentum is ``pct_change(lookback)`` — a trailing return using only bars at or
before ``t``. Ranking is applied cross-sectionally within each row, so bar ``t``
is ranked against other symbols' bar ``t`` only. Nothing reads ``t+1``.
"""

import numpy as np
import pandas as pd

from helpers.registry import register_portfolio_strategy
from helpers.timeframe_utils import get_bars_for_period
from config import CONFIG

_TF = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


@register_portfolio_strategy(
    name="Cross-Sectional Momentum (Top 5, 60d)",
    dependencies=[],
    params={
        "lookback": get_bars_for_period("60d", _TF, _MUL),
        "top_n": 5,
        # Hysteresis: keep a held name until it falls out of the top `exit_rank`.
        # Without a buffer the book churns every time two names swap places.
        "exit_rank": 15,
        # Only hold names trading above their own long-term average.
        "trend_ma": get_bars_for_period("200d", _TF, _MUL),
    },
)
def cross_sectional_momentum(portfolio_data, **kwargs):
    """Hold the top-N names by trailing return; drop them past ``exit_rank``.

    Parameters
    ----------
    portfolio_data : dict[str, pd.DataFrame]
        Every symbol in the portfolio, keyed by ticker.

    Returns
    -------
    dict[str, pd.Series]
        Symbol -> Signal series (1 = hold long, -1 = flat).
    """
    lookback = kwargs["lookback"]
    top_n = kwargs["top_n"]
    exit_rank = kwargs["exit_rank"]
    trend_ma = kwargs["trend_ma"]

    symbols = list(portfolio_data.keys())
    if not symbols:
        return {}

    # Shared calendar across the universe. Symbols that did not trade on a given
    # date are NaN and rank last, so they cannot be selected.
    closes = pd.DataFrame(
        {s: portfolio_data[s]["Close"] for s in symbols}
    ).sort_index()

    momentum = closes.pct_change(lookback)
    above_ma = closes > closes.rolling(trend_ma, min_periods=trend_ma).mean()
    momentum = momentum.where(above_ma)

    # rank(axis=1) compares symbols against each other on the SAME bar — this is
    # the operation a per-symbol strategy cannot perform.
    ranks = momentum.rank(axis=1, ascending=False, na_option="bottom")

    enter = ranks.le(top_n) & momentum.notna()
    hold = ranks.le(exit_rank) & momentum.notna()

    # Hysteresis: once in, stay in while still inside `exit_rank`. Resolved with
    # a forward-fill over the ambiguous middle band rather than a Python loop, so
    # it stays vectorised.
    #   enter -> 1, not-hold -> -1, in-between -> carry previous
    state = pd.DataFrame(np.nan, index=closes.index, columns=closes.columns)
    state = state.mask(enter, 1.0)
    state = state.mask(~hold, -1.0)
    state = state.ffill().fillna(-1.0)

    return {
        s: state[s].reindex(portfolio_data[s].index).fillna(-1.0).astype(int)
        for s in symbols
    }
