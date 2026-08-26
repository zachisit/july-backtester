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
import re
import subprocess
import sys
import tempfile
from pathlib import Path

MISMATCH_EXIT = 2

# Content that survives a round trip unchanged except for these: GitHub strips
# trailing whitespace, and Windows checkouts hand us CRLF.
_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)


def normalise(text: str) -> str:
    """Canonical form for comparing what we sent against what came back."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_WS.sub("", text)
    return text.strip("\n")


def read_source(path: str) -> str:
    if path == "-":
        body = sys.stdin.read()
    else:
        p = Path(path)
        if not p.is_file():
            die(f"not a file: {path}")
        body = p.read_text(encoding="utf-8")
    if not body.strip():
        die("refusing to post an empty body")
    if body.strip().startswith("@") and "\n" not in body.strip():
        # The exact shape of failure 2, caught before it posts.
        die(f"body is a bare @path ({body.strip()!r}) - this is the `-f body=@file` "
            f"bug. Pass the file to --file instead.")
    return body


def die(msg: str, code: int = 1):
    print(f"[gh_post] ERROR: {msg}", file=sys.stderr)
    sys.exit(code)


def gh(*args: str) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        die(f"gh {' '.join(args[:3])}... failed: {r.stderr.strip()[:400]}")
    return r.stdout.strip()


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


def _tmp(body: str) -> str:
    f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                    encoding="utf-8", newline="\n")
    f.write(body)
    f.close()
    return f.name


def cmd_comment(a) -> int:
    body = read_source(a.file)
    url = gh("issue", "comment", str(a.number), "--repo", a.repo,
             "--body-file", _tmp(body))
    m = re.search(r"#issuecomment-(\d+)", url)
    if not m:
        print(f"[gh_post] posted but could not parse a comment id from: {url}",
              file=sys.stderr)
        print("[gh_post] NOT VERIFIED - check it by hand.", file=sys.stderr)
        return MISMATCH_EXIT
    return verify(body, fetch_comment_body(a.repo, m.group(1)), url)


def cmd_review(a) -> int:
    body = read_source(a.file)
    args = ["pr", "review", str(a.number), "--repo", a.repo,
            "--body-file", _tmp(body)]
    args.append({"APPROVE": "--approve", "REQUEST_CHANGES": "--request-changes"}
                .get(a.event, "--comment"))
    gh(*args)
    raw = gh("api", f"repos/{a.repo}/pulls/{a.number}/reviews")
    reviews = json.loads(raw)
    if not reviews:
        print("[gh_post] posted but no reviews returned - NOT VERIFIED",
              file=sys.stderr)
        return MISMATCH_EXIT
    latest = reviews[-1]
    return verify(body, latest.get("body") or "", latest.get("html_url", ""))


def cmd_create(a) -> int:
    body = read_source(a.file)
    args = ["issue", "create", "--repo", a.repo, "--title", a.title,
            "--body-file", _tmp(body)]
    for label in (a.label or []):
        args += ["--label", label]
    url = gh(*args)
    m = re.search(r"/issues/(\d+)", url)
    if not m:
        print(f"[gh_post] created but could not parse a number from: {url}",
              file=sys.stderr)
        return MISMATCH_EXIT
    return verify(body, fetch_issue_body(a.repo, m.group(1)), url)


def cmd_edit_body(a) -> int:
    body = read_source(a.file)
    url = gh("issue", "edit", str(a.number), "--repo", a.repo,
             "--body-file", _tmp(body))
    return verify(body, fetch_issue_body(a.repo, str(a.number)),
                  url or f"{a.repo}#{a.number}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="gh_post.py",
        description="Post GitHub content and verify it landed byte-for-byte.")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp, number=True):
        sp.add_argument("--repo", required=True, help="OWNER/REPO")
        if number:
            sp.add_argument("--number", required=True)
        sp.add_argument("--file", required=True,
                        help="path to the body, or - for stdin")

    common(sub.add_parser("comment", help="comment on an issue or PR"))

    r = sub.add_parser("review", help="submit a PR review")
    common(r)
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
