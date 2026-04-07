# tests/test_mc_score_sort.py
"""
Regression test for MC Score sort order in generate_per_portfolio_summary.

Before the fix, sort_values(by='MC Score') ran AFTER fillna('N/A') converted
the DataFrame to object dtype, producing lexicographic order:
  descending string sort: "9" > "10" > "-1"  → rows: 9, 10, -1  (wrong)
  descending numeric sort: 10 > 9 > -1       → rows: 10, 9, -1  (correct)
"""

import io
import os
import sys
from contextlib import redirect_stdout
from unittest.mock import patch

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.summary import generate_per_portfolio_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(strategy_name: str, mc_score: float) -> dict:
    """Minimal result dict for generate_per_portfolio_summary."""
    return {
        "Strategy": strategy_name,
        "Trades": 10,
        "pnl_percent": 0.05,
        "max_drawdown": 0.10,
        "mc_score": mc_score,
        "mc_verdict": "Robust",
        "calmar_ratio": 1.0,
        "sharpe_ratio": 1.0,
        "win_rate": 0.6,
        "profit_factor": 1.5,
        "vs_spy_benchmark": 0.05,
        "vs_qqq_benchmark": 0.03,
        "avg_trade_duration": 3.0,
        "oos_pnl_pct": 0.02,
        "wfa_verdict": "Pass",
        "expectancy": 0.5,
        "sqn": 1.2,
        "Portfolio": "Test Portfolio",
        "Asset": "MULTI",
        "trade_log": [],
    }


def _run_summary(results):
    """Run generate_per_portfolio_summary and return captured stdout."""
    buf = io.StringIO()
    with (
        redirect_stdout(buf),
        patch("helpers.summary.os.makedirs"),
        patch.object(pd.DataFrame, "to_csv"),
    ):
        benchmark_returns = {"SPY": 0.10, "QQQ": 0.12}
        generate_per_portfolio_summary(
            portfolio_results=results,
            portfolio_name="Test Portfolio",
            benchmark_returns=benchmark_returns,
            run_id="test-sort-run",
        )
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMcScoreNumericSort:

    def test_rows_sorted_numerically_not_lexicographically(self):
        """
        mc_scores [10, 9, -1] must appear in order 10 → 9 → -1 in the output.

        Lexicographic descending sort would give "9" > "10" > "-1",
        producing order 9, 10, -1 — this test proves that path is gone.
        """
        results = [
            _make_result("Strategy-Worst", mc_score=-1),
            _make_result("Strategy-Mid",   mc_score=9),
            _make_result("Strategy-Best",  mc_score=10),
        ]
        output = _run_summary(results)

        pos_best  = output.index("Strategy-Best")
        pos_mid   = output.index("Strategy-Mid")
        pos_worst = output.index("Strategy-Worst")

        assert pos_best < pos_mid < pos_worst, (
            "Expected numeric descending order: Strategy-Best (10), "
            "Strategy-Mid (9), Strategy-Worst (-1). "
            f"Got positions: Best={pos_best}, Mid={pos_mid}, Worst={pos_worst}"
        )

    def test_lexicographic_order_would_have_failed(self):
        """
        Documents the exact wrong order the old code produced.

        Lexicographic descending: "9" > "10" > "-1" → Mid, Best, Worst.
        With the fix, Mid must NOT come before Best.
        """
        results = [
            _make_result("Strategy-Worst", mc_score=-1),
            _make_result("Strategy-Mid",   mc_score=9),
            _make_result("Strategy-Best",  mc_score=10),
        ]
        output = _run_summary(results)

        pos_best = output.index("Strategy-Best")
        pos_mid  = output.index("Strategy-Mid")

        # The bug would have put Mid (9) before Best (10); assert that is NOT the case
        assert pos_best < pos_mid, (
            "Strategy-Best (mc_score=10) must appear before Strategy-Mid (mc_score=9). "
            "Lexicographic sort would reverse these."
        )
