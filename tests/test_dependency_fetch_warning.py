# tests/test_dependency_fetch_warning.py
"""
Tests for main._dependency_warning_for_failed_fetch — the second warning
logged when a failed comparison-ticker fetch backs an active strategy
dependency (e.g. I:VIX -> vix_df). See issue #261: Polygon's I:VIX/I:TNX
only serve data from 2023-02-14 onward, and a failed dependency fetch was
previously indistinguishable in the logs from "the strategy found no
setups" -- it's actually "the strategy never had the data to evaluate one".
"""
import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import main


class TestDependencyWarningForFailedFetch:
    def test_none_when_symbol_is_not_a_dependency(self):
        # QQQ is benchmark-only in the default config -- the plain
        # "Failed to fetch" warning already covers this case.
        deps = {"spy": "SPY", "vix": "I:VIX", "tnx": "I:TNX"}
        assert main._dependency_warning_for_failed_fetch("QQQ", deps) is None

    def test_none_when_dependencies_dict_is_empty(self):
        assert main._dependency_warning_for_failed_fetch("I:VIX", {}) is None

    def test_vix_dependency_names_vix_df_and_the_dependency_key(self):
        deps = {"spy": "SPY", "vix": "I:VIX", "tnx": "I:TNX"}
        msg = main._dependency_warning_for_failed_fetch("I:VIX", deps)
        assert msg is not None
        assert "I:VIX" in msg
        assert "vix_df" in msg
        assert "dependencies=['vix']" in msg

    def test_tnx_dependency_names_tnx_df(self):
        deps = {"spy": "SPY", "vix": "I:VIX", "tnx": "I:TNX"}
        msg = main._dependency_warning_for_failed_fetch("I:TNX", deps)
        assert "tnx_df" in msg
        assert "dependencies=['tnx']" in msg

    def test_spy_dependency_names_spy_df(self):
        deps = {"spy": "SPY", "vix": "I:VIX"}
        msg = main._dependency_warning_for_failed_fetch("SPY", deps)
        assert "spy_df" in msg
        assert "dependencies=['spy']" in msg

    def test_message_explains_the_fail_closed_behavior(self):
        # The whole point of this warning is connecting a failed fetch to
        # "zero trades, no error" -- assert that framing survives, not just
        # the symbol/key names.
        deps = {"vix": "I:VIX"}
        msg = main._dependency_warning_for_failed_fetch("I:VIX", deps)
        assert "None" in msg
        assert "fail CLOSED" in msg
        assert "zero trades" in msg
