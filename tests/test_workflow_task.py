import json
import logging
import subprocess
from types import SimpleNamespace

import pytest

from mlops_agent.workflow_task import run_stage


def test_worker_is_bounded_no_shell_or_inherited_secrets(monkeypatch, caplog):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret-test-only")

    def run(argv, **kwargs):
        assert argv == ["/opt/training/bin/python", "-m", "mlops_agent.pipeline", "validation"]
        assert kwargs["timeout"] == 240 and kwargs["shell"] is False
        assert "OPENROUTER_API_KEY" not in kwargs["env"]
        assert kwargs["env"]["MLFLOW_TRACKING_URI"] == "http://mlflow:5000"
        return SimpleNamespace(returncode=0, stdout='{"status":"ok","evidence":{}}')

    monkeypatch.setattr(subprocess, "run", run)
    with caplog.at_level(logging.INFO):
        assert run_stage("validation", {"workflow_run_id": "test"}) == {
            "completed_stage": "validation"
        }
    assert json.loads(caplog.records[-1].message)["status"] == "ok"
    assert "secret-test-only" not in caplog.text


@pytest.mark.parametrize("failure", ["timeout", "unavailable", "invalid", "failed"])
def test_worker_failures_are_logged_without_raw_output(monkeypatch, caplog, failure):
    def run(*args, **kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("secret-command", 240, stderr="secret-stderr")
        if failure == "unavailable":
            raise OSError("secret-error")
        return SimpleNamespace(
            returncode=1,
            stdout=(
                "secret-output"
                if failure == "invalid"
                else '{"status":"error","error":"secret-output"}'
            ),
        )

    monkeypatch.setattr(subprocess, "run", run)
    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError) as error:
        run_stage("evaluation", {"workflow_run_id": "test"})
    entry = json.loads(caplog.records[-1].message)
    assert entry["tool"] == "airflow_evaluation" and entry["status"] == "error"
    assert entry["duration_ms"] > 0 and entry["request_id"] == "test"
    assert "secret" not in str(error.value) + caplog.text


def test_unapproved_operation_does_not_launch_worker(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Worker must not be invoked")

    monkeypatch.setattr(subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="Unapproved"):
        run_stage("deploy", {"workflow_run_id": "test"})
