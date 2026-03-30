# tests/test_config_validator.py
"""
Unit tests for helpers/config_validator.py — Config Key Validation.

Covers:
  validate_config — unknown key detection, fuzzy matching, clean config passes
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.config_validator import validate_config, KNOWN_KEYS


# ---------------------------------------------------------------------------
# TestValidateConfig
# ---------------------------------------------------------------------------

class TestValidateConfig:

    def test_valid_config_returns_empty(self):
        """A config with only known keys should produce zero warnings."""
        config = {"data_provider": "yahoo", "start_date": "2020-01-01", "initial_capital": 100000}
        warnings = validate_config(config)
        assert warnings == []

    def test_unknown_key_produces_warning(self):
        """An unrecognised key should produce exactly one warning."""
        config = {"data_provider": "yahoo", "fake_key_xyz": True}
        warnings = validate_config(config)
        assert len(warnings) == 1
        assert "fake_key_xyz" in warnings[0]

    def test_typo_suggests_correction(self):
        """A typo'd key should trigger a 'did you mean?' suggestion."""
        # "sensitvity_sweep_enabled" is a plausible typo for "sensitivity_sweep_enabled"
        config = {"sensitvity_sweep_enabled": True}
        warnings = validate_config(config)
        assert len(warnings) == 1
        assert "did you mean" in warnings[0].lower()
        assert "sensitivity_sweep_enabled" in warnings[0]

    def test_multiple_unknown_keys(self):
        """Multiple unknown keys should each produce a separate warning."""
        config = {"bad_key_1": 1, "bad_key_2": 2, "data_provider": "yahoo"}
        warnings = validate_config(config)
        assert len(warnings) == 2

    def test_empty_config_returns_empty(self):
        """An empty config dict should produce zero warnings."""
        warnings = validate_config({})
        assert warnings == []

    def test_all_known_keys_pass(self):
        """A config containing every known key should produce zero warnings."""
        config = {key: None for key in KNOWN_KEYS}
        warnings = validate_config(config)
        assert warnings == []

    def test_close_typo_slippage(self):
        """'slippage_percent' should suggest 'slippage_pct'."""
        config = {"slippage_percent": 0.001}
        warnings = validate_config(config)
        assert len(warnings) == 1
        assert "slippage_pct" in warnings[0]

    def test_close_typo_commission(self):
        """'comission_per_share' should suggest 'commission_per_share'."""
        config = {"comission_per_share": 0.002}
        warnings = validate_config(config)
        assert len(warnings) == 1
        assert "commission_per_share" in warnings[0]

    def test_no_suggestion_for_completely_random_key(self):
        """A completely random key should warn but not suggest anything."""
        config = {"zzzzz_not_a_key_12345": True}
        warnings = validate_config(config)
        assert len(warnings) == 1
        assert "did you mean" not in warnings[0].lower()

    def test_real_config_passes(self):
        """The actual CONFIG from config.py should produce zero warnings."""
        from config import CONFIG
        warnings = validate_config(CONFIG)
        assert warnings == [], f"Real CONFIG has unknown keys: {warnings}"

    def test_known_keys_includes_all_config_sections(self):
        """KNOWN_KEYS should contain keys from every section of config.py."""
        # Spot-check one key from each major section
        expected_samples = [
            "data_provider", "start_date", "timeframe", "price_adjustment",
            "save_individual_trades", "mc_score_min_to_show_in_summary",
            "portfolios", "allocation_per_trade", "stop_loss_configs",
            "min_trades_for_mc", "wfa_split_ratio", "slippage_pct",
            "noise_injection_pct", "strategies", "sensitivity_sweep_enabled",
            "rolling_sharpe_window", "htb_rate_annual", "mc_sampling",
            "volume_impact_coeff", "export_ml_features",
        ]
        for key in expected_samples:
            assert key in KNOWN_KEYS, f"KNOWN_KEYS missing '{key}'"
