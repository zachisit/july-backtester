import random as _random

import pandas as pd
import numpy as np
from config import CONFIG
from .simulations import calculate_advanced_metrics
from helpers.position_sizing import calculate_position_size, check_portfolio_heat
from helpers import instruments as _inst
from helpers import intrabar as _intrabar


def _hold_duration_days(entry_dt, exit_dt):
    """Hold duration in days, preserving sub-day precision for intraday trades.

    Returns an ``int`` when the span is a whole number of days — daily and
    midnight-normalized timestamps reproduce the previous
    ``(exit - entry).days`` value byte-for-byte — and a rounded ``float``
    fraction otherwise (e.g. 45-minute bars), so ``HoldDuration`` /
    ``Avg. Hold`` / ``# bars`` are meaningful for sub-daily strategies instead
    of truncating to ``0``.
    """
    total_days = (exit_dt - entry_dt).total_seconds() / 86400.0
    return int(total_days) if float(total_days).is_integer() else round(total_days, 4)


def _equity_contribution(inst, pos, close, side="long"):
    """A position's contribution to account equity, honouring its margin mode.

    - ``cash_full`` (equities): mark-to-market value — cash was reduced by the full
      notional at entry, so the position contributes its market value.
    - ``initial_margin`` (futures): unrealized P&L — only margin was reserved (not
      spent), so the position contributes its open profit/loss on top of cash.
    """
    if inst.margin_mode == _inst.INITIAL_MARGIN:
        return _inst.unrealized_pnl(inst, pos['shares'], pos['entry_price'], close, side=side)
    return _inst.market_value(inst, pos['shares'], close)


def _update_trailing_atr_stop(pos, sym_df, date, stop_config, side="long"):
    """Trailing-ATR-with-breakeven-floor update for one position (`trailing_atr`).

    ``side="long"`` rides the running-max High and ratchets the stop UP (floored at
    breakeven); ``side="short"`` rides the running-min Low and ratchets the stop DOWN
    (capped at breakeven). Symmetric mechanic.

    Two-phase exit (Sleeve A mechanic):
      1. Pre-arm: the stop stays at its initial point-capped ATR level until the bar's
         High reaches the arm target (a reward:risk ratio off the capped stop, computed
         at entry).
      2. Armed: ratchet a ``high - trail_mult * atr_locked`` trail (never loosening),
         clamped to a ``floor`` — ``"breakeven"`` (literal entry, no offset) or a numeric
         price. The ATR is the value LOCKED at the breakout bar (never recomputed live).
    Next-bar-activation model: the level set this bar becomes active next bar.

    The trail rides the running-max **High**, not the close (Sleeve A reference). Using
    the current bar's High with the ``max(prev, candidate)`` ratchet is provably identical
    to tracking a running peak explicitly: ``max_k(high[k] - c)`` telescopes into
    ``running_extreme - c``.
    """
    atr_locked = pos.get('atr_locked')
    if atr_locked is None:
        return
    row = sym_df.loc[date]
    trail_mult = stop_config.get("trail_mult", 1.0)
    # Breakeven floor anchors to the pre-slippage price for margined instruments
    # (futures) and to the slipped fill for cash-full instruments (equities).
    # The correct anchor is stored explicitly as 'trail_anchor' at entry time,
    # gated on margin_mode (mirrors the percentage/points _stop_anchor pattern).
    # Fall back to raw_entry_price for positions created before this key existed.
    entry = pos.get('trail_anchor', pos.get('raw_entry_price', pos['entry_price']))
    floor = stop_config.get("floor")

    if side == "long":
        # ride the running-max High; ratchet the stop up, floored at breakeven/entry
        extreme = row.get('High')
        if not pos.get('trail_armed', False):
            target = pos.get('trail_target')
            if target is not None and pd.notna(extreme) and extreme >= target:
                pos['trail_armed'] = True
            else:
                return
        if pd.isna(extreme):
            return
        candidate = extreme - trail_mult * atr_locked
        if floor == "breakeven":
            candidate = max(candidate, entry)
        elif isinstance(floor, (int, float)):
            candidate = max(candidate, float(floor))
        prev = pos.get('stop_loss_level')
        pos['stop_loss_level'] = candidate if pd.isna(prev) else max(prev, candidate)
    else:
        # short: ride the running-min Low; ratchet the stop DOWN, capped at breakeven/entry
        extreme = row.get('Low')
        if not pos.get('trail_armed', False):
            target = pos.get('trail_target')
            if target is not None and pd.notna(extreme) and extreme <= target:
                pos['trail_armed'] = True
            else:
                return
        if pd.isna(extreme):
            return
        candidate = extreme + trail_mult * atr_locked
        if floor == "breakeven":
            candidate = min(candidate, entry)
        elif isinstance(floor, (int, float)):
            candidate = min(candidate, float(floor))
        prev = pos.get('stop_loss_level')
        pos['stop_loss_level'] = candidate if pd.isna(prev) else min(prev, candidate)


def _prearm_decision(high, low, stop_level, target, window_bars, side="long"):
    """Outcome of ONE pre-arm bar for a ``trailing_atr`` position.

    Returns ``("stop", fill)`` | ``("arm", None)`` | ``("hold", None)``:

    - both the initial stop and the arm target sit inside this coarse bar → the
      order is resolved from finer sub-bar data (``resolve_order_precedence``);
      with no finer coverage the STOP is assumed first (conservative — the coarse
      engine's prior behaviour),
    - only the stop → ``("stop", stop_level)`` (reference parity: the leg1 loop
      never gap-refines a plain stop-only hit, same convention as the armed
      leg2 trail — only the both-hit race above consults finer data),
    - only the target → ``("arm", None)`` (caller arms + seeds the trail),
    - neither → ``("hold", None)``.

    This is the seam that lets the engine reproduce the reference's leg1 loop,
    which evaluates the ENTRY bar and resolves same-bar both-hit from 1-minute
    data. Opt-in: callers only reach it when ``intrabar_resolution`` is on and
    finer data was supplied.
    """
    if pd.isna(stop_level) or target is None:
        return ("hold", None)
    if side == "long":
        hit_s = pd.notna(low) and low <= stop_level
        hit_t = pd.notna(high) and high >= target
    else:
        hit_s = pd.notna(high) and high >= stop_level
        hit_t = pd.notna(low) and low <= target
    if hit_s and hit_t:
        which, fill, _ = _intrabar.resolve_order_precedence(window_bars, stop_level, target, side=side)
        if which == "target":
            return ("arm", None)
        if which == "stop":
            return ("stop", fill)
        return ("stop", stop_level)   # no finer coverage -> conservative stop-first
    if hit_s:
        return ("stop", stop_level)
    if hit_t:
        return ("arm", None)
    return ("hold", None)


def run_portfolio_simulation(portfolio_data, signals, initial_capital, allocation_pct, spy_df, vix_df, tnx_df, stop_config, size_mults=None, delisting_dates=None, intrabar_data=None):
    """
    Runs a portfolio simulation with integrated stop-loss handling and logs
    a rich set of features for each trade for future machine learning analysis.
    (Version hardened against KeyError from misaligned dates).

    Parameters
    ----------
    delisting_dates : dict[str, str], optional
        {symbol: "YYYY-MM-DD"} mapping of delisting dates from helpers/survivorship.py.
        When provided, open positions are force-closed on delisting.
    """
    from helpers.timeframe_utils import get_bars_per_year, get_bars_per_day_exact

    execution_time = CONFIG.get("execution_time", "open").lower()
    htb_rate_annual = CONFIG.get("htb_rate_annual", 0.0)
    # Sub-bar resolution: opt-in and requires finer-resolution data to be supplied.
    # Off / no data -> stop fills behave exactly as before (no-op).
    _intrabar_on = bool(CONFIG.get("intrabar_resolution", False)) and intrabar_data is not None

    # Dynamic HTB rate compounding based on timeframe (fixes issue #55)
    bars_per_year = get_bars_per_year(CONFIG)
    htb_rate_per_bar = (1.0 + htb_rate_annual) ** (1.0 / bars_per_year) - 1.0 if htb_rate_annual > 0 else 0.0

    # --- 20-trading-day average DAILY volume (issue #264) ---
    # A hardcoded rolling(window=20).mean() on raw bars is the mean volume of
    # one BAR, not one DAY, whenever more than one bar makes up a trading
    # session (H/MIN timeframes) -- e.g. on 5-minute bars it averages ~100
    # minutes of volume and calls that "daily" volume, silently miscalibrating
    # both the max_pct_adv liquidity cap and the volume-impact market-impact
    # model. get_bars_per_day_exact() (unlike get_bars_for_period, which
    # ignores `timeframe_multiplier` in its H-timeframe branch) correctly
    # resolves how many bars make up one session, so the window spans ~20 real
    # trading days and the per-bar mean is rescaled back up into a genuine
    # daily-volume figure. The correctness identity is
    #
    #     mean(20*bpd bars) * bpd == sum(window)/(20*bpd) * bpd == sum(window)/20
    #
    # i.e. total volume over the window / 20 days -- but that only holds while
    # the window actually spans 20 days. Hence the EXACT (float) bars-per-day
    # here rather than the truncated bar count (issue #268): int() truncation
    # cost 1H/2H 7.7% and 4H 38.5% of their true ADV, leaving #264 closed only
    # for D/W/M and MIN 5/15/30. For D/W/M bars_per_day == 1.0 exactly, so the
    # window is 20 and the rescale is x1.0 -- a byte-for-byte no-op that
    # protects the equity golden master.
    # Resolved PER SYMBOL (issue #270): `trading_hours_per_day` is one
    # process-wide number, but instruments already resolve per symbol, so a
    # book mixing equities (6.5h RTH) with 24h futures gets the wrong
    # bars-per-day for one side of it whatever the global says. Defaults are
    # unchanged -- resolve_session_hours() falls back to the global unless a
    # run sets a per-symbol override or opts into calendar-derived hours --
    # so this is a no-op for every existing config.
    _adv_params_cache: dict = {}

    def _adv_params(symbol):
        """(window_bars, bars_per_day) for *symbol*, computed once."""
        params = _adv_params_cache.get(symbol)
        if params is None:
            # Passed as a CALLABLE so per-symbol resolution happens only on
            # intraday timeframes. A D/W/M run never reads a session length,
            # and must not start failing on a bad `trading_hours_per_day` it
            # would otherwise have ignored.
            bars_per_day = get_bars_per_day_exact(
                CONFIG,
                session_hours=lambda: _inst.resolve_session_hours(symbol, CONFIG),
            )
            params = _adv_params_cache[symbol] = (
                max(1, round(20 * bars_per_day)),
                bars_per_day,
            )
        return params

    # Per-symbol memo for the rolling ADV series (issue #269). Each call used
    # to recompute .rolling().mean() across the WHOLE series and then keep a
    # single value; with four call sites (and two of them on the same entry
    # bar) that is a lot of repeated work. Cost is driven by series length
    # rather than window width -- measured at ~0.6ms per call on 2 years of
    # 5-minute bars (39k rows) vs ~0.09ms on daily -- so it is intraday runs
    # that pay, roughly a minute of pure re-computation on a 100-symbol book.
    #
    # Scoped to this closure ON PURPOSE, not module level: workers process
    # many strategies/portfolios in one process, and a module-level cache
    # would serve one portfolio's volume series to the next.
    #
    # Deliberately unbounded. It trades memory for time at roughly one
    # float64 series per traded symbol -- on a 500-name book of 5-minute
    # bars over 2 years that is ~314KB x 500 = ~157MB, against the ~790MB of
    # OHLCV the same run already holds resident, so ~20% on top of data that
    # must be in memory anyway. Only symbols that actually reach an ADV
    # lookup are cached, and the whole dict is released when the simulation
    # returns. An LRU bound would reintroduce exactly the recomputation this
    # exists to remove, so size it down only if a real run shows pressure.
    _adv_cache: dict = {}

    # min_periods stays 1 DELIBERATELY (issue #269). Raising it to one full
    # session so the early estimate has a day behind it looks like an
    # improvement but is a regression: both consumers guard with
    # `if pd.notna(adv) and adv > 0`, so a NaN does not produce a cautious
    # cap -- it skips the cap block entirely. Raising min_periods would
    # therefore leave the first session of every intraday backtest with NO
    # liquidity cap and NO market impact at all, which is strictly worse than
    # the noisy-but-unbiased estimate min_periods=1 gives (one bar's volume
    # rescaled by bars-per-day is a fair guess at the day's volume, just a
    # high-variance one). Revisit only alongside a decision about what a
    # missing ADV should mean -- see the discussion on #269.
    def _daily_adv(volume_series, at_date, symbol):
        """Trailing ~20-trading-day average DAILY volume as of `at_date`."""
        adv_series = _adv_cache.get(symbol)
        if adv_series is None:
            window_bars, bars_per_day = _adv_params(symbol)
            adv_series = _adv_cache[symbol] = (
                volume_series.rolling(
                    window=window_bars, min_periods=1
                ).mean()
                * bars_per_day
            )
        # NaN propagates through the multiply, so a missing/NaN bar still
        # yields NaN here exactly as the per-call version did.
        return adv_series.get(at_date, np.nan)

    short_positions: dict = {}

    # Resolve per-symbol instrument metadata once. For equities the resolved
    # instrument reproduces the engine's prior arithmetic byte-for-byte (see
    # helpers/instruments.py); futures branch on margin_mode / integer_units.
    instruments = {sym: _inst.resolve_instrument(sym, CONFIG) for sym in portfolio_data}

    cash = initial_capital
    reserved_margin = 0.0  # initial margin reserved by open futures positions (buying-power)
    positions = {}
    all_dates = sorted(list(set(date for df in portfolio_data.values() for date in df.index)))
    portfolio_timeline = pd.Series(index=all_dates, dtype=float)
    trade_log = []
    trade_counter = 0
    cumulative_profit = 0.0

    prev_trading_dates = { symbol: df.index.to_series().shift(1) for symbol, df in portfolio_data.items() }
    # Next-bar timestamp per symbol — bounds the sub-bar window of the CURRENT bar
    # for intrabar resolution ([date, next_date)). For a daily bar this is exactly
    # the calendar day; for an intraday (e.g. 45-min) bar it is that bar's own span.
    next_trading_dates = { symbol: df.index.to_series().shift(-1) for symbol, df in portfolio_data.items() }

    def _close_long_now(symbol, pos, exit_date, raw_exit_price, exit_reason):
        """Close a long position immediately, logging it exactly like the main
        exit path (helpers.instruments slippage/commission, R-multiple, MAE/MFE).

        Only used by the opt-in entry-bar intrabar-parity check (a same-bar
        entry+exit — the position never enters ``positions`` at all in that
        case). The ordinary multi-bar exit path is untouched by this helper.
        """
        nonlocal cash, reserved_margin, cumulative_profit, trade_counter
        trade_df = portfolio_data[symbol].loc[pos['entry_date']:exit_date]
        mae_pct, mfe_pct = 0.0, 0.0
        if not trade_df.empty:
            mae_pct = (trade_df['Low'].min() - pos['entry_price']) / pos['entry_price']
            mfe_pct = (trade_df['High'].max() - pos['entry_price']) / pos['entry_price']
        trade_counter += 1
        exit_price = _inst.apply_slippage(instruments[symbol], raw_exit_price, "sell")
        exit_impact_bps = 0.0
        _coeff = CONFIG.get('volume_impact_coeff', 0.0)
        if _coeff > 0 and 'Volume' in portfolio_data[symbol].columns:
            _adv = _daily_adv(portfolio_data[symbol]['Volume'], exit_date, symbol)
            if pd.notna(_adv) and _adv > 0:
                _impact = _coeff * np.sqrt(pos['shares'] / _adv)
                exit_price = exit_price * (1 - _impact)
                exit_impact_bps = round(_impact * 10000, 1)
        _exit_inst = instruments[symbol]
        commission = _inst.commission(_exit_inst, pos['shares'])
        if _exit_inst.margin_mode == _inst.INITIAL_MARGIN:
            gross_pnl = (exit_price - pos['entry_price']) * pos['shares'] * _exit_inst.point_value
            cash += gross_pnl - commission
            reserved_margin -= pos.get('margin', 0.0)
            net_pnl = gross_pnl - (2 * commission)
        else:
            cash += (pos['shares'] * exit_price) - commission
            net_pnl = ((exit_price - pos['entry_price']) * pos['shares']) - (2 * commission)
        cumulative_profit += net_pnl
        duration = _hold_duration_days(pos['entry_date'], exit_date)
        position_value = _inst.notional(_exit_inst, pos['shares'], pos['entry_price'])
        _isl = pos.get('initial_stop_loss_level')
        if pd.notna(_isl) and _isl > 0 and _isl < pos['entry_price']:
            _irps = pos['entry_price'] - _isl
        else:
            _irps = pos['entry_price'] * 0.01
        _rm = (net_pnl / (_irps * pos['shares'] * _exit_inst.point_value)
               if _irps > 0 and pos['shares'] > 0 else None)
        log_entry = {
            'Symbol': symbol, 'Trade': f"Long {trade_counter}",
            'EntryDate': pos['entry_date'].isoformat(), 'EntryPrice': pos['entry_price'],
            'ExitDate': exit_date.isoformat(), 'ExitPrice': exit_price,
            'Profit': net_pnl, 'ProfitPct': net_pnl / position_value if position_value > 0 else 0,
            'Shares': pos['shares'], 'PosSizeMult': pos.get('size_mult', 1.0),
            'is_win': 1 if net_pnl > 0 else 0, 'HoldDuration': duration,
            'MAE_pct': mae_pct, 'MFE_pct': mfe_pct, 'ExitReason': exit_reason,
            'InitialRisk': _irps, 'RMultiple': _rm,
            'VolumeImpact_bps': round(pos.get('entry_impact_bps', 0.0) + exit_impact_bps, 1),
        }
        log_entry.update(pos.get('features', {}))
        trade_log.append(log_entry)

    def _close_short_now(symbol, spos, exit_date, raw_cover_price, cover_reason):
        """Cover a short position immediately — mirror of ``_close_long_now``
        for the opt-in entry-bar intrabar-parity check on the short side."""
        nonlocal cash, reserved_margin, trade_counter
        inst_c = instruments[symbol]
        cover_slip = _inst.apply_slippage(inst_c, raw_cover_price, "buy")
        commission = _inst.commission(inst_c, spos['shares'])
        _gross = (spos['shares'] * (spos['entry_price'] - cover_slip)) * inst_c.point_value
        net_pnl = _gross - (2 * commission) - spos.get('total_borrow_cost', 0.0)
        cash += _gross - commission
        if inst_c.margin_mode == _inst.INITIAL_MARGIN:
            reserved_margin -= spos.get('margin', 0.0)
        trade_counter += 1
        short_trade_df = portfolio_data[symbol].loc[spos['entry_date']:exit_date]
        if not short_trade_df.empty:
            _ep = spos['entry_price']
            short_mfe = (_ep - short_trade_df['Low'].min()) / _ep
            short_mae = (short_trade_df['High'].max() - _ep) / _ep
        else:
            short_mfe, short_mae = 0.0, 0.0
        _s_ir = spos.get('initial_risk')
        _s_rm = (net_pnl / (_s_ir * spos['shares'] * inst_c.point_value)
                 if _s_ir and _s_ir > 0 and spos['shares'] > 0 else None)
        trade_log.append({
            'Symbol': symbol, 'Trade': f"Short {trade_counter}",
            'EntryDate': spos['entry_date'].isoformat(), 'EntryPrice': spos['entry_price'],
            'ExitDate': exit_date.isoformat(), 'ExitPrice': cover_slip,
            'Profit': net_pnl, 'ProfitPct': net_pnl / spos['notional'] if spos['notional'] > 0 else 0,
            'Shares': spos['shares'], 'is_win': 1 if net_pnl > 0 else 0,
            'HoldDuration': _hold_duration_days(spos['entry_date'], exit_date),
            'MAE_pct': short_mae, 'MFE_pct': short_mfe,
            'ExitReason': cover_reason,
            'InitialRisk': _s_ir if (_s_ir and _s_ir > 0) else 0.0,
            'RMultiple': _s_rm,
        })
        trade_log[-1].update(spos.get('features', {}))

    def _pit_flag(symbol, date, column, default):
        df = portfolio_data[symbol]
        if column not in df.columns or date not in df.index:
            return default
        value = df.at[date, column]
        return default if pd.isna(value) else bool(value)

    for date in portfolio_timeline.index:
        # --- EQUITY CALCULATION ---
        current_market_value = 0.0
        for symbol, pos in positions.items():
            # <-- NEW CHECK: Make sure the date exists for this symbol before getting its price
            if date in portfolio_data[symbol].index:
                close_price = portfolio_data[symbol].loc[date]['Close']
                if pd.notna(close_price):
                    current_market_value += _equity_contribution(instruments[symbol], pos, close_price, side="long")
            else:
                # If date doesn't exist, use the last known price for a more stable equity curve
                # This is an edge case, but good practice.
                last_valid_date = portfolio_data[symbol].index[portfolio_data[symbol].index < date][-1]
                close_price = portfolio_data[symbol].loc[last_valid_date]['Close']
                current_market_value += _equity_contribution(instruments[symbol], pos, close_price, side="long")

        for symbol, spos in short_positions.items():
            if date in portfolio_data[symbol].index:
                cur = portfolio_data[symbol].loc[date].get('Close')
                if pd.notna(cur):
                    current_market_value += _inst.unrealized_pnl(
                        instruments[symbol], spos['shares'], spos['entry_price'], cur, side="short")

        total_equity = cash + current_market_value
        portfolio_timeline[date] = total_equity

        # --- POSITION MANAGEMENT (EXITS) ---
        exited_symbols = []
        for symbol, pos in list(positions.items()):
            # <-- NEW CHECK: The most important check. If the current date doesn't exist for this stock,
            # we can't possibly check for signals or get prices. Skip to the next stock.
            if date not in portfolio_data[symbol].index:
                continue

            raw_exit_price, exit_date, exit_reason = np.nan, pd.NaT, "Strategy Exit"

            # PIT membership is enforced on the execution date. This prevents a
            # prior-day signal from entering or retaining a position at the first
            # non-member open. If no post-leave bar exists, main.py marks the last
            # available member bar for a conservative close liquidation.
            pit_member = _pit_flag(symbol, date, '_pit_member', True)
            pit_force_exit = _pit_flag(symbol, date, '_pit_force_exit', False)
            if pit_force_exit:
                raw_exit_price = portfolio_data[symbol].loc[date].get('Close')
                exit_date = date
                exit_reason = "PIT Membership Exit (last available close)"
            elif not pit_member:
                raw_exit_price = portfolio_data[symbol].loc[date].get(
                    'Open' if execution_time == 'open' else 'Close')
                exit_date = date
                exit_reason = "PIT Membership Exit"

            # --- STOP-LOSS CHECK ---
            if (pd.isna(raw_exit_price) and stop_config.get("type") != "none"
                    and pd.notna(pos.get('stop_loss_level'))):
                current_low = portfolio_data[symbol].loc[date].get('Low')
                # Pre-arm both-hit resolution (opt-in): while a trailing_atr position
                # hasn't armed yet, a bar that touches BOTH the initial stop and the
                # arm target is ambiguous on daily/coarse OHLC alone. Resolve the
                # ordering from finer-resolution sub-bars — reproducing the reference
                # mechanic's leg1 loop — instead of always assuming the stop won.
                if (stop_config.get("type") == "trailing_atr" and _intrabar_on
                        and not pos.get('trail_armed', False) and pos.get('trail_target') is not None):
                    current_high = portfolio_data[symbol].loc[date].get('High')
                    _wbars = _intrabar.window_bars(intrabar_data.get(symbol), date,
                                                   next_trading_dates[symbol].get(date))
                    _decision, _fill = _prearm_decision(
                        current_high, current_low, pos['stop_loss_level'], pos['trail_target'],
                        _wbars, side="long")
                    if _decision == "stop":
                        raw_exit_price = _fill
                        exit_date = date
                        exit_reason = f"Stop Loss ({stop_config['type']})"
                    # "arm" / "hold": leave raw_exit_price NaN — the TRAIL block below
                    # calls _update_trailing_atr_stop, which arms + seeds off THIS same
                    # bar's High when the target was reached (idempotent on "hold").
                elif pd.notna(current_low) and current_low <= pos['stop_loss_level']:
                    raw_exit_price = pos['stop_loss_level']
                    exit_date = date
                    exit_reason = f"Stop Loss ({stop_config['type']})"
                    # Sub-bar resolution: refine the fill from finer-resolution bars
                    # when enabled + available — a gap through the stop fills at the
                    # (worse) sub-bar open rather than optimistically at the stop.
                    # Skipped once an ATR trail has armed: the reference trailing
                    # mechanic (Sleeve A leg2) always fills at the exact trail level,
                    # gap or not — gap-refinement there would diverge from parity.
                    if (_intrabar_on and symbol in intrabar_data
                            and not (stop_config.get("type") == "trailing_atr" and pos.get('trail_armed', False))):
                        _day_bars = _intrabar.window_bars(intrabar_data[symbol], date,
                                                          next_trading_dates[symbol].get(date))
                        _fill, _ = _intrabar.resolve_stop_fill(_day_bars, pos['stop_loss_level'], side="long")
                        if _fill is not None:
                            raw_exit_price = _fill

            # --- STRATEGY-BASED EXIT (full <= -1) or PARTIAL SCALE-OUT (-1 < s < 0) ---
            partial_fraction = 0.0
            if pd.isna(raw_exit_price):
                signal_date_to_check = prev_trading_dates[symbol].get(date) if execution_time == 'open' else date
                if pd.notna(signal_date_to_check) and signal_date_to_check in signals[symbol].index:
                    signal_value = signals[symbol].loc[signal_date_to_check]
                    if signal_value <= -1:
                        raw_exit_price = portfolio_data[symbol].loc[date].get('Open' if execution_time == 'open' else 'Close')
                        exit_date = date
                    elif signal_value < 0:
                        # Fractional exit signal: scale OUT this fraction of the position,
                        # keeping the remainder open. Full exit remains signal <= -1.
                        partial_fraction = abs(float(signal_value))

            # --- PARTIAL SCALE-OUT EXECUTION (position stays open) ---
            if pd.isna(raw_exit_price) and partial_fraction > 0:
                _pinst = instruments[symbol]
                _praw = portfolio_data[symbol].loc[date].get('Open' if execution_time == 'open' else 'Close')
                _pexit_shares = pos['shares'] * partial_fraction
                if _pinst.integer_units:
                    _pexit_shares = _inst.round_units(_pinst, _pexit_shares)
                _min_units = 1.0 if _pinst.integer_units else 1e-9
                if pd.notna(_praw) and _pexit_shares >= _min_units and _pexit_shares < pos['shares']:
                    _pexit = _inst.apply_slippage(_pinst, _praw, "sell")
                    _pcomm = _inst.commission(_pinst, _pexit_shares)
                    if _pinst.margin_mode == _inst.INITIAL_MARGIN:
                        _pgross = (_pexit - pos['entry_price']) * _pexit_shares * _pinst.point_value
                        cash += _pgross - _pcomm
                        _prel = pos.get('margin', 0.0) * (_pexit_shares / pos['shares'])
                        reserved_margin -= _prel
                        pos['margin'] = pos.get('margin', 0.0) - _prel
                        _pnet = _pgross - (2 * _pcomm)
                    else:
                        cash += (_pexit_shares * _pexit) - _pcomm
                        _pnet = ((_pexit - pos['entry_price']) * _pexit_shares) - (2 * _pcomm)
                    cumulative_profit += _pnet
                    trade_counter += 1
                    _ptdf = portfolio_data[symbol].loc[pos['entry_date']:date]
                    _pmae = (_ptdf['Low'].min() - pos['entry_price']) / pos['entry_price'] if not _ptdf.empty else 0.0
                    _pmfe = (_ptdf['High'].max() - pos['entry_price']) / pos['entry_price'] if not _ptdf.empty else 0.0
                    _pisl = pos.get('initial_stop_loss_level')
                    if pd.notna(_pisl) and _pisl > 0 and _pisl < pos['entry_price']:
                        _pirps = pos['entry_price'] - _pisl
                    else:
                        _pirps = pos['entry_price'] * 0.01
                    _prm = (_pnet / (_pirps * _pexit_shares * _pinst.point_value)
                            if _pirps > 0 and _pexit_shares > 0 else None)
                    _pval = _inst.notional(_pinst, _pexit_shares, pos['entry_price'])
                    _plog = {
                        'Symbol': symbol, 'Trade': f"Long {trade_counter} (partial)",
                        'EntryDate': pos['entry_date'].isoformat(), 'EntryPrice': pos['entry_price'],
                        'ExitDate': date.isoformat(), 'ExitPrice': _pexit,
                        'Profit': _pnet, 'ProfitPct': _pnet / _pval if _pval > 0 else 0,
                        'Shares': _pexit_shares, 'PosSizeMult': pos.get('size_mult', 1.0),
                        'is_win': 1 if _pnet > 0 else 0,
                        'HoldDuration': _hold_duration_days(pos['entry_date'], date),
                        'MAE_pct': _pmae, 'MFE_pct': _pmfe, 'ExitReason': 'Partial Scale-Out',
                        'InitialRisk': _pirps, 'RMultiple': _prm, 'VolumeImpact_bps': 0.0,
                    }
                    _plog.update(pos.get('features', {}))
                    trade_log.append(_plog)
                    pos['shares'] -= _pexit_shares

            # --- MAINTENANCE MARGIN / MARGIN CALL (futures only) ---
            # Force-liquidate a futures position when posted margin + unrealized P&L
            # falls below the maintenance requirement (notional * maintenance_margin_pct).
            # Disabled by default (0.0). Equities (cash_full) never margin-call.
            if pd.isna(raw_exit_price):
                _mm_pct = CONFIG.get("maintenance_margin_pct", 0.0) or 0.0
                _mc_inst = instruments[symbol]
                if _mm_pct > 0 and _mc_inst.margin_mode == _inst.INITIAL_MARGIN:
                    _mc_close = portfolio_data[symbol].loc[date].get('Close')
                    if pd.notna(_mc_close):
                        _unreal = _inst.unrealized_pnl(
                            _mc_inst, pos['shares'], pos['entry_price'], _mc_close, side="long")
                        _mc_notional = _inst.notional(_mc_inst, pos['shares'], pos['entry_price'])
                        if pos.get('margin', 0.0) + _unreal < _mc_notional * _mm_pct:
                            raw_exit_price = _mc_close   # forced liquidation at market
                            exit_date = date
                            exit_reason = "Margin Call"

            # --- TRAIL THE STOP AND CONTINUE IF NOT EXITING ---
            if pd.isna(raw_exit_price):
                if stop_config.get("type") == "atr" and pd.notna(pos.get('stop_loss_level')):
                    current_close = portfolio_data[symbol].loc[date].get('Close')
                    current_atr = portfolio_data[symbol].loc[date].get('ATR_14')
                    if pd.notna(current_close) and pd.notna(current_atr):
                        new_stop_level = _inst.atr_stop_level(
                            current_close, current_atr, stop_config.get("multiplier", 3.0),
                            side="long", point_cap=stop_config.get("point_cap"))
                        pos['stop_loss_level'] = max(pos['stop_loss_level'], new_stop_level)
                elif stop_config.get("type") == "trailing_atr":
                    _update_trailing_atr_stop(pos, portfolio_data[symbol], date, stop_config)
                continue

            # --- TRADE EXIT AND LOGGING LOGIC ---
            trade_df = portfolio_data[symbol].loc[pos['entry_date']:exit_date]
            mae_pct, mfe_pct = 0.0, 0.0
            if not trade_df.empty:
                lowest_price = trade_df['Low'].min()
                mae_pct = (lowest_price - pos['entry_price']) / pos['entry_price']
                highest_price = trade_df['High'].max()
                mfe_pct = (highest_price - pos['entry_price']) / pos['entry_price']
                
            trade_counter += 1
            exit_price = _inst.apply_slippage(instruments[symbol], raw_exit_price, "sell")

            # --- VOLUME-BASED MARKET IMPACT (exit) ---
            exit_impact_bps = 0.0
            _exit_impact_coeff = CONFIG.get('volume_impact_coeff', 0.0)
            if _exit_impact_coeff > 0 and 'Volume' in portfolio_data[symbol].columns:
                _adv_exit = _daily_adv(portfolio_data[symbol]['Volume'], date, symbol)
                if pd.notna(_adv_exit) and _adv_exit > 0:
                    _order_pct = pos['shares'] / _adv_exit
                    _impact = _exit_impact_coeff * np.sqrt(_order_pct)
                    exit_price = exit_price * (1 - _impact)
                    exit_impact_bps = round(_impact * 10000, 1)

            _exit_inst = instruments[symbol]
            commission = _inst.commission(_exit_inst, pos['shares'])
            if _exit_inst.margin_mode == _inst.INITIAL_MARGIN:
                # Futures: realise P&L (via $/point) into cash and release reserved margin.
                gross_pnl = (exit_price - pos['entry_price']) * pos['shares'] * _exit_inst.point_value
                cash += gross_pnl - commission
                reserved_margin -= pos.get('margin', 0.0)
                net_pnl = gross_pnl - (2 * commission)
            else:
                cash += (pos['shares'] * exit_price) - commission
                net_pnl = ((exit_price - pos['entry_price']) * pos['shares']) - (2 * commission)
            cumulative_profit += net_pnl
            duration = _hold_duration_days(pos['entry_date'], exit_date)
            position_value = _inst.notional(_exit_inst, pos['shares'], pos['entry_price'])

            # --- Initial Risk and R-Multiple ---
            _initial_sl = pos.get('initial_stop_loss_level')
            if pd.notna(_initial_sl) and _initial_sl > 0 and _initial_sl < pos['entry_price']:
                _initial_risk_per_share = pos['entry_price'] - _initial_sl
            else:
                _initial_risk_per_share = pos['entry_price'] * 0.01
            _r_multiple = (net_pnl / (_initial_risk_per_share * pos['shares'] * _exit_inst.point_value)
                           if _initial_risk_per_share > 0 and pos['shares'] > 0 else None)

            log_entry = {
                'Symbol': symbol, 'Trade': f"Long {trade_counter}",
                'EntryDate': pos['entry_date'].isoformat(), 'EntryPrice': pos['entry_price'],
                'ExitDate': exit_date.isoformat(), 'ExitPrice': exit_price,
                'Profit': net_pnl, 'ProfitPct': net_pnl / position_value if position_value > 0 else 0,
                'Shares': pos['shares'],
                'PosSizeMult': pos.get('size_mult', 1.0),
                'is_win': 1 if net_pnl > 0 else 0,
                'HoldDuration': duration,
                'MAE_pct': mae_pct, 'MFE_pct': mfe_pct,
                'ExitReason': exit_reason,
                'InitialRisk': _initial_risk_per_share,
                'RMultiple': _r_multiple,
                'VolumeImpact_bps': round(pos.get('entry_impact_bps', 0.0) + exit_impact_bps, 1),
            }
            log_entry.update(pos.get('features', {}))
            trade_log.append(log_entry)
            exited_symbols.append(symbol)

        for symbol in exited_symbols: del positions[symbol]

        # --- BORROW COST DEBIT (shorts held overnight) ---
        for symbol, spos in list(short_positions.items()):
            cost = _inst.borrow_cost_per_bar(instruments[symbol], spos['notional'], htb_rate_per_bar)
            if cost:
                cash -= cost
                spos['total_borrow_cost'] = spos.get('total_borrow_cost', 0.0) + cost

        # --- SHORT COVER (stop-loss / margin call / strategy signal / PIT) ---
        short_exited = []
        for symbol, spos in list(short_positions.items()):
            if date not in portfolio_data[symbol].index:
                continue
            inst_c = instruments[symbol]
            row = portfolio_data[symbol].loc[date]
            cover_raw, cover_reason = np.nan, "Short Cover"

            # PIT membership exit
            pit_member = _pit_flag(symbol, date, '_pit_member', True)
            pit_force_exit = _pit_flag(symbol, date, '_pit_force_exit', False)
            if pit_force_exit:
                cover_raw = row.get('Close')
                cover_reason = "PIT Membership Exit (last available close)"
            elif not pit_member:
                cover_raw = row.get('Open' if execution_time == 'open' else 'Close')
                cover_reason = "PIT Membership Exit"

            # STOP-LOSS (short is stopped when the High trades up through the stop)
            if (pd.isna(cover_raw) and stop_config.get("type") != "none"
                    and pd.notna(spos.get('stop_loss_level'))):
                cur_high = row.get('High')
                # Pre-arm both-hit resolution (opt-in, mirror of the long side): while
                # not yet armed, a bar touching both the initial stop and the arm
                # target is resolved from finer sub-bars instead of assumed-stop.
                if (stop_config.get("type") == "trailing_atr" and _intrabar_on
                        and not spos.get('trail_armed', False) and spos.get('trail_target') is not None):
                    cur_low = row.get('Low')
                    _wbars = _intrabar.window_bars(intrabar_data.get(symbol), date,
                                                   next_trading_dates[symbol].get(date))
                    _decision, _fill = _prearm_decision(
                        cur_high, cur_low, spos['stop_loss_level'], spos['trail_target'],
                        _wbars, side="short")
                    if _decision == "stop":
                        cover_raw = _fill
                        cover_reason = f"Stop Loss ({stop_config['type']})"
                    # "arm" / "hold": leave cover_raw NaN — the trail-update below arms
                    # + seeds off THIS same bar's Low when the target was reached.
                elif pd.notna(cur_high) and cur_high >= spos['stop_loss_level']:
                    cover_raw = spos['stop_loss_level']
                    cover_reason = f"Stop Loss ({stop_config['type']})"
                    # See mirrored long-side comment: skip gap-refinement once the ATR
                    # trail has armed, matching the reference's exact-level trail fill.
                    if (_intrabar_on and symbol in intrabar_data
                            and not (stop_config.get("type") == "trailing_atr" and spos.get('trail_armed', False))):
                        _day_bars = _intrabar.window_bars(intrabar_data[symbol], date,
                                                          next_trading_dates[symbol].get(date))
                        _fill, _ = _intrabar.resolve_stop_fill(_day_bars, spos['stop_loss_level'], side="short")
                        if _fill is not None:
                            cover_raw = _fill

            # MAINTENANCE MARGIN / MARGIN CALL (futures short)
            if pd.isna(cover_raw):
                _mm_pct = CONFIG.get("maintenance_margin_pct", 0.0) or 0.0
                if _mm_pct > 0 and inst_c.margin_mode == _inst.INITIAL_MARGIN:
                    _mc_close = row.get('Close')
                    if pd.notna(_mc_close):
                        _unreal = _inst.unrealized_pnl(
                            inst_c, spos['shares'], spos['entry_price'], _mc_close, side="short")
                        _mc_notional = _inst.notional(inst_c, spos['shares'], spos['entry_price'])
                        if spos.get('margin', 0.0) + _unreal < _mc_notional * _mm_pct:
                            cover_raw = _mc_close
                            cover_reason = "Margin Call"

            # STRATEGY cover (signal < 0 while short)
            if pd.isna(cover_raw):
                sig_date = prev_trading_dates[symbol].get(date) if execution_time == 'open' else date
                if (pd.notna(sig_date) and sig_date in signals[symbol].index
                        and signals[symbol].loc[sig_date] < 0):
                    cover_raw = row.get('Open' if execution_time == 'open' else 'Close')
                    cover_reason = "Short Cover"

            # Not covering this bar → trail the short stop and move on.
            if pd.isna(cover_raw):
                if stop_config.get("type") == "atr" and pd.notna(spos.get('stop_loss_level')):
                    _cc, _ca = row.get('Close'), row.get('ATR_14')
                    if pd.notna(_cc) and pd.notna(_ca):
                        _ns = _inst.atr_stop_level(_cc, _ca, stop_config.get("multiplier", 3.0),
                                                   side="short", point_cap=stop_config.get("point_cap"))
                        spos['stop_loss_level'] = min(spos['stop_loss_level'], _ns)
                elif stop_config.get("type") == "trailing_atr":
                    _update_trailing_atr_stop(spos, portfolio_data[symbol], date, stop_config, side="short")
                continue

            # --- EXECUTE COVER ---
            cover_slip = _inst.apply_slippage(inst_c, cover_raw, "buy")
            commission = _inst.commission(inst_c, spos['shares'])
            _gross = (spos['shares'] * (spos['entry_price'] - cover_slip)) * inst_c.point_value
            net_pnl = _gross - (2 * commission) - spos.get('total_borrow_cost', 0.0)
            cash += _gross - commission
            if inst_c.margin_mode == _inst.INITIAL_MARGIN:
                reserved_margin -= spos.get('margin', 0.0)
            trade_counter += 1
            # MAE/MFE for shorts: favorable = price drops, adverse = price rises
            short_trade_df = portfolio_data[symbol].loc[spos['entry_date']:date]
            if not short_trade_df.empty:
                _ep = spos['entry_price']
                short_mfe = (_ep - short_trade_df['Low'].min())  / _ep  # max drop = best case
                short_mae = (short_trade_df['High'].max() - _ep) / _ep  # max rise = worst case
            else:
                short_mfe, short_mae = 0.0, 0.0
            _s_ir = spos.get('initial_risk')
            _s_rm = (net_pnl / (_s_ir * spos['shares'] * inst_c.point_value)
                     if _s_ir and _s_ir > 0 and spos['shares'] > 0 else None)
            trade_log.append({
                'Symbol': symbol, 'Trade': f"Short {trade_counter}",
                'EntryDate': spos['entry_date'].isoformat(), 'EntryPrice': spos['entry_price'],
                'ExitDate': date.isoformat(), 'ExitPrice': cover_slip,
                'Profit': net_pnl, 'ProfitPct': net_pnl / spos['notional'] if spos['notional'] > 0 else 0,
                'Shares': spos['shares'], 'is_win': 1 if net_pnl > 0 else 0,
                'HoldDuration': _hold_duration_days(spos['entry_date'], date),
                'MAE_pct': short_mae, 'MFE_pct': short_mfe,
                'ExitReason': cover_reason,
                'InitialRisk': _s_ir if (_s_ir and _s_ir > 0) else 0.0,
                'RMultiple': _s_rm,
            })
            trade_log[-1].update(spos.get('features', {}))
            short_exited.append(symbol)
        for symbol in short_exited:
            del short_positions[symbol]

        # --- SHORT ENTRY (signal = -2, not already in any position) ---
        _priority = CONFIG.get("entry_priority", "alphabetical")
        if _priority == "signal_date":
            def _short_sig_key(item):
                sym, _df = item
                if date not in _df.index:
                    return (1, "", sym)
                sd = prev_trading_dates[sym].get(date) if execution_time == "open" else date
                if (pd.notna(sd) and sym in signals and sd in signals[sym].index
                        and signals[sym].loc[sd] == -2):
                    return (0, str(sd), sym)
                return (1, "", sym)
            _short_items = sorted(portfolio_data.items(), key=_short_sig_key)
        elif _priority == "random_seed":
            _rng_short = _random.Random(CONFIG.get("entry_random_seed", 42))
            _short_items = sorted(portfolio_data.items(), key=lambda x: x[0])
            _rng_short.shuffle(_short_items)
        else:
            _short_items = sorted(portfolio_data.items(), key=lambda x: x[0])
        for symbol, df in _short_items:
            if date not in df.index or symbol in positions or symbol in short_positions:
                continue
            if (not _pit_flag(symbol, date, '_pit_member', True)
                    or _pit_flag(symbol, date, '_pit_force_exit', False)):
                continue
            sig_date = prev_trading_dates[symbol].get(date) if execution_time == 'open' else date
            if pd.notna(sig_date) and sig_date in signals[symbol].index and signals[symbol].loc[sig_date] == -2:
                ep = df.loc[date].get('Open' if execution_time == 'open' else 'Close')
                if pd.isna(ep) or ep <= 0:
                    continue
                inst_se = instruments[symbol]

                # Short-side stop / target / trail init (mirror of the long entry block).
                # Stop sits ABOVE entry; target BELOW; ATR locked at the signal bar.
                _s_stop, _s_target, _s_atr, _s_trail_anchor = np.nan, None, None, None
                _sc_type = stop_config.get("type")
                if _sc_type in ('percentage', 'points'):
                    _s_stop = _inst.stop_level(inst_se, ep, stop_config, side="short")
                elif _sc_type == 'atr':
                    _dbe = prev_trading_dates[symbol].get(date)
                    if pd.notna(_dbe) and _dbe in df.index:
                        _ab, _cb = df.loc[_dbe].get('ATR_14'), df.loc[_dbe].get('Close')
                        if pd.notna(_ab) and pd.notna(_cb):
                            _s_stop = _inst.atr_stop_level(_cb, _ab, stop_config.get("multiplier", 3.0),
                                                           side="short", point_cap=stop_config.get("point_cap"))
                elif _sc_type == 'trailing_atr':
                    _dbe = prev_trading_dates[symbol].get(date)
                    _ab = df.loc[_dbe].get('ATR_14') if (pd.notna(_dbe) and _dbe in df.index) else np.nan
                    if pd.notna(_ab):
                        _s_atr = float(_ab)
                        _sm = stop_config.get("stop_mult", 1.0)
                        _eff = _s_atr * _sm
                        _pc = stop_config.get("point_cap")
                        if _pc is not None and _pc > 0:
                            _eff = min(_eff, _pc)
                        # Anchor mirrors the long-side margin_mode gate: futures
                        # (INITIAL_MARGIN) use the raw pre-slippage price; equities
                        # (CASH_FULL) use the fill price. For equity shorts the fill
                        # price equals ep (no slippage applied on that path), so the
                        # gate is consistent even though the values coincide today.
                        _s_trail_anchor = (
                            ep if inst_se.margin_mode == _inst.INITIAL_MARGIN
                            else ep)   # equity fill = ep (no short slippage on CASH_FULL path)
                        _s_stop = _s_trail_anchor + _eff
                        _t1 = stop_config.get("t1_mult", 0.0)
                        if _sm > 0 and _t1 > 0:
                            _s_target = _s_trail_anchor - _eff * (_t1 / _sm)
                _s_ir = float(_s_stop - ep) if (pd.notna(_s_stop) and _s_stop > ep) else None

                # --- CAPTURE FEATURES AT ENTRY (mirror of the long entry block) ---
                _s_features = {}
                try:
                    _s_features['entry_RSI_14'] = df.loc[date, 'RSI_14']
                    _s_features['entry_ATR_14_pct'] = df.loc[date, 'ATR_14_pct']
                    _s_features['entry_SMA200_dist_pct'] = df.loc[date, 'SMA200_dist_pct']
                    _s_features['entry_Volume_Spike'] = df.loc[date, 'Volume_Spike']
                    if spy_df is not None:
                        _s_features['entry_SPY_RSI_14'] = spy_df.loc[date, 'RSI_14']
                        _s_features['entry_SPY_SMA200_dist_pct'] = spy_df.loc[date, 'SMA200_dist_pct']
                    if vix_df is not None:
                        _s_features['entry_VIX_Close'] = vix_df.loc[date, 'Close']
                    if tnx_df is not None:
                        _s_features['entry_TNX_Close'] = tnx_df.loc[date, 'Close']
                except KeyError:
                    pass

                if inst_se.margin_mode == _inst.INITIAL_MARGIN:
                    # Futures short: integer contracts, reserve initial margin, pay commission.
                    # Short-sale fill is unfavourable (lower), mirroring the long-side "buy"
                    # slippage above. `ep` stays the RAW anchor for the stop/target levels
                    # already computed from it (_s_stop/_s_target); this slipped price is
                    # only the realized fill used for margin/notional/P&L accounting.
                    _s_entry_fill = _inst.apply_slippage(inst_se, ep, "sell")
                    _free = cash - reserved_margin
                    _s_sizing_method = CONFIG.get('position_sizing_method', 'fixed')
                    if _s_sizing_method == "risk_pct_capped":
                        # Mirror of the long-side risk_pct_capped branch. _s_ir
                        # (initial risk in points) is already computed above,
                        # before this dispatch -- unlike the long path, the
                        # short path sets its stop before sizing.
                        if _s_ir and _s_ir > 0:
                            _risk_budget = max(total_equity, 0.0) * CONFIG.get("risk_pct_per_trade", 0.01)
                            _raw_contracts = np.floor(_risk_budget / (_s_ir * inst_se.point_value))
                            _cap = CONFIG.get("max_contracts_cap", 20)
                            shares = max(0.0, min(_raw_contracts, _cap))
                        else:
                            shares = 0.0
                    elif _s_sizing_method == "fixed_contracts":
                        # Mirror of the long-side fixed_contracts branch: a fixed
                        # contract count every trade, never equity-scaled.
                        shares = float(CONFIG.get("fixed_contracts_per_trade", 1))
                    else:
                        alloc = min(total_equity * allocation_pct, _free)
                        if alloc <= 0:
                            continue
                        # Size off margin capacity, not full notional (mirror of the long-side
                        # fix): dividing the target dollar amount by point_value treats it as
                        # unlevered notional, which for a leveraged futures contract eventually
                        # floors to 0 contracts forever as price appreciates.
                        _s_per_contract_margin = _inst.margin_required(inst_se, 1, ep)
                        shares = _inst.round_units(inst_se, alloc / _s_per_contract_margin) if _s_per_contract_margin > 0 else 0.0
                    if shares < 1:
                        continue
                    _s_margin = _inst.margin_required(inst_se, shares, _s_entry_fill)
                    commission = _inst.commission(inst_se, shares)
                    if _s_margin + commission > cash - reserved_margin:
                        continue
                    reserved_margin += _s_margin
                    cash -= commission
                    short_positions[symbol] = {
                        'entry_date': date, 'entry_price': _s_entry_fill, 'raw_entry_price': ep,
                        'shares': shares, 'notional': _inst.notional(inst_se, shares, _s_entry_fill),
                        'total_borrow_cost': 0.0, 'margin': _s_margin,
                        'stop_loss_level': _s_stop, 'initial_stop_loss_level': _s_stop,
                        'trail_target': _s_target, 'atr_locked': _s_atr,
                        'trail_anchor': _s_trail_anchor,
                        'trail_armed': False, 'initial_risk': _s_ir, 'features': _s_features,
                    }
                else:
                    alloc = min(total_equity * allocation_pct, cash)
                    if alloc <= 0:
                        continue
                    shares = alloc / ep
                    commission = _inst.commission(inst_se, shares)
                    cash -= commission   # proceeds and collateral cancel; only commission is a real cash cost
                    short_positions[symbol] = {
                        'entry_date': date, 'entry_price': ep,
                        'shares': shares, 'notional': shares * ep, 'total_borrow_cost': 0.0,
                        'margin': 0.0,
                        'stop_loss_level': _s_stop, 'initial_stop_loss_level': _s_stop,
                        'trail_target': _s_target, 'atr_locked': _s_atr,
                        'trail_anchor': _s_trail_anchor,
                        'trail_armed': False, 'initial_risk': _s_ir, 'features': _s_features,
                    }

                # --- ENTRY-BAR EVALUATION (opt-in, mirror of the long entry-bar check) ---
                if (_intrabar_on and stop_config.get("type") == "trailing_atr"
                        and short_positions[symbol].get('trail_target') is not None):
                    _spos0 = short_positions[symbol]
                    _hi0 = df.loc[date].get('High')
                    _lo0 = df.loc[date].get('Low')
                    _wbars0 = _intrabar.window_bars(intrabar_data.get(symbol), date,
                                                    next_trading_dates[symbol].get(date))
                    _dec0, _fill0 = _prearm_decision(
                        _hi0, _lo0, _spos0['stop_loss_level'], _spos0['trail_target'],
                        _wbars0, side="short")
                    if _dec0 == "stop":
                        _close_short_now(symbol, _spos0, date, _fill0, f"Stop Loss ({stop_config['type']})")
                        del short_positions[symbol]
                    else:
                        _update_trailing_atr_stop(_spos0, df, date, stop_config, side="short")

        # --- POSITION ENTRY LOGIC ---
        if _priority == "signal_date":
            def _long_sig_key(item):
                sym, _df = item
                if date not in _df.index:
                    return (1, "", sym)
                sd = prev_trading_dates[sym].get(date) if execution_time == "open" else date
                if (pd.notna(sd) and sym in signals and sd in signals[sym].index
                        and signals[sym].loc[sd] == 1):
                    return (0, str(sd), sym)
                return (1, "", sym)
            _entry_items = sorted(portfolio_data.items(), key=_long_sig_key)
        elif _priority == "random_seed":
            _rng_long = _random.Random(CONFIG.get("entry_random_seed", 42))
            _entry_items = sorted(portfolio_data.items(), key=lambda x: x[0])
            _rng_long.shuffle(_entry_items)
        else:
            _entry_items = sorted(portfolio_data.items(), key=lambda x: x[0])
        for symbol, df in _entry_items:
            # <-- NEW CHECK: If the current date doesn't exist for this stock,
            # we cannot possibly enter a position.
            if date not in df.index:
                continue

            if symbol in positions: continue
            if (not _pit_flag(symbol, date, '_pit_member', True)
                    or _pit_flag(symbol, date, '_pit_force_exit', False)):
                continue
            raw_entry_price, entry_exec_date = np.nan, pd.NaT
            signal_date = prev_trading_dates[symbol].get(date) if execution_time == 'open' else date
            if pd.notna(signal_date) and signal_date in signals[symbol].index and signals[symbol].loc[signal_date] == 1:
                raw_entry_price = df.loc[date].get('Open' if execution_time == 'open' else 'Close')
                entry_exec_date = date

            if pd.isna(raw_entry_price): continue

            entry_price = _inst.apply_slippage(instruments[symbol], raw_entry_price, "buy")

            if entry_price > 0 and cash > 0:
                # --- PER-SIGNAL SIZE MULTIPLIER ---
                # Apply per-signal size multiplier when the strategy provides one
                # (e.g. 0.6x / 0.8x / 1.0x based on ML probability band). Multiplied
                # into the sized position below, before the portfolio heat check.
                _size_mult = 1.0
                if size_mults is not None and symbol in size_mults:
                    _sm_val = size_mults[symbol].get(signal_date, np.nan)
                    if pd.notna(_sm_val) and _sm_val > 0:
                        _size_mult = float(_sm_val)

                # --- POSITION SIZING ---
                sizing_method = CONFIG.get('position_sizing_method', 'fixed')
                sizing_kwargs = {}

                # For risk_parity: derive stop_distance_pct from the configured stop so
                # sizing uses the actual stop rather than always falling back to 3x ATR.
                if sizing_method == "risk_parity":
                    stop_type = stop_config.get("type", "none")
                    if stop_type == "percentage":
                        sizing_kwargs["stop_distance_pct"] = stop_config.get("value", 0.05)
                    elif stop_type == "atr":
                        _day_before = prev_trading_dates[symbol].get(entry_exec_date)
                        if _day_before is not None and _day_before in df.index and "ATR_14" in df.columns:
                            _atr = df.loc[_day_before, 'ATR_14']
                            _close = df.loc[_day_before, 'Close']
                            if pd.notna(_atr) and pd.notna(_close) and _close > 0:
                                sizing_kwargs["stop_distance_pct"] = _inst.atr_stop_distance_pct(
                                    _atr, stop_config.get("multiplier", 3.0), _close)

                # For kelly: compute rolling stats from completed trades so sizing
                # actually adapts to the strategy's live performance.
                if sizing_method == "kelly" and len(trade_log) >= 10:
                    _wins = [t for t in trade_log if t.get("is_win") == 1 and t.get("ProfitPct") is not None]
                    _losses = [t for t in trade_log if t.get("is_win") == 0 and t.get("ProfitPct") is not None]
                    if _wins and _losses:
                        sizing_kwargs["win_rate"] = len(_wins) / len(trade_log)
                        sizing_kwargs["avg_win"] = sum(t["ProfitPct"] for t in _wins) / len(_wins)
                        sizing_kwargs["avg_loss"] = sum(abs(t["ProfitPct"]) for t in _losses) / len(_losses)

                # Slice to current date to prevent look-ahead bias: vol_parity and
                # risk_parity use .iloc[-1] on the passed DataFrame, so passing the
                # full history would use a future ATR value on early simulation dates.
                inst = instruments[symbol]
                if sizing_method == "risk_pct_capped":
                    # Compounding risk-percent sizing: risk risk_pct_per_trade of
                    # CURRENT (compounding) equity per trade, contracts = floor(
                    # risk_budget / (stop_dist_pts * point_value)), hard-capped at
                    # max_contracts_cap. This compounds with account growth --
                    # unlike fixed_contracts, which never scales.
                    _rp_stop_dist_pts = None
                    _stype_sz = stop_config.get("type", "none")
                    if _stype_sz == "trailing_atr":
                        _dbe_sz = prev_trading_dates[symbol].get(entry_exec_date)
                        if pd.notna(_dbe_sz) and _dbe_sz in df.index:
                            _atr_sz = df.loc[_dbe_sz].get('ATR_14')
                            if pd.notna(_atr_sz):
                                _eff_sz = float(_atr_sz) * stop_config.get("stop_mult", 1.0)
                                _pc_sz = stop_config.get("point_cap")
                                if _pc_sz is not None and _pc_sz > 0:
                                    _eff_sz = min(_eff_sz, _pc_sz)
                                _rp_stop_dist_pts = _eff_sz
                    elif _stype_sz == "percentage":
                        # Use the RAW pre-slippage price for consistency with the
                        # stop-level anchor computed later in this function for
                        # the same stop type -- using the slipped entry_price here
                        # would size against a slightly different (shrunk) stop
                        # distance than the one the position is actually stopped at.
                        _rp_stop_dist_pts = stop_config.get("value", 0.05) * raw_entry_price
                    elif _stype_sz == "atr":
                        _dbe_sz = prev_trading_dates[symbol].get(entry_exec_date)
                        if pd.notna(_dbe_sz) and _dbe_sz in df.index:
                            _atr_sz = df.loc[_dbe_sz].get('ATR_14')
                            if pd.notna(_atr_sz):
                                _eff_sz = float(_atr_sz) * stop_config.get("multiplier", 3.0)
                                _pc_sz = stop_config.get("point_cap")
                                if _pc_sz is not None and _pc_sz > 0:
                                    _eff_sz = min(_eff_sz, _pc_sz)
                                _rp_stop_dist_pts = _eff_sz

                    if _rp_stop_dist_pts and _rp_stop_dist_pts > 0:
                        _risk_budget = max(total_equity, 0.0) * CONFIG.get("risk_pct_per_trade", 0.01)
                        _raw_contracts = np.floor(_risk_budget / (_rp_stop_dist_pts * inst.point_value))
                        _cap = CONFIG.get("max_contracts_cap", 20)
                        shares = max(0.0, min(_raw_contracts, _cap)) * _size_mult
                        # The portfolio heat check below falls back to the flat
                        # target_risk_per_trade (2%) proxy when stop_distance_pct is
                        # absent from sizing_kwargs. For risk_pct_capped the position
                        # was already sized to risk exactly risk_pct_per_trade (1%) of
                        # equity via the REAL stop distance -- which is typically much
                        # smaller than 2% of price for this strategy (point_cap=60 on
                        # a multi-thousand-point index is a small fraction). Passing the
                        # flat 2% proxy instead of the true stop_dist_pts/entry_price
                        # fraction overstates dollar risk on every trade (by ~10-15x
                        # observed), so check_portfolio_heat() spuriously rejects
                        # already-correctly-risk-capped trades once notional grows
                        # large relative to equity. Populate the real fraction so the
                        # heat check evaluates the position's actual risk. Divide by
                        # raw_entry_price (not the slipped entry_price) to match the
                        # anchor _rp_stop_dist_pts was computed against above.
                        sizing_kwargs["stop_distance_pct"] = _rp_stop_dist_pts / raw_entry_price
                    else:
                        shares = 0.0
                elif sizing_method == "fixed_contracts":
                    # Fixed contract-count sizing: EXACTLY N contracts every
                    # trade, forever -- never scaled to equity. This is already
                    # a contract count, not a dollar-notional target, so it
                    # bypasses calculate_position_size and the point_value/
                    # margin conversion below entirely.
                    shares = float(CONFIG.get("fixed_contracts_per_trade", 1)) * _size_mult
                else:
                    shares = calculate_position_size(
                        method=sizing_method,
                        equity=total_equity,
                        price=entry_price,
                        symbol_data=df.loc[:date],
                        config=CONFIG,
                        allocation_pct=allocation_pct,  # honour the caller's allocation, not CONFIG only
                        **sizing_kwargs
                    )

                    # Apply the per-signal size multiplier (entry-queue / ML band)
                    # to the sized position before the heat check.
                    shares = shares * _size_mult

                    # Futures size in contracts: the sizing methods return a dollar-notional
                    # based size; dividing out $/point converts it to contracts (pv=1 for equities).
                    if inst.margin_mode == _inst.INITIAL_MARGIN:
                        # Margined (leveraged) futures: the sizing target is a dollar
                        # amount of equity to commit. Converting it via point_value
                        # treats that dollar amount as full unlevered notional, so as
                        # price appreciates the position size keeps shrinking below 1
                        # contract and, once it floors to 0, equity never moves again
                        # and it never recovers. Size off margin_required() instead,
                        # which is what the account actually posts to hold the contract.
                        # Checked BEFORE point_value (rather than nested inside a
                        # `point_value != 1.0` gate) so a margined instrument whose
                        # point_value happens to be 1.0 still gets margin-based sizing
                        # instead of silently falling through as if it were unlevered.
                        _target_dollars = shares * entry_price
                        _per_contract_margin = _inst.margin_required(inst, 1, entry_price)
                        shares = _target_dollars / _per_contract_margin if _per_contract_margin > 0 else 0.0
                    elif inst.point_value != 1.0:
                        shares = shares / inst.point_value

                # --- PORTFOLIO HEAT CHECK ---
                # Compute the dollar risk this position adds. For methods with a
                # known stop distance we use that; otherwise fall back to the
                # target_risk_per_trade parameter (which is what vol/risk parity
                # sized against anyway). notional() applies $/point for futures.
                _stop_dist = sizing_kwargs.get("stop_distance_pct") or CONFIG.get("target_risk_per_trade", 0.02)
                new_position_risk = _inst.notional(inst, shares, entry_price) * _stop_dist
                max_heat = CONFIG.get("max_portfolio_heat", 1.0)
                if not check_portfolio_heat(positions, new_position_risk, total_equity, max_heat):
                    continue

                # Cash constraint (equity full-notional pre-clamp; futures clamp on margin below)
                if inst.margin_mode != _inst.INITIAL_MARGIN:
                    capital_needed = _inst.margin_required(inst, shares, entry_price)
                    if capital_needed > cash:
                        shares = cash / entry_price

                # --- VOLUME-BASED LIQUIDITY FILTER ---
                max_pct_adv = CONFIG.get('max_pct_adv') or 0
                if max_pct_adv > 0 and 'Volume' in df.columns:
                    adv_20 = _daily_adv(df['Volume'], entry_exec_date, symbol)
                    if pd.notna(adv_20) and adv_20 > 0:
                        max_shares_allowed = adv_20 * max_pct_adv
                        if max_shares_allowed <= 0:
                            continue
                        shares = min(shares, max_shares_allowed)

                # --- VOLUME-BASED MARKET IMPACT ---
                entry_impact_bps = 0.0
                impact_coeff = CONFIG.get('volume_impact_coeff', 0.0)
                if impact_coeff > 0 and 'Volume' in df.columns:
                    adv_20_impact = _daily_adv(df['Volume'], entry_exec_date, symbol)
                    if pd.notna(adv_20_impact) and adv_20_impact > 0:
                        order_pct_of_adv = shares / adv_20_impact
                        impact_additional = impact_coeff * np.sqrt(order_pct_of_adv)
                        entry_price = entry_price * (1 + impact_additional)
                        entry_impact_bps = round(impact_additional * 10000, 1)

                # Integer contracts for futures; fractional shares pass through for equities.
                shares = _inst.round_units(inst, shares)

                # --- AFFORDABILITY (margin-mode aware) ---
                commission_cost = _inst.commission(inst, shares)
                if inst.margin_mode == _inst.INITIAL_MARGIN:
                    # Futures: reserve initial margin against free buying power; the only
                    # cash outlay at entry is commission (margin is collateral, not spent).
                    _margin = _inst.margin_required(inst, shares, entry_price)
                    _free = cash - reserved_margin
                    if _margin + commission_cost > _free:
                        _per = _inst.margin_required(inst, 1, entry_price)
                        shares = _inst.round_units(inst, (_free - commission_cost) / _per) if _per > 0 else 0.0
                        commission_cost = _inst.commission(inst, shares)
                        _margin = _inst.margin_required(inst, shares, entry_price)
                    can_afford = shares >= 1 and (_margin + commission_cost) <= (cash - reserved_margin)
                else:
                    # Equity cash_full: full notional + commission debited from cash.
                    total_cost = _inst.margin_required(inst, shares, entry_price) + commission_cost
                    if total_cost > cash:
                        # Robustly calculate the absolute maximum number of shares we can possibly afford
                        shares = cash / (entry_price + CONFIG['commission_per_share'])
                        if shares <= 0: continue  # Cannot afford even a fraction of a share
                        # Recalculate final total cost with the affordable share size
                        total_cost = (shares * entry_price) + (shares * CONFIG['commission_per_share'])
                    can_afford = cash >= total_cost and shares > 0.001

                # Final check: Ensure we can afford the trade and it's a meaningful size
                if can_afford:
                    # --- CAPTURE FEATURES AT ENTRY ---
                    features = {}
                    try:
                        features['entry_RSI_14'] = df.loc[entry_exec_date, 'RSI_14']
                        features['entry_ATR_14_pct'] = df.loc[entry_exec_date, 'ATR_14_pct']
                        features['entry_SMA200_dist_pct'] = df.loc[entry_exec_date, 'SMA200_dist_pct']
                        features['entry_Volume_Spike'] = df.loc[entry_exec_date, 'Volume_Spike']
                        if spy_df is not None:
                            features['entry_SPY_RSI_14'] = spy_df.loc[entry_exec_date, 'RSI_14']
                            features['entry_SPY_SMA200_dist_pct'] = spy_df.loc[entry_exec_date, 'SMA200_dist_pct']
                        if vix_df is not None:
                            features['entry_VIX_Close'] = vix_df.loc[entry_exec_date, 'Close']
                        if tnx_df is not None:
                            features['entry_TNX_Close'] = tnx_df.loc[entry_exec_date, 'Close']
                    except KeyError:
                        pass
                    
                    # --- STRATEGIC DECISION: ATR TRAILING STOP CALCULATION METHOD ---
                    #
                    # This system implements a "Next Day Activation" model for ATR trailing stops,
                    # which aligns with a realistic, end-of-day trading workflow. This is a deliberate
                    # choice over other interpretations.
                    #
                    # INTERPRETATION A (The Implemented Logic):
                    #   - PURPOSE: To model a trader who analyzes the market after the close and sets
                    #     orders for the NEXT trading session. It strictly avoids look-ahead bias.
                    #   - INITIAL STOP: Calculated using the CLOSE and ATR from the day BEFORE entry (the signal day).
                    #     This value becomes the active stop for the entire entry day.
                    #   - TRAILING STOP: The active stop for any given day (Day D) is the value that was
                    #     calculated at the close of the PREVIOUS day (Day D-1). A new potential stop is
                    #     calculated at the close of Day D, which will then become active on Day D+1.
                    #   - CHECK: The Low of Day D is compared against the stop calculated on Day D-1.
                    #
                    # INTERPRETATION B (Alternative, Not Used Here):
                    #   - LOGIC: The stop is calculated and updated using the current day's data
                    #     (e.g., `entry_price - (ATR_on_entry_day * multiplier)`).
                    #   - REASON FOR REJECTION: While this simulates setting a stop immediately after a
                    #     fill, it introduces a slight look-ahead bias in a daily-bar backtest, as
                    #     the full day's ATR (which depends on the day's High and Low) would not be
                    #     known at the market open. Interpretation A is a more conservative and
                    #     academically rigorous approach for daily-bar systems.
                    #
                    # By adhering strictly to Interpretation A, this code ensures that all stop-loss
                    # decisions are based only on information that would have been available *before*
                    # the trading session in which the stop is active.
                    # ---
                    # --- SET INITIAL STOP LOSS ONCE ENTRY PRICE IS KNOWN ---
                    stop_loss_level = np.nan
                    _trail_target = None   # arm price for trailing_atr (None otherwise)
                    _atr_locked = None     # ATR frozen at the breakout bar for trailing_atr
                    _trail_anchor = None   # stop/target/floor anchor price for trailing_atr
                    _stype = stop_config.get("type")
                    if _stype in ('percentage', 'points'):
                        # Margined instruments (futures): anchor to the RAW pre-slippage
                        # price, not the slipped fill. Slippage is a separate, symmetric
                        # friction applied to the realized entry/exit fills; for futures it
                        # must not also shift where the stop/target levels sit, or every
                        # stop distance is silently shrunk (long side) by the entry-slippage
                        # amount.
                        #
                        # Cash-full instruments (equities): keep the PRE-EXISTING behaviour
                        # of anchoring to the slipped `entry_price`. The equity backtest path
                        # is protected byte-for-byte by the golden-master suite
                        # (tests/fixtures/engine_golden_master.json); changing this anchor
                        # for equities would silently alter historical equity results, which
                        # is out of scope for this futures-only fix.
                        _stop_anchor = (
                            raw_entry_price if inst.margin_mode == _inst.INITIAL_MARGIN
                            else entry_price)
                        stop_loss_level = _inst.stop_level(
                            instruments[symbol], _stop_anchor, stop_config, side="long")

                    elif _stype == 'atr':
                        # Get the data from the day BEFORE entry (the signal day)
                        day_before_entry = prev_trading_dates[symbol].get(entry_exec_date)

                        if pd.notna(day_before_entry) and day_before_entry in df.index:
                            day_before_data = df.loc[day_before_entry]
                            atr_before_entry = day_before_data.get('ATR_14')
                            close_before_entry = day_before_data.get('Close')

                            if pd.notna(atr_before_entry) and pd.notna(close_before_entry):
                                # The initial stop is based on the previous day's data,
                                # matching the "Next Day Activation" spec. point_cap (if set)
                                # clips the ATR distance to a fixed point ceiling per trade.
                                stop_loss_level = _inst.atr_stop_level(
                                    close_before_entry, atr_before_entry,
                                    stop_config.get("multiplier", 3.0), side="long",
                                    point_cap=stop_config.get("point_cap"))

                    elif _stype == 'trailing_atr':
                        # Sleeve A mechanic. Lock ATR at the breakout (signal) bar and keep it
                        # fixed for the whole trade — stop, target, and trail all use this one
                        # value (never recomputed live). Initial stop is a point-capped ATR stop;
                        # the arm target is a reward:risk ratio off that CAPPED stop so the cap
                        # propagates into the target:
                        #   eff_stop_dist = min(stop_mult*atr, point_cap)
                        #   target_dist   = eff_stop_dist * (t1_mult / stop_mult)
                        _dbe = prev_trading_dates[symbol].get(entry_exec_date)
                        _atr_b = df.loc[_dbe].get('ATR_14') if (pd.notna(_dbe) and _dbe in df.index) else np.nan
                        if pd.notna(_atr_b):
                            _atr_locked = float(_atr_b)
                            _stop_mult = stop_config.get("stop_mult", 1.0)
                            _eff_stop_dist = _atr_locked * _stop_mult
                            _pc = stop_config.get("point_cap")
                            if _pc is not None and _pc > 0:
                                _eff_stop_dist = min(_eff_stop_dist, _pc)
                            # Anchor to the RAW pre-slippage price for margined
                            # instruments (futures) and to the slipped fill for
                            # cash-full instruments (equities) — mirrors the
                            # percentage/points _stop_anchor gating pattern (#238).
                            _trail_anchor = (
                                raw_entry_price if inst.margin_mode == _inst.INITIAL_MARGIN
                                else entry_price)
                            stop_loss_level = _trail_anchor - _eff_stop_dist
                            _t1_mult = stop_config.get("t1_mult", 0.0)
                            if _stop_mult > 0 and _t1_mult > 0:
                                _trail_target = _trail_anchor + _eff_stop_dist * (_t1_mult / _stop_mult)

                    positions[symbol] = {
                        'shares': shares, 'entry_price': entry_price,
                        'raw_entry_price': raw_entry_price,
                        'entry_date': entry_exec_date, 'features': features,
                        'stop_loss_level': stop_loss_level,
                        'initial_stop_loss_level': stop_loss_level,
                        'entry_impact_bps': entry_impact_bps,
                        'size_mult': _size_mult,
                        'risk': new_position_risk,
                        'trail_armed': False,
                        'trail_target': _trail_target,
                        'atr_locked': _atr_locked,
                        'trail_anchor': _trail_anchor,
                        'margin': _margin if inst.margin_mode == _inst.INITIAL_MARGIN else 0.0,
                    }
                    if inst.margin_mode == _inst.INITIAL_MARGIN:
                        reserved_margin += _margin
                        cash -= commission_cost
                    else:
                        cash -= total_cost

                    # --- ENTRY-BAR EVALUATION (opt-in, trailing_atr + intrabar_resolution) ---
                    # The reference Sleeve A mechanic checks the stop/target starting ON
                    # the entry bar itself (leg1 loop is `range(entry_i, cap+1)`), but the
                    # position-management loop above only re-checks `positions` starting
                    # the NEXT date. Reproduce the entry-bar check here: if the entry bar's
                    # own High/Low already resolves the stop or the arm target, apply it
                    # immediately instead of silently deferring to the next bar.
                    if (_intrabar_on and stop_config.get("type") == "trailing_atr"
                            and positions[symbol].get('trail_target') is not None):
                        _pos0 = positions[symbol]
                        _hi0 = df.loc[date].get('High')
                        _lo0 = df.loc[date].get('Low')
                        _wbars0 = _intrabar.window_bars(intrabar_data.get(symbol), date,
                                                        next_trading_dates[symbol].get(date))
                        _dec0, _fill0 = _prearm_decision(
                            _hi0, _lo0, _pos0['stop_loss_level'], _pos0['trail_target'],
                            _wbars0, side="long")
                        if _dec0 == "stop":
                            _close_long_now(symbol, _pos0, date, _fill0, f"Stop Loss ({stop_config['type']})")
                            del positions[symbol]
                        else:
                            # "arm" / "hold": _update_trailing_atr_stop arms + seeds off
                            # THIS bar's High when the target was already reached (no-op
                            # otherwise), matching the reference's same-bar arm.
                            _update_trailing_atr_stop(_pos0, df, date, stop_config, side="long")

    exclude_open = CONFIG.get('exclude_open_positions', False)

    # --- SURVIVORSHIP BIAS: FORCE-CLOSE DELISTED OPEN POSITIONS ---
    # This MUST run before the End-of-Backtest mark-to-market block below.
    # Otherwise, a still-open position in a delisted symbol would either be
    # marked-to-market at its last bar (exclude_open=False) or dropped entirely
    # (exclude_open=True) — in both cases the delisting loss would be silently
    # ignored, defeating the purpose of survivorship handling.
    survivorship_stats = {}
    # Each entry: (symbol, delisting_ts, shares, exit_price) — used to correct the
    # equity curve, whose daily-loop values still mark the position to market.
    _delisting_corrections = []
    if delisting_dates and CONFIG.get("include_delisted", False):
        _price_assumption = CONFIG.get("delisting_price_assumption", "last_close")
        _positions_delisted = 0
        _total_delisting_loss = 0.0
        for symbol in list(positions.keys()):
            if symbol not in delisting_dates:
                continue
            pos = positions[symbol]
            delisting_ts = pd.Timestamp(delisting_dates[symbol])
            entry_ts = pos['entry_date']
            if delisting_ts < entry_ts:
                continue  # delisted before we entered — leave for normal handling

            # Determine exit price under the configured assumption.
            if _price_assumption == "zero":
                exit_price = 0.0
            else:  # "last_close": last available Close on/before the delisting date
                exit_price = pos['entry_price']  # fallback
                sym_df = portfolio_data.get(symbol)
                if sym_df is not None and not sym_df.empty:
                    prior = sym_df.loc[sym_df.index <= delisting_ts, 'Close'].dropna()
                    if not prior.empty:
                        exit_price = float(prior.iloc[-1])

            _dl_inst = instruments[symbol]
            commission = _inst.commission(_dl_inst, pos['shares'])
            if _dl_inst.margin_mode == _inst.INITIAL_MARGIN:
                # Futures: realise P&L (via $/point) into cash and release reserved
                # margin — cash never held the notional, so crediting proceeds would
                # inject phantom capital.
                gross_pnl = (exit_price - pos['entry_price']) * pos['shares'] * _dl_inst.point_value
                cash += gross_pnl - commission
                reserved_margin -= pos.get('margin', 0.0)
                net_pnl = gross_pnl - (2 * commission)
            else:
                net_pnl = ((exit_price - pos['entry_price']) * pos['shares']) - (2 * commission)
                # Realised proceeds return to cash (delisting is a real liquidation).
                cash += (pos['shares'] * exit_price) - commission

            _initial_sl = pos.get('initial_stop_loss_level')
            if pd.notna(_initial_sl) and _initial_sl > 0 and _initial_sl < pos['entry_price']:
                _initial_risk_per_share = pos['entry_price'] - _initial_sl
            else:
                _initial_risk_per_share = pos['entry_price'] * 0.01
            _r_multiple = (net_pnl / (_initial_risk_per_share * pos['shares'] * _dl_inst.point_value)
                           if _initial_risk_per_share > 0 and pos['shares'] > 0 else None)

            trade_counter += 1
            _pos_value = _inst.notional(_dl_inst, pos['shares'], pos['entry_price'])
            trade_log.append({
                'Symbol': symbol, 'Trade': f"Long {trade_counter}",
                'EntryDate': pos['entry_date'].isoformat(), 'EntryPrice': pos['entry_price'],
                'ExitDate': delisting_ts.isoformat(), 'ExitPrice': exit_price,
                'Profit': net_pnl, 'ProfitPct': net_pnl / _pos_value if _pos_value > 0 else -1.0,
                'Shares': pos['shares'], 'is_win': 1 if net_pnl > 0 else 0,
                'HoldDuration': _hold_duration_days(pos['entry_date'], delisting_ts),
                'MAE_pct': 0.0, 'MFE_pct': 0.0, 'ExitReason': "Delisting",
                'InitialRisk': _initial_risk_per_share, 'RMultiple': _r_multiple,
                **pos.get('features', {}),
            })
            _delisting_corrections.append((symbol, delisting_ts, pos['shares'], exit_price))
            _positions_delisted += 1
            _total_delisting_loss += net_pnl
            del positions[symbol]  # exclude from EoB mark-to-market / drop logic

        survivorship_stats = {
            "positions_delisted": _positions_delisted,
            "total_delisting_loss": _total_delisting_loss,
            "delisting_loss_pct": (_total_delisting_loss / initial_capital
                                   if initial_capital > 0 else 0.0),
        }

    # --- START: MARK-TO-MARKET LOGIC ---
    # After the main loop, check for any positions that are still open.
    # Skipped when exclude_open_positions=True (realized-only reporting mode).
    last_date = all_dates[-1]
    if positions and not exclude_open:
        for symbol, pos in list(positions.items()):
            # Get the closing price on the very last day of the backtest
            last_price = portfolio_data[symbol]['Close'].get(last_date)
            if pd.notna(last_price):
                exit_date = last_date
                exit_reason = "End of Backtest"

                # --- This is the same logging logic from the main loop ---
                trade_df = portfolio_data[symbol].loc[pos['entry_date']:exit_date]
                mae_pct = (trade_df['Low'].min() - pos['entry_price']) / pos['entry_price'] if not trade_df.empty else 0.0
                mfe_pct = (trade_df['High'].max() - pos['entry_price']) / pos['entry_price'] if not trade_df.empty else 0.0
                trade_counter += 1
                _mtm_inst = instruments[symbol]
                exit_price = _inst.apply_slippage(_mtm_inst, last_price, "sell")
                commission = _inst.commission(_mtm_inst, pos['shares'])
                # We don't add to cash as this is a hypothetical close
                net_pnl = ((exit_price - pos['entry_price']) * pos['shares'] * _mtm_inst.point_value) - (2 * commission)

                # --- Initial Risk and R-Multiple ---
                _initial_sl = pos.get('initial_stop_loss_level')
                if pd.notna(_initial_sl) and _initial_sl > 0 and _initial_sl < pos['entry_price']:
                    _initial_risk_per_share = pos['entry_price'] - _initial_sl
                else:
                    _initial_risk_per_share = pos['entry_price'] * 0.01
                _r_multiple = (net_pnl / (_initial_risk_per_share * pos['shares'] * _mtm_inst.point_value)
                               if _initial_risk_per_share > 0 and pos['shares'] > 0 else None)

                log_entry = {'Symbol': symbol, 'Trade': f"Long {trade_counter}", 'EntryDate': pos['entry_date'].isoformat(), 'EntryPrice': pos['entry_price'], 'ExitDate': exit_date.isoformat(), 'ExitPrice': exit_price, 'Profit': net_pnl, 'ProfitPct': net_pnl / _inst.notional(_mtm_inst, pos['shares'], pos['entry_price']), 'Shares': pos['shares'], 'is_win': 1 if net_pnl > 0 else 0, 'HoldDuration': _hold_duration_days(pos['entry_date'], exit_date), 'MAE_pct': mae_pct, 'MFE_pct': mfe_pct, 'ExitReason': exit_reason, 'InitialRisk': _initial_risk_per_share, 'RMultiple': _r_multiple, **pos.get('features', {})}
                trade_log.append(log_entry)

    # Open SHORTS still on the book at the last bar — mark to market (parallel to longs).
    # Without this an open short vanishes from the trade log (and, if it's the only
    # trade, run returns None), even though the equity curve already carries its MTM.
    if short_positions and not exclude_open:
        for symbol, spos in list(short_positions.items()):
            last_price = portfolio_data[symbol]['Close'].get(last_date)
            if pd.isna(last_price):
                continue
            _s_inst = instruments[symbol]
            cover_slip = _inst.apply_slippage(_s_inst, last_price, "buy")
            commission = _inst.commission(_s_inst, spos['shares'])
            _gross = (spos['shares'] * (spos['entry_price'] - cover_slip)) * _s_inst.point_value
            net_pnl = _gross - (2 * commission) - spos.get('total_borrow_cost', 0.0)
            # hypothetical close — do not touch cash (parallel to the long EoB branch)
            trade_counter += 1
            _std = portfolio_data[symbol].loc[spos['entry_date']:last_date]
            if not _std.empty:
                _ep = spos['entry_price']
                _s_mfe = (_ep - _std['Low'].min()) / _ep
                _s_mae = (_std['High'].max() - _ep) / _ep
            else:
                _s_mfe, _s_mae = 0.0, 0.0
            _s_ir = spos.get('initial_risk')
            _s_rm = (net_pnl / (_s_ir * spos['shares'] * _s_inst.point_value)
                     if _s_ir and _s_ir > 0 and spos['shares'] > 0 else None)
            trade_log.append({
                'Symbol': symbol, 'Trade': f"Short {trade_counter}",
                'EntryDate': spos['entry_date'].isoformat(), 'EntryPrice': spos['entry_price'],
                'ExitDate': last_date.isoformat(), 'ExitPrice': cover_slip,
                'Profit': net_pnl, 'ProfitPct': net_pnl / spos['notional'] if spos['notional'] > 0 else 0,
                'Shares': spos['shares'], 'is_win': 1 if net_pnl > 0 else 0,
                'HoldDuration': _hold_duration_days(spos['entry_date'], last_date),
                'MAE_pct': _s_mae, 'MFE_pct': _s_mfe, 'ExitReason': "End of Backtest",
                'InitialRisk': _s_ir if (_s_ir and _s_ir > 0) else 0.0, 'RMultiple': _s_rm,
            })
            trade_log[-1].update(spos.get('features', {}))
    # --- END: MARK-TO-MARKET LOGIC ---

    pnl_list = [t['Profit'] for t in trade_log]
    if not pnl_list: return None

    # --- SURVIVORSHIP BIAS: CORRECT EQUITY CURVE FOR DELISTED POSITIONS ---
    # The daily loop marked each now-delisted position to market for every bar
    # of the hold, including bars on/after the delisting date. From the delisting
    # date forward the position is no longer held — its value is the realised
    # proceeds (shares * exit_price), which were added to cash above. So for each
    # date >= delisting we replace the marked-to-market contribution
    # (shares * Close[date]) with the frozen realised value (shares * exit_price).
    # This avoids double-counting the loss and keeps Sharpe/drawdown/CAGR correct.
    if _delisting_corrections:
        for symbol, delisting_ts, shares, exit_price in _delisting_corrections:
            sym_df = portfolio_data.get(symbol)
            if sym_df is None:
                continue
            mask = portfolio_timeline.index >= delisting_ts
            for dt in portfolio_timeline.index[mask]:
                if pd.isna(portfolio_timeline.loc[dt]):
                    continue
                # What the daily loop added for this symbol on this date.
                if dt in sym_df.index:
                    mtm_close = sym_df.loc[dt, 'Close']
                else:
                    prior_idx = sym_df.index[sym_df.index < dt]
                    mtm_close = sym_df.loc[prior_idx[-1], 'Close'] if len(prior_idx) else np.nan
                if pd.isna(mtm_close):
                    continue
                # x point_value: the daily loop's contribution was $/point-scaled
                # (unrealized_pnl for futures, market value with pv=1 for equities),
                # so the replacement delta must scale the same way.
                portfolio_timeline.loc[dt] += (shares * (exit_price - mtm_close)
                                               * instruments[symbol].point_value)

    duration_list = [t['HoldDuration'] for t in trade_log]
    if exclude_open:
        # Realized-only: headline P&L is the sum of closed trade profits only.
        final_pnl_percent = sum(pnl_list) / initial_capital
    else:
        final_pnl_percent = (portfolio_timeline.dropna().iloc[-1] / initial_capital) - 1
    metrics = calculate_advanced_metrics(pnl_list, portfolio_timeline.dropna(), duration_list)

    return {**metrics, "pnl_percent": final_pnl_percent, "Trades": len(pnl_list),
            "trade_pnl_list": pnl_list, "trade_log": trade_log, "initial_capital": initial_capital,
            "portfolio_timeline": portfolio_timeline.dropna(), **survivorship_stats}
