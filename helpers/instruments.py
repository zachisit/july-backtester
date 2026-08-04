"""helpers/instruments.py

Per-symbol instrument metadata — the missing abstraction that let the engine
hard-assume "1 share = $1/point, NYSE hours, full-notional cash, dividends apply".

Every cost / sizing / accounting decision that used to read a global CONFIG key
directly now flows through an :class:`Instrument`, so the same execution core can
price equities *and* futures (and, later, forex / crypto) correctly.

Design contract — NO REGRESSION FOR EQUITIES
--------------------------------------------
``resolve_instrument(symbol, config)`` returns an **equity** instrument by default,
built from the existing config keys (``commission_per_share``, ``slippage_pct``,
``htb_rate_annual``) with ``point_value=1``, ``margin_mode="cash_full"`` and
``integer_units=False``. The cost helpers below then reproduce the *exact* arithmetic
the engine used before this module existed:

- ``commission(inst, units)``        -> ``units * commission_per_share``
- ``apply_slippage(inst, p, "buy")`` -> ``p * (1 + slippage_pct)``
- ``apply_slippage(inst, p, "sell")``-> ``p * (1 - slippage_pct)``
- ``market_value(inst, units, p)``   -> ``units * p``
- ``margin_required(inst, units, p)``-> ``units * p``  (full notional)
- ``borrow_cost_per_bar(...)``       -> ``notional * htb_per_bar``

This module is pure and stateless — no I/O, no globals, no randomness.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace

# --- Asset classes -----------------------------------------------------------
EQUITY = "equity"
FUTURE = "future"
FOREX = "forex"
CRYPTO = "crypto"

# --- Margin modes ------------------------------------------------------------
CASH_FULL = "cash_full"          # equities: post 100% of notional
INITIAL_MARGIN = "initial_margin"  # futures: post a small % of notional

# --- Commission / slippage models -------------------------------------------
PER_SHARE = "per_share"
PER_CONTRACT = "per_contract"
SLIP_PCT = "pct"
SLIP_TICKS = "ticks"

# --- Calendars ---------------------------------------------------------------
NYSE = "NYSE"
CME_ETH = "CME_ETH"

# CME contract-month codes (Jan..Dec) — used to parse a root from e.g. "ESM6".
_MONTH_CODES = "FGHJKMNQUVXZ"
# Matches PRODUCT + MONTH_CODE + YEAR_DIGIT(s): "ESM6", "MNQZ26", "CLF7", "M2KZ6".
# The root group allows a digit after the first letter so products like M2K (Micro
# Russell 2000) parse correctly; the regex still backtracks so "ESM6" -> root "ES".
_CONTRACT_RE = re.compile(rf"^([A-Z][A-Z0-9]{{0,2}})([{_MONTH_CODES}])(\d{{1,2}})$")

# $/point multipliers, seeded from SignalDeck's FUTURES_MULTIPLIERS map.
# All values are overridable via config["instruments"]["point_values"].
FUTURES_POINT_VALUES: dict[str, float] = {
    "ES": 50.0, "MES": 5.0,
    "NQ": 20.0, "MNQ": 2.0,
    "RTY": 50.0, "M2K": 5.0,
    "YM": 5.0, "MYM": 0.5,
    "CL": 1000.0, "MCL": 100.0,
    "GC": 100.0, "MGC": 10.0,
    "SI": 5000.0,
    "ZB": 1000.0, "ZN": 1000.0, "ZF": 1000.0,
}

# Minimum price increments. Overridable via config["instruments"]["tick_sizes"].
FUTURES_TICK_SIZES: dict[str, float] = {
    "ES": 0.25, "MES": 0.25,
    "NQ": 0.25, "MNQ": 0.25,
    "RTY": 0.10, "M2K": 0.10,
    "YM": 1.0, "MYM": 1.0,
    "CL": 0.01, "MCL": 0.01,
    "GC": 0.10, "MGC": 0.10,
    "SI": 0.005,
    "ZB": 0.03125, "ZN": 0.015625, "ZF": 0.0078125,
}

_DEFAULT_FUTURES_TICK = 0.25


@dataclass(frozen=True)
class Instrument:
    """Immutable trading metadata for one symbol."""

    symbol: str
    asset_class: str = EQUITY
    point_value: float = 1.0            # $ per 1.0 price point (1.0 for equities)
    tick_size: float = 0.01             # minimum price increment
    margin_mode: str = CASH_FULL        # CASH_FULL | INITIAL_MARGIN
    initial_margin_pct: float = 1.0     # fraction of notional posted at entry
    commission_model: str = PER_SHARE   # PER_SHARE | PER_CONTRACT
    commission_value: float = 0.0       # $/share or $/contract
    slippage_model: str = SLIP_PCT      # PCT | TICKS
    slippage_value: float = 0.0         # fraction (pct) or number of ticks
    integer_units: bool = False         # True -> whole contracts
    borrow_applies: bool = True         # False for futures (no stock-loan fee)
    calendar: str = NYSE                # NYSE | CME_ETH


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------
def parse_root(symbol: str) -> str:
    """Return the product root for a futures ticker.

    ``"ESM6" -> "ES"``, ``"MNQZ26" -> "MNQ"``. A plain root (``"ES"``) or a
    non-futures symbol is returned unchanged / uppercased.
    """
    m = _CONTRACT_RE.match(symbol.upper())
    return m.group(1) if m else symbol.upper()


def _looks_like_futures_contract(symbol: str) -> bool:
    """True when *symbol* is an unambiguous contract-month code (e.g. ``ESM6``)
    whose root is a known futures product. Bare roots like ``"SI"`` (also a real
    equity ticker) are NOT auto-classified — they must be opted in via config."""
    m = _CONTRACT_RE.match(symbol.upper())
    return bool(m and m.group(1) in FUTURES_POINT_VALUES)


def _equity_instrument(symbol: str, config: dict) -> Instrument:
    """Equity instrument built from legacy config keys — reproduces prior math."""
    return Instrument(
        symbol=symbol,
        asset_class=EQUITY,
        point_value=1.0,
        tick_size=0.01,
        margin_mode=CASH_FULL,
        initial_margin_pct=1.0,
        commission_model=PER_SHARE,
        commission_value=float(config.get("commission_per_share", 0.0)),
        slippage_model=SLIP_PCT,
        slippage_value=float(config.get("slippage_pct", 0.0)),
        integer_units=False,
        borrow_applies=True,
        calendar=NYSE,
    )


def _futures_instrument(symbol: str, config: dict) -> Instrument:
    """Futures instrument seeded from the point-value / tick tables + config."""
    inst_cfg = config.get("instruments", {}) or {}
    root = parse_root(symbol)

    point_values = {**FUTURES_POINT_VALUES, **inst_cfg.get("point_values", {})}
    tick_sizes = {**FUTURES_TICK_SIZES, **inst_cfg.get("tick_sizes", {})}

    return Instrument(
        symbol=symbol,
        asset_class=FUTURE,
        point_value=float(point_values.get(root, 1.0)),
        tick_size=float(tick_sizes.get(root, _DEFAULT_FUTURES_TICK)),
        margin_mode=INITIAL_MARGIN,
        initial_margin_pct=float(inst_cfg.get("futures_initial_margin_pct", 0.10)),
        commission_model=PER_CONTRACT,
        commission_value=float(inst_cfg.get("futures_commission_per_contract", 2.50)),
        slippage_model=SLIP_TICKS,
        slippage_value=float(inst_cfg.get("futures_slippage_ticks", 1.0)),
        integer_units=True,
        borrow_applies=False,
        calendar=CME_ETH,
    )


def is_futures_data_symbol(symbol: str, config: dict) -> bool:
    """True when *symbol* should be fetched from a futures **data** endpoint.

    Deliberately narrower than :func:`resolve_instrument`: only an explicit
    per-symbol override (``asset_class: "future"``) or an unambiguous
    contract-month code (``ESM6``) routes to the futures API.
    ``default_asset_class`` is intentionally ignored here — benchmark and
    dependency tickers (SPY, I:VIX, ...) share the same fetch path as portfolio
    symbols, and a blanket "future" default must not reroute them to an
    endpoint that cannot serve them.
    """
    inst_cfg = config.get("instruments", {}) or {}
    override = (inst_cfg.get("overrides", {}) or {}).get(symbol)
    if override is not None and "asset_class" in override:
        return override["asset_class"] == FUTURE
    return _looks_like_futures_contract(symbol)


def resolve_instrument(symbol: str, config: dict) -> Instrument:
    """Resolve an :class:`Instrument` for *symbol* from *config*.

    Precedence:
      1. ``config["instruments"]["overrides"][symbol]`` — explicit per-symbol dict.
      2. Unambiguous contract-month code (``ESM6``) with a known root -> future.
      3. ``config["instruments"]["default_asset_class"] == "future"`` -> future.
      4. Otherwise -> equity (the safe, no-regression default).

    An override dict may set ``"asset_class"`` and any :class:`Instrument` field;
    unspecified fields inherit the resolved asset-class defaults.
    """
    inst_cfg = config.get("instruments", {}) or {}
    overrides = inst_cfg.get("overrides", {}) or {}
    default_class = inst_cfg.get("default_asset_class", EQUITY)

    override = overrides.get(symbol)
    if override is not None:
        asset_class = override.get("asset_class", default_class)
        base = (_futures_instrument(symbol, config)
                if asset_class == FUTURE else _equity_instrument(symbol, config))
        fields = {k: v for k, v in override.items()
                  if k in Instrument.__dataclass_fields__ and k not in ("symbol", "asset_class")}
        return replace(base, asset_class=asset_class, **fields)

    if _looks_like_futures_contract(symbol):
        return _futures_instrument(symbol, config)

    if default_class == FUTURE:
        return _futures_instrument(symbol, config)

    return _equity_instrument(symbol, config)


# ---------------------------------------------------------------------------
# Cost / accounting helpers — replace the hard-coded call sites in the engine
# ---------------------------------------------------------------------------
def commission(inst: Instrument, units: float) -> float:
    """Commission for *units* (shares or contracts). One-side only — callers that
    charge round-trip (entry+exit) multiply by 2, exactly as the engine does."""
    return abs(units) * inst.commission_value


def apply_slippage(inst: Instrument, raw_price: float, side: str) -> float:
    """Slippage-adjusted fill price. ``side`` is ``"buy"`` or ``"sell"``.

    - ``pct`` model:   buy -> ``raw * (1 + s)``,  sell -> ``raw * (1 - s)``
    - ``ticks`` model: buy -> ``raw + n*tick``,   sell -> ``raw - n*tick``
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
    sign = 1.0 if side == "buy" else -1.0
    if inst.slippage_model == SLIP_TICKS:
        return raw_price + sign * inst.slippage_value * inst.tick_size
    return raw_price * (1.0 + sign * inst.slippage_value)


def round_units(inst: Instrument, raw_units: float) -> float:
    """Floor to whole contracts for integer-unit instruments; pass through
    fractional shares otherwise (equities kept their fractional sizing)."""
    if inst.integer_units:
        return float(math.floor(abs(raw_units))) * (1.0 if raw_units >= 0 else -1.0)
    return raw_units


def market_value(inst: Instrument, units: float, price: float) -> float:
    """Mark-to-market value of a long position: ``units * price * point_value``.
    For equities (``point_value=1``) this equals ``units * price`` — unchanged."""
    return units * price * inst.point_value


def notional(inst: Instrument, units: float, price: float) -> float:
    """Full contract/share notional (positive), independent of margin mode."""
    return abs(units) * price * inst.point_value


def margin_required(inst: Instrument, units: float, price: float) -> float:
    """Cash the account must set aside to open *units* at *price*.

    - ``cash_full`` (equities): full notional (``units * price``) — unchanged.
    - ``initial_margin`` (futures): ``notional * initial_margin_pct``.
    """
    n = notional(inst, units, price)
    if inst.margin_mode == INITIAL_MARGIN:
        return n * inst.initial_margin_pct
    return n


def unrealized_pnl(inst: Instrument, units: float, entry: float, current: float,
                   side: str = "long") -> float:
    """Open P&L in dollars. ``side`` is ``"long"`` or ``"short"``."""
    direction = 1.0 if side == "long" else -1.0
    return units * (current - entry) * inst.point_value * direction


def borrow_cost_per_bar(inst: Instrument, position_notional: float,
                        htb_per_bar: float) -> float:
    """Per-bar stock-loan (hard-to-borrow) fee on a short. Zero for instruments
    that don't pay borrow (futures) — the silent trap in the old code."""
    if not inst.borrow_applies:
        return 0.0
    return position_notional * htb_per_bar


def stop_level(inst: Instrument, entry: float, stop_config: dict,
               side: str = "long") -> float | None:
    """Initial stop price from a stop config. Supports ``percentage`` and the new
    ``points`` type here; ``atr`` needs bar context and stays in the engine.

    - ``percentage``: long -> ``entry*(1-v)``, short -> ``entry*(1+v)``
    - ``points``:     long -> ``entry - v``,   short -> ``entry + v``  (price points)
    Returns ``None`` for unsupported / ``none`` types.
    """
    stype = (stop_config or {}).get("type", "none")
    sign = -1.0 if side == "long" else 1.0
    if stype == "percentage":
        return entry * (1.0 + sign * stop_config.get("value", 0.05))
    if stype == "points":
        return entry + sign * stop_config.get("value", 0.0)
    return None


def atr_stop_level(reference_price: float, atr: float, multiplier: float,
                   side: str = "long", point_cap: float | None = None) -> float:
    """ATR stop price: ``ref - atr*mult`` (long) / ``ref + atr*mult`` (short).

    Single home for the ATR stop formula that the engine previously duplicated in
    three places (initial stop, trailing update, and risk-parity sizing). ``reference_price``
    is the close the stop is measured from (the signal-day close on entry, the
    current close while trailing).

    ``point_cap`` (in instrument price points) clips the ATR-derived distance so the
    stop never sits more than ``point_cap`` points from the reference — i.e.
    ``distance = min(atr*mult, point_cap)`` per trade. ``None``/``<=0`` disables the cap.
    """
    sign = -1.0 if side == "long" else 1.0
    distance = atr * multiplier
    if point_cap is not None and point_cap > 0:
        distance = min(distance, point_cap)
    return reference_price + sign * distance


def atr_stop_distance_pct(atr: float, multiplier: float, price: float) -> float:
    """ATR stop distance as a fraction of ``price`` — used by risk-parity sizing.
    Returns ``0.0`` when ``price <= 0``."""
    return (atr * multiplier) / price if price > 0 else 0.0
