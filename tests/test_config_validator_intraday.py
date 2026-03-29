# tests/test_config_validator_intraday.py
"""
Unit tests for intraday config validation in helpers/config_validator.py.

Covers:
  validate_intraday_config  — warns about intraday-specific issues
"""

import os
import sys
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.config_validator import validate_intraday_config


# ---------------------------------------------------------------------------
# TestValidateIntradayConfig
# ---------------------------------------------------------------------------

class TestValidateIntradayConfig:
    """Test validate_intraday_config() for intraday timeframe warnings."""

    def test_daily_timeframe_no_warnings(self):
        """Daily timeframe should produce no warnings."""
        config = {"timeframe": "D"}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 0

    def test_daily_with_wfa_no_warnings(self):
        """Daily with WFA enabled should produce no warnings."""
        config = {"timeframe": "D", "wfa_split_ratio": 0.80}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 0

    def test_hourly_1h_info_message(self):
        """Hourly (1H) should produce info message about intraday support."""
        config = {"timeframe": "H", "timeframe_multiplier": 1}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 1
        assert "INFO: Intraday backtesting detected" in warnings[0]
        assert "timeframe=H" in warnings[0]
        assert "automatically adjusted" in warnings[0]

    def test_hourly_4h_info_message_shows_multiplier(self):
        """4-hour bars should show '4h' in the info message."""
        config = {"timeframe": "H", "timeframe_multiplier": 4}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 1
        assert "timeframe=4h" in warnings[0]

    def test_minute_5m_info_message(self):
        """5-minute bars should produce info message."""
        config = {"timeframe": "MIN", "timeframe_multiplier": 5}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 1
        assert "INFO: Intraday backtesting detected" in warnings[0]
        assert "timeframe=5min" in warnings[0]

    def test_minute_1m_shows_min_not_1min(self):
        """1-minute bars should show 'MIN' not '1min' (multiplier==1)."""
        config = {"timeframe": "MIN", "timeframe_multiplier": 1}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 1
        assert "timeframe=MIN" in warnings[0]

    def test_hourly_with_wfa_warns_about_limitations(self):
        """Hourly + WFA should produce both info + WFA warning."""
        config = {"timeframe": "H", "timeframe_multiplier": 1, "wfa_split_ratio": 0.80}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 2
        # First warning: info about intraday
        assert "INFO: Intraday backtesting detected" in warnings[0]
        # Second warning: WFA limitation
        assert "WARNING: Walk-Forward Analysis with intraday data" in warnings[1]
        assert "calendar days, not trading bars" in warnings[1]
        assert "issue #55 Phase 2" in warnings[1]

    def test_minute_with_wfa_warns_about_limitations(self):
        """5-minute + WFA should produce both info + WFA warning."""
        config = {"timeframe": "MIN", "timeframe_multiplier": 5, "wfa_split_ratio": 0.80}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 2
        assert "INFO:" in warnings[0]
        assert "WARNING: Walk-Forward Analysis" in warnings[1]

    def test_intraday_with_wfa_disabled_no_wfa_warning(self):
        """Intraday with WFA disabled (None or 0) should not warn about WFA."""
        config = {"timeframe": "H", "wfa_split_ratio": None}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 1
        assert "INFO:" in warnings[0]
        assert "WFA" not in warnings[0]

    def test_intraday_with_wfa_zero_no_wfa_warning(self):
        """Intraday with wfa_split_ratio=0 should not warn about WFA."""
        config = {"timeframe": "MIN", "timeframe_multiplier": 5, "wfa_split_ratio": 0}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 1
        assert "WARNING" not in warnings[0]

    def test_weekly_timeframe_no_warnings(self):
        """Weekly timeframe is not intraday, should produce no warnings."""
        config = {"timeframe": "W"}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 0

    def test_monthly_timeframe_no_warnings(self):
        """Monthly timeframe is not intraday, should produce no warnings."""
        config = {"timeframe": "M"}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 0

    def test_lowercase_timeframe_recognized(self):
        """Lowercase 'h' should be recognized as intraday."""
        config = {"timeframe": "h", "timeframe_multiplier": 1}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 1
        assert "INFO: Intraday backtesting detected" in warnings[0]

    def test_missing_timeframe_defaults_to_daily_no_warnings(self):
        """Missing timeframe should default to daily (no warnings)."""
        config = {}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 0

    def test_missing_multiplier_defaults_to_one(self):
        """Missing timeframe_multiplier should default to 1 (shows 'H' not '1h')."""
        config = {"timeframe": "H"}
        warnings = validate_intraday_config(config)
        assert len(warnings) == 1
        assert "timeframe=H" in warnings[0]
