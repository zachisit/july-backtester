# tests/test_comparison_tickers.py
"""
Unit tests for helpers/comparison_tickers.py — comparison ticker config parser.

Tests cover:
- Valid configs (single benchmark, multiple benchmarks, mixed roles)
- Legacy fallback behavior
- Duplicate symbol handling
- Invalid role values
- Missing required keys
- Empty lists
- Label defaulting
- Output structure validation
"""

import os
import sys
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.comparison_tickers import (
    parse_comparison_tickers,
    get_legacy_comparison_tickers,
)


# ---------------------------------------------------------------------------
# TestGetLegacyComparisonTickers
# ---------------------------------------------------------------------------

class TestGetLegacyComparisonTickers:
    """Test legacy fallback function."""

    def test_returns_list_of_dicts(self):
        """Legacy function returns a list of dicts."""
        result = get_legacy_comparison_tickers()
        assert isinstance(result, list)
        assert all(isinstance(entry, dict) for entry in result)

    def test_contains_spy_qqq_vix_tnx(self):
        """Legacy defaults include SPY, QQQ, VIX, TNX."""
        result = get_legacy_comparison_tickers()
        symbols = [entry["symbol"] for entry in result]
        assert "SPY" in symbols
        assert "QQQ" in symbols
        assert "I:VIX" in symbols
        assert "I:TNX" in symbols

    def test_spy_has_role_both(self):
        """SPY is both a benchmark and dependency in legacy mode."""
        result = get_legacy_comparison_tickers()
        spy = next(e for e in result if e["symbol"] == "SPY")
        assert spy["role"] == "both"

    def test_qqq_has_role_benchmark(self):
        """QQQ is benchmark-only in legacy mode."""
        result = get_legacy_comparison_tickers()
        qqq = next(e for e in result if e["symbol"] == "QQQ")
        assert qqq["role"] == "benchmark"

    def test_vix_has_role_dependency(self):
        """VIX is dependency-only in legacy mode."""
        result = get_legacy_comparison_tickers()
        vix = next(e for e in result if e["symbol"] == "I:VIX")
        assert vix["role"] == "dependency"


# ---------------------------------------------------------------------------
# TestParseComparisonTickers — Valid Configs
# ---------------------------------------------------------------------------

class TestParseValidConfigs:
    """Test parsing of valid comparison_tickers configs."""

    def test_single_benchmark_spy(self):
        """Single benchmark (SPY only)."""
        config = {
            "comparison_tickers": [
                {"symbol": "SPY", "role": "benchmark", "label": "SPY"},
            ]
        }
        result = parse_comparison_tickers(config)

        assert len(result["benchmarks"]) == 1
        assert result["benchmarks"][0] == {"symbol": "SPY", "label": "SPY"}
        assert result["dependencies"] == {}
        assert result["all_symbols"] == ["SPY"]

    def test_three_benchmarks(self):
        """Three benchmarks (SPY, QQQ, XLF)."""
        config = {
            "comparison_tickers": [
                {"symbol": "SPY", "role": "benchmark", "label": "SPY"},
                {"symbol": "QQQ", "role": "benchmark", "label": "QQQ"},
                {"symbol": "XLF", "role": "benchmark", "label": "Financials"},
            ]
        }
        result = parse_comparison_tickers(config)

        assert len(result["benchmarks"]) == 3
        assert result["benchmarks"][2]["label"] == "Financials"
        assert result["all_symbols"] == ["SPY", "QQQ", "XLF"]

    def test_single_dependency_vix(self):
        """Single dependency (VIX only)."""
        config = {
            "comparison_tickers": [
                {"symbol": "I:VIX", "role": "dependency"},
            ]
        }
        result = parse_comparison_tickers(config)

        assert result["benchmarks"] == []
        assert "vix" in result["dependencies"]
        assert result["dependencies"]["vix"] == "I:VIX"
        assert result["all_symbols"] == ["I:VIX"]

    def test_mixed_roles_spy_both_qqq_benchmark_vix_dependency(self):
        """Mixed roles: SPY (both), QQQ (benchmark), VIX (dependency)."""
        config = {
            "comparison_tickers": [
                {"symbol": "SPY", "role": "both", "label": "SPY"},
                {"symbol": "QQQ", "role": "benchmark", "label": "QQQ"},
                {"symbol": "I:VIX", "role": "dependency"},
            ]
        }
        result = parse_comparison_tickers(config)

        # SPY appears in both benchmarks and dependencies
        assert len(result["benchmarks"]) == 2
        assert {"symbol": "SPY", "label": "SPY"} in result["benchmarks"]
        assert {"symbol": "QQQ", "label": "QQQ"} in result["benchmarks"]

        assert "spy" in result["dependencies"]
        assert "vix" in result["dependencies"]
        assert result["dependencies"]["spy"] == "SPY"
        assert result["dependencies"]["vix"] == "I:VIX"

    def test_label_defaults_to_symbol(self):
        """Label defaults to symbol when not provided."""
        config = {
            "comparison_tickers": [
                {"symbol": "SPY", "role": "benchmark"},  # No label
            ]
        }
        result = parse_comparison_tickers(config)

        assert result["benchmarks"][0]["label"] == "SPY"

    def test_label_defaults_strips_i_prefix(self):
        """Label for I:VIX defaults to 'VIX' (strips I: prefix)."""
        config = {
            "comparison_tickers": [
                {"symbol": "I:VIX", "role": "benchmark"},  # No label
            ]
        }
        result = parse_comparison_tickers(config)

        assert result["benchmarks"][0]["label"] == "VIX"

    def test_label_defaults_strips_caret_prefix(self):
        """Label for ^VIX defaults to 'VIX' (strips ^ prefix)."""
        config = {
            "comparison_tickers": [
                {"symbol": "^VIX", "role": "benchmark"},  # No label
            ]
        }
        result = parse_comparison_tickers(config)

        assert result["benchmarks"][0]["label"] == "VIX"

    def test_dependency_key_lowercase(self):
        """Dependency keys are lowercase."""
        config = {
            "comparison_tickers": [
                {"symbol": "SPY", "role": "dependency"},
                {"symbol": "I:VIX", "role": "dependency"},
            ]
        }
        result = parse_comparison_tickers(config)

        assert "spy" in result["dependencies"]
        assert "vix" in result["dependencies"]
        assert "SPY" not in result["dependencies"]  # Not uppercase


# ---------------------------------------------------------------------------
# TestParseComparisonTickers — Fallback & Edge Cases
# ---------------------------------------------------------------------------

class TestParseFallbackAndEdgeCases:
    """Test legacy fallback and edge case handling."""

    def test_missing_key_uses_legacy(self):
        """Missing comparison_tickers key triggers legacy fallback."""
        config = {}  # No comparison_tickers key
        result = parse_comparison_tickers(config)

        # Should have legacy symbols (SPY, QQQ, VIX, TNX)
        assert len(result["all_symbols"]) == 4
        assert "SPY" in result["all_symbols"]
        assert "QQQ" in result["all_symbols"]

    def test_empty_list_uses_legacy(self):
        """Empty comparison_tickers list triggers legacy fallback."""
        config = {"comparison_tickers": []}
        result = parse_comparison_tickers(config)

        assert len(result["all_symbols"]) == 4  # Legacy defaults

    def test_none_value_uses_legacy(self):
        """comparison_tickers=None triggers legacy fallback."""
        config = {"comparison_tickers": None}
        result = parse_comparison_tickers(config)

        assert len(result["all_symbols"]) == 4  # Legacy defaults

    def test_duplicate_symbol_keeps_first(self):
        """Duplicate symbols are skipped (first occurrence kept)."""
        config = {
            "comparison_tickers": [
                {"symbol": "SPY", "role": "benchmark", "label": "SPY"},
                {"symbol": "SPY", "role": "dependency", "label": "Duplicate"},  # Duplicate
            ]
        }
        result = parse_comparison_tickers(config)

        # Only one SPY in all_symbols
        assert result["all_symbols"] == ["SPY"]
        # First occurrence (benchmark) is kept
        assert len(result["benchmarks"]) == 1
        assert result["dependencies"] == {}  # Second (dependency) was skipped

    def test_invalid_role_skipped(self):
        """Entry with invalid role is skipped."""
        config = {
            "comparison_tickers": [
                {"symbol": "SPY", "role": "invalid_role"},
                {"symbol": "QQQ", "role": "benchmark"},
            ]
        }
        result = parse_comparison_tickers(config)

        # SPY skipped, QQQ kept
        assert result["all_symbols"] == ["QQQ"]
        assert len(result["benchmarks"]) == 1

    def test_missing_symbol_key_skipped(self):
        """Entry missing 'symbol' key is skipped."""
        config = {
            "comparison_tickers": [
                {"role": "benchmark", "label": "NoSymbol"},  # Missing symbol
                {"symbol": "QQQ", "role": "benchmark"},
            ]
        }
        result = parse_comparison_tickers(config)

        assert result["all_symbols"] == ["QQQ"]

    def test_missing_role_key_skipped(self):
        """Entry missing 'role' key is skipped."""
        config = {
            "comparison_tickers": [
                {"symbol": "SPY", "label": "NoRole"},  # Missing role
                {"symbol": "QQQ", "role": "benchmark"},
            ]
        }
        result = parse_comparison_tickers(config)

        assert result["all_symbols"] == ["QQQ"]

    def test_non_dict_entry_skipped(self):
        """Non-dict entry (e.g., string) is skipped."""
        config = {
            "comparison_tickers": [
                "SPY",  # Invalid: should be a dict
                {"symbol": "QQQ", "role": "benchmark"},
            ]
        }
        result = parse_comparison_tickers(config)

        assert result["all_symbols"] == ["QQQ"]


# ---------------------------------------------------------------------------
# TestParseOutputStructure
# ---------------------------------------------------------------------------

class TestParseOutputStructure:
    """Test that parse_comparison_tickers returns the expected structure."""

    def test_returns_dict_with_required_keys(self):
        """Output dict has all required keys."""
        config = {
            "comparison_tickers": [
                {"symbol": "SPY", "role": "benchmark"},
            ]
        }
        result = parse_comparison_tickers(config)

        assert "benchmarks" in result
        assert "dependencies" in result
        assert "all_symbols" in result
        assert "comparison_tickers" in result

    def test_benchmarks_is_list(self):
        """benchmarks key is a list."""
        config = {"comparison_tickers": [{"symbol": "SPY", "role": "benchmark"}]}
        result = parse_comparison_tickers(config)

        assert isinstance(result["benchmarks"], list)

    def test_dependencies_is_dict(self):
        """dependencies key is a dict."""
        config = {"comparison_tickers": [{"symbol": "I:VIX", "role": "dependency"}]}
        result = parse_comparison_tickers(config)

        assert isinstance(result["dependencies"], dict)

    def test_all_symbols_is_list(self):
        """all_symbols key is a list."""
        config = {"comparison_tickers": [{"symbol": "SPY", "role": "benchmark"}]}
        result = parse_comparison_tickers(config)

        assert isinstance(result["all_symbols"], list)

    def test_all_symbols_unique(self):
        """all_symbols contains unique values (no duplicates)."""
        config = {
            "comparison_tickers": [
                {"symbol": "SPY", "role": "both"},  # SPY appears once
            ]
        }
        result = parse_comparison_tickers(config)

        # Even though SPY is in both benchmarks and dependencies, it appears once in all_symbols
        assert result["all_symbols"] == ["SPY"]
