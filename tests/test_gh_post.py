# tests/test_gh_post.py
"""Tests for scripts/gh_post.py.

The tool's value is entirely in `verify()` - the round-trip check that catches a
mangled comment regardless of WHY it was mangled. These tests pin that, plus the
preflight that rejects the `-f body=@file` shape before it can post.

No network. Every test drives pure functions or patched subprocess calls.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "scripts"))

import gh_post  # noqa: E402


class TestNormalise:
    """Only the differences GitHub legitimately introduces may be ignored."""

    def test_crlf_matches_lf(self):
        """Windows contributors hand us CRLF; GitHub returns LF. That is not a
        mangled comment - Shardul is on Windows and would hit this on every post."""
        assert gh_post.normalise("a\r\nb") == gh_post.normalise("a\nb")

    def test_trailing_whitespace_ignored(self):
        assert gh_post.normalise("a   \nb\t\n") == gh_post.normalise("a\nb")

    def test_leading_and_trailing_blank_lines_ignored(self):
        assert gh_post.normalise("\n\nbody\n\n") == gh_post.normalise("body")

    def test_internal_blank_lines_preserved(self):
        """Markdown paragraph breaks are content, not noise."""
        assert gh_post.normalise("a\n\nb") != gh_post.normalise("a\nb")

    def test_substantive_difference_survives(self):
        assert gh_post.normalise("see foo.py:12") != gh_post.normalise("see ")


class TestVerify:
    """THE invariant: identical content passes, anything else fails - and the
    failure is reported, never swallowed."""

    def test_identical_content_passes(self, capsys):
        assert gh_post.verify("hello", "hello", "http://x") == 0
        assert "verified" in capsys.readouterr().out

    def test_crlf_roundtrip_passes(self):
        assert gh_post.verify("a\r\nb\r\n", "a\nb", "http://x") == 0

    def test_backtick_substitution_damage_is_caught(self, capsys):
        """Failure mode 1: the shell ate a backticked path before gh saw it."""
        sent = "check `helpers/rolling.py` for the fix"
        landed = "check  for the fix"          # substitution result
        assert gh_post.verify(sent, landed, "http://x") == gh_post.MISMATCH_EXIT
        assert "MISMATCH" in capsys.readouterr().err

    def test_literal_at_path_damage_is_caught(self, capsys):
        """Failure mode 2: `-f body=@path` posted the path, not the file."""
        sent = "Correcting my earlier comment. The real analysis is..."
        landed = "@C:/Users/shard/AppData/Local/Temp/gh_comment_106.md"
        assert gh_post.verify(sent, landed, "http://x") == gh_post.MISMATCH_EXIT
        assert "MISMATCH" in capsys.readouterr().err

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

    def test_rejects_bare_at_path(self, tmp_path):
        """Preflight for failure mode 2: catch it BEFORE it posts, not after."""
        f = tmp_path / "b.md"
        f.write_text("@C:/Users/shard/AppData/Local/Temp/gh_comment_106.md",
                     encoding="utf-8")
        with pytest.raises(SystemExit) as e:
            gh_post.read_source(str(f))
        assert e.value.code == 1

    def test_at_sign_in_real_prose_is_fine(self, tmp_path):
        """A comment opening with an @mention is normal and must not be blocked."""
        f = tmp_path / "b.md"
        f.write_text("@shardul0701 - thanks for the review.\n\nDetails follow.",
                     encoding="utf-8")
        assert gh_post.read_source(str(f)).startswith("@shardul0701")

    def test_rejects_empty_body(self, tmp_path):
        f = tmp_path / "b.md"
        f.write_text("   \n\n", encoding="utf-8")
        with pytest.raises(SystemExit):
            gh_post.read_source(str(f))

    def test_rejects_missing_file(self):
        with pytest.raises(SystemExit):
            gh_post.read_source("/nonexistent/nope.md")


class TestNoInlineBodyOption:
    """Failure mode 1 is removed structurally: there is no flag that accepts
    body text as a shell argument, so it cannot be shell-substituted."""

    @pytest.mark.parametrize("cmd", ["comment", "review", "create", "edit-body"])
    def test_no_body_flag_exists(self, cmd):
        parser = gh_post.build_parser()
        argv = [cmd, "--repo", "o/r", "--file", "x.md"]
        if cmd != "create":
            argv += ["--number", "1"]
        else:
            argv += ["--title", "t"]
        args = parser.parse_args(argv)
        assert not hasattr(args, "body")
        assert args.file == "x.md"

    def test_file_is_required(self):
        with pytest.raises(SystemExit):
            gh_post.build_parser().parse_args(
                ["comment", "--repo", "o/r", "--number", "1"])


class TestVerifiedPostFlow:
    """End to end with `gh` patched - pins that a mismatch is surfaced as a
    non-zero exit rather than being reported as success."""

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
        """If the comment id cannot be recovered, verification did not happen -
        that must not read as verified."""
        f = tmp_path / "b.md"
        f.write_text("hello", encoding="utf-8")
        self._patch(monkeypatch, "hello", url="https://example.com/no-id-here")
        assert gh_post.main(["comment", "--repo", "o/r", "--number", "1",
                             "--file", str(f)]) == gh_post.MISMATCH_EXIT


class TestPortabilityForContributorsWithoutLocalTooling:
    """This repo's own conventions (the `rtk` command prefix, a specific venv)
    are one machine's setup. Most contributors are remote and have none of it.

    A tool that dies with a raw traceback on their machine reads as "broken"
    and sends them straight back to the unsafe `gh --body` invocation - the
    exact thing it exists to prevent. So the environment failures must be
    actionable, not tracebacks.
    """

    def test_no_rtk_dependency_anywhere_in_the_module(self):
        """The tool must run as plain `python scripts/gh_post.py`."""
        src = open(gh_post.__file__, encoding="utf-8").read()
        code = "\n".join(l for l in src.splitlines()
                         if not l.strip().startswith("#"))
        assert "rtk " not in code

    def test_missing_gh_binary_gives_install_instructions(self, monkeypatch,
                                                          capsys):
        def boom(*a, **k):
            raise FileNotFoundError(2, "No such file or directory", "gh")
        monkeypatch.setattr(gh_post.subprocess, "run", boom)
        with pytest.raises(SystemExit) as e:
            gh_post.gh("issue", "comment")
        assert e.value.code == 1
        err = capsys.readouterr().err
        assert "not installed" in err
        assert "cli.github.com" in err          # where to get it
        assert "gh auth login" in err           # what to do next
        assert "Traceback" not in err

    def test_unauthenticated_gh_is_named_as_such(self, monkeypatch, capsys):
        """`gh` present but not logged in is a different fix from `gh` absent."""
        class R:
            returncode = 1
            stdout = ""
            stderr = ("error: not logged into any GitHub hosts. "
                      "Run gh auth login to authenticate.")
        monkeypatch.setattr(gh_post.subprocess, "run", lambda *a, **k: R())
        with pytest.raises(SystemExit):
            gh_post.gh("issue", "comment")
        err = capsys.readouterr().err
        assert "not authenticated" in err
        assert "gh auth login" in err

    def test_other_os_errors_are_not_swallowed(self, monkeypatch, capsys):
        def boom(*a, **k):
            raise PermissionError(13, "Permission denied", "gh")
        monkeypatch.setattr(gh_post.subprocess, "run", boom)
        with pytest.raises(SystemExit):
            gh_post.gh("issue", "comment")
        assert "could not run 'gh'" in capsys.readouterr().err

    def test_ordinary_api_errors_still_surface_their_message(self, monkeypatch,
                                                             capsys):
        """A 404 must not be misreported as an auth problem."""
        class R:
            returncode = 1
            stdout = ""
            stderr = "gh: Not Found (HTTP 404)"
        monkeypatch.setattr(gh_post.subprocess, "run", lambda *a, **k: R())
        with pytest.raises(SystemExit):
            gh_post.gh("api", "repos/o/r/issues/999")
        err = capsys.readouterr().err
        assert "404" in err
        assert "not authenticated" not in err

    def test_runs_on_stdlib_only(self):
        """No third-party imports - a contributor must not need this repo's
        venv, or any pip install, to post a comment."""
        import ast
        tree = ast.parse(open(gh_post.__file__, encoding="utf-8").read())
        mods = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                mods.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods.add(node.module.split(".")[0])
        allowed = {"argparse", "json", "re", "subprocess", "sys", "tempfile",
                   "pathlib", "difflib", "__future__"}
        assert mods <= allowed, f"non-stdlib imports: {mods - allowed}"
