"""
Regression test for issue #319 — generate_final_summary defaulted
``max_acceptable_drawdown`` to ``-9999.0`` while the other three summary
functions default it to ``1.0``.

``max_drawdown`` is a positive magnitude, so the filter
``max_drawdown <= max_dd_filter`` with ``max_dd_filter = -9999`` is
unsatisfiable — every strategy is filtered out and the single-asset final
summary prints "No strategies met the final criteria" with no hint why, whenever
the key is absent from the config.
"""

import pytest

import helpers.summary as summary


@pytest.fixture
def permissive_config(monkeypatch):
    # Isolate the DD filter: make every OTHER filter permissive, and REMOVE
    # max_acceptable_drawdown so the code path under test uses its default.
    monkeypatch.setitem(summary.CONFIG, "mc_score_min_to_show_in_summary", -999)
    monkeypatch.setitem(summary.CONFIG, "min_pandl_to_show_in_summary", -999.0)
    monkeypatch.setitem(summary.CONFIG, "min_calmar_to_show_in_summary", -999.0)
    monkeypatch.setitem(summary.CONFIG, "min_trades_for_mc", 1)
    monkeypatch.setitem(summary.CONFIG, "verbose_output", False)
    # Harden benchmark isolation so adding a benchmark to a test can't couple to
    # config.py's min_performance_vs_spy/qqq.
    monkeypatch.setitem(summary.CONFIG, "min_performance_vs_spy", -9999.0)
    monkeypatch.setitem(summary.CONFIG, "min_performance_vs_qqq", -9999.0)
    monkeypatch.delitem(summary.CONFIG, "max_acceptable_drawdown", raising=False)


def _result(max_dd=0.2):
    return {
        "Strategy": "MyStrat", "Trades": 100, "max_drawdown": max_dd,
        "mc_score": 0, "pnl_percent": 0.5, "calmar_ratio": 1.0,
    }


def test_default_dd_filter_does_not_reject_a_normal_strategy(permissive_config, capsys):
    # A strategy with a normal 20% max drawdown must survive the default DD
    # filter (default 1.0 = 100% DD allowed), not be silently dropped.
    summary.generate_final_summary([_result(max_dd=0.2)], benchmark_returns={})
    out = capsys.readouterr().out
    assert "No strategies met the final criteria" not in out, \
        "default max_acceptable_drawdown filtered out a normal strategy (#319)"
    assert "MyStrat" in out


def test_explicit_dd_filter_still_rejects_over_threshold(permissive_config, monkeypatch, capsys):
    # The filter still works when configured: a 50% DD strategy is rejected by a
    # 30% cap, and the printed hint names the DD threshold (the "no hint why"
    # half of #319).
    monkeypatch.setitem(summary.CONFIG, "max_acceptable_drawdown", 0.30)
    summary.generate_final_summary([_result(max_dd=0.5)], benchmark_returns={})
    out = capsys.readouterr().out
    assert "No strategies met the final criteria" in out
    assert "30%" in out  # the filter hint shows the DD threshold


def test_dd_exactly_at_cap_passes(permissive_config, monkeypatch, capsys):
    # Boundary: max_drawdown == cap must PASS (filter is <=, not <).
    monkeypatch.setitem(summary.CONFIG, "max_acceptable_drawdown", 0.30)
    summary.generate_final_summary([_result(max_dd=0.30)], benchmark_returns={})
    out = capsys.readouterr().out
    assert "No strategies met the final criteria" not in out
    assert "MyStrat" in out


def test_over_100pct_dd_dropped_under_default(permissive_config, capsys):
    # Documents the current behavior: a blown (>100% DD, e.g. margined) strategy
    # is dropped by the 1.0 default. Pins it either way (see PR discussion).
    summary.generate_final_summary([_result(max_dd=1.2)], benchmark_returns={})
    out = capsys.readouterr().out
    assert "No strategies met the final criteria" in out


@pytest.mark.parametrize("func_name,args", [
    ("generate_final_summary", None),
    ("generate_portfolio_summary_report", None),
])
def test_all_summary_functions_share_the_default(permissive_config, capsys, func_name, args):
    # The key-absent scenario must not drop a normal strategy in any summary
    # function — locks the shared _DEFAULT_MAX_ACCEPTABLE_DD convention.
    func = getattr(summary, func_name)
    func([_result(max_dd=0.2)], benchmark_returns={})
    out = capsys.readouterr().out
    assert "No strategies met the final criteria" not in out
    assert "MyStrat" in out


def test_default_constant_is_one():
    assert summary._DEFAULT_MAX_ACCEPTABLE_DD == 1.0
