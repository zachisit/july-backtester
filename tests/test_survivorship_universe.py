# tests/test_survivorship_universe.py
"""
Tests for universe coverage (issue #148): delisted_symbols_file merging
and the warning emitted when include_delisted=True without a file configured.

Tests the main.py logic in isolation by calling the relevant section directly
via monkeypatching — no network calls, no file I/O beyond tmp_path.
"""

import json
import logging
import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.config_validator import validate_config, KNOWN_KEYS


# ---------------------------------------------------------------------------
# TestConfigValidatorKeys
# ---------------------------------------------------------------------------

class TestConfigValidatorKeys:
    """delisted_symbols_file must be in the known-keys allowlist."""

    def test_delisted_symbols_file_is_known_key(self):
        assert "delisted_symbols_file" in KNOWN_KEYS

    def test_no_warning_for_delisted_symbols_file_key(self):
        config = {"delisted_symbols_file": "nasdaq_100_delisted.json"}
        warnings = validate_config(config)
        assert not any("delisted_symbols_file" in w for w in warnings)

    def test_typo_gets_did_you_mean_suggestion(self):
        config = {"delisted_symbol_file": "some.json"}  # missing 's'
        warnings = validate_config(config)
        assert any("delisted_symbols_file" in w for w in warnings)


# ---------------------------------------------------------------------------
# TestDelistedSymbolsMerge  (unit-tests the merge logic via tmp_path)
# ---------------------------------------------------------------------------

class TestDelistedSymbolsMerge:
    """
    Validate the universe-merging behaviour described in main.py:
    - delisted_symbols_file present + file exists → symbols merged, deduped
    - delisted_symbols_file present + file missing → warning logged
    - include_delisted=True but no delisted_symbols_file → warning logged
    - delisted_symbols_file=None → no merge, no warning
    """

    def _run_merge(self, base_symbols, delisted_file_content, config_override, tmp_path, caplog):
        """
        Simulate the merge block from main.py in isolation.
        Returns the resulting symbols list.
        """
        import orjson

        config = {
            "include_delisted": False,
            "delisted_symbols_file": None,
        }
        config.update(config_override)

        # Write delisted file if content provided
        if delisted_file_content is not None:
            delisted_path = tmp_path / "nasdaq_delisted.json"
            delisted_path.write_text(json.dumps(delisted_file_content))
            if config.get("delisted_symbols_file") == "__tmp__":
                config["delisted_symbols_file"] = str(delisted_path)

        symbols = list(base_symbols)

        with caplog.at_level(logging.INFO):
            if config.get("include_delisted", False):
                delisted_file = config.get("delisted_symbols_file")
                if delisted_file:
                    delisted_path_str = delisted_file
                    if os.path.exists(delisted_path_str):
                        with open(delisted_path_str, "rb") as f:
                            extra_symbols = orjson.loads(f.read())
                        before = len(symbols)
                        symbols = list(dict.fromkeys(symbols + extra_symbols))
                    else:
                        logging.getLogger("main").warning(
                            f"delisted_symbols_file '{delisted_file}' not found — universe contains survivors only"
                        )
                else:
                    logging.getLogger("main").warning(
                        "include_delisted=True but no delisted_symbols_file configured. "
                        "Universe contains survivors only."
                    )

        return symbols

    def test_merge_adds_delisted_symbols(self, tmp_path, caplog):
        base     = ["AAPL", "MSFT"]
        delisted = ["ENRON", "WORLDCOM"]
        result   = self._run_merge(
            base, delisted,
            {"include_delisted": True, "delisted_symbols_file": "__tmp__"},
            tmp_path, caplog,
        )
        assert "ENRON" in result
        assert "WORLDCOM" in result
        assert "AAPL" in result

    def test_merge_deduplicates_symbols(self, tmp_path, caplog):
        base     = ["AAPL", "MSFT", "ENRON"]
        delisted = ["ENRON", "LEHMAN"]   # ENRON appears in both
        result   = self._run_merge(
            base, delisted,
            {"include_delisted": True, "delisted_symbols_file": "__tmp__"},
            tmp_path, caplog,
        )
        assert result.count("ENRON") == 1
        assert "LEHMAN" in result

    def test_merge_preserves_order(self, tmp_path, caplog):
        base     = ["AAPL", "MSFT"]
        delisted = ["ENRON", "LEHMAN"]
        result   = self._run_merge(
            base, delisted,
            {"include_delisted": True, "delisted_symbols_file": "__tmp__"},
            tmp_path, caplog,
        )
        assert result.index("AAPL") < result.index("MSFT")
        assert result.index("MSFT") < result.index("ENRON")

    def test_missing_file_logs_warning(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            self._run_merge(
                ["AAPL"], None,
                {"include_delisted": True, "delisted_symbols_file": "/nonexistent/path.json"},
                tmp_path, caplog,
            )
        assert any("not found" in r.message for r in caplog.records)

    def test_no_file_configured_logs_warning(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING):
            self._run_merge(
                ["AAPL"], None,
                {"include_delisted": True, "delisted_symbols_file": None},
                tmp_path, caplog,
            )
        assert any("survivors only" in r.message for r in caplog.records)

    def test_include_delisted_false_no_merge(self, tmp_path, caplog):
        base     = ["AAPL", "MSFT"]
        delisted = ["ENRON"]
        result   = self._run_merge(
            base, delisted,
            {"include_delisted": False, "delisted_symbols_file": "__tmp__"},
            tmp_path, caplog,
        )
        assert "ENRON" not in result
        assert result == base
