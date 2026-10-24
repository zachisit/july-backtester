"""Mutation evidence requires a green baseline and actual assertion failures."""
from types import SimpleNamespace

import pytest

from scripts import reverify_sizing_mutants as audit


@pytest.mark.parametrize("result", [("1 failed", 1, 1), ("1 error", 0, 1)])
def test_failed_control_aborts_before_mutation(monkeypatch, capsys, result):
    calls = []
    monkeypatch.setattr(audit, "run", lambda targets: (calls.append(targets) or result))
    assert audit.main() == 1
    assert len(calls) == 1
    assert "control failed" in capsys.readouterr().out


@pytest.mark.parametrize("returncode,failures", [(0, 0), (1, 0), (1, 1)])
def test_only_a_completed_assertion_failure_kills_a_mutant(
    tmp_path, monkeypatch, returncode, failures,
):
    source = tmp_path / "subject.py"
    source.write_text("original")
    monkeypatch.setattr(audit, "MUTANTS", [("example", str(source), "original", "mutated", ["target"])])
    monkeypatch.setattr(audit, "run", lambda targets: (
        ("control passed", 0, 0) if source.read_text() == "original"
        else ("mutant result", failures, returncode)))
    assert audit.main() == (0 if returncode == 1 and failures else 1)
    assert source.read_text() == "original"


def test_runner_preserves_returncode_without_misreading_fixture_error(monkeypatch):
    monkeypatch.setattr(audit.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="ERROR test_case - fixture exploded\n1 error\n", stderr=""))
    _, failures, returncode = audit.run(["target"])
    assert (failures, returncode) == (0, 1)


def test_runner_rejects_collection_failure(monkeypatch):
    monkeypatch.setattr(audit.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=2, stdout="collection failed", stderr=""))
    with pytest.raises(RuntimeError, match="did not complete"):
        audit.run(["target"])


def test_source_is_restored_if_runner_crashes(tmp_path, monkeypatch):
    source = tmp_path / "subject.py"
    source.write_text("original")
    monkeypatch.setattr(audit, "MUTANTS", [("example", str(source), "original", "mutated", ["target"])])

    def run(targets):
        if source.read_text() == "mutated":
            raise RuntimeError("runner failed")
        return "control passed", 0, 0

    monkeypatch.setattr(audit, "run", run)
    with pytest.raises(RuntimeError, match="runner failed"):
        audit.main()
    assert source.read_text() == "original"


def test_utf8_and_crlf_source_is_restored_byte_for_byte(tmp_path, monkeypatch):
    source = tmp_path / "subject.py"
    original = "original # μ\r\n".encode("utf-8")
    source.write_bytes(original)
    monkeypatch.setattr(audit, "MUTANTS", [("example", str(source), "original", "mutated", ["target"])])
    monkeypatch.setattr(audit, "run", lambda targets: (
        ("control passed", 0, 0) if source.read_bytes() == original
        else ("1 failed", 1, 1)))
    assert audit.main() == 0
    assert source.read_bytes() == original
