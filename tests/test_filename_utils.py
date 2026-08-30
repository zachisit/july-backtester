"""tests/test_filename_utils.py

Tests for helpers/filename_utils.sanitize_symbol_for_filename.
Covers: illegal character replacement, Windows reserved device names,
and common ticker symbol patterns.
"""

import ast
import os
import re

import pandas as pd
import pytest
from helpers.filename_utils import (
    resolve_existing,
    filename_candidates,
    sanitize_symbol_for_filename,
)

# First entry of scripts/validate_norgate_export.DATABASES — the stub in
# TestReadPathsFindALegacyUnguardedFile answers symbols for this one only.
_FIRST_DB = "US Equities"

# Names whose import marks a module as a filename read path.
_SANITIZER_IMPORTS = {"sanitize_symbol_for_filename", "filename_candidates",
                      "resolve_existing"}
_DERIVE_SKIP = {".git", ".venv", "node_modules", "data_cache", "output",
                "__pycache__", ".tokensave", ".pytest_cache", "tests"}


def _derive_read_paths(root=None):
    """Every non-test module importing a filename helper, repo-relative.

    DERIVED rather than hand-listed: @shardul0701 pointed out that a
    hand-maintained coverage array reads as "protected" to the next person while
    silently failing to grow, which is the same failure class the whole contract
    is about. He verified the derivation is exact against the hand-list, so this
    is a maintainability fix, not a behaviour change.
    """
    if root is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in _DERIVE_SKIP and not d.startswith(".")]
        for fnm in filenames:
            if not fnm.endswith(".py") or fnm.startswith("test_"):
                continue
            path = os.path.join(dirpath, fnm)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            if _imports_filename_utils(tree):
                found.append(os.path.relpath(path, root))
    return sorted(set(found))


def _imports_filename_utils(tree):
    """True if *tree* imports the filename helpers by ANY of the six forms.

    @shardul0701 found the original matched only `ImportFrom` with the module
    path spelled out, so three ordinary forms were missed:

        import helpers.filename_utils as fu       MISSED
        from helpers import filename_utils        MISSED
        import helpers.filename_utils             MISSED

    A sixth read path written any of those ways extended coverage by nothing and
    the guard never noticed — the exact failure this contract exists to prevent.
    """
    for n in ast.walk(tree):
        # from helpers.filename_utils import X  /  from .filename_utils import X
        if isinstance(n, ast.ImportFrom):
            if n.module and "filename_utils" in n.module:
                if {a.name for a in n.names} & _SANITIZER_IMPORTS:
                    return True
                # from helpers.filename_utils import *
                if any(a.name == "*" for a in n.names):
                    return True
            # from helpers import filename_utils
            if any(a.name == "filename_utils" for a in n.names):
                return True
        # import helpers.filename_utils [as fu]
        if isinstance(n, ast.Import):
            if any("filename_utils" in a.name for a in n.names):
                return True
    return False


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

    # Independently hand-spelled, NOT derived from the implementation — a
    # comprehension here would reproduce whatever bug the source has.
    _WIN32_RESERVED_LITERAL = {
        "CON", "PRN", "AUX", "NUL",
        "CONIN$", "CONOUT$",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
        # Windows reads the ISO/IEC 8859-1 superscript digits AS digits.
        # Missing from the implementation AND from this literal until the set
        # was checked against the Win32 spec instead of against itself — which
        # is the failure mode a set-equality test is structurally blind to.
        "COM¹", "COM²", "COM³", "LPT¹", "LPT²", "LPT³",
    }

    @pytest.mark.parametrize("name", sorted(_WIN32_RESERVED_LITERAL))
    def test_every_reserved_name_is_guarded(self, name):
        """Each name individually, not just the edges of the ranges.

        The parametrization above covers COM1/COM9/LPT1/LPT9. Verified:
        shrinking the implementation's set to COM{1,2,9} — deleting COM3-COM8 —
        passed the ENTIRE suite, because nothing tested the middle. A guarded
        `_COM3.parquet` on disk would then be unreachable, and new writes would
        emit `COM3.parquet`, which on Windows fails or targets the device.
        """
        assert sanitize_symbol_for_filename(name) == f"_{name}"
        assert filename_candidates(name) == [f"_{name}", name]

    def test_reserved_set_matches_the_hand_spelled_literal(self):
        """Set equality, so a name cannot be added or dropped unnoticed."""
        from helpers import filename_utils as fu
        actual = {n.upper() for n in fu._WINDOWS_RESERVED}
        assert actual == self._WIN32_RESERVED_LITERAL, (
            f"reserved set drifted:\n  only in impl: "
            f"{sorted(actual - self._WIN32_RESERVED_LITERAL)}\n"
            f"  missing from impl: "
            f"{sorted(self._WIN32_RESERVED_LITERAL - actual)}")


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

    def test_cache_write_uses_the_guarded_reserved_spelling(
            self, tmp_path, monkeypatch):
        """The OTHER half of the #345 contract, which this PR made invisible.

        The contract is: readers try every spelling, writers ALWAYS emit the
        guarded one. Hardening the readers means a write-guard regression now
        produces files the tolerant readers happily find — so no round-trip
        test can detect it. Verified: dropping `guard_reserved` at this write
        site passes the ENTIRE suite (2226 passed).

        On Windows an unguarded `CON` write fails or targets the device; in
        caching that failure is swallowed by the try/except into an error log,
        giving silent perpetual re-fetch — the same silent-failure profile as
        #345, on the same survivorship-critical names.

        So the write spelling has to be asserted directly, not round-tripped.
        """
        import pandas as pd
        import helpers.caching as caching
        monkeypatch.setattr(caching, "CACHE_DIR", str(tmp_path))

        df = pd.DataFrame(
            {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0],
             "Volume": [1.0]},
            index=pd.to_datetime(["2020-01-01"]))
        caching.set_cached_data(df, "CON", "2020-01-01", "2020-01-02", "D", 1)

        written = [p.name for p in tmp_path.iterdir()]
        assert any(n.startswith("_CON_") for n in written), (
            f"cache WROTE the unguarded reserved spelling: {written}")
        assert not any(n.startswith("CON_") for n in written), (
            f"cache wrote an unguarded CON file: {written}")

    def test_cache_roundtrip_discriminates_the_old_whitelist(
            self, tmp_path, monkeypatch):
        """`I:VIX` cannot detect the reversion this class exists to pin.

        It sanitizes to `I_VIX` under BOTH the old whitelist and the shared
        blacklist, so the roundtrip above passes either way — verified by
        reverting caching.py to a whitelist scrub and watching the whole suite
        stay green. Only a symbol carrying a character the whitelist ATE and
        the blacklist KEEPS separates them.
        """
        import pandas as pd
        import helpers.caching as caching
        monkeypatch.setattr(caching, "CACHE_DIR", str(tmp_path))

        df = pd.DataFrame(
            {"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0],
             "Volume": [1.0]},
            index=pd.to_datetime(["2020-01-01"]))
        caching.set_cached_data(df, "$VIX", "2020-01-01", "2020-01-02", "D", 1)

        written = [p.name for p in tmp_path.iterdir()]
        assert any(n.startswith("$VIX_") for n in written), (
            f"cache key dropped the '$' — that is the OLD whitelist scrub, "
            f"which collapsed $VIX and ^VIX onto one file: {written}")
        assert caching.get_cached_data(
            "$VIX", "2020-01-01", "2020-01-02", "D", 1) is not None

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


class TestReadPathsResolveEveryCandidateSpelling:
    """Issue #345 — the contract was written down and three of five readers
    violated it.

    `filename_utils.py` says "READ paths must use this, not
    sanitize_symbol_for_filename alone", because a corpus written before the
    reserved-name guard stores `CON`/`PRN` unguarded. A reader checking only
    `_CON` reports "missing" / "not cached" for a file that EXISTS — silently,
    never raising — and those are precisely the delisted names the survivorship
    work depends on.

    @shardul0701's diagnosis of why it drifted is the part worth encoding:
    *the unsafe call had the short obvious name and the safe one was opt-in.*
    So `resolve_existing()` now does the whole candidate x case x template loop,
    and these tests make a future violation detectable rather than silent.
    """

    def test_resolves_a_legacy_unguarded_parquet(self, tmp_path):
        """The #345 case: a corpus written before the guard stores PRN
        unguarded, and the guarded spelling `_PRN.parquet` does not exist."""
        (tmp_path / "PRN.parquet").touch()
        got = resolve_existing(tmp_path, "PRN")
        assert got is not None, "legacy unguarded spelling not resolved"
        assert os.path.basename(got) == "PRN.parquet"

    def test_does_not_match_the_dated_delisted_form(self, tmp_path):
        """Scope boundary, asserted rather than assumed: the `-YYYYMM` fallback
        is `_find_parquet`'s job (it globs), not this helper's. Encoding it here
        would give two places that know the corpus naming convention."""
        (tmp_path / "PRN-200207.parquet").touch()
        assert resolve_existing(tmp_path, "PRN") is None

    def test_prefers_the_guarded_spelling_when_both_exist(self, tmp_path):
        (tmp_path / "_CON.parquet").touch()
        (tmp_path / "CON.parquet").touch()
        assert resolve_existing(tmp_path, "CON").endswith("_CON.parquet")

    def test_case_variants_are_tried(self, tmp_path, monkeypatch):
        """Asserted on the paths PROBED, not on a filesystem hit.

        A test that writes `aapl.parquet` and looks up `AAPL` is VACUOUS on
        macOS and Windows, whose filesystems are case-insensitive — it passes
        whether or not the code tries variants, and only has teeth on
        case-sensitive Linux (i.e. CI). Same platform-dependent-vacuity class as
        #307. Recording the probes works identically everywhere.
        """
        probed = []
        real_isfile = os.path.isfile

        def spy(path):
            probed.append(os.path.basename(str(path)))
            return False
        monkeypatch.setattr(os.path, "isfile", spy)
        resolve_existing(tmp_path, "AAPL")
        monkeypatch.setattr(os.path, "isfile", real_isfile)

        assert "AAPL.parquet" in probed
        assert "aapl.parquet" in probed, (
            "case variants are not probed; a corpus stored in a different case "
            "would read as missing on a case-sensitive filesystem"
        )

    def test_reserved_name_probes_both_spellings(self, tmp_path, monkeypatch):
        """The #345 case, likewise asserted on probes rather than on a hit."""
        probed = []
        monkeypatch.setattr(os.path, "isfile",
                            lambda p: probed.append(os.path.basename(str(p))) or False)
        resolve_existing(tmp_path, "CON")
        assert "_CON.parquet" in probed          # guarded, tried first
        assert "CON.parquet" in probed           # legacy — the #345 fix
        assert probed.index("_CON.parquet") < probed.index("CON.parquet")

    def test_template_supports_a_richer_filename(self, tmp_path):
        """The cache keys by symbol AND date range, so a plain suffix is not
        enough — that shape is why caching.py hand-rolled it and drifted."""
        (tmp_path / "PRN_2020-01-01_2024-01-01_D_1.parquet").touch()
        got = resolve_existing(tmp_path, "PRN",
                               template="{name}_2020-01-01_2024-01-01_D_1.parquet")
        assert got is not None

    def test_absent_symbol_returns_none(self, tmp_path):
        assert resolve_existing(tmp_path, "NOSUCH") is None

    def test_template_with_a_second_field_does_not_raise(self, tmp_path):
        """`template.format(name=...)` raised KeyError on any template carrying
        a second brace field. Safe today (caching.py interpolates its dates
        first) but a needless footgun in the helper that is meant to be the
        obvious safe call. @shardul0701."""
        assert resolve_existing(
            tmp_path, "X", template="{name}_{a}.parquet") is None

    def test_template_with_a_second_field_still_resolves_a_real_file(self, tmp_path):
        """...and the literal braces are preserved, not silently eaten."""
        (tmp_path / "CON_{a}.parquet").write_bytes(b"x")
        got = resolve_existing(tmp_path, "CON", template="{name}_{a}.parquet")
        assert got is not None and os.path.basename(got) == "CON_{a}.parquet"

    def test_ordinary_symbols_get_exactly_one_candidate_spelling(self, tmp_path):
        """36,682 of 36,684 securities are not reserved names, so the guard must
        not invent a second *spelling* for them."""
        assert filename_candidates("AAPL") == ["AAPL"]

    def test_probe_count_is_one_spelling_times_two_cases(self, monkeypatch):
        """What the lookup actually costs, measured rather than asserted about
        candidates.

        @shardul0701 caught the previous version of this: it was named
        ...cost_no_extra_lookups but asserted on `filename_candidates`, which
        counts *spellings*, not probes. An ordinary symbol does pay one extra
        `stat` -- `case_variants=True` doubles every spelling, and that is
        deliberate (a Linux corpus may hold either case). Pinning the real
        numbers means a regression to 10 probes fails here instead of passing a
        test whose name promised otherwise.
        """
        probes = []
        real_isfile = os.path.isfile

        def spy(p):
            probes.append(os.path.basename(p))
            return False

        monkeypatch.setattr(os.path, "isfile", spy)
        resolve_existing("/nonexistent", "AAPL")
        ordinary = list(probes)
        probes.clear()
        resolve_existing("/nonexistent", "CON")
        reserved = list(probes)
        monkeypatch.setattr(os.path, "isfile", real_isfile)

        # 1 spelling x 2 cases
        assert ordinary == ["AAPL.parquet", "aapl.parquet"], ordinary
        # 2 spellings x 2 cases, guarded spelling probed first
        assert reserved == [
            "_CON.parquet", "_con.parquet", "CON.parquet", "con.parquet",
        ], reserved

    def test_case_expansion_rule_survives_a_lowercase_symbol(self, monkeypatch):
        """Pin the RULE (exact / upper / lower), not its collapsed output.

        Every existing probe fixture uses a symbol whose sanitized form is
        already uppercase — `AAPL`, `CON` — so the `.upper()` spelling dedups
        into the exact one and the expected probe list is IDENTICAL with or
        without it. Verified: deleting `.upper()` from resolve_existing passed
        the entire suite. Only a lowercase or mixed-case symbol exercises it,
        and on a case-sensitive filesystem (CI, Linux prod) that deletion is a
        silent drop of `CON.parquet` for a ticker configured as `con`.
        """
        probes = []
        real_isfile = os.path.isfile

        def spy(p):
            probes.append(os.path.basename(p))
            return False

        monkeypatch.setattr(os.path, "isfile", spy)
        resolve_existing("/nonexistent", "con")
        lowered = list(probes)
        probes.clear()
        resolve_existing("/nonexistent", "BrkB")
        mixed = list(probes)
        monkeypatch.setattr(os.path, "isfile", real_isfile)

        assert "CON.parquet" in lowered, (
            f"the .upper() case variant is gone — a corpus storing CON.parquet "
            f"is unreachable for a ticker spelled 'con' on any case-sensitive "
            f"filesystem: {lowered}")
        assert lowered == ["_con.parquet", "_CON.parquet",
                           "con.parquet", "CON.parquet"], lowered
        assert mixed == ["BrkB.parquet", "BRKB.parquet", "brkb.parquet"], mixed

class TestReadPathsFindALegacyUnguardedFile:
    """The primary evidence for #345: **behaviour**, not source text.

    @shardul0701 demonstrated that the two structural guards this class replaces
    could not detect the defect they existed for -- one required the name-build
    and the existence-test to sit on the *same source line* (so it missed
    `caching.py`, whose defect spans eight lines and which the PR body led
    with), and the other was a whole-file substring check satisfiable by a dead
    import. Both passed on the pre-fix files.

    So these assert the observable property instead: drop a file under the
    **legacy unguarded spelling** (`CON.parquet`, as a pre-guard corpus holds
    it) into a temp corpus, and require each read path to find it. That fails on
    every pre-fix reader, and no amount of line-layout or import shuffling can
    fool it.
    """

    @staticmethod
    def _write_parquet(path):
        pd.DataFrame(
            {"Open": [1.0], "High": [1.0], "Low": [1.0],
             "Close": [1.0], "Volume": [100]},
            index=pd.DatetimeIndex([pd.Timestamp("2024-01-02", tz="UTC")],
                                   name="Datetime"),
        ).to_parquet(path)

    # ---- helpers/caching.py -------------------------------------------------

    def test_caching_reads_a_legacy_reserved_name(self, tmp_path, monkeypatch):
        """`get_cached_data("CON", ...)` must HIT a cache file written before the
        reserved-name guard. Pre-fix this returned None and re-fetched forever."""
        from helpers import caching

        monkeypatch.setattr(caching, "CACHE_DIR", str(tmp_path))
        legacy = tmp_path / "CON_2024-01-01_2024-06-01_day_1.parquet"
        self._write_parquet(legacy)

        got = caching.get_cached_data("CON", "2024-01-01", "2024-06-01", "day", 1)
        assert got is not None, (
            "get_cached_data reported a cache MISS for a file that exists under "
            "the legacy unguarded spelling — this is #345"
        )

    def test_caching_still_reads_an_ordinary_symbol(self, tmp_path, monkeypatch):
        """No-regression: the guarded path must not break the 99.99% case."""
        from helpers import caching

        monkeypatch.setattr(caching, "CACHE_DIR", str(tmp_path))
        self._write_parquet(tmp_path / "AAPL_2024-01-01_2024-06-01_day_1.parquet")
        assert caching.get_cached_data(
            "AAPL", "2024-01-01", "2024-06-01", "day", 1) is not None

    def test_caching_misses_when_genuinely_absent(self, tmp_path, monkeypatch):
        """The counter-case, so the two above cannot pass by always returning a
        frame."""
        from helpers import caching

        monkeypatch.setattr(caching, "CACHE_DIR", str(tmp_path))
        assert caching.get_cached_data(
            "CON", "2024-01-01", "2024-06-01", "day", 1) is None

    # ---- scripts/norgate_to_parquet.py --------------------------------------

    def test_export_symbol_skips_a_legacy_reserved_name(self, tmp_path):
        """`--skip-existing` must treat a legacy `CON.parquet` as present.

        Pre-fix (and still true on the first revision of this PR, which fixed
        only the `main()` call site) this re-exported every reserved-name symbol
        and left both spellings on disk.
        """
        import scripts.norgate_to_parquet as n2p

        self._write_parquet(tmp_path / "CON.parquet")

        called = []

        def _boom(*a, **k):
            called.append(1)
            raise AssertionError("re-exported a symbol that is already present")

        # export_symbol imports get_price_data lazily from services.norgate_service
        import sys
        import types
        stub = types.ModuleType("services.norgate_service")
        stub.get_price_data = _boom
        monkey_prev = sys.modules.get("services.norgate_service")
        sys.modules["services.norgate_service"] = stub
        try:
            ok = n2p.export_symbol("CON", tmp_path, {}, skip_existing=True)
        finally:
            if monkey_prev is None:
                sys.modules.pop("services.norgate_service", None)
            else:
                sys.modules["services.norgate_service"] = monkey_prev

        assert ok is True
        assert not called, "fetched data for a symbol already on disk"

    def test_export_symbol_still_exports_an_absent_symbol(self, tmp_path):
        """The counter-case, and it is load-bearing.

        Gutting `export_symbol` to an unconditional `return True` passed the
        ENTIRE test file — verified. Every assertion about it was of the form
        "returned True and did not fetch", which a do-nothing exporter
        satisfies perfectly while silently exporting nothing at all. A skip
        test without an export test proves only half the contract, and the half
        it omits is the one that destroys a corpus.
        """
        import sys
        import types
        import scripts.norgate_to_parquet as n2p

        fetched = []
        frame = pd.DataFrame(
            {"Open": [1.0], "High": [1.0], "Low": [1.0],
             "Close": [1.0], "Volume": [100]},
            index=pd.DatetimeIndex([pd.Timestamp("2024-01-02", tz="UTC")],
                                   name="Datetime"))

        def _fetch(symbol, *a, **k):
            fetched.append(symbol)
            return frame

        stub = types.ModuleType("services.norgate_service")
        stub.get_price_data = _fetch
        prev = sys.modules.get("services.norgate_service")
        sys.modules["services.norgate_service"] = stub
        try:
            ok = n2p.export_symbol(
                "NOSUCH", tmp_path,
                {"start_date": "2024-01-01", "end_date": "2024-06-01"},
                skip_existing=True)
        finally:
            if prev is None:
                sys.modules.pop("services.norgate_service", None)
            else:
                sys.modules["services.norgate_service"] = prev

        assert fetched == ["NOSUCH"], (
            "export_symbol did not fetch a symbol that is absent from the "
            "corpus — it exports nothing")
        assert ok is True
        assert (tmp_path / "NOSUCH.parquet").is_file(), (
            "export_symbol reported success without writing the file")

    def test_export_symbol_writes_the_guarded_reserved_spelling(self, tmp_path):
        """The export write guard, pinned directly for the same reason as the
        cache one: the tolerant readers mask its removal, so dropping
        `guard_reserved` here passes the entire suite. Verified."""
        import sys
        import types
        import scripts.norgate_to_parquet as n2p

        frame = pd.DataFrame(
            {"Open": [1.0], "High": [1.0], "Low": [1.0],
             "Close": [1.0], "Volume": [100]},
            index=pd.DatetimeIndex([pd.Timestamp("2024-01-02", tz="UTC")],
                                   name="Datetime"))
        stub = types.ModuleType("services.norgate_service")
        stub.get_price_data = lambda *a, **k: frame
        prev = sys.modules.get("services.norgate_service")
        sys.modules["services.norgate_service"] = stub
        try:
            n2p.export_symbol(
                "CON", tmp_path,
                {"start_date": "2024-01-01", "end_date": "2024-06-01"})
        finally:
            if prev is None:
                sys.modules.pop("services.norgate_service", None)
            else:
                sys.modules["services.norgate_service"] = prev

        names = [p.name for p in tmp_path.iterdir()]
        assert "_CON.parquet" in names, (
            f"export WROTE the unguarded reserved spelling: {names}")
        assert "CON.parquet" not in names, names

    def test_main_skip_existing_honours_a_legacy_reserved_name(
            self, tmp_path, monkeypatch, caplog):
        """`main()`'s OWN skip decision — measured at main(), not downstream.

        History worth keeping, because the first version of this test was
        decoration and its docstring said otherwise:

        Reverting main()'s skip check to a guarded-spelling probe does NOT
        re-export anything, because `export_symbol` runs its own
        `resolve_existing` and skips there instead. So a test that only asserts
        "nothing was fetched" passes on a broken main() and measures
        export_symbol's fix twice. Verified: with main() reverted, that
        assertion still passed and only the AST scan caught it.

        This version stubs `export_symbol` so main()'s decision is the only
        thing observed, and asserts on the skip COUNT main() itself reports.
        """
        import sys
        import types
        import scripts.norgate_to_parquet as n2p

        self._write_parquet(tmp_path / "CON.parquet")

        exported = []
        stub = types.ModuleType("services.norgate_service")
        stub.get_price_data = lambda *a, **k: None

        # Stub export_symbol so main()'s OWN skip decision is what is measured.
        # Without this, export_symbol's separate resolve_existing absorbs the
        # defect and this test passes on a broken main().
        def _reached(symbol, *a, **k):
            exported.append(symbol)
            return True

        monkeypatch.setattr(n2p, "export_symbol", _reached)
        # main() imports norgatedata for its availability check; the package is
        # not installable here (no subscription), so it is stubbed rather than
        # skipped -- a skipped test on the one call site that had no coverage
        # would leave exactly the hole this test exists to close.
        nd = types.ModuleType("norgatedata")
        nd.status = lambda: "OK"
        nd.database_symbols = lambda db: ["CON"]
        nd.StockPriceAdjustmentType = types.SimpleNamespace(TOTALRETURN=1)
        nd.PaddingType = types.SimpleNamespace(
            NONE=0, ALLMARKETDAYS=1, ALLWEEKDAYS=2, ALLCALENDARDAYS=3)
        prev_svc = sys.modules.get("services.norgate_service")
        prev_nd = sys.modules.get("norgatedata")
        sys.modules["services.norgate_service"] = stub
        sys.modules["norgatedata"] = nd
        monkeypatch.setattr(
            sys, "argv",
            ["norgate_to_parquet.py", "--tickers", "CON",
             "--output-dir", str(tmp_path), "--skip-existing"])
        try:
            with caplog.at_level("INFO", logger="scripts.norgate_to_parquet"):
                n2p.main()
        finally:
            for key, prev in (("services.norgate_service", prev_svc),
                              ("norgatedata", prev_nd)):
                if prev is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = prev

        assert not exported, (
            f"main() passed {exported} to export_symbol despite a legacy "
            f"CON.parquet already on disk — main()'s own skip check did not "
            f"resolve the unguarded spelling (#345)")
        # The skip/export ACCOUNTING is the only observable produced solely by
        # main()'s own check — export_symbol's backstop cannot fake it.
        summary = "\n".join(r.message for r in caplog.records)
        assert "0 exported, 0 failed, 1 skipped" in summary, (
            "main() did not count the symbol as skipped — its own check did "
            "not resolve the legacy unguarded spelling:\n" + summary)

    def test_main_skip_existing_still_exports_an_absent_symbol(
            self, tmp_path, monkeypatch):
        """The counter-case. Without it, `if args.skip_existing:` — skip
        EVERYTHING, unconditionally — passes, and so does a main() that never
        exports at all. A skip test that only proves skipping is half a
        contract."""
        import sys
        import types
        import scripts.norgate_to_parquet as n2p

        exported = []
        stub = types.ModuleType("services.norgate_service")
        stub.get_price_data = lambda *a, **k: None
        monkeypatch.setattr(
            n2p, "export_symbol",
            lambda symbol, *a, **k: (exported.append(symbol), True)[1])

        nd = types.ModuleType("norgatedata")
        nd.status = lambda: "OK"
        nd.database_symbols = lambda db: ["NOSUCH"]
        nd.StockPriceAdjustmentType = types.SimpleNamespace(TOTALRETURN=1)
        nd.PaddingType = types.SimpleNamespace(
            NONE=0, ALLMARKETDAYS=1, ALLWEEKDAYS=2, ALLCALENDARDAYS=3)
        prev_svc = sys.modules.get("services.norgate_service")
        prev_nd = sys.modules.get("norgatedata")
        sys.modules["services.norgate_service"] = stub
        sys.modules["norgatedata"] = nd
        monkeypatch.setattr(
            sys, "argv",
            ["norgate_to_parquet.py", "--tickers", "NOSUCH",
             "--output-dir", str(tmp_path), "--skip-existing"])
        try:
            n2p.main()
        finally:
            for key, prev in (("services.norgate_service", prev_svc),
                              ("norgatedata", prev_nd)):
                if prev is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = prev

        assert exported == ["NOSUCH"], (
            "main() skipped a symbol that is NOT on disk — --skip-existing "
            "skipped everything")

    # ---- scripts/validate_norgate_export.py ---------------------------------

    def test_validator_does_not_report_a_legacy_name_as_missing(
            self, tmp_path, capsys):
        """The validator's most load-bearing cell. Pre-fix, a corpus containing
        `CON.parquet` was reported as MISSING it."""
        import sys
        import types
        import importlib

        stub = types.ModuleType("norgatedata")
        stub.database_symbols = lambda db: ["CON"] if db == _FIRST_DB else []
        prev = sys.modules.get("norgatedata")
        sys.modules["norgatedata"] = stub
        try:
            v = importlib.import_module("scripts.validate_norgate_export")
            self._write_parquet(tmp_path / "CON.parquet")
            v.validate(tmp_path)
            out = capsys.readouterr().out
        finally:
            if prev is None:
                sys.modules.pop("norgatedata", None)
            else:
                sys.modules["norgatedata"] = prev

        # POSITIVE assertions first. Asserting only `"MISSING" not in out` was
        # vacuous: the final QA round gutted validate() to a bare `return` --
        # checking nothing, printing nothing -- and this test still passed. It
        # also could not detect its own fixture rotting; renaming DATABASES[0]
        # makes the stub answer [] for every database, so CON is never checked,
        # and the negative assertion holds just as well.
        assert f"[{_FIRST_DB}]" in out, (
            f"validator never ran the {_FIRST_DB!r} block — the stub's database "
            f"name has drifted from scripts.validate_norgate_export.DATABASES, "
            f"so this test is checking nothing:\n{out}")
        assert "Local parquet   : 1" in out, (
            "validator did not count the legacy CON.parquet as present:\n" + out)
        assert "TOTAL missing   : 0" in out, out
        assert "MISSING" not in out, (
            "validator reported a symbol as missing from a corpus that has it "
            "under the legacy unguarded spelling:\n" + out
        )

    def test_validator_does_report_a_genuinely_absent_symbol(
            self, tmp_path, capsys):
        """The counter-case. Forcing `missing = []` inside validate() passed —
        verified. For a VALIDATOR the missing-report is the entire product, so
        a test suite that only proves it stays quiet proves nothing."""
        import sys
        import types
        import importlib

        stub = types.ModuleType("norgatedata")
        stub.database_symbols = lambda db: ["NOSUCH"] if db == _FIRST_DB else []
        prev = sys.modules.get("norgatedata")
        sys.modules["norgatedata"] = stub
        try:
            v = importlib.import_module("scripts.validate_norgate_export")
            v.validate(tmp_path)          # empty corpus — nothing on disk
            out = capsys.readouterr().out
        finally:
            if prev is None:
                sys.modules.pop("norgatedata", None)
            else:
                sys.modules["norgatedata"] = prev

        assert "MISSING 1" in out, out
        assert "TOTAL missing   : 1" in out, out
        assert "- NOSUCH" in out, out

    # ---- services/csv_service.py --------------------------------------------

    def test_csv_service_reads_a_legacy_reserved_name(self, tmp_path):
        """`CON.csv` on disk must be found. @shardul0701 noted the AST backstop
        was blind on this file's idiom, so the behavioural test IS the guard
        here -- it needs to exist rather than be assumed."""
        from services import csv_service

        (tmp_path / "CON.csv").write_text(
            "Date,Open,High,Low,Close,Volume\n2024-01-02,1,1,1,1,100\n",
            encoding="utf-8")
        assert csv_service._find_csv("CON", str(tmp_path)) is not None

    def test_csv_service_misses_when_genuinely_absent(self, tmp_path):
        from services import csv_service
        assert csv_service._find_csv("CON", str(tmp_path)) is None

    # ---- services/parquet_service.py ----------------------------------------

    def test_parquet_service_reads_a_legacy_reserved_name(self, tmp_path):
        from services import parquet_service

        self._write_parquet(tmp_path / "CON.parquet")
        assert parquet_service._find_parquet("CON", str(tmp_path)) is not None

    def test_parquet_service_misses_when_genuinely_absent(self, tmp_path):
        from services import parquet_service
        assert parquet_service._find_parquet("CON", str(tmp_path)) is None


class TestProviderEntryPointsReturnLegacyNamedData:
    """END TO END, through the function `main.py` actually calls.

    Every reserved-name pin in this file targets the RESOLVER layer --
    `_find_parquet`, `_find_csv`, `resolve_existing`, `get_cached_data`. The
    provider ENTRY points one frame up were never tested with a reserved name,
    and a QA sweep weaponised that twice: a sanitized-name equality gate in
    `parquet_service.get_price_data` and a listing-based fast-path precheck in
    `csv_service.get_price_data` each dropped CON/PRN silently while the FULL
    suite stayed green.

    Neither is reachable by the AST backstop, and that is not a fixable gap:
    the scanner models probe VERBS, and a string-equality filter on an
    already-resolved path is not a probe. The guard for this class has to be
    behavioural, asserted at the layer the application uses.
    """

    @staticmethod
    def _frame():
        return pd.DataFrame(
            {"Open": [1.0, 2.0], "High": [1.0, 2.0], "Low": [1.0, 2.0],
             "Close": [1.0, 2.0], "Volume": [100, 200]},
            index=pd.DatetimeIndex(
                [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")],
                name="Datetime"))

    def test_parquet_provider_returns_a_legacy_unguarded_reserved_name(
            self, tmp_path):
        from services import parquet_service

        self._frame().to_parquet(tmp_path / "CON.parquet")
        got = parquet_service.get_price_data(
            "CON", "2024-01-01", "2024-06-01",
            {"parquet_data_dir": str(tmp_path)})
        assert got is not None and not got.empty, (
            "the parquet PROVIDER dropped a reserved-name symbol whose only "
            "file uses the legacy unguarded spelling — #345 through the front "
            "door")

    def test_parquet_provider_returns_the_dated_delisted_form(self, tmp_path):
        """The real corpus stores delisted reserved names DATED
        (`PRN-200207.parquet`). That fallback had no coverage through the
        provider entry point at all."""
        from services import parquet_service

        self._frame().to_parquet(tmp_path / "PRN-200207.parquet")
        got = parquet_service.get_price_data(
            "PRN", "2024-01-01", "2024-06-01",
            {"parquet_data_dir": str(tmp_path)})
        assert got is not None and not got.empty, (
            "the parquet provider dropped the DATED delisted form — the shape "
            "the frozen corpus actually stores")

    def test_parquet_provider_still_returns_an_ordinary_symbol(self, tmp_path):
        from services import parquet_service

        self._frame().to_parquet(tmp_path / "AAPL.parquet")
        assert parquet_service.get_price_data(
            "AAPL", "2024-01-01", "2024-06-01",
            {"parquet_data_dir": str(tmp_path)}) is not None

    def test_csv_provider_returns_a_legacy_unguarded_reserved_name(
            self, tmp_path):
        from services import csv_service

        (tmp_path / "CON.csv").write_text(
            "Date,Open,High,Low,Close,Volume\n"
            "2024-01-02,1,1,1,1,100\n2024-01-03,2,2,2,2,200\n",
            encoding="utf-8")
        got = csv_service.get_price_data(
            "CON", "2024-01-01", "2024-06-01",
            {"csv_data_dir": str(tmp_path)})
        assert got is not None and not got.empty, (
            "the CSV PROVIDER dropped a reserved-name symbol whose only file "
            "uses the legacy unguarded spelling — #345 through the front door")

    def test_csv_provider_still_returns_an_ordinary_symbol(self, tmp_path):
        from services import csv_service

        (tmp_path / "AAPL.csv").write_text(
            "Date,Open,High,Low,Close,Volume\n2024-01-02,1,1,1,1,100\n",
            encoding="utf-8")
        assert csv_service.get_price_data(
            "AAPL", "2024-01-01", "2024-06-01",
            {"csv_data_dir": str(tmp_path)}) is not None

    # -- every LOCAL-FILE branch get_data_service dispatches to ---------------
    #
    # @shardul0701's answer to "are the provider pins in the right place":
    # right layer, wrong boundary. The class covered the two providers that
    # happen to IMPORT a filename helper — which is also the membership rule of
    # `_derive_read_paths`. That rule is self-fulfilling: a reader that never
    # imports the sanitizer is invisible to the guard BECAUSE it violates the
    # contract, so the modules most worth pinning are the ones the derivation
    # cannot see.
    #
    # `get_data_service` has six branches. polygon / norgate / yahoo fetch over
    # the network and never build a per-symbol local filename, so they are out
    # of scope by construction. The local-file readers are csv, parquet and
    # merged — and merged was uncovered.

    LOCAL_FILE_PROVIDERS = ["csv", "parquet", "merged"]

    def test_every_local_file_provider_branch_is_pinned(self):
        """If a new local-file provider is added, this fails until it is
        given a pin — the coverage cannot silently stay at the old set."""
        src = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "services", "__init__.py"), encoding="utf-8").read()
        branches = set(re.findall(r'provider == "(\w+)"', src))
        network = {"polygon", "norgate", "yahoo"}
        local = branches - network
        assert local == set(self.LOCAL_FILE_PROVIDERS), (
            f"get_data_service's local-file branches changed: {sorted(local)}.\n"
            f"Every branch that reads a per-symbol file from disk needs a "
            f"reserved-name pin in this class — add it, or add the new branch "
            f"to `network` with a one-line reason if it fetches remotely.")

    def test_merged_provider_returns_a_legacy_unguarded_reserved_name(
            self, tmp_path):
        """Was a strict xfail; closed by #355.

        The merged provider built its own candidate list and imported no
        filename helper, so a symbol arriving in its SOURCE spelling could not
        reach the file the corpus stores. It now also tries
        `filename_candidates`, and the xfail flipping to XPASS is what said so.
        """
        from src.data.unified_market_data_provider import UnifiedMarketDataProvider

        self._frame().rename(columns=str.lower).to_parquet(
            tmp_path / "_CON.parquet")
        prov = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        got = prov.get_price_data("CON", "2024-01-01", "2024-06-01")
        assert got is not None and not got.empty

    def test_merged_provider_returns_an_illegal_char_symbol(self, tmp_path):
        """Was a strict xfail; closed by #355. This is the shape with live
        exposure — @shardul0701 measured six sanitized stems in the shipped
        merged corpus (BBAI_W, BIII_W, MPTI_R, OPFI_W, PAII_W, VACI_W —
        warrants and class shares) that this provider could not reach."""
        from src.data.unified_market_data_provider import UnifiedMarketDataProvider

        self._frame().rename(columns=str.lower).to_parquet(
            tmp_path / "BRK_B.parquet")
        prov = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        got = prov.get_price_data("BRK/B", "2024-01-01", "2024-06-01")
        assert got is not None and not got.empty

    def test_merged_provider_composes_the_uppercase_sanitized_variant(
            self, tmp_path, monkeypatch):
        """The `.upper()` branch, tested WITHOUT the filesystem.

        On macOS/APFS a case-insensitive lookup matches regardless, so a
        behavioural test here passes through the filesystem rather than through
        the code — and deleting `.upper()` survived mutation. On case-sensitive
        CI/Linux that branch is the only thing letting a lowercase source
        spelling reach an uppercase stem. Record the composed candidates
        instead.
        """
        from src.data.unified_market_data_provider import UnifiedMarketDataProvider

        self._frame().rename(columns=str.lower).to_parquet(
            tmp_path / "BRK_B.parquet")
        prov = UnifiedMarketDataProvider(merged_dir=str(tmp_path))

        probed = []
        real_exists = os.path.exists

        def spy(p):
            probed.append(os.path.basename(p))
            return real_exists(p)

        monkeypatch.setattr(os.path, "exists", spy)
        prov._candidate_paths("brk/b")
        monkeypatch.setattr(os.path, "exists", real_exists)

        assert "BRK_B.parquet" in probed, (
            f"the uppercase sanitized variant was never composed, so a "
            f"lowercase symbol cannot reach an uppercase stem on a "
            f"case-sensitive filesystem: {probed}")

    def test_merged_provider_prefers_the_exact_file_over_the_sanitized_one(
            self, tmp_path):
        """Candidate ORDER. Nothing pinned it, so a refactor that put the
        sanitized spellings first passed the whole suite while flipping which
        file wins when both exist."""
        from src.data.unified_market_data_provider import UnifiedMarketDataProvider

        f = self._frame().rename(columns=str.lower)
        f.to_parquet(tmp_path / "CON.parquet")
        f.to_parquet(tmp_path / "_CON.parquet")
        prov = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        got = prov._resolve("CON")
        assert os.path.basename(got) == "CON.parquet", (
            f"resolved {os.path.basename(got)} — a bare exact file must still "
            f"beat a sanitized one; the new candidates are appended, not "
            f"prepended")

    def test_merged_provider_is_self_consistent_on_disk_spellings(self, tmp_path):
        """Why the gap is hard to notice, pinned so the xfails above are not
        read as 'the merged provider is broken'. It resolves what its own
        list_symbols() reports; the loss is only at the outside boundary."""
        from src.data.unified_market_data_provider import UnifiedMarketDataProvider

        # the merged store uses lowercase OHLCV column names
        self._frame().rename(columns=str.lower).to_parquet(
            tmp_path / "BBAI_W.parquet")
        prov = UnifiedMarketDataProvider(merged_dir=str(tmp_path))
        got = prov.get_price_data("BBAI_W", "2024-01-01", "2024-06-01")
        assert got is not None and not got.empty, (
            "the merged provider cannot resolve its own on-disk stem — that "
            "would be a different and larger defect than the one pinned above")


class TestNotFoundWarningReportsWhatWasActuallyProbed:
    """@shardul0701's finding: the CSV not-found warning recomposed its own
    path list from the bare sanitizer instead of reporting the resolver's
    probes, so it named only the GUARDED spellings.

    For `CON` it claimed to have tried `_CON.csv, _con.csv` while having also
    probed `CON.csv` and `con.csv` -- the unguarded legacy spellings this whole
    change exists to support. Someone debugging a missing `CON.csv` was told the
    loader never looked for it.

    Same defect class as the PR subject -- a bare `_sanitize_filename` on a read
    path -- wearing a log line.
    """

    def test_warning_names_every_probed_spelling(self, tmp_path, caplog):
        from services import csv_service

        probed = csv_service._csv_probe_paths("CON", str(tmp_path))
        probed_names = {os.path.basename(p) for p in probed}
        # the resolver genuinely tries the unguarded spellings
        assert "CON.csv" in probed_names and "con.csv" in probed_names
        assert "_CON.csv" in probed_names

        with caplog.at_level("WARNING"):
            csv_service.get_price_data(
                "CON", "2024-01-01", "2024-06-01",
                {"csv_data_dir": str(tmp_path)})
        warnings = "\n".join(r.message for r in caplog.records)
        assert "not found" in warnings.lower(), warnings

        # Parse the reported list EXACTLY. A substring check is vacuous here --
        # "CON.csv" is a substring of "_CON.csv", so `name in warnings` passes
        # even when the guarded spelling is the only one reported. My own
        # mutation run caught that; the assertion has to compare basenames as a
        # set, not search the message text.
        reported = warnings.split("Tried:", 1)[1]
        reported_names = {os.path.basename(p.strip())
                          for p in reported.split(",") if p.strip()}
        missing = probed_names - reported_names
        assert not missing, (
            f"warning omits {sorted(missing)}, which the resolver actually "
            f"probed — a diagnostic that under-reports sends the reader to the "
            f"wrong place:\n{warnings}")

    def test_probe_list_is_deduped_and_ordered(self):
        """An all-caps ticker yields the same path for the .upper() and bare
        spellings; the warning should not print it twice."""
        probed = csv_service_probe("AAPL")
        assert len(probed) == len(set(probed))
        assert os.path.basename(probed[0]) == "AAPL.csv"


def csv_service_probe(symbol, csv_dir="/nonexistent"):
    from services import csv_service
    return csv_service._csv_probe_paths(symbol, csv_dir)


class TestReadPathListIsDerived:
    """`READ_PATH_FILES` must be DERIVED, not hand-listed.

    @shardul0701: a name in a coverage list reads as "protected" to the next
    person. A hand-maintained list is the same "checked, fine" failure one level
    up -- a sixth read path can be added and the guard never notices, which is
    precisely the failure mode this whole PR is about.

    He also verified the derivation is exact today, which is why this is a
    maintainability fix rather than a live bug.
    """

    def test_derivation_matches_every_sanitizer_importer(self):
        derived = set(_derive_read_paths())
        assert derived, "derivation found nothing — the walker is broken"
        # the five known read paths, as a floor
        for expected in ["helpers/caching.py", "services/parquet_service.py",
                         "services/csv_service.py",
                         "scripts/norgate_to_parquet.py",
                         "scripts/validate_norgate_export.py",
                         # joined the set in #355: the merged provider now
                         # imports filename_candidates, so the derivation sees
                         # it. Its arrival here IS the fix being real.
                         "src/data/unified_market_data_provider.py"]:
            assert expected.replace("/", os.sep) in derived, \
                f"{expected} vanished from the derived read-path set"

    # All six ways to import the module. The original test exercised only the
    # first, so it read as proving the property while covering one sixth of it.
    IMPORT_FORMS = {
        "from_module_import_name":
            "from helpers.filename_utils import sanitize_symbol_for_filename\n",
        "relative_from_import":
            "from .filename_utils import sanitize_symbol_for_filename\n",
        "function_body_import":
            "def f():\n"
            "    from helpers.filename_utils import sanitize_symbol_for_filename\n",
        "import_module_as_alias":
            "import helpers.filename_utils as fu\n",
        "from_package_import_module":
            "from helpers import filename_utils\n",
        "plain_import_module":
            "import helpers.filename_utils\n",
    }

    @pytest.mark.parametrize("form", sorted(IMPORT_FORMS))
    def test_a_new_read_path_is_picked_up_automatically(self, form, tmp_path):
        """The property that matters: adding a sixth importer extends coverage
        without anyone editing a list — however it spells the import."""
        pkg = tmp_path / "svc"
        pkg.mkdir()
        (pkg / "new_reader.py").write_text(
            self.IMPORT_FORMS[form] + "def read(s, d):\n    return s\n",
            encoding="utf-8")
        found = _derive_read_paths(root=str(tmp_path))
        assert os.path.join("svc", "new_reader.py") in found, (
            f"a read path importing via {form!r} extends coverage by nothing "
            f"and the guard never notices")

    def test_a_module_importing_nothing_relevant_is_not_a_read_path(self, tmp_path):
        """The counter-case, or the derivation could pass by returning
        everything."""
        (tmp_path / "unrelated.py").write_text(
            "import os\ndef f():\n    return os.getcwd()\n", encoding="utf-8")
        assert _derive_read_paths(root=str(tmp_path)) == []

    def test_coverage_is_the_six_known_read_paths(self):
        """A deliberate TRIPWIRE on the number, not a spec.

        Raised 5 -> 6 in #355, deliberately: the merged provider now imports
        filename_candidates, so the derivation sees it. That is the fix being
        real, not the number being bumped to get green.

        I published "234 modules" on this PR; the real coverage is 5, and 234
        came from a walk over a polluted working tree. This exists so a change
        in coverage is noticed rather than assumed.

        @shardul0701 flagged the hazard in pinning a count: it fights
        `test_a_new_read_path_is_picked_up_automatically` two classes up, and
        the obvious repair when it breaks is to bump the constant — which is
        exactly how a pinned number decays back into prose. Hence the message
        below rather than a bare assert.
        """
        found = _derive_read_paths()
        assert len(found) == 6, (
            f"read-path coverage changed: {len(found)} modules now import a "
            f"filename helper, not 6.\n{found}\n\n"
            f"THIS IS A TRIPWIRE, NOT A FAILURE. If you legitimately added a "
            f"read path, raise this number DELIBERATELY and add the module to "
            f"the floor list in TestReadPathListIsDerived — do not bump it "
            f"just to get green, and do not quote a coverage number anywhere "
            f"without re-deriving it."
        )


class TestNoReadPathBuildsItsOwnFilename:
    """The structural backstop — an AST taint scan, widened after review.

    Rev 1 compared substrings on one source line and missed the multiline shape.
    Rev 2 (the taint scan) fixed that but @shardul0701 mutation-proved it was
    still blind on **eight** further shapes — including the list-literal ->
    loop-variable idiom that is `csv_service.py`'s OWN live code, so the
    backstop was blind pointed exactly at a file it claimed to cover.

    Reproduced, then widened: pathlib `is_file`, `glob`/`listdir` probes,
    annotated and tuple targets, module scope, comprehensions, container ->
    loop-variable flow, and cross-function returns. The self-tests below pin
    every one, so a future narrowing fails loudly instead of quietly.

    Still a BACKSTOP. The behavioural tests above are the real evidence — that
    ordering is what kept the csv blindness from being a hole.
    """

    SANITIZERS = {"_sanitize_filename", "sanitize_symbol_for_filename"}
    SAFE = {"resolve_existing", "_resolve_existing",
            "filename_candidates", "_filename_candidates"}
    # `is_file`/`isdir`/`is_dir` close the pathlib gap: report.py already has
    # is_file() sites and norgate_to_parquet.py -- where the fourth violator
    # lived -- is itself pathlib.
    EXIST_ATTRS = {"exists", "isfile", "is_file", "isdir", "is_dir"}
    # Directory listings are existence tests wearing different clothes;
    # parquet_service.py already uses the listdir idiom.
    LISTING_FUNCS = {"glob", "iglob", "listdir", "scandir",
                     # the other two standard corpus enumerations
                     "walk", "iterdir"}
    # THE CONTRACT IS NOT VERB-SCOPED. @shardul0701's widest finding: a reader
    # that just opens the path and catches the error has the identical failure
    # — CON/PRN drop out silently — and never calls exists() at all:
    #
    #     p = os.path.join(D, _sanitize_filename(s) + ".parquet")
    #     try: return pd.read_parquet(p)
    #     except FileNotFoundError: return None
    #
    # A new read path is at least as likely to be written this way.
    # Verbs that CREATE the file. A probe on a path this scope just wrote is
    # verification of its own write, not a lookup of a pre-existing corpus.
    #
    # SPLIT BY WHERE THE PATH LIVES. Treating every name in every arg as
    # "written" made the suppression fire on spurious overlap — `json.dump({'p':
    # p}, fh)` marked `p` written when `p` was DATA, and any write sharing the
    # bare name `os` or a directory variable suppressed unrelated probes.
    # Verified: that re-opened the os.access regression on main() itself,
    # because `output_dir.mkdir()` sits above the skip check.
    PATH_ARG_WRITES = {"to_parquet", "to_csv", "to_json", "to_pickle",
                       "to_feather", "to_hdf", "to_excel", "savefig"}
    # the RECEIVER is the path: `p.write_text(...)`, `p.touch()`
    # NOTE: `mkdir` is deliberately NOT here. It creates a DIRECTORY, so it
    # cannot vouch for a probe of a file inside that directory — and letting it
    # do so was the headline over-suppression this rule already had to fix once,
    # one level down.
    RECEIVER_WRITES = {"write_text", "write_bytes", "touch"}
    # `fh.write(x)` / `json.dump(obj, fh)` target a HANDLE, not a path — they
    # mark nothing, or a path passed as data would read as written.
    WRITE_FUNCS = PATH_ARG_WRITES | RECEIVER_WRITES
    READ_FUNCS = {"read_parquet", "read_csv", "read_json", "read_pickle",
                  "read_feather", "read_table", "open", "stat", "lstat",
                  "getmtime", "getsize",
                  # read_bytes/read_text were absent while their WRITE twins
                  # write_bytes/write_text were present — the asymmetry was the
                  # tell. A guarded-only reader spelled `Path(p).read_bytes()`
                  # scanned clean inside a COVERED module while the identical
                  # `.stat()` spelling was caught: whether a violation is found
                  # was a verb lottery.
                  "read_bytes", "read_text", "read_hdf", "read_excel",
                  # readers a parquet corpus actually attracts
                  "ParquetFile", "HDFStore", "copyfile", "copy2", "copy",
                  "move", "load", "ZipFile", "read_metadata", "samefile",
                  # An os.access() spelling of main()'s skip check reverted the
                  # #345 fix with the ENTIRE suite still green -- verified. The
                  # verb set is the backstop's whole surface, so a gap in it is
                  # a gap in the contract.
                  "access", "lexists", "getatime", "getctime"}

    _NESTED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)

    # THE COMPUTED-KEY RULE. Stated once; the xfails below refer to it rather
    # than each re-deriving the same argument.
    #
    # `container[*]` is a SINGLE identity covering every computed slot, because
    # a computed key has no statically-known value. Three consequences follow,
    # and all three are pinned as strict xfails:
    #
    #   1. a constant-key write does not match a computed-key read
    #   2. a computed-key write does not match a constant-key read
    #   3. a SAFE computed write clears the taint of an earlier BARE computed
    #      write to a different key (last-write-wins over one shared identity)
    #
    # Each is the same undecidable question -- does the computed key equal the
    # other one -- answered "assume not". Answering it any other way does not
    # remove the undecidability, it relocates it onto correct code: (1) and (2)
    # are mirror images, and reversing (3) would flag a bare write followed by
    # a safe write whose OWN slot is then probed, which is correct.
    #
    # @shardul0701 found faces 1-3 across four revisions. If you find face
    # four, add it here rather than deriving a fresh justification for it.
    _COMPUTED_KEY_RULE = (
        "`container[*]` is one identity for every computed slot; the same "
        "undecidable question (does the computed key equal the other one) is "
        "answered 'assume not'. See _COMPUTED_KEY_RULE on this class"
    )

    @staticmethod
    def _root():
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @classmethod
    def _calls(cls, node):
        for n in ast.walk(node):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Name):
                    yield f.id
                elif isinstance(f, ast.Attribute):
                    yield f.attr

    @classmethod
    def _dotted(cls, node):
        """Canonical spelling of a Name/Attribute/Subscript chain, or None.

        `self.safe` -> "self.safe";  `d['safe']` -> "d['safe']".
        Constant subscripts only — a computed key is not a stable identity.
        """
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = cls._dotted(node.value)
            return f"{base}.{node.attr}" if base else None
        if isinstance(node, ast.Subscript):
            base = cls._dotted(node.value)
            key = node.slice
            if base and isinstance(key, ast.Constant):
                return f"{base}[{key.value!r}]"
            if base:
                # COMPUTED key -> `container[*]`. See _COMPUTED_KEY_RULE below
                # for the single rule this creates and its three consequences.
                return f"{base}[*]"
        return None

    @classmethod
    def _names(cls, node):
        """Every identity referenced: bare names AND dotted/subscripted members.

        Members must be spelled the same way on both the write and read side or
        the taint never matches at the probe.
        """
        out = set()
        for n in ast.walk(node):
            if isinstance(n, ast.Name):
                out.add(n.id)
            elif isinstance(n, (ast.Attribute, ast.Subscript)):
                d = cls._dotted(n)
                if d:
                    out.add(d)
        return out

    @classmethod
    def _target_names(cls, t):
        out = []
        if isinstance(t, ast.Name):
            out.append(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                out.extend(cls._target_names(e))
        elif isinstance(t, ast.Starred):
            out.extend(cls._target_names(t.value))
        elif isinstance(t, (ast.Attribute, ast.Subscript)):
            # `self.safe = _sanitize_filename(s)` / `d['safe'] = ...` bound
            # nothing before, so the taint vanished. Key it on the MEMBER, not
            # the base object.
            #
            # The first version of this fix tainted the base (`self`, `d`),
            # which poisoned every member of that object for the rest of the
            # scope: @shardul0701 showed `self.cfg_path` and `d['config']` then
            # flag on correct code. That 0-false-positive result only held
            # because all five read paths happen to be module-level functions
            # with no object state — the first class-based read path would have
            # tripped it, and this file's own SAFE_SHAPES docstring is the
            # argument against shipping that.
            dotted = cls._dotted(t)
            if dotted:
                out.append(dotted)
            # No `else`. It used to fall back to tainting the base name for a
            # computed key, but _dotted now spells those `d[*]`, so the branch
            # was only reachable for a chain not rooted in a Name -- g()['safe'],
            # (a or b)['x'] -- where the base walk lands on the same non-Name
            # root and contributes nothing. @shardul0701 enumerated it:
            # unreachable-with-effect, and its comment described a fallback that
            # no longer existed. Stale prose in a guard is the failure this file
            # is about, so it is deleted rather than reworded.
        return out

    @staticmethod
    def _record_write(written, identity, lineno):
        """Record that *identity* was written at *lineno*.

        LAST write wins, not the first: `setdefault` pinned the earliest line
        forever, so a write / re-taint / probe sequence stayed suppressed even
        though the probed path was never the one written.

        A computed slot (`d[*]`) is NEVER recorded. `_COMPUTED_KEY_RULE` answers
        the undecidable "is this the same slot" with "assume not" — but on the
        suppression side that default flips to HIDING findings, so a
        computed-slot write must not vouch for any probe.
        """
        if not identity or identity.endswith("[*]") or "[*]" in identity:
            return
        prev = written.get(identity)
        if prev is None or lineno > prev:
            written[identity] = lineno

    @staticmethod
    def _was_written(identity, tainted, written, aliases, probe_line):
        """True when *identity* holds a path this scope created above the probe.

        Three conditions, each closing a reproduced hole:
          * the write is above the probe (`<=`, so a write and its verification
            on ONE physical line still counts)
          * the write POSTDATES the taint that is being reported. Without this,
            write / rebind-to-a-new-bare-path / probe stayed suppressed even
            though the probed value was never written.
          * an alias counts: `q = p; df.to_parquet(q); exists(p)` writes the
            same file, and treating it as unwritten was a false positive on
            ordinary code.
        """
        names = {identity} | aliases.get(identity, set())
        taint_line = tainted.get(identity, 0)
        for nm in names:
            w = written.get(nm)
            if w is not None and taint_line <= w <= probe_line:
                return True
        return False

    @classmethod
    def _scope_nodes(cls, body):
        """A scope's own nodes, NOT descending into nested defs.

        Descending conflates same-named locals across functions — it made the
        resolver's `candidates` in csv_service collide with the warning block's
        `candidates` and produced a false positive on correct code.
        """
        out = []
        stack = [st for st in body if not isinstance(st, cls._NESTED)]
        while stack:
            node = stack.pop()
            out.append(node)
            for child in ast.iter_child_nodes(node):
                if not isinstance(child, cls._NESTED):
                    stack.append(child)
        # SOURCE ORDER matters: a safe binding rebound to a bare-sanitized
        # fallback must end up tainted, which is only well-defined if
        # assignments are processed in the order they are written.
        return sorted(out, key=lambda n: (getattr(n, "lineno", 0),
                                          getattr(n, "col_offset", 0)))

    @classmethod
    def _scopes(cls, tree):
        yield "<module>", cls._scope_nodes(tree.body)
        for f in ast.walk(tree):
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield f.name, cls._scope_nodes(f.body)
            # Class BODIES were scanned in no scope at all: ClassDef is in
            # _NESTED (so the module walk skips it) and only functions were
            # yielded, so a violation written at class-body level was invisible.
            elif isinstance(f, ast.ClassDef):
                yield f"class {f.name}", cls._scope_nodes(f.body)
            # A lambda body is in no scope either, so even a fully
            # self-contained violation inside one is invisible. Its body is an
            # expression, not a statement list.
            elif isinstance(f, ast.Lambda):
                yield "<lambda>", cls._scope_nodes([ast.Expr(value=f.body)])

    @classmethod
    def _tainting_functions(cls, tree, sanitizers=None, safe_names=None):
        """Functions returning a sanitizer-derived value — calling one taints.

        Fixpoint, so a chain (a calls b calls the sanitizer) resolves.
        """
        sanitizers = cls.SANITIZERS if sanitizers is None else sanitizers
        safe_names = cls.SAFE if safe_names is None else safe_names
        fns = {f.name: f for f in ast.walk(tree)
               if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
        tainting, changed = set(), True
        # `name = lambda ...: <bare path>` is a function for our purposes. It is
        # also how a SAFE helper gets shadowed — un-blessing the name is only
        # half the fix; without this the shadow is neither safe nor tainting,
        # so its callers were still clean.
        for n in ast.walk(tree):
            if not isinstance(n, ast.Assign) or not isinstance(n.value, ast.Lambda):
                continue
            body = n.value.body
            c = set(cls._calls(body))
            if (c & sanitizers) and not (c & safe_names):
                for t in n.targets:
                    tainting.update(cls._target_names(t))
        while changed:
            changed = False
            for name, f in fns.items():
                if name in tainting:
                    continue
                local = set()
                for _ in range(4):      # fixpoint, so append-accumulators settle
                    for node in ast.walk(f):
                        tgts, val = cls._assign_parts(node)
                        if val is None:
                            continue
                        c = set(cls._calls(val))
                        if c & safe_names:
                            continue
                        if (c & sanitizers) or (c & tainting) \
                                or (cls._names(val) & local):
                            for t in tgts:
                                local.update(cls._target_names(t))
                    # container mutation carries taint with no assignment node
                    for node in ast.walk(f):
                        if not (isinstance(node, ast.Call)
                                and isinstance(node.func, ast.Attribute)
                                and node.func.attr in {"append", "extend",
                                                       "insert", "add", "update"}):
                            continue
                        container = cls._dotted(node.func.value)
                        if not container:
                            continue
                        for arg in node.args:
                            ac = set(cls._calls(arg))
                            if ac & safe_names:
                                continue
                            if (ac & sanitizers) or (ac & tainting) \
                                    or (cls._names(arg) & local):
                                local.add(container)
                for node in ast.walk(f):
                    if isinstance(node, ast.Return) and node.value is not None:
                        c = set(cls._calls(node.value))
                        if c & safe_names:
                            continue
                        if (c & sanitizers) or (c & tainting) \
                                or (cls._names(node.value) & local):
                            tainting.add(name)
                            changed = True
                            break
        return tainting

    @staticmethod
    def _assign_parts(node):
        """(targets, value) for every binding form that can carry taint."""
        if isinstance(node, ast.Assign):
            return node.targets, node.value
        if isinstance(node, ast.AnnAssign) and node.value is not None:
            return [node.target], node.value
        if isinstance(node, ast.AugAssign):
            return [node.target], node.value
        if isinstance(node, ast.NamedExpr):
            return [node.target], node.value
        if isinstance(node, (ast.For, ast.AsyncFor)):
            # container -> loop variable: the csv_service idiom
            return [node.target], node.iter
        if isinstance(node, ast.comprehension):
            return [node.target], node.iter
        return [], None

    @classmethod
    def scan(cls, src):
        """[(scope, build_line, probe_line, var)] for each contract violation."""
        tree = ast.parse(src)
        out = []

        # `from os.path import exists as _e` renames the probe out of every
        # name set above; collect the local aliases so `_e(p)` still counts.
        probe_aliases = set()
        # Sanitizer aliases matter MORE than probe aliases: `_derive_read_paths`
        # matches on alias.name and ignores asname, so a module importing
        # `sanitize_symbol_for_filename as scrub` is listed as a covered read
        # path, the contract test scans it, and it passes on a live violation.
        # Coverage that reads as protection while protecting nothing is this
        # file's whole subject.
        sanitizers = set(cls.SANITIZERS)
        safe_names = set(cls.SAFE)
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom):
                for a in n.names:
                    if a.name in (cls.EXIST_ATTRS | cls.LISTING_FUNCS
                                  | cls.READ_FUNCS):
                        probe_aliases.add(a.asname or a.name)
                    if a.name in cls.SANITIZERS:
                        sanitizers.add(a.asname or a.name)
                    if a.name in cls.SAFE:
                        safe_names.add(a.asname or a.name)
        # `import helpers.filename_utils as fu` then
        # `scrub = fu.sanitize_symbol_for_filename` — the sanitizer bound via
        # an ATTRIBUTE, which the ImportFrom walk above cannot see.
        # FIXPOINT, because one extra hop defeated the single-pass version:
        # `scrub = fu.sanitize_symbol_for_filename` then `scrub2 = scrub`, and
        # `getattr(fu, "sanitize_symbol_for_filename")`.
        for _ in range(6):
            before = set(sanitizers)
            for n in ast.walk(tree):
                if not isinstance(n, ast.Assign):
                    continue
                v = n.value
                hit = False
                if isinstance(v, ast.Attribute) and v.attr in sanitizers:
                    hit = True
                elif isinstance(v, ast.Name) and v.id in sanitizers:
                    hit = True
                elif (isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                        and v.func.id == "getattr" and len(v.args) > 1
                        and isinstance(v.args[1], ast.Constant)
                        and v.args[1].value in sanitizers):
                    hit = True
                if hit:
                    for t in n.targets:
                        sanitizers.update(cls._target_names(t))
            if set(sanitizers) == before:
                break
        # A module that REBINDS a safe helper name shadows the real one, and
        # treating the local as safe launders every caller. Any binding form --
        # def, lambda, plain assignment -- not just FunctionDef. The genuine
        # helpers are imported by read paths, never defined in them.
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and n.name in safe_names:
                safe_names.discard(n.name)
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    for nm in cls._target_names(t):
                        safe_names.discard(nm)

        tainting_fns = cls._tainting_functions(tree, sanitizers, safe_names)

        for scope_name, stmts in cls._scopes(tree):
            tainted, safe = {}, set()

            # Names bound to a directory listing, so `n in files` counts as a
            # probe even when the listdir call happened on an earlier line.
            listing_vars = set()
            # Paths this scope WROTE, with the line it wrote them on. Probing a
            # path you just created is post-write verification, not a read of a
            # pre-existing corpus, so flagging it is a false positive on
            # correct code.
            written = {}
            # Pure aliases (`q = p`), symmetric: a write through either name
            # writes the same file.
            aliases = {}
            for node in stmts:
                tgts, val = cls._assign_parts(node)
                if val is None or not isinstance(node, ast.Assign):
                    continue
                src_id = cls._dotted(val)
                if not src_id or "[*]" in src_id:
                    continue
                for t in tgts:
                    for nm in cls._target_names(t):
                        aliases.setdefault(nm, set()).add(src_id)
                        aliases.setdefault(src_id, set()).add(nm)
            for node in stmts:
                tgts, val = cls._assign_parts(node)
                if val is not None and (set(cls._calls(val)) & cls.LISTING_FUNCS):
                    for t in tgts:
                        listing_vars.update(cls._target_names(t))
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)):
                    if node.func.attr in cls.PATH_ARG_WRITES:
                        # `df.to_parquet(p)` / `to_parquet(path=p)` -- the path
                        # is the first positional or a path keyword. ONLY that
                        # expression is written; other args are options.
                        targets = list(node.args[:1])
                        targets += [k.value for k in node.keywords
                                    if k.arg in ("path", "path_or_buf", "fname")]
                        for a in targets:
                            # EXACT identity only. Collecting every name INSIDE
                            # the expression meant writing `p + '.tmp'` (the
                            # atomic-rename idiom) or `join(backup_dir, p)`
                            # vouched for a probe of `p` itself — which is
                            # precisely a #345 pre-existence lookup. A
                            # suppression rule must never generalise.
                            cls._record_write(written, cls._dotted(a),
                                              node.lineno)
                    elif node.func.attr in cls.RECEIVER_WRITES:
                        cls._record_write(written,
                                          cls._dotted(node.func.value),
                                          node.lineno)
                # open(): as a builtin `open(p, 'w')` or as `Path.open('w')`,
                # with the mode positional OR keyword.
                is_builtin_open = (isinstance(node, ast.Call)
                                   and isinstance(node.func, ast.Name)
                                   and node.func.id == "open")
                is_path_open = (isinstance(node, ast.Call)
                                and isinstance(node.func, ast.Attribute)
                                and node.func.attr == "open")
                if is_builtin_open or is_path_open:
                    mode = None
                    margs = node.args[1:] if is_builtin_open else node.args[:1]
                    if margs:
                        mode = margs[0]
                    for k in node.keywords:
                        if k.arg == "mode":
                            mode = k.value
                    if isinstance(mode, ast.Constant) and \
                            isinstance(mode.value, str) and \
                            not mode.value.startswith("r"):
                        if is_builtin_open and node.args:
                            cls._record_write(written,
                                              cls._dotted(node.args[0]),
                                              node.lineno)
                        elif is_path_open:
                            cls._record_write(written,
                                              cls._dotted(node.func.value),
                                              node.lineno)

            _taint_memo = {}

            def taints(val):
                # Memoised: the structural recursion below is exponential on
                # nested ternaries otherwise (measured: 51s at depth 20).
                key = id(val)
                if key in _taint_memo:
                    return _taint_memo[key]
                _taint_memo[key] = False        # cycle guard
                _taint_memo[key] = _taints(val)
                return _taint_memo[key]

            def _taints(val):
                # WHICH ARM IS LIVE decides whether a safe call launders a bare
                # one. `safe or bare` is genuinely safe -- the bare arm is only
                # reached after the safe one proved nothing exists, which is
                # caching.py's shape. But `bare or safe` always yields the bare
                # path (a join() is never falsy) and `safe and bare` yields the
                # bare path whenever resolve succeeds. Treating any SAFE call
                # anywhere as blessing was direction-blind.
                if isinstance(val, ast.BoolOp):
                    if isinstance(val.op, ast.Or):
                        return taints(val.values[0])
                    return taints(val.values[-1])
                # A ternary picks an arm, so either arm tainting taints.
                if isinstance(val, ast.IfExp):
                    return taints(val.body) or taints(val.orelse)
                # A tuple value assigned to a tuple target is element-wise; one
                # safe element used to bless every name in the target.
                if isinstance(val, ast.Tuple):
                    return any(taints(e) for e in val.elts)
                # A ternary anywhere OUTSIDE a safe call taints if either arm
                # does — `str(bare if c else safe)` is the bare path wrapped.
                # But do NOT descend into a safe call's ARGUMENTS: there the
                # value is the resolver's result, a ternary among its args says
                # nothing about it, and descending false-flagged correct code.
                # `val` may itself BE the safe call, in which case there is
                # nothing outside it to inspect.
                if isinstance(val, ast.Call):
                    _fn = val.func
                    _nm = (_fn.attr if isinstance(_fn, ast.Attribute)
                           else _fn.id if isinstance(_fn, ast.Name) else "")
                    if _nm in safe_names:
                        return False
                stack, seen = [val], set()
                while stack:
                    nd = stack.pop()
                    if id(nd) in seen:
                        continue
                    seen.add(id(nd))
                    if isinstance(nd, ast.IfExp):
                        if taints(nd.body) or taints(nd.orelse):
                            return True
                    for ch in ast.iter_child_nodes(nd):
                        if isinstance(ch, ast.Call):
                            fn = ch.func
                            nm = (fn.attr if isinstance(fn, ast.Attribute)
                                  else fn.id if isinstance(fn, ast.Name) else "")
                            if nm in safe_names:
                                continue
                        stack.append(ch)
                c = set(cls._calls(val))
                if c & safe_names:
                    return False
                # A sanitizer passed as a VALUE rather than called —
                # `list(map(_sanitize_filename, syms))` — still produces
                # sanitized names.
                return bool((c & sanitizers) or (c & tainting_fns)
                            or (cls._names(val) & sanitizers)
                            or (cls._names(val) & set(tainted)))

            for _ in range(6):          # fixpoint: loop-carried bindings settle
                before = (dict(tainted), set(safe))
                # The memo MUST be cleared each round. taints() reads `tainted`,
                # which grows across rounds, so a False cached before a name
                # became tainted would stick — it silently un-caught the
                # comprehension and csv-service-as-a-method shapes until the
                # suite failed on them.
                _taint_memo.clear()
                # `acc.append(x)` / `acc.extend([...])` -- container mutation
                # carries taint without any assignment node. Missing this is
                # what let a mutated csv_service (which accumulates into a list
                # via append) slip past the scanner in my own mutation run.
                for node in stmts:
                    if not (isinstance(node, ast.Call)
                            and isinstance(node.func, ast.Attribute)
                            and node.func.attr in {"append", "extend", "insert",
                                                   "add", "update"}):
                        continue
                    # The container may itself be a member: `self.paths.append`
                    # / `d['paths'].append`. Gating on ast.Name meant those
                    # never entered this loop at all, so the very function this
                    # handler was written for went invisible the moment it was
                    # rewritten as a method. @shardul0701. `_dotted` composes
                    # with the computed-key rule: `d[k].append` -> `d[*]`.
                    container = cls._dotted(node.func.value)
                    if not container:
                        continue
                    # NO `container in safe` short-circuit here. There used to
                    # be one; it read as the laundering rule and decided
                    # nothing. @shardul0701 A/B'd it across every battery and
                    # the suite -- byte-identical with and without. The actual
                    # clearing happens in the assignment loop below, which is
                    # where the fix belongs.
                    for arg in node.args:
                        if set(cls._calls(arg)) & safe_names:
                            continue
                        if (set(cls._calls(arg)) & sanitizers) \
                                or (set(cls._calls(arg)) & tainting_fns) \
                                or (cls._names(arg) & set(tainted)):
                            tainted.setdefault(container, node.lineno)
                for node in stmts:
                    tgts, val = cls._assign_parts(node)
                    if val is None:
                        continue
                    names = []
                    for t in tgts:
                        names.extend(cls._target_names(t))
                    if not names:
                        continue
                    # ast.comprehension has no lineno; fall back to its iter
                    lineno = getattr(node, "lineno", None) \
                        or getattr(val, "lineno", 0)
                    # TAINT IS EVALUATED FIRST. Testing safe-ness first
                    # short-circuited on any SAFE call anywhere in the value, so
                    # a ternary with a bare arm wrapped in ANYTHING --
                    # `(bare if c else safe) or 'x'`, `str(bare if c else safe)`
                    # -- was marked safe before taints() ever ran. taints()
                    # already treats a fully-safe ternary as untainted and an
                    # `or`-fallback as safe, so this ordering costs nothing and
                    # closes the wrapper hole at any depth.
                    if not taints(val) and (set(cls._calls(val)) & safe_names):
                        for nm in names:
                            safe.add(nm)
                            # ORDER-AWARE. An unconditional pop cleared taint
                            # that a container mutation had added on a LATER
                            # line, because the fixpoint re-runs this loop every
                            # round -- so `paths = [_resolve_existing(...)]`
                            # followed by `paths.append(<bare>)` laundered the
                            # append forever. That is the safe-primary /
                            # bare-fallback shape again, on a list instead of a
                            # rebinding. Only clear taint that originated at or
                            # above this assignment.
                            if tainted.get(nm, lineno) <= lineno:
                                tainted.pop(nm, None)
                    elif taints(val):
                        # LAST WRITE WINS, in source order. Safety used to be
                        # permanent within a scope, which made the
                        # safe-primary / bare-fallback rebinding invisible:
                        #     p = _resolve_existing(D, s)
                        #     p = os.path.join(D, _sanitize_filename(s))
                        #     if os.path.exists(p): ...
                        # caching.py is unaffected — its safe and fallback are
                        # ONE `or` expression, so the statement still calls a
                        # SAFE helper and stays safe.
                        for nm in names:
                            safe.discard(nm)
                            tainted[nm] = lineno
                if (dict(tainted), set(safe)) == before:
                    break

            probe_names = (cls.EXIST_ATTRS | cls.LISTING_FUNCS | cls.READ_FUNCS
                           | probe_aliases)

            # A probe passed as a VALUE rather than called:
            # `any(map(os.path.isfile, paths))`. This is the exact mirror of
            # the sanitizer-as-value case already handled in taints(), which
            # only ever had one side of the symmetry.
            for node in stmts:
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id in {"map", "filter"}):
                    continue
                if not node.args:
                    continue
                head = node.args[0]
                head_name = (head.attr if isinstance(head, ast.Attribute)
                             else head.id if isinstance(head, ast.Name) else "")
                if head_name not in probe_names:
                    continue
                for it in node.args[1:]:
                    if set(cls._calls(it)) & safe_names:
                        continue
                    if set(cls._calls(it)) & sanitizers:
                        out.append((scope_name, node.lineno, node.lineno,
                                    "<inline>"))
                        continue
                    refs = cls._names(it)
                    hit = refs & set(tainted)
                    # same post-write suppression as the main probe block —
                    # this block was added later and did not consult it, so
                    # `to_parquet(p)` then `all(map(isfile,[p]))` false-flagged
                    if hit and all(cls._was_written(r, tainted, written,
                                                    aliases, node.lineno)
                                   for r in hit):
                        continue
                    if hit and not (refs & safe):
                        v = sorted(hit)[0]
                        out.append((scope_name, tainted[v], node.lineno, v))
            for node in stmts:
                if not isinstance(node, ast.Call):
                    continue
                f = node.func
                fname = (f.attr if isinstance(f, ast.Attribute)
                         else f.id if isinstance(f, ast.Name) else "")
                if fname not in probe_names:
                    continue
                # `open(p, 'w')` is a WRITE, not a probe. Write paths are
                # supposed to build the guarded spelling from the bare
                # sanitizer -- that is the contract, not a violation of it --
                # so flagging them is a false positive on correct code, which
                # is what gets guards deleted.
                if fname == "open":
                    _is_builtin = isinstance(node.func, ast.Name)
                    _margs = node.args[1:] if _is_builtin else node.args[:1]
                    _mode = _margs[0] if _margs else None
                    for _k in node.keywords:
                        if _k.arg == "mode":
                            _mode = _k.value
                    if isinstance(_mode, ast.Constant) and \
                            isinstance(_mode.value, str) and \
                            not _mode.value.startswith("r"):
                        continue
                inner = set(cls._calls(node))
                if inner & safe_names:
                    continue
                # A tainting function called INLINE inside the probe. The
                # cross-function shape that was pinned assigned `p = build(s)`
                # first; inlining it walked straight through, because this block
                # never consulted tainting_fns even though it was computed.
                if (inner & sanitizers) or (inner & tainting_fns):
                    out.append((scope_name, node.lineno, node.lineno, "<inline>"))
                    continue
                refs = cls._names(node)
                hit = refs & set(tainted)
                # Post-write verification: this scope created THIS path above,
                # so probing it is not a read-path lookup.
                #
                # Suppress on the TAINTED identity only — never on any shared
                # name. Checking all refs meant a write that merely mentioned
                # `os`, or a `mkdir` on the directory the probe also names,
                # silenced an unrelated violation. Verified: that re-opened the
                # os.access regression on main() itself, since
                # `output_dir.mkdir()` sits above its skip check. A suppression
                # rule is the one place a bug HIDES findings rather than
                # inventing them, so it has to be exact.
                _recv = (cls._dotted(node.func.value)
                         if isinstance(node.func, ast.Attribute) else None)
                _checked = set(hit) | ({_recv} if _recv in tainted else set())
                if _checked and all(cls._was_written(r, tainted, written,
                                                     aliases, node.lineno)
                                    for r in _checked):
                    continue
                if hit and not (refs & safe):
                    v = sorted(hit)[0]
                    out.append((scope_name, tainted[v], node.lineno, v))

            # `name in os.listdir(d)` — the tainted value is on the LEFT of a
            # Compare, so the Call walk above cannot reach it.
            for node in stmts:
                if not isinstance(node, ast.Compare):
                    continue
                if not any(isinstance(o, (ast.In, ast.NotIn)) for o in node.ops):
                    continue
                rhs = set()
                for c in node.comparators:
                    rhs |= set(cls._calls(c))
                # The listing may have been computed earlier and bound to a
                # name -- `files = os.listdir(d)` ... `if n in files:` -- in
                # which case the comparator is a Name, not a call, and
                # requiring the call here misses it.
                rhs_names = set()
                for c in node.comparators:
                    rhs_names |= cls._names(c)
                if not ((rhs & cls.LISTING_FUNCS) or (rhs_names & listing_vars)):
                    continue
                left = node.left
                if set(cls._calls(left)) & safe_names:
                    continue
                if set(cls._calls(left)) & sanitizers:
                    out.append((scope_name, node.lineno, node.lineno, "<inline>"))
                    continue
                refs = cls._names(left)
                hit = refs & set(tainted)
                if hit and not (refs & safe):
                    v = sorted(hit)[0]
                    out.append((scope_name, tainted[v], node.lineno, v))

        return sorted(set(out), key=lambda r: (r[2], r[0]))

    # -- the contract ---------------------------------------------------------

    def test_no_derived_read_path_violates_the_contract(self):
        """Every module that imports a filename helper — currently 5.

        @shardul0701 corrected the previous docstring (and a claim I made on the
        PR): this scans the DERIVED read paths, not "every non-test module". The
        repo has 103 non-test modules; the other 98 import no sanitizer, so they
        cannot violate a contract about sanitizer-built paths — but the number
        that describes this test's coverage is 5, and an inflated one is the
        same "reads as protected" failure the contract is about.
        """
        root = self._root()
        offenders = []
        for rel in _derive_read_paths():
            src = open(os.path.join(root, rel), encoding="utf-8").read()
            for sc, bl, tl, v in self.scan(src):
                offenders.append(f"{rel} {sc}(): '{v}' built L{bl}, probed L{tl}")
        assert not offenders, (
            "a read path tests a bare-sanitized name for existence — a corpus "
            "written before the reserved-name guard will read as MISSING:\n  "
            + "\n  ".join(offenders))

    # -- the scanner must itself be able to fail ------------------------------
    #
    # Every shape below is a REAL defect that a previous revision of this
    # scanner passed clean. They are the regression suite for the guard.

    SHAPES = {
        "multiline":
            "def f(s):\n    x=_sanitize_filename(s)\n    p=os.path.join(D,x)\n"
            "    if os.path.exists(p): return 1\n",
        "walrus":
            "def f(s):\n"
            "    if os.path.exists(p:=os.path.join(D,_sanitize_filename(s))): return p\n",
        "list_literal_to_loop_var":
            "def f(s):\n    safe=_sanitize_filename(s)\n"
            "    c=[os.path.join(D,safe+'.csv'), os.path.join(D,safe.lower()+'.csv')]\n"
            "    for path in c:\n        if os.path.isfile(path): return path\n",
        "annotated_assign":
            "def f(s):\n    p: str = os.path.join(D,_sanitize_filename(s))\n"
            "    if os.path.exists(p): return 1\n",
        "pathlib_is_file":
            "def f(s,d):\n    p = d / (_sanitize_filename(s)+'.parquet')\n"
            "    if p.is_file(): return 1\n",
        "module_scope":
            "x=_sanitize_filename('CON')\np=os.path.join(D,x)\n"
            "if os.path.exists(p): pass\n",
        "tuple_assign":
            "def f(s):\n    a,p = 1, os.path.join(D,_sanitize_filename(s))\n"
            "    if os.path.exists(p): return 1\n",
        "glob":
            "def f(s):\n    p=os.path.join(D,_sanitize_filename(s)+'*')\n"
            "    if glob.glob(p): return 1\n",
        "cross_function":
            "def build(s):\n    return os.path.join(D,_sanitize_filename(s))\n"
            "def f(s):\n    p=build(s)\n    if os.path.exists(p): return 1\n",
        "listdir_membership":
            "def f(s):\n    n=_sanitize_filename(s)+'.parquet'\n"
            "    if n in os.listdir(D): return 1\n",
        "comprehension":
            "def f(s):\n    safe=_sanitize_filename(s)\n"
            "    return [p for p in [D+safe] if os.path.isfile(p)]\n",
        # container mutation carries taint with no assignment node -- this is
        # csv_service's real accumulator shape, and its absence let a mutated
        # csv_service slip past the scanner during verification.
        "append_accumulator":
            "def f(s):\n    acc=[]\n    acc.append(D+_sanitize_filename(s))\n"
            "    for path in acc:\n        if os.path.isfile(path): return path\n",
        "append_accumulator_cross_function":
            "def build(s):\n    acc=[]\n    acc.append(D+_sanitize_filename(s))\n"
            "    return acc\n"
            "def f(s):\n    for path in build(s):\n"
            "        if os.path.isfile(path): return path\n",
        # --- @shardul0701's second blind-spot sweep -------------------------
        "inline_tainting_call_in_probe":
            "def build(s):\n    return os.path.join(D,_sanitize_filename(s))\n"
            "def f(s):\n    if os.path.exists(build(s)): return 1\n",
        "safe_then_rebound_bare":
            "def f(s):\n    p=_resolve_existing(D,s)\n"
            "    p=os.path.join(D,_sanitize_filename(s))\n"
            "    if os.path.exists(p): return 1\n",
        "attribute_target":
            "class C:\n    def f(self,s):\n        self.safe=_sanitize_filename(s)\n"
            "        if os.path.exists(os.path.join(D,self.safe)): return 1\n",
        "dict_subscript_target":
            "def f(s):\n    d={}\n    d['safe']=_sanitize_filename(s)\n"
            "    if os.path.exists(os.path.join(D,d['safe'])): return 1\n",
        # the widest one: reading IS a probe
        "direct_read_no_exists_test":
            "def f(s):\n    p=os.path.join(D,_sanitize_filename(s)+'.parquet')\n"
            "    try:\n        return pd.read_parquet(p)\n"
            "    except FileNotFoundError:\n        return None\n",
        "open_probe":
            "def f(s):\n    p=os.path.join(D,_sanitize_filename(s))\n"
            "    try:\n        return open(p)\n    except OSError:\n        return None\n",
        "os_stat_probe":
            "def f(s):\n    p=os.path.join(D,_sanitize_filename(s))\n"
            "    try:\n        os.stat(p)\n    except OSError:\n        return None\n",
        "aliased_exists_import":
            "from os.path import exists as _e\n"
            "def f(s):\n    p=os.path.join(D,_sanitize_filename(s))\n"
            "    if _e(p): return 1\n",
        "map_over_sanitizer":
            "def f(syms):\n    ps=list(map(_sanitize_filename,syms))\n"
            "    for p in ps:\n        if os.path.isfile(D+p): return p\n",
        # --- member-keying battery ------------------------------------------
        "computed_key_target":
            "def f(s,d,k):\n    d[k]=_sanitize_filename(s)\n"
            "    return os.path.exists(d[k])\n",
        "computed_write_computed_other_key":
            "def f(s,d,k,j):\n    d[k]=_sanitize_filename(s)\n"
            "    return os.path.exists(d[j])\n",
        "nested_container_computed_key":
            "class C:\n    def f(self,s,k):\n        self.m[k]=_sanitize_filename(s)\n"
            "        return os.path.exists(self.m[k])\n",
        # The order-dependent counterpart of consequence 3: safe-then-bare IS
        # caught, because the bare write re-taints. Pinned so the asymmetry is
        # visible next to the xfail rather than only described in it.
        "safe_computed_write_then_bare_computed_write":
            "def f(s,d,k,j):\n    d[k]=_resolve_existing(D,s)\n"
            "    d[j]=os.path.join(D,_sanitize_filename(s))\n"
            "    if os.path.exists(d[j]): return 1\n",
        # Attributes do NOT collapse -- distinct names stay distinct
        # identities, so the laundering has no attribute-side equivalent.
        "attr_safe_and_bare_keep_distinct_identities":
            "class C:\n    def f(self,s):\n"
            "        self.bad=os.path.join(D,_sanitize_filename(s))\n"
            "        self.good=_resolve_existing(D,s)\n"
            "        if os.path.exists(self.bad): return 1\n",
        # --- container mutation on a MEMBER container -----------------------
        # Both handlers used to gate on ast.Name, so `self.paths.append(...)`
        # never entered them -- while `self.paths += [...]` did, because
        # AugAssign routes through _target_names. The asymmetry meant the very
        # function the handler was written for went invisible the moment it was
        # rewritten as a method. Both spellings and both container kinds pinned.
        "attr_append_then_probe":
            "class C:\n    def f(self,s):\n        self.paths=[]\n"
            "        self.paths.append(os.path.join(D,_sanitize_filename(s)))\n"
            "        for p in self.paths:\n"
            "            if os.path.isfile(p): return p\n",
        "attr_append_then_probe_direct":
            "class C:\n    def f(self,s):\n        self.paths=[]\n"
            "        self.paths.append(os.path.join(D,_sanitize_filename(s)))\n"
            "        if os.path.isfile(self.paths[0]): return 1\n",
        "subscript_append_then_probe":
            "def f(s,d):\n    d['paths']=[]\n"
            "    d['paths'].append(os.path.join(D,_sanitize_filename(s)))\n"
            "    for p in d['paths']:\n        if os.path.isfile(p): return p\n",
        # csv_service's own resolver, written as a method. THE point of the fix.
        "csv_service_resolver_as_a_method":
            "class C:\n    def find(self,symbol,csv_dir):\n        self.paths=[]\n"
            "        safe=_sanitize_filename(symbol)\n"
            "        self.paths.append(os.path.join(csv_dir,safe+'.csv'))\n"
            "        self.paths.append(os.path.join(csv_dir,safe.lower()+'.csv'))\n"
            "        for path in self.paths:\n"
            "            if os.path.isfile(path): return path\n",
        "attr_augassign_then_probe":
            "class C:\n    def f(self,s):\n        self.paths=[]\n"
            "        self.paths += [os.path.join(D,_sanitize_filename(s))]\n"
            "        for p in self.paths:\n            if os.path.isfile(p): return p\n",
        "subscript_augassign_then_probe":
            "def f(s,d):\n    d['paths']=[]\n"
            "    d['paths'] += [os.path.join(D,_sanitize_filename(s))]\n"
            "    for p in d['paths']:\n        if os.path.isfile(p): return p\n",
        # the whole verb set, not just append
        "attr_add_verb":
            "class C:\n    def f(self,s,d):\n        self.seen=set()\n"
            "        self.seen.add(os.path.join(d,_sanitize_filename(s)))\n"
            "        for p in self.seen:\n            if os.path.isfile(p): return p\n",
        "attr_extend_verb":
            "class C:\n    def f(self,s,d):\n        self.paths=[]\n"
            "        self.paths.extend([os.path.join(d,_sanitize_filename(s))])\n"
            "        for p in self.paths:\n            if os.path.isfile(p): return p\n",
        "attr_insert_verb":
            "class C:\n    def f(self,s,d):\n        self.paths=[]\n"
            "        self.paths.insert(0,os.path.join(d,_sanitize_filename(s)))\n"
            "        for p in self.paths:\n            if os.path.isfile(p): return p\n",
        # --- safe primary, bare fallback, on a LIST -------------------------
        # Item 4(b) again in a different spelling. An unconditional taint-pop
        # in the fixpoint's assignment loop cleared taint that the append had
        # added on a later line, every round -- so this laundered forever, and
        # order-independently, despite the comment claiming last-write-wins.
        "safe_list_then_bare_append":
            "def f(s,d):\n    paths=[_resolve_existing(d,s)]\n"
            "    paths.append(os.path.join(d,_sanitize_filename(s)+'.csv'))\n"
            "    for p in paths:\n        if os.path.isfile(p): return p\n",
        "safe_attr_list_then_bare_append":
            "class C:\n    def f(self,s,d):\n"
            "        self.paths=[_resolve_existing(d,s)]\n"
            "        self.paths.append(os.path.join(d,_sanitize_filename(s)+'.csv'))\n"
            "        for p in self.paths:\n"
            "            if os.path.isfile(p): return p\n",
        # --- final QA round -------------------------------------------------
        # A RENAMED sanitizer import. Nastier than the probe-alias case:
        # _derive_read_paths matches on alias.name and ignores asname, so the
        # module is listed as a covered read path, the contract test scans it,
        # and it passes on a live violation. Coverage that reads as protection.
        "sanitizer_import_alias":
            "from helpers.filename_utils import sanitize_symbol_for_filename as scrub\n"
            "def f(s,d):\n    p=os.path.join(d,scrub(s)+'.parquet')\n"
            "    if os.path.exists(p): return p\n",
        # An os.access() spelling of main()'s skip check reverted the #345 fix
        # with the whole suite green. The verb set is the backstop's entire
        # surface.
        "os_access_probe":
            "def f(s,d):\n    p=os.path.join(d,_sanitize_filename(s)+'.parquet')\n"
            "    if os.access(p, os.F_OK): return p\n",
        "lexists_probe":
            "def f(s,d):\n    p=os.path.join(d,_sanitize_filename(s)+'.parquet')\n"
            "    if os.path.lexists(p): return p\n",
        "getatime_probe":
            "def f(s,d):\n    p=os.path.join(d,_sanitize_filename(s)+'.parquet')\n"
            "    return os.path.getatime(p)\n",
        # listing bound to a name on an earlier line
        "precomputed_listdir_membership":
            "def f(s,d):\n    files=os.listdir(d)\n"
            "    n=_sanitize_filename(s)+'.parquet'\n"
            "    if n in files: return n\n",
        # --- second QA round ------------------------------------------------
        "os_walk_membership":
            "def f(s,d):\n    n=_sanitize_filename(s)+'.parquet'\n"
            "    for root,dirs,files in os.walk(d):\n"
            "        if n in files: return n\n",
        "iterdir_membership":
            "def f(s,d):\n    n=_sanitize_filename(s)+'.parquet'\n"
            "    names={p.name for p in d.iterdir()}\n"
            "    if n in names: return n\n",
        # the mirror of map(_sanitize_filename, ...) — the probe as a value
        "probe_as_value_map":
            "def f(s,d):\n    paths=[os.path.join(d,_sanitize_filename(s))]\n"
            "    if any(map(os.path.isfile, paths)): return 1\n",
        "probe_as_value_filter":
            "def f(s,d):\n    paths=[os.path.join(d,_sanitize_filename(s))]\n"
            "    return next(filter(os.path.isfile, paths), None)\n",
        # a TERNARY with a bare arm is not laundered by its safe arm, unlike
        # an `or`-fallback (see the SAFE shape caching_or_fallback_shape)
        "ternary_bare_arm":
            "def f(s,d,c):\n"
            "    p=os.path.join(d,_sanitize_filename(s)) if c else _resolve_existing(d,s)\n"
            "    if p and os.path.exists(p): return p\n",
        "class_body_scope":
            "class C:\n    NAME=_sanitize_filename('CON')+'.parquet'\n"
            "    P=os.path.join(D,NAME)\n"
            "    OK=os.path.exists(P)\n",
        "lambda_body":
            "f = lambda s: os.path.exists(os.path.join(D,_sanitize_filename(s)))\n",
        "member_aliased_into_plain_name":
            "class C:\n    def f(self,s):\n        self.safe=_sanitize_filename(s)\n"
            "        n=self.safe\n"
            "        if os.path.exists(os.path.join(D,n)): return 1\n",
        "member_in_fstring":
            "class C:\n    def f(self,s):\n        self.safe=_sanitize_filename(s)\n"
            "        if os.path.exists(f'{D}/{self.safe}.parquet'): return 1\n",
        "nested_attribute":
            "class C:\n    def f(self,s):\n        self.cfg.safe=_sanitize_filename(s)\n"
            "        if os.path.exists(os.path.join(D,self.cfg.safe)): return 1\n",
        "attr_via_read_func":
            "class C:\n    def f(self,s):\n        self.safe=_sanitize_filename(s)\n"
            "        return pd.read_parquet(os.path.join(D,self.safe))\n",
        "dictkey_via_read_func":
            "def f(s,d):\n    d['safe']=_sanitize_filename(s)\n"
            "    return pd.read_parquet(os.path.join(D,d['safe']))\n",
    }

    SAFE_SHAPES = {
        "resolve_existing":
            "def f(s):\n    p=_resolve_existing(D,s)\n"
            "    if p and os.path.exists(p): return 1\n",
        "candidates_loop_the_csv_service_head_shape":
            "def f(s):\n    c=[]\n    for safe in _filename_candidates(s):\n"
            "        c += [os.path.join(D,safe+'.csv')]\n"
            "    for path in c:\n        if os.path.isfile(path): return path\n",
        "unrelated_existence_test":
            "def f(d):\n"
            "    if os.path.exists(os.path.join(d,'config.yml')): return 1\n",
        "two_functions_reusing_one_local_name":
            # the false positive that scope-leaking produced on real code
            "def safe_one(s):\n    c=[]\n"
            "    for x in _filename_candidates(s):\n        c += [D+x]\n"
            "    for path in c:\n        if os.path.isfile(path): return path\n"
            "def unsafe_looking(s):\n    c=[_sanitize_filename(s)]\n"
            "    return ', '.join(c)\n",
        # --- @shardul0701's correct-code battery ----------------------------
        # The first two are the FALSE POSITIVES my base-name taint introduced.
        # The rest are the shapes most likely to annoy someone into deleting
        # the guard, which is the real way a guard dies.
        "unrelated_attr_after_tainted_attr":
            "class C:\n    def f(self,s):\n        self.safe=_sanitize_filename(s)\n"
            "        return os.path.exists(self.cfg_path)\n",
        "unrelated_dict_key_after_tainted_key":
            "def f(s,d):\n    d['safe']=_sanitize_filename(s)\n"
            "    return os.path.exists(d['config'])\n",
        "write_path_only_no_probe":
            "def f(s,d):\n    p=os.path.join(d,_sanitize_filename(s)+'.parquet')\n"
            "    df.to_parquet(p)\n",
        "resolve_then_read_the_resolved":
            "def f(s,d):\n    p=_resolve_existing(d,s)\n"
            "    return pd.read_parquet(p) if p else None\n",
        "candidates_loop_then_read":
            "def f(s,d):\n    for safe in _filename_candidates(s):\n"
            "        p=os.path.join(d,safe)\n"
            "        if os.path.isfile(p): return pd.read_parquet(p)\n",
        "unrelated_open_alongside_bare_name":
            "def f(s,d):\n    safe=_sanitize_filename(s)\n    log(safe)\n"
            "    return open(os.path.join(d,'config.yml'))\n",
        "safe_reassigned_from_safe":
            "def f(s,d):\n    p=_resolve_existing(d,s)\n"
            "    p=p or _resolve_existing(d,s.upper())\n"
            "    if p and os.path.exists(p): return p\n",
        "caching_or_fallback_shape":
            "def f(s,d):\n    fn=_sanitize_filename(s)+'.parquet'\n"
            "    fp=_resolve_existing(d,s) or os.path.join(d,fn)\n"
            "    if os.path.exists(fp): return fp\n",
        "log_bare_then_resolve":
            "def f(s,d):\n    logger.debug(_sanitize_filename(s))\n"
            "    return _resolve_existing(d,s)\n",
        "write_read_split_across_functions":
            "def w(s,d):\n    return os.path.join(d,_sanitize_filename(s))\n"
            "def r(d):\n    return pd.read_parquet(os.path.join(d,'fixed.parquet'))\n",
        # The false-positive class survived my first member-keying fix through
        # the computed-key fallback: `d[k] = ...` tainted the bare container,
        # so an unrelated CONSTANT-key read flagged. Both directions are now
        # pinned -- `computed_key_target` above must stay caught while this
        # stays clean.
        "computed_key_write_then_unrelated_const_read":
            "def f(s,d,k):\n    d[k]=_sanitize_filename(s)\n"
            "    return os.path.exists(d['config'])\n",
        "attr_write_no_probe":
            "class C:\n    def f(self,s):\n        self.safe=_sanitize_filename(s)\n"
            "        return self.safe\n",
        "resolve_into_attr_probe_other_attr":
            "class C:\n    def f(self,s):\n        self.p=_resolve_existing(D,s)\n"
            "        return os.path.exists(self.other)\n",
        # Why consequence 3 is not fixable by making a safe write non-clearing:
        # this correct code would then flag. The probe reads the SAFE slot.
        "bare_computed_write_then_safe_write_probe_the_safe_one":
            "def f(s,d,k,j):\n    d[j]=os.path.join(D,_sanitize_filename(s))\n"
            "    d[k]=_resolve_existing(D,s)\n"
            "    return os.path.exists(d[k]) if d[k] else None\n",
        "attr_probe_the_safe_one_alongside_a_bare_one":
            "class C:\n    def f(self,s):\n"
            "        self.bad=os.path.join(D,_sanitize_filename(s))\n"
            "        self.good=_resolve_existing(D,s)\n"
            "        if self.good and os.path.exists(self.good): return 1\n",
        # Member-container appends that are CORRECT must stay clean, or
        # widening the handler to members would have cost precision.
        "attr_append_resolve_existing":
            "class C:\n    def f(self,s):\n        self.paths=[]\n"
            "        self.paths.append(_resolve_existing(D,s))\n"
            "        for p in self.paths:\n"
            "            if p and os.path.isfile(p): return p\n",
        "attr_append_inside_candidates_loop":
            "class C:\n    def f(self,s,d):\n        self.paths=[]\n"
            "        for safe in _filename_candidates(s):\n"
            "            self.paths.append(os.path.join(d,safe+'.csv'))\n"
            "        for path in self.paths:\n"
            "            if os.path.isfile(path): return path\n",
        # The mirror of safe_list_then_bare_append, and it must stay clean:
        # the bare entries go with the DISCARDED list, so the probe can only
        # ever see resolved paths. Missing this is correct, and it is what
        # makes the order-aware pop a fix rather than a blunt re-taint.
        "bare_append_then_rebound_to_a_safe_list":
            "class C:\n    def f(self,s,d):\n        self.paths=[]\n"
            "        self.paths.append(os.path.join(d,_sanitize_filename(s)+'.csv'))\n"
            "        self.paths=[_resolve_existing(d,s)]\n"
            "        for p in self.paths:\n"
            "            if p and os.path.isfile(p): return p\n",
        # --- final QA round: WRITE paths are not violations -----------------
        # A write path is SUPPOSED to build the guarded spelling from the bare
        # sanitizer -- that is the contract, not a breach of it. Adding `open`
        # to READ_FUNCS made a plain write flag, and post-write verification
        # (write the file, then assert it exists) flagged too. Both are correct
        # code, and false positives are what get guards deleted.
        "open_for_write":
            "def f(s,d):\n"
            "    with open(os.path.join(d,_sanitize_filename(s)+'.csv'),'w') as fh:\n"
            "        fh.write('x')\n",
        "verify_own_write":
            "def f(s,d,df):\n    p=os.path.join(d,_sanitize_filename(s)+'.parquet')\n"
            "    df.to_parquet(p)\n    assert os.path.exists(p)\n",
        # --- second QA round: pathlib and keyword write spellings -----------
        # `written` collected names from positional args only, so every
        # receiver-based pathlib write flagged its own verification. This file
        # covers norgate_to_parquet.py, which is ALREADY pathlib — the first
        # write-then-verify refactor there would have tripped the contract
        # test on correct code.
        "pathlib_write_text_then_verify":
            "def f(s,d):\n    p=d/(_sanitize_filename(s)+'.parquet')\n"
            "    p.write_text('x')\n    assert p.exists()\n",
        "pathlib_touch_then_check":
            "def f(s,d):\n    p=d/(_sanitize_filename(s)+'.parquet')\n"
            "    p.touch()\n    if p.exists(): return p\n",
        "pathlib_open_for_write":
            "def f(s,d):\n    p=d/(_sanitize_filename(s)+'.csv')\n"
            "    with p.open('w') as fh:\n        fh.write('x')\n",
        "open_with_keyword_mode":
            "def f(s,d):\n"
            "    with open(os.path.join(d,_sanitize_filename(s)+'.csv'), mode='w') as fh:\n"
            "        fh.write('x')\n",
        "to_parquet_keyword_path_then_verify":
            "def f(s,d,df):\n    p=os.path.join(d,_sanitize_filename(s)+'.parquet')\n"
            "    df.to_parquet(path=p)\n    assert os.path.exists(p)\n",
        "unrelated_iterdir_listing":
            "def f(d):\n    return [p.name for p in d.iterdir()]\n",
    }

    @pytest.mark.parametrize("shape", sorted(SHAPES))
    def test_scanner_catches(self, shape):
        assert self.scan(self.SHAPES[shape]), (
            f"scanner is blind to the {shape!r} shape — this is a real defect "
            f"a previous revision passed clean")

    # -- ARCHITECTURAL LIMITS of a flow-insensitive, per-scope taint scan ----
    #
    # Found by the final QA round. Unlike the verb-set and alias gaps (fixed
    # above), these three need analysis this scanner does not do: a probing
    # function is the mirror of a tainting function, branch merging needs flow
    # sensitivity, and closures need scopes to nest rather than partition.
    # Each is a real defect that scans clean; pinned strict so implementing any
    # of them forces the record to be updated.

    @pytest.mark.xfail(reason=(
        "the probe crosses a function boundary. _tainting_functions models the "
        "BUILD side crossing a boundary; there is no matching notion of a "
        "probing function, so `check(build_bare(s))` is invisible"),
        strict=True)
    def test_probe_helper_function_is_a_known_miss(self):
        src = ("def check(p):\n    return os.path.isfile(p)\n"
               "def build_bare(s,d):\n"
               "    return os.path.join(d,_sanitize_filename(s))\n"
               "def f(s,d):\n    if check(build_bare(s,d)): return 1\n")
        assert self.scan(src)

    @pytest.mark.xfail(reason=(
        "branch merging. The taint pass is flow-INSENSITIVE with last-write-"
        "wins over source order, so a textually-later safe ELSE branch clears "
        "the bare IF branch's taint. Same laundering class as the order-"
        "dependent bug fixed earlier, reached through control flow instead"),
        strict=True)
    def test_branch_bare_then_else_safe_is_a_known_miss(self):
        src = ("def f(s,d,c):\n    if c:\n"
               "        p=os.path.join(d,_sanitize_filename(s))\n"
               "    else:\n        p=_resolve_existing(d,s)\n"
               "    if p and os.path.exists(p): return p\n")
        assert self.scan(src)

    @pytest.mark.xfail(reason=(
        "a module-level tainted constant probed INSIDE a function. The plain-"
        "name sibling of test_cross_method_attribute_is_a_known_miss, and it "
        "needs the same missing capability: seeding a scope with taint from an "
        "enclosing one. Declining it here for the same reason -- seeding "
        "carries its own false-positive risk (a same-named local that is "
        "safe) and belongs in one change with its own battery, not bolted on"),
        strict=True)
    def test_module_constant_probed_in_a_function_is_a_known_miss(self):
        src = ("NAME=_sanitize_filename('CON')+'.parquet'\n"
               "def f(d):\n"
               "    if os.path.exists(os.path.join(d,NAME)): return 1\n")
        assert self.scan(src)

    @pytest.mark.xfail(reason=(
        "closure. _scope_nodes deliberately does NOT descend into nested defs "
        "-- that partitioning is what removed the cross-function false "
        "positive on csv_service -- so a nested def probing an enclosing "
        "scope's variable sees no taint. Fixing it means scopes that nest for "
        "reads while staying separate for writes"),
        strict=True)
    def test_closure_probe_is_a_known_miss(self):
        src = ("def f(s,d):\n    p=os.path.join(d,_sanitize_filename(s))\n"
               "    def inner():\n        if os.path.exists(p): return p\n"
               "    return inner()\n")
        assert self.scan(src)

    @pytest.mark.parametrize("shape", sorted(SAFE_SHAPES))
    def test_scanner_does_not_false_positive(self, shape):
        assert not self.scan(self.SAFE_SHAPES[shape]), (
            f"false positive on {shape!r} — a guard that cries wolf on correct "
            f"code gets disabled by whoever it annoys")

    # -- KNOWN LIMITS, pinned so they cannot rot -----------------------------
    #
    # Both are real defects the scanner does NOT catch. Recorded as strict
    # xfails rather than prose: the moment either is implemented these flip to
    # failures and force the record to be updated deliberately. Prose in a
    # docstring would just quietly become false.

    @pytest.mark.xfail(reason=(
        "taint keys on the member (self.safe), which does not follow object "
        "aliases -- `q = o` makes o.safe and q.safe unrelated identities. This "
        "is the price of the precision that removed the poison-every-member "
        "false positives, and @shardul0701 and I both judge the trade worth "
        "it; recorded so it is a decision rather than a surprise"),
        strict=True)
    def test_object_alias_is_a_known_miss(self):
        src = ("def f(s,o):\n    o.safe=_sanitize_filename(s)\n    q=o\n"
               "    if os.path.exists(os.path.join(D,q.safe)): return 1\n")
        assert self.scan(src)

    @pytest.mark.xfail(reason=(
        "taint is per-function, so a write in __init__ never reaches a probe "
        "in a sibling method -- the most natural spelling of a class-based "
        "read path, and the shape the member-keying fix was justified by. "
        "PRE-EXISTING, not a regression from that fix. Closing it means "
        "seeding method scopes with attribute taint from sibling methods of "
        "the same ClassDef, which carries its own false-positive risk (one "
        "method resolving safely into self.p while another probes it) and so "
        "belongs in its own change"),
        strict=True)
    def test_cross_method_attribute_is_a_known_miss(self):
        src = ("class C:\n    def __init__(self,s):\n"
               "        self.safe=_sanitize_filename(s)\n"
               "    def read(self):\n"
               "        p=os.path.join(D,self.safe+'.parquet')\n"
               "        if os.path.exists(p): return 1\n")
        assert self.scan(src)

    # The three consequences of the computed-key collapse. All hang off
    # _COMPUTED_KEY_RULE above rather than re-deriving the argument three
    # times -- @shardul0701's point, after finding the third face himself.

    @pytest.mark.xfail(reason=(
        "consequence 1 -- const-key write, computed-key read. " + _COMPUTED_KEY_RULE),
        strict=True)
    def test_const_write_computed_read_is_a_known_miss(self):
        src = ("def f(s,d,k):\n    d['safe']=_sanitize_filename(s)\n"
               "    return os.path.exists(d[k])\n")
        assert self.scan(src)

    @pytest.mark.xfail(reason=(
        "consequence 2 -- computed-key write, const-key read. Structurally "
        "identical to the SAFE shape computed_key_write_then_unrelated_const_"
        "read; only the runtime value of k separates them. " + _COMPUTED_KEY_RULE),
        strict=True)
    def test_computed_write_const_read_is_a_known_miss(self):
        src = ("def f(s,d,k):\n    d[k]=_sanitize_filename(s)\n"
               "    return os.path.exists(d['safe'])\n")
        assert self.scan(src)

    @pytest.mark.xfail(reason=(
        "consequence 3 -- a SAFE computed write launders an earlier BARE "
        "computed write to a different key, because last-write-wins runs over "
        "one shared identity. Order-dependent: safe-then-bare IS caught (see "
        "SHAPES). PRE-EXISTING at the base-name level, not introduced by the "
        "collapse. " + _COMPUTED_KEY_RULE),
        strict=True)
    def test_safe_computed_write_launders_earlier_bare_write(self):
        src = ("def f(s,d,k,j):\n"
               "    d[j]=os.path.join(D,_sanitize_filename(s))\n"
               "    d[k]=_resolve_existing(D,s)\n"
               "    if os.path.exists(d[j]): return 1\n")
        assert self.scan(src)
