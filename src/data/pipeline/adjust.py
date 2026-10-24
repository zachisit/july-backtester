"""Task 5 — Option A total-return forward-adjustment factor engine.

Anchored at 2026-04-22 (factor == 1.0). For each patch date the cumulative
factor is the product of every corporate-action multiplier whose ex-date is in
(ANCHOR, date]:

  * split  (split_from f, split_to t): price x (t/f)   ; volume x (f/t)
  * dividend (cash d, prev raw close C): price x (1 + d/C)  ; volume unchanged

Canonical price = raw_price x price_factor.  Canonical volume = raw_volume x volume_factor.
Raw is recoverable as canonical_price / price_factor.

Sanity guards (fail-closed / flag): a dividend with d/C above DIV_FAIL is dropped
and the symbol flagged; d/C above DIV_WARN is applied but warned; extreme split
ratios are applied but warned (legit penny-stock reverse splits).
"""
import os
import json
import pandas as pd

from . import paths

DIV_WARN = 0.25     # dividend > 25% of price -> warn (special dividend territory)
DIV_FAIL = 0.60     # dividend > 60% of price -> drop + flag (almost certainly bad)
SPLIT_RATIO_WARN = 50.0


def load_corporate_actions(last_date):
    """Return (splits_by_ticker, divs_by_ticker), filtered to (ANCHOR, last_date].

    splits_by_ticker[ticker] = list of (ex_ts, split_from, split_to)
    divs_by_ticker[ticker]   = list of (ex_ts, cash_amount)
    Deduped on (ticker, ex_date); both sorted by ex-date.
    """
    last_date = pd.Timestamp(last_date)
    ca = os.path.join(paths.POLYGON_RAW, "corporate_actions")

    with open(os.path.join(ca, "splits.json"), "r", encoding="utf-8") as f:
        splits = pd.DataFrame(json.load(f))
    with open(os.path.join(ca, "dividends.json"), "r", encoding="utf-8") as f:
        divs = pd.DataFrame(json.load(f))

    sb, db = {}, {}
    if not splits.empty:
        splits["ex"] = pd.to_datetime(splits["execution_date"])
        splits = splits[(splits["ex"] > paths.ANCHOR) & (splits["ex"] <= last_date)]
        splits = splits.drop_duplicates(["ticker", "execution_date"])
        for tk, g in splits.groupby("ticker"):
            sb[tk] = sorted((r.ex, float(r.split_from), float(r.split_to))
                            for r in g.itertuples())
    if not divs.empty:
        divs["ex"] = pd.to_datetime(divs["ex_dividend_date"])
        divs = divs[(divs["ex"] > paths.ANCHOR) & (divs["ex"] <= last_date)]
        divs = divs[divs["cash_amount"].astype(float) > 0]
        divs = divs.drop_duplicates(["ticker", "ex_dividend_date"])
        for tk, g in divs.groupby("ticker"):
            db[tk] = sorted((r.ex, float(r.cash_amount)) for r in g.itertuples())
    return sb, db


def build_factors(dates, raw_close, splits, divs):
    """Build per-date price & volume factors for one ticker.

    dates      : sorted list/Index of patch-date Timestamps (date > ANCHOR).
    raw_close  : dict {Timestamp -> raw close} covering dates AND the trading day
                 before each ex-date (incl. the 04-22 anchor) for dividend C.
    splits/divs: lists from load_corporate_actions for this ticker (may be []).

    Returns (price_factor: pd.Series, volume_factor: pd.Series, method: str,
             warnings: list[dict]).
    """
    dates = pd.DatetimeIndex(sorted(dates))
    warnings = []
    used_split = used_div = False

    # event multipliers keyed by ex-date
    price_events = {}   # ex_ts -> multiplier on price for dates >= ex
    vol_events = {}     # ex_ts -> multiplier on volume for dates >= ex

    for ex, f, t in splits:
        if f <= 0 or t <= 0:
            warnings.append({"type": "split_bad", "ex": str(ex.date()),
                             "split_from": f, "split_to": t})
            continue
        ratio = t / f
        if ratio >= SPLIT_RATIO_WARN or ratio <= 1.0 / SPLIT_RATIO_WARN:
            warnings.append({"type": "split_extreme", "ex": str(ex.date()),
                             "ratio": ratio})
        price_events[ex] = price_events.get(ex, 1.0) * ratio
        vol_events[ex] = vol_events.get(ex, 1.0) * (f / t)
        used_split = True

    # dividends need the raw close on the trading day BEFORE ex-date
    rc = pd.Series(raw_close).sort_index()
    for ex, d in divs:
        prior = rc.loc[rc.index < ex]
        if prior.empty or prior.iloc[-1] <= 0:
            warnings.append({"type": "div_no_prevclose", "ex": str(ex.date()), "cash": d})
            continue
        C = float(prior.iloc[-1])
        frac = d / C
        if frac > DIV_FAIL:
            warnings.append({"type": "div_fail", "ex": str(ex.date()),
                             "cash": d, "prev_close": C, "frac": frac})
            continue
        if frac > DIV_WARN:
            warnings.append({"type": "div_large", "ex": str(ex.date()),
                             "cash": d, "prev_close": C, "frac": frac})
        price_events[ex] = price_events.get(ex, 1.0) * (1.0 + frac)
        used_div = True

    # accumulate cumulative product over patch dates
    pf = pd.Series(1.0, index=dates)
    vf = pd.Series(1.0, index=dates)
    for ex in sorted(price_events):
        pf.loc[dates >= ex] *= price_events[ex]
    for ex in sorted(vol_events):
        vf.loc[dates >= ex] *= vol_events[ex]

    method = ("split+dividend" if used_split and used_div else
              "split" if used_split else
              "dividend" if used_div else "none")
    return pf, vf, method, warnings
