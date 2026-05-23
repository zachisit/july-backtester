"""Strategy-verdict formatters shared between terminal output and PDF reports.

The engine produces several per-strategy verdicts (P&L vs benchmark, MC tail
risk, walk-forward, rolling WFA, curve smoothness). Historically these were
only fully visible in ``output/runs/<id>/llm_verdict.json`` while the
terminal summary table showed only a subset. This module formats them
consistently in two surfaces:

* :func:`format_strategy_verdict_lines` — multi-line per-strategy block used
  by both the terminal printer and the PDF tearsheet.
* :func:`print_strategy_verdicts` — emits all strategy verdict blocks to
  stdout under a header, called from ``main.py`` after the summary tables.

A result dict is expected to look like the per-strategy result produced by
``main.py::run_single_simulation``: keys include ``Strategy``, ``Portfolio``,
``pnl_percent``, ``mc_verdict``, ``mc_score``, ``wfa_verdict``,
``wfa_rolling_verdict``, ``smooth_verdict``, ``smooth_notes`` plus a
``vs_<benchmark>_benchmark`` margin for each benchmark configured.
"""
from __future__ import annotations

from typing import Iterable, Mapping, Sequence


_VERDICT_HEADER = "=" * 30 + " STRATEGY VERDICTS " + "=" * 30


def _primary_benchmark_label(benchmark_returns: Mapping[str, float] | None) -> str | None:
    if not benchmark_returns:
        return None
    return next(iter(benchmark_returns))


def _format_pp(margin_pp: float, benchmark_label: str) -> str:
    if margin_pp > 0:
        return f"BEATS {benchmark_label} by +{margin_pp:.2f}pp"
    return f"LAGS {benchmark_label} by {margin_pp:.2f}pp"


def _benchmark_margin_pp(result: Mapping, benchmark_label: str,
                         benchmark_returns: Mapping[str, float]) -> float | None:
    """Compute the percentage-point margin vs a benchmark from the result dict.

    Looks up the precomputed ``vs_<label>_benchmark`` margin first (fractional);
    falls back to ``pnl_percent - benchmark_returns[label]`` if absent.
    Returns ``None`` when neither is available.
    """
    key = f"vs_{benchmark_label.lower().replace(' ', '_')}_benchmark"
    margin_frac = result.get(key)
    if margin_frac is None:
        pnl_frac = result.get("pnl_percent")
        bh_frac = benchmark_returns.get(benchmark_label)
        if pnl_frac is None or bh_frac is None:
            return None
        margin_frac = float(pnl_frac) - float(bh_frac)
    try:
        return round(float(margin_frac) * 100, 2)
    except (TypeError, ValueError):
        return None


def format_strategy_verdict_lines(result: Mapping,
                                  benchmark_returns: Mapping[str, float] | None = None,
                                  indent: str = "  ") -> list[str]:
    """Format one strategy result as a list of human-readable verdict lines.

    The lines are intentionally tabular within each block and do not include
    any final newline. The caller decides how to join them (terminal printer
    uses ``"\\n".join(...)``; the PDF report concatenates with ``"\\n"`` too).
    """
    strategy = result.get("Strategy", "?")
    portfolio = result.get("Portfolio", "")
    header = f"{strategy}" + (f" ({portfolio})" if portfolio else "")

    lines: list[str] = [header]

    primary_label = _primary_benchmark_label(benchmark_returns)
    if primary_label:
        margin_pp = _benchmark_margin_pp(result, primary_label, benchmark_returns)
        if margin_pp is not None:
            lines.append(f"{indent}Verdict:    {_format_pp(margin_pp, primary_label)}")
        else:
            lines.append(f"{indent}Verdict:    no margin available")
    else:
        lines.append(f"{indent}Verdict:    no benchmark configured")

    # MC
    mc_v = result.get("mc_verdict")
    mc_s = result.get("mc_score")
    if mc_v is not None:
        score_part = f" (score: {mc_s})" if mc_s is not None else ""
        lines.append(f"{indent}MC:         {mc_v}{score_part}")

    # WFA
    wfa = result.get("wfa_verdict")
    wfa_roll = result.get("wfa_rolling_verdict")
    if wfa is not None or wfa_roll is not None:
        wfa_part = wfa if wfa is not None else "N/A"
        roll_part = wfa_roll if wfa_roll is not None else "N/A"
        lines.append(f"{indent}WFA:        {wfa_part} | Rolling: {roll_part}")

    # Smoothness
    smooth = result.get("smooth_verdict")
    if smooth is not None:
        lines.append(f"{indent}Smoothness: {smooth}")
        for note in (result.get("smooth_notes") or []):
            lines.append(f"{indent}  - {note}")

    return lines


def format_strategy_verdicts_block(results: Sequence[Mapping],
                                   benchmark_returns: Mapping[str, float] | None = None) -> str:
    """Format the full multi-strategy verdict block as a single string."""
    blocks: list[str] = [_VERDICT_HEADER]
    for r in results:
        if not r.get("Trades"):
            continue
        blocks.extend(format_strategy_verdict_lines(r, benchmark_returns))
        blocks.append("")  # blank line between strategies
    blocks.append("=" * len(_VERDICT_HEADER))
    return "\n".join(blocks)


def print_strategy_verdicts(results: Sequence[Mapping],
                            benchmark_returns: Mapping[str, float] | None = None,
                            *, file=None) -> None:
    """Emit the multi-strategy verdict block to stdout (or a custom file).

    No-op when ``results`` is empty or contains only zero-trade strategies.
    """
    valid = [r for r in results if r.get("Trades")]
    if not valid:
        return
    text = format_strategy_verdicts_block(valid, benchmark_returns)
    print(text, file=file)
