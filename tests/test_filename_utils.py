"""tests/test_filename_utils.py

Tests for helpers/filename_utils.sanitize_symbol_for_filename.
Covers: illegal character replacement, Windows reserved device names,
and common ticker symbol patterns.
"""

import ast
import os

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

        assert "MISSING" not in out, (
            "validator reported a symbol as missing from a corpus that has it "
            "under the legacy unguarded spelling:\n" + out
        )


class TestNoReadPathBuildsItsOwnFilename:
    """The structural backstop, rewritten as an **AST dataflow** scan.

    The previous version compared substrings on a single source line. It missed
    `helpers/caching.py` entirely -- name built at line 21, existence tested at
    line 29 -- which is both the more common shape in real code and the example
    the PR body led with. It also could not see a violation inside a function
    that merely *imported* a safe helper without calling it.

    This walks each function, tracks which locals derive from the bare
    sanitizer, and flags an existence test on any of them -- plus the inline
    one-liner form. It is a backstop only; the behavioural tests above are the
    real evidence.
    """

    READ_PATH_FILES = [
        os.path.join("helpers", "caching.py"),
        os.path.join("services", "parquet_service.py"),
        os.path.join("services", "csv_service.py"),
        os.path.join("scripts", "norgate_to_parquet.py"),
        os.path.join("scripts", "validate_norgate_export.py"),
    ]

    SANITIZERS = {"_sanitize_filename", "sanitize_symbol_for_filename"}
    SAFE = {"resolve_existing", "_resolve_existing", "filename_candidates"}
    EXIST = {"exists", "isfile"}

    @staticmethod
    def _root():
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @classmethod
    def _called_names(cls, node):
        for n in ast.walk(node):
            if isinstance(n, ast.Call):
                f = n.func
                if isinstance(f, ast.Name):
                    yield f.id
                elif isinstance(f, ast.Attribute):
                    yield f.attr

    @classmethod
    def scan(cls, src):
        """Return [(func, build_line, test_line, var)] for each violation."""
        out = []
        for fn in ast.walk(ast.parse(src)):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            tainted, safe = {}, set()
            for node in ast.walk(fn):
                if not isinstance(node, ast.Assign):
                    continue
                names = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if not names:
                    continue
                called = set(cls._called_names(node.value))
                refs = {n.id for n in ast.walk(node.value)
                        if isinstance(n, ast.Name)}
                if called & cls.SAFE:
                    for nm in names:
                        safe.add(nm)
                        tainted.pop(nm, None)
                elif (called & cls.SANITIZERS) or (refs & set(tainted)):
                    if not (refs & safe):
                        for nm in names:
                            tainted[nm] = node.lineno
            for node in ast.walk(fn):
                if not (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and node.func.attr in cls.EXIST):
                    continue
                inner = set(cls._called_names(node))
                if inner & cls.SAFE:
                    continue
                if inner & cls.SANITIZERS:
                    out.append((fn.name, node.lineno, node.lineno, "<inline>"))
                    continue
                refs = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
                hit = refs & set(tainted)
                if hit and not (refs & safe):
                    v = sorted(hit)[0]
                    out.append((fn.name, tainted[v], node.lineno, v))
        return out

    @pytest.mark.parametrize("relpath", READ_PATH_FILES)
    def test_existence_checks_do_not_use_the_bare_sanitizer(self, relpath):
        src = open(os.path.join(self._root(), relpath), encoding="utf-8").read()
        offenders = self.scan(src)
        assert not offenders, (
            f"{relpath} tests a bare-sanitized name for existence — a corpus "
            f"written before the reserved-name guard will read as MISSING:\n  "
            + "\n  ".join(
                f"{fn}(): '{v}' built line {bl}, existence tested line {tl}"
                for fn, bl, tl, v in offenders)
        )

    # -- the scanner must itself be able to fail -----------------------------

    MULTILINE_SHAPE = (
        "def get_cached_data(symbol):\n"
        "    safe = _sanitize_filename(symbol)\n"
        "    fn = f'{safe}_2024_D_1.parquet'\n"
        "    fp = os.path.join(CACHE_DIR, fn)\n"
        "    if os.path.exists(fp):\n"
        "        return 1\n"
    )
    INLINE_SHAPE = (
        "def validate(d, symbols):\n"
        "    return [s for s in symbols\n"
        "            if not (d / _sanitize_filename(s)).exists()]\n"
    )
    DEAD_IMPORT_SHAPE = (
        "from helpers.filename_utils import resolve_existing  # never called\n"
        + MULTILINE_SHAPE
    )
    SAFE_SHAPE = (
        "def get_cached_data(symbol):\n"
        "    fp = _resolve_existing(CACHE_DIR, symbol)\n"
        "    if fp and os.path.exists(fp):\n"
        "        return 1\n"
    )

    def test_scanner_catches_the_multiline_shape(self):
        """The shape the previous same-line guard MISSED, and the one #345
        actually took in `caching.py`."""
        assert self.scan(self.MULTILINE_SHAPE)

    def test_scanner_catches_the_inline_shape(self):
        assert self.scan(self.INLINE_SHAPE)

    def test_scanner_is_not_fooled_by_a_dead_import(self):
        """The previous whole-file substring guard passed on exactly this."""
        assert self.scan(self.DEAD_IMPORT_SHAPE)

    def test_scanner_clears_the_safe_shape(self):
        """No false positive, or the guard gets disabled by whoever it annoys."""
        assert not self.scan(self.SAFE_SHAPE)
