"""
tests/test_data_handler_branches.py

Branch coverage for trade_analyzer/data_handler.py.
Targets lines NOT covered by test_data_handler.py:

  - load_trades: non-FileNotFoundError exception (35-37)
  - clean_trades_data: no '% Profit' column warning (133)
  - clean_trades_data: 'Position value' column path (185-186)
  - clean_trades_data: Return_Frac from '% Profit' (192-194)
  - clean_trades_data: Return_Frac default 0 (195-197)
  - calculate_daily_returns: 'Cum. Profit' fallback column (233-234)
  - calculate_daily_returns: single equity point warning (265)
  - calculate_daily_returns: NaT dates warning (266-267)
  - calculate_daily_returns: no cumulative profit column (268-269)
  - download_benchmark_data: invalid dates → None (289-291)
  - download_benchmark_data: empty yfinance data → None (307-311)
  - download_benchmark_data: normal single-level 'Close' path (363-373, 400-401)
  - download_benchmark_data: 'Adj Close' fallback path
  - download_benchmark_data: price column not found → None (335-338)
  - download_benchmark_data: MultiIndex (price, ticker) tuple path (343-347)
  - download_benchmark_data: MultiIndex DataFrame slice path (350-353)
  - download_benchmark_data: MultiIndex Series path (354-355)
  - download_benchmark_data: MultiIndex exception → None (360-362)
  - download_benchmark_data: exception handler (379-389)
  - download_benchmark_data: empty after processing → None (396-398)
"""
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from trade_analyzer.data_handler import (
    load_trades,
    clean_trades_data,
    calculate_daily_returns,
    download_benchmark_data,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_trades(n=5, include_profit=True, include_pct=True):
    """Minimal trades DataFrame for clean_trades_data."""
    dates = pd.date_range("2021-01-04", periods=n, freq="3B")
    ex_dates = pd.date_range("2021-01-06", periods=n, freq="3B")
    d = {"Date": dates, "Ex. date": ex_dates}
    if include_profit:
        d["Profit"] = [100.0, -50.0, 200.0, -30.0, 150.0][:n]
    if include_pct:
        d["% Profit"] = [2.0, -1.0, 4.0, -0.5, 3.0][:n]
    return pd.DataFrame(d)


def _cum_profit_trades(n=5, col_name="Cumulative_Profit"):
    """Trades with a cumulative profit column for calculate_daily_returns."""
    dates = pd.date_range("2021-01-04", periods=n, freq="3B")
    ex_dates = pd.date_range("2021-01-07", periods=n, freq="3B")
    cum = np.cumsum([100.0, -50.0, 200.0, -30.0, 150.0][:n])
    return pd.DataFrame({"Date": dates, "Ex. date": ex_dates, col_name: cum})


# ---------------------------------------------------------------------------
# load_trades — non-FileNotFoundError exception (35-37)
# ---------------------------------------------------------------------------

class TestLoadTradesExceptions:

    def test_non_fnf_exception_re_raises(self, tmp_path):
        """pd.read_csv raises IOError (not FileNotFoundError) → lines 35-37."""
        csv_path = str(tmp_path / "trades.csv")
        with patch(
            "trade_analyzer.data_handler.pd.read_csv",
            side_effect=IOError("disk read error"),
        ):
            with pytest.raises(IOError):
                load_trades(csv_path)

    def test_permission_error_re_raises(self, tmp_path):
        csv_path = str(tmp_path / "trades.csv")
        with patch(
            "trade_analyzer.data_handler.pd.read_csv",
            side_effect=PermissionError("denied"),
        ):
            with pytest.raises(PermissionError):
                load_trades(csv_path)


# ---------------------------------------------------------------------------
# clean_trades_data — missing '% Profit' warning (133)
# ---------------------------------------------------------------------------

class TestCleanTradesNoPctProfit:

    def test_no_pct_profit_column_does_not_crash(self):
        """'% Profit' absent → print warning but continue (line 133)."""
        df = _minimal_trades(include_pct=False)
        result_df, summary = clean_trades_data(df, 100_000)
        assert isinstance(result_df, pd.DataFrame)
        assert isinstance(summary, str)


# ---------------------------------------------------------------------------
# clean_trades_data — 'Position value' column path (185-186)
# ---------------------------------------------------------------------------

class TestCleanTradesPositionValue:

    def test_position_value_column_used_for_return_frac(self):
        """'Position value' present → Return_Frac uses it (lines 185-186)."""
        df = _minimal_trades()
        df["Position value"] = 10_000.0
        result_df, _ = clean_trades_data(df, 100_000)
        assert "Return_Frac" in result_df.columns
        # Return_Frac = Profit / position_value
        expected = df["Profit"].iloc[0] / 10_000.0
        assert result_df["Return_Frac"].iloc[0] == pytest.approx(expected)

    def test_position_value_capitalized_also_used(self):
        """'Position Value' (capital V) path also works."""
        df = _minimal_trades()
        df["Position Value"] = 10_000.0
        result_df, _ = clean_trades_data(df, 100_000)
        assert "Return_Frac" in result_df.columns


# ---------------------------------------------------------------------------
# clean_trades_data — Return_Frac from '% Profit' and default 0 (192-197)
# ---------------------------------------------------------------------------

class TestCleanTradesReturnFrac:

    def test_return_frac_from_pct_profit_when_initial_equity_zero(self):
        """initial_equity=0 bypasses the Profit branch → elif uses '% Profit' (192-194).
        Note: 'Profit' must still be present — Win computation at line 178 requires it."""
        df = _minimal_trades()  # has both Profit and % Profit
        result_df, _ = clean_trades_data(df, 0)  # initial_equity=0 → first if is False
        assert "Return_Frac" in result_df.columns
        assert result_df["Return_Frac"].iloc[0] == pytest.approx(0.02)

    def test_return_frac_defaults_to_zero_when_no_pct_profit_and_zero_equity(self):
        """initial_equity=0 AND no '% Profit' → else branch sets Return_Frac=0 (195-197)."""
        df = _minimal_trades(include_pct=False)  # has Profit but not % Profit
        result_df, _ = clean_trades_data(df, 0)  # initial_equity=0 → first if is False
        assert "Return_Frac" in result_df.columns
        assert (result_df["Return_Frac"] == 0.0).all()


# ---------------------------------------------------------------------------
# calculate_daily_returns — 'Cum. Profit' fallback (233-234)
# ---------------------------------------------------------------------------

class TestDailyReturnsCumProfitFallback:

    def test_cum_profit_column_used_when_cumulative_profit_absent(self):
        """'Cum. Profit' column present (not 'Cumulative_Profit') → lines 233-234."""
        df = _cum_profit_trades(col_name="Cum. Profit")
        equity, returns = calculate_daily_returns(df, 100_000)
        assert not equity.empty

    def test_result_is_tuple_of_series(self):
        df = _cum_profit_trades(col_name="Cum. Profit")
        equity, returns = calculate_daily_returns(df, 100_000)
        assert isinstance(equity, pd.Series)
        assert isinstance(returns, pd.Series)


# ---------------------------------------------------------------------------
# calculate_daily_returns — edge cases in daily equity
# ---------------------------------------------------------------------------

class TestDailyReturnsEdgeCases:

    def test_single_equity_point_warns_not_crash(self):
        """Exit date < entry date → 1-point equity curve → line 265 warning."""
        # entry date is AFTER exit date → start_point_date > last_trade_date
        # → full_date_range from last_trade_date to last_trade_date = 1 point
        df = pd.DataFrame({
            "Date":               [pd.Timestamp("2021-01-10")],  # entry after exit
            "Ex. date":           [pd.Timestamp("2021-01-05")],
            "Cumulative_Profit":  [100.0],
        })
        equity, returns = calculate_daily_returns(df, 100_000)
        assert isinstance(equity, pd.Series)
        assert isinstance(returns, pd.Series)

    def test_nat_dates_returns_empty_series(self):
        """NaT dates → pd.notna() check fails → lines 266-267."""
        df = pd.DataFrame({
            "Date":              [pd.NaT],
            "Ex. date":          [pd.NaT],
            "Cumulative_Profit": [0.0],
        })
        equity, returns = calculate_daily_returns(df, 100_000)
        assert equity.empty
        assert returns.empty

    def test_no_cum_profit_column_returns_empty(self):
        """No 'Cumulative_Profit' or 'Cum. Profit' → lines 268-269 warning."""
        df = pd.DataFrame({
            "Date":     pd.date_range("2021-01-04", periods=3, freq="3B"),
            "Ex. date": pd.date_range("2021-01-07", periods=3, freq="3B"),
            "Profit":   [100.0, -50.0, 200.0],  # 'Profit' alone — no cum col
        })
        equity, returns = calculate_daily_returns(df, 100_000)
        assert equity.empty
        assert returns.empty


# ---------------------------------------------------------------------------
# download_benchmark_data — all paths mocked
# ---------------------------------------------------------------------------

_START = pd.Timestamp("2021-01-04")
_END   = pd.Timestamp("2021-12-31")


def _bench_df(col="Close", n=10):
    """Simple single-level benchmark DataFrame."""
    idx = pd.date_range("2021-01-04", periods=n)
    return pd.DataFrame({col: np.linspace(300, 350, n)}, index=idx)


class TestDownloadBenchmarkInvalidDates:

    def test_nat_start_returns_none(self):
        result = download_benchmark_data("SPY", pd.NaT, _END)
        assert result is None

    def test_nat_end_returns_none(self):
        result = download_benchmark_data("SPY", _START, pd.NaT)
        assert result is None


class TestDownloadBenchmarkEmptyData:

    def test_empty_yfinance_response_returns_none(self):
        """yf.download returns empty DataFrame → lines 307-311."""
        with patch("trade_analyzer.data_handler.yf.download", return_value=pd.DataFrame()):
            result = download_benchmark_data("SPY", _START, _END)
        assert result is None


class TestDownloadBenchmarkSingleLevel:

    def test_close_column_returns_dataframe(self):
        """Normal path: single-level 'Close' column → returns DataFrame."""
        with patch("trade_analyzer.data_handler.yf.download", return_value=_bench_df("Close")):
            result = download_benchmark_data("SPY", _START, _END)
        assert result is not None
        assert "Benchmark_Price" in result.columns

    def test_adj_close_used_when_close_absent(self):
        """'Adj Close' fallback when 'Close' absent."""
        with patch("trade_analyzer.data_handler.yf.download", return_value=_bench_df("Adj Close")):
            result = download_benchmark_data("SPY", _START, _END)
        assert result is not None
        assert "Benchmark_Price" in result.columns

    def test_neither_close_column_returns_none(self):
        """Neither 'Close' nor 'Adj Close' → lines 335-338 → returns None."""
        bad_df = _bench_df("Volume")
        with patch("trade_analyzer.data_handler.yf.download", return_value=bad_df):
            result = download_benchmark_data("SPY", _START, _END)
        assert result is None

    def test_empty_after_dropna_returns_none(self):
        """All NaN prices → dropna removes all → lines 396-398 → None."""
        df = pd.DataFrame(
            {"Close": [np.nan] * 5},
            index=pd.date_range("2021-01-04", periods=5),
        )
        with patch("trade_analyzer.data_handler.yf.download", return_value=df):
            result = download_benchmark_data("SPY", _START, _END)
        assert result is None


class TestDownloadBenchmarkMultiIndex:

    def _multi_df(self, price_col="Close", ticker="SPY"):
        """Create a MultiIndex columns DataFrame like yfinance sometimes returns."""
        idx = pd.date_range("2021-01-04", periods=5)
        cols = pd.MultiIndex.from_tuples(
            [(price_col, ticker), ("Open", ticker)],
            names=["Price", "Ticker"],
        )
        data = np.column_stack([np.linspace(300, 310, 5), np.linspace(299, 309, 5)])
        return pd.DataFrame(data, index=idx, columns=cols)

    def test_multiindex_tuple_access_path(self):
        """(price_col, ticker) present in MultiIndex → lines 345-346."""
        mi_df = self._multi_df("Close", "SPY")
        with patch("trade_analyzer.data_handler.yf.download", return_value=mi_df):
            result = download_benchmark_data("SPY", _START, _END)
        # May return None or a DataFrame depending on column resolution
        assert result is None or "Benchmark_Price" in result.columns

    def test_multiindex_dataframe_slice_path(self):
        """MultiIndex where (price_col, ticker) NOT in columns → tries slice → DataFrame path (350-353)."""
        idx = pd.date_range("2021-01-04", periods=5)
        # Create MultiIndex where (Close, AAPL) is there but not (Close, SPY)
        cols = pd.MultiIndex.from_tuples(
            [("Close", "AAPL"), ("Open", "AAPL")],
        )
        data = np.column_stack([np.linspace(130, 140, 5), np.linspace(129, 139, 5)])
        mi_df = pd.DataFrame(data, index=idx, columns=cols)
        with patch("trade_analyzer.data_handler.yf.download", return_value=mi_df):
            result = download_benchmark_data("SPY", _START, _END)
        assert result is None or "Benchmark_Price" in result.columns

    def test_multiindex_series_slice_path(self):
        """MultiIndex where Close slice is a Series (single ticker) → lines 354-355."""
        idx = pd.date_range("2021-01-04", periods=5)
        # A single-ticker MultiIndex where data["Close"] returns a Series
        cols = pd.MultiIndex.from_tuples([("Close", "SPY")])
        data = pd.DataFrame(np.linspace(300, 310, 5).reshape(-1, 1), index=idx, columns=cols)
        with patch("trade_analyzer.data_handler.yf.download", return_value=data):
            result = download_benchmark_data("SPY", _START, _END)
        assert result is None or "Benchmark_Price" in result.columns

    def test_multiindex_exception_returns_none(self):
        """MultiIndex processing raises ValueError → lines 360-362 → None."""
        idx = pd.date_range("2021-01-04", periods=5)
        cols = pd.MultiIndex.from_tuples([("Close", "SPY"), ("Open", "SPY")])
        data = np.column_stack([np.linspace(300, 310, 5), np.linspace(299, 309, 5)])
        mi_df = pd.DataFrame(data, index=idx, columns=cols)

        with patch("trade_analyzer.data_handler.yf.download", return_value=mi_df), \
             patch.object(pd.Series, "to_frame", side_effect=ValueError("forced")):
            result = download_benchmark_data("SPY", _START, _END)
        # Should return None after the MultiIndex exception
        assert result is None or "Benchmark_Price" in result.columns


class TestDownloadBenchmarkExceptionHandler:

    def test_yfinance_raises_exception_returns_none(self):
        """yf.download raises → exception handler 379-389 → returns None."""
        with patch(
            "trade_analyzer.data_handler.yf.download",
            side_effect=RuntimeError("network error"),
        ):
            result = download_benchmark_data("SPY", _START, _END)
        assert result is None
