"""VIX eVRP / VIX3M dual signal, fully funded with SGOV (issue #487).

Adaptation of Zarattini, Mele & Aziz, "The Volatility Edge: A Dual Approach
For VIX ETNs Trading" (2025) to actual ETFs, a cash account and next-open
execution. Locked conventions (private-strategies PR #179):

* ``eVRP = VIX - 100 * sqrt(252) * sample_std(last 10 simple SPY daily returns)``,
  using the prior completed session only (the engine executes at the next open).

  ============================  ==========================
  Condition (prior close)       Target
  ============================  ==========================
  eVRP > 0  and VIX < VIX3M     40% SVXY / 60% SGOV
  eVRP <= 0 and VIX < VIX3M     20% SVXY / 80% SGOV
  eVRP <= 0 and VIX > VIX3M     20% VIXY / 80% SGOV
  otherwise (incl. VIX = VIX3M) 100% SGOV
  ============================  ==========================

* The signed underlying-index exposure is VIXY ``+1`` and SVXY ``-0.5`` per
  unit of value (SVXY's -0.5x daily objective), so 40% SVXY is -20% index
  exposure. Rebalance band: 2 percentage points of that signed exposure.
* Costs: 5 bps per traded notional on VIXY/SVXY, 1 bp on SGOV.
* No stops, no margin, no share shorting; purchases use settled cash.

This is a research configuration, not a recommendation; see
``docs/TARGET_WEIGHT_PORTFOLIOS.md`` for the reproduction and its limitations.
"""

import numpy as np
import pandas as pd

from helpers.registry import register_target_weight

#: Signal-state labels written to the report's signal diagnostics.
STATE_STRONG_INVERSE = "strong_inverse"   # 40% SVXY
STATE_WEAK_INVERSE = "weak_inverse"       # 20% SVXY
STATE_LONG_VOL = "long_vol"               # 20% VIXY
STATE_CASH = "cash"                       # 100% SGOV


def evrp_dual_signal(spy_close: pd.Series, vix: pd.Series, vix3m: pd.Series,
                     window: int = 10, size: float = 0.2) -> pd.DataFrame:
    """Signed VIXY-equivalent target per session close, with its inputs.

    ``target`` is the signed index exposure: ``-size`` (strong inverse),
    ``-size/2`` (weak inverse), ``+size`` (long vol) or ``0``. All inputs are
    aligned to *spy_close*'s sessions without forward-filling; a session with
    a missing or non-positive VIX/VIX3M, or without ``window`` returns, is cash.
    """
    vix = vix.reindex(spy_close.index)
    vix3m = vix3m.reindex(spy_close.index)
    rv = spy_close.pct_change(fill_method=None).rolling(window).std(ddof=1) * np.sqrt(252) * 100
    premium = vix - rv
    valid = rv.notna() & vix.gt(0) & vix3m.gt(0)
    calm = vix.lt(vix3m)
    strong = valid & calm & premium.gt(0)
    weak = valid & calm & premium.le(0)
    long_vol = valid & ~calm & vix.gt(vix3m) & premium.le(0)
    target = pd.Series(0.0, index=spy_close.index)
    target.loc[strong] = -size
    target.loc[weak] = -size / 2
    target.loc[long_vol] = size
    state = pd.Series(STATE_CASH, index=spy_close.index)
    state.loc[strong] = STATE_STRONG_INVERSE
    state.loc[weak] = STATE_WEAK_INVERSE
    state.loc[long_vol] = STATE_LONG_VOL
    return pd.DataFrame({"target_exposure": target, "state": state, "evrp": premium,
                         "spy_realized_vol": rv, "vix": vix, "vix3m": vix3m})


def basket_from_exposure(target: pd.Series) -> pd.DataFrame:
    """VIXY/SVXY weights for a signed index-exposure target (SVXY = -0.5x)."""
    return pd.DataFrame({"VIXY": target.clip(lower=0), "SVXY": (-2 * target).clip(lower=0)},
                        index=target.index)


@register_target_weight(
    name="VIX eVRP Dual (SGOV funded)",
    symbols=["VIXY", "SVXY"],
    cash_symbol="SGOV",
    signal_symbols={"spy": "SPY", "vix": "I:VIX", "vix3m": "I:VIX3M"},
    exposure={"VIXY": 1.0, "SVXY": -0.5, "SGOV": 0.0},
    cost_bps={"VIXY": 5.0, "SVXY": 5.0, "SGOV": 1.0},
    band=0.02,
    params={"window": 10, "size": 0.2},
    portfolio_name="VIXY-SVXY-SGOV",
    report_periods={"2022 onward": ("2022-01-01", None),
                    "T+1 era": ("2024-05-28", None),
                    "Post publication": ("2025-06-24", None)},
    description=("eVRP (VIX minus 10-day SPY realized vol) x VIX/VIX3M term structure; "
                 "inverse via SVXY, long vol via VIXY, idle cash in SGOV."),
)
def vix_evrp_dual_sgov(data, window=10, size=0.2, **kwargs):
    signal = evrp_dual_signal(data["spy"]["Close"], data["vix"]["Close"],
                              data["vix3m"]["Close"], window=window, size=size)
    return pd.concat([basket_from_exposure(signal["target_exposure"]), signal], axis=1)
