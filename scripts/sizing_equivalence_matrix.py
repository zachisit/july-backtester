#!/usr/bin/env python3
"""Record the share/contract count the engine actually takes, per sizing cell.

Written for #384 (part of #381), whose acceptance criterion is that folding
`risk_pct_capped` and `fixed_contracts` into `calculate_position_size` changes
no numbers. The golden master (tests/test_engine_characterization.py) is NOT
sufficient evidence for that on its own: it exercises `fixed` and `risk_parity`
and no other method, so it is silent on four of the six — including both of the
ones being moved. Run this on the parent commit, run it again on the change,
and diff:

    python scripts/sizing_equivalence_matrix.py before.json
    git checkout <the change>
    python scripts/sizing_equivalence_matrix.py after.json
    python -c "import json,sys; a=json.load(open('before.json')); \
b=json.load(open('after.json')); \
print([k for k in a if a[k]!=b[k]])"

The grid is 4,032 cells: {equity, futures} x {long, short} x {close, open}
execution x 3 clamp profiles x 7 methods (six real plus one deliberate typo, to
prove the unknown-method path is still reachable) x 6 stop types x 4 price
levels. Cells that take no position are themselves an observable and are
recorded as `shares: null` rather than dropped.

The clamp axis exists because the first version of this harness pinned
`max_portfolio_heat: 1.0` and `max_pct_adv: 0.0` — copied from the golden
master's base config, where disabling them is correct design for isolating the
core arithmetic. That made this harness blind in exactly the place the golden
master is blind, and for the same reason: `risk_pct_capped` returns TWO values,
the unit count and `sizing_kwargs["stop_distance_pct"]`, and the second one is
read only by the portfolio heat check. Deleting that second output produced
**0 diffs of 1008** against the heat-disabled grid while silently reverting the
heat check to its flat 2% `target_risk_per_trade` proxy — the 10-15x
misvaluation documented at the assignment site.
(@shardul0701 called this out on #384 before the harness caught it.)

Turning the clamps on at their config defaults was NOT enough either: at heat
0.10 both the real fraction and the 2% proxy pass everywhere in this grid, so
the swap stayed invisible. It is only observable where the cap falls BETWEEN
the two, which needs a real stop fraction materially under 2% — the documented
shape of the bug. Hence the 5000.0 price level (where trailing_atr's point_cap
of 60 binds, giving 1.2% of price) and the `heat_tight` profile. With those,
deleting the side output moves 10 cells, all in `heat_tight`, in BOTH
directions: a correctly-sized trade gets rejected, and an over-risked one gets
admitted.

Exceptions are caught and recorded as `{"error": ...}` on purpose — a refactor
that turns a sized trade into a NameError is a diff, not a crash of the harness.
"""
import json
import math
import os
import sys
import warnings
from unittest.mock import patch

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.portfolio_simulations import run_portfolio_simulation  # noqa: E402

_BASE = {
    "slippage_pct": 0.0005,
    "commission_per_share": 0.002,
    "execution_time": "close",
    "risk_free_rate": 0.05,
    "htb_rate_annual": 0.0,
    "volume_impact_coeff": 0.0,
    "target_risk_per_trade": 0.02,
    "entry_priority": "alphabetical",
    "exclude_open_positions": False,
    "include_delisted": False,
    "allocation_per_trade": 0.10,
    "risk_pct_per_trade": 0.01,
    "max_contracts_cap": 20,
    "fixed_contracts_per_trade": 7,
    "instruments": {
        "default_asset_class": "equity",
        "futures_initial_margin_pct": 0.10,
        "futures_commission_per_contract": 2.50,
        "futures_slippage_ticks": 1.0,
        "overrides": {},
    },
}

METHODS = ["fixed", "kelly", "vol_parity", "risk_parity",
           "risk_pct_capped", "fixed_contracts", "bogus_method"]

STOPS = {
    "none": {"type": "none"},
    "pct5": {"type": "percentage", "value": 0.05},
    "atr": {"type": "atr", "multiplier": 2.0},
    "trailing_atr": {"type": "trailing_atr", "stop_mult": 1.0, "trail_mult": 1.0,
                     "t1_mult": 2.0, "point_cap": 60, "floor": "breakeven"},
    "points": {"type": "points", "value": 5.0},
    "signal_bar": {"type": "signal_bar", "buffer": 0.005},
}

# "MESM6" is a contract-month ticker, so resolve_instrument auto-detects it as
# an MES future ($5/point, 10% initial margin). "AAA" resolves to a cash equity.
SYMBOLS = ("AAA", "MESM6")

# 4000, not 5000. At $5,000 the margin-based fallback sizes to exactly
# `fixed_contracts_per_trade`, so the branch under test and the branch it
# replaced AGREE BY ARITHMETIC and all 72 futures cells at that price go inert
# — zero decisive, while still counting toward the total. `risk_pct_capped` was
# dented the same way there. A collision, not a bug, but it makes the headline
# cell count overstate what was actually tested. `fixed_contracts_per_trade` is
# 7 rather than 3 for the same reason. (@shardul0701 on #388.)
PRICES = (20.0, 100.0, 1000.0, 4000.0)

# The equity axis. Every earlier revision of this harness encoded `equity` in
# the key and then pinned it at 100,000 in the innermost loop — so there was
# one equity level across the whole grid, and the key field read like coverage
# that did not exist.
#
# It is the axis #385 is DEFINED on, twice over: `max_contracts_cap` makes
# dollar risk stop compounding past the point it binds (a 100x account growth
# took risk-per-trade from ~0.95% to 0.010% of equity), and the notional
# ceiling is `equity * ceiling_pct / price`. A grid that cannot vary equity
# pins the status quo rather than the fix. Three lines. (@shardul0701 on #388
# and #390.)
EQUITIES = (50_000.0, 100_000.0, 2_000_000.0)

# "off" isolates the sizing arithmetic (the golden master's choice); "default"
# turns on the two clamps the sized number actually flows into on a real run.
# Only "default" can see risk_pct_capped's heat-check side output.
CLAMPS = {
    "off": {"max_portfolio_heat": 1.0, "max_pct_adv": 0.0},
    "default": {"max_portfolio_heat": 0.10, "max_pct_adv": 0.05},
    # `default` is still not tight enough to SEE the heat-check side output:
    # dropping it swaps the real stop fraction for the flat 2% proxy, and at
    # heat 0.10 both sides pass everywhere in this grid, so the swap is
    # invisible. It only becomes observable where the cap falls BETWEEN the two
    # -- i.e. where the real fraction is materially under 2%, which is the
    # documented shape of the bug (a point_cap of 60 on a multi-thousand-point
    # index). The 5000.0 price level below puts trailing_atr's cap in force
    # (ATR 100 -> capped to 60 -> 1.2% of price) and 1% heat then admits on the
    # real fraction and rejects on the proxy. Measured, not assumed: mutating
    # the side output away moves cells only in this profile.
    "heat_tight": {"max_portfolio_heat": 0.01, "max_pct_adv": 0.05},
}


def _frame(base_price, n=14, atr_pct=2.0):
    """Gently rising series — nothing stops out before the exit signal fires.

    ATR is RAMPED, not constant. `np.full(n, ...)` gave every bar the same ATR,
    which makes the signal-bar-vs-fill-bar anchor unobservable: the two branches
    that read `ATR_14` would return the same number whichever bar they picked,
    so a grid built on a flat column cannot see an anchor defect at all. That
    was correct for #384 (which does not touch the anchors) and wrong to carry
    forward. A 5%-per-bar ramp makes adjacent bars distinguishable.
    (@shardul0701 on #388.)
    """
    closes = np.array([base_price * (1 + 0.002 * i) for i in range(n)])
    atr0 = atr_pct * base_price / 100.0
    idx = pd.bdate_range(start="2023-01-02", periods=n, freq="B")
    idx.name = "Datetime"
    return pd.DataFrame({
        "Open": np.round(closes * 0.999, 6),
        "High": np.round(closes * 1.010, 6),
        "Low": np.round(closes * 0.990, 6),
        "Close": closes,
        "Volume": np.full(n, 5_000_000.0),
        "ATR_14": np.array([atr0 * (1 + 0.05 * i) for i in range(n)]),
    }, index=idx)


def _round(v):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return None if math.isnan(f) or math.isinf(f) else round(f, 8)


def _cell(symbol, method, stop_key, price, equity, direction, exec_time, clamps):
    df = _frame(price)
    pairs = {2: -2, 9: -1} if direction == "short" else {2: 1, 9: -1}
    sig = pd.Series(0, index=df.index, dtype=int)
    for i, v in pairs.items():
        sig.iloc[i] = v
    cfg = {**_BASE, **CLAMPS[clamps],
           "position_sizing_method": method, "execution_time": exec_time}
    try:
        with patch.dict("config.CONFIG", cfg, clear=False):
            res = run_portfolio_simulation(
                portfolio_data={symbol: df}, signals={symbol: sig},
                initial_capital=equity, allocation_pct=0.10,
                spy_df=None, vix_df=None, tnx_df=None,
                stop_config=STOPS[stop_key],
            )
    except Exception as exc:                      # a crash IS an observable
        return {"error": "%s: %s" % (type(exc).__name__, exc)}
    if not res or not res.get("trade_log"):
        return {"shares": None}
    t = res["trade_log"][0]
    return {
        "shares": _round(t.get("Shares")),
        "entry": _round(t.get("EntryPrice", t.get("Price"))),
        "risk": _round(t.get("InitialRisk")),
        "profit": _round(t.get("Profit")),
        "reason": t.get("ExitReason"),
    }


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    warnings.filterwarnings("ignore")
    out = {}
    for symbol in SYMBOLS:
        for direction in ("long", "short"):
            for exec_time in ("close", "open"):
                for clamps in CLAMPS:
                    for method in METHODS:
                        for stop_key in STOPS:
                            for price in PRICES:
                                for equity in EQUITIES:
                                    key = "|".join(
                                        [symbol, direction, exec_time, clamps,
                                         method, stop_key, str(price),
                                         str(equity)])
                                    out[key] = _cell(symbol, method, stop_key,
                                                     price, equity, direction,
                                                     exec_time, clamps)
    with open(argv[1], "w") as fh:
        json.dump(out, fh, indent=0, sort_keys=True)
    traded = sum(1 for v in out.values() if v.get("shares") is not None)
    sys.stderr.write("cells: %d (%d took a position)\n" % (len(out), traded))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
