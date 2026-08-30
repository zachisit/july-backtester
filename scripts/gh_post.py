#!/usr/bin/env python3
"""scripts/gh_post.py - post GitHub comments that are verified to have landed.

WHY THIS EXISTS
---------------
Two contributors lost comment content to `gh` in the same week, through two
DIFFERENT mechanisms:

1. ``gh issue comment --body "...`backticks`..."`` - the shell ran command
   substitution inside the double-quoted string before ``gh`` ever saw it. File
   paths vanished from a posted review; one invocation created a stray file
   named ``cash``.
2. ``gh api -f body=@/path/to/file`` - ``-f`` sends its value **literally**, so
   the string ``@C:/Users/.../gh_comment_106.md`` posted as the comment body
   and the real reply was never sent. (``-F`` is the flag with ``@file``
   semantics; ``--body-file`` is better still.)

A style rule like "always use --body-file" does not cover case 2 - that author
*was* trying to pass a file. Any guard that reasons about the CAUSE will miss
the next variant.

So this tool checks the OUTCOME instead: it posts, reads the comment back from
the API, and compares it to the source file. If what landed is not what was
written, it says so loudly and prints the comment URL so it can be fixed or
deleted. That check is agnostic to why the content was mangled, which is the
only property that makes it durable.

Secondary hardening: there is no inline-body option at all. Content comes from
a file or stdin, never from a shell argument, which removes case 1 structurally
rather than by convention.

USAGE
-----
    python scripts/gh_post.py comment  --repo O/R --number 302 --file reply.md
    python scripts/gh_post.py review   --repo O/R --number 302 --file r.md [--event APPROVE]
    python scripts/gh_post.py create   --repo O/R --title "..."  --file body.md [--label backlog]
    python scripts/gh_post.py edit-body --repo O/R --number 109 --file body.md

    cat reply.md | python scripts/gh_post.py comment --repo O/R --number 302 --file -

Exit codes: 0 verified, 1 usage/API error, 2 POSTED BUT CONTENT MISMATCH.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MISMATCH_EXIT = 2

# A bare @path - the shape of failure 2. A real path has no spaces, so this
# does not fire on `@shardul0701 LGTM, merging.`; and it must additionally look
# like a path, so a one-word `@zachisit` ping or an `@org/team` mention posted
# on its own is not refused either. Handles and team names cannot contain a
# drive letter, a backslash, or a dot, and do not start with a separator.
_BARE_AT_PATH = re.compile(r"@(?:[/\\]\S*|\S*[\\:.]\S*)")


def normalise(text: str) -> str:
    """Canonical form for comparing what we sent against what came back.

    This is deliberately the IDENTITY function, and that is an empirical result
    rather than an assumption.

    An earlier version stripped trailing whitespace and normalised CRLF, on the
    stated grounds that "GitHub does that anyway". Nobody had checked. Probing
    the real API - post, read back, compare byte-for-byte, delete - shows the
    body is stored **verbatim** on every axis tried:

        trailing spaces / tabs        identical
        trailing whitespace in a fence identical
        CRLF                          identical
        lone CR                       identical
        leading / trailing newlines   identical
        NBSP, emoji, zero-width space identical

    @shardul0701 probed twelve further axes on review (NFD unicode, BOM,
    U+2028/9, C0 controls, ZWJ + variation selectors, bidi overrides, bodies at
    and past 65 536 chars, tab-only lines, no trailing newline) - all verbatim,
    with exactly one exception:

        NUL byte U+0000               ALTERED -> stored as the two chars "^@"

    That exception needs no code here, and stating it is the point: it is a
    change we WANT reported, not folded away. So the correct reading is not
    "GitHub is verbatim, therefore comparison is safe" but "GitHub is verbatim
    except for NUL, and NUL is real damage" - which lands on the same identity
    function for a sounder reason. Anyone re-deriving this from the table above
    should have the exception with it.

    Each removed allowance had defended against nothing while creating a real
    false-negative hole: stripping trailing whitespace on BOTH sides meant that
    if transit damage removed it - which corrupts a diff inside a code fence so
    it no longer applies, and destroys markdown hard breaks - this tool said
    "verified".

    Kept as a named function rather than inlined so that if a genuine
    normalisation is ever demonstrated, it lands here **with a citation** and a
    test, instead of being reasoned into existence again.
    """
    return text


_NOT_UTF8 = (
    "{what} is not valid UTF-8 ({reason}, byte {pos}).\n"
    "         Windows PowerShell's Set-Content/Add-Content write the ANSI\n"
    "         codepage (cp1252 here), not UTF-8 - an em dash or a curly quote\n"
    "         is enough to produce this. Re-save as UTF-8, e.g.\n"
    "         Set-Content -Encoding utf8 body.md")


def read_source(path: str) -> str:
    # utf-8-SIG, not utf-8. PowerShell's `>` and Out-File default to UTF-8
    # *with a BOM* on Windows, which is the ordinary way a contributor here
    # drafts a comment. GitHub stores that BOM verbatim - probed live - so
    # reading as plain utf-8 posts an invisible U+FEFF into the comment AND
    # silently defeats the bare-@path guard below, because the body no longer
    # starts with "@". That is failure story 2 walking through the guard built
    # to stop it, by way of the default drafting path on the target platform.
    if path == "-":
        buf = getattr(sys.stdin, "buffer", None)
        if buf is None:                       # already-decoded stream (tests)
            body = sys.stdin.read()
        else:
            try:
                body = buf.read().decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                die(_NOT_UTF8.format(what="stdin", reason=exc.reason,
                                     pos=exc.start))
    else:
        p = Path(path)
        if not p.is_file():
            die(f"not a file: {path}")
        try:
            body = p.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            # Everything else in this tool fails with an actionable die().
            # This one raised a raw traceback, which reads as "the tool is
            # broken" and sends people back to `gh --body`.
            die(_NOT_UTF8.format(what=path, reason=exc.reason, pos=exc.start))
    if not body.strip():
        die("refusing to post an empty body")
    if _BARE_AT_PATH.fullmatch(body.strip()):
        # The exact shape of failure 2, caught before it posts. Matching on the
        # path SHAPE (no whitespace) rather than a leading "@" keeps a genuine
        # one-line reply like "@shardul0701 LGTM, merging." from being refused -
        # a false alarm here teaches people to distrust the tool.
        die(f"body is a bare @path ({body.strip()!r}) - this is the `-f body=@file` "
            f"bug. Pass the file to --file instead.")
    return body


def die(msg: str, code: int = 1):
    print(f"[gh_post] ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


GH_MISSING = (
    "the GitHub CLI ('gh') is not installed or not on PATH.\n"
    "         install:  https://cli.github.com  "
    "(brew install gh / winget install GitHub.cli / apt install gh)\n"
    "         then run: gh auth login"
)

GH_UNAUTH = (
    "the GitHub CLI is installed but not authenticated for this host.\n"
    "         run: gh auth login"
)


class GhError(RuntimeError):
    """A `gh` invocation failed. Raised rather than exiting so callers can tell
    'nothing was posted' apart from 'posted, but the readback failed'."""


# gh's documented exit code for an auth problem. Substring-matching "auth" in
# stderr misfires on "author" and "authorization", sending people to re-login
# over an unrelated 422/403.
_GH_AUTH_EXIT = 4
_NOT_LOGGED_IN = re.compile(r"\bgh auth login\b|not logged in|no such host")


def gh(*args: str) -> str:
    """Run `gh`. Raises GhError on failure; never exits."""
    try:
        # encoding= is load-bearing, not decoration. `text=True` alone decodes
        # with locale.getpreferredencoding(), which is cp1252 on Windows - so a
        # comment containing an emoji or an em dash reads back as mojibake and
        # verify() reports MISMATCH on a comment that posted perfectly. That is
        # the failure this tool is least able to afford: a false alarm trains
        # people to ignore exit 2. gh always emits UTF-8.
        r = subprocess.run(["gh", *args], capture_output=True, text=True,
                           encoding="utf-8")
    except FileNotFoundError:
        # Contributors outside this machine will not have the local `rtk`
        # wrapper and may not have `gh` either. A raw traceback here reads as
        # "the tool is broken" and sends people straight back to the unsafe
        # `--body` invocation, which is the opposite of the point.
        raise GhError(GH_MISSING)
    except OSError as exc:
        raise GhError(f"could not run 'gh': {exc}")
    if r.returncode != 0:
        err = r.stderr.strip()
        if r.returncode == _GH_AUTH_EXIT or _NOT_LOGGED_IN.search(err.lower()):
            raise GhError(GH_UNAUTH)
        raise GhError(f"gh {' '.join(args[:3])}... failed: {err[:400]}")
    return r.stdout.strip()


def gh_or_die(*args: str) -> str:
    """For calls made BEFORE anything is posted, where exiting is safe."""
    try:
        return gh(*args)
    except GhError as exc:
        die(str(exc))


def unverified(url: str, why: str) -> int:
    """Posted, but we could not confirm the content.

    Must NOT exit 1: that is the tool's code for 'nothing was posted', and a
    user who sees it will reasonably run the command again - producing a
    duplicate comment on top of the one that already landed.
    """
    print(f"[gh_post] *** POSTED BUT NOT VERIFIED *** {why}", file=sys.stderr)
    print(f"[gh_post] the content IS live at: {url}", file=sys.stderr)
    print("[gh_post] check it by hand. Do NOT just re-run - it posted.",
          file=sys.stderr)
    return MISMATCH_EXIT


def fetch_comment_body(repo: str, comment_id: str) -> str:
    raw = gh("api", f"repos/{repo}/issues/comments/{comment_id}")
    return json.loads(raw)["body"]


def fetch_issue_body(repo: str, number: str) -> str:
    raw = gh("api", f"repos/{repo}/issues/{number}")
    return json.loads(raw)["body"] or ""


def verify(sent: str, landed: str, url: str) -> int:
    """Compare and report. Returns a process exit code."""
    if normalise(sent) == normalise(landed):
        print(f"[gh_post] verified: content matches source ({len(sent)} chars)")
        print(url)
        return 0

    print("[gh_post] *** MISMATCH: what posted is NOT what you wrote ***",
          file=sys.stderr)
    print(f"[gh_post] url: {url}", file=sys.stderr)
    print(f"[gh_post] sent   {len(normalise(sent))} chars", file=sys.stderr)
    print(f"[gh_post] landed {len(normalise(landed))} chars", file=sys.stderr)

    import difflib
    diff = list(difflib.unified_diff(
        normalise(sent).splitlines(), normalise(landed).splitlines(),
        fromfile="what you wrote", tofile="what landed", lineterm="", n=1))
    for line in diff[:40]:
        print(f"[gh_post] {line}", file=sys.stderr)
    if len(diff) > 40:
        print(f"[gh_post] ... {len(diff) - 40} more diff lines", file=sys.stderr)
    print("[gh_post] fix or delete the comment above.", file=sys.stderr)
    return MISMATCH_EXIT


class _TmpBody:
    """Write the body to a 0600 temp file for --body-file, then always remove it.

    `delete=False` is required (Windows cannot reopen an open NamedTemporaryFile),
    so cleanup has to be explicit or every invocation leaves a draft comment
    sitting in $TMPDIR indefinitely.
    """

    def __init__(self, body: str):
        self.body = body

    def __enter__(self) -> str:
        f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                        encoding="utf-8", newline="")
        f.write(self.body)
        f.close()
        self.path = f.name
        return self.path

    def __exit__(self, *exc):
        try:
            os.unlink(self.path)
        except OSError:
            pass
        return False


def cmd_comment(a) -> int:
    body = read_source(a.file)
    with _TmpBody(body) as path:
        try:
            url = gh("issue", "comment", str(a.number), "--repo", a.repo,
                     "--body-file", path)
        except GhError as exc:
            die(str(exc))          # nothing posted - exit 1 is correct here
    m = re.search(r"#issuecomment-(\d+)", url)
    if not m:
        return unverified(url, "could not parse a comment id from the URL.")
    try:
        landed = fetch_comment_body(a.repo, m.group(1))
    except GhError as exc:
        return unverified(url, f"read-back failed: {exc}")
    return verify(body, landed, url)


def cmd_review(a) -> int:
    """Submit a PR review.

    --file is optional for APPROVE: a bare approve with no comment is the most
    common one, and refusing it would force people back to raw `gh pr review`,
    i.e. around the rule this tool exists to enforce.
    """
    body = read_source(a.file) if a.file else ""
    flag = {"APPROVE": "--approve",
            "REQUEST_CHANGES": "--request-changes"}.get(a.event, "--comment")
    args = ["pr", "review", str(a.number), "--repo", a.repo, flag]

    if not body:
        if a.event != "APPROVE":
            die(f"--file is required for --event {a.event}")
        try:
            gh(*args)
        except GhError as exc:
            die(str(exc))
        print("[gh_post] approved with no body - nothing to verify")
        return 0

    with _TmpBody(body) as path:
        try:
            gh(*(args + ["--body-file", path]))
        except GhError as exc:
            die(str(exc))

    # Identify the review by AUTHOR, not by list position. `gh api` returns one
    # page of 30 by default and this endpoint is ascending, so reviews[-1] is
    # the 30th-OLDEST review on a busy PR - never the one just submitted. Even
    # under 30, a concurrent reviewer would make it someone else's.
    try:
        me = json.loads(gh("api", "user"))["login"]
        raw = gh("api", "--paginate",
                 f"repos/{a.repo}/pulls/{a.number}/reviews?per_page=100")
        reviews = [r for r in json.loads(raw)
                   if (r.get("user") or {}).get("login") == me]
    except (GhError, ValueError, KeyError) as exc:
        return unverified(f"{a.repo}#{a.number}", f"read-back failed: {exc}")
    if not reviews:
        return unverified(f"{a.repo}#{a.number}",
                          "no review by the authenticated user came back.")
    latest = max(reviews, key=lambda r: r.get("submitted_at") or "")
    return verify(body, latest.get("body") or "", latest.get("html_url", ""))


def cmd_create(a) -> int:
    body = read_source(a.file)
    with _TmpBody(body) as path:
        args = ["issue", "create", "--repo", a.repo, "--title", a.title,
                "--body-file", path]
        for label in (a.label or []):
            args += ["--label", label]
        try:
            url = gh(*args)
        except GhError as exc:
            die(str(exc))
    m = re.search(r"/issues/(\d+)", url)
    if not m:
        return unverified(url, "could not parse an issue number from the URL.")
    try:
        landed = fetch_issue_body(a.repo, m.group(1))
    except GhError as exc:
        return unverified(url, f"read-back failed: {exc}")
    return verify(body, landed, url)


def cmd_edit_body(a) -> int:
    body = read_source(a.file)
    with _TmpBody(body) as path:
        try:
            url = gh("issue", "edit", str(a.number), "--repo", a.repo,
                     "--body-file", path)
        except GhError as exc:
            die(str(exc))
    target = url or f"{a.repo}#{a.number}"
    try:
        landed = fetch_issue_body(a.repo, str(a.number))
    except GhError as exc:
        return unverified(target, f"read-back failed: {exc}")
    return verify(body, landed, target)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gh_post.py",
        description="Post GitHub content and verify it landed byte-for-byte.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, number=True, file_required=True):
        sp.add_argument("--repo", required=True, help="OWNER/REPO")
        if number:
            sp.add_argument("--number", required=True)
        sp.add_argument("--file", required=file_required,
                        help="path to the body, or - for stdin")

    common(sub.add_parser("comment", help="comment on an issue or PR"))

    r = sub.add_parser("review", help="submit a PR review")
    common(r, file_required=False)   # optional only for a bodyless APPROVE
    r.add_argument("--event", default="COMMENT",
                   choices=["COMMENT", "APPROVE", "REQUEST_CHANGES"])

    c = sub.add_parser("create", help="create an issue")
    common(c, number=False)
    c.add_argument("--title", required=True)
    c.add_argument("--label", action="append")

    common(sub.add_parser("edit-body", help="replace an issue body"))
    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    return {"comment": cmd_comment, "review": cmd_review,
            "create": cmd_create, "edit-body": cmd_edit_body}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
