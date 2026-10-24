"""Stub results for strategy runs that produced no trades or crashed (#432).

``run_portfolio_simulation`` returns ``None`` when a strategy never trades, and a
worker exception used to be swallowed as ``None`` too, so both kinds of run
silently vanished from every table. ``run_single_simulation`` now returns a
*stub* result instead: it carries the same ``Strategy`` / ``Portfolio`` /
metric keys a real result does (neutral values), plus a ``status`` of
``"no_trades"`` or ``"error"``. Stubs are never shown as ranked strategies;
they are accounted for in a "Not shown" block and counted (as not profitable)
by the sensitivity report.
"""
from __future__ import annotations

from typing import Iterable, Mapping

STATUS_NO_TRADES = "no_trades"
STATUS_ERROR = "error"
STUB_STATUSES = (STATUS_NO_TRADES, STATUS_ERROR)


def is_stub(result: Mapping | None) -> bool:
    """True for a no-trades / error stub result."""
    return bool(result) and result.get("status") in STUB_STATUSES


def split_results(results: Iterable[Mapping]) -> tuple[list, list]:
    """Return ``(real_results, stubs)``, preserving order."""
    real, stubs = [], []
    for r in results:
        if r is None:
            continue
        (stubs if is_stub(r) else real).append(r)
    return real, stubs


def make_stub_result(strategy: str, portfolio: str, status: str, *,
                     initial_capital: float | None = None,
                     benchmark_returns: Mapping[str, float] | None = None,
                     error: str | None = None,
                     meta: Mapping | None = None) -> dict:
    """Build a neutral stub carrying the keys a real result carries."""
    stub = {
        "Strategy": strategy,
        "Portfolio": portfolio,
        "status": status,
        "Trades": 0,
        "pnl_percent": 0.0,
        "trade_log": [],
        "trade_pnl_list": [],
        "initial_capital": initial_capital,
        "portfolio_timeline": None,
        "max_drawdown": 0,
        "calmar_ratio": 0,
        "sharpe_ratio": 0,
        "profit_factor": 0,
        "win_rate": 0,
        "avg_trade_duration": 0,
        "max_recovery_days": None,
        "avg_recovery_days": None,
        "mc_verdict": "N/A (no trades)" if status == STATUS_NO_TRADES else "N/A (error)",
        "mc_score": -999,
        "oos_pnl_pct": None,
        "wfa_verdict": "N/A",
        "wfa_rolling_verdict": "N/A",
        "expectancy": None,
        "sqn": None,
        "rolling_sharpe_mean": None,
        "rolling_sharpe_min": None,
        "rolling_sharpe_final": None,
        "regime_heatmap": None,
        "smooth_verdict": "N/A",
        "smooth_notes": [],
    }
    for label, bench in (benchmark_returns or {}).items():
        stub[f"vs_{label.lower().replace(' ', '_')}_benchmark"] = 0.0 - bench
    if error is not None:
        stub["error"] = error
    if meta:
        # base_strategy / param_label / stop_label (#434), same as real results.
        stub.update(meta)
    return stub


def format_not_shown(stubs: Iterable[Mapping]) -> list[str]:
    """Lines for the "Not shown: N with 0 trades, M errored" block (empty if no stubs)."""
    stubs = list(stubs)
    no_trades = [s for s in stubs if s.get("status") == STATUS_NO_TRADES]
    errored = [s for s in stubs if s.get("status") == STATUS_ERROR]
    if not no_trades and not errored:
        return []
    lines = [f"Not shown: {len(no_trades)} with 0 trades, {len(errored)} errored"]
    for s in no_trades:
        lines.append(f"  - 0 trades: {s.get('Strategy', '?')}")
    for s in errored:
        lines.append(f"  - ERROR: {s.get('Strategy', '?')}: {s.get('error', 'unknown error')}")
    return lines
