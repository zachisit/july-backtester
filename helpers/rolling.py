"""helpers/rolling.py

Trailing-window statistics that exclude the current bar.

WHY THIS MODULE EXISTS
----------------------
``series.rolling(N).mean()`` **includes the current bar**. When the resulting
average is then used as the *baseline* the current bar is tested against, the
bar inflates its own baseline and the stated threshold is silently not the
threshold:

    volume > 2.5 * volume.rolling(10).mean()

With a 10-bar window, that is algebraically ``volume > 3.0x`` the mean of the
*prior nine* bars. The rule reads as 2.5x and behaves as 3.0x, with nothing to
indicate the difference.

This has now been found independently three times in this project:

* a volume-spread indicator, where the inclusive 10-bar average made two of its
  eight patterns fire **0-1 times per symbol per decade** - effectively dead
  code that looked implemented;
* a gap-proximity scan, where a test spike measured **5.9x** instead of 8.0x;
* and the same shape exists today at several live call sites (see below).

Three independent rediscoveries is the signal that the correct convention needs
to be the easy one to reach for, rather than something each author derives.

WHEN THE INCLUSIVE FORM IS CORRECT
----------------------------------
Plenty of the time. A moving average used as a *trend line* (price vs its own
200-day mean) legitimately includes today. The defect is specific to using the
window as a **reference the current bar is compared against** - spike detection,
relative-volume, "unusual activity" screens.

Rule of thumb: if the current bar appears on **both** sides of the comparison,
exclude it from the baseline.

MIGRATION NOTE
--------------
Existing call sites are deliberately **not** rewritten by the PR introducing
this module. Switching an established indicator from inclusive to exclusive
changes its signals and therefore every backtest that uses it - that is a
per-strategy decision with a results delta, not a mechanical refactor. Known
inclusive sites at time of writing:

* ``main.py`` - ``Volume_Spike`` (also exported into the ML feature set)
* ``helpers/indicators.py:1429`` - ``avg_volume``
* ``custom_strategies/private/volume_spike_reversal.py``
* ``custom_strategies/private/vol_compression_breakout.py``
"""

from __future__ import annotations

import pandas as pd


def trailing_mean(series: pd.Series, window: int, *, exclude_current: bool = True,
                  min_periods: int | None = None) -> pd.Series:
    """Rolling mean over *window* bars, **excluding the current bar** by default.

    Parameters
    ----------
    series : pd.Series
        The series to average.
    window : int
        Number of bars in the window.
    exclude_current : bool, default True
        When True the window covers bars ``[t-window, t-1]``, so the value at
        ``t`` is a baseline the bar at ``t`` can be compared against without
        contaminating it. Set False for a genuine moving average that includes
        the current bar (e.g. a trend line).
    min_periods : int, optional
        Defaults to ``window`` - a full window is required, so the warm-up is
        ``NaN`` rather than an average of one or two bars. Counted in *prior*
        bars under ``exclude_current``: ``min_periods=1`` means "at least one
        preceding bar", so index 0 is still ``NaN`` and no bar can ever average
        against itself.

    Returns
    -------
    pd.Series
        Aligned to *series*, ``NaN`` during warm-up.
    """
    if window < 1:
        raise ValueError(f"window must be >= 1, got {window}")
    if min_periods is None:
        min_periods = window
    elif min_periods < 1:
        # `min_periods or window` would silently swallow 0 as "unset".
        raise ValueError(f"min_periods must be >= 1, got {min_periods}")
    base = series.shift(1) if exclude_current else series
    return base.rolling(window, min_periods=min_periods).mean()


def spike_ratio(series: pd.Series, window: int, *,
                min_periods: int | None = None) -> pd.Series:
    """Current bar as a multiple of its **trailing** (exclusive) mean.

    The intended form for "volume > N x average" tests::

        spike_ratio(df["Volume"], 20) > 2.5    # genuinely 2.5x the prior 20 bars

    rather than::

        df["Volume"] > 2.5 * df["Volume"].rolling(20).mean()   # actually ~2.71x

    The inclusive form's true multiple against the prior ``N-1`` bars is
    ``k(N-1)/(N-k)`` - for ``N=20, k=2.5`` that is **2.714**, and for the
    ``N=10, k=2.5`` case in the module docstring, exactly 3.0. Note it is *not*
    ``kN/(N-1)``; the current bar sits on both sides of the inequality, so
    solving for it changes the denominator as well as the numerator.

    Returns ``NaN`` where the baseline is ``NaN`` or **non-positive**, rather
    than ``inf`` or a sign-flipped ratio, so a zero-volume warm-up cannot
    register as an infinite spike.
    """
    base = trailing_mean(series, window, exclude_current=True, min_periods=min_periods)
    return (series / base.where(base > 0))
