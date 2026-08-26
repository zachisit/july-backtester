"""tests/test_filename_utils.py

Tests for helpers/filename_utils.sanitize_symbol_for_filename.
Covers: illegal character replacement, Windows reserved device names,
and common ticker symbol patterns.
"""

import pytest
from helpers.filename_utils import (
    filename_candidates,
    sanitize_symbol_for_filename,
)


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


class TestReservedNameGuardDoesNotOrphanRealData:
    """QA finding F1 on #193 - the one that would have shipped data loss.

    The reserved-name guard prefixes "_", and every READER was looking up only
    the prefixed spelling. But `CON` and `PRN` are REAL TICKERS with files in
    the frozen Norgate corpus:

        CON-199804.parquet      PRN-200207.parquet

    Both DELISTED - i.e. exactly the survivorship-critical names that corpus
    exists to preserve. Verified present in the real 36,684-file corpus, which
    cannot be regenerated (the Norgate subscription has lapsed). Pre-fix, both
    resolved to None and dropped out of backtests with one warning in a run of
    thousands of symbols.
    """

    def test_write_side_guard_is_unchanged(self):
        """The guard must still fire - we are not reverting it, only making
        readers tolerant. NUL.parquet must never be created."""
        assert sanitize_symbol_for_filename("NUL") == "_NUL"
        assert sanitize_symbol_for_filename("CON") == "_CON"
        assert sanitize_symbol_for_filename("com1") == "_com1"

    def test_candidates_offer_the_legacy_spelling_for_reserved_names(self):
        assert filename_candidates("CON") == ["_CON", "CON"]
        assert filename_candidates("PRN") == ["_PRN", "PRN"]

    def test_candidates_are_a_single_entry_for_ordinary_symbols(self):
        """No behaviour change and no extra stat() calls for the 36,682 other
        securities in the corpus."""
        assert filename_candidates("AAPL") == ["AAPL"]
        assert filename_candidates("I:VIX") == ["I_VIX"]
        assert filename_candidates("BRK.B") == ["BRK.B"]

    def test_parquet_reader_finds_the_real_delisted_corpus_files(self, tmp_path):
        """The regression itself, using the exact filenames from the corpus."""
        from services.parquet_service import _find_parquet
        for fname in ["CON-199804.parquet", "PRN-200207.parquet", "AAPL.parquet"]:
            (tmp_path / fname).touch()
        assert _find_parquet("CON", str(tmp_path)).endswith("CON-199804.parquet")
        assert _find_parquet("PRN", str(tmp_path)).endswith("PRN-200207.parquet")
        assert _find_parquet("AAPL", str(tmp_path)).endswith("AAPL.parquet")

    def test_parquet_reader_prefers_the_guarded_spelling_when_both_exist(self, tmp_path):
        from services.parquet_service import _find_parquet
        (tmp_path / "_CON.parquet").touch()
        (tmp_path / "CON.parquet").touch()
        assert _find_parquet("CON", str(tmp_path)).endswith("_CON.parquet")

    def test_csv_reader_finds_a_legacy_unguarded_file(self, tmp_path):
        """PRN.csv is a perfectly legal filename on macOS/Linux, where this
        project actually runs."""
        from services.csv_service import _find_csv
        (tmp_path / "PRN.csv").touch()
        assert _find_csv("PRN", str(tmp_path)).endswith("PRN.csv")

    def test_unknown_symbol_still_returns_none(self, tmp_path):
        from services.parquet_service import _find_parquet
        assert _find_parquet("NOSUCH", str(tmp_path)) is None


class TestDegenerateAndIllegalInputs:
    """QA finding F3 - guard gaps the reserved-name check did not cover.

    The old caching.py sanitizer was a strict whitelist and scrubbed all of
    these; the consolidated blacklist did not, so for that call site they were
    a regression rather than merely a gap.
    """

    def test_control_characters_are_scrubbed(self):
        """NUL is illegal on POSIX too - open() raises rather than returning."""
        assert sanitize_symbol_for_filename("A\x00B") == "A_B"
        assert sanitize_symbol_for_filename("A\x1fB") == "A_B"
        assert "\x00" not in sanitize_symbol_for_filename("\x00\x01\x02")

    def test_trailing_space_no_longer_defeats_the_reserved_check(self):
        """Windows strips trailing spaces, so "CON " resolves to the CON
        device - the guard has to see through it."""
        assert sanitize_symbol_for_filename("CON ") == "_CON"
        assert sanitize_symbol_for_filename("con.") == "_con"

    def test_trailing_dots_and_spaces_are_stripped(self):
        assert sanitize_symbol_for_filename("ABC.") == "ABC"
        assert sanitize_symbol_for_filename("ABC ") == "ABC"
        assert sanitize_symbol_for_filename("ABC . . ") == "ABC"

    def test_empty_input_gets_a_usable_stem(self):
        """"" would yield a hidden ".parquet" with no stem, and every such
        symbol would collide on that one file."""
        assert sanitize_symbol_for_filename("") == "_EMPTY_"
        assert sanitize_symbol_for_filename("   ") == "_EMPTY_"
        assert sanitize_symbol_for_filename("...") == "_EMPTY_"

    def test_conin_and_conout_are_reserved(self):
        assert sanitize_symbol_for_filename("CONIN$") == "_CONIN$"
        assert sanitize_symbol_for_filename("CONOUT$") == "_CONOUT$"

    def test_still_idempotent_after_the_new_passes(self):
        """sanitize(sanitize(x)) == sanitize(x) - a value sanitized twice across
        call sites must not drift."""
        for probe in ["A\x00B", "CON ", "ABC.", "", "$I:TNX", "ADX>20", "..."]:
            once = sanitize_symbol_for_filename(probe)
            assert sanitize_symbol_for_filename(once) == once, probe


class TestCachingCallSiteIsPinned:
    """QA finding F5 - no test imported helpers.caching at all, so reverting it
    to its old whitelist sanitizer passed the entire suite. The consolidation at
    call site #1 of 5 was unverifiable by CI."""

    def test_cache_roundtrip_for_an_index_ticker(self, tmp_path, monkeypatch):
        """Behavioural pin: write then read through the real cache functions
        for a symbol whose name needs sanitizing. Reverting caching.py to its
        old whitelist previously passed the entire suite."""
        import pandas as pd
        import helpers.caching as caching
        monkeypatch.setattr(caching, "CACHE_DIR", str(tmp_path))

        df = pd.DataFrame(
            {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0],
             "Volume": [1.0]},
            index=pd.to_datetime(["2020-01-01"]))
        caching.set_cached_data(df, "I:VIX", "2020-01-01", "2020-01-02", "D", 1)

        written = [p.name for p in tmp_path.iterdir()]
        assert written, "nothing was written to the cache"
        assert any(n.startswith("I_VIX_") for n in written), written

        back = caching.get_cached_data("I:VIX", "2020-01-01", "2020-01-02", "D", 1)
        assert back is not None, "cache write/read used different filenames"

    def test_cache_key_reflects_the_shared_sanitizer_not_the_old_whitelist(self):
        """The old caching.py scrub was a strict whitelist that collapsed `$`
        and `^`; the shared blacklist preserves them."""
        assert sanitize_symbol_for_filename("I:VIX") == "I_VIX"
        assert sanitize_symbol_for_filename("$VIX") == "$VIX"   # old: "_VIX"

    def test_index_tickers_stay_distinct_in_cache_keys(self):
        """The old whitelist collapsed $VIX and ^VIX to the same "_VIX" key -
        two different series sharing one cache file."""
        assert sanitize_symbol_for_filename("$VIX") != \
            sanitize_symbol_for_filename("^VIX")
