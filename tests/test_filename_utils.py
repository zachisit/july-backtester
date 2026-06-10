"""tests/test_filename_utils.py

Tests for helpers/filename_utils.sanitize_symbol_for_filename.
Covers: illegal character replacement, Windows reserved device names,
and common ticker symbol patterns.
"""

import pytest
from helpers.filename_utils import sanitize_symbol_for_filename


class TestIllegalChars:
    def test_colon_replaced(self):
        assert sanitize_symbol_for_filename("I:VIX") == "I_VIX"

    def test_dollar_colon_replaced(self):
        assert sanitize_symbol_for_filename("$I:TNX") == "$I_TNX"

    def test_backslash_replaced(self):
        assert sanitize_symbol_for_filename("A\\B") == "A_B"

    def test_forward_slash_replaced(self):
        assert sanitize_symbol_for_filename("A/B") == "A_B"

    def test_asterisk_replaced(self):
        assert sanitize_symbol_for_filename("A*B") == "A_B"

    def test_question_mark_replaced(self):
        assert sanitize_symbol_for_filename("A?B") == "A_B"

    def test_double_quote_replaced(self):
        assert sanitize_symbol_for_filename('A"B') == "A_B"

    def test_angle_brackets_replaced(self):
        assert sanitize_symbol_for_filename("A<B>C") == "A_B_C"

    def test_pipe_replaced(self):
        assert sanitize_symbol_for_filename("A|B") == "A_B"

    def test_multiple_illegal_chars(self):
        assert sanitize_symbol_for_filename("A:B/C") == "A_B_C"


class TestLegalCharsPreserved:
    def test_plain_ticker_unchanged(self):
        assert sanitize_symbol_for_filename("AAPL") == "AAPL"

    def test_dollar_sign_preserved(self):
        assert sanitize_symbol_for_filename("$VIX") == "$VIX"

    def test_dollar_index_prefix_preserved(self):
        assert sanitize_symbol_for_filename("$I:VIX") == "$I_VIX"

    def test_dollar_spx_preserved(self):
        assert sanitize_symbol_for_filename("$SPX") == "$SPX"

    def test_caret_preserved(self):
        assert sanitize_symbol_for_filename("^VIX") == "^VIX"

    def test_dot_preserved(self):
        assert sanitize_symbol_for_filename("BRK.B") == "BRK.B"

    def test_hyphen_preserved(self):
        assert sanitize_symbol_for_filename("BRK-B") == "BRK-B"


class TestWindowsReservedNames:
    """Windows reserved device names must not appear as filename stems."""

    @pytest.mark.parametrize("reserved", [
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM9", "LPT1", "LPT9",
    ])
    def test_reserved_name_gets_prefix(self, reserved):
        assert sanitize_symbol_for_filename(reserved) == f"_{reserved}"

    def test_reserved_name_case_insensitive(self):
        assert sanitize_symbol_for_filename("con") == "_con"
        assert sanitize_symbol_for_filename("Nul") == "_Nul"

    def test_reserved_with_extension_gets_prefix(self):
        assert sanitize_symbol_for_filename("CON.parquet") == "_CON.parquet"

    def test_non_reserved_not_prefixed(self):
        assert sanitize_symbol_for_filename("AAPL") == "AAPL"
        assert sanitize_symbol_for_filename("CONT") == "CONT"
        assert sanitize_symbol_for_filename("CONNECT") == "CONNECT"
