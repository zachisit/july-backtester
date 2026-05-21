import json
import os

import pandas as pd
import pytest

from helpers.llm_verdict import generate_llm_verdict, _build_equity_curve, _compute_smoothness, _fmt, _fmt_pct


def _make_timeline(n_days=500, start="2020-01-02", growth=0.0003):
    """Daily equity series starting at 100 000, growing at `growth` per day."""
    idx = pd.bdate_range(start=start, periods=n_days)
    equity = 100_000 * (1 + growth) ** pd.Series(range(n_days), index=idx)
    return equity


def _make_bm_df(n_days=500, start="2020-01-02", growth=0.0002):
    """Minimal OHLCV DataFrame for a benchmark ticker."""
    idx = pd.bdate_range(start=start, periods=n_days)
    close = 400 * (1 + growth) ** pd.Series(range(n_days), index=idx)
    return pd.DataFrame({"Close": close}, index=idx)


def _result(strategy="Strat A", portfolio="P1", pnl=0.15, trades=50,
            sharpe=1.2, calmar=0.9, max_dd=0.18, win_rate=0.55,
            mc_score=70, mc_verdict="Pass", wfa_verdict="Pass",
            wfa_rolling_verdict=None, timeline=None):
    r = {
        "Strategy": strategy,
        "Portfolio": portfolio,
        "pnl_percent": pnl,
        "Trades": trades,
        "sharpe_ratio": sharpe,
        "calmar_ratio": calmar,
        "max_drawdown": max_dd,
        "win_rate": win_rate,
        "mc_score": mc_score,
        "mc_verdict": mc_verdict,
        "wfa_verdict": wfa_verdict,
        "wfa_rolling_verdict": wfa_rolling_verdict,
        "vs_spy_benchmark": pnl - 0.10,
        "portfolio_timeline": timeline if timeline is not None else _make_timeline(),
    }
    return r


_BENCH = {"SPY": 0.10}


class TestFileOutput:
    def test_file_created(self, tmp_path):
        path = generate_llm_verdict([_result()], _BENCH, output_dir=str(tmp_path))
        assert os.path.exists(path)
        assert path.endswith("llm_verdict.json")

    def test_valid_json(self, tmp_path):
        path = generate_llm_verdict([_result()], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            data = json.load(f)
        assert "strategies" in data
        assert "summary" in data

    def test_empty_results_writes_file(self, tmp_path):
        path = generate_llm_verdict([], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            data = json.load(f)
        assert data["summary"]["total_strategies_with_trades"] == 0

    def test_zero_trades_excluded(self, tmp_path):
        results = [_result(trades=0), _result(strategy="B", trades=10)]
        path = generate_llm_verdict(results, _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            data = json.load(f)
        assert data["summary"]["total_strategies_with_trades"] == 1
        assert data["strategies"][0]["strategy"] == "B"


class TestBeatsVerdict:
    def test_beats_spy_true_when_outperforms(self, tmp_path):
        path = generate_llm_verdict([_result(pnl=0.15)], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert s["beats_spy"] is True

    def test_beats_spy_false_when_underperforms(self, tmp_path):
        path = generate_llm_verdict([_result(pnl=0.05)], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert s["beats_spy"] is False

    def test_verdict_contains_beats_when_outperforms(self, tmp_path):
        path = generate_llm_verdict([_result(pnl=0.15)], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert "BEATS" in s["verdict"]
        assert "SPY" in s["verdict"]

    def test_verdict_contains_lags_when_underperforms(self, tmp_path):
        path = generate_llm_verdict([_result(pnl=0.05)], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert "LAGS" in s["verdict"]

    def test_outperformance_pp_arithmetic(self, tmp_path):
        path = generate_llm_verdict([_result(pnl=0.15)], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        detail = s["benchmarks"]["SPY"]
        assert abs(detail["outperformance_pp"] - 5.0) < 1e-6

    def test_strategy_return_pct_correct(self, tmp_path):
        path = generate_llm_verdict([_result(pnl=0.15)], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert abs(s["strategy_return_pct"] - 15.0) < 1e-6


class TestSummaryBlock:
    def test_beats_spy_count(self, tmp_path):
        results = [_result(pnl=0.20), _result(strategy="B", pnl=0.05), _result(strategy="C", pnl=0.15)]
        for r in results:
            r["vs_spy_benchmark"] = r["pnl_percent"] - 0.10
        path = generate_llm_verdict(results, _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            summary = json.load(f)["summary"]
        assert summary["beats_spy_count"] == 2

    def test_beats_spy_pct(self, tmp_path):
        results = [_result(pnl=0.20), _result(strategy="B", pnl=0.05)]
        for r in results:
            r["vs_spy_benchmark"] = r["pnl_percent"] - 0.10
        path = generate_llm_verdict(results, _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            summary = json.load(f)["summary"]
        assert abs(summary["beats_spy_pct"] - 50.0) < 1e-6


class TestSortingAndRanking:
    def test_sorted_best_first(self, tmp_path):
        results = [
            _result(strategy="Low", pnl=0.05),
            _result(strategy="High", pnl=0.25),
            _result(strategy="Mid", pnl=0.15),
        ]
        for r in results:
            r["vs_spy_benchmark"] = r["pnl_percent"] - 0.10
        path = generate_llm_verdict(results, _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            strategies = json.load(f)["strategies"]
        names = [s["strategy"] for s in strategies]
        assert names == ["High", "Mid", "Low"]

    def test_rank_field_present(self, tmp_path):
        path = generate_llm_verdict([_result()], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert s["rank"] == 1


class TestMultipleBenchmarks:
    def test_all_benchmarks_in_detail(self, tmp_path):
        bench = {"SPY": 0.10, "QQQ": 0.14}
        r = _result(pnl=0.20)
        r["vs_spy_benchmark"] = 0.10
        r["vs_qqq_benchmark"] = 0.06
        path = generate_llm_verdict([r], bench, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert "SPY" in s["benchmarks"]
        assert "QQQ" in s["benchmarks"]

    def test_primary_benchmark_drives_beats_key(self, tmp_path):
        bench = {"QQQ": 0.14, "SPY": 0.10}
        r = _result(pnl=0.12)
        r["vs_qqq_benchmark"] = -0.02
        r["vs_spy_benchmark"] = 0.02
        path = generate_llm_verdict([r], bench, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert "beats_qqq" in s
        assert s["beats_qqq"] is False


class TestHelpers:
    def test_fmt_none(self):
        assert _fmt(None) is None

    def test_fmt_rounds(self):
        assert _fmt(1.23456789) == 1.2346

    def test_fmt_pct_converts_fraction(self):
        assert abs(_fmt_pct(0.18) - 18.0) < 1e-9

    def test_fmt_pct_none(self):
        assert _fmt_pct(None) is None


class TestEquityCurve:
    def test_equity_curve_present_in_output(self, tmp_path):
        path = generate_llm_verdict([_result()], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert "equity_curve" in s
        assert s["equity_curve"]["frequency"] == "monthly"

    def test_strategy_series_starts_at_100(self, tmp_path):
        path = generate_llm_verdict([_result()], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert s["equity_curve"]["strategy"][0] == 100.0

    def test_growing_curve_ends_above_100(self, tmp_path):
        r = _result(timeline=_make_timeline(growth=0.001))
        path = generate_llm_verdict([r], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert s["equity_curve"]["strategy"][-1] > 100.0

    def test_benchmark_curve_included_when_dfs_provided(self, tmp_path):
        bm_dfs = {"SPY": _make_bm_df()}
        path = generate_llm_verdict([_result()], _BENCH, output_dir=str(tmp_path), benchmark_dfs=bm_dfs)
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert "SPY" in s["equity_curve"]
        assert s["equity_curve"]["SPY"][0] == 100.0

    def test_benchmark_curve_absent_without_dfs(self, tmp_path):
        path = generate_llm_verdict([_result()], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert "SPY" not in s["equity_curve"]

    def test_dates_and_series_same_length(self, tmp_path):
        bm_dfs = {"SPY": _make_bm_df()}
        path = generate_llm_verdict([_result()], _BENCH, output_dir=str(tmp_path), benchmark_dfs=bm_dfs)
        with open(path) as f:
            ec = json.load(f)["strategies"][0]["equity_curve"]
        assert len(ec["dates"]) == len(ec["strategy"]) == len(ec["SPY"])

    def test_no_crash_when_timeline_is_none(self, tmp_path):
        r = _result(timeline=None)
        r["portfolio_timeline"] = None
        path = generate_llm_verdict([r], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert s["equity_curve"] == {}

    def test_annual_returns_present(self, tmp_path):
        path = generate_llm_verdict([_result()], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert isinstance(s["annual_returns"], list)
        assert len(s["annual_returns"]) >= 1

    def test_annual_returns_have_year_and_strategy_pct(self, tmp_path):
        path = generate_llm_verdict([_result()], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        for row in s["annual_returns"]:
            assert "year" in row
            assert "strategy_pct" in row

    def test_annual_returns_include_benchmark_when_dfs_provided(self, tmp_path):
        bm_dfs = {"SPY": _make_bm_df()}
        path = generate_llm_verdict([_result()], _BENCH, output_dir=str(tmp_path), benchmark_dfs=bm_dfs)
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        for row in s["annual_returns"]:
            assert "SPY_pct" in row

    def test_build_equity_curve_returns_empty_for_short_series(self):
        short = _make_timeline(n_days=5)
        curve, annual = _build_equity_curve(short, None, [])
        assert curve == {}
        assert annual == []

    def test_strategy_outperforms_benchmark_visible_in_curve(self, tmp_path):
        # Strategy grows faster than SPY — final normalized value should be higher
        fast_tl = _make_timeline(n_days=500, growth=0.0008)
        slow_bm = _make_bm_df(n_days=500, growth=0.0001)
        bm_dfs = {"SPY": slow_bm}
        r = _result(timeline=fast_tl)
        path = generate_llm_verdict([r], _BENCH, output_dir=str(tmp_path), benchmark_dfs=bm_dfs)
        with open(path) as f:
            ec = json.load(f)["strategies"][0]["equity_curve"]
        assert ec["strategy"][-1] > ec["SPY"][-1]


class TestCurveSmoothness:
    def _monthly(self, values):
        """Build a month-end Series from a list of values."""
        idx = pd.date_range("2015-01-01", periods=len(values), freq="ME")
        return pd.Series(values, index=idx, dtype=float)

    def test_returns_none_when_fewer_than_12_months(self):
        short = self._monthly([100.0 * 1.01**i for i in range(10)])
        assert _compute_smoothness(short) is None

    def test_returns_none_for_none_input(self):
        assert _compute_smoothness(None) is None

    def test_all_keys_present(self):
        vals = [100.0 * 1.01**i for i in range(36)]
        s = _compute_smoothness(self._monthly(vals))
        assert s is not None
        for key in (
            "smoothness_r2", "monthly_return_std_pct", "positive_months_pct",
            "max_monthly_drawdown_pct", "longest_flat_streak_months",
            "upthrust_count", "smooth_verdict", "smooth_notes",
        ):
            assert key in s

    def test_perfectly_linear_r2_near_one(self):
        vals = [100.0 * 1.01**i for i in range(60)]
        s = _compute_smoothness(self._monthly(vals))
        assert s["smoothness_r2"] >= 0.99

    def test_perfectly_linear_verdict_smooth(self):
        vals = [100.0 * 1.01**i for i in range(60)]
        s = _compute_smoothness(self._monthly(vals))
        assert s["smooth_verdict"] == "SMOOTH"

    def test_smooth_notes_empty_when_smooth(self):
        vals = [100.0 * 1.01**i for i in range(60)]
        s = _compute_smoothness(self._monthly(vals))
        assert s["smooth_notes"] == []

    def test_plateau_14_months_detected(self):
        # 18 months growing, 14 months below peak, 12 months recovery
        vals = [100.0 * 1.01**i for i in range(18)]
        peak = vals[-1]
        vals += [peak * 0.97] * 14
        vals += [peak * 1.01**i for i in range(1, 13)]
        s = _compute_smoothness(self._monthly(vals))
        assert s["longest_flat_streak_months"] == 14

    def test_plateau_triggers_non_smooth_verdict(self):
        vals = [100.0 * 1.01**i for i in range(18)]
        peak = vals[-1]
        vals += [peak * 0.97] * 14
        vals += [peak * 1.01**i for i in range(1, 13)]
        s = _compute_smoothness(self._monthly(vals))
        assert s["smooth_verdict"] != "SMOOTH"

    def test_no_plateau_on_monotone_growth(self):
        vals = [100.0 * 1.01**i for i in range(60)]
        s = _compute_smoothness(self._monthly(vals))
        assert s["longest_flat_streak_months"] == 0

    def test_two_failures_yields_rough(self):
        # 11 growing months, 25 months below peak, 10 recovery
        # → longest_flat = 25 (>= 12) AND positive_months ~40% (< 60%)
        vals = [100.0 * 1.01**i for i in range(11)]
        peak = vals[-1]
        vals += [peak * 0.95] * 25
        vals += [peak * 1.01**i for i in range(1, 11)]
        s = _compute_smoothness(self._monthly(vals))
        assert s["longest_flat_streak_months"] >= 12
        assert s["positive_months_pct"] < 60.0
        assert s["smooth_verdict"] == "ROUGH"

    def test_one_failure_yields_acceptable(self):
        # Pattern: 2 up months (+0.5%) then 3 flat months, repeating
        # positive_months ≈ 40% (< 60%) — only 1 threshold fails
        vals = [100.0]
        for cycle in range(12):
            for j in range(5):
                vals.append(vals[-1] * 1.005 if j < 2 else vals[-1])
        s = _compute_smoothness(self._monthly(vals))
        assert s["positive_months_pct"] < 60.0
        assert s["smooth_verdict"] == "ACCEPTABLE"

    def test_curve_smoothness_in_generate_output(self, tmp_path):
        r = _result(timeline=_make_timeline(n_days=1000, growth=0.0005))
        path = generate_llm_verdict([r], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert "curve_smoothness" in s
        assert s["curve_smoothness"] is not None
        assert s["curve_smoothness"]["smooth_verdict"] in ("SMOOTH", "ACCEPTABLE", "ROUGH")

    def test_curve_smoothness_null_for_short_timeline(self, tmp_path):
        r = _result(timeline=_make_timeline(n_days=150, growth=0.0005))
        path = generate_llm_verdict([r], _BENCH, output_dir=str(tmp_path))
        with open(path) as f:
            s = json.load(f)["strategies"][0]
        assert s["curve_smoothness"] is None
