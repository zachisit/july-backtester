"""Asset-class-aware smoothness verdict profiles.

The curve-smoothness verdict in :mod:`helpers.llm_verdict` grades an equity
curve SMOOTH / ACCEPTABLE / ROUGH by counting how many of five failure
conditions trip. Historically those five thresholds were hard-coded constants
chosen for a steadily-compounding, many-name *equity* book — something that
trades often enough to smooth into a monthly time series.

A concentrated, event-driven strategy (e.g. a single-instrument futures
breakout sleeve: one instrument, long dead stretches between edges, risk-based
sizing that produces occasional big months) is the structural opposite. Working
exactly as intended it will trip ``plateau >= 12`` and ``upthrust > 2`` — that is
what its equity curve *looks like*, not instability. Judging it against
equity-book thresholds mislabels correct behaviour as ROUGH.

This module makes the thresholds a named **profile** so the verdict is
interpreted against the right baseline. The ``equity`` profile reproduces the
prior hard-coded constants byte-for-byte (so default runs are unchanged); other
profiles loosen the thresholds appropriately. A profile is selected per strategy
result — either explicitly via ``config["smoothness_profile"]`` or automatically
from the instrument asset class already tracked in ``config["instruments"]``.

Pure and stateless: no I/O, no engine coupling, safe to import anywhere.
"""
from __future__ import annotations

from typing import Iterable, Mapping

# Profile names
EQUITY = "equity"
CONCENTRATED_FUTURES = "concentrated_futures"
AUTO = "auto"

DEFAULT_PROFILE_NAME = EQUITY

# Threshold keys and their comparison semantics (mirrors compute_smoothness):
#   r2_min                -> fail when r2 < r2_min
#   positive_months_min   -> fail when positive_months_pct < positive_months_min
#   longest_flat_max      -> fail when longest_flat_streak >= longest_flat_max
#   upthrust_max          -> fail when upthrust_count > upthrust_max
#   worst_month_min       -> fail when worst_monthly_return_pct < worst_month_min
SMOOTHNESS_PROFILES: dict[str, dict[str, float]] = {
    # Byte-for-byte the pre-existing hard-coded constants. DO NOT CHANGE — the
    # llm_verdict tests assert exact grades against these values.
    EQUITY: {
        "r2_min": 0.90,
        "positive_months_min": 60.0,
        "longest_flat_max": 12,
        "upthrust_max": 2,
        "worst_month_min": -10.0,
    },
    # Concentrated / event-driven (single-instrument futures breakout, etc.):
    # tolerate longer plateaus between edges, more big months from risk-based
    # sizing, and deeper single-month moves without calling the curve broken.
    CONCENTRATED_FUTURES: {
        "r2_min": 0.70,
        "positive_months_min": 45.0,
        "longest_flat_max": 24,
        "upthrust_max": 6,
        "worst_month_min": -20.0,
    },
}

# Which profile an instrument asset class maps to under AUTO selection.
_ASSET_CLASS_PROFILE = {
    "future": CONCENTRATED_FUTURES,
    "equity": EQUITY,
}


def get_thresholds(profile=None) -> dict[str, float]:
    """Resolve *profile* to a complete thresholds dict.

    ``profile`` may be:
      * ``None`` -> the equity defaults (byte-identical to the legacy constants).
      * a profile name (``str``) -> the named profile, or the equity defaults
        (with a warning) if the name is unknown.
      * a ``dict`` -> a partial or full override merged over the equity defaults,
        so callers may tweak a single threshold without restating the rest.

    The returned dict is always a fresh copy containing all five keys.
    """
    base = dict(SMOOTHNESS_PROFILES[EQUITY])
    if profile is None:
        return base
    if isinstance(profile, Mapping):
        base.update({k: v for k, v in profile.items() if k in base})
        return base
    name = str(profile)
    if name in SMOOTHNESS_PROFILES:
        return dict(SMOOTHNESS_PROFILES[name])
    print(f"  [WARNING] Unknown smoothness profile '{name}' — using '{EQUITY}' defaults.")
    return base


def resolve_profile_name(symbols: Iterable[str] | None, config: Mapping) -> str:
    """Decide which smoothness profile applies to a strategy result.

    Precedence:
      1. ``config["smoothness_profile"]`` when set to an explicit profile name
         (anything other than ``"auto"``/empty) — a hard override for the run.
      2. ``"auto"`` (the default): derive from the instrument asset class of the
         portfolio's symbols. If every resolvable symbol is a future, use
         ``concentrated_futures``; otherwise ``equity``.
      3. ``equity`` as the safe, no-regression fallback.

    An unknown explicit name is returned as-is; :func:`get_thresholds` degrades
    it to the equity defaults with a warning at compute time.
    """
    explicit = (config or {}).get("smoothness_profile")
    if explicit and str(explicit).lower() != AUTO:
        return str(explicit)

    classes = _asset_classes(symbols, config)
    if not classes:
        return EQUITY
    # Map each symbol's asset class to its profile via _ASSET_CLASS_PROFILE
    # (the single source of truth — add a row there to support a new class).
    # Only commit to a non-equity profile when the whole book agrees; a mixed
    # book falls back to the safe equity baseline.
    profiles = {_ASSET_CLASS_PROFILE.get(c, EQUITY) for c in classes}
    return next(iter(profiles)) if len(profiles) == 1 else EQUITY


def _asset_classes(symbols: Iterable[str] | None, config: Mapping) -> list[str]:
    """Resolve each symbol to its asset class via the instruments layer.

    Imported locally to avoid any import-time coupling to the instruments module
    (and to keep this module cheap to import in multiprocessing workers).
    """
    if not symbols:
        return []
    try:
        from helpers.instruments import resolve_instrument
    except Exception:
        return []
    out: list[str] = []
    for sym in symbols:
        try:
            out.append(resolve_instrument(sym, dict(config)).asset_class)
        except Exception:
            # Unresolvable symbol -> treat as equity so we never loosen by accident.
            out.append("equity")
    return out


def mc_sampling_caveat(mc_verdict, profile_name: str, mc_sampling: str):
    """Context note folding the MC "DD Understated" flag into asset-class awareness.

    "DD Understated" fires when the historical drawdown got a luckier trade
    ordering than random i.i.d. reshuffling typically produces. For a
    concentrated, regime-dependent strategy that check is legitimate, but i.i.d.
    resampling destroys the win/loss streak clustering such strategies live on —
    ``config["mc_sampling"] = "block"`` (block-bootstrap) is the intended tool
    for exactly this case (see CLAUDE.md, SECTION 18).

    Returns a one-line caveat when a non-equity profile got a "DD Understated"
    verdict under i.i.d. sampling, else ``None``. Reporting-layer only — it never
    changes the MC score or touches :mod:`helpers.monte_carlo`.
    """
    if profile_name == EQUITY:
        return None
    if not mc_verdict or "DD Understated" not in str(mc_verdict):
        return None
    if str(mc_sampling or "iid").lower() != "iid":
        return None
    return (
        "DD Understated came from i.i.d. resampling on a concentrated/"
        "regime-dependent strategy — set mc_sampling='block' (block-bootstrap "
        "preserves streak clustering) before treating this as a red flag."
    )


def resolve_mc_sampling(mc_sampling, profile_name: str):
    """Resolve the effective Monte-Carlo resampling method for a run.

    ``"auto"`` ties the method to the asset-class smoothness profile: a
    ``concentrated_futures`` strategy uses ``"block"`` (block-bootstrap
    preserves the win/loss streak clustering a single-instrument,
    regime-dependent strategy lives on, so the MC "DD-Understated" verdict is
    judged on the appropriate resampling rather than i.i.d. — which structurally
    trips that verdict for this strategy class); any other profile uses
    ``"iid"``. An explicit ``"iid"`` / ``"block"`` (or any non-``"auto"`` value)
    is returned unchanged, so the default (``"iid"``) run is byte-for-byte
    unaffected.
    """
    sampling = mc_sampling or "iid"  # normalise None/empty -> iid
    if str(sampling).lower() == "auto":
        return "block" if profile_name == CONCENTRATED_FUTURES else "iid"
    return sampling
