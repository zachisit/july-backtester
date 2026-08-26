"""custom_strategies/momentum_rotation_example.py

Public, generic **rotation** example (issue #294) — demonstrates the
cross-sectional ranking plugin kind. Contains NO proprietary alpha: it is plain
N-day price-return momentum, the textbook baseline.

A rotation plugin is a *ranking* function, registered with @register_rotation.
It receives the whole universe at a rebalance date and returns a ranking; the
framework (helpers/rotation.py) does everything else — top-N selection,
equal-weight sizing, rebalance/trim/add, and all cost/accounting.

Because it registers with kind="rotation", it is invisible to the legacy
per-symbol pipeline (get_active_strategies) and only runs when driven through
helpers.rotation.run_rotation / the rotation config. Existing runs are unaffected.
"""

from __future__ import annotations

from helpers.registry import register_rotation
from helpers.timeframe_utils import get_bars_for_period
from config import CONFIG

_TF = CONFIG.get("timeframe", "D")
_MUL = CONFIG.get("timeframe_multiplier", 1)


@register_rotation(
    name="Momentum Rotation (Example)",
    params={"lookback": get_bars_for_period("90d", _TF, _MUL)},
)
def momentum_rotation_example(data, rebalance_date, lookback=90, **kwargs):
    """Rank the universe by trailing ``lookback``-bar total price return.

    Parameters
    ----------
    data : dict[str, pd.DataFrame]
        Per-symbol OHLCV frames.
    rebalance_date : pd.Timestamp
        The bar at which selection is decided.
    lookback : int
        Number of bars in the momentum lookback window.

    Returns
    -------
    dict[str, float]
        ``{symbol: momentum_score}`` — higher is stronger. Symbols without enough
        history at ``rebalance_date`` are omitted (never selected).
    """
    scores: dict[str, float] = {}
    for sym, df in data.items():
        if df is None or df.empty:
            continue
        window = df.loc[:rebalance_date]
        if len(window) <= lookback:
            continue
        closes = window["Close"]
        past = closes.iloc[-lookback - 1]
        now = closes.iloc[-1]
        if past and past > 0:
            scores[sym] = float(now / past - 1.0)
    return scores
