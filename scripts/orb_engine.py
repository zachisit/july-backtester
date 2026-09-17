"""
Instrument-agnostic intraday Opening Range Breakout (ORB) engine.

Strategy shape (the spec under test):
    * Opening range (OR) = first `or_minutes` of the NY cash session (09:30 ET).
    * Entry  = stop order at the OR extreme, armed only inside the trade window
               [09:30 + or_minutes, entry_cutoff].  Default cutoff 11:00 ET.
    * Stop   = the opposite OR extreme (or a fraction of OR width).
    * Exit   = R-multiple target, or flat at `time_exit` (default RTH close).

EXECUTION HONESTY (Gate 2)
--------------------------
Every fill in this engine is one a real order could have received:

  * Entry is a resting STOP order.  If the bar gapped through the trigger, the fill is the
    bar OPEN (worse than the trigger), never the trigger itself.
  * Stop exit is a resting STOP order.  If the bar gapped through the stop, the fill is the
    bar OPEN (worse), never the stop level.
  * Target exit is a resting LIMIT order.  If the bar gapped through the target, the fill is
    the bar OPEN (better) -- a limit fills at its price or better.
  * When one bar's range spans BOTH stop and target, the stop is assumed to fill first.
    Bar data cannot resolve the intrabar path, so the pessimistic branch is taken.
  * The entry bar is itself checked for a stop hit: there is no unprotected window between
    arming and enforcement. On that bar the stop fills at its LEVEL rather than the bar open,
    because the open happened before the order existed -- only a later bar boundary can gap.

`gap_aware=False` exists ONLY to measure how much of the P&L is an execution artifact.
It books fantasy fills at theoretical levels and must never be used for a headline number.

`fade=True` trades against the break instead of with it, on the same bars at the same trigger
prices. It is the matched placebo for "is the breakout direction informative?" -- pair it with
`stop_mode="frac"` so both directions risk the same amount and the comparison is fair.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Iterable

import numpy as np
import pandas as pd

RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)


@dataclass
class OrbParams:
    or_minutes: int = 15               # opening-range length
    entry_cutoff: time = time(11, 0)   # no new entries after this
    time_exit: time = time(15, 59)     # flat by this bar's close
    target_r: float | None = None      # R-multiple target; None = time exit only
    stop_mode: str = "opposite"        # "opposite" = other OR extreme, "frac" = frac of OR width
    stop_frac: float = 1.0             # used when stop_mode == "frac"
    buffer_ticks: float = 0.0          # trigger offset beyond the OR extreme, in ticks
    direction: str = "both"            # "both" | "long" | "short"
    fade: bool = False                 # True = trade AGAINST the breakout (matched placebo)
    allow_reentry: bool = False        # False = at most one trade per session
    min_or_ticks: float = 0.0          # skip session if OR narrower than this
    max_or_atr: float | None = None    # skip session if OR wider than this * ATR(or_atr_days)
    or_atr_days: int = 14

    def label(self) -> str:
        """Must identify a config UNIQUELY -- it is the join key for every report table."""
        t = "TE" if self.target_r is None else f"{self.target_r:g}R"
        mode = "fade" if self.fade else "follow"
        return (f"OR{self.or_minutes}m/cut{self.entry_cutoff.strftime('%H%M')}"
                f"/exit{self.time_exit.strftime('%H%M')}/{t}/{self.direction}/{mode}")


@dataclass
class Costs:
    tick_size: float = 0.25
    point_value: float = 50.0
    slippage_ticks: float = 1.0        # adverse ticks per fill (entry and each exit)
    commission_rt: float = 2.50        # round-trip commission, USD per contract

    def slip(self) -> float:
        return self.slippage_ticks * self.tick_size


@dataclass
class SessionResult:
    trades: list[dict] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)


def _sessionise(df: pd.DataFrame) -> Iterable[tuple[pd.Timestamp, pd.DataFrame]]:
    """Yield (session_date, RTH bars) for each cash session present in the data."""
    rth = df.between_time(RTH_OPEN, RTH_CLOSE, inclusive="left")
    for day, bars in rth.groupby(rth.index.date, sort=True):
        yield pd.Timestamp(day), bars


def _atr_by_session(df: pd.DataFrame, days: int) -> pd.Series:
    """Prior-day ATR of the RTH session, indexed by session date (shifted = no look-ahead)."""
    rth = df.between_time(RTH_OPEN, RTH_CLOSE, inclusive="left")
    g = rth.groupby(rth.index.date)
    daily = pd.DataFrame({"high": g["high"].max(), "low": g["low"].min(), "close": g["close"].last()})
    prev_close = daily["close"].shift(1)
    tr = pd.concat([
        daily["high"] - daily["low"],
        (daily["high"] - prev_close).abs(),
        (daily["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(days).mean().shift(1)


def run_orb(df: pd.DataFrame, params: OrbParams, costs: Costs,
            *, gap_aware: bool = True) -> SessionResult:
    """Run the ORB strategy over a 1-minute, tz-aware, NY-local OHLCV frame."""
    out = SessionResult()
    skip = out.skipped
    atr = _atr_by_session(df, params.or_atr_days) if params.max_or_atr else None
    buf = params.buffer_ticks * costs.tick_size
    slip = costs.slip()

    or_end_minutes = 9 * 60 + 30 + params.or_minutes

    for day, bars in _sessionise(df):
        mins = bars.index.hour * 60 + bars.index.minute
        or_bars = bars[mins < or_end_minutes]
        if len(or_bars) < max(2, params.or_minutes // 2):
            skip["thin_opening_range"] = skip.get("thin_opening_range", 0) + 1
            continue

        or_high = float(or_bars["high"].max())
        or_low = float(or_bars["low"].min())
        or_width = or_high - or_low
        if or_width <= 0:
            skip["zero_width_or"] = skip.get("zero_width_or", 0) + 1
            continue
        if or_width < params.min_or_ticks * costs.tick_size:
            skip["or_too_narrow"] = skip.get("or_too_narrow", 0) + 1
            continue
        if params.max_or_atr is not None:
            a = atr.get(day.date(), np.nan)
            if not np.isfinite(a) or a <= 0:
                skip["no_atr"] = skip.get("no_atr", 0) + 1
                continue
            if or_width > params.max_or_atr * a:
                skip["or_too_wide"] = skip.get("or_too_wide", 0) + 1
                continue

        cutoff = params.entry_cutoff.hour * 60 + params.entry_cutoff.minute
        texit = params.time_exit.hour * 60 + params.time_exit.minute
        scan = bars[(mins >= or_end_minutes) & (mins <= texit)]
        if scan.empty:
            skip["no_trade_window"] = skip.get("no_trade_window", 0) + 1
            continue

        long_trig = or_high + buf
        short_trig = or_low - buf
        open_trade: dict | None = None
        n_trades_today = 0

        smins = scan.index.hour * 60 + scan.index.minute
        arr = scan[["open", "high", "low", "close"]].to_numpy(dtype=float)
        idx = scan.index

        def manage(bar_i: int, trade: dict, *, same_bar: bool) -> tuple[float, str] | None:
            """Resolve an open trade against bar `bar_i`. Returns (fill, reason) or None.

            `same_bar` marks the bar the trade was opened on. A stop placed mid-bar cannot
            gap at that bar's open -- the open already happened before entry -- so the fill
            is the stop level itself. Only at a subsequent bar boundary can a gap occur.
            """
            o, h, l, c = arr[bar_i]
            m = int(smins[bar_i])
            side = trade["side"]
            stop, tgt = trade["stop"], trade["target"]
            hit_stop = (l <= stop) if side == 1 else (h >= stop)
            hit_tgt = tgt is not None and ((h >= tgt) if side == 1 else (l <= tgt))

            if hit_stop:
                # Stop order. A bar-boundary gap through the level fills at the reopen.
                if gap_aware and not same_bar:
                    return (min(stop, o) if side == 1 else max(stop, o)), "stop"
                return stop, "stop"
            if hit_tgt:
                # Limit order: fills at the limit or better.
                if gap_aware and not same_bar:
                    return (max(tgt, o) if side == 1 else min(tgt, o)), "target"
                return tgt, "target"
            if m >= texit:
                return c, "time"
            return None

        last_exit_bar = -1
        for i in range(len(scan)):
            o, h, l, c = arr[i]
            m = int(smins[i])
            ts = idx[i]

            # ---------------- manage a position carried into this bar ----------------
            if open_trade is not None:
                got = manage(i, open_trade, same_bar=False)
                if got is not None:
                    _close_trade(open_trade, ts, got[0], got[1], costs, slip, out)
                    open_trade = None
                    n_trades_today += 1
                    last_exit_bar = i
                    if not params.allow_reentry:
                        break

            # ---------------- look for an entry ----------------
            # Never enter on the same bar a trade just closed on: the intrabar path that
            # would make that sequence possible is not observable in bar data.
            if open_trade is None and m <= cutoff and i != last_exit_bar:
                if params.allow_reentry or n_trades_today == 0:
                    # brk is the side of the RANGE that broke; side is the side TRADED.
                    # They differ when params.fade is set, which is how the matched placebo
                    # is expressed: identical bar, identical price, opposite direction.
                    brk = 0
                    trig = np.nan
                    long_ok = h >= long_trig
                    short_ok = l <= short_trig
                    if long_ok and short_ok:
                        # Both extremes broken in one bar: the path is unknowable, so take
                        # the side whose trigger sat closer to the bar's open (likelier first).
                        skip["both_sides_same_bar"] = skip.get("both_sides_same_bar", 0) + 1
                        if abs(long_trig - o) <= abs(o - short_trig):
                            brk, trig = 1, long_trig
                        else:
                            brk, trig = -1, short_trig
                    elif long_ok:
                        brk, trig = 1, long_trig
                    elif short_ok:
                        brk, trig = -1, short_trig

                    side = -brk if params.fade else brk
                    if side == 1 and params.direction == "short":
                        side = 0
                    elif side == -1 and params.direction == "long":
                        side = 0

                    if side != 0:
                        # Fill is set by the direction price APPROACHED the level from, not
                        # by the side traded: price rising through an upper trigger fills a
                        # buy-stop and a sell-limit at the same place. A bar-boundary gap
                        # through the level fills at the reopen.
                        if gap_aware:
                            fill = max(trig, o) if brk == 1 else min(trig, o)
                        else:
                            fill = trig
                        gapped = abs(fill - trig) > 1e-9
                        fill_net = fill + slip if side == 1 else fill - slip

                        if params.stop_mode == "opposite":
                            stop = or_low if side == 1 else or_high
                        else:
                            stop = (fill_net - params.stop_frac * or_width if side == 1
                                    else fill_net + params.stop_frac * or_width)
                        risk = (fill_net - stop) if side == 1 else (stop - fill_net)
                        if risk <= 0:
                            skip["nonpositive_risk"] = skip.get("nonpositive_risk", 0) + 1
                        else:
                            target = None
                            if params.target_r is not None:
                                target = (fill_net + params.target_r * risk if side == 1
                                          else fill_net - params.target_r * risk)
                            open_trade = {
                                "session": day.date(), "side": side,
                                "entry_ts": ts, "entry_px": fill_net, "raw_trigger": trig,
                                "entry_gapped": bool(gapped), "stop": stop, "target": target,
                                "risk_pts": risk, "or_high": or_high, "or_low": or_low,
                                "or_width": or_width, "entry_minute": m,
                            }
                            # No protection-free window: the entry bar is checked immediately.
                            got = manage(i, open_trade, same_bar=True)
                            if got is not None:
                                _close_trade(open_trade, ts, got[0], got[1], costs, slip, out)
                                open_trade = None
                                n_trades_today += 1
                                last_exit_bar = i
                                if not params.allow_reentry:
                                    break

        # session ended with a position still open (data ran out before time_exit)
        if open_trade is not None:
            last = scan.iloc[-1]
            _close_trade(open_trade, scan.index[-1], float(last["close"]), "eod_data_end",
                         costs, slip, out)

    return out


def _close_trade(tr: dict, ts, exit_px: float, reason: str, costs: Costs,
                 slip: float, out: SessionResult) -> None:
    side = tr["side"]
    # Slippage on the exit is adverse regardless of direction.
    net_exit = exit_px - slip if side == 1 else exit_px + slip
    pts = (net_exit - tr["entry_px"]) * side
    gross_usd = pts * costs.point_value
    net_usd = gross_usd - costs.commission_rt
    rec = dict(tr)
    rec.update({
        "exit_ts": ts, "exit_px": net_exit, "exit_reason": reason,
        "points": pts, "gross_usd": gross_usd, "net_usd": net_usd,
        "r_multiple": net_usd / (tr["risk_pts"] * costs.point_value) if tr["risk_pts"] > 0 else np.nan,
        "hold_minutes": int((ts - tr["entry_ts"]).total_seconds() // 60),
        "side_label": "long" if side == 1 else "short",
    })
    rec.pop("side", None)
    rec["side"] = side
    out.trades.append(rec)


def trades_frame(res: SessionResult) -> pd.DataFrame:
    if not res.trades:
        return pd.DataFrame()
    df = pd.DataFrame(res.trades)
    return df.sort_values("entry_ts").reset_index(drop=True)
