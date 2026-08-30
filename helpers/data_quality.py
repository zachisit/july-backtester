"""helpers/data_quality.py

Pre-flight data quality validation for OHLCV data.

Detects common data issues that silently corrupt backtest results:
1. Missing bars (gaps in expected calendar)
2. Price jumps >20% (potential unadjusted splits)
3. Zero volume days
4. OHLC relationship violations
5. Negative prices
6. Duplicate timestamps
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from typing import Any

logger = logging.getLogger(__name__)

# Price jump threshold (20% daily move flags as potential unadjusted split)
_PRICE_JUMP_THRESHOLD = 0.20

# --- issue #360 ---------------------------------------------------------------
# CHECK 4 counted jumps and never weighed them, and the count saturates at
# min(15, n*2). So ONE catastrophic bar cost 2 points: a synthetic 1e-06 -> 1.0
# round-trip (+99,999,900%) scored 96/100 and passed, and so did a real one —
# ELRNF, 4.37e-07 -> 0.656. A 25% tick-quantisation wobble on a 1990s
# $0.125-grid name and a 1,000,000x unadjusted split were priced identically.
#
# Escalate on the WORST surviving jump, by decade, because the damage is
# log-scaled: 30% is noise, 300% is a 4:1 split, 30,000% is a units error.
#   decades = floor(log10(worst));  charge 15/decade, capped at 45.
# Nothing is charged below one decade (1,000%), which leaves every honest large
# move — earnings gaps, biotech binaries, ordinary splits — exactly where it
# was. Calibration is insensitive: +15/cap45, +20/cap50 and +25/cap60 demote
# the SAME 144 corpus series and none leaves anything above the gate, so the
# mildest is taken. It is the easiest to defend the day someone asks why a
# series lost points.
#
# --- issue #368 ---
# `worst` is max(a,b)/min(a,b) - 1, not `pct_change().abs()`. pct_change is
# unbounded above and bounded at 1.0 below, so a FALL can never reach one
# decade however far it falls, and the escalation could only ever see upward
# moves. An unadjusted FORWARD split -- the more common corporate action of
# the two -- scored 98 and passed while its mirror-image REVERSE split scored
# 68. A one-way collapse from $2 to $2e-06 that never comes back is
# untradeable, prints as exactly -100%, and passed at 98 with CHECK 7 blind to
# it as well: that check keys on exactly 1e-06. Round-trips through the same
# floor were already caught, because their UP leg carried the magnitude.
#
# max/min - 1 is the SAME number as |pct_change| for an upward move -- both
# are p/prev - 1 -- so every threshold above keeps the value it was calibrated
# to, by construction rather than by re-measurement, and a fall is weighed as
# the mirror-image rise it would have been had the series been read the other
# way round. The bare ratio would NOT do: it shifts every magnitude up by a
# decade, so a -90% crash and a +900% biotech binary become one decade and get
# charged, and it needs the floor moved to 2 to leave them alone. Eligibility
# stays on |pct_change| > 20%, which is very slightly tighter downward (a
# ratio of 1.25) than upward (1.2); a move that fails it has a ratio of at
# most 1.25, which is zero decades, so the escalation loses nothing to that.
_JUMP_MAGNITUDE_PER_DECADE = 15
_JUMP_MAGNITUDE_CAP = 45

# TWO GUARDS, because `pct_change()` is boundary-blind and would otherwise
# misattribute 59 of its 144 hits (41%). A demerit is recoverable; an issue
# string naming the wrong cause is not — it sends every future reader hunting
# for a split that does not exist, and nothing in the score says it was wrong.
#
#   GAP      the "jump" spans a coverage hole and is not a jump at all. CELH
#            $1.0033 -> $13.3333 is +1,228.9% over 82 CALENDAR days: honest
#            data with a three-month hole in it. 26 of the 144. CHECK 9 already
#            reports the hole, and reports it correctly.
#   SUBPENNY both ends under a cent: tick-grid bounce on a bankrupt shell.
#            TUPBQ $0.0001 -> $0.0013 is 1,200% of nothing — the denominator is
#            the grid minimum, so the percentage is enormous while the move is
#            a handful of ticks. It is not evidence of a split, and calling it
#            one is the misattribution. 36 of the 144 — 3 of which are
#            also GAP, which is why 26 + 36 dedupes to 59 and not 62.
#
#            Stated plainly rather than papered over: these 36 carry NO
#            demerit from CHECK 7 either. Measured — 0 of 36 carry a floor bar,
#            because CHECK 7 keys on EXACTLY 1e-06 and these sit at 1e-04 to
#            1e-05. So guarding here leaves a genuinely untradeable series
#            scoring 80-84 and passing. That is a real hole, and it is NOT this
#            check's to close. "Untradeable" is not "wrong": its honest home is
#            the dollar-volume screen (filter_universe / the still-unwired
#            merged_min_avg_dollar_volume), not a data-quality demerit.
#            Charging a split demerit here to cover for it would put the right
#            number on the wrong reason.
#
#            Do NOT reach for an absolute price-LEVEL check instead. It is
#            genuinely the one axis validate_ohlcv lacks, and it was measured
#            and rejected (#367): of the 641 series with a max close over
#            $10,000, 555 simply decay to a sane modern price, because that is
#            what cumulative reverse-split back-adjustment looks like. UVXY is
#            in there with a first bar of $5.1e+11 and no residual
#            discontinuity that is not a real volatility event, and SPX/DJI/
#            NDX/RUT/OEX live in the same store carrying index levels rather
#            than share prices. A level threshold fires mostly on correct
#            data.
#
# 85 of the 144 survive both guards: TOVX, AMDS, HLMMQ — adjacent-bar
# unadjusted reverse splits, which is what the check's name promises. Both
# guards restrict the MAGNITUDE escalation ONLY; the count demerit is
# untouched, so a guarded jump is still reported and still charged as a jump.
#
# Both guards are per-JUMP, not per-series, which is why the demerit is taken
# from the worst ELIGIBLE jump rather than the worst jump. 9 of the 59 guarded
# series are charged anyway, every one of them on a different bar than the one
# that got them classified — CLRD's +125,000% spans a 6-day hole and is
# ignored, and the +8,417% four days later on adjacent bars is not. Taking the
# series maximum instead would let a guarded jump lend its magnitude to an
# eligible one, which is the mutant `worst overall, not worst eligible` pins.
_JUMP_MAX_BAR_GAP_DAYS = 5          # a long weekend; anything more is a hole
_JUMP_SUBPENNY_PRICE = 0.01

# --- issue #350 ---------------------------------------------------------------
# The merged corpus carries closes of EXACTLY 1e-06: 25,730 bars across 813
# series (measured full-corpus over O/H/L/C; an earlier partial scan said
# 23,695+/782+).
#
# WHAT 1e-06 IS. Not an injected sentinel. It is the bottom of the provider's
# fixed absolute tick grid: the share of closes sitting exactly on the round
# decade climbs monotonically as price falls ($100 0.26% -> $0.01 5.57% ->
# $0.0001 38.79% -> $1e-06 99.34%), one bar in 74.9M sits strictly below it,
# none of the affected bars have zero volume, and all 813 series come from one
# provider. A clamp produces a spike with nothing behind it and leaves zero
# bars below the floor. This is a real, representable price.
#
# NOT "these are not sub-penny stocks" — that claim was filed on #350 and
# RETRACTED there, and it was wrong the same way twice: the $10.00/$8.70/$8.50
# medians quoted for FMNJ/NEOM/RINO are over the WHOLE FILE (29-36 years,
# mostly while the company was alive). Over only the years the 1e-06 prints
# occur they are $0.0005/$0.0001/$0.0001. Corpus-wide, 639 of the 813 affected
# series are under a cent in the era the prints occur. They ARE sub-penny.
#
# WHY THE CHECK STILL EARNS ITS PLACE. Correct price, unusable bar: a close of
# 1e-06 against a neighbour at 1e-04 is a true -99% and a true +9,900%, and
# returns/ATR/vol/sizing computed off it are garbage whether or not the quote
# is honest. The check is about tradeability, not truthfulness.
_SENTINEL_CLOSE = 1e-06
_SENTINEL_ATOL = 1e-12
# Deliberately large enough to fail any reasonable gate on its own. Every other
# check here is proportional to how much data is affected; this one is not,
# because the DAMAGE saturates at one bar. A single floor print in an otherwise
# clean $2 series manufactures a +199,999,900% one-bar return, which is as
# ruinous to a Sharpe, a vol estimate or an MC draw over that window as 644 of
# them. So LKCOF (1 bar in 1,690) and HMNY (644 in 5,750) taking the same 60 is
# the design working, not indiscriminate scoring. Proportional scoring would
# re-open the hole: at 0.06% affected, LKCOF would lose ~0 points and pass.
#
# WHY IT IS NOT REDUNDANT WITH CHECK 4. Every affected series does also trip
# the price-jump check, but CHECK 4 saturates at min(15, jumps*2), so 115 of
# the 813 affected corpus series still score >= 80 at base (max 84) — and
# main.py prints only sub-threshold rows, so the issue string of a passing
# symbol is never displayed. CHECK 7 is what demotes those 115.
#
# WHAT IT IS NOT: a general detector. It keys on one value, so the identical
# round-trip one tick up evades it entirely — verified: a single 2e-06 bar
# carrying +99,999,900% scored 96/100 and passed, as did 1e-04 at +1,999,900%,
# because CHECK 4 counted jumps and never weighed magnitude. CHECK 4 now weighs
# magnitude (#360), which closes that specific hole.
#
# IT IS STILL NOT REDUNDANT, and the note here used to say it should be
# "retired when they land". That was wrong, and measuring it is what showed so.
# The two checks have complementary blind spots, with ZERO overlap at the gate:
#   * A magnitude escalation keyed above 1,000% cannot see a floor series whose
#     largest move is smaller than that. 26 floor series have max |ret| <= 1000%
#     and 10 of them pass the 80 gate with this check disabled — one is FRCB,
#     First Republic, $3.51 -> $0.3336 across the 2023 receivership.
#   * Conversely CHECK 7 cannot see ELRNF: 4.37e-07 -> 0.656, +149,999,907%,
#     the ONE bar in 74.9M sitting strictly BELOW the floor, invisible to a
#     check that keys on the exact value.
# Corpus-wide: of the 1,760 series carrying a >1,000% bar, all 787 that also
# carry floor bars already score < 80 without CHECK 7, and all 144 that still
# pass carry no floor bar at all. Neither check subsumes the other.
#
# PRECISION ON "FAIL": main.py warns below `data_quality_threshold` (80) and
# only RAISES when `strict_data_quality=True`, which is False by default. So
# under stock config this surfaces the series loudly; it hard-stops a run only
# in strict mode. Worth stating exactly, because "blocking" overstated it.
_SENTINEL_DEMERITS = 60

# A listed equity trades ~252 days/yr. A long span at low density is a stitched
# or recycled ticker wearing one symbol — the check that catches SSCC and FER.
_DENSITY_MIN_YEARS = 3.0
_DENSITY_MIN_BARS_PER_YEAR = 150
_DENSITY_DEMERITS = 25

# Density measures bars against SPAN, which is a ratio — and a ratio cannot
# separate "uniformly thin" from "two dense eras with a hole in between". It
# only trips once >40% of the span is missing, so the shapes this was named for
# were passing anyway: a 5-year hole in a 20-year span scored 87.0, and the
# sub-3-year variant landed on EXACTLY 80.0 — not below it — sliding under the
# strict `< 80` gate. The hole itself is the evidence, so measure it directly
# and do NOT gate it on _DENSITY_MIN_YEARS; that is the guard it slipped past.
# A listed equity's largest real gap is a long weekend; a year of nothing is a
# different security wearing the same symbol.
_GAP_MAX_DAYS = 365
_GAP_DEMERITS = 25


def validate_ohlcv(df: pd.DataFrame, symbol: str, timeframe: str = "D",
                   calendar: str = "NYSE") -> tuple[float, list[str]]:
    """
    Validate OHLCV data and return quality score 0-100 and list of issues.

    Checks performed:
    1. Missing bars (compare against expected calendar)
    2. Price jumps >20% (potential unadjusted split)
    3. Zero volume days
    4. OHLC relationship violations (High < Low, Close outside H/L range)
    5. Negative prices
    6. Duplicate timestamps

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV data with DatetimeIndex. Expected columns: Open, High, Low, Close, Volume
    symbol : str
        Symbol name for error messages
    timeframe : str
        Timeframe code ("D", "H", "MIN", etc.) - used for missing bar detection

    Returns
    -------
    score : float
        Quality score 0-100 (100 = perfect, 0 = severe issues)
    issues : list[str]
        Human-readable issue descriptions

    Examples
    --------
    >>> score, issues = validate_ohlcv(spy_df, "SPY", "D")
    >>> if score < 80:
    ...     print(f"Low quality data: {issues}")
    """
    if df is None or df.empty:
        return 0.0, [f"{symbol}: DataFrame is empty"]

    issues = []
    demerits = 0  # Points deducted from 100
    total_bars = len(df)

    # Column-name normalisation (#358). CHECK 7 was made case-insensitive
    # because the merged store writes lowercase `ohlcv` and a raw audit of that
    # corpus silently no-opped against "Close". That reasoning applies to every
    # check here, and CHECKS 2-5 matched literally — so against the corpus this
    # module exists to audit they did not fail loudly, they SKIPPED. A frame
    # with a High<Low violation, a 400% jump and 30 zero-volume bars scored
    # 100/100 in lowercase.
    #
    # Resolved once here rather than per check, so the next check added cannot
    # reintroduce it. `capitalize()` also folds "CLOSE". Duplicate labels after
    # folding keep the first (the csv_service pattern) — CHECK 7 deliberately
    # keeps reading the ORIGINAL frame positionally, so it still sees a column
    # dropped here.
    named = df.rename(columns=lambda c: str(c).capitalize())
    named = named.loc[:, ~named.columns.duplicated(keep="first")]

    # --- CHECK 1: Duplicate timestamps ---
    duplicates = df.index.duplicated().sum()
    if duplicates > 0:
        issues.append(f"Duplicate timestamps: {duplicates} bars")
        demerits += min(20, duplicates * 2)  # Cap at 20 points

    # --- CHECK 2: Negative prices ---
    for col in ["Open", "High", "Low", "Close"]:
        if col in named.columns:
            negative_count = (named[col] < 0).sum()
            if negative_count > 0:
                issues.append(f"Negative {col} prices: {negative_count} bars")
                demerits += min(30, negative_count * 5)  # Severe issue

    # --- CHECK 3: OHLC relationship violations ---
    if all(c in named.columns for c in ["Open", "High", "Low", "Close"]):
        # High must be >= Low
        hl_violations = (named["High"] < named["Low"]).sum()
        if hl_violations > 0:
            issues.append(f"High < Low violations: {hl_violations} bars")
            demerits += min(25, hl_violations * 3)

        # Close must be within [Low, High]
        close_violations = ((named["Close"] < named["Low"]) | (named["Close"] > named["High"])).sum()
        if close_violations > 0:
            issues.append(f"Close outside H/L range: {close_violations} bars")
            demerits += min(20, close_violations * 2)

        # Open must be within [Low, High]
        open_violations = ((named["Open"] < named["Low"]) | (named["Open"] > named["High"])).sum()
        if open_violations > 0:
            issues.append(f"Open outside H/L range: {open_violations} bars")
            demerits += min(15, open_violations * 2)

    # --- CHECK 4: Price jumps >20% (potential unadjusted splits) ---
    if "Close" in named.columns:
        # Sorted, because a return is a property of the DATA and not of row
        # order. On a newest-first frame (services/csv_service.py never sorts,
        # and supports the newest-first Nasdaq.com export) pct_change reads
        # every move backwards: a +10,000% jump prints as -99%, which still
        # trips the 20% threshold but reads as 0 decades and escapes the
        # magnitude escalation entirely. Same defect CHECK 8 was fixed for.
        close = named["Close"]
        if isinstance(close.index, pd.DatetimeIndex):
            close = close.sort_index()
        returns = close.pct_change().abs()
        large_jumps = returns[returns > _PRICE_JUMP_THRESHOLD]
        if len(large_jumps) > 0:
            # Report first 3 jumps
            jump_dates = large_jumps.head(3).index.strftime("%Y-%m-%d").tolist()
            jump_pcts = large_jumps.head(3).values * 100
            jump_strs = [f"{date} ({pct:.1f}%)" for date, pct in zip(jump_dates, jump_pcts)]
            issues.append(f"Price jumps >{_PRICE_JUMP_THRESHOLD*100:.0f}%: {len(large_jumps)} occurrences, e.g., {', '.join(jump_strs)}")
            demerits += min(15, len(large_jumps) * 2)

            # Magnitude escalation (#360). See _JUMP_MAGNITUDE_PER_DECADE for
            # why the count alone priced a 25% wobble and a 1,000,000x split
            # the same, and _JUMP_MAX_BAR_GAP_DAYS for the two guards.
            # Positional throughout. CHECK 1 reports duplicate timestamps and
            # keeps going, so this code has to survive them: `.reindex()` on a
            # duplicated axis raises outright, and `.loc[label]` on one returns
            # a Series that min()/max() cannot compare. Both would come out of
            # a function whose contract is to survive bad data and report on it.
            prices = close.to_numpy(dtype="float64")
            prev = np.concatenate([[np.nan], prices[:-1]])
            hi_end = np.maximum(prices, prev)
            lo_end = np.minimum(prices, prev)
            rets = returns.to_numpy(dtype="float64")

            # The magnitude weighed below is max/min - 1, not the return
            # (#368). For an upward move it is algebraically the same as
            # `rets` -- both are p/prev - 1 -- and the mirror-image magnitude
            # for a downward one, which `rets` cannot express at all: it is
            # bounded at 1.0 below. Algebraically, not bit-for-bit: (b-a)/a
            # and b/a - 1 are different float evaluations and disagree in the
            # last ulp (measured max 9.1e-13 over 200k random up-moves). That
            # cannot reach a decade -- 3M samples clustered on the 11x
            # boundary produced 0 disagreements in floor(log10) -- so the
            # #360 calibration is preserved, but do not read "identical" as
            # "the same bits".
            with np.errstate(divide="ignore", invalid="ignore"):
                magnitude = np.where(lo_end > 0, hi_end / lo_end - 1.0, np.nan)

            # isfinite on BOTH, because the two catch different bars. A
            # prev_close of exactly 0 makes pct_change return inf, and
            # np.log10(inf) is not an int (OverflowError). A CLOSE of exactly
            # 0 against a positive previous close makes pct_change return
            # exactly -1.0, which is finite and passes the 20% threshold,
            # while max/min is infinite -- the same OverflowError from the
            # other side, and one this check did not have before #368.
            #
            # Both are a zero price rather than a split, so neither has a
            # magnitude worth weighing here. Do NOT read that as "CHECK 2
            # owns it": CHECK 2 tests `< 0` strictly, so a close of exactly
            # 0 is caught by no check in this function -- 6.25 -> 0 -> 6.25
            # scores 96.0 and prints "inf%" in the CHECK 4 count string.
            # Skipping it is still right for this check; it is simply
            # unowned, not handled elsewhere (#369).
            eligible = (rets > _PRICE_JUMP_THRESHOLD) & np.isfinite(rets)
            eligible &= np.isfinite(magnitude)
            eligible &= hi_end >= _JUMP_SUBPENNY_PRICE
            if isinstance(close.index, pd.DatetimeIndex):
                spacing = close.index.to_series().diff().dt.days.to_numpy(
                    dtype="float64")
                eligible &= spacing <= _JUMP_MAX_BAR_GAP_DAYS

            if eligible.any():
                pos = int(np.argmax(np.where(eligible, magnitude, -np.inf)))
                worst = float(magnitude[pos])
                # floor(log10) of a RATIO: 10.0 (an 11x move either way) is
                # one decade, 100.0 (101x) two. Guarded against worst <= 0,
                # which the ratio cannot produce here -- the threshold is
                # 0.20, so max/min is above 1.2 -- but which a future
                # threshold change could.
                decades = int(np.floor(np.log10(worst))) if worst > 0 else 0
                if decades >= 1:
                    demerits += min(_JUMP_MAGNITUDE_CAP,
                                    decades * _JUMP_MAGNITUDE_PER_DECADE)
                    at = close.index[pos]
                    # CHRONOLOGICAL, not lo -> hi. The magnitude is symmetric;
                    # the series is not, and printing a fall as "$1 -> $200"
                    # names the wrong corporate action (#368).
                    was = float(prev[pos])
                    now = float(prices[pos])
                    signed = (now / was - 1.0) * 100.0
                    when = at.strftime("%Y-%m-%d") if hasattr(at, "strftime") else str(at)
                    issues.append(
                        f"Extreme price jump: {signed:+,.0f}% on {when} "
                        f"(${was:.6g} -> ${now:.6g}) — a {worst + 1.0:,.0f}x "
                        f"{'rise' if now > was else 'fall'}, {decades} decades "
                        f"past {_PRICE_JUMP_THRESHOLD * 100:.0f}%, on ADJACENT "
                        f"bars and above ${_JUMP_SUBPENNY_PRICE:g}, so neither "
                        f"a coverage gap nor tick-grid bounce; consistent with "
                        f"an unadjusted split (#360)")

    # --- CHECK 5: Zero volume days ---
    if "Volume" in named.columns:
        zero_volume = (named["Volume"] == 0).sum()
        if zero_volume > 0:
            pct = (zero_volume / total_bars) * 100
            issues.append(f"Zero volume: {zero_volume} bars ({pct:.1f}%)")
            demerits += min(10, int(pct))  # 1 point per 1% of bars

    # --- CHECK 6: Missing bars ---
    # Only check for daily equities data. Futures (CME_ETH, 23/5 sessions with a
    # different holiday calendar) don't match a Mon–Fri business-day count, so the
    # NYSE-based estimate would flag phantom gaps — skip it for non-NYSE calendars.
    if timeframe.upper() == "D" and total_bars > 1 and str(calendar).upper() == "NYSE":
        # min/max, not [0]/[-1]: on a newest-first index the latter hands
        # _estimate_expected_bars a reversed range, which returns 0 expected
        # bars and silently passes the series. Same defect as CHECK 8 had.
        expected_bars = _estimate_expected_bars(
            df.index.min(), df.index.max(), timeframe)
        if expected_bars > total_bars:
            missing = expected_bars - total_bars
            pct = (missing / expected_bars) * 100
            issues.append(f"Missing bars: {missing} gaps ({pct:.1f}% of expected)")
            demerits += min(20, int(pct / 2))  # 1 point per 2% missing

    # --- CHECK 7: floor-tick prices (issue #350) ---
    # Bars printing EXACTLY 1e-06, the bottom of the provider's tick grid. See
    # the note on _SENTINEL_CLOSE for what the value is and is not — in
    # particular this does NOT claim the affected names are anything other than
    # sub-penny stocks, which is what they are.
    #
    # Disproportionate by design — see the note on _SENTINEL_DEMERITS for what
    # that does and does not do, and for the open question about flat scoring.
    #
    # SCOPE: keyed on the VALUE 1e-06, not on the round-trip shape, so it
    # assumes an instrument where 1e-06 is below anything worth trading. True
    # for the equities and futures this engine trades; it would be wrong for a
    # sub-micro-dollar crypto pair, which would take the full demerit on honest
    # data. Revisit if such data ever reaches this function.
    #
    # Scans ALL FOUR price columns, case-insensitively:
    #   * a sentinel on Low is the shape that actually trades — every daily-bar
    #     stop in this engine fills off Low, so a fabricated wick to the floor
    #     is worse than a fabricated close. Close-only scored such a bar 100/100.
    #   * the merged store writes LOWERCASE ohlcv. A raw audit of that corpus —
    #     the corpus this check exists for — silently no-opped against "Close".
    #   * EVERY column matching the name, not one per name. A dict keyed on the
    #     lowercased name keeps only the last, so a frame carrying both `close`
    #     (with the sentinel) and `Close` (clean) — exactly the artifact a merge
    #     of a mixed-case corpus produces — scanned the clean one and scored 100.
    if total_bars > 0:
        affected = np.zeros(total_bars, dtype=bool)
        hit_cols = []
        lowered = [str(c).lower() for c in df.columns]
        for name in ("close", "open", "high", "low"):
            for pos, lower_name in enumerate(lowered):
                if lower_name != name:
                    continue
                # Positional, because a duplicated label makes df[label] a
                # DataFrame rather than a Series.
                vals = pd.to_numeric(
                    df.iloc[:, pos], errors="coerce").to_numpy(dtype="float64")
                mask = np.isclose(vals, _SENTINEL_CLOSE, rtol=0.0,
                                  atol=_SENTINEL_ATOL)
                if mask.any():
                    affected |= mask
                    col_label = str(df.columns[pos])
                    if col_label not in hit_cols:
                        hit_cols.append(col_label)
        sentinel = int(affected.sum())      # bars, not cells — no double count
        if sentinel > 0:
            pct = (sentinel / total_bars) * 100
            issues.append(
                f"Tick-floor prices (== {_SENTINEL_CLOSE:g}) in "
                f"{'/'.join(hit_cols)}: {sentinel} bars ({pct:.1f}%) — real "
                f"quotes at the provider's grid floor, but untradeable: one "
                f"such bar poisons return/vol/Sharpe/MC for any window "
                f"containing it (#350)")
            demerits += _SENTINEL_DEMERITS

    # --- CHECK 8: bar density (issue #350) ---
    # A listed equity trades ~252 days/yr. A long span with a low median
    # bars-per-year is a stitched or recycled ticker wearing one symbol — the
    # check that would have caught SSCC and FER.
    if (timeframe.upper() == "D" and total_bars > 1
            and isinstance(df.index, pd.DatetimeIndex)):
        # Read the geometry off a SORTED copy. `index[-1] - index[0]` goes
        # NEGATIVE on a newest-first index, fails the span gate, and skips the
        # check on exactly the series it exists to catch — a descending sparse
        # series scored 100.0 where the same data ascending scored 55.0. Not
        # hypothetical: services/csv_service.py never sorts its index (the
        # other three providers do) and supports the newest-first Nasdaq.com
        # export. The score must be a property of the data, not of row order.
        ordered = df.index.sort_values()
        span_years = (ordered[-1] - ordered[0]).days / 365.25
        # Measured regardless of the span gate, because CHECK 9 needs the
        # density verdict even on spans too short for CHECK 8 to report on.
        is_sparse = (span_years > 0
                     and total_bars / span_years < _DENSITY_MIN_BARS_PER_YEAR)
        if span_years > _DENSITY_MIN_YEARS:
            # bars / SPAN, not the median over trading years. The median counts
            # only years that have bars, so the canonical recycled-ticker shape
            # — dense era, multi-year hole, dense era — read as 261 bars/yr and
            # scored exactly 80.0, passing a strict `< 80` gate. That is the
            # very shape this check is named for. Measuring against the span
            # makes a hole count against the series, which is the point.
            bars_per_year = total_bars / span_years
            if bars_per_year < _DENSITY_MIN_BARS_PER_YEAR:
                # States what was measured, not a cause. A thin-but-continuous
                # series and a stock returning from a two-year halt both land
                # here, and neither is evidence of stitching — naming a cause
                # this check cannot distinguish sends the reader the wrong way.
                # CHECK 9 owns the "recycled" claim, because a hole evidences it.
                issues.append(
                    f"Sparse history: {bars_per_year:.0f} bars/yr over "
                    f"{span_years:.1f}y (expect ~252) — thin coverage (#350)")
                demerits += _DENSITY_DEMERITS

        # --- CHECK 9: internal history gap (issue #350) ---
        # The hole itself, measured directly. See _GAP_MAX_DAYS for why the
        # bars/span ratio in CHECK 8 cannot stand in for this, and why this one
        # is deliberately NOT gated on _DENSITY_MIN_YEARS.
        gap = ordered.to_series().diff().max()
        if pd.notna(gap) and gap.days > _GAP_MAX_DAYS:
            at = ordered[int(np.argmax(np.diff(ordered.to_numpy())))]
            where = (f"{gap.days} days ({gap.days / 365.25:.1f}y) with no bars "
                     f"after {at.date()}")
            if is_sparse:
                # Sparse on both sides AND holed — the SSCC/FER signature,
                # where the provider resolved a thin wrong-file series over the
                # dense real one. Here the accusation is earned.
                issues.append(
                    f"History gap: {where} — stitched or recycled ticker "
                    f"(#350)")
                demerits += _GAP_DEMERITS
            else:
                # Dense on both sides of the hole: a corporate action, not a
                # stitch. NBIS (Yandex suspended Feb 2022, relisted as Nebius
                # Oct 2024) runs 207 bars/yr and trades $1.4bn/day; OLED and
                # RDNT are the same shape. Charging them the gap demerit
                # crossed the 80 gate on all three, on honest data. The hole is
                # real and worth reporting — a backtest spanning it has a
                # hole too — so report it and charge nothing. The demerit
                # needs the sparse evidence, and that is CHECK 8's job.
                issues.append(
                    f"History gap: {where} — dense on both sides, so a "
                    f"corporate action or suspension rather than a stitch; "
                    f"reported, not penalised (#350)")

    # --- COMPUTE SCORE ---
    score = max(0.0, 100.0 - demerits)

    return score, issues


def _estimate_expected_bars(start_dt: pd.Timestamp, end_dt: pd.Timestamp, timeframe: str) -> int:
    """
    Estimate expected number of bars for a date range.

    Uses business day frequency for daily data. Returns actual count for
    intraday (missing bar check disabled for intraday).

    Parameters
    ----------
    start_dt : pd.Timestamp
        First bar timestamp
    end_dt : pd.Timestamp
        Last bar timestamp
    timeframe : str
        Timeframe code ("D", "H", "MIN")

    Returns
    -------
    int
        Estimated bar count
    """
    if timeframe.upper() == "D":
        # Business days between start and end (approximate)
        bdays = pd.bdate_range(start=start_dt, end=end_dt, freq="B")
        return len(bdays)
    else:
        # Intraday: missing bars are expected (market hours, holidays)
        # Return 0 to disable the check
        return 0


def quality_report(symbols: list[str], data: dict[str, pd.DataFrame], timeframe: str = "D",
                   config: dict | None = None) -> pd.DataFrame:
    """
    Generate quality report for multiple symbols.

    Parameters
    ----------
    symbols : list[str]
        List of symbol names
    data : dict[str, pd.DataFrame]
        {symbol: OHLCV DataFrame} mapping
    timeframe : str
        Timeframe code for missing bar detection

    Returns
    -------
    pd.DataFrame
        Columns: symbol, score, issues (joined string), bars
        Sorted by score (lowest first)
    """
    rows = []
    for symbol in symbols:
        df = data.get(symbol)
        if df is None:
            rows.append({
                "symbol": symbol,
                "score": 0.0,
                "issues": "No data",
                "bars": 0,
            })
            continue

        calendar = "NYSE"
        if config is not None:
            try:
                from helpers.instruments import resolve_instrument
                calendar = resolve_instrument(symbol, config).calendar
            except Exception:
                calendar = "NYSE"
        score, issues = validate_ohlcv(df, symbol, timeframe, calendar=calendar)
        rows.append({
            "symbol": symbol,
            "score": score,
            "issues": "; ".join(issues) if issues else "No issues",
            "bars": len(df),
        })

    report_df = pd.DataFrame(rows)
    report_df = report_df.sort_values("score", ascending=True).reset_index(drop=True)
    return report_df
