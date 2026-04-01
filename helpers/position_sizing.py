"""helpers/position_sizing.py

Position sizing algorithms for portfolio risk management.

Supports 4 methods:
1. Fixed % allocation (current default)
2. Kelly Criterion (optimal growth)
3. Volatility parity (inverse ATR)
4. Risk parity (equal $ risk per position)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)


def calculate_position_size(
    method: str,
    equity: float,
    price: float,
    symbol_data: pd.DataFrame,
    config: dict,
    **kwargs
) -> float:
    """
    Calculate position size (number of shares) based on selected method.

    Parameters
    ----------
    method : str
        Position sizing method: "fixed", "kelly", "vol_parity", "risk_parity"
    equity : float
        Current total portfolio equity
    price : float
        Entry price for this trade
    symbol_data : pd.DataFrame
        Recent OHLCV data for the symbol (must include ATR_14 for vol/risk parity)
    config : dict
        CONFIG dict with position sizing parameters
    **kwargs : dict
        Method-specific parameters:
        - Kelly: win_rate, avg_win, avg_loss
        - Risk parity: stop_distance_pct

    Returns
    -------
    shares : float
        Number of shares to buy (can be fractional)

    Examples
    --------
    >>> # Fixed 10% allocation
    >>> shares = calculate_position_size("fixed", 100000, 50.0, df, config)

    >>> # Kelly Criterion
    >>> shares = calculate_position_size(
    ...     "kelly", 100000, 50.0, df, config,
    ...     win_rate=0.55, avg_win=0.10, avg_loss=0.05
    ... )
    """
    if method == "fixed":
        return _fixed_allocation(equity, price, config)

    elif method == "kelly":
        return _kelly_criterion(equity, price, config, **kwargs)

    elif method == "vol_parity":
        return _volatility_parity(equity, price, symbol_data, config)

    elif method == "risk_parity":
        return _risk_parity(equity, price, symbol_data, config, **kwargs)

    else:
        logger.warning(
            f"Unknown position sizing method '{method}'. Falling back to 'fixed'."
        )
        return _fixed_allocation(equity, price, config)


def _fixed_allocation(equity: float, price: float, config: dict) -> float:
    """
    Fixed percentage allocation (current default behavior).

    allocation_per_trade = 10% → 10% of equity allocated to each trade
    """
    allocation_pct = config.get("allocation_per_trade", 0.10)
    capital_to_allocate = equity * allocation_pct
    shares = capital_to_allocate / price if price > 0 else 0.0
    return shares


def _kelly_criterion(equity: float, price: float, config: dict, **kwargs) -> float:
    """
    Kelly Criterion position sizing for optimal growth.

    Kelly fraction: f = (p * b - q) / b
    where:
    - p = win rate
    - q = loss rate (1 - p)
    - b = avg_win / avg_loss

    We use a fractional Kelly to be conservative (default 25% of full Kelly).
    """
    # Extract historical stats from kwargs
    win_rate = kwargs.get("win_rate")
    avg_win = kwargs.get("avg_win")
    avg_loss = kwargs.get("avg_loss")

    # Validation
    if win_rate is None or avg_win is None or avg_loss is None:
        logger.warning(
            "Kelly sizing requires win_rate, avg_win, avg_loss. Falling back to fixed."
        )
        return _fixed_allocation(equity, price, config)

    if not (0 < win_rate < 1):
        logger.warning(f"Invalid win_rate {win_rate}. Falling back to fixed.")
        return _fixed_allocation(equity, price, config)

    if avg_win <= 0 or avg_loss <= 0:
        logger.warning(f"Invalid avg_win/avg_loss ({avg_win}/{avg_loss}). Falling back to fixed.")
        return _fixed_allocation(equity, price, config)

    # Calculate Kelly fraction
    b = avg_win / avg_loss
    p = win_rate
    q = 1.0 - p

    kelly_f = (p * b - q) / b

    # Kelly can be negative (strategy has negative edge) or > 1 (very high edge)
    # Clamp to [0, 1] for safety
    kelly_f = max(0.0, min(1.0, kelly_f))

    # Apply fractional Kelly (default 25% for safety)
    kelly_fraction = config.get("kelly_fraction", 0.25)
    f = kelly_f * kelly_fraction

    capital_to_allocate = equity * f
    shares = capital_to_allocate / price if price > 0 else 0.0

    return shares


def _volatility_parity(equity: float, price: float, symbol_data: pd.DataFrame, config: dict) -> float:
    """
    Volatility parity sizing: allocate inversely proportional to volatility.

    Lower volatility symbols get larger positions, higher volatility get smaller.
    Target risk per trade is controlled by config.

    Uses ATR as a proxy for volatility.
    """
    if "ATR_14" not in symbol_data.columns or len(symbol_data) == 0:
        logger.warning("ATR_14 not available for vol parity sizing. Falling back to fixed.")
        return _fixed_allocation(equity, price, config)

    atr = symbol_data["ATR_14"].iloc[-1]

    if pd.isna(atr) or atr <= 0:
        logger.warning("Invalid ATR value for vol parity sizing. Falling back to fixed.")
        return _fixed_allocation(equity, price, config)

    atr_pct = atr / price if price > 0 else 0.0

    if atr_pct <= 0:
        return _fixed_allocation(equity, price, config)

    # target_risk_per_trade = 2% means we want to risk 2% of equity on this trade
    # shares = (equity * target_risk) / (price * atr_pct)
    target_risk = config.get("target_risk_per_trade", 0.02)
    shares = (equity * target_risk) / (price * atr_pct) if atr_pct > 0 else 0.0

    return shares


def _risk_parity(equity: float, price: float, symbol_data: pd.DataFrame, config: dict, **kwargs) -> float:
    """
    Risk parity sizing: equal $ risk per position.

    Requires a stop loss distance. Position size is calculated so that
    hitting the stop would lose `target_risk_per_trade` of equity.

    shares = (equity * target_risk) / (price * stop_distance_pct)
    """
    stop_distance_pct = kwargs.get("stop_distance_pct")

    if stop_distance_pct is None or stop_distance_pct <= 0:
        # Fallback: use ATR-based stop if available
        if "ATR_14" in symbol_data.columns and len(symbol_data) > 0:
            atr = symbol_data["ATR_14"].iloc[-1]
            if pd.notna(atr) and atr > 0:
                # Default: 3x ATR stop
                stop_distance_pct = (atr * 3.0) / price
            else:
                logger.warning("No valid stop distance for risk parity sizing. Falling back to fixed.")
                return _fixed_allocation(equity, price, config)
        else:
            logger.warning("No stop distance or ATR for risk parity sizing. Falling back to fixed.")
            return _fixed_allocation(equity, price, config)

    target_risk = config.get("target_risk_per_trade", 0.02)
    shares = (equity * target_risk) / (price * stop_distance_pct) if stop_distance_pct > 0 else 0.0

    return shares


def check_portfolio_heat(positions: dict, new_position_risk: float, equity: float, max_heat: float) -> bool:
    """
    Check if adding a new position would exceed maximum portfolio heat.

    Portfolio heat = total $ risk across all open positions / equity

    Parameters
    ----------
    positions : dict
        Currently open positions (from portfolio_simulations.py)
    new_position_risk : float
        $ risk for the new position being considered
    equity : float
        Current total portfolio equity
    max_heat : float
        Maximum allowed portfolio heat (e.g., 0.10 = 10%)

    Returns
    -------
    bool
        True if adding the position is allowed, False if it would exceed max_heat

    Examples
    --------
    >>> positions = {"AAPL": {"risk": 500}, "MSFT": {"risk": 300}}
    >>> check_portfolio_heat(positions, 400, 100000, 0.02)  # 2% max heat
    False  # (500 + 300 + 400) / 100000 = 0.012 > 0.02? No, allowed
    """
    # Sum current risk across all positions
    current_risk = sum(pos.get("risk", 0.0) for pos in positions.values())

    total_risk = current_risk + new_position_risk

    heat = total_risk / equity if equity > 0 else 0.0

    if heat > max_heat:
        logger.debug(
            f"Portfolio heat check: {heat:.2%} > {max_heat:.2%}. Trade rejected."
        )
        return False

    return True
