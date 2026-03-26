"""
Tests for run_monte_carlo_simulation in trade_analyzer/calculations.py (lines 372-541).
Focuses on guard clauses, ruin detection, percentage returns mode, and output structure.
Uses small sim counts (10-50) to keep runtime fast.
"""
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from trade_analyzer.calculations import run_monte_carlo_simulation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _profits(values):
    """Wrap a list as a pd.Series of trade profits."""
    return pd.Series(values, dtype=float)


def _run(trade_data, num_simulations=20, num_trades_per_sim=10,
         initial_equity=10_000.0, duration_years=1.0,
         use_percentage_returns=False, drawdown_as_negative=False):
    """Thin wrapper with sensible defaults for fast tests."""
    return run_monte_carlo_simulation(
        trade_data=trade_data,
        num_simulations=num_simulations,
        num_trades_per_sim=num_trades_per_sim,
        initial_equity=initial_equity,
        duration_years=duration_years,
        use_percentage_returns=use_percentage_returns,
        drawdown_as_negative=drawdown_as_negative,
    )


# ---------------------------------------------------------------------------
# Guard clauses — all should return empty dict immediately
# ---------------------------------------------------------------------------

class TestGuardClauses:
    def test_non_series_returns_empty(self):
        result = _run([100, 200, 300])   # list, not Series
        assert result == {}

    def test_empty_series_returns_empty(self):
        result = _run(_profits([]))
        assert result == {}

    def test_num_trades_per_sim_zero_returns_empty(self):
        result = run_monte_carlo_simulation(
            _profits([100, 200]), num_simulations=10, num_trades_per_sim=0,
            initial_equity=10_000.0, duration_years=1.0,
        )
        assert result == {}

    def test_num_simulations_zero_returns_empty(self):
        result = run_monte_carlo_simulation(
            _profits([100, 200]), num_simulations=0, num_trades_per_sim=10,
            initial_equity=10_000.0, duration_years=1.0,
        )
        assert result == {}

    def test_initial_equity_zero_returns_empty(self):
        result = _run(_profits([100, 200]), initial_equity=0.0)
        assert result == {}

    def test_initial_equity_negative_returns_empty(self):
        result = _run(_profits([100, 200]), initial_equity=-1000.0)
        assert result == {}

    def test_all_nan_series_returns_empty(self):
        result = _run(_profits([np.nan, np.nan, np.nan]))
        assert result == {}


# ---------------------------------------------------------------------------
# Output structure — happy path
# ---------------------------------------------------------------------------

class TestOutputStructure:
    @pytest.fixture(scope="class")
    def result(self):
        np.random.seed(42)
        return _run(_profits([100, -50, 200, -30, 150] * 10), num_simulations=20)

    def test_has_simulated_equity_paths(self, result):
        assert "simulated_equity_paths" in result

    def test_simulated_equity_paths_shape(self, result):
        df = result["simulated_equity_paths"]
        # shape: (num_trades_per_sim + 1) rows × num_simulations cols
        assert df.shape == (11, 20)

    def test_has_final_equities(self, result):
        assert "final_equities" in result
        assert len(result["final_equities"]) == 20

    def test_has_max_drawdown_amounts(self, result):
        assert "max_drawdown_amounts" in result
        assert len(result["max_drawdown_amounts"]) == 20

    def test_has_max_drawdown_percentages(self, result):
        assert "max_drawdown_percentages" in result

    def test_has_lowest_equities(self, result):
        assert "lowest_equities" in result

    def test_has_cagrs(self, result):
        assert "cagrs" in result
        assert len(result["cagrs"]) == 20

    def test_has_mc_detailed_percentiles(self, result):
        assert "mc_detailed_percentiles" in result

    def test_has_mc_summary_statistics(self, result):
        assert "mc_summary_statistics" in result

    def test_equity_paths_start_at_initial_equity(self, result):
        df = result["simulated_equity_paths"]
        assert (df.iloc[0] == 10_000.0).all()

    def test_final_equities_match_last_row_of_paths(self, result):
        df = result["simulated_equity_paths"]
        last_row = df.iloc[-1].values
        np.testing.assert_array_almost_equal(
            result["final_equities"].values, last_row
        )

    def test_summary_statistics_keys(self, result):
        expected_metrics = {"Final Equity", "CAGR", "Max Drawdown $",
                            "Max Drawdown %", "Lowest Equity"}
        assert set(result["mc_summary_statistics"].keys()) == expected_metrics

    def test_summary_statistics_inner_keys(self, result):
        inner = result["mc_summary_statistics"]["Final Equity"]
        assert "Average" in inner
        assert "Median" in inner
        assert "5th Percentile" in inner
        assert "95th Percentile" in inner

    def test_detailed_percentiles_keys(self, result):
        expected_metrics = {"Final Equity", "CAGR", "Max Drawdown $",
                            "Max Drawdown %", "Lowest Equity"}
        assert set(result["mc_detailed_percentiles"].keys()) == expected_metrics


# ---------------------------------------------------------------------------
# Ruin detection — equity goes to zero or below
# ---------------------------------------------------------------------------

class TestRuinDetection:
    def test_ruin_path_final_equity_is_zero(self):
        """All-losing trades guarantee ruin; final equity must be 0."""
        np.random.seed(0)
        result = _run(
            _profits([-1000] * 20),    # every trade loses $1000
            num_trades_per_sim=20,
            initial_equity=5_000.0,
        )
        assert result["final_equities"].min() == 0.0

    def test_ruin_path_cagr_is_minus_one(self):
        """Ruined simulations should record CAGR = -1.0 (i.e. -100%)."""
        np.random.seed(0)
        result = _run(
            _profits([-1000] * 20),
            num_trades_per_sim=20,
            initial_equity=5_000.0,
        )
        assert (result["cagrs"] == -1.0).all()

    def test_ruin_equity_path_stays_at_zero_after_ruin(self):
        """After ruin, remaining equity path entries must all be 0."""
        np.random.seed(0)
        result = _run(
            _profits([-1000] * 20),
            num_simulations=5,
            num_trades_per_sim=20,
            initial_equity=5_000.0,
        )
        df = result["simulated_equity_paths"]
        for col in df.columns:
            path = df[col].values
            # Find first zero
            zero_idx = np.argmax(path == 0)
            if path[zero_idx] == 0:
                assert (path[zero_idx:] == 0).all()

    def test_no_ruin_cagr_is_not_minus_one(self):
        """Profitable trades should not result in -1.0 CAGR."""
        np.random.seed(1)
        result = _run(
            _profits([500] * 20),
            num_trades_per_sim=10,
            initial_equity=10_000.0,
        )
        assert not (result["cagrs"] == -1.0).any()


# ---------------------------------------------------------------------------
# Percentage returns mode
# ---------------------------------------------------------------------------

class TestPercentageReturnsMode:
    def test_percentage_mode_equity_grows_multiplicatively(self):
        """10 trades each returning +10% on $10k should give ~$25,937 (1.1^10)."""
        np.random.seed(5)
        result = run_monte_carlo_simulation(
            trade_data=_profits([10.0] * 50),   # 10% per trade
            num_simulations=5,
            num_trades_per_sim=10,
            initial_equity=10_000.0,
            duration_years=1.0,
            use_percentage_returns=True,
        )
        expected = 10_000.0 * (1.10 ** 10)
        # All simulations draw the same value (10.0), so final equity == expected
        np.testing.assert_allclose(
            result["final_equities"].values,
            expected,
            rtol=1e-6,
        )

    def test_percentage_mode_ruin_with_large_losses(self):
        """Trades of -100% each cause immediate ruin."""
        np.random.seed(7)
        result = run_monte_carlo_simulation(
            trade_data=_profits([-100.0] * 20),   # -100% = ruin in one trade
            num_simulations=10,
            num_trades_per_sim=5,
            initial_equity=10_000.0,
            duration_years=1.0,
            use_percentage_returns=True,
        )
        assert result["final_equities"].max() == 0.0

    def test_dollar_mode_vs_percentage_mode_different_results(self):
        """Same numeric values produce different results in $ vs % mode."""
        np.random.seed(9)
        dollar_result = _run(
            _profits([5.0] * 30),
            num_simulations=10,
            num_trades_per_sim=10,
            initial_equity=1_000.0,
            use_percentage_returns=False,
        )
        np.random.seed(9)
        pct_result = _run(
            _profits([5.0] * 30),
            num_simulations=10,
            num_trades_per_sim=10,
            initial_equity=1_000.0,
            use_percentage_returns=True,
        )
        dollar_avg = dollar_result["final_equities"].mean()
        pct_avg = pct_result["final_equities"].mean()
        assert dollar_avg != pytest.approx(pct_avg, rel=0.001)


# ---------------------------------------------------------------------------
# drawdown_as_negative flag
# ---------------------------------------------------------------------------

class TestDrawdownAsNegativeFlag:
    def test_drawdown_as_negative_makes_values_negative(self):
        np.random.seed(3)
        result = _run(
            _profits([100, -200, 100, -200] * 5),
            drawdown_as_negative=True,
        )
        # At least some drawdowns should be negative (losses exist)
        assert (result["max_drawdown_amounts"] <= 0).all()
        assert (result["max_drawdown_percentages"] <= 0).all()

    def test_drawdown_as_positive_makes_values_non_negative(self):
        np.random.seed(3)
        result = _run(
            _profits([100, -200, 100, -200] * 5),
            drawdown_as_negative=False,
        )
        assert (result["max_drawdown_amounts"] >= 0).all()
        assert (result["max_drawdown_percentages"] >= 0).all()


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_single_simulation(self):
        np.random.seed(11)
        result = _run(_profits([100, -50, 200]), num_simulations=1)
        assert result["final_equities"].shape == (1,)
        assert result["simulated_equity_paths"].shape[1] == 1

    def test_single_trade_per_sim(self):
        np.random.seed(13)
        result = _run(_profits([100, -50, 200]), num_simulations=10, num_trades_per_sim=1)
        assert result["simulated_equity_paths"].shape == (2, 10)  # 2 rows: start + 1 trade

    def test_duration_years_zero_cagr_nan_or_handled(self):
        """duration_years=0 may produce NaN CAGR — should not raise."""
        np.random.seed(15)
        result = _run(_profits([100] * 10), duration_years=0.0)
        # Just confirm it runs without error and returns a result
        assert "cagrs" in result

    def test_insufficient_data_for_percentiles_returns_nan(self):
        """Only 1 simulation → too few points for robust percentile calc → NaN."""
        np.random.seed(17)
        result = _run(_profits([100] * 10), num_simulations=1)
        # With only 1 data point, at least some detailed percentiles should be NaN
        fe_percentiles = result["mc_detailed_percentiles"]["Final Equity"]
        assert any(np.isnan(v) for v in fe_percentiles.values())

    def test_column_names_in_equity_paths(self):
        np.random.seed(19)
        result = _run(_profits([50, -25] * 10), num_simulations=5)
        cols = list(result["simulated_equity_paths"].columns)
        assert cols == ["Sim_1", "Sim_2", "Sim_3", "Sim_4", "Sim_5"]
