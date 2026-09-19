"""Every script path named in docs must actually exist in this repository.

Proposed by @shardul0701 reviewing #402. Doc→script references have now rotted
twice in two dedicated sweeps:

  #399  deleted scripts/norgate_to_parquet.py and scripts/validate_norgate_export.py
        while docs/README_full.md kept instructing people to run them.
  #402  swept again, and still left MERGE_SPEC.md §1 citing two probe scripts that
        `git log --all --diff-filter=AD` shows were NEVER committed here — under a
        heading reading "Proven facts from source inspection (not assumptions)".

Both sweeps were greps by a human who knew what they were looking for, and both
missed. So this is the check, not the discipline.

Deliberately narrow: it only asserts that a referenced path EXISTS. It says
nothing about whether the surrounding prose is accurate — that is not mechanically
checkable, and pretending otherwise would make this test a place where judgement
goes to die.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC_GLOBS = ("*.md", "*.example", "*.yml", "*.yaml", "*.cfg", "*.toml")
SCRIPT_REF = re.compile(r"\b((?:scripts|tools)/[\w/\-]+\.py)\b")

# Submodules are separate repositories with their own files; `git ls-files` here
# does not list their contents, so scanning their docs would report every path
# they legitimately reference as missing.
SKIP_DIRS = {".git", ".venv", "node_modules", "output", "data_cache",
             "__pycache__", ".pytest_cache", "custom_strategies", "parquet_data"}


def _tracked_files() -> set[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return set(out.split())


def _docs():
    for pattern in DOC_GLOBS:
        for doc in ROOT.rglob(pattern):
            if SKIP_DIRS.isdisjoint(doc.parts):
                yield doc


def test_every_documented_script_path_exists():
    tracked = _tracked_files()
    missing: dict[str, list[str]] = {}
    for doc in _docs():
        text = doc.read_text(encoding="utf-8", errors="replace")
        for path in SCRIPT_REF.findall(text):
            if path not in tracked:
                missing.setdefault(path, []).append(str(doc.relative_to(ROOT)))
    assert not missing, (
        "docs reference script paths that do not exist in this repo:\n" +
        "\n".join(f"  {p} <- {', '.join(sorted(set(docs)))}"
                  for p, docs in sorted(missing.items()))
    )


def test_the_check_would_actually_catch_a_missing_script(tmp_path):
    """Guards the guard: a regex that silently stops matching passes vacuously."""
    assert SCRIPT_REF.findall("run `scripts/does_not_exist.py` first") == \
        ["scripts/does_not_exist.py"]
    assert SCRIPT_REF.findall("see tools/x/y_z-1.py") == ["tools/x/y_z-1.py"]
    # Not every .py mention is a repo path — bare names must not be claimed.
    assert SCRIPT_REF.findall("import main.py") == []


def test_it_scans_more_than_zero_docs():
    """A path/glob mistake would make the main test pass by scanning nothing."""
    assert sum(1 for _ in _docs()) > 5
