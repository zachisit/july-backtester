# tests/test_gh_post.py
"""Tests for scripts/gh_post.py.

The tool's value is entirely in `verify()` - the round-trip check that catches a
mangled comment regardless of WHY it was mangled. These tests pin that, the
preflight, and the environment failures a remote contributor hits.

A prior version of this suite tested the two historical failure stories well and
left the MECHANICS unpinned: an adversarial pass applied five mutations to
`normalise`/`verify`/the preflight and all five survived. The mutation cases
below exist to close that.

No network. Every test drives pure functions or patched subprocess calls.
"""

import ast
import json
import logging  # noqa: F401  (kept for parity with sibling suites)
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gh_post  # noqa: E402


class TestNormaliseIsVerbatim:
    """`normalise` is the identity, and that is an EMPIRICAL result.

    An earlier version stripped trailing whitespace and folded CRLF, justified
    by "GitHub does that anyway". Nobody had checked. Probing the live API -
    post, read back, byte-compare, delete - showed the body is stored verbatim
    on every axis tried. So each allowance protected nothing and opened a
    false-negative hole.
    """

    @pytest.mark.parametrize("text", [
        "line with two spaces  \nnext",         # markdown hard break
        "```diff\n-foo   \n+bar\n```",          # trailing WS inside a fence
        "a\r\nb",                               # CRLF
        "a\rb",                                 # lone CR
        "\n\nbody\n\n",                         # leading/trailing newlines
        "nbsp\u00a0zwsp\u200b emoji \U0001f600",
        "\ttab-indented first line",
    ])
    def test_content_is_not_altered(self, text):
        assert gh_post.normalise(text) == text

    def test_trailing_whitespace_damage_is_now_visible(self):
        """The concrete hole the old normalisation created: a diff whose context
        lines lost trailing spaces no longer applies, and it verified clean."""
        sent = "```diff\n-foo   \n+bar\n```"
        landed = "```diff\n-foo\n+bar\n```"
        assert gh_post.normalise(sent) != gh_post.normalise(landed)

    def test_hard_break_damage_is_now_visible(self):
        assert gh_post.normalise("one  \ntwo") != gh_post.normalise("one\ntwo")


class TestVerify:
    """THE invariant: identical content passes, anything else fails - and the
    failure is reported, never swallowed."""

    def test_identical_content_passes(self, capsys):
        assert gh_post.verify("hello", "hello", "http://x") == 0
        assert "verified" in capsys.readouterr().out

    def test_backtick_substitution_damage_is_caught(self, capsys):
        """Failure mode 1: the shell ate a backticked path before gh saw it."""
        sent = "check `helpers/rolling.py` for the fix"
        landed = "check  for the fix"
        assert gh_post.verify(sent, landed, "http://x") == gh_post.MISMATCH_EXIT
        assert "MISMATCH" in capsys.readouterr().err

    def test_literal_at_path_damage_is_caught(self, capsys):
        """Failure mode 2: `-f body=@path` posted the path, not the file."""
        sent = "Correcting my earlier comment. The real analysis is..."
        landed = "@C:/Users/shard/AppData/Local/Temp/gh_comment_106.md"
        assert gh_post.verify(sent, landed, "http://x") == gh_post.MISMATCH_EXIT
        assert "MISMATCH" in capsys.readouterr().err

    # --- mutation cases: each of these survived the previous suite ---

    def test_appended_content_is_caught(self):
        """Mutation M2 turned `==` into `in`, so anything APPENDED to the posted
        body verified clean - a comment with injected trailing content."""
        sent = "the real body"
        assert gh_post.verify(sent, sent + "\n\nspam appended", "http://x") == \
            gh_post.MISMATCH_EXIT

    def test_prefixed_content_is_caught(self):
        sent = "the real body"
        assert gh_post.verify("spam\n" + sent, sent, "http://x") == \
            gh_post.MISMATCH_EXIT

    def test_internal_spacing_damage_is_caught(self):
        """Mutation M3 dropped the `$` anchor, hiding ALL internal spacing loss."""
        assert gh_post.verify("a b", "ab", "http://x") == gh_post.MISMATCH_EXIT

    def test_first_line_indentation_damage_is_caught(self):
        """Mutation M1 used .strip() instead of .strip('\\n')."""
        assert gh_post.verify("    indented", "indented", "http://x") == \
            gh_post.MISMATCH_EXIT

    def test_lone_cr_is_not_silently_folded(self):
        assert gh_post.verify("a\rb", "a\nb", "http://x") == \
            gh_post.MISMATCH_EXIT

    def test_truncation_is_caught(self):
        assert gh_post.verify("a" * 500, "a" * 400, "http://x") == \
            gh_post.MISMATCH_EXIT

    def test_empty_landed_is_caught(self):
        assert gh_post.verify("real content", "", "http://x") == \
            gh_post.MISMATCH_EXIT

    def test_mismatch_prints_url_so_it_can_be_fixed(self, capsys):
        gh_post.verify("x", "y", "http://github.test/c/1")
        assert "http://github.test/c/1" in capsys.readouterr().err

    def test_mismatch_prints_a_diff(self, capsys):
        gh_post.verify("line one\nline two", "line one", "http://x")
        err = capsys.readouterr().err
        assert "what you wrote" in err and "what landed" in err


class TestReadSource:

    def test_reads_a_file(self, tmp_path):
        f = tmp_path / "b.md"
        f.write_text("body text", encoding="utf-8")
        assert gh_post.read_source(str(f)) == "body text"

    @pytest.mark.parametrize("raw", [
        "@C:/Users/shard/AppData/Local/Temp/gh_comment_106.md",
        "@C:/Users/shard/AppData/Local/Temp/gh_comment_106.md\n",   # every editor
        "  @/tmp/body.md  \n",
        "@../relative/path.md\n",
    ])
    def test_rejects_bare_at_path(self, tmp_path, raw):
        """Mutation M6 checked the UNSTRIPPED body, so the trailing-newline form -
        which is what every editor and heredoc produces - slipped straight past."""
        f = tmp_path / "b.md"
        f.write_text(raw, encoding="utf-8")
        with pytest.raises(SystemExit) as e:
            gh_post.read_source(str(f))
        assert e.value.code == 1

    @pytest.mark.parametrize("prose", [
        "@shardul0701 LGTM, merging.",            # one line, no newline
        "@shardul0701 - thanks for the review.\n\nDetails follow.",
        "@Suriya-002 see #302",
    ])
    def test_at_mention_prose_is_not_blocked(self, tmp_path, prose):
        """A false alarm here teaches people to distrust the tool. A real @path
        has no whitespace; an @mention reply does."""
        f = tmp_path / "b.md"
        f.write_text(prose, encoding="utf-8")
        assert gh_post.read_source(str(f)) == prose

    @pytest.mark.parametrize("ping", [
        "@zachisit",                    # "who owns this?" - a whole valid comment
        "@shardul0701\n",
        "@zachisit/reviewers",          # team mention, GitHub's own syntax
        "@Suriya-002",
    ])
    def test_a_bare_handle_is_not_a_path(self, tmp_path, ping):
        """`@\\S+\\Z` refused these: a one-word ping IS a real comment people
        post, and a team mention has no spaces either. The discriminator is not
        "contains whitespace", it is "looks like a path" - a leading separator,
        or a drive letter / backslash / extension dot. GitHub handles and team
        names permit none of those, so the two sets do not overlap."""
        f = tmp_path / "b.md"
        f.write_text(ping, encoding="utf-8")
        assert gh_post.read_source(str(f)) == ping

    def test_rejects_empty_body(self, tmp_path):
        f = tmp_path / "b.md"
        f.write_text("   \n\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            gh_post.read_source(str(f))

    def test_rejects_missing_file(self):
        with pytest.raises(SystemExit):
            gh_post.read_source("/nonexistent/nope.md")


class TestNoInlineBodyOption:
    """Failure mode 1 is removed structurally: no flag accepts body text as a
    shell argument, so it cannot be shell-substituted."""

    @pytest.mark.parametrize("cmd", ["comment", "review", "create", "edit-body"])
    def test_no_body_flag_exists(self, cmd):
        parser = gh_post.build_parser()
        argv = [cmd, "--repo", "o/r", "--file", "x.md"]
        argv += ["--title", "t"] if cmd == "create" else ["--number", "1"]
        args = parser.parse_args(argv)
        assert not hasattr(args, "body")
        assert args.file == "x.md"

    @pytest.mark.parametrize("cmd", ["comment", "create", "edit-body"])
    def test_file_is_required(self, cmd):
        argv = [cmd, "--repo", "o/r"]
        argv += ["--title", "t"] if cmd == "create" else ["--number", "1"]
        with pytest.raises(SystemExit):
            gh_post.build_parser().parse_args(argv)

    def test_review_file_is_optional_for_bodyless_approve(self):
        """A bare approve is the commonest review. Refusing it would push people
        back to raw `gh pr review`, i.e. around the rule this enforces."""
        a = gh_post.build_parser().parse_args(
            ["review", "--repo", "o/r", "--number", "1", "--event", "APPROVE"])
        assert a.file is None


class TestTempFileHygiene:

    def test_temp_file_is_removed(self):
        """delete=False is required for Windows, so cleanup must be explicit -
        otherwise every invocation leaves a draft body in $TMPDIR forever."""
        with gh_post._TmpBody("draft body") as path:
            assert os.path.exists(path)
            assert open(path, encoding="utf-8").read() == "draft body"
        assert not os.path.exists(path)

    def test_temp_file_is_removed_even_on_exception(self):
        try:
            with gh_post._TmpBody("draft") as path:
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert not os.path.exists(path)

    @pytest.mark.skipif(os.name == "nt", reason=(
        "POSIX mode bits do not exist on Windows: os.chmod only toggles the "
        "read-only flag and os.stat always reports 0o666, so this assertion is "
        "unconditionally false there. Confinement on Windows comes from the ACL "
        "on the per-user %LOCALAPPDATA%\\Temp, which st_mode cannot see."))
    def test_temp_file_is_not_world_readable(self):
        """Note this passes by INHERITANCE, not by intent: _TmpBody never calls
        chmod. NamedTemporaryFile -> mkstemp opens O_CREAT|O_EXCL with mode 0600
        on POSIX. Worth knowing if the implementation ever stops using mkstemp."""
        with gh_post._TmpBody("secret draft") as path:
            assert os.stat(path).st_mode & 0o077 == 0

    def test_content_is_written_verbatim(self):
        """newline='' - no translation. A body with CRLF must reach gh as CRLF,
        or the round-trip comparison is against something we never sent."""
        body = "a\r\nb\n"
        with gh_post._TmpBody(body) as path:
            assert open(path, encoding="utf-8", newline="").read() == body


class TestGhOutputIsDecodedAsUtf8:
    """`text=True` alone decodes the child's stdout with
    locale.getpreferredencoding(), which is **cp1252 on Windows**.

    gh always emits UTF-8, so on Windows the read-back of a comment containing
    an emoji or an em dash comes back as mojibake and `verify()` reports
    MISMATCH on a comment that posted perfectly. Measured against the live API:
    54 of the 100 most recent comment bodies in this repo contain characters
    that do not exist in cp1252. Some UTF-8 byte sequences land on cp1252's
    undefined bytes (0x81/0x8D/0x8F/0x90/0x9D) and raise UnicodeDecodeError
    instead, which escapes `except GhError` in cmd_comment as a raw traceback.

    Neither shows up in a mocked suite: every other test here patches `gh` or
    drives pure functions, so nothing exercises the decode. The unicode case in
    TestNormaliseIsVerbatim asserts emoji safety one layer above where emoji
    actually break.
    """

    def test_gh_pins_utf8_rather_than_the_locale_codepage(self, monkeypatch):
        seen = {}

        class R:
            returncode = 0
            stdout = "ok"
            stderr = ""

        def fake(cmd, **kw):
            seen.update(kw)
            return R()

        monkeypatch.setattr(gh_post.subprocess, "run", fake)
        gh_post.gh("api", "user")
        assert seen.get("encoding") == "utf-8", (
            "gh() must pin encoding='utf-8'; text=True alone uses the locale "
            "codepage and mangles non-latin-1 comment bodies on Windows")

    def test_real_utf8_child_process_round_trips(self, monkeypatch):
        """Not a mock: a real child process writing real UTF-8 bytes, which is
        what `gh` is. Fails on Windows without the explicit encoding."""
        real_run = gh_post.subprocess.run
        payload = "### ✅ Milestone 1 — Complete \U0001f600"

        def fake(cmd, **kw):
            return real_run(
                [sys.executable, "-c",
                 "import sys;sys.stdout.buffer.write("
                 f"{payload.encode('utf-8')!r})"], **kw)

        monkeypatch.setattr(gh_post.subprocess, "run", fake)
        assert gh_post.gh("api", "whatever") == payload

    def test_fetch_comment_body_survives_an_emoji_body(self, monkeypatch):
        """The end-to-end shape of the live failure: a real comment body with
        an emoji and an em dash must come back identical, not as mojibake.

        ensure_ascii=False is load-bearing. The first draft of this test used
        the json.dumps default, which escapes non-ASCII to \\uXXXX - so the
        bytes on the wire were pure ASCII, cp1252 decoded them identically, and
        the test SURVIVED its own mutation. gh does not escape: it returns the
        API's raw UTF-8. Ask for the bytes that actually break.
        """
        body = "### ✅ Milestone 1 — Complete"
        real_run = gh_post.subprocess.run

        def fake(cmd, **kw):
            doc = json.dumps({"body": body},
                             ensure_ascii=False).encode("utf-8")
            return real_run(
                [sys.executable, "-c",
                 f"import sys;sys.stdout.buffer.write({doc!r})"], **kw)

        monkeypatch.setattr(gh_post.subprocess, "run", fake)
        assert gh_post.fetch_comment_body("o/r", "1") == body


class TestPostedButUnverified:
    """Posted-but-unverifiable must NOT exit 1. Exit 1 is the tool's code for
    'nothing was posted', and a user who sees it will re-run the command -
    producing a duplicate on top of the comment that already landed."""

    def test_returns_mismatch_exit_not_one(self, capsys):
        assert gh_post.unverified("http://x/1", "read-back failed") == \
            gh_post.MISMATCH_EXIT

    def test_says_the_content_is_live(self, capsys):
        gh_post.unverified("http://x/1", "read-back failed")
        err = capsys.readouterr().err
        assert "http://x/1" in err
        assert "IS live" in err
        assert "Do NOT just re-run" in err

    def test_readback_failure_after_successful_post_reports_the_url(
            self, monkeypatch, tmp_path, capsys):
        f = tmp_path / "b.md"
        f.write_text("hello", encoding="utf-8")
        url = "https://x/i/1#issuecomment-99"
        monkeypatch.setattr(gh_post, "gh", lambda *a: url)

        def boom(repo, cid):
            raise gh_post.GhError("connection reset")
        monkeypatch.setattr(gh_post, "fetch_comment_body", boom)

        rc = gh_post.main(["comment", "--repo", "o/r", "--number", "1",
                           "--file", str(f)])
        assert rc == gh_post.MISMATCH_EXIT
        assert url in capsys.readouterr().err


class TestVerifiedPostFlow:

    def _patch(self, monkeypatch, landed, url="https://x/i/1#issuecomment-99"):
        monkeypatch.setattr(gh_post, "gh", lambda *a: url)
        monkeypatch.setattr(gh_post, "fetch_comment_body", lambda r, c: landed)

    def test_matching_post_exits_zero(self, monkeypatch, tmp_path):
        f = tmp_path / "b.md"
        f.write_text("hello world", encoding="utf-8")
        self._patch(monkeypatch, "hello world")
        assert gh_post.main(["comment", "--repo", "o/r", "--number", "1",
                             "--file", str(f)]) == 0

    def test_mangled_post_exits_two(self, monkeypatch, tmp_path):
        f = tmp_path / "b.md"
        f.write_text("hello `world`", encoding="utf-8")
        self._patch(monkeypatch, "hello ")
        assert gh_post.main(["comment", "--repo", "o/r", "--number", "1",
                             "--file", str(f)]) == gh_post.MISMATCH_EXIT

    def test_unparseable_url_is_not_reported_as_success(self, monkeypatch,
                                                        tmp_path):
        f = tmp_path / "b.md"
        f.write_text("hello", encoding="utf-8")
        self._patch(monkeypatch, "hello", url="https://example.com/no-id-here")
        assert gh_post.main(["comment", "--repo", "o/r", "--number", "1",
                             "--file", str(f)]) == gh_post.MISMATCH_EXIT


class TestReviewIdentifiedByAuthorNotPosition:
    """`gh api` returns ONE PAGE OF 30 by default and this endpoint is ascending,
    so `reviews[-1]` is the 30th-OLDEST review on a busy PR - never the one just
    submitted. Under 30, a concurrent reviewer makes it someone else's. Either
    way the tool reports a false MISMATCH, training people to ignore exit 2."""

    def _run(self, monkeypatch, tmp_path, reviews, body="my review"):
        f = tmp_path / "b.md"
        f.write_text(body, encoding="utf-8")
        calls = []

        def fake_gh(*a):
            calls.append(a)
            if a[:2] == ("api", "user"):
                return '{"login": "zachisit"}'
            if a[0] == "api":
                import json as _j
                return _j.dumps(reviews)
            return ""
        monkeypatch.setattr(gh_post, "gh", fake_gh)
        rc = gh_post.main(["review", "--repo", "o/r", "--number", "1",
                           "--file", str(f)])
        return rc, calls

    def test_picks_own_review_not_the_last_in_the_list(self, monkeypatch,
                                                       tmp_path):
        reviews = [
            {"user": {"login": "zachisit"}, "body": "my review",
             "submitted_at": "2026-08-26T10:00:00Z", "html_url": "u1"},
            {"user": {"login": "shardul0701"}, "body": "someone else's",
             "submitted_at": "2026-08-26T11:00:00Z", "html_url": "u2"},
        ]
        rc, _ = self._run(monkeypatch, tmp_path, reviews)
        assert rc == 0   # reviews[-1] would have compared against u2 and failed

    def test_picks_the_newest_of_several_own_reviews(self, monkeypatch,
                                                     tmp_path):
        reviews = [
            {"user": {"login": "zachisit"}, "body": "an older one",
             "submitted_at": "2026-08-20T10:00:00Z", "html_url": "u1"},
            {"user": {"login": "zachisit"}, "body": "my review",
             "submitted_at": "2026-08-26T10:00:00Z", "html_url": "u2"},
        ]
        rc, _ = self._run(monkeypatch, tmp_path, reviews)
        assert rc == 0

    def test_selects_by_timestamp_not_list_position(self, monkeypatch,
                                                    tmp_path):
        """Guards the second half of the fix. Filtering by author alone is not
        enough: if the API ever returns own-reviews out of order, `reviews[-1]`
        picks the wrong one. Ordering here is deliberately NOT ascending, so a
        positional implementation compares against the stale review and fails."""
        reviews = [
            {"user": {"login": "zachisit"}, "body": "my review",
             "submitted_at": "2026-08-26T12:00:00Z", "html_url": "new"},
            {"user": {"login": "zachisit"}, "body": "a stale earlier one",
             "submitted_at": "2026-08-20T09:00:00Z", "html_url": "old"},
        ]
        rc, _ = self._run(monkeypatch, tmp_path, reviews)
        assert rc == 0

    def test_requests_pagination(self, monkeypatch, tmp_path):
        """Without --paginate the default page of 30 silently truncates."""
        reviews = [{"user": {"login": "zachisit"}, "body": "my review",
                    "submitted_at": "2026-08-26T10:00:00Z", "html_url": "u"}]
        _, calls = self._run(monkeypatch, tmp_path, reviews)
        review_calls = [c for c in calls if c[0] == "api" and "reviews" in c[-1]]
        assert review_calls, "no reviews API call made"
        assert any("--paginate" in c for c in review_calls)

    def test_no_own_review_is_unverified_not_success(self, monkeypatch,
                                                     tmp_path):
        reviews = [{"user": {"login": "someone_else"}, "body": "x",
                    "submitted_at": "2026-08-26T10:00:00Z", "html_url": "u"}]
        rc, _ = self._run(monkeypatch, tmp_path, reviews)
        assert rc == gh_post.MISMATCH_EXIT


class TestPortabilityForContributorsWithoutLocalTooling:
    """This repo's own conventions (the `rtk` prefix, a specific venv) are one
    machine's setup. Most contributors are remote. A tool that dies with a raw
    traceback on their machine reads as "broken" and sends them straight back to
    the unsafe `gh --body` invocation - the exact thing it prevents."""

    def test_no_rtk_dependency_anywhere_in_the_module(self):
        src = open(gh_post.__file__, encoding="utf-8").read()
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        assert "rtk " not in code

    def test_missing_gh_binary_gives_install_instructions(self, monkeypatch):
        def boom(*a, **k):
            raise FileNotFoundError(2, "No such file or directory", "gh")
        monkeypatch.setattr(gh_post.subprocess, "run", boom)
        with pytest.raises(gh_post.GhError) as e:
            gh_post.gh("issue", "comment")
        msg = str(e.value)
        assert "not installed" in msg
        assert "cli.github.com" in msg          # where to get it
        assert "gh auth login" in msg           # what to do next

    def test_unauthenticated_gh_is_named_as_such(self, monkeypatch):
        class R:
            returncode = 1
            stdout = ""
            stderr = ("error: not logged into any GitHub hosts. "
                      "Run gh auth login to authenticate.")
        monkeypatch.setattr(gh_post.subprocess, "run", lambda *a, **k: R())
        with pytest.raises(gh_post.GhError) as e:
            gh_post.gh("issue", "comment")
        assert "not authenticated" in str(e.value)

    def test_gh_auth_exit_code_is_recognised(self, monkeypatch):
        class R:
            returncode = 4
            stdout = ""
            stderr = "something terse"
        monkeypatch.setattr(gh_post.subprocess, "run", lambda *a, **k: R())
        with pytest.raises(gh_post.GhError) as e:
            gh_post.gh("api", "user")
        assert "not authenticated" in str(e.value)

    @pytest.mark.parametrize("stderr", [
        "GraphQL: Could not resolve to a User with the login of 'ghost' on field author (HTTP 422)",
        "error: commit author token validation failed",
        "HTTP 403: authorization to fine-grained token endpoint denied",
    ])
    def test_author_and_authorization_are_not_mistaken_for_auth(self, monkeypatch,
                                                                stderr):
        """Substring-matching "auth" fires on author/authorization, misdirecting
        people to re-login over an unrelated 422/403."""
        class R:
            returncode = 1
            stdout = ""
        R.stderr = stderr
        monkeypatch.setattr(gh_post.subprocess, "run", lambda *a, **k: R())
        with pytest.raises(gh_post.GhError) as e:
            gh_post.gh("api", "x")
        assert "not authenticated" not in str(e.value)

    def test_other_os_errors_are_not_swallowed(self, monkeypatch):
        def boom(*a, **k):
            raise PermissionError(13, "Permission denied", "gh")
        monkeypatch.setattr(gh_post.subprocess, "run", boom)
        with pytest.raises(gh_post.GhError) as e:
            gh_post.gh("issue", "comment")
        assert "could not run 'gh'" in str(e.value)

    def test_ordinary_api_errors_still_surface_their_message(self, monkeypatch):
        class R:
            returncode = 1
            stdout = ""
            stderr = "gh: Not Found (HTTP 404)"
        monkeypatch.setattr(gh_post.subprocess, "run", lambda *a, **k: R())
        with pytest.raises(gh_post.GhError) as e:
            gh_post.gh("api", "repos/o/r/issues/999")
        assert "404" in str(e.value)

    def test_runs_on_stdlib_only(self):
        """No third-party imports - a contributor must not need this repo's venv,
        or any pip install, to post a comment."""
        tree = ast.parse(open(gh_post.__file__, encoding="utf-8").read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods.add(node.module.split(".")[0])
        allowed = {"argparse", "json", "os", "re", "subprocess", "sys",
                   "tempfile", "pathlib", "difflib", "__future__"}
        assert mods <= allowed, f"non-stdlib imports: {mods - allowed}"
