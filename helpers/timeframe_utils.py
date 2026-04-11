# helpers/timeframe_utils.py

def get_bars_for_period(period_str: str, timeframe: str, multiplier: int = 1) -> int:
    """
    Translates a time period string (e.g., '200d', '50h') into the number of bars
    required for a given chart timeframe ('D', 'H', 'MIN').

    This is essential for making strategies timeframe-independent.

    Args:
        period_str (str): The desired, human-readable time period (e.g., '200d', '14d').
        timeframe (str): The chart timeframe from your config ('D', 'H', 'MIN').
        multiplier (int): The number of units in the timeframe (e.g., 5 for 5-minute bars).

    Returns:
        int: The calculated number of bars for the indicator.
    
    Raises:
        ValueError: If units are incompatible or the timeframe is unsupported.
    """
    # Standard NYSE/NASDAQ trading day has 6.5 hours (9:30 AM - 4:00 PM ET).
    HOURS_PER_DAY = 6.5 
    MINUTES_PER_HOUR = 60

    # Calculate the number of bars per day based on the multiplier
    if timeframe == 'MIN' and multiplier > 0:
        BARS_PER_DAY = int((HOURS_PER_DAY * MINUTES_PER_HOUR) / multiplier)
    else:
        BARS_PER_DAY = 1 # Default for Daily timeframe

    try:
        # Parse the period string (e.g., '200d' -> 200, 'd')
        value = int("".join(filter(str.isdigit, period_str)))
        unit = "".join(filter(str.isalpha, period_str)).lower()
    except (ValueError, TypeError):
        raise ValueError(f"Invalid period_str format: '{period_str}'. Expected format like '200d', '14d'.")

    if timeframe == 'D':
        if unit == 'd':
            return value
        else:
            # It doesn't make sense to ask for hourly bars on a daily chart.
            raise ValueError(f"Cannot use period unit '{unit}' with Daily ('D') timeframe. Use 'd'.")

    elif timeframe == 'H':
        if unit == 'd':
            # To get a 200-day equivalent MA on an hourly chart, we need 200 * 6.5 bars.
            return int(value * HOURS_PER_DAY)
        elif unit == 'h':
            return value
        else:
            raise ValueError(f"Cannot use period unit '{unit}' with Hourly ('H') timeframe. Use 'd' or 'h'.")

    elif timeframe == 'W':
        if unit == 'd':
            # 5 trading days per week
            return max(1, int(value / 5))
        else:
            raise ValueError(f"Cannot use period unit '{unit}' with Weekly ('W') timeframe. Use 'd'.")

    elif timeframe == 'M':
        if unit == 'd':
            # ~21 trading days per month
            return max(1, int(value / 21))
        else:
            raise ValueError(f"Cannot use period unit '{unit}' with Monthly ('M') timeframe. Use 'd'.")

    elif timeframe == 'MIN':
        if unit == 'd':
            # --- CHANGE THIS LINE ---
            return int(value * BARS_PER_DAY)
        elif unit == 'h':
            # --- CHANGE THIS LINE ---
            return int(value * (MINUTES_PER_HOUR / multiplier))
        elif unit == 'min':
            # --- CHANGE THIS LINE ---
            return int(value / multiplier)
        else:
            raise ValueError(f"Cannot use period unit '{unit}' with Minute ('MIN') timeframe. Use 'd', 'h', or 'min'.")

    else:
        raise ValueError(f"Unsupported timeframe in config: {timeframe}")


def get_bars_per_year(config: dict) -> int:
    """
    Calculate the number of trading bars per year based on timeframe config.

    This is critical for correct annualization of metrics (Sharpe ratio, Sortino
    ratio, Alpha, Beta) when backtesting on intraday timeframes.

    Args:
        config (dict): The CONFIG dictionary containing 'timeframe' and
                       optionally 'timeframe_multiplier'.

    Returns:
        int: Number of trading bars per year for the given timeframe.

    Examples:
        >>> get_bars_per_year({"timeframe": "D"})
        252
        >>> get_bars_per_year({"timeframe": "H", "timeframe_multiplier": 1})
        1638
        >>> get_bars_per_year({"timeframe": "MIN", "timeframe_multiplier": 5})
        19656
        >>> get_bars_per_year({"timeframe": "W"})
        52
        >>> get_bars_per_year({"timeframe": "M"})
        12

    Notes:
        - Assumes 252 trading days per year (NYSE/NASDAQ standard)
        - Assumes 6.5 trading hours per day (9:30 AM - 4:00 PM ET)
        - For minute bars: bars_per_year = 252 * 6.5 * 60 / multiplier
        - For hourly bars: bars_per_year = 252 * 6.5 / multiplier

    Raises:
        ValueError: If timeframe is not supported.
    """
    TRADING_DAYS_PER_YEAR = 252
    HOURS_PER_DAY = 6.5  # NYSE/NASDAQ standard (9:30 AM - 4:00 PM ET)
    MINUTES_PER_HOUR = 60

    timeframe = config.get("timeframe", "D").upper()
    multiplier = int(config.get("timeframe_multiplier", 1))

    if multiplier <= 0:
        raise ValueError(f"timeframe_multiplier must be > 0, got {multiplier}")

    if timeframe == "D":
        return TRADING_DAYS_PER_YEAR
    elif timeframe == "H":
        bars_per_day = HOURS_PER_DAY / multiplier
        return int(TRADING_DAYS_PER_YEAR * bars_per_day)
    elif timeframe == "MIN":
        bars_per_day = (HOURS_PER_DAY * MINUTES_PER_HOUR) / multiplier
        return int(TRADING_DAYS_PER_YEAR * bars_per_day)
    elif timeframe == "W":
        return 52  # ~52 weeks per year
    elif timeframe == "M":
        return 12  # 12 months per year
    else:
        raise ValueError(
            f"Unsupported timeframe '{timeframe}'. "
            f"Must be one of: D, H, MIN, W, M"
        )