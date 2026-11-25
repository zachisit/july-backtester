"""helpers/target_weight_portfolio.py

Fully funded **target-weight portfolio** engine (issue #487).

The classic engine (:mod:`helpers.portfolio_simulations`) simulates one
independent position per symbol, sized as a fraction of equity, and reports a
closed-trade log. That shape cannot express a *basket* strategy whose signal is
a set of portfolio weights across several products held at once, with an
idle-cash sleeve, partial rebalances that never "close" a trade, and a cash
account that may only buy with settled money.

This module is that explicit, separate path. It never touches the single-asset
engine; strategies opt in by registering with
:func:`helpers.registry.register_target_weight`.

Accounting contract
-------------------
* **Fully funded, cash account.** No borrowing, no negative cash, no negative
  share counts, no short-sale proceeds. Inverse exposure is obtained by
  *holding* an inverse product, never by shorting one. Violations raise.
* **Information timing.** Target weights are produced from data up to and
  including the close of session ``t-1`` and evaluated at the **open of
  session t**. Session 0 has no prior signal: the whole account starts in the
  cash sleeve.
* **Rebalance rule.** Trade only when (a) it is the first session, (b) a held
  risk product has a zero target weight, (c) the sign of the signed exposure
  changes, (d) a risk product with a positive target is not held, or
  (e) ``|target exposure - current exposure| > band``. Exposure is
  ``sum(exposure_coeff[s] * value[s]) / NAV`` (``band_basis="exposure"``), or
  the largest absolute risk-weight drift when the strategy declares no
  exposure coefficients (``band_basis="weights"``).
* **Settlement.** Sale proceeds become a *receivable* that settles on the
  ``lag``-th eligible settlement session after the trade date. Three modes:

  - ``"settled_only"``: only settled cash may buy; receivables are part of NAV
    but cannot be spent. Stricter than Regulation T, so it understates what a
    real cash account can do (PR #489 review).
  - ``"gfv_aware"``: the Reg T cash-account rule. Risk-product purchases may
    use unsettled sale proceeds, but shares bought that way are *restricted*
    and are never sold before the proceeds that paid for them settle (selling
    them earlier is a good-faith violation). The cash sleeve is bought with
    settled cash only.
  - ``"immediate"``: reuses proceeds at the same open with no restriction. A
    non-deployable upper bound: it can commit good-faith violations.
* **Stale intentions are never executed.** Each open re-reads the latest
  prior-close target; there is no order queue.
* **Idle cash.** Every open, all settled cash left after the desired risk
  purchases is parked in the cash-sleeve product (e.g. SGOV) — that is the
  only "interest" the account earns; none is added on top.
* **Costs.** ``cost_bps[symbol]`` per traded notional on both sales and
  purchases, including the initial cash-sleeve purchase. Fractional units, no
  minimum commission, no terminal liquidation.
* **Prices.** The engine applies whatever Open/Close it is given and adds no
  cash flows. Distributions are therefore only included when the inputs are
  total-return adjusted; the runner records (and by default enforces) whether
  the data provider certifies that (see ``price_basis`` in
  :mod:`helpers.target_weight_runner`).

The trade loop is a generalisation of the frozen standalone ledger in
private-strategies PR #179 (``sgov_study.simulate_funded``); arithmetic order
is preserved so that a run on the same inputs reproduces it to machine
precision (see ``scripts/vix_evrp_parity.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

SETTLED_ONLY = "settled_only"
GFV_AWARE = "gfv_aware"
IMMEDIATE = "immediate"
_SETTLEMENT_MODES = (SETTLED_ONLY, GFV_AWARE, IMMEDIATE)
#: Modes that carry sale proceeds as receivables on a settlement calendar.
_RECEIVABLE_MODES = (SETTLED_ONLY, GFV_AWARE)

#: US equities: T+2 before the SEC T+1 cut-over on 2024-05-28, T+1 after.
DEFAULT_SETTLEMENT_RULES = (("1900-01-01", 2), ("2024-05-28", 1))


class FundingViolation(AssertionError):
    """Raised when a simulated account would borrow or hold a negative amount."""


@dataclass
class TargetWeightResult:
    """Output of :func:`simulate_target_weights`."""

    ledger: pd.DataFrame            # one row per session
    fills: pd.DataFrame             # one row per executed sale / purchase
    symbols: list                   # all held symbols, cash sleeve last
    cash_symbol: str
    initial_capital: float
    settlement: str
    settlement_map: dict = field(default_factory=dict)
    #: gfv_aware only: one row per restricted lot (Date, Symbol, Shares, FreeDate):
    #: shares bought with unsettled proceeds that may not be sold before FreeDate.
    restrictions: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(
        columns=["Date", "Symbol", "Shares", "FreeDate"]))

    @property
    def nav(self) -> pd.Series:
        return self.ledger["nav"]

    @property
    def returns(self) -> pd.Series:
        return self.ledger["return"]


# ---------------------------------------------------------------------------
# Settlement calendar
# ---------------------------------------------------------------------------

def settlement_lag(date: pd.Timestamp, rules=DEFAULT_SETTLEMENT_RULES) -> int:
    """Settlement lag (in eligible sessions) in force on *date*."""
    lag = None
    for effective, value in sorted(((pd.Timestamp(d), int(v)) for d, v in rules)):
        if date >= effective:
            lag = value
    if lag is None:
        raise ValueError(f"No settlement rule covers {date.date()}")
    if lag < 1:
        raise ValueError("settlement lag must be >= 1 session; use settlement='immediate' "
                         "for same-open reuse of proceeds")
    return lag


def xnys_sessions(start, end) -> pd.DatetimeIndex:
    """US equity sessions, including exchange-only closures and unscheduled holidays."""
    import exchange_calendars as xcals
    start, end = pd.Timestamp(start), pd.Timestamp(end)
    cal = xcals.get_calendar("XNYS", start=start - pd.Timedelta(days=7),
                             end=end + pd.Timedelta(days=7))
    dates = cal.sessions.tz_localize(None)
    return dates[(dates >= start) & (dates <= end)]


def settlement_dates(sessions: pd.DatetimeIndex, rules=DEFAULT_SETTLEMENT_RULES,
                     exclude_federal_holidays: bool = True) -> dict:
    """Map each trade date in *sessions* to the date its proceeds settle.

    Eligible settlement days are XNYS sessions minus
    US federal (bank) holidays when *exclude_federal_holidays*. Excluding bank
    holidays on which the exchange is open (Columbus Day, Veterans Day) is the
    conservative cash-account assumption used by the PR #179 study; it is not
    a certified broker clearing calendar.
    """
    sessions = pd.DatetimeIndex(sessions)
    if sessions.tz is not None:
        sessions = sessions.tz_localize(None)
    if sessions.empty:
        return {}
    last = sessions[-1] + pd.Timedelta(days=14 + 3 * max(int(lag) for _, lag in rules))
    eligible = xnys_sessions(sessions[0], last)
    if exclude_federal_holidays:
        # Note: USFederalHolidayCalendar moves a Saturday holiday to the
        # preceding Friday (e.g. 2021-06-18, 2021-12-31, 2023-11-10), which the
        # Federal Reserve does not observe. Those NYSE sessions are therefore
        # treated as non-settlement days: slightly more conservative than the
        # bank calendar, and kept for parity with the PR #179 study.
        from pandas.tseries.holiday import USFederalHolidayCalendar
        holidays = USFederalHolidayCalendar().holidays(start=sessions[0], end=eligible[-1])
        eligible = eligible[~eligible.isin(holidays)]
    result = {}
    for date in sessions:
        lag = settlement_lag(date, rules)
        future = eligible[eligible > date]
        result[date] = future[lag - 1]
    return result


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

def _validate_inputs(opens, closes, targets, risk_symbols, cash_symbol):
    symbols = list(risk_symbols) + [cash_symbol]
    if cash_symbol in risk_symbols:
        raise ValueError("cash_symbol must not also be a risk symbol")
    for name, frame in (("opens", opens), ("closes", closes)):
        missing = [s for s in symbols if s not in frame.columns]
        if missing:
            raise ValueError(f"{name} is missing columns {missing}")
    if not opens.index.equals(closes.index) or not opens.index.equals(targets.index):
        raise ValueError("opens, closes and targets must share one session index")
    if not opens.index.is_monotonic_increasing or not opens.index.is_unique:
        raise ValueError("session index must be unique and increasing")
    op = opens[symbols].to_numpy(dtype=float)
    cl = closes[symbols].to_numpy(dtype=float)
    if not np.isfinite(op).all() or not np.isfinite(cl).all() or (op <= 0).any() or (cl <= 0).any():
        raise ValueError("Open/Close prices must be finite and positive on every session")
    missing = [s for s in risk_symbols if s not in targets.columns]
    if missing:
        raise ValueError(f"targets is missing risk-symbol columns {missing}")
    if getattr(opens.index, "tz", None) is not None:
        raise ValueError("session index must be tz-naive dates")
    w = targets[list(risk_symbols)].to_numpy(dtype=float)
    if not np.isfinite(w).all():
        raise ValueError("target weights contain NaN/inf")
    if (w < 0).any():
        raise ValueError("negative target weights would require shorting; hold an inverse product instead")
    if (w.sum(axis=1) > 1 + 1e-12).any():
        raise ValueError("risk weights above 100% would require borrowing")
    return symbols, op, cl, w


def _validate_costs(cost_bps, symbols) -> np.ndarray:
    """Per-symbol fee rate (fraction of traded notional), in *symbols* order.

    A key that is not a traded symbol is refused rather than ignored: a
    mistyped override (``"vixy"``) would otherwise run at the default cost and
    look like a completed stress run. Fees must be finite, ``>= 0`` (a negative
    fee would create NAV) and below 100% of notional.
    """
    cost_bps = dict(cost_bps or {})
    unknown = [k for k in cost_bps if k not in symbols]
    if unknown:
        raise ValueError(f"cost_bps has keys that are not traded symbols: {unknown}. "
                         f"Traded symbols (case-sensitive): {list(symbols)}")
    try:
        bps = np.array([float(cost_bps.get(s, 0.0)) for s in symbols], dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"cost_bps values must be numbers of basis points: {exc}") from exc
    bad = [s for s, v in zip(symbols, bps) if not (np.isfinite(v) and 0 <= v < 10000)]
    if bad:
        raise ValueError(f"cost_bps must be finite, >= 0 and < 10000 bps; invalid for {bad}")
    return bps / 10000


def _pay_gfv(amount, cash, receivables, lots, unit_cost):
    """Fund a gfv_aware risk purchase: settled cash first, then receivables.

    Receivables are consumed earliest-settling first and reduced in place.
    The shares paid for with each receivable become a restricted lot that is
    free on that receivable's settlement date. ``unit_cost`` is the all-in
    cost of one share (price x (1 + fee)). The caller deducts the settled-cash
    part from ``cash``. Returns ``[(settlement_date, amount), ...]`` of the
    receivables used.
    """
    used_list = []
    rest = amount - min(max(cash, 0.0), amount)
    for rec in sorted(receivables, key=lambda r: r[0]):
        if rest <= 0:
            break
        used = min(rec[1], rest)
        if used <= 0:
            continue
        rec[1] -= used
        rest -= used
        lots.append([rec[0], used / unit_cost])
        used_list.append((rec[0], used))
    receivables[:] = [r for r in receivables if r[1] > 0]
    if rest > 1e-9 * max(amount, 1.0):
        raise FundingViolation("gfv_aware purchase exceeds settled cash plus receivables")
    return used_list


def simulate_target_weights(
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    targets: pd.DataFrame,
    risk_symbols: list,
    cash_symbol: str,
    *,
    exposure: dict | None = None,
    band: float = 0.02,
    cost_bps: dict | None = None,
    settlement: str = SETTLED_ONLY,
    settle_map: dict | None = None,
    settlement_rules=DEFAULT_SETTLEMENT_RULES,
    initial_capital: float = 1.0,
) -> TargetWeightResult:
    """Simulate a fully funded basket that tracks prior-close target weights.

    Parameters
    ----------
    opens, closes : DataFrame
        Adjusted Open/Close per symbol (columns) on every session (index).
        Every risk symbol and the cash sleeve must trade on every session.
    targets : DataFrame
        Target **risk** weights decided at each session's close, same index.
        The cash-sleeve weight is ``1 - sum(risk weights)``. Row ``t`` is
        executed at the open of row ``t+1``.
    risk_symbols : list
        Risk products, in purchase-priority order.
    cash_symbol : str
        The idle-cash product (bought with every dollar of settled cash).
    exposure : dict, optional
        Signed underlying exposure per unit of value (e.g. VIXY ``+1``, SVXY
        ``-0.5``). Selects ``band_basis="exposure"``; ``None`` bands on the
        largest risk-weight drift instead.
    band : float
        Rebalance tolerance (0.02 = 2 percentage points).
    cost_bps : dict
        Per-symbol cost in basis points of traded notional (default 0). Keys
        must be traded symbols; values finite, ``>= 0`` and ``< 10000``.
    settlement : "settled_only" | "gfv_aware" | "immediate"
    settle_map : dict, optional
        Precomputed ``{trade_date: settlement_date}``; derived from the session
        calendar and *settlement_rules* when omitted.
    initial_capital : float
        Starting cash, all of it placed in the cash sleeve on session 0.
    """
    if settlement not in _SETTLEMENT_MODES:
        raise ValueError(f"settlement must be one of {_SETTLEMENT_MODES}, got {settlement!r}")
    if not (np.isfinite(initial_capital) and initial_capital > 0):
        raise ValueError("initial_capital must be positive and finite")
    if not (np.isfinite(band) and band >= 0):
        raise ValueError("band must be finite and >= 0")
    risk_symbols = list(risk_symbols)
    symbols, op, cl, risk_w = _validate_inputs(opens, closes, targets, risk_symbols, cash_symbol)
    dates = opens.index
    n_risk = len(risk_symbols)
    fees = _validate_costs(cost_bps, symbols)
    coeffs = None
    if exposure is not None:
        missing = [s for s in risk_symbols if not float(exposure.get(s, 0.0))]
        if missing:
            raise ValueError(f"exposure must give every risk symbol a non-zero coefficient; "
                             f"missing/zero for {missing}. Use exposure=None to band on weights.")
        if ((risk_w > 0).sum(axis=1) > 1).any():
            raise ValueError("band_basis='exposure' needs at most one risk product targeted per "
                             "session (otherwise exposure does not identify the basket); "
                             "use exposure=None to band on per-product weights")
        coeffs = [float(exposure.get(s, 0.0)) for s in symbols]
    if settlement in _RECEIVABLE_MODES and settle_map is None:
        settle_map = settlement_dates(dates, settlement_rules)
    settle_map = settle_map or {}

    scale = float(initial_capital)
    tiny = 1e-14 * scale

    def _exposure(values, total):
        acc = 0.0
        for c, v in zip(coeffs, values):
            acc += c * v
        return float(acc) / total

    def _basket(i):
        if i == 0:
            w = np.zeros(len(symbols))
        else:
            w = np.zeros(len(symbols))
            w[:n_risk] = risk_w[i - 1]
        w[-1] = 1 - w[:n_risk].sum()
        if w.min() < 0 or not np.isfinite(w).all():
            raise FundingViolation("Basket would require leverage")
        return w

    gfv = settlement == GFV_AWARE
    q = np.zeros(len(symbols))
    # gfv_aware: per risk product, [free_date, shares] lots bought with unsettled
    # proceeds. They may not be sold before free_date (good-faith violation).
    restricted: list = [[] for _ in range(n_risk)]
    cash, previous = scale, scale
    receivables: list = []
    rows, fills, lot_log = [], [], []
    for i, date in enumerate(dates):
        due = sum(value for when, value in receivables if when <= date)
        cash += due
        receivables = [[when, value] for when, value in receivables if when > date]
        pending = sum(value for _, value in receivables)
        if gfv:
            for j in range(n_risk):
                restricted[j] = [lot for lot in restricted[j] if lot[0] > date]
        old = q * op[i]
        before = float(old.sum()) + cash + pending
        weights = _basket(i)
        if coeffs is not None:
            target = _exposure(weights, 1.0)
            current = _exposure(old, before)
            drift_trigger = np.sign(target) != np.sign(current) or abs(target - current) > band
        else:
            target = float(weights[:n_risk].sum())
            current = float(old[:n_risk].sum()) / before
            drift = np.abs(weights[:n_risk] - old[:n_risk] / before)
            drift_trigger = bool(n_risk and drift.max() > band)
        product_exit = bool(np.any((q[:n_risk] > 0) & (weights[:n_risk] == 0)))
        product_entry = bool(np.any((q[:n_risk] == 0) & (weights[:n_risk] > 0)))
        rebalance = i == 0 or product_exit or product_entry or drift_trigger
        cost = turnover = 0.0
        if rebalance:
            # Plan the allocation on post-cost NAV; purchases below are still
            # limited to settled cash.
            after = before
            for _ in range(20):
                after = before - float((fees * np.abs(weights * after - old)).sum())
            desired_values = weights * after
            sells = np.maximum(old - desired_values, 0.0)
            for j, sale in enumerate(sells):
                full_exit = bool(weights[j] == 0)
                if gfv and j < n_risk and restricted[j]:
                    # Shares bought with still-unsettled proceeds cannot be sold yet.
                    locked = sum(shares for _, shares in restricted[j])
                    sale = min(sale, max(q[j] - locked, 0.0) * op[i, j])
                    full_exit = False
                if sale <= tiny:
                    if full_exit and q[j] > 0:
                        # Residual dust (value <= tiny) of a product being exited:
                        # clear it, otherwise "held with a zero target" fires a
                        # rebalance on every later session (PR #489 review #1).
                        q[j] = 0.0
                    continue
                # A full exit sells every share; ``q - sale/price`` can leave
                # ~1e-17 shares of floating-point residue (PR #489 review #1).
                q[j] = 0.0 if full_exit else max(q[j] - sale / op[i, j], 0.0)
                expense = sale * fees[j]
                proceeds = sale - expense
                cost += expense
                turnover += sale / before
                settles = date if settlement == IMMEDIATE else settle_map[date]
                if settlement == IMMEDIATE:
                    cash += proceeds
                else:
                    receivables.append([settles, proceeds])
                fills.append({"Date": date, "Symbol": symbols[j], "Side": "SELL",
                              "Shares": sale / op[i, j], "Price": op[i, j], "Notional": sale,
                              "Cost": expense, "NetCash": proceeds, "SettlementDate": settles,
                              "Reason": "rebalance"})
            # Desired risk holdings have priority over parking idle cash.
            for j in range(n_risk):
                deficit = max(desired_values[j] - q[j] * op[i, j], 0.0)
                spendable = max(cash, 0)
                if gfv:
                    spendable += sum(value for _, value in receivables)
                purchase = min(deficit, spendable / (1 + fees[j]))
                if purchase:
                    q[j] += purchase / op[i, j]
                    unsettled_used = []
                    if gfv:
                        unsettled_used = _pay_gfv(purchase * (1 + fees[j]), cash, receivables, restricted[j],
                                 (1 + fees[j]) * op[i, j])
                        cash = max(cash, 0) - min(max(cash, 0), purchase * (1 + fees[j]))
                        lot_log.extend({"Date": date, "Symbol": symbols[j], "FreeDate": when,
                                        "Shares": amt / ((1 + fees[j]) * op[i, j])}
                                       for when, amt in unsettled_used)
                    else:
                        cash -= purchase * (1 + fees[j])
                    cost += purchase * fees[j]
                    turnover += purchase / before
                    # The arithmetic above is kept for every non-zero amount (frozen-ledger
                    # parity); only amounts above the dust threshold are fills, as for
                    # sales and cash parking.
                    if purchase > tiny:
                        fills.append({"Date": date, "Symbol": symbols[j], "Side": "BUY",
                                      "Shares": purchase / op[i, j], "Price": op[i, j],
                                      "Notional": purchase, "Cost": purchase * fees[j],
                                      "NetCash": -purchase * (1 + fees[j]), "SettlementDate": date,
                                      "Reason": "rebalance",
                                      "UnsettledFunding": float(sum(a for _, a in unsettled_used)),
                                      "RestrictedUntil": (max(d for d, _ in unsettled_used)
                                                          if unsettled_used else pd.NaT)})
        # Every dollar of settled cash goes to the cash sleeve; receivables wait.
        k = len(symbols) - 1
        purchase = max(cash, 0) / (1 + fees[k])
        q[k] += purchase / op[i, k]
        cash -= purchase * (1 + fees[k])
        cost += purchase * fees[k]
        turnover += purchase / before
        if purchase > tiny:
            fills.append({"Date": date, "Symbol": symbols[k], "Side": "BUY",
                          "Shares": purchase / op[i, k], "Price": op[i, k], "Notional": purchase,
                          "Cost": purchase * fees[k], "NetCash": -purchase * (1 + fees[k]),
                          "SettlementDate": date, "Reason": "park_cash"})
        pending = sum(value for _, value in receivables)
        if cash < -1e-12 * scale or (q < -1e-12).any() or pending < -1e-12 * scale:
            raise FundingViolation(f"{date.date()}: borrowing or short holdings are forbidden")
        cash = max(cash, 0.0)
        after_open = float((q * op[i]).sum()) + cash + pending
        if not np.isclose(after_open, before - cost, rtol=1e-11, atol=1e-12 * scale):
            raise FundingViolation(f"{date.date()}: open is not self-financing "
                                   f"({after_open!r} != {before - cost!r})")
        if coeffs is not None:
            executed = _exposure(q * op[i], after_open)
        else:
            executed = float((q[:n_risk] * op[i, :n_risk]).sum()) / after_open
        values = q * cl[i]
        nav = float(values.sum()) + cash + pending
        close_exposure = (_exposure(values, nav) if coeffs is not None
                          else float(values[:n_risk].sum()) / nav)
        row = {"date": date, "nav": nav, "return": nav / previous - 1,
               "target": target, "exposure_open_before": current,
               "exposure_open_after": executed, "exposure_close": close_exposure,
               "rebalanced": bool(rebalance),
               "target_unfilled_at_open": abs(executed - target) > band,
               "cash": cash, "unsettled": pending, "unsettled_weight": pending / nav,
               "cost": cost, "turnover": turnover}
        for j, s in enumerate(symbols):
            row[f"{s}_shares"] = q[j]
        for j, s in enumerate(symbols):
            row[f"{s}_value"] = values[j]
        for j, s in enumerate(symbols):
            row[f"{s}_weight"] = values[j] / nav
        for j, s in enumerate(symbols):
            row[f"{s}_target_weight"] = weights[j]
        rows.append(row)
        previous = nav
    ledger = pd.DataFrame(rows).set_index("date")
    # UnsettledFunding / RestrictedUntil (gfv_aware only): how much of a purchase
    # was paid with unsettled proceeds, and the latest date those shares free up.
    fill_cols = ["Date", "Symbol", "Side", "Shares", "Price", "Notional", "Cost",
                 "NetCash", "SettlementDate", "Reason", "UnsettledFunding", "RestrictedUntil"]
    fills_df = pd.DataFrame(fills, columns=fill_cols)
    return TargetWeightResult(ledger=ledger, fills=fills_df, symbols=symbols,
                              cash_symbol=cash_symbol, initial_capital=scale,
                              settlement=settlement,
                              settlement_map=dict(settle_map) if settlement in _RECEIVABLE_MODES else {},
                              restrictions=pd.DataFrame(lot_log, columns=["Date", "Symbol", "Shares", "FreeDate"]))


# ---------------------------------------------------------------------------
# Benchmarks and metrics
# ---------------------------------------------------------------------------

def buy_and_hold_returns(open_: pd.Series, close: pd.Series, entry_cost_bps: float = 0.0) -> pd.Series:
    """Daily returns of buying at the first session's open and holding.

    Session 0 is ``close/open/(1+cost) - 1``; later sessions are close-to-close.
    """
    if not open_.index.equals(close.index):
        raise ValueError("open/close misaligned")
    out = close.pct_change(fill_method=None)
    out.iloc[0] = close.iloc[0] / open_.iloc[0] / (1 + entry_cost_bps / 10000) - 1
    return out


def performance_metrics(returns: pd.Series, cash_reference: pd.Series | None = None,
                        periods_per_year: int = 252, risk_free_rate: float = 0.02) -> dict:
    """Return-series metrics, matching the PR #179 study's definitions.

    Drawdown is measured against ``max(1, running peak)`` of the growth path so
    an initial cost is a drawdown from the starting capital. CAGR annualises by
    ``sessions / periods_per_year``. ``sharpe_cash_reference`` is the
    annualised mean excess return over *cash_reference* divided by the
    annualised excess volatility. ``sharpe_rf`` uses *risk_free_rate* (the
    run's ``risk_free_rate`` config); ``sharpe_rf2`` is kept at a fixed 2% for
    parity with the study's ``metrics.csv``.
    """
    returns = returns.astype(float)
    wealth = (1 + returns).cumprod()
    years = len(returns) / periods_per_year
    vol = returns.std(ddof=1) * np.sqrt(periods_per_year)
    dd = wealth / wealth.cummax().clip(lower=1) - 1
    cagr = float(wealth.iloc[-1] ** (1 / years) - 1) if years > 0 else float("nan")
    out = {"total_return": float(wealth.iloc[-1] - 1), "cagr": cagr,
           "volatility": float(vol), "max_drawdown": float(dd.min()),
           "sharpe_rf0": float(returns.mean() * periods_per_year / vol) if vol else None,
           "sharpe_rf2": float((returns.mean() * periods_per_year - .02) / vol) if vol else None,
           "sharpe_rf": (float((returns.mean() * periods_per_year - risk_free_rate) / vol)
                         if vol else None),
           "risk_free_rate": float(risk_free_rate),
           "calmar": cagr / abs(float(dd.min())) if dd.min() else None,
           "observations": int(len(returns)),
           "start": str(returns.index[0].date()), "end": str(returns.index[-1].date())}
    if cash_reference is not None:
        cash_reference = cash_reference.reindex(returns.index)
        excess = returns - cash_reference
        evol = excess.std(ddof=1) * np.sqrt(periods_per_year)
        out["sharpe_cash_reference"] = (float(excess.mean() * periods_per_year / evol)
                                        if evol > 1e-10 else None)
        out["annualized_excess_mean"] = float(excess.mean() * periods_per_year)
    return out


def drawdown_series(nav: pd.Series, initial_capital: float) -> pd.Series:
    """Fractional drawdown of *nav* from its running peak, floored at *initial_capital*."""
    return nav / nav.cummax().clip(lower=float(initial_capital)) - 1
