"""
tests/test_norgate_sanitize_filename.py

Tests for _sanitize_filename() in scripts/norgate_to_parquet.py.

This function determines how Norgate symbols map to filenames on disk.
The key invariant: dollar-sign ($) is NOT a Windows-illegal character,
so Norgate's native index format ($VIX, $SPX) must pass through unchanged.
This was the root cause of the index export failures fixed in #107 —
symbols were being normalized to I:VIX before export, which became I_VIX.parquet,
making them unreachable by the Norgate API which expects $VIX.
"""

import os
import sys
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from scripts.norgate_to_parquet import _sanitize_filename


class TestSanitizeFilename:

    # --- Dollar prefix ($) must be preserved — this is Norgate's native index format ---

    def test_norgate_vix_dollar_preserved(self):
        """$VIX → $VIX  ($ is not a Windows-illegal char; file will be $VIX.parquet)"""
        assert _sanitize_filename("$VIX") == "$VIX"

    def test_norgate_spx_dollar_preserved(self):
        assert _sanitize_filename("$SPX") == "$SPX"

    def test_norgate_dji_dollar_preserved(self):
        assert _sanitize_filename("$DJI") == "$DJI"

    # --- Colon (:) is illegal on Windows — must become underscore ---

    def test_polygon_ivix_colon_replaced(self):
        """I:VIX → I_VIX  (colon is illegal; Polygon format before our fix wrote I_VIX.parquet)"""
        assert _sanitize_filename("I:VIX") == "I_VIX"

    def test_dollar_i_colon_replaced(self):
        """$I:VIX → $I_VIX  ($ kept, colon replaced)"""
        assert _sanitize_filename("$I:VIX") == "$I_VIX"

    # --- Plain equity tickers pass through unchanged ---

    def test_equity_aapl_unchanged(self):
        assert _sanitize_filename("AAPL") == "AAPL"

    def test_equity_msft_unchanged(self):
        assert _sanitize_filename("MSFT") == "MSFT"

    def test_equity_spy_unchanged(self):
        assert _sanitize_filename("SPY") == "SPY"

    # --- All other illegal characters become underscores ---

    def test_backslash_replaced(self):
        assert _sanitize_filename("A\\B") == "A_B"

    def test_asterisk_replaced(self):
        assert _sanitize_filename("A*B") == "A_B"

    def test_question_mark_replaced(self):
        assert _sanitize_filename("A?B") == "A_B"

    def test_multiple_illegal_chars(self):
        assert _sanitize_filename("A:B/C") == "A_B_C"
