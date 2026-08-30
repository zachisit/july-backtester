# tests/test_gap_proximity_harness.py
"""Tests for the #298 research harness scripts.

PR #298 added 408 lines across four scripts with **zero tests**. These cover the
two that are unit-testable:

* ``scripts/gap_proximity_scan.py`` - ``qualifying`` / ``read_ohlcv`` / ``resolve``
* ``scripts/make_tearsheet.py``     - ``load_equity`` / ``stats`` / ``annual``

``check_annual.py`` and ``check_leverage.py`` are deliberately NOT covered: both
are top-level scripts with no functions and hardcoded Windows paths into one
contributor's ``output/runs/2026-08-06_10-35-14`` directory. They execute on
import, so they cannot be imported without side effects, let alone asserted on.
Testing them requires refactoring them into functions first.

The tests are written as invariants where the script's own docstrings make a
claim - the trailing average excluding the current bar, Sharpe being an excess
return, annual returns compounding back to the total - because those claims are
the reason to trust the research built on them.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gap_proximity_scan as gps  # noqa: E402
import make_tearsheet as mt  # noqa: E402


# ---------------------------------------------------------------------------
# gap_proximity_scan.qualifying
# ---------------------------------------------------------------------------

def _frame(closes, volumes, opens=None, highs=None):
    n = len(closes)
    idx = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame({
        "Open": opens if opens is not None else closes,
        "High": highs if highs is not None else closes,
        "Low": closes,
        "Close": closes,
        "Volume": volumes,
    }, index=idx, dtype=float)


class TestQualifying:
    """The script's docstring states the volume baseline excludes the bar being
    tested. That is the load-bearing claim: an inclusive baseline lets a huge bar
    inflate its own reference and the volume test partly defeats itself."""

    def test_volume_baseline_excludes_the_bar_itself(self):
        # 20 flat bars at volume 100, then one bar at 800.
        # Exclusive baseline -> 800/100 = 8.0x. Inclusive would be ~5.9x.
        closes = [100.0] * 20 + [200.0]
        vols = [100.0] * 20 + [800.0]
        q = gps.qualifying(_frame(closes, vols), move_th=0.30, vol_mult=8.0)
        assert bool(q.iloc[-1]), "8.0x spike must clear an 8.0x threshold"

    def test_an_inclusive_baseline_would_have_missed_it(self):
        """Pins the defect the exclusive shift(1) avoids, so it cannot regress."""
        closes = [100.0] * 20 + [200.0]
        vols = [100.0] * 20 + [800.0]
        df = _frame(closes, vols)
        inclusive = df["Volume"].rolling(gps.VOL_WIN).mean()   # no shift
        measured = df["Volume"].iloc[-1] / inclusive.iloc[-1]
        assert measured < 6.0            # ~5.9x - the understated figure
        exclusive = df["Volume"].rolling(gps.VOL_WIN).mean().shift(1)
        assert df["Volume"].iloc[-1] / exclusive.iloc[-1] == pytest.approx(8.0)

    def test_both_conditions_are_required(self):
        closes = [100.0] * 20 + [200.0]          # +100% move
        big_move_small_vol = gps.qualifying(
            _frame(closes, [100.0] * 21), move_th=0.30, vol_mult=5.0)
        assert not bool(big_move_small_vol.iloc[-1]), "move alone must not qualify"

        flat = [100.0] * 21                      # no move
        small_move_big_vol = gps.qualifying(
            _frame(flat, [100.0] * 20 + [800.0]), move_th=0.30, vol_mult=5.0)
        assert not bool(small_move_big_vol.iloc[-1]), "volume alone must not qualify"

    def test_move_takes_the_max_of_open_close_high(self):
        """A bar that gapped up and closed flat still counts - the move is the
        max of the open, close and high excursions from the prior close."""
        closes = [100.0] * 20 + [100.0]
        opens = [100.0] * 20 + [140.0]           # +40% on the open only
        q = gps.qualifying(
            _frame(closes, [100.0] * 20 + [800.0], opens=opens),
            move_th=0.30, vol_mult=5.0)
        assert bool(q.iloc[-1])

    def test_move_is_absolute_so_crashes_qualify(self):
        closes = [100.0] * 20 + [50.0]           # -50%
        q = gps.qualifying(_frame(closes, [100.0] * 20 + [800.0]),
                           move_th=0.30, vol_mult=5.0)
        assert bool(q.iloc[-1]), "a -50% bar is as parabolic as +50%"

    def test_thresholds_are_inclusive(self):
        """`>=`, not `>` - a bar exactly on the stated threshold qualifies.

        The threshold is derived from the bar's own arithmetic rather than
        written as 0.30. `130.0 / 100.0 - 1` is 0.30000000000000004, which is
        strictly greater than 0.30, so a literal would pass under `>` too and
        pin nothing. Mutation-checked: `>=` -> `>` fails this.
        """
        closes = [100.0] * 20 + [130.0]
        exact_move = 130.0 / 100.0 - 1           # the value the code computes
        df = _frame(closes, [100.0] * 20 + [500.0])
        assert bool(gps.qualifying(df, move_th=exact_move, vol_mult=5.0).iloc[-1])

        exact_vol_mult = 500.0 / 100.0           # volume exactly 5.0x baseline
        assert bool(gps.qualifying(df, move_th=0.30,
                                   vol_mult=exact_vol_mult).iloc[-1])

    def test_warmup_bars_never_qualify(self):
        """Before VOL_WIN+1 bars the baseline is NaN; NaN comparisons are False,
        so no bar can qualify on an incomplete window."""
        closes = [100.0] * 5 + [1000.0]
        q = gps.qualifying(_frame(closes, [100.0] * 5 + [99999.0]),
                           move_th=0.30, vol_mult=5.0)
        assert not q.any(), "no qualification is possible during warm-up"

    def test_returns_a_bool_aligned_series(self):
        df = _frame([100.0] * 25, [100.0] * 25)
        q = gps.qualifying(df, 0.30, 5.0)
        assert len(q) == len(df)
        assert q.index.equals(df.index)


# ---------------------------------------------------------------------------
# gap_proximity_scan.read_ohlcv / resolve
# ---------------------------------------------------------------------------

class TestReadOhlcv:

    def _write(self, path, tz=None, cols=("open", "high", "low", "close", "volume")):
        idx = pd.date_range("2020-01-01", periods=3, freq="D", tz=tz)
        df = pd.DataFrame({c: [1.0, 2.0, 3.0] for c in cols}, index=idx)
        df.to_parquet(path)
        return df

    def test_lowercase_columns_are_capitalised(self, tmp_path):
        p = tmp_path / "AAA.parquet"
        self._write(p)
        out = gps.read_ohlcv(p)
        assert list(out.columns) == ["Open", "High", "Low", "Close", "Volume"]

    def test_missing_required_column_returns_none(self, tmp_path):
        p = tmp_path / "BBB.parquet"
        self._write(p, cols=("open", "high", "low", "close"))   # no volume
        assert gps.read_ohlcv(p) is None

    def test_unreadable_file_returns_none(self, tmp_path):
        p = tmp_path / "nope.parquet"
        p.write_text("not parquet", encoding="utf-8")
        assert gps.read_ohlcv(p) is None

    def test_missing_file_returns_none(self, tmp_path):
        assert gps.read_ohlcv(tmp_path / "absent.parquet") is None

    def test_tz_aware_index_is_normalised_to_naive_midnight(self, tmp_path):
        p = tmp_path / "CCC.parquet"
        self._write(p, tz="US/Eastern")
        out = gps.read_ohlcv(p)
        assert out.index.tz is None
        assert (out.index == out.index.normalize()).all()

    def test_duplicate_dates_keep_the_last(self, tmp_path):
        p = tmp_path / "DDD.parquet"
        idx = pd.to_datetime(["2020-01-01", "2020-01-01", "2020-01-02"])
        pd.DataFrame({"open": [1.0, 9.0, 3.0], "high": [1.0, 9.0, 3.0],
                      "low": [1.0, 9.0, 3.0], "close": [1.0, 9.0, 3.0],
                      "volume": [1.0, 9.0, 3.0]}, index=idx).to_parquet(p)
        out = gps.read_ohlcv(p)
        assert len(out) == 2
        assert out["Close"].iloc[0] == 9.0            # last wins

    def test_output_is_sorted(self, tmp_path):
        p = tmp_path / "EEE.parquet"
        idx = pd.to_datetime(["2020-01-03", "2020-01-01", "2020-01-02"])
        pd.DataFrame({c: [1.0, 2.0, 3.0] for c in
                      ("open", "high", "low", "close", "volume")},
                     index=idx).to_parquet(p)
        out = gps.read_ohlcv(p)
        assert out.index.is_monotonic_increasing


class TestResolve:
    """Delisted securities are keyed TICKER-YYYYMM in the corpus, so a plain
    ticker lookup has to fall back to the stamped form or the name is silently
    dropped from the scan."""

    def test_exact_match_preferred(self, tmp_path):
        (tmp_path / "AAPL.parquet").touch()
        (tmp_path / "AAPL-200001.parquet").touch()
        assert gps.resolve("AAPL", tmp_path).name == "AAPL.parquet"

    def test_falls_back_to_the_delisted_stamp(self, tmp_path):
        (tmp_path / "BSC-200805.parquet").touch()
        assert gps.resolve("BSC", tmp_path).name == "BSC-200805.parquet"

    def test_picks_the_latest_stamp_when_a_ticker_was_reused(self, tmp_path):
        (tmp_path / "MER-198001.parquet").touch()
        (tmp_path / "MER-200812.parquet").touch()
        assert gps.resolve("MER", tmp_path).name == "MER-200812.parquet"

    def test_unknown_symbol_returns_none(self, tmp_path):
        assert gps.resolve("NOPE", tmp_path) is None


# ---------------------------------------------------------------------------
# make_tearsheet
# ---------------------------------------------------------------------------

def _curve(values, start="2020-01-01"):
    return pd.Series(values, index=pd.date_range(start, periods=len(values),
                                                 freq="D"), dtype=float)


class TestLoadEquity:

    def _run(self, tmp_path, rows):
        d = tmp_path / "analyzer_csvs" / "Port"
        d.mkdir(parents=True)
        (d / "x_equity.csv").write_text(rows, encoding="utf-8")
        return tmp_path

    def test_reads_sorts_and_drops_nan(self, tmp_path):
        run = self._run(tmp_path,
                        "date,equity\n2020-01-03,102\n2020-01-01,100\n"
                        "2020-01-02,\n2020-01-04,105\n")
        s = mt.load_equity(run)
        assert list(s.values) == [100.0, 102.0, 105.0]
        assert s.index.is_monotonic_increasing
        assert s.index.tz is None

    def test_exits_when_no_equity_csv_present(self, tmp_path):
        (tmp_path / "analyzer_csvs").mkdir()
        with pytest.raises(SystemExit):
            mt.load_equity(tmp_path)


class TestStats:

    def test_total_and_cagr_on_a_known_curve(self):
        eq = _curve([100.0, 200.0])                 # +100% over 1 day
        d = mt.stats(eq, rf=0.0)
        assert d["total_pct"] == pytest.approx(100.0)
        assert d["bars"] == 2

    def test_max_drawdown_is_the_trough_from_the_peak(self):
        eq = _curve([100.0, 120.0, 60.0, 90.0])     # -50% from 120
        assert mt.stats(eq, rf=0.0)["max_dd_pct"] == pytest.approx(-50.0)

    def test_no_drawdown_yields_nan_calmar_not_a_divide_by_zero(self):
        eq = _curve([100.0, 101.0, 102.0, 103.0])
        assert np.isnan(mt.stats(eq, rf=0.0)["calmar"])

    def test_sharpe_is_an_excess_return_not_rf_zero(self):
        """The docstring's whole point: computing Sharpe against zero gives 0.68
        where the engine reports 0.28 on the same curve. The two keys must
        differ whenever rf > 0, and sharpe must be the lower of the pair for a
        positive-drift curve."""
        rng = np.random.default_rng(7)
        eq = _curve(100000 * np.cumprod(1 + rng.normal(0.0006, 0.01, 400)))
        d = mt.stats(eq, rf=0.05)
        assert d["sharpe"] != pytest.approx(d["sharpe_rf0"])
        assert d["sharpe"] < d["sharpe_rf0"]

    def test_rf_zero_collapses_the_two_sharpes(self):
        rng = np.random.default_rng(7)
        eq = _curve(100000 * np.cumprod(1 + rng.normal(0.0006, 0.01, 400)))
        d = mt.stats(eq, rf=0.0)
        assert d["sharpe"] == pytest.approx(d["sharpe_rf0"])

    def test_flat_curve_yields_nan_sharpe_not_a_divide_by_zero(self):
        d = mt.stats(_curve([100.0] * 10), rf=0.0)
        assert np.isnan(d["sharpe"])
        assert np.isnan(d["sharpe_rf0"])

    def test_sharpe_is_self_consistent_at_non_daily_bars_per_year(self):
        rng = np.random.default_rng(3)
        eq = _curve(100000 * np.cumprod(1 + rng.normal(0.0004, 0.01, 500)))
        bpy, rf = 1260, 0.05
        r = eq.pct_change().dropna()
        rf_bar = (1 + rf) ** (1 / bpy) - 1
        ex = r - rf_bar
        expected = float(ex.mean() / ex.std(ddof=1) * np.sqrt(bpy))
        assert mt.stats(eq, rf=rf, bars_per_year=bpy)["sharpe"] == \
            pytest.approx(expected)


class TestAnnual:
    """The docstring claims compounding these reproduces the total exactly -
    stated because the engine's own annual_returns block does not (#299). That
    claim is the reason the script exists, so it gets pinned."""

    def test_annual_returns_compound_back_to_the_total(self):
        rng = np.random.default_rng(11)
        idx = pd.date_range("2019-06-01", "2023-03-01", freq="D")
        eq = pd.Series(100000 * np.cumprod(1 + rng.normal(0.0004, 0.008,
                                                          len(idx))), index=idx)
        rows = mt.annual(eq)
        compounded = np.prod(1 + rows["return_pct"].to_numpy() / 100.0) - 1
        total = eq.iloc[-1] / eq.iloc[0] - 1
        assert compounded == pytest.approx(total, rel=1e-9)

    def test_first_partial_year_measures_from_the_curves_start(self):
        """A run starting mid-year must measure year 1 from the first bar, not
        from an imaginary 1 January - that is what makes the compounding exact."""
        idx = pd.to_datetime(["2020-06-01", "2020-12-31", "2021-12-31"])
        eq = pd.Series([100.0, 110.0, 121.0], index=idx)
        rows = mt.annual(eq)
        got = dict(zip(rows["year"], rows["return_pct"]))
        assert got[2020] == pytest.approx(10.0)
        assert got[2021] == pytest.approx(10.0)

    def test_one_row_per_calendar_year(self):
        idx = pd.date_range("2020-01-01", "2022-12-31", freq="D")
        eq = pd.Series(np.linspace(100, 200, len(idx)), index=idx)
        assert sorted(mt.annual(eq)["year"].tolist()) == [2020, 2021, 2022]
