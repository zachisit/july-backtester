"""helpers/sizing_diagnostics.py

One consumer-facing account of *why* the engine sized a position differently
from what was asked for — or declined to size one at all (#387, part of #381).

The problem
-----------
The engine declined or clamped a position in six places and said so in none of
them, and the places disagreed with each other about what to do:

    _risk_parity, no stop distance      3xATR proxy -- sizes 3.35x too large
    risk_pct_capped long, no distance   shares = 0.0 -- no trade
    risk_pct_capped short, no distance  shares = 0.0
    cash clamp                          truncates to cash / price
    ADV cap                             truncates, or `continue` at zero volume
    _risk_parity's own zero             returns 0.0

Two sizing methods, opposite failure modes, on the same input. The root is that
*"the engine could not deliver what was configured"* was not represented
anywhere, so each call site inferred it from an absent number and invented an
answer.

`{"type": "none"}` is the DOCUMENTED DEFAULT stop config, so the failing
combination for the second row was "select a sizing method and change nothing
else": `run_portfolio_simulation` returned `None`, with no error and no partial
result, and a zero-trade run reads as a *strategy* finding — which invites
debugging the signal logic for a fault in the sizing gate.

Four kinds, not one
-------------------
Collapsing these into a single "no stop" message would mislabel three of them.
The taxonomy is @shardul0701's on #387, and the third kind is his correction to
an earlier four-way cut of mine that grouped clamps with absent stops:

    COVERAGE_DRIFT      derivable and merely missing from a switch. Closed by
                        #385 for `points` / `signal_bar`; kept as a category so
                        a seventh stop type is reported rather than silent.
    NO_STOP             genuinely absent -- `{"type": "none"}`. No distance
                        exists. Needs a deliberate policy, which this module
                        does NOT decide; it only makes the condition visible.
    OVERRIDDEN          the size WAS computable and something else reduced it:
                        cash, the ADV cap, portfolio heat. Distinguishable from
                        NO_STOP in the message and actionable in a different
                        way -- a cash clamp says raise capital or lower
                        allocation, an ADV truncation says the name is too thin
                        for the size, and neither says anything about stops.
    UNREACHABLE         `stop_frac < risk_pct_per_trade`: the budget cannot be
                        delivered without leverage, so the ceiling-clamped
                        value is correct and merely undeclared.

Why a run summary rather than a warning per site
------------------------------------------------
The ADV cap is armed by default (`max_pct_adv: 0.05`) and fires per entry, so a
per-site warning would emit thousands of lines on a thin universe and be
filtered out within a day. Worse, the #372 banner in this same engine showed the
other failure mode: a once-per-process dedup set that had to be reset by an
autouse fixture in the test suite, and that would have gone silently green
forever once the gap it guarded was closed.

So this accumulates counts and reports ONCE per simulation. No dedup state, no
per-bar logging, and the counts land on the result dict where a test can assert
them instead of scraping a log.
"""

from __future__ import annotations

import logging
from collections import Counter

logger = logging.getLogger(__name__)

# --- the four kinds -------------------------------------------------------
COVERAGE_DRIFT = "coverage_drift"
NO_STOP = "no_stop"
OVERRIDDEN = "overridden"
UNREACHABLE = "unreachable"

# Reason codes. The kind is the taxonomy; the reason is the site, because
# "overridden" alone does not tell a user which knob to turn.
REASONS = {
    # kind, one-line consumer-facing explanation
    "no_stop_distance": (
        NO_STOP,
        "no stop distance was available, so the position could not be "
        "risk-sized (stop_loss_configs is {'type': 'none'}?)"),
    "unsupported_stop_type": (
        COVERAGE_DRIFT,
        "the sizing method has no branch for this stop type, though the "
        "distance is derivable -- this is a gap in the engine, not a config "
        "error"),
    "atr_proxy_substituted": (
        NO_STOP,
        "no stop distance, so risk_parity substituted a 3xATR proxy -- the "
        "position is sized against a distance the strategy did not ask for"),
    "clamped_by_cash": (
        OVERRIDDEN,
        "reduced to fit available cash -- raise capital or lower "
        "allocation_per_trade"),
    "clamped_by_adv": (
        OVERRIDDEN,
        "reduced by the max_pct_adv liquidity cap -- the name is too thin for "
        "the requested size"),
    "skipped_zero_volume": (
        OVERRIDDEN,
        "skipped: the ADV cap resolved to zero shares on a zero-volume bar"),
    "rejected_by_heat": (
        OVERRIDDEN,
        "rejected by the max_portfolio_heat budget"),
    "clamped_by_notional_ceiling": (
        UNREACHABLE,
        "the risk budget is unreachable without leverage (stop distance is "
        "narrower than risk_pct_per_trade), so the ceiling-clamped size was "
        "used"),
}


class SizingDiagnostics:
    """Counts sizing outcomes over one simulation and reports them once.

    Deliberately not a singleton and not module state: `run_portfolio_simulation`
    is called once per portfolio per strategy, often across worker processes,
    and a module-level accumulator would either mix runs together or need
    resetting from a test fixture. One instance per run, returned on the result.
    """

    __slots__ = ("_counts", "_symbols")

    def __init__(self):
        self._counts = Counter()
        self._symbols = {}

    def record(self, reason: str, symbol: str | None = None) -> None:
        if reason not in REASONS:
            # A typo'd reason would otherwise be counted under its own key and
            # reported as a category nobody defined.
            raise KeyError(
                "unknown sizing-diagnostic reason %r; add it to REASONS with "
                "its kind" % (reason,))
        self._counts[reason] += 1
        if symbol is not None:
            # Bounded: the first few names are enough to make a report
            # actionable, and an unbounded set on a 500-name universe is a
            # memory cost for no extra information.
            seen = self._symbols.setdefault(reason, [])
            if len(seen) < 5 and symbol not in seen:
                seen.append(symbol)

    def as_dict(self) -> dict:
        """Counts by reason. Empty when nothing was declined or clamped."""
        return dict(self._counts)

    def by_kind(self) -> dict:
        out = Counter()
        for reason, n in self._counts.items():
            out[REASONS[reason][0]] += n
        return dict(out)

    def is_empty(self) -> bool:
        return not self._counts

    def format_report(self, label: str = "") -> str:
        if self.is_empty():
            return ""
        head = "Position sizing: {} entr{} did not get the configured size".format(
            sum(self._counts.values()),
            "y" if sum(self._counts.values()) == 1 else "ies")
        if label:
            head = "[{}] {}".format(label, head)
        lines = [head]
        for reason, n in sorted(self._counts.items(), key=lambda kv: -kv[1]):
            kind, explanation = REASONS[reason]
            names = self._symbols.get(reason, [])
            suffix = ""
            if names:
                suffix = "  e.g. {}{}".format(
                    ", ".join(names), ", ..." if n > len(names) else "")
            lines.append("  {:>6}  {:<12} {}{}".format(n, kind, explanation, suffix))
        return "\n".join(lines)

    def log_report(self, label: str = "") -> None:
        report = self.format_report(label)
        if report:
            logger.warning(report)
