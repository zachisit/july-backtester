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
# carrying +99,999,900% scores 96/100 and passes, as does 1e-04 at +1,999,900%,
# because CHECK 4 counts jumps and never weighs magnitude. The durable fix is a
# magnitude escalation in CHECK 4 plus a dollar-volume screen at selection
# (both follow-ups). This is a stopgap keyed to today's corpus, and should be
# retired when they land.
#
# PRECISION ON "FAIL": main.py warns below `data_quality_threshold` (80) and
# only RAISES when `strict_data_quality=True`, which is False by default. So
# under stock config this surfaces the series loudly; it hard-stops a run only
# in strict mode. Worth stating exactly, because "blocking" overstated it.
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
        returns = named["Close"].pct_change().abs()
        large_jumps = returns[returns > _PRICE_JUMP_THRESHOLD]
        if len(large_jumps) > 0:
            # Report first 3 jumps
            jump_dates = large_jumps.head(3).index.strftime("%Y-%m-%d").tolist()
            jump_pcts = large_jumps.head(3).values * 100
            jump_strs = [f"{date} ({pct:.1f}%)" for date, pct in zip(jump_dates, jump_pcts)]
            issues.append(f"Price jumps >{_PRICE_JUMP_THRESHOLD*100:.0f}%: {len(large_jumps)} occurrences, e.g., {', '.join(jump_strs)}")
            demerits += min(15, len(large_jumps) * 2)

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
