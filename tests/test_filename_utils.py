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

    def test_angle_brackets_map_to_semantic_tokens(self):
        # Angle brackets are consumed by the comparison-operator prepass before
        # the generic scrub, so they become distinct _lt_/_gt_ tokens rather
        # than both collapsing to "_" (see TestComparisonOperators).
        assert sanitize_symbol_for_filename("A<B>C") == "A_lt_B_gt_C"

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


class TestComparisonOperators:
    """Comparison operators must map to distinct tokens so paired sweep configs
    (e.g. ``ADX>20`` / ``ADX<20``) never collapse to one filename and silently
    overwrite each other's results. Regression for issue #193.
    """

    def test_gt_and_lt_stay_distinct(self):
        # The core regression: without the semantic prepass both scrub to
        # "ADX_20" and the second sweep config overwrites the first.
        assert (sanitize_symbol_for_filename("ADX>20")
                != sanitize_symbol_for_filename("ADX<20"))

    def test_gte_and_gt_stay_distinct(self):
        # Longest-operator-first ordering: ">=" must not degrade into "_gt_=".
        assert (sanitize_symbol_for_filename("ADX>=20")
                != sanitize_symbol_for_filename("ADX>20"))

    def test_lte_and_lt_stay_distinct(self):
        assert (sanitize_symbol_for_filename("ADX<=20")
                != sanitize_symbol_for_filename("ADX<20"))

    @pytest.mark.parametrize("label,expected", [
        ("ADX>20", "ADX_gt_20"),
        ("ADX<20", "ADX_lt_20"),
        ("ADX>=20", "ADX_gte_20"),
        ("ADX<=20", "ADX_lte_20"),
        ("RSI<30", "RSI_lt_30"),
        ("RSI>70", "RSI_gt_70"),
    ])
    def test_exact_token_mapping(self, label, expected):
        assert sanitize_symbol_for_filename(label) == expected

    def test_all_four_operators_mutually_distinct(self):
        labels = ["ADX>20", "ADX<20", "ADX>=20", "ADX<=20"]
        out = [sanitize_symbol_for_filename(x) for x in labels]
        assert len(set(out)) == len(out), out

    def test_real_incident_filename(self):
        # The literal label that produced the on-disk collision documented in
        # issue #193 (`EMA_PB-A3_ADX>20.csv`).
        assert (sanitize_symbol_for_filename("EMA_PB-A3_ADX>20")
                == "EMA_PB-A3_ADX_gt_20")

    def test_no_residual_illegal_chars_after_mapping(self):
        # Every "<"/">" must be consumed by the prepass — none may survive into
        # the output where a filesystem would reject or mangle it.
        for label in ["ADX>20", "ADX<20", "ADX>=20", "ADX<=20", "A<B>C"]:
            result = sanitize_symbol_for_filename(label)
            assert "<" not in result and ">" not in result, result

    def test_operator_mapping_composes_with_other_illegal_chars(self):
        # A colon (illegal) alongside an operator: both handled, still distinct.
        assert sanitize_symbol_for_filename("I:X>5") == "I_X_gt_5"
        assert sanitize_symbol_for_filename("I:X<5") == "I_X_lt_5"

    def test_plain_label_without_operator_unchanged(self):
        # No-op path: a label with no comparison operator is untouched by the prepass.
        assert sanitize_symbol_for_filename("SMA_50_200") == "SMA_50_200"


class TestResidualLiteralTokenCollision:
    """@shardul0701's non-blocking finding on #193.

    The operator prepass trades the original "any `>`/`<` collapses to `_`"
    collision for a much narrower one: a label that ALREADY contains a literal
    `_gt_` / `_lt_` / `_gte_` / `_lte_` collides with the corresponding operator
    label, because the substitution is not escaped.

    Left unfixed deliberately. A correct fix needs an escape scheme (e.g. tokens
    `~gt~` with literal `~` doubled to `~~`), which CHANGES THE FILENAME FORMAT
    and would rename every existing sweep output - disproportionate for a
    collision that requires a hand-authored label containing the exact
    substring, versus the original which fired on any comparison sweep.

    Pinned as strict xfail rather than left as prose: the moment an escape
    scheme lands, these flip to failures and force the tests to be updated. A
    known collision in a collision-fixing utility should not be able to rot.
    """

    @pytest.mark.xfail(reason=(
        "known residual: literal '_gt_' collides with the '>' substitution; "
        "fixing needs an escape scheme that changes the filename format"),
        strict=True)
    def test_literal_token_is_distinct_from_the_operator(self):
        assert sanitize_symbol_for_filename("ADX_gt_20") != \
            sanitize_symbol_for_filename("ADX>20")

    @pytest.mark.xfail(reason="same residual, two-char operator form",
                       strict=True)
    def test_literal_two_char_token_is_distinct_from_the_operator(self):
        assert sanitize_symbol_for_filename("ADX_lte_20") != \
            sanitize_symbol_for_filename("ADX<=20")

    def test_the_collision_is_narrower_than_the_bug_it_replaced(self):
        """The original defect fired on ANY comparison sweep - the pair below is
        the exact case Suriya blocked on. That is fixed and stays fixed; only
        the hand-authored-literal case remains."""
        assert sanitize_symbol_for_filename("ADX>20") != \
            sanitize_symbol_for_filename("ADX<20")
        assert sanitize_symbol_for_filename("ADX>=20") != \
            sanitize_symbol_for_filename("ADX>20")
