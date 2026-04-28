"""helpers/survivorship.py

Survivorship bias handling for backtests. Provides functions to:
1. Fetch delisting dates from data providers
2. Force-close positions when stocks are delisted

This prevents overly optimistic results from testing only on stocks that survived.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)


def get_delisting_dates(symbols: list[str], data_provider: str, config: dict) -> dict[str, str]:
    """
    Return dict of {symbol: delisting_date} for all delisted symbols.

    Only data providers that support delisting data will return values.
    Yahoo and CSV providers log a warning and return empty dict.

    Parameters
    ----------
    symbols : list[str]
        List of all symbols (active and delisted) to check
    data_provider : str
        Name of the data provider ("norgate", "polygon", "yahoo", "csv")
    config : dict
        Full CONFIG dict (may contain provider-specific keys)

    Returns
    -------
    dict[str, str]
        {"SYMBOL": "YYYY-MM-DD", ...} for delisted symbols only.
        Active symbols are not included in the dict.
        Empty dict if provider doesn't support delisting data.

    Examples
    --------
    >>> delisting_dates = get_delisting_dates(["AAPL", "ENRON"], "polygon", CONFIG)
    >>> delisting_dates
    {"ENRON": "2001-11-28"}
    """
    if data_provider == "norgate":
        return _get_delisting_dates_norgate(symbols, config)
    elif data_provider == "polygon":
        return _get_delisting_dates_polygon(symbols, config)
    elif data_provider in ("yahoo", "csv"):
        logger.warning(
            f"[WARNING] Data provider '{data_provider}' does not support delisting "
            "data. Survivorship bias handling is disabled. Consider using Norgate "
            "or Polygon for production backtests."
        )
        return {}
    else:
        logger.warning(
            f"[WARNING] Unknown data provider '{data_provider}'. Cannot fetch "
            "delisting dates. Survivorship bias handling is disabled."
        )
        return {}


def _get_delisting_dates_norgate(symbols: list[str], config: dict) -> dict[str, str]:
    """
    Fetch delisting dates from Norgate Data.

    Norgate provides delisting information via `norgatedata.delistingdate(symbol)`.

    Returns
    -------
    dict[str, str]
        {symbol: "YYYY-MM-DD"} for delisted symbols only
    """
    try:
        import norgatedata
    except ImportError:
        logger.warning(
            "[WARNING] norgatedata library not installed. Cannot fetch delisting "
            "dates. Install with: pip install norgatedata"
        )
        return {}

    delisting_dates = {}
    for symbol in symbols:
        try:
            delisting_dt = norgatedata.delistingdate(symbol)
            if delisting_dt is not None:
                # Convert to ISO date string
                delisting_dates[symbol] = delisting_dt.strftime("%Y-%m-%d")
        except Exception as exc:
            # Symbol lookup failed or API error - skip silently
            logger.debug(f"Failed to fetch delisting date for {symbol}: {exc}")
            continue

    return delisting_dates


def _get_delisting_dates_polygon(symbols: list[str], config: dict) -> dict[str, str]:
    """
    Fetch delisting dates from Polygon.io.

    Polygon provides delisting information via the /v3/reference/tickers endpoint
    with `active=false` parameter.

    Returns
    -------
    dict[str, str]
        {symbol: "YYYY-MM-DD"} for delisted symbols only
    """
    from helpers.aws_utils import get_secret

    api_key = get_secret(config.get("polygon_api_secret_name", "POLYGON_API_KEY"))
    if not api_key:
        logger.warning(
            "[WARNING] POLYGON_API_KEY not set. Cannot fetch delisting dates."
        )
        return {}

    # Polygon API returns delisting dates in the ticker details endpoint
    # /v3/reference/tickers/{ticker}?date={date}
    # The `delisted_utc` field contains the delisting timestamp

    import requests

    delisting_dates = {}
    base_url = "https://api.polygon.io/v3/reference/tickers"

    for symbol in symbols:
        try:
            url = f"{base_url}/{symbol}"
            params = {"apiKey": api_key}
            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()
                results = data.get("results", {})
                delisted_utc = results.get("delisted_utc")

                if delisted_utc:
                    # Parse ISO timestamp and extract date
                    delisting_dt = pd.Timestamp(delisted_utc)
                    delisting_dates[symbol] = delisting_dt.strftime("%Y-%m-%d")

            elif response.status_code == 429:
                # Rate limit hit - log and stop querying
                logger.warning(
                    f"[WARNING] Polygon API rate limit hit while fetching delisting "
                    f"dates. Only {len(delisting_dates)} of {len(symbols)} symbols checked."
                )
                break

        except Exception as exc:
            logger.debug(f"Failed to fetch delisting date for {symbol}: {exc}")
            continue

    return delisting_dates


def adjust_for_survivorship(
    trade_log: list[dict],
    delisting_dates: dict[str, str],
    initial_capital: float,
    delisting_price_assumption: str = "last_close",
) -> tuple[list[dict], dict[str, Any]]:
    """
    Force-close open positions when stocks are delisted.

    Iterates through trade log. If a position is still open (no ExitDate) and
    the symbol has a delisting date, the position is force-closed on the
    delisting date with an assumed exit price.

    Parameters
    ----------
    trade_log : list[dict]
        Original trade log from simulation. May contain open positions.
    delisting_dates : dict[str, str]
        {symbol: "YYYY-MM-DD"} mapping from `get_delisting_dates()`
    initial_capital : float
        Used to compute delisting loss as % of initial capital
    delisting_price_assumption : str
        How to determine exit price when delisted:
        - "last_close": use last known Close price from trade (default)
        - "zero": assume total loss (price = 0)

    Returns
    -------
    adjusted_trade_log : list[dict]
        Trade log with delisting exits added. Open positions are closed.
    survivorship_stats : dict
        {
            "positions_delisted": int,
            "total_delisting_loss": float,
            "delisting_loss_pct": float,  # vs initial capital
        }

    Examples
    --------
    >>> trade_log = [
    ...     {"Symbol": "ENRON", "EntryDate": "2001-01-01", "ExitDate": None, ...},
    ... ]
    >>> delisting_dates = {"ENRON": "2001-11-28"}
    >>> adjusted_log, stats = adjust_for_survivorship(trade_log, delisting_dates, 100000)
    >>> stats["positions_delisted"]
    1
    """
    adjusted_log = []
    positions_delisted = 0
    total_delisting_loss = 0.0

    for trade in trade_log:
        symbol = trade.get("Symbol")
        exit_date = trade.get("ExitDate")

        # Position already closed - pass through unchanged
        if exit_date is not None and pd.notna(exit_date):
            adjusted_log.append(trade)
            continue

        # Position is open - check if delisted
        if symbol in delisting_dates:
            delisting_date_str = delisting_dates[symbol]
            entry_date = pd.Timestamp(trade["EntryDate"])
            delisting_date = pd.Timestamp(delisting_date_str)

            # Only force-close if delisting happened after entry
            if delisting_date >= entry_date:
                # Determine exit price
                if delisting_price_assumption == "zero":
                    exit_price = 0.0
                else:  # "last_close"
                    exit_price = trade.get("EntryPrice", 0.0)  # Fallback to entry price

                # Compute loss
                shares = trade.get("Shares", 0)
                entry_price = trade.get("EntryPrice", 0.0)
                profit = shares * (exit_price - entry_price)

                # Create delisting exit trade
                delisted_trade = trade.copy()
                delisted_trade["ExitDate"] = delisting_date_str
                delisted_trade["ExitPrice"] = exit_price
                delisted_trade["Profit"] = profit
                delisted_trade["ProfitPct"] = (
                    (exit_price - entry_price) / entry_price if entry_price > 0 else -1.0
                )
                delisted_trade["ExitReason"] = "Delisting"

                adjusted_log.append(delisted_trade)
                positions_delisted += 1
                total_delisting_loss += profit
                continue

        # Open position, not delisted - pass through unchanged
        adjusted_log.append(trade)

    survivorship_stats = {
        "positions_delisted": positions_delisted,
        "total_delisting_loss": total_delisting_loss,
        "delisting_loss_pct": (
            total_delisting_loss / initial_capital if initial_capital > 0 else 0.0
        ),
    }

    return adjusted_log, survivorship_stats
