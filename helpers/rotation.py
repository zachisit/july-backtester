"""helpers/rotation.py

Cross-sectional **rotation** mechanism (issue #294).

The per-symbol ``Signal`` plugin answers "am I long *this* symbol right now?"
independently for every ticker. A rotation strategy is a fundamentally different
shape: at each rebalance it looks at the *whole* universe at once, **ranks** the
symbols against each other, and holds only the best N. The legacy engine cannot
express that — it runs every symbol in isolation with no cross-sectional view.

This module is the framework-owned MECHANISM for that shape. A rotation strategy
becomes **"a ranking function + config"** instead of a bespoke standalone script:

* the ranking function (the *alpha*) is a small pure callable — public generic
  examples live in ``custom_strategies/``; proprietary ones stay private;
* everything else — top-N selection, weighting, rebalance / trim / add
  mechanics, sizing, and **all cost / cash / MTM accounting** — is owned here and
  delegated to the tested primitives in :mod:`helpers.instruments`.

Design contract
---------------
* **Pure / stateless** — no globals, no I/O, no randomness. Everything comes in
  through ``data`` + ``config`` + the ranking function.
* **Scale-invariant** (issue #293). Every sizing decision is a *fraction of
  current equity*; nothing is an absolute dollar amount. Running the same
  rotation at ``initial_capital`` 100k vs 1M produces the same percentage
  returns and proportional share counts. There is no absolute-dollar position
  cap — the only cap, ``max_position_pct``, is relative.
* **No new cost math.** Fills, commission, share rounding, market value and
  margin all route through :mod:`helpers.instruments`; this module never
  hand-rolls slippage / commission arithmetic.
* **Long-only** by default; no short overlay.

The result dict is the SAME shape :func:`helpers.portfolio_simulations.run_portfolio_simulation`
returns (``trade_log``, ``portfolio_timeline``, ``trade_pnl_list``,
``initial_capital``, ``pnl_percent``, ``Trades`` + advanced metrics), so the
existing summary / reporting / WFA / MC layers consume a rotation result with no
special-casing.

Public API
----------
run_rotation(data, rank_fn, config, *, regime_gate=None, params=None) -> dict | None
run_rotation_from_config(data, config) -> dict | None   (honors rotation.enabled)
build_rebalance_dates(data, rebalance_days) -> list[pd.Timestamp]
WEIGHTING_SCHEMES -> dict[str, Callable]     (pluggable weighting registry)

Deferred integration (finding F7)
---------------------------------
The ``main.py`` multiprocessing Pool / ``init_worker`` orchestration is
deliberately NOT wired to auto-run rotation strategies — that path is the
Do-Not-Touch engine architecture and is out of scope here. Consequently the
``rotation.enabled`` and ``rotation.rank_strategy`` config keys are not honored
by a bare ``python main.py`` run yet. They are NOT silently inert, though:
:func:`run_rotation_from_config` is the caller-facing, non-Pool entry point that
reads both keys, resolves the named ``@register_rotation`` plugin, and runs it —
so a script or notebook can drive the capability today with the config it
already declares. Full Pool wiring is a tracked follow-up.
"""

from __future__ import annotations

import logging
from typing import Callable

import numpy as np
import pandas as pd

from helpers import instruments as _inst

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config defaults (mirrored in config.py SECTION 30 / config_validator.KNOWN_KEYS)
# ---------------------------------------------------------------------------
_DEFAULT_ROTATION = {
    "enabled": False,
    "rank_strategy": None,   # name of a registered rotation plugin (used by callers)
    "top_n": 5,
    "rebalance_days": 21,    # forced rebalance interval, in trading days
    "weighting": "equal",    # key into WEIGHTING_SCHEMES
    "sell_buffer_rank": 0,    # hysteresis: keep a holding while rank <= top_n + this
    "drift_trim_pct": 0.0,    # only trim/add when |weight - target| > this fraction
}


# Cash-affordability comparisons must not trip on floating-point noise at the
# fully-invested boundary (weights summing to exactly 1.0). Without a tolerance a
# final buy can clamp at one capital scale but not another purely from FP
# rounding, breaking scale-invariance (issue #293). This tolerance is a tiny
# absolute floor plus a relative term, both far below any economically-meaningful
# shortfall and far above FP residue at any scale.
def _over_budget(cost: float, cash: float) -> bool:
    return cost - cash > 1e-6 + 1e-9 * abs(cash)


def get_rotation_config(config: dict) -> dict:
    """Return the ``rotation`` sub-dict merged over :data:`_DEFAULT_ROTATION`."""
    user = dict(config.get("rotation", {}) or {})
    merged = {**_DEFAULT_ROTATION, **user}
    return merged


# ---------------------------------------------------------------------------
# Weighting schemes (pluggable). A scheme maps the selected symbols to target
# weights (fractions of equity). Callers may register more by mutating the dict.
# ---------------------------------------------------------------------------
def _equal_weights(selected: list[str], data: dict, rebalance_date, config: dict) -> dict:
    """Equal weight across the selected names: ``1 / top_n`` each."""
    top_n = int(get_rotation_config(config).get("top_n", 5)) or 1
    w = 1.0 / top_n
    return {sym: w for sym in selected}


def _fixed_alloc_weights(selected: list[str], data: dict, rebalance_date, config: dict) -> dict:
    """Each name gets ``allocation_per_trade`` of equity — reuses the existing
    fixed-allocation knob rather than reinventing a sizing layer."""
    alloc = float(config.get("allocation_per_trade", 0.10))
    return {sym: alloc for sym in selected}


WEIGHTING_SCHEMES: dict[str, Callable] = {
    "equal": _equal_weights,
    "fixed_alloc": _fixed_alloc_weights,
}


# ---------------------------------------------------------------------------
# Rebalance calendar
# ---------------------------------------------------------------------------
def build_rebalance_dates(data: dict, rebalance_days: int) -> list:
    """Every ``rebalance_days``-th trading date across the union of all symbols.

    The union of per-symbol indices is the master trading calendar; we sample it
    at a fixed stride so the cadence is deterministic and provider-agnostic. The
    final date is always included so the last window is not silently dropped.
    """
    all_dates: set = set()
    for df in data.values():
        if df is not None and not df.empty:
            all_dates.update(df.index.tolist())
    trading_dates = sorted(all_dates)
    if not trading_dates:
        return []

    stride = max(1, int(rebalance_days))
    dates = trading_dates[::stride]
    if trading_dates[-1] not in dates:
        dates.append(trading_dates[-1])
    return dates


# ---------------------------------------------------------------------------
# Ranking normalisation
# ---------------------------------------------------------------------------
def _normalise_ranking(raw) -> list:
    """Coerce a ranking function's output into an ordered list of symbols.

    Accepts either an already-ordered ``list``/``tuple`` (best first) or a
    ``dict``/``pd.Series`` of ``symbol -> score`` (sorted descending here).
    ``None`` / empty -> ``[]``.
    """
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [k for k, _ in sorted(raw.items(), key=lambda kv: kv[1], reverse=True)]
    if isinstance(raw, pd.Series):
        return list(raw.sort_values(ascending=False).index)
    return list(raw)


def _price(df: pd.DataFrame, date, col: str = "Close"):
    """Price for *symbol* on *date*; NaN when the bar is absent."""
    if df is None or date not in df.index:
        return np.nan
    return float(df.at[date, col])


def _carry_forward_close(df: pd.DataFrame, date) -> float:
    """Close on *date*, or the most recent prior Close when *date* has no bar
    (calendar gap). NaN only when *date* precedes the symbol's first bar.

    This is the single carry-forward rule shared by the intraday MTM (`_mtm`)
    and the daily equity curve (`_build_daily_timeline`) so the two never
    disagree (finding F3). Falling back to the entry price — as an earlier draft
    did — made the two equity computations diverge on a missing bar.
    """
    if df is None:
        return np.nan
    if date in df.index:
        return float(df.at[date, "Close"])
    prior = df.index[df.index <= date]
    return float(df.at[prior[-1], "Close"]) if len(prior) else np.nan


# ---------------------------------------------------------------------------
# Core rotation loop
# ---------------------------------------------------------------------------
def run_rotation(
    data: dict,
    rank_fn: Callable,
    config: dict,
    *,
    regime_gate: Callable | None = None,
    params: dict | None = None,
) -> dict | None:
    """Run a cross-sectional rotation backtest.

    Parameters
    ----------
    data : dict[str, pd.DataFrame]
        Per-symbol OHLCV frames (``Open/High/Low/Close`` required), each indexed
        by a ``DatetimeIndex``.
    rank_fn : Callable
        ``rank_fn(data, rebalance_date, **params) -> ranking``. ``ranking`` is an
        ordered list (best first) or a ``{symbol: score}`` dict / Series. Only
        symbols present in ``data`` are honoured. The function must decide using
        data **up to and including** ``rebalance_date`` only — it must not read
        any bar after it. The framework enforces the fill side: decisions made on
        the signal bar are executed at the **next** trading bar's Open (no
        same-bar look-ahead — finding F1), mirroring the engine's
        ``execution_time="open"`` convention.
    config : dict
        The CONFIG dict. Read keys: ``rotation`` (see :data:`_DEFAULT_ROTATION`),
        ``max_position_pct``, ``initial_capital``, ``allocation_per_trade``, plus
        whatever :func:`helpers.instruments.resolve_instrument` consumes.
    regime_gate : Callable, optional
        ``regime_gate(data, rebalance_date) -> bool``. When it returns ``False``
        the book is fully liquidated to cash for that rebalance (risk-off).
    params : dict, optional
        Static kwargs forwarded to ``rank_fn``.

    Returns
    -------
    dict | None
        Pipeline-shaped result dict, or ``None`` when no trade ever closed.
    """
    params = dict(params or {})
    rcfg = get_rotation_config(config)
    top_n = max(1, int(rcfg.get("top_n", 5)))
    sell_buffer = max(0, int(rcfg.get("sell_buffer_rank", 0)))
    drift_trim = max(0.0, float(rcfg.get("drift_trim_pct", 0.0)))
    weighting = rcfg.get("weighting", "equal")
    rebalance_days = int(rcfg.get("rebalance_days", 21))
    # Scale-invariant relative cap only (issue #293) — NO absolute-dollar cap.
    max_pos_pct = float(config.get("max_position_pct", 1.0))
    initial_capital = float(config.get("initial_capital", 100_000.0))

    weight_fn = WEIGHTING_SCHEMES.get(weighting)
    if weight_fn is None:
        logger.warning(
            "[WARNING] Unknown rotation weighting '%s' — falling back to 'equal'.",
            weighting,
        )
        weight_fn = _equal_weights

    if not data:
        return None

    # Per-symbol instrument metadata (tested cost/accounting primitives).
    insts = {sym: _inst.resolve_instrument(sym, config) for sym in data}

    rebalance_dates = build_rebalance_dates(data, rebalance_days)
    if not rebalance_dates:
        return None

    # Master daily calendar for the equity curve.
    all_dates = sorted({d for df in data.values()
                        if df is not None and not df.empty
                        for d in df.index.tolist()})

    cash = initial_capital
    positions: dict = {}   # sym -> {shares, entry_price, entry_date, cost_basis}
    trade_log: list = []
    trade_counter = 0
    # (date, cash, {sym: shares}) after each rebalance — the daily equity curve is
    # reconstructed from these: cash + live MTM changes only at rebalance dates.
    snapshots: list = []

    def _mtm(date, col: str = "Close") -> float:
        """Equity = cash + live position value at *date*. ``col`` selects the
        mark price: ``"Close"`` (curve MTM) or ``"Open"`` (execution-bar mark).
        Missing bars carry the last known Close forward — the same rule the daily
        equity curve uses — so the two never disagree (finding F3)."""
        total = cash
        for sym, pos in positions.items():
            p = _price(data[sym], date, col) if col != "Close" else np.nan
            if np.isnan(p):
                p = _carry_forward_close(data[sym], date)
            if np.isnan(p):
                p = pos["entry_price"]
            total += _inst.market_value(insts[sym], pos["shares"], p)
        return total

    def _do_sell(sym, exec_date, reason):
        nonlocal cash, trade_counter
        pos = positions[sym]
        inst = insts[sym]
        raw = _price(data[sym], exec_date, "Open")
        if np.isnan(raw) or raw <= 0:
            # The symbol has no bar at exec_date — its data ended mid-backtest
            # (delisting / provider dropout). Falling back to the same
            # carry-forward Close that _mtm / _do_close_mtm already use still
            # liquidates the position now, instead of leaving it an unkillable
            # zombie that free-rides on a frozen mark until End of Backtest.
            raw = _carry_forward_close(data[sym], exec_date)
            if np.isnan(raw) or raw <= 0:
                return
        exit_price = _inst.apply_slippage(inst, raw, "sell")
        shares = pos["shares"]
        commission = _inst.commission(inst, shares)
        proceeds = _inst.market_value(inst, shares, exit_price) - commission
        pv = inst.point_value
        net_pnl = (exit_price - pos["entry_price"]) * shares * pv - 2 * commission

        # MAE / MFE over the hold window (parallel to the engine's logic).
        window = data[sym].loc[pos["entry_date"]:exec_date]
        ep = pos["entry_price"]
        mae_pct = (window["Low"].min() - ep) / ep if not window.empty else 0.0
        mfe_pct = (window["High"].max() - ep) / ep if not window.empty else 0.0

        # No stop in a rotation -> 1% initial-risk proxy (engine convention).
        initial_risk = ep * 0.01
        r_multiple = (net_pnl / (initial_risk * shares * pv)
                      if initial_risk > 0 and shares > 0 else None)

        trade_counter += 1
        notional = _inst.notional(inst, shares, ep)
        trade_log.append({
            "Symbol": sym, "Trade": f"Long {trade_counter}",
            "EntryDate": pos["entry_date"].isoformat(), "EntryPrice": ep,
            "ExitDate": exec_date.isoformat(), "ExitPrice": exit_price,
            "Profit": net_pnl,
            "ProfitPct": net_pnl / notional if notional > 0 else 0.0,
            "Shares": shares, "is_win": 1 if net_pnl > 0 else 0,
            "HoldDuration": (exec_date - pos["entry_date"]).days,
            "MAE_pct": mae_pct, "MFE_pct": mfe_pct, "ExitReason": reason,
            "InitialRisk": initial_risk, "RMultiple": r_multiple,
        })
        cash += proceeds
        del positions[sym]

    def _do_buy(sym, exec_date, target_dollars):
        nonlocal cash
        inst = insts[sym]
        raw = _price(data[sym], exec_date, "Open")
        if np.isnan(raw) or raw <= 0 or target_dollars <= 0:
            return
        entry_price = _inst.apply_slippage(inst, raw, "buy")
        pv = inst.point_value
        raw_shares = target_dollars / (entry_price * pv)
        shares = _inst.round_units(inst, raw_shares)
        if shares <= 0:
            return
        commission = _inst.commission(inst, shares)
        total_cost = _inst.market_value(inst, shares, entry_price) + commission
        if _over_budget(total_cost, cash):
            # Trim to what cash allows (still scale-invariant).
            affordable = (cash - commission) / (entry_price * pv)
            shares = _inst.round_units(inst, affordable)
            if shares <= 0:
                return
            commission = _inst.commission(inst, shares)
            total_cost = _inst.market_value(inst, shares, entry_price) + commission
            if _over_budget(total_cost, cash):
                return
        cash -= total_cost
        positions[sym] = {
            "shares": shares, "entry_price": entry_price,
            "entry_date": exec_date, "cost_basis": total_cost,
        }

    def _do_add(sym, exec_date, target_dollars):
        """Top up an UNDER-weight holding back toward its target (drift add — the
        add side of trim/add, finding F5). Buys the share deficit at the exec bar's
        Open, subject to cash; blends the entry price share-weighted so the
        eventual close's PnL stays honest. No trade_log entry — an add is an entry,
        not a realised round trip; it folds into the position's eventual sale."""
        nonlocal cash
        pos = positions[sym]
        inst = insts[sym]
        raw = _price(data[sym], exec_date, "Open")
        if np.isnan(raw) or raw <= 0:
            return
        entry_price = _inst.apply_slippage(inst, raw, "buy")
        pv = inst.point_value
        cur_val = _inst.market_value(inst, pos["shares"], entry_price)
        deficit = target_dollars - cur_val
        if deficit <= 0:
            return
        add_shares = _inst.round_units(inst, deficit / (entry_price * pv))
        if add_shares <= 0:
            return
        commission = _inst.commission(inst, add_shares)
        add_cost = _inst.market_value(inst, add_shares, entry_price) + commission
        if _over_budget(add_cost, cash):
            affordable = (cash - commission) / (entry_price * pv)
            add_shares = _inst.round_units(inst, affordable)
            if add_shares <= 0:
                return
            commission = _inst.commission(inst, add_shares)
            add_cost = _inst.market_value(inst, add_shares, entry_price) + commission
            if _over_budget(add_cost, cash):
                return
        cash -= add_cost
        new_shares = pos["shares"] + add_shares
        pos["entry_price"] = (
            (pos["entry_price"] * pos["shares"] + entry_price * add_shares) / new_shares
        )
        pos["shares"] = new_shares
        pos["cost_basis"] += add_cost
        # entry_date stays the original (earliest) fill.

    def _do_trim(sym, exec_date, target_dollars):
        """Reduce an over-weight position back toward its target (partial sell)."""
        nonlocal cash, trade_counter
        pos = positions[sym]
        inst = insts[sym]
        raw = _price(data[sym], exec_date, "Open")
        if np.isnan(raw) or raw <= 0:
            return
        exit_price = _inst.apply_slippage(inst, raw, "sell")
        pv = inst.point_value
        current_val = _inst.market_value(inst, pos["shares"], exit_price)
        excess = current_val - target_dollars
        if excess <= 0:
            return
        sell_shares = _inst.round_units(inst, excess / (exit_price * pv))
        if sell_shares <= 0 or sell_shares >= pos["shares"]:
            return
        commission = _inst.commission(inst, sell_shares)
        proceeds = _inst.market_value(inst, sell_shares, exit_price) - commission
        # Reduce cost basis proportionally so the remaining position's PnL is honest.
        frac = sell_shares / pos["shares"]
        realized_basis = pos["cost_basis"] * frac
        net_pnl = proceeds - realized_basis
        ep = pos["entry_price"]
        initial_risk = ep * 0.01
        r_multiple = (net_pnl / (initial_risk * sell_shares * pv)
                      if initial_risk > 0 and sell_shares > 0 else None)
        trade_counter += 1
        notional = _inst.notional(inst, sell_shares, ep)
        trade_log.append({
            "Symbol": sym, "Trade": f"Trim {trade_counter}",
            "EntryDate": pos["entry_date"].isoformat(), "EntryPrice": ep,
            "ExitDate": exec_date.isoformat(), "ExitPrice": exit_price,
            "Profit": net_pnl,
            "ProfitPct": net_pnl / notional if notional > 0 else 0.0,
            "Shares": sell_shares, "is_win": 1 if net_pnl > 0 else 0,
            "HoldDuration": (exec_date - pos["entry_date"]).days,
            "MAE_pct": 0.0, "MFE_pct": 0.0, "ExitReason": "Rebalance Trim",
            "InitialRisk": initial_risk, "RMultiple": r_multiple,
        })
        cash += proceeds
        pos["shares"] -= sell_shares
        pos["cost_basis"] -= realized_basis

    def _do_close_mtm(sym, close_date, reason="End of Backtest"):
        """End-of-backtest mark-to-market close at the last Close — NOT a same-bar
        buy+sell round trip (finding F2). Parallel to the engine's EoB MTM: it
        records a trade for the log/metrics but does NOT touch cash (the daily
        equity curve already carries the open position's value to the last bar)."""
        nonlocal trade_counter
        pos = positions[sym]
        inst = insts[sym]
        last_close = _carry_forward_close(data[sym], close_date)
        if np.isnan(last_close) or last_close <= 0:
            del positions[sym]
            return
        exit_price = _inst.apply_slippage(inst, last_close, "sell")
        shares = pos["shares"]
        pv = inst.point_value
        commission = _inst.commission(inst, shares)
        net_pnl = (exit_price - pos["entry_price"]) * shares * pv - 2 * commission
        window = data[sym].loc[pos["entry_date"]:close_date]
        ep = pos["entry_price"]
        mae_pct = (window["Low"].min() - ep) / ep if not window.empty else 0.0
        mfe_pct = (window["High"].max() - ep) / ep if not window.empty else 0.0
        initial_risk = ep * 0.01
        r_multiple = (net_pnl / (initial_risk * shares * pv)
                      if initial_risk > 0 and shares > 0 else None)
        trade_counter += 1
        notional = _inst.notional(inst, shares, ep)
        trade_log.append({
            "Symbol": sym, "Trade": f"Long {trade_counter}",
            "EntryDate": pos["entry_date"].isoformat(), "EntryPrice": ep,
            "ExitDate": close_date.isoformat(), "ExitPrice": exit_price,
            "Profit": net_pnl,
            "ProfitPct": net_pnl / notional if notional > 0 else 0.0,
            "Shares": shares, "is_win": 1 if net_pnl > 0 else 0,
            "HoldDuration": (close_date - pos["entry_date"]).days,
            "MAE_pct": mae_pct, "MFE_pct": mfe_pct, "ExitReason": reason,
            "InitialRisk": initial_risk, "RMultiple": r_multiple,
        })
        del positions[sym]

    # Next-bar execution map (finding F1): a decision made on the signal bar is
    # filled at the FOLLOWING trading bar's Open, mirroring the engine's
    # execution_time="open" one-day lag. The terminal master bar has no next bar,
    # so a signal there executes nothing (and thus can create no zero-duration
    # round trip — finding F2).
    date_to_next = {all_dates[i]: all_dates[i + 1] for i in range(len(all_dates) - 1)}
    terminal_date = all_dates[-1]

    # Seed the equity curve before the first fill (fully in cash).
    snapshots.append((all_dates[0], cash, {}))

    # --- Rebalance loop -----------------------------------------------------
    for signal_date in rebalance_dates:
        exec_date = date_to_next.get(signal_date)
        if exec_date is None:
            # Signal on the last bar -> nothing to execute. The end-of-backtest
            # MTM close below marks any open book to that bar's Close.
            continue

        # Decisions read data strictly up to and including signal_date; fills land
        # on exec_date (the next bar). rank_fn is contractually bound to the
        # signal bar, so there is no look-ahead into the execution bar.
        risk_on = True
        if regime_gate is not None:
            try:
                risk_on = bool(regime_gate(data, signal_date))
            except Exception as exc:  # a bad gate must not corrupt the whole run
                logger.warning("[WARNING] rotation regime_gate raised: %s", exc)
                risk_on = True

        if not risk_on:
            # Risk-off: liquidate everything to cash at the execution bar.
            for sym in list(positions.keys()):
                _do_sell(sym, exec_date, "Regime Off")
            snapshots.append((exec_date, cash, {}))
            continue

        raw_ranking = rank_fn(data, signal_date, **params)
        ranking = [s for s in _normalise_ranking(raw_ranking) if s in data]
        target = ranking[:top_n]
        keep_set = set(ranking[:top_n + sell_buffer])  # hysteresis band

        # 1. Sell holdings that fell out of the keep band (or vanished from rank).
        for sym in list(positions.keys()):
            if sym not in keep_set:
                _do_sell(sym, exec_date, "Rank Drop")

        # 2. Final desired book = kept holdings (all now within the keep band) plus
        #    new top-ranked names filling the remaining slots up to top_n. This set
        #    is EXACTLY what will be held, so every kept name is weighted and
        #    drift-controlled, and target weights cannot silently exceed 1 (F4).
        kept = list(positions.keys())
        slots = max(0, top_n - len(kept))
        new_names = [s for s in target if s not in positions][:slots]
        selected = kept + new_names

        # 3. Coherent target weights: cap each at max_position_pct, then normalise
        #    so the book sums to <= 1 (no silent cash-clamp underweighting — F4).
        weights = weight_fn(selected, data, signal_date, config)
        weights = {s: min(w, max_pos_pct) for s, w in weights.items()}
        total_w = sum(weights.values())
        if total_w > 1.0:
            weights = {s: w / total_w for s, w in weights.items()}

        # New positions cannot be opened on the terminal bar — they could not be
        # held for even one bar and would be immediate friction (finding F2).
        allow_new = exec_date != terminal_date

        # Mark equity at the EXECUTION bar (not a future bar) for sizing (F1).
        equity_now = _mtm(exec_date, "Open")

        # 4. Drift control on existing holdings: trim over-weight, top up under-weight.
        # Trims run to completion before any add is attempted. Trims and adds
        # were previously interleaved in ranking-order, so an add early in the
        # pass could be starved of cash that a same-cycle trim later in the
        # pass would have freed — an add's fill (and thus the strategy's
        # realised weights) depended on the arbitrary order rank_fn returned
        # names in, with nothing logged. Two-pass ordering removes that
        # path-dependence: every trim's freed cash is available to every add.
        pending_adds = []
        for sym in list(positions.keys()):
            w = weights.get(sym)
            if w is None:
                continue
            target_dollars = equity_now * w
            cur_price = _price(data[sym], exec_date, "Open")
            if np.isnan(cur_price) or cur_price <= 0:
                continue
            cur_val = _inst.market_value(insts[sym], positions[sym]["shares"], cur_price)
            if cur_val <= 0:
                continue
            drift = (cur_val - target_dollars) / target_dollars if target_dollars > 0 else 0.0
            if drift > drift_trim:
                # A trim only sells shares already held for a real (non-zero)
                # duration, so it's fine on the terminal bar too.
                _do_trim(sym, exec_date, target_dollars)
            elif drift < -drift_trim and allow_new:
                # Same "no new capital commitment on the terminal bar" rule
                # that gates _do_buy (finding F2) — without it, an add here
                # buys shares that the End-of-Backtest MTM immediately closes
                # on that same bar: a same-day buy+sell hidden inside a
                # longer-duration trade.
                pending_adds.append((sym, target_dollars))

        for sym, target_dollars in pending_adds:
            _do_add(sym, exec_date, target_dollars)

        # 5. Buy new names to fill the target, from the top of the ranking.
        if allow_new:
            for sym in new_names:
                w = weights.get(sym, 0.0)
                if w <= 0:
                    continue
                _do_buy(sym, exec_date, equity_now * w)

        snapshots.append((exec_date, cash, {s: p["shares"] for s, p in positions.items()}))

    # --- End of backtest: mark any remaining book to the last Close ----------
    # A close-at-last-Close MTM, NOT a same-bar buy+sell round trip (finding F2).
    # No terminal empty snapshot: the last rebalance snapshot's holdings are marked
    # to each day's Close by _build_daily_timeline, so the terminal equity already
    # includes open-position value (parallel to the engine's EoB mark-to-market).
    for sym in list(positions.keys()):
        _do_close_mtm(sym, terminal_date)

    pnl_list = [t["Profit"] for t in trade_log]
    if not pnl_list:
        return None

    # --- Daily mark-to-market equity curve ----------------------------------
    # cash + live position MTM only change at rebalance dates, so each daily
    # equity value is the most-recent snapshot's cash plus its held shares priced
    # at that day's close. Scale-invariant: every term is linear in share counts.
    timeline = _build_daily_timeline(data, insts, snapshots, all_dates)

    from helpers.simulations import calculate_advanced_metrics  # lazy (CONFIG import)
    duration_list = [t["HoldDuration"] for t in trade_log]
    metrics = calculate_advanced_metrics(pnl_list, timeline.dropna(), duration_list)
    final_pnl_percent = (timeline.dropna().iloc[-1] / initial_capital) - 1

    return {
        **metrics,
        "pnl_percent": final_pnl_percent,
        "Trades": len(pnl_list),
        "trade_pnl_list": pnl_list,
        "trade_log": trade_log,
        "initial_capital": initial_capital,
        "portfolio_timeline": timeline.dropna(),
    }


def _build_daily_timeline(data, insts, snapshots, all_dates) -> pd.Series:
    """Daily equity curve from per-rebalance ``(date, cash, {sym: shares})``
    snapshots.

    For each trading day, the effective book is the latest snapshot at or before
    that day; equity is that snapshot's cash plus its held shares priced at the
    day's close. cash and holdings only change at rebalance dates, so this is
    exact. Scale-invariant: every term is linear in share counts, which are
    themselves proportional to initial capital."""
    if not all_dates or not snapshots:
        return pd.Series(dtype=float)

    dates = pd.DatetimeIndex(sorted(all_dates))
    snap_dates = pd.DatetimeIndex([s[0] for s in snapshots])
    # For each day, index of the most recent snapshot at/before it.
    pos = snap_dates.searchsorted(dates, side="right") - 1

    equity = pd.Series(np.nan, index=dates, dtype=float)
    for i, d in enumerate(dates):
        si = pos[i]
        if si < 0:
            continue  # before the first rebalance (shouldn't happen: rebal[0]==dates[0])
        _, cash, holdings = snapshots[si]
        val = cash
        for sym, shares in holdings.items():
            # Same carry-forward rule as _mtm so the two equity paths agree (F3).
            close = _carry_forward_close(data[sym], d)
            if not np.isnan(close):
                val += _inst.market_value(insts[sym], shares, close)
        equity.loc[d] = val
    return equity


# ---------------------------------------------------------------------------
# Config-driven entry point (finding F7): the non-Pool integration that lets a
# caller honor rotation.enabled / rotation.rank_strategy today.
# ---------------------------------------------------------------------------
def run_rotation_from_config(data: dict, config: dict) -> dict | None:
    """Run the rotation named by ``config["rotation"]["rank_strategy"]``, honoring
    ``config["rotation"]["enabled"]``.

    Returns ``None`` (and logs) when rotation is disabled, no ``rank_strategy`` is
    set, or the named plugin is not registered. This is the caller-facing bridge
    that makes the ``rotation.enabled`` / ``rotation.rank_strategy`` config keys
    active without touching main.py's Do-Not-Touch multiprocessing Pool
    (see the module docstring's deferral note).
    """
    rcfg = get_rotation_config(config)
    if not rcfg.get("enabled"):
        logger.info("rotation disabled (rotation.enabled is False) — nothing to run.")
        return None
    name = rcfg.get("rank_strategy")
    if not name:
        logger.warning("[WARNING] rotation.enabled but rotation.rank_strategy is unset.")
        return None

    from helpers.registry import get_rotation_strategies  # lazy: avoid import cycle
    rots = get_rotation_strategies()
    entry = rots.get(name)
    if entry is None:
        logger.warning(
            "[WARNING] rotation.rank_strategy '%s' is not a registered @register_rotation "
            "plugin. Available: %s", name, sorted(rots.keys()),
        )
        return None

    return run_rotation(
        data,
        entry["logic"],
        config,
        regime_gate=entry.get("regime_gate"),
        params=entry.get("params"),
    )
