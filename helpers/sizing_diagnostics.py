"""Per-run explanations for absent stop inputs and overridden position sizes.

Counts describe sizing conditions across entry attempts; one attempt may have
several conditions. Risk-method outcomes are recorded by the sizing function
that made the decision. Cash/margin, ADV and heat outcomes are recorded at the
engine's actual guards. Zero-trade runs log the same report before returning
None; successful results also expose counts under sizing_diagnostics.
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
        "no stop distance was available for the requested risk sizing; "
        "check stop_loss_configs and the signal-bar inputs"),
    "unsupported_stop_type": (
        COVERAGE_DRIFT,
        "unsupported stop type prevented resolving a sizing distance; check "
        "stop_loss_configs or add support for this stop type"),
    "atr_proxy_substituted": (
        NO_STOP,
        "no stop distance, so risk_parity substituted a 3xATR proxy -- the "
        "position is sized against a distance the strategy did not ask for"),
    "clamped_by_cash": (
        OVERRIDDEN,
        "reduced or declined to fit available cash or margin -- raise capital "
        "or lower allocation_per_trade"),
    "clamped_by_adv": (
        OVERRIDDEN,
        "reduced by the max_pct_adv liquidity cap -- the name is too thin for "
        "the requested size"),
    "rejected_by_heat": (
        OVERRIDDEN,
        "rejected by the max_portfolio_heat budget"),
    "clamped_by_contract_cap": (
        OVERRIDDEN,
        "reduced by max_contracts_cap before the requested risk budget was reached"),
    "clamped_by_notional_ceiling": (
        UNREACHABLE,
        "the configured notional ceiling prevents reaching the risk budget, "
        "so the ceiling-clamped size was used"),
}


class SizingDiagnostics:
    """Counts sizing outcomes over one simulation and reports them once.

    Deliberately not a singleton and not module state: `run_portfolio_simulation`
    is called once per portfolio per strategy, often across worker processes,
    and a module-level accumulator would either mix runs together or need
    resetting from a test fixture. One instance per run, returned on the result.
    """

    __slots__ = ("_counts", "_symbols", "_details")

    def __init__(self):
        self._counts = Counter()
        self._symbols = {}
        self._details = {}

    def record(self, reason: str, symbol: str | None = None,
               detail: str | None = None) -> None:
        if reason not in REASONS:
            # A typo'd reason would otherwise be counted under its own key and
            # reported as a category nobody defined.
            raise KeyError(
                "unknown sizing-diagnostic reason %r; add it to REASONS with "
                "its kind" % (reason,))
        self._counts[reason] += 1
        if detail:
            details = self._details.setdefault(reason, [])
            if len(details) < 5 and detail not in details:
                details.append(detail)
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
        count = sum(self._counts.values())
        head = "Position sizing: {} condition{} recorded".format(
            count, "" if count == 1 else "s")
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
            details = self._details.get(reason, [])
            if details:
                suffix += "  (" + "; ".join(details) + ")"
            lines.append("  {:>6}  {:<12} {}{}".format(n, kind, explanation, suffix))
        return "\n".join(lines)

    def log_report(self, label: str = "") -> None:
        report = self.format_report(label)
        if report:
            logger.warning(report)
