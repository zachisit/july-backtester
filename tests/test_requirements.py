# tests/test_requirements.py
"""
Regression guard for requirements.txt.

Ensures every entry is pinned with == so that `pip install -r requirements.txt`
produces a reproducible install regardless of when or where it is run.
Unpinned or inequality-only constraints (e.g. numpy<2.0) are the root cause
of "works on my machine" failures for new contributors.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _parse_requirements():
    """
    Return a list of (line_number, raw_line, package_spec) for every
    non-blank, non-comment line in requirements.txt.
    Inline comments are stripped from the spec before returning.
    """
    req_path = PROJECT_ROOT / "requirements.txt"
    entries = []
    for i, line in enumerate(req_path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        spec = stripped.split("#")[0].strip()
        if spec:
            entries.append((i, line, spec))
    return entries


def test_all_packages_are_pinned():
    """Every package in requirements.txt must use == for exact version pinning."""
    unpinned = []
    for lineno, raw, spec in _parse_requirements():
        if "==" not in spec:
            unpinned.append(f"  line {lineno}: {raw.strip()!r}")
    assert not unpinned, (
        "The following requirements.txt entries are not pinned with ==:\n"
        + "\n".join(unpinned)
        + "\nAdd exact version pins (e.g. pandas==2.2.3) to prevent install failures."
    )


def test_no_inequality_only_constraints():
    """Upper/lower-bound constraints without == (e.g. numpy<2.0) are not sufficient."""
    bad = []
    for lineno, raw, spec in _parse_requirements():
        if ("<" in spec or ">" in spec) and "==" not in spec:
            bad.append(f"  line {lineno}: {raw.strip()!r}")
    assert not bad, (
        "The following entries use inequality constraints without an exact pin:\n"
        + "\n".join(bad)
        + "\nReplace with == pins to guarantee reproducible installs."
    )


def test_requirements_file_is_not_empty():
    """requirements.txt must contain at least one pinned package."""
    entries = _parse_requirements()
    assert len(entries) >= 1, "requirements.txt appears to be empty"


def test_core_packages_present():
    """Core runtime packages must appear in requirements.txt."""
    req_path = PROJECT_ROOT / "requirements.txt"
    text = req_path.read_text(encoding="utf-8").lower()
    for pkg in ("pandas", "numpy", "yfinance", "matplotlib", "requests"):
        assert pkg in text, f"Expected package {pkg!r} not found in requirements.txt"
