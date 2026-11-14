"""Exercise the documented offline command against real captured evidence."""

import json
import runpy
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("wrapped", [False, True])
def test_captured_conversation_can_be_reverified_without_provider(tmp_path, monkeypatch, wrapped):
    export = json.loads(Path("docs/evidence/agent-live.json").read_text())
    # A stale/untrusted stored check flag cannot determine the new check result.
    export["checks"] = {"conversation_complete": False}
    source = tmp_path / "captured.json"
    source.write_text(json.dumps(export if wrapped else export["conversation"]))
    output = tmp_path / "verified.json"
    monkeypatch.setattr(
        sys, "argv", ["verify-agent.py", "--from-json", str(source), "--output", str(output)]
    )
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path("scripts/verify-agent.py", run_name="__main__")
    assert exit_info.value.code == 0
    verified = json.loads(output.read_text())
    assert all(verified["checks"].values())
    assert verified["conversation"] == export["conversation"]


def test_malformed_capture_reports_safe_error_without_echo(tmp_path, monkeypatch, capsys):
    source = tmp_path / "malformed.json"
    source.write_text('{"request_id":"private-capture-sentinel"}')
    output = tmp_path / "unused.json"
    monkeypatch.setattr(
        sys, "argv", ["verify-agent.py", "--from-json", str(source), "--output", str(output)]
    )
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path("scripts/verify-agent.py", run_name="__main__")
    assert exit_info.value.code == 2
    assert not output.exists()
    error = capsys.readouterr().err
    assert "does not match the response schema" in error
    assert "private-capture-sentinel" not in error
