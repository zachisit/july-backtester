"""helpers/corporate_actions.py

Putting per-share fundamentals on the same basis as prices.

WHY THIS MODULE EXISTS
----------------------
Price series and per-share fundamentals use **different share-count bases**, and
mixing them silently corrupts every ratio built from both:

    cur_pe = price / ttm_eps

Data vendors serve prices either as-traded or retroactively split-adjusted, but
normalised financials return EPS **as filed** - on the share count in force at
the time, never restated. A 10:1 split therefore makes P/E look **ten times
cheaper**, and a screen that ranks by *lowest* P/E promotes exactly the affected
names to the top of its buy list. Nothing errors.

This was found live: a quality-value screen selected a mega-cap growth name in
every quarter it qualified because its P/E was being divided by its split ratio,
and correcting it moved the strategy from apparently beating its benchmark by
6.7pp/yr to trailing it.

THE SUBTLETY THAT COST THREE REVIEW ROUNDS
------------------------------------------
Which splits matter depends entirely on the price convention, and two competent
readings of the same code disagreed until someone printed a number:

* ``price_adjustment="total_return"`` -> prices are rebased to **today's** share
  count. A split executing **after** the backtest window still reaches back and
  affects it: a 2026 split contaminates a 2024 P/E, because the 2024 price bar
  has already been divided by it while the 2024 EPS has not.
* ``price_adjustment="none"`` -> prices are **as traded**. Only splits executing
  *inside* the window matter; a future split is irrelevant because neither side
  reflects it yet. This convention therefore **requires** an ``as_of`` date -
  that is the only thing separating the two cases, so omitting it raises rather
  than silently adjusting for nothing.

Both models are correct - for their setting. Nothing in the codebase asserted the
relationship, so the disagreement was unresolvable by reading. Hence
:func:`split_adjustment_factor`, which takes the convention as an explicit
argument, and :func:`validate_fundamentals_basis`, which refuses to let it be
implicit.

IS THIS LOOK-AHEAD?
-------------------
No, for a **ratio**. P/E is scale-invariant: rescaling numerator and denominator
onto a common basis leaves it unchanged, so the P/E computed at ``T`` equals the
true P/E at ``T`` regardless of which basis both sides share. The same holds for
EPS growth and any per-share ratio.

It **would** be look-ahead for an absolute per-share *level* - a ``price >= 10``
floor, a fixed-dollar threshold. Under ``total_return`` a pre-split bar can sit
below such a floor when the real price then was well above it. Screens with
absolute price floors need to know this; see :func:`validate_fundamentals_basis`.
"""

from __future__ import annotations

import logging
import math

import pandas as pd

logger = logging.getLogger(__name__)

#: Price conventions this module understands.
ADJUSTED_TO_TODAY = "total_return"   # vendor rebases full history to current shares
AS_TRADED = "none"                   # nominal prices, never restated


def _naive(ts):
    """Drop tz so vendor split dates (naive calendar dates) compare against
    provider timestamps (this project normalises indices to UTC-aware)."""
    ts = pd.Timestamp(ts)
    return ts.tz_localize(None) if ts.tzinfo is not None else ts


def _require_known_convention(value: str) -> str:
    """Reject an unrecognised price convention.

    Shared by both public entry points **on purpose**. They previously disagreed
    on identical bad input - :func:`split_adjustment_factor` raised while
    :func:`validate_fundamentals_basis` fell through an ``if/elif`` and returned
    ``[]``, so a typo produced *zero* warnings from the one function whose job is
    to state the requirement out loud.

    That silence compounds: ``services/polygon_service.py`` tests the same value
    with ``== "total_return"`` and falls back to ``"false"``, so a misspelling
    also silently switches the vendor request to as-traded prices. Nothing
    downstream notices, because ``helpers/config_validator.py`` only checks that
    the key is *present*, not that its value is one this module understands.

    Centralising the check is what makes drifting apart again impossible.
    """
    if value not in (ADJUSTED_TO_TODAY, AS_TRADED):
        raise ValueError(
            f"unknown price_adjustment {value!r}; expected "
            f"{ADJUSTED_TO_TODAY!r} or {AS_TRADED!r}"
        )
    return value


def split_adjustment_factor(splits, period_end, *, as_of=None,
                            price_adjustment: str = ADJUSTED_TO_TODAY) -> float:
    """Divide a per-share figure from *period_end* by this to match the price basis.

    Parameters
    ----------
    splits : iterable of (execution_date, ratio)
        ``ratio`` is ``split_to / split_from`` - 10.0 for a 10-for-1.
    period_end : timestamp-like
        End of the fiscal period the per-share figure was reported for.
    as_of : timestamp-like
        The evaluation date. **Required under** :data:`AS_TRADED`, where a split
        that has not executed yet must not be applied - there is no safe default,
        because without an evaluation date no split can be classified as
        executed-yet, and silently treating them all as future would skip
        in-window splits that unambiguously matter. Ignored (and not required)
        under :data:`ADJUSTED_TO_TODAY`, where the price side already carries
        every split regardless of when it happened.
    price_adjustment : str
        :data:`ADJUSTED_TO_TODAY` or :data:`AS_TRADED`.

    Returns
    -------
    float
        Cumulative factor, ``1.0`` when no split applies.

    Raises
    ------
    ValueError
        Unknown *price_adjustment*; *as_of* omitted under :data:`AS_TRADED`; or a
        split ratio that is not a positive finite number.
    """
    _require_known_convention(price_adjustment)
    if price_adjustment == AS_TRADED and as_of is None:
        # Returning 1.0 here would be the exact silent-wrong-answer this module
        # exists to prevent: an in-window split left unadjusted, no log, no error.
        raise ValueError(
            "as_of is required under price_adjustment='none' (AS_TRADED): without "
            "an evaluation date no split can be classified as already executed"
        )
    splits = list(splits or ())   # materialise: a generator would be spent after
    if not splits:                # the first call from adjust_per_share()
        return 1.0

    period_end = _naive(period_end)
    as_of = _naive(as_of) if as_of is not None else None

    factor = 1.0
    for raw_date, ratio in splits:
        r = float(ratio)
        if not math.isfinite(r) or r <= 0:
            # Vendor feeds carry zeros and nulls for mislabelled distributions.
            # A ratio of 0 would divide EPS to inf -> P/E of 0 -> straight to the
            # top of a lowest-P/E ranking. Reverse splits (0 < r < 1) are valid.
            raise ValueError(
                f"split ratio must be a positive finite number, got {ratio!r} "
                f"on {raw_date!r}"
            )
        exec_date = _naive(raw_date)
        if exec_date <= period_end:
            # Already reflected in the as-filed figure. A split executing ON the
            # period end counts as inside it: the as-filed weighted-average share
            # count for that period already reflects it.
            continue
        if price_adjustment == AS_TRADED:
            # Prices are nominal, so a split only creates a mismatch once it has
            # actually executed. A future split affects neither side yet. A split
            # executing exactly ON as_of has executed, so it applies.
            if exec_date > as_of:
                continue
        factor *= r
    return factor


def adjust_per_share(values: pd.Series, period_ends, splits, *, as_of=None,
                     price_adjustment: str = ADJUSTED_TO_TODAY) -> pd.Series:
    """Vectorised :func:`split_adjustment_factor` over a series of per-share values.

    *period_ends* must align positionally with *values*; a length mismatch raises.
    """
    splits = list(splits or ())   # one-shot iterables are consumed by the first
    period_ends = list(period_ends)   # call below, silently leaving the rest at 1.0
    if len(period_ends) != len(values):
        raise ValueError(
            f"period_ends has {len(period_ends)} entries but values has "
            f"{len(values)}; they must align positionally"
        )
    factors = [
        split_adjustment_factor(splits, pe, as_of=as_of,
                                price_adjustment=price_adjustment)
        for pe in period_ends
    ]
    return values / pd.Series(factors, index=values.index)


def validate_fundamentals_basis(config: dict, *, uses_per_share_ratio: bool = True,
                                uses_absolute_price_floor: bool = False) -> list[str]:
    """Warn when a price convention and fundamentals usage are inconsistent.

    Call this from any strategy or research harness that divides a price by a
    per-share fundamental. It does not know whether the caller *has* split-
    adjusted - it makes the requirement explicit and states which splits matter,
    so the question is answered deliberately rather than assumed.

    Returns a list of warning strings (empty when nothing to flag).

    Raises
    ------
    ValueError
        ``config["price_adjustment"]`` is present but not a convention this
        module understands. An *absent* key is fine and defaults to
        :data:`ADJUSTED_TO_TODAY`; an unrecognised one is a typo whose most
        likely outcome is silently receiving as-traded data from the vendor
        while believing otherwise. See :func:`_require_known_convention`.
    """
    warnings: list[str] = []
    adjustment = config.get("price_adjustment", ADJUSTED_TO_TODAY)
    _require_known_convention(adjustment)

    if uses_per_share_ratio:
        if adjustment == ADJUSTED_TO_TODAY:
            warnings.append(
                "INFO: price_adjustment='total_return' -> prices are rebased to "
                "TODAY's share count. Per-share fundamentals must be divided by "
                "the cumulative ratio of EVERY split executing after each period "
                "end, INCLUDING splits after the backtest window. An unadjusted "
                "denominator understates P/E by the split ratio and promotes "
                "split names in any lowest-P/E ranking."
            )
        elif adjustment == AS_TRADED:
            warnings.append(
                "INFO: price_adjustment='none' -> prices are as-traded. Only "
                "splits executing INSIDE the evaluation window create a basis "
                "mismatch, and those still MUST be adjusted for. as_of is "
                "REQUIRED by split_adjustment_factor under this convention - it "
                "is what separates an already-executed split from a future one."
            )

    if uses_absolute_price_floor and adjustment == ADJUSTED_TO_TODAY:
        warnings.append(
            "WARNING: an absolute price floor (e.g. price >= 10) under "
            "price_adjustment='total_return' is NOT scale-invariant. A pre-split "
            "bar is divided by the split ratio, so a stock that really traded at "
            "$750 can fail a $10 floor. Ratios are unaffected; absolute levels "
            "are not."
        )

    for msg in warnings:
        # The look-ahead message is the only real defect this can report; logging
        # it at INFO under a default WARNING-level root logger made it invisible.
        (logger.warning if msg.startswith("WARNING") else logger.info)(msg)
    return warnings
