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
  ``lag``-th eligible settlement session after the trade date
  (``settlement="settled_only"``). Only settled cash may buy. Receivables are
  part of NAV but cannot be spent. ``settlement="immediate"`` is a benchmark
  that reuses proceeds the same open; it is not a cash-account result.
* **Stale intentions are never executed.** Each open re-reads the latest
  prior-close target; there is no order queue.
* **Idle cash.** Every open, all settled cash left after the desired risk
  purchases is parked in the cash-sleeve product (e.g. SGOV) — that is the
  only "interest" the account earns; none is added on top.
* **Costs.** ``cost_bps[symbol]`` per traded notional on both sales and
  purchases, including the initial cash-sleeve purchase. Fractional units, no
  minimum commission, no terminal liquidation.
* **Prices.** Adjusted (total-return) Open/Close are used, so distributions are
  modelled as reinvested in the unit price — not as a payment-date cash flow.

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
IMMEDIATE = "immediate"
_SETTLEMENT_MODES = (SETTLED_ONLY, IMMEDIATE)

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


def settlement_dates(sessions: pd.DatetimeIndex, rules=DEFAULT_SETTLEMENT_RULES,
                     exclude_federal_holidays: bool = True) -> dict:
    """Map each trade date in *sessions* to the date its proceeds settle.

    Eligible settlement days are the trading sessions themselves (the data's
    own calendar), extended past the last session with business days, minus
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
    extension = pd.bdate_range(sessions[-1] + pd.Timedelta(days=1), periods=30)
    eligible = sessions.union(extension)
    if exclude_federal_holidays:
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
        Per-symbol cost in basis points of traded notional (default 0).
    settlement : "settled_only" | "immediate"
    settle_map : dict, optional
        Precomputed ``{trade_date: settlement_date}``; derived from the session
        calendar and *settlement_rules* when omitted.
    initial_capital : float
        Starting cash, all of it placed in the cash sleeve on session 0.
    """
    if settlement not in _SETTLEMENT_MODES:
        raise ValueError(f"settlement must be one of {_SETTLEMENT_MODES}, got {settlement!r}")
    if not (initial_capital > 0):
        raise ValueError("initial_capital must be positive")
    if band < 0:
        raise ValueError("band must be >= 0")
    risk_symbols = list(risk_symbols)
    symbols, op, cl, risk_w = _validate_inputs(opens, closes, targets, risk_symbols, cash_symbol)
    dates = opens.index
    n_risk = len(risk_symbols)
    cost_bps = cost_bps or {}
    fees = np.array([float(cost_bps.get(s, 0.0)) for s in symbols]) / 10000
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
    if settlement == SETTLED_ONLY and settle_map is None:
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

    q = np.zeros(len(symbols))
    cash, previous = scale, scale
    receivables: list = []
    rows, fills = [], []
    for i, date in enumerate(dates):
        due = sum(value for when, value in receivables if when <= date)
        cash += due
        receivables = [(when, value) for when, value in receivables if when > date]
        pending = sum(value for _, value in receivables)
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
                if sale <= tiny:
                    continue
                q[j] = max(q[j] - sale / op[i, j], 0.0)
                expense = sale * fees[j]
                proceeds = sale - expense
                cost += expense
                turnover += sale / before
                settles = date if settlement == IMMEDIATE else settle_map[date]
                if settlement == IMMEDIATE:
                    cash += proceeds
                else:
                    receivables.append((settles, proceeds))
                fills.append({"Date": date, "Symbol": symbols[j], "Side": "SELL",
                              "Shares": sale / op[i, j], "Price": op[i, j], "Notional": sale,
                              "Cost": expense, "NetCash": proceeds, "SettlementDate": settles,
                              "Reason": "rebalance"})
            # Desired risk holdings have priority over parking idle cash.
            for j in range(n_risk):
                deficit = max(desired_values[j] - q[j] * op[i, j], 0.0)
                purchase = min(deficit, max(cash, 0) / (1 + fees[j]))
                if purchase:
                    q[j] += purchase / op[i, j]
                    cash -= purchase * (1 + fees[j])
                    cost += purchase * fees[j]
                    turnover += purchase / before
                    fills.append({"Date": date, "Symbol": symbols[j], "Side": "BUY",
                                  "Shares": purchase / op[i, j], "Price": op[i, j],
                                  "Notional": purchase, "Cost": purchase * fees[j],
                                  "NetCash": -purchase * (1 + fees[j]), "SettlementDate": date,
                                  "Reason": "rebalance"})
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
    fill_cols = ["Date", "Symbol", "Side", "Shares", "Price", "Notional", "Cost",
                 "NetCash", "SettlementDate", "Reason"]
    fills_df = pd.DataFrame(fills, columns=fill_cols)
    return TargetWeightResult(ledger=ledger, fills=fills_df, symbols=symbols,
                              cash_symbol=cash_symbol, initial_capital=scale,
                              settlement=settlement,
                              settlement_map=dict(settle_map) if settlement == SETTLED_ONLY else {})


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
                        periods_per_year: int = 252) -> dict:
    """Return-series metrics, matching the PR #179 study's definitions.

    Drawdown is measured against ``max(1, running peak)`` of the growth path so
    an initial cost is a drawdown from the starting capital. CAGR annualises by
    ``sessions / periods_per_year``. ``sharpe_cash_reference`` is the
    annualised mean excess return over *cash_reference* divided by the
    annualised excess volatility.
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
