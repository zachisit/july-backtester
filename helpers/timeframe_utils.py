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
            
    elif timeframe == 'W':
        TRADING_DAYS_PER_WEEK = 5
        if unit == 'd':
            return max(1, round(value / TRADING_DAYS_PER_WEEK))
        elif unit == 'w':
            return value
        else:
            raise ValueError(f"Cannot use period unit '{unit}' with Weekly ('W') timeframe. Use 'd' or 'w'.")

    elif timeframe == 'M':
        TRADING_DAYS_PER_MONTH = 21
        if unit == 'd':
            return max(1, round(value / TRADING_DAYS_PER_MONTH))
        elif unit == 'm':
            return value
        else:
            raise ValueError(f"Cannot use period unit '{unit}' with Monthly ('M') timeframe. Use 'd' or 'm'.")

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
        - Assumes 6.5 trading hours per day (9:30 AM - 4:00 PM ET) unless
          overridden via config["trading_hours_per_day"] — e.g. round-the-clock
          futures (CME Globex ~23h/day) trade far more bars/year on an intraday
          timeframe than an RTH-only equity, so the default understates their
          true annualization factor.
        - For minute bars: bars_per_year = 252 * trading_hours_per_day * 60 / multiplier
        - For hourly bars: bars_per_year = 252 * trading_hours_per_day / multiplier

    Raises:
        ValueError: If timeframe is not supported.
    """
    TRADING_DAYS_PER_YEAR = 252
    HOURS_PER_DAY = float(config.get("trading_hours_per_day", 6.5))  # override for 24h instruments
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


def get_bars_per_day_exact(config: dict, session_hours: float | None = None) -> float:
    """
    Bars in a single trading day as an EXACT (unrounded) float.

    Identical branch logic to get_bars_per_day(), without the int()
    truncation. Use this wherever the value is a *scaling factor* rather
    than a bar count -- notably the 20-day average-daily-volume calculation
    in helpers/portfolio_simulations.py (issues #264, #268).

    Why this exists (issue #268): get_bars_per_day() truncates, so for any
    multiplier that does not divide the session length evenly the fraction
    is silently lost. With the default 6.5-hour session:

        H x1 / MIN x60 -> int(6.5)   == 6     (true 6.5,   -7.7%)
        H x2           -> int(3.25)  == 3     (true 3.25,  -7.7%)
        H x4           -> int(1.625) == 1     (true 1.625, -38.5%)

    The ADV fix from #265 rests on the identity

        mean(20*bpd bars) * bpd == sum(window)/(20*bpd) * bpd == sum(window)/20

    i.e. "total volume over the window / 20 days" -- true daily ADV, but
    ONLY while the window genuinely spans 20 days. A truncated bars-per-day
    corrupts both the window width and the rescale factor, so 20-day ADV on
    hourly data was understated by 7.7% (1H/2H) to 38.5% (4H).

    Args:
        config (dict): CONFIG dict with 'timeframe', optional
                        'timeframe_multiplier', and optional
                        'trading_hours_per_day' (default 6.5).
        session_hours (float | callable | None): explicit session length,
                        overriding config['trading_hours_per_day']. Pass the
                        value from
                        helpers.instruments.resolve_session_hours(symbol,
                        config) for per-symbol correctness on a mixed book
                        (issue #270), or a zero-arg CALLABLE returning it to
                        defer that resolution -- it is then invoked only on
                        intraday timeframes, so a D/W/M run neither pays for
                        nor can fail on a session length it never reads.
                        None keeps the process-wide global.

    Returns:
        float: Bars per trading day, unrounded. May be < 1.0 when a single
                bar spans more than one session (correct: such a bar carries
                more than one day's volume, so the rescale must scale down).

    Examples:
        >>> get_bars_per_day_exact({"timeframe": "D"})
        1.0
        >>> get_bars_per_day_exact({"timeframe": "H", "timeframe_multiplier": 2})
        3.25
        >>> get_bars_per_day_exact({"timeframe": "MIN", "timeframe_multiplier": 5})
        78.0

    Raises:
        ValueError: If timeframe is not supported, timeframe_multiplier <= 0,
                    or trading_hours_per_day <= 0.
    """
    MINUTES_PER_HOUR = 60

    timeframe = config.get("timeframe", "D").upper()
    multiplier = int(config.get("timeframe_multiplier", 1))

    if multiplier <= 0:
        raise ValueError(f"timeframe_multiplier must be > 0, got {multiplier}")

    # Validate the timeframe BEFORE the session-length check below, so an
    # unsupported timeframe always reports itself as such rather than being
    # masked by an unrelated key that the branch it would have taken happens
    # to read.
    if timeframe not in ("D", "W", "M", "H", "MIN"):
        raise ValueError(
            f"Unsupported timeframe '{timeframe}'. "
            f"Must be one of: D, H, MIN, W, M"
        )

    if timeframe in ("D", "W", "M"):
        # Already one bar per period -- a daily/weekly/monthly bar's Volume
        # is a whole period's volume already, not a fraction of a day's.
        # Returns BEFORE resolving session hours: these timeframes never read
        # the session length, so they must not fail (or pay) for it. That is
        # also why `session_hours` may be a callable -- see below.
        return 1.0

    # Resolved only now, on the branches that actually consult it. Accepting a
    # zero-arg callable lets a caller defer per-symbol resolution (which can
    # itself raise) until we know an intraday timeframe needs it.
    if callable(session_hours):
        session_hours = session_hours()

    HOURS_PER_DAY = float(
        config.get("trading_hours_per_day", 6.5)
        if session_hours is None
        else session_hours
    )

    # Only the intraday branches consult the session length, so validate it
    # here rather than penalising daily runs for a key they never read. A
    # zero/negative session would otherwise yield a 0.0 rescale factor,
    # silently driving average daily volume to 0 -- which makes the
    # max_pct_adv cap reject every trade with no error (the exact class of
    # silent miscalibration #264 was about).
    if HOURS_PER_DAY <= 0:
        raise ValueError(
            f"trading_hours_per_day must be > 0, got {HOURS_PER_DAY}"
        )

    if timeframe == "H":
        return HOURS_PER_DAY / multiplier
    return (HOURS_PER_DAY * MINUTES_PER_HOUR) / multiplier


def get_bars_per_day(config: dict) -> int:
    """
    Calculate the number of bars in a single trading day for a given timeframe.

    Used to rescale a rolling *per-bar* volume average into a true average
    *daily* volume figure (see the max_pct_adv liquidity cap and
    volume_impact_coeff market-impact model in
    helpers/portfolio_simulations.py, issue #264): the mean of Volume over a
    window of N bars is the mean volume of ONE bar, not one day, whenever
    more than one bar makes up a trading day. Multiplying that per-bar mean
    by get_bars_per_day() converts it into a daily-equivalent figure.

    Deliberately independent of get_bars_for_period(), which ignores
    `timeframe_multiplier` in its H-timeframe 'd'-unit branch (a separate,
    pre-existing bug left untouched to avoid changing behavior for any
    strategy already depending on it -- tracked in #267). get_bars_per_day()
    always honours the multiplier.

    NOTE (issue #268): this returns a truncated bar COUNT and is therefore
    lossy whenever the multiplier does not divide the session evenly (4H ->
    1 rather than 1.625). For a *scaling factor* -- e.g. rescaling a per-bar
    volume mean into a daily figure -- use get_bars_per_day_exact() instead.

    Args:
        config (dict): CONFIG dict with 'timeframe', optional
                        'timeframe_multiplier', and optional
                        'trading_hours_per_day' (default 6.5).

    Returns:
        int: Number of bars per trading day. Always >= 1.

    Examples:
        >>> get_bars_per_day({"timeframe": "D"})
        1
        >>> get_bars_per_day({"timeframe": "H", "timeframe_multiplier": 2})
        3
        >>> get_bars_per_day({"timeframe": "MIN", "timeframe_multiplier": 5})
        78

    Raises:
        ValueError: If timeframe is not supported, timeframe_multiplier <= 0,
                    or (intraday timeframes only) trading_hours_per_day <= 0.
                    The last condition is inherited from
                    get_bars_per_day_exact() and is new as of #268; it
                    previously returned 1 for a zero-length session.
    """
    # Single source of truth: same branches, same validation, then clamp to
    # a usable bar count. max(1, ...) keeps a sub-daily-resolution config
    # (one bar spanning several sessions) from returning a 0-bar count.
    return max(1, int(get_bars_per_day_exact(config)))