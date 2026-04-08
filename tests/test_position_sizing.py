"""tests/test_position_sizing.py

Tests for position sizing algorithms (helpers/position_sizing.py).
"""

import pytest
import pandas as pd
import numpy as np
from helpers.position_sizing import (
    calculate_position_size,
    check_portfolio_heat,
    _fixed_allocation,
    _kelly_criterion,
    _volatility_parity,
    _risk_parity,
)


# ---------------------------------------------------------------------------
# Test calculate_position_size (main entry point)
# ---------------------------------------------------------------------------

class TestCalculatePositionSize:
    """Test the main calculate_position_size function."""

    def test_unknown_method_falls_back_to_fixed(self):
        """Unknown method logs warning and falls back to fixed allocation."""
        dates = pd.date_range("2020-01-01", periods=10, freq="D")
        df = pd.DataFrame({"Close": range(100, 110), "ATR_14": [2.0] * 10}, index=dates)
        config = {"allocation_per_trade": 0.10}

        shares = calculate_position_size("unknown_method", 100000, 50.0, df, config)

        # Should fall back to fixed: (100000 * 0.10) / 50 = 200
        assert shares == pytest.approx(200.0)

    def test_routes_to_correct_method(self):
        """Each method routes to the correct implementation."""
        dates = pd.date_range("2020-01-01", periods=10, freq="D")
        df = pd.DataFrame({"Close": range(100, 110), "ATR_14": [2.0] * 10}, index=dates)
        config = {"allocation_per_trade": 0.10, "target_risk_per_trade": 0.02, "kelly_fraction": 0.25}

        # Fixed
        shares_fixed = calculate_position_size("fixed", 100000, 50.0, df, config)
        assert shares_fixed == pytest.approx(200.0)

        # Vol parity
        shares_vol = calculate_position_size("vol_parity", 100000, 50.0, df, config)
        assert shares_vol > 0

        # Risk parity
        shares_risk = calculate_position_size("risk_parity", 100000, 50.0, df, config, stop_distance_pct=0.05)
        assert shares_risk > 0

        # Kelly (will fall back to fixed without historical stats)
        shares_kelly = calculate_position_size("kelly", 100000, 50.0, df, config)
        assert shares_kelly > 0


# ---------------------------------------------------------------------------
# Test _fixed_allocation
# ---------------------------------------------------------------------------

class TestFixedAllocation:
    """Test fixed percentage allocation."""

    def test_calculates_correct_shares(self):
        """Fixed allocation: shares = (equity * pct) / price."""
        config = {"allocation_per_trade": 0.10}
        shares = _fixed_allocation(100000, 50.0, config)
        assert shares == pytest.approx(200.0)  # (100000 * 0.10) / 50

    def test_different_allocation_percentages(self):
        """Different allocation percentages produce correct results."""
        config_5pct = {"allocation_per_trade": 0.05}
        config_20pct = {"allocation_per_trade": 0.20}

        shares_5 = _fixed_allocation(100000, 50.0, config_5pct)
        shares_20 = _fixed_allocation(100000, 50.0, config_20pct)

        assert shares_5 == pytest.approx(100.0)
        assert shares_20 == pytest.approx(400.0)

    def test_zero_price_returns_zero(self):
        """Zero price returns zero shares."""
        config = {"allocation_per_trade": 0.10}
        shares = _fixed_allocation(100000, 0.0, config)
        assert shares == 0.0


# ---------------------------------------------------------------------------
# Test _kelly_criterion
# ---------------------------------------------------------------------------

class TestKellyCriterion:
    """Test Kelly Criterion position sizing."""

    def test_positive_edge_returns_positive_shares(self):
        """Kelly with positive edge (55% win rate, 2:1 R:R) returns shares."""
        config = {"kelly_fraction": 1.0}  # Full Kelly for testing
        shares = _kelly_criterion(
            100000, 50.0, config,
            win_rate=0.55, avg_win=0.10, avg_loss=0.05
        )
        assert shares > 0

    def test_negative_edge_returns_zero(self):
        """Kelly with negative edge (40% win rate, 1:1 R:R) returns zero shares."""
        config = {"kelly_fraction": 1.0}
        shares = _kelly_criterion(
            100000, 50.0, config,
            win_rate=0.40, avg_win=0.05, avg_loss=0.05
        )
        assert shares == 0.0  # Negative Kelly clamped to 0

    def test_fractional_kelly_reduces_bet_size(self):
        """Fractional Kelly (25%) is more conservative than full Kelly."""
        full_kelly_config = {"kelly_fraction": 1.0}
        frac_kelly_config = {"kelly_fraction": 0.25}

        shares_full = _kelly_criterion(
            100000, 50.0, full_kelly_config,
            win_rate=0.55, avg_win=0.10, avg_loss=0.05
        )
        shares_frac = _kelly_criterion(
            100000, 50.0, frac_kelly_config,
            win_rate=0.55, avg_win=0.10, avg_loss=0.05
        )

        assert shares_frac < shares_full
        assert shares_frac == pytest.approx(shares_full * 0.25)

    def test_missing_parameters_falls_back_to_fixed(self):
        """Missing win_rate/avg_win/avg_loss falls back to fixed allocation."""
        config = {"allocation_per_trade": 0.10, "kelly_fraction": 0.25}

        # Missing win_rate
        shares = _kelly_criterion(100000, 50.0, config, avg_win=0.10, avg_loss=0.05)
        assert shares == pytest.approx(200.0)  # Fixed fallback

        # Missing avg_win
        shares = _kelly_criterion(100000, 50.0, config, win_rate=0.55, avg_loss=0.05)
        assert shares == pytest.approx(200.0)

    def test_invalid_win_rate_falls_back(self):
        """Invalid win_rate (< 0 or > 1) falls back to fixed."""
        config = {"allocation_per_trade": 0.10, "kelly_fraction": 0.25}

        shares = _kelly_criterion(
            100000, 50.0, config,
            win_rate=1.5, avg_win=0.10, avg_loss=0.05
        )
        assert shares == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Test _volatility_parity
# ---------------------------------------------------------------------------

class TestVolatilityParity:
    """Test volatility parity position sizing."""

    def test_higher_atr_yields_smaller_position(self):
        """Higher volatility (ATR) results in smaller position size."""
        config = {"target_risk_per_trade": 0.02}

        low_vol_df = pd.DataFrame({"ATR_14": [1.0]}, index=[pd.Timestamp("2020-01-01")])
        high_vol_df = pd.DataFrame({"ATR_14": [5.0]}, index=[pd.Timestamp("2020-01-01")])

        shares_low = _volatility_parity(100000, 50.0, low_vol_df, config)
        shares_high = _volatility_parity(100000, 50.0, high_vol_df, config)

        assert shares_low > shares_high

    def test_calculates_correct_shares(self):
        """Vol parity formula: shares = (equity * target_risk) / (price * atr_pct)."""
        config = {"target_risk_per_trade": 0.02}
        df = pd.DataFrame({"ATR_14": [2.0]}, index=[pd.Timestamp("2020-01-01")])

        shares = _volatility_parity(100000, 50.0, df, config)

        # atr_pct = 2.0 / 50.0 = 0.04
        # shares = (100000 * 0.02) / (50.0 * 0.04) = 2000 / 2.0 = 1000
        assert shares == pytest.approx(1000.0)

    def test_missing_atr_falls_back_to_fixed(self):
        """Missing ATR_14 column falls back to fixed allocation."""
        config = {"allocation_per_trade": 0.10, "target_risk_per_trade": 0.02}
        df = pd.DataFrame({"Close": [50.0]}, index=[pd.Timestamp("2020-01-01")])  # No ATR

        shares = _volatility_parity(100000, 50.0, df, config)
        assert shares == pytest.approx(200.0)  # Fixed fallback

    def test_zero_atr_falls_back_to_fixed(self):
        """Zero or NaN ATR falls back to fixed allocation."""
        config = {"allocation_per_trade": 0.10, "target_risk_per_trade": 0.02}
        df = pd.DataFrame({"ATR_14": [0.0]}, index=[pd.Timestamp("2020-01-01")])

        shares = _volatility_parity(100000, 50.0, df, config)
        assert shares == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Test _risk_parity
# ---------------------------------------------------------------------------

class TestRiskParity:
    """Test risk parity position sizing."""

    def test_wider_stop_yields_smaller_position(self):
        """Wider stop distance results in smaller position size."""
        config = {"target_risk_per_trade": 0.02}
        df = pd.DataFrame({"ATR_14": [2.0]}, index=[pd.Timestamp("2020-01-01")])

        shares_tight = _risk_parity(100000, 50.0, df, config, stop_distance_pct=0.02)
        shares_wide = _risk_parity(100000, 50.0, df, config, stop_distance_pct=0.10)

        assert shares_tight > shares_wide

    def test_calculates_correct_shares(self):
        """Risk parity formula: shares = (equity * target_risk) / (price * stop_distance)."""
        config = {"target_risk_per_trade": 0.02}
        df = pd.DataFrame({"ATR_14": [2.0]}, index=[pd.Timestamp("2020-01-01")])

        shares = _risk_parity(100000, 50.0, df, config, stop_distance_pct=0.05)

        # shares = (100000 * 0.02) / (50.0 * 0.05) = 2000 / 2.5 = 800
        assert shares == pytest.approx(800.0)

    def test_fallback_to_atr_stop_when_no_stop_distance(self):
        """When stop_distance_pct not provided, uses 3x ATR as stop."""
        config = {"target_risk_per_trade": 0.02}
        df = pd.DataFrame({"ATR_14": [2.0]}, index=[pd.Timestamp("2020-01-01")])

        shares = _risk_parity(100000, 50.0, df, config)

        # stop_distance_pct = (2.0 * 3.0) / 50.0 = 0.12
        # shares = (100000 * 0.02) / (50.0 * 0.12) = 2000 / 6.0 = 333.33
        assert shares == pytest.approx(333.33, rel=0.01)

    def test_missing_stop_and_atr_falls_back_to_fixed(self):
        """Missing both stop distance and ATR falls back to fixed."""
        config = {"allocation_per_trade": 0.10, "target_risk_per_trade": 0.02}
        df = pd.DataFrame({"Close": [50.0]}, index=[pd.Timestamp("2020-01-01")])  # No ATR

        shares = _risk_parity(100000, 50.0, df, config)
        assert shares == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Test check_portfolio_heat
# ---------------------------------------------------------------------------

class TestPortfolioHeat:
    """Test portfolio heat limit enforcement."""

    def test_allows_trade_when_under_limit(self):
        """Trade is allowed when total heat remains under max_heat."""
        positions = {
            "AAPL": {"risk": 500},
            "MSFT": {"risk": 300},
        }
        # Current heat: (500 + 300) / 100000 = 0.008 (0.8%)
        # New position: 200
        # Total heat: (800 + 200) / 100000 = 0.01 (1.0%)
        # Max heat: 2%
        result = check_portfolio_heat(positions, 200, 100000, 0.02)
        assert result is True

    def test_rejects_trade_when_over_limit(self):
        """Trade is rejected when total heat would exceed max_heat."""
        positions = {
            "AAPL": {"risk": 1500},
            "MSFT": {"risk": 1500},
        }
        # Current heat: 3000 / 100000 = 0.03 (3%)
        # New position: 500
        # Total heat: 3500 / 100000 = 0.035 (3.5%)
        # Max heat: 3%
        result = check_portfolio_heat(positions, 500, 100000, 0.03)
        assert result is False

    def test_empty_positions_allows_first_trade(self):
        """Empty positions dict allows first trade under max_heat."""
        positions = {}
        result = check_portfolio_heat(positions, 1000, 100000, 0.02)  # 1% heat, 2% max
        assert result is True

    def test_zero_equity_returns_true(self):
        """Zero equity: heat defaults to 0.0 (division guarded), so trade is allowed."""
        positions = {}
        result = check_portfolio_heat(positions, 100, 0, 0.10)
        assert result is True

    def test_max_heat_100pct_allows_all(self):
        """max_heat=1.0 (100%) allows all trades."""
        positions = {
            "SYM1": {"risk": 50000},  # 50% of equity
        }
        result = check_portfolio_heat(positions, 40000, 100000, 1.0)  # 90% total heat
        assert result is True

    def test_positions_without_risk_key_treated_as_zero(self):
        """Positions without 'risk' key are treated as 0 risk."""
        positions = {
            "AAPL": {},  # No risk key
            "MSFT": {"risk": 500},
        }
        # Only MSFT contributes to heat
        result = check_portfolio_heat(positions, 1000, 100000, 0.02)  # (500+1000)/100000 = 1.5%
        assert result is True


# ---------------------------------------------------------------------------
# Regression tests for bugs fixed after initial implementation
# ---------------------------------------------------------------------------

class TestLookAheadBiasSlice:
    """vol_parity and risk_parity must not see future ATR values."""

    def test_vol_parity_uses_last_row_of_slice_not_full_history(self):
        """Slicing symbol_data to current date prevents using a future ATR."""
        config = {"target_risk_per_trade": 0.02}
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        # Early ATR is 1.0; last (future) ATR is 100.0
        df = pd.DataFrame({"ATR_14": [1.0, 1.0, 1.0, 1.0, 100.0]}, index=dates)

        # Slice to the 4th bar (simulating current date = dates[3])
        current_slice = df.loc[: dates[3]]
        shares_correct = _volatility_parity(100000, 50.0, current_slice, config)

        # Using full history (the bug) would read ATR=100 from the last bar
        shares_biased = _volatility_parity(100000, 50.0, df, config)

        # Correct sizing uses ATR=1.0 → much larger position than biased ATR=100.0
        assert shares_correct > shares_biased


class TestKellyRollingStats:
    """Kelly must produce non-fixed sizing once trade history is available."""

    def test_kelly_with_stats_differs_from_fixed(self):
        """Kelly with win_rate/avg_win/avg_loss produces a different size than fixed."""
        config = {"allocation_per_trade": 0.10, "kelly_fraction": 0.25}
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        df = pd.DataFrame({"ATR_14": [2.0] * 5}, index=dates)

        shares_fixed = calculate_position_size("fixed", 100000, 50.0, df, config)
        # win_rate=0.65, R:R=2:1 → full Kelly = 0.475 → fractional = 0.11875 ≠ 0.10 fixed
        shares_kelly = calculate_position_size(
            "kelly", 100000, 50.0, df, config,
            win_rate=0.65, avg_win=0.08, avg_loss=0.04,
        )
        assert shares_kelly != shares_fixed
        assert shares_kelly == pytest.approx(237.5)

    def test_kelly_falls_back_when_fewer_than_10_trades(self):
        """Kelly falls back to fixed when insufficient trade history is passed."""
        config = {"allocation_per_trade": 0.10, "kelly_fraction": 0.25}
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        df = pd.DataFrame({"ATR_14": [2.0] * 5}, index=dates)

        # No kwargs → missing win_rate/avg_win/avg_loss → fallback to fixed
        shares = calculate_position_size("kelly", 100000, 50.0, df, config)
        assert shares == pytest.approx(200.0)


class TestRiskParityStopDistance:
    """risk_parity must use the configured stop distance, not always ATR fallback."""

    def test_percentage_stop_uses_config_value(self):
        """stop_distance_pct derived from percentage stop matches direct call."""
        config = {"target_risk_per_trade": 0.02}
        df = pd.DataFrame({"ATR_14": [2.0]}, index=[pd.Timestamp("2020-01-01")])

        # Direct call with explicit stop distance = 5%
        shares_direct = _risk_parity(100000, 50.0, df, config, stop_distance_pct=0.05)
        # shares = (100000 * 0.02) / (50.0 * 0.05) = 800
        assert shares_direct == pytest.approx(800.0)

    def test_atr_fallback_used_when_no_stop_distance(self):
        """When stop_distance_pct is absent, 3x ATR fallback is used."""
        config = {"target_risk_per_trade": 0.02}
        df = pd.DataFrame({"ATR_14": [2.0]}, index=[pd.Timestamp("2020-01-01")])

        shares_fallback = _risk_parity(100000, 50.0, df, config)
        # stop_distance = (2.0 * 3.0) / 50.0 = 0.12
        # shares = (100000 * 0.02) / (50.0 * 0.12) ≈ 333.33
        assert shares_fallback == pytest.approx(333.33, rel=0.01)

        # Explicit stop of 5% must produce a different (larger) result than 12% fallback
        shares_explicit = _risk_parity(100000, 50.0, df, config, stop_distance_pct=0.05)
        assert shares_explicit > shares_fallback
