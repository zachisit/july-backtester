"""Tests for asset-class-aware smoothness verdict profiles.

Covers the pure profile logic in ``helpers/smoothness_profiles.py`` and its
integration with ``helpers/llm_verdict.compute_smoothness``:

* the ``equity`` profile is byte-identical to the legacy hard-coded thresholds,
* a looser profile can only *reduce* the failure count for the same curve,
* profile selection resolves from an explicit config key or (under ``auto``)
  from the instrument asset class,
* the MC "DD Understated" caveat fires only for a non-equity profile scored
  under i.i.d. resampling.

No I/O, no network, deterministic.
"""
import numpy as np
import pandas as pd
import pytest

from helpers.smoothness_profiles import (
    EQUITY,
    CONCENTRATED_FUTURES,
    DEFAULT_PROFILE_NAME,
    SMOOTHNESS_PROFILES,
    get_thresholds,
    resolve_profile_name,
    mc_sampling_caveat,
    resolve_mc_sampling,
)
from helpers.llm_verdict import compute_smoothness


def _curve(seed, months=36, vol=0.08, drift=0.01):
    """Deterministic monthly equity Series (month-end index)."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, months)
    eq = 100.0 * np.cumprod(1.0 + rets)
    idx = pd.date_range("2015-01-31", periods=months, freq="ME")
    return pd.Series(eq, index=idx)


class TestGetThresholds:
    def test_none_returns_equity_defaults(self):
        assert get_thresholds(None) == SMOOTHNESS_PROFILES[EQUITY]

    def test_equity_defaults_match_legacy_constants(self):
        # These are the exact constants the verdict has always used.
        assert SMOOTHNESS_PROFILES[EQUITY] == {
            "r2_min": 0.90,
            "positive_months_min": 60.0,
            "longest_flat_max": 12,
            "upthrust_max": 2,
            "worst_month_min": -10.0,
        }

    def test_named_profile(self):
        assert get_thresholds(CONCENTRATED_FUTURES) == SMOOTHNESS_PROFILES[CONCENTRATED_FUTURES]

    def test_unknown_name_falls_back_to_equity(self, capsys):
        th = get_thresholds("does_not_exist")
        assert th == SMOOTHNESS_PROFILES[EQUITY]
        assert "Unknown smoothness profile" in capsys.readouterr().out

    def test_dict_override_merges_over_equity(self):
        th = get_thresholds({"worst_month_min": -25.0})
        assert th["worst_month_min"] == -25.0
        # Untouched keys keep the equity defaults.
        assert th["r2_min"] == 0.90
        assert th["upthrust_max"] == 2

    def test_returned_dict_is_a_copy(self):
        th = get_thresholds(EQUITY)
        th["r2_min"] = 0.0
        assert SMOOTHNESS_PROFILES[EQUITY]["r2_min"] == 0.90

    def test_concentrated_is_looser_on_every_axis(self):
        eq = SMOOTHNESS_PROFILES[EQUITY]
        cf = SMOOTHNESS_PROFILES[CONCENTRATED_FUTURES]
        assert cf["r2_min"] <= eq["r2_min"]
        assert cf["positive_months_min"] <= eq["positive_months_min"]
        assert cf["longest_flat_max"] >= eq["longest_flat_max"]
        assert cf["upthrust_max"] >= eq["upthrust_max"]
        assert cf["worst_month_min"] <= eq["worst_month_min"]


class TestResolveProfileName:
    def test_default_is_equity(self):
        assert DEFAULT_PROFILE_NAME == EQUITY

    def test_explicit_config_override_wins(self):
        cfg = {"smoothness_profile": "equity",
               "instruments": {"overrides": {"ESZ5": {"asset_class": "future"}}}}
        # Even with a futures symbol, the explicit override forces equity.
        assert resolve_profile_name(["ESZ5"], cfg) == "equity"

    def test_auto_futures_symbols_map_to_concentrated(self):
        cfg = {"smoothness_profile": "auto",
               "instruments": {"overrides": {"ESZ5": {"asset_class": "future"}}}}
        assert resolve_profile_name(["ESZ5"], cfg) == CONCENTRATED_FUTURES

    def test_auto_equity_symbols_map_to_equity(self):
        cfg = {"smoothness_profile": "auto", "instruments": {}}
        assert resolve_profile_name(["AAPL", "MSFT"], cfg) == EQUITY

    def test_auto_mixed_is_not_concentrated(self):
        cfg = {"smoothness_profile": "auto",
               "instruments": {"overrides": {"ESZ5": {"asset_class": "future"}}}}
        # Any equity name means "not all futures" -> equity baseline.
        assert resolve_profile_name(["ESZ5", "AAPL"], cfg) == EQUITY

    def test_empty_symbols_default_to_equity(self):
        assert resolve_profile_name([], {"smoothness_profile": "auto"}) == EQUITY
        assert resolve_profile_name(None, {"smoothness_profile": "auto"}) == EQUITY

    def test_missing_config_key_defaults_to_auto_equity(self):
        assert resolve_profile_name(["AAPL"], {}) == EQUITY

    def test_asset_class_profile_table_is_load_bearing(self, monkeypatch):
        # resolve_profile_name must consult _ASSET_CLASS_PROFILE, not hardcode
        # "future". Register a synthetic class and confirm it routes through.
        import helpers.smoothness_profiles as sp
        monkeypatch.setitem(sp._ASSET_CLASS_PROFILE, "crypto", CONCENTRATED_FUTURES)
        cfg = {"smoothness_profile": "auto",
               "instruments": {"overrides": {"BTCUSD": {"asset_class": "crypto"}}}}
        assert sp.resolve_profile_name(["BTCUSD"], cfg) == CONCENTRATED_FUTURES


class TestComputeSmoothnessProfileParam:
    def test_none_default_is_byte_identical_to_equity(self):
        for seed in range(6):
            c = _curve(seed)
            a = compute_smoothness(c)
            b = compute_smoothness(c, EQUITY)
            assert a["smooth_verdict"] == b["smooth_verdict"]
            assert a["smooth_notes"] == b["smooth_notes"]

    def test_profile_name_echoed_in_result(self):
        c = _curve(1)
        assert compute_smoothness(c, CONCENTRATED_FUTURES)["profile"] == CONCENTRATED_FUTURES
        assert compute_smoothness(c)["profile"] == EQUITY

    def test_looser_profile_never_adds_failures(self):
        for seed in range(12):
            c = _curve(seed, vol=0.10)
            n_eq = len(compute_smoothness(c, EQUITY)["smooth_notes"])
            n_cf = len(compute_smoothness(c, CONCENTRATED_FUTURES)["smooth_notes"])
            assert n_cf <= n_eq

    def test_profile_actually_changes_a_verdict(self):
        # At least one volatile curve is downgraded under equity but not under
        # the concentrated profile — proves the thresholds are wired through.
        changed = False
        for seed in range(30):
            c = _curve(seed, vol=0.12)
            eq = compute_smoothness(c, EQUITY)
            cf = compute_smoothness(c, CONCENTRATED_FUTURES)
            if len(cf["smooth_notes"]) < len(eq["smooth_notes"]):
                changed = True
                break
        assert changed

    def test_dict_override_applied(self):
        # Force everything to pass -> SMOOTH regardless of curve shape.
        c = _curve(3, vol=0.15)
        loose = {
            "r2_min": 0.0, "positive_months_min": 0.0, "longest_flat_max": 10_000,
            "upthrust_max": 10_000, "worst_month_min": -10_000.0,
        }
        assert compute_smoothness(c, loose)["smooth_verdict"] == "SMOOTH"


class TestConfigValidation:
    def test_valid_profile_values_pass(self):
        from helpers.config_validator import validate_config
        for val in ("auto", "equity", "concentrated_futures", "AUTO", "Equity"):
            assert validate_config({"smoothness_profile": val}) == []

    def test_unknown_profile_value_warns(self):
        from helpers.config_validator import validate_config
        warnings = validate_config({"smoothness_profile": "concentraded_futures"})
        assert any("smoothness_profile" in w and "not a known profile" in w for w in warnings)

    def test_dict_profile_not_value_checked(self):
        from helpers.config_validator import validate_config
        # A dict override is a legitimate value and must not trip the enum check.
        assert validate_config({"smoothness_profile": {"r2_min": 0.5}}) == []

    def test_missing_profile_key_is_silent(self):
        from helpers.config_validator import validate_config
        assert validate_config({}) == []


class TestMcSamplingCaveat:
    def test_fires_for_concentrated_iid_dd_understated(self):
        note = mc_sampling_caveat("DD Understated", CONCENTRATED_FUTURES, "iid")
        assert note is not None and "block" in note

    def test_none_for_equity_profile(self):
        assert mc_sampling_caveat("DD Understated", EQUITY, "iid") is None

    def test_none_when_already_block_sampling(self):
        assert mc_sampling_caveat("DD Understated", CONCENTRATED_FUTURES, "block") is None

    def test_none_without_dd_understated(self):
        assert mc_sampling_caveat("Robust", CONCENTRATED_FUTURES, "iid") is None
        assert mc_sampling_caveat(None, CONCENTRATED_FUTURES, "iid") is None

    def test_fires_within_multi_verdict_string(self):
        note = mc_sampling_caveat("Perf. Outlier, DD Understated", CONCENTRATED_FUTURES, "iid")
        assert note is not None


class TestResolveMcSampling:
    def test_auto_concentrated_futures_uses_block(self):
        assert resolve_mc_sampling("auto", CONCENTRATED_FUTURES) == "block"

    def test_auto_equity_uses_iid(self):
        assert resolve_mc_sampling("auto", EQUITY) == "iid"

    def test_auto_is_case_insensitive(self):
        assert resolve_mc_sampling("AUTO", CONCENTRATED_FUTURES) == "block"
        assert resolve_mc_sampling("Auto", EQUITY) == "iid"

    def test_explicit_values_pass_through_unchanged(self):
        # Explicit settings are never overridden — the default "iid" run stays byte-identical.
        assert resolve_mc_sampling("iid", CONCENTRATED_FUTURES) == "iid"
        assert resolve_mc_sampling("block", EQUITY) == "block"
        assert resolve_mc_sampling("iid", EQUITY) == "iid"

    def test_none_defaults_to_iid_passthrough(self):
        assert resolve_mc_sampling(None, CONCENTRATED_FUTURES) == "iid"
