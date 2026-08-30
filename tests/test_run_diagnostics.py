"""Tests for scripts/check_annual.py and scripts/check_leverage.py.

Both were one-shot diagnostics with a run ID and Windows backslash paths baked
in at line 3 -- so on POSIX they did not fail on a missing file, the string was
not a path at all and they raised before doing anything. Refactored to take a
run directory and to return rows rather than print them, which is what makes
these assertions possible.

Fixtures are synthetic and written to tmp_path; nothing here reads a real run.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import check_annual as ca
import check_leverage as cl


# --------------------------------------------------------------- check_annual
def _write_verdict(tmp_path: Path, annual, curve, dates, total,
                   spy_curve=None, qqq_curve=None) -> Path:
    run = tmp_path / "run"
    run.mkdir(exist_ok=True)
    ec = {"dates": dates, "strategy": curve}
    if spy_curve:
        ec["SPY"] = spy_curve
    if qqq_curve:
        ec["QQQ"] = qqq_curve
    v = {"strategies": [{"strategy_return_pct": total,
                         "annual_returns": annual,
                         "equity_curve": ec}],
         "benchmarks": {}}
    (run / "llm_verdict.json").write_text(json.dumps(v), encoding="utf-8")
    return run


class TestAnnualReconciliation:
    def test_compounding_reproduces_the_total_when_consistent(self, tmp_path):
        """+10% then +10% compounds to 21%. The check must agree when the
        report is internally consistent -- otherwise it flags everything."""
        run = _write_verdict(
            tmp_path,
            annual=[{"year": 2020, "strategy_pct": 10.0},
                    {"year": 2021, "strategy_pct": 10.0}],
            curve=[100.0, 110.0, 121.0],
            dates=["2019-12-31", "2020-12-31", "2021-12-31"],
            total=21.0)
        row = ca.series_comparison(ca.load_verdict(run))[0]
        assert row["annual_compounded_pct"] == pytest.approx(21.0)
        assert row["compounded_minus_reported_pp"] == pytest.approx(0.0)

    def test_the_discrepancy_is_detected_when_they_disagree(self, tmp_path):
        """This is what makes it a repro for #299 rather than a calculator.
        Annuals compound to 21% while the report claims 15%."""
        run = _write_verdict(
            tmp_path,
            annual=[{"year": 2020, "strategy_pct": 10.0},
                    {"year": 2021, "strategy_pct": 10.0}],
            curve=[100.0, 110.0, 121.0],
            dates=["2019-12-31", "2020-12-31", "2021-12-31"],
            total=15.0)
        row = ca.series_comparison(ca.load_verdict(run))[0]
        assert row["annual_compounded_pct"] == pytest.approx(21.0)
        assert row["reported_total_pct"] == pytest.approx(15.0)
        assert row["compounded_minus_reported_pp"] == pytest.approx(6.0)

    def test_a_mid_year_start_measures_year_one_from_the_first_bar(self, tmp_path):
        """A run starting in July has no 1-January bar. Year one must be
        measured from the curve's first bar; anything else invents a return."""
        run = _write_verdict(
            tmp_path,
            annual=[{"year": 2020, "strategy_pct": 20.0},
                    {"year": 2021, "strategy_pct": 10.0}],
            curve=[100.0, 120.0, 132.0],
            dates=["2020-07-01", "2020-12-31", "2021-12-31"],
            total=32.0)
        rows = ca.per_year_comparison(ca.load_verdict(run))
        first = rows[0]
        assert first["year"] == 2020
        assert first["measured_from_first_bar"] is True
        assert first["derived_pct"] == pytest.approx(20.0)
        assert rows[1]["measured_from_first_bar"] is False
        assert rows[1]["derived_pct"] == pytest.approx(10.0)

    def test_missing_verdict_raises_rather_than_returning_empty(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ca.load_verdict(tmp_path / "nope")


# ------------------------------------------------------------- check_leverage
def _write_log(tmp_path: Path, rows, name="trades.csv", cols=None) -> Path:
    p = tmp_path / name
    pd.DataFrame(rows, columns=cols).to_csv(p, index=False)
    return p


class TestPeakExposure:
    def test_non_overlapping_holds_never_stack(self, tmp_path):
        """Two trades that do not overlap peak at one position, and gross
        exposure is one position's notional -- not the sum of both."""
        p = _write_log(tmp_path, [
            {"EntryDate": "2020-01-02", "ExitDate": "2020-01-10",
             "Shares": 100, "EntryPrice": 50.0, "Profit": 500.0},
            {"EntryDate": "2020-02-03", "ExitDate": "2020-02-10",
             "Shares": 100, "EntryPrice": 50.0, "Profit": 500.0},
        ])
        r = cl.peak_exposure(cl.load_trades(p), 100_000.0)
        assert r["peak_concurrency"] == 1
        assert r["entry_notional"] == pytest.approx(5_000.0)
        assert r["levered"] is False

    def test_overlapping_holds_stack_and_that_is_the_whole_point(self, tmp_path):
        """Same two trades, overlapping. Peak is 2 and notional is both."""
        p = _write_log(tmp_path, [
            {"EntryDate": "2020-01-02", "ExitDate": "2020-03-10",
             "Shares": 100, "EntryPrice": 50.0, "Profit": 500.0},
            {"EntryDate": "2020-02-03", "ExitDate": "2020-04-10",
             "Shares": 100, "EntryPrice": 50.0, "Profit": 500.0},
        ])
        r = cl.peak_exposure(cl.load_trades(p), 100_000.0)
        assert r["peak_concurrency"] == 2
        assert r["entry_notional"] == pytest.approx(10_000.0)

    def test_gross_exposure_against_a_hand_computed_book(self, tmp_path):
        """Two overlapping $5,000 positions on a $10,000 book with nothing
        realised: 10,000 / 10,000 = 100.0%, at the edge but not levered."""
        p = _write_log(tmp_path, [
            {"EntryDate": "2020-01-02", "ExitDate": "2020-03-10",
             "Shares": 100, "EntryPrice": 50.0, "Profit": 0.0},
            {"EntryDate": "2020-01-03", "ExitDate": "2020-03-11",
             "Shares": 100, "EntryPrice": 50.0, "Profit": 0.0},
        ])
        r = cl.peak_exposure(cl.load_trades(p), 10_000.0)
        assert r["equity_floor"] == pytest.approx(10_000.0)
        assert r["gross_exposure_pct"] == pytest.approx(100.0)
        assert r["levered"] is False

    def test_leverage_is_reported_when_notional_exceeds_the_floor(self, tmp_path):
        p = _write_log(tmp_path, [
            {"EntryDate": "2020-01-02", "ExitDate": "2020-03-10",
             "Shares": 200, "EntryPrice": 50.0, "Profit": 0.0},
            {"EntryDate": "2020-01-03", "ExitDate": "2020-03-11",
             "Shares": 200, "EntryPrice": 50.0, "Profit": 0.0},
        ])
        r = cl.peak_exposure(cl.load_trades(p), 10_000.0)
        assert r["entry_notional"] == pytest.approx(20_000.0)
        assert r["levered"] is True

    def test_a_close_settles_before_an_open_on_the_same_date(self, tmp_path):
        """Sorting on date alone leaves same-day ties in arbitrary order and
        inflates the peak. A hand-off on one date is one position, not two.

        Row order is deliberately adversarial -- the opening trade is listed
        FIRST. pandas' stable sort preserves insertion order within a date, so
        a date-only sort would put the open before the close and read 2. With
        the fixture in the natural order the mutation survives, which is how
        it was found.
        """
        p = _write_log(tmp_path, [
            {"EntryDate": "2020-01-10", "ExitDate": "2020-01-20",
             "Shares": 100, "EntryPrice": 50.0, "Profit": 0.0},
            {"EntryDate": "2020-01-02", "ExitDate": "2020-01-10",
             "Shares": 100, "EntryPrice": 50.0, "Profit": 0.0},
        ])
        r = cl.peak_exposure(cl.load_trades(p), 100_000.0)
        assert r["peak_concurrency"] == 1

    def test_a_trade_exiting_on_the_peak_date_is_not_counted_as_open(self, tmp_path):
        """The open set must agree with the concurrency count that defined the
        peak. A trade closing on the peak date settled before the opens that
        created it, so counting it would double-count capital that was freed.
        """
        p = _write_log(tmp_path, [
            {"EntryDate": "2020-01-02", "ExitDate": "2020-01-10",
             "Shares": 100, "EntryPrice": 50.0, "Profit": 0.0},
            {"EntryDate": "2020-01-03", "ExitDate": "2020-01-30",
             "Shares": 100, "EntryPrice": 50.0, "Profit": 0.0},
            {"EntryDate": "2020-01-10", "ExitDate": "2020-01-30",
             "Shares": 100, "EntryPrice": 50.0, "Profit": 0.0},
            {"EntryDate": "2020-01-10", "ExitDate": "2020-01-30",
             "Shares": 100, "EntryPrice": 50.0, "Profit": 0.0},
        ])
        r = cl.peak_exposure(cl.load_trades(p), 100_000.0)
        assert r["peak_concurrency"] == 3
        assert r["open_positions"] == r["peak_concurrency"]
        assert r["entry_notional"] == pytest.approx(15_000.0)

    def test_missing_columns_raise_a_named_error(self, tmp_path):
        p = _write_log(tmp_path, [{"EntryDate": "2020-01-02", "Shares": 1}])
        with pytest.raises(KeyError, match="missing required columns"):
            cl.load_trades(p)
