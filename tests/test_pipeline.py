import json
import logging
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from mlops_agent.dataset import dataset_bytes
from mlops_agent.pipeline import (
    POLICY,
    Pipeline,
    PipelineRequest,
    decide_gate,
    read_json,
    write_json,
)


@pytest.fixture
def pipeline(tmp_path):
    import hashlib

    content = dataset_bytes()
    source = tmp_path / "input"
    source.mkdir()
    (source / "iris.csv").write_bytes(content)
    write_json(
        source / "lineage.json",
        {
            "dataset_path": "data/iris.csv",
            "dataset_git_revision": "a" * 40,
            "code_git_revision": "b" * 40,
            "dataset_dvc_md5": hashlib.md5(content, usedforsecurity=False).hexdigest(),
        },
    )
    return Pipeline(
        PipelineRequest(workflow_run_id="test__1"),
        source,
        tmp_path / "runs",
        "b" * 40,
        "http://mlflow:5000",
    )


def test_stages_persist_snapshot_split_model_and_logs(pipeline, caplog):
    with caplog.at_level(logging.INFO):
        pipeline.execute("validation")
        pipeline.execute("preprocessing")
        pipeline.execute("training")
    assert (pipeline.run / "iris.csv").read_bytes() == dataset_bytes()
    assert (pipeline.run / "model.joblib").is_file()
    assert len(pipeline.prepared().test_indices) == 45
    events = [json.loads(r.message) for r in caplog.records]
    assert [e["tool"] for e in events] == [
        "airflow_validation",
        "airflow_preprocessing",
        "airflow_training",
    ]
    assert all(e["status"] == "ok" and e["duration_ms"] > 0 and e["request_id"] for e in events)


def test_malformed_fixture_does_not_change_source_or_create_model(pipeline):
    pipeline.request.input_variant = "malformed_validation_fixture"
    with pytest.raises(ValueError, match="Dataset validation failed"):
        pipeline.validation()
    assert (pipeline.input_root / "iris.csv").read_bytes() == dataset_bytes()
    assert not (pipeline.run / "model.joblib").exists()
    assert not (pipeline.run / "approved.json").exists()


def test_code_and_content_provenance_are_checked(pipeline):
    pipeline.code_revision = "c" * 40
    with pytest.raises(ValueError, match="provenance mismatch"):
        pipeline.validation()
    pipeline.code_revision = "b" * 40
    content = (pipeline.input_root / "iris.csv").read_bytes().replace(b"5.0", b"5.1", 1)
    (pipeline.input_root / "iris.csv").write_bytes(content)
    with pytest.raises(ValueError, match="provenance mismatch"):
        pipeline.validation()


@pytest.mark.parametrize(
    "config",
    [
        {"workflow_run_id": "../escape"},
        {"input_variant": "../other"},
        {"min_f1": 0.0},
        {"training": {"C": -1}},
        {"promote": True},
    ],
)
def test_reject_arbitrary_paths_config_and_gate_override(config):
    with pytest.raises(ValidationError):
        PipelineRequest.model_validate({"workflow_run_id": "test", **config})


def test_request_cannot_change_across_retry(pipeline):
    with pytest.raises(ValueError, match="changed across attempts"):
        Pipeline(
            PipelineRequest(workflow_run_id="test__1", training={"C": 0.01}),
            pipeline.input_root,
            pipeline.run.parent,
            "b" * 40,
            pipeline.uri,
        )


@pytest.mark.parametrize(
    "metrics,rows",
    [
        ({"accuracy": 0.99, "f1_macro": 0.99, "log_loss": 0.4}, 45),
        ({"accuracy": 0.89, "f1_macro": 0.99, "log_loss": 0.1}, 45),
        ({"accuracy": 0.99, "f1_macro": 0.89, "log_loss": 0.1}, 45),
        ({"accuracy": 0.99, "f1_macro": 0.99, "log_loss": 0.1}, 44),
        ({"accuracy": 1, "f1_macro": float("nan"), "log_loss": 0.1}, 45),
        ({"accuracy": 1, "f1_macro": 1}, 45),
        ({"accuracy": 1, "f1_macro": 1, "log_loss": -0.1}, 45),
    ],
)
def test_gate_requires_every_threshold_finite_and_minimum_cohort(metrics, rows):
    assert not decide_gate(metrics, rows)["passed"]


def test_exact_gate_thresholds_pass():
    assert decide_gate({"accuracy": 0.9, "f1_macro": 0.9, "log_loss": 0.35}, 45)["passed"]


class FakeClient:
    def __init__(self):
        self.tags = {"assignment.gate": "pending", "assignment.airflow_run": "test__1"}
        self.artifacts = {}

    def set_tag(self, run, key, value):
        self.tags[key] = value

    def log_dict(self, run, value, name):
        self.artifacts[name] = value

    def get_run(self, run):
        return SimpleNamespace(
            data=SimpleNamespace(tags=self.tags), info=SimpleNamespace(status="FINISHED")
        )


@pytest.fixture
def evaluated(pipeline, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(pipeline, "mlflow", lambda: SimpleNamespace(MlflowClient=lambda: client))
    write_json(
        pipeline.run / "evaluation.json",
        {
            "run_id": "e" * 32,
            "workflow_run_id": "test__1",
            "test_rows": 45,
            "metrics": {"accuracy": 0.92, "f1_macro": 0.91, "log_loss": 0.2},
        },
    )
    return pipeline, client


def test_failed_gate_cannot_approve_and_records_reason(evaluated):
    pipeline, client = evaluated
    result = read_json(pipeline.run / "evaluation.json")
    result["metrics"]["log_loss"] = 0.8
    write_json(pipeline.run / "evaluation.json", result)
    with pytest.raises(ValueError, match="gate failed"):
        pipeline.quality_gate()
    assert client.tags["assignment.gate"] == "failed"
    assert client.artifacts["quality_gate.json"]["policy"] == POLICY
    with pytest.raises(ValueError, match="requires"):
        pipeline.approve_candidate()
    assert not (pipeline.run / "approved.json").exists()


def test_passed_gate_approves_candidate_only_and_is_retryable(evaluated):
    pipeline, client = evaluated
    pipeline.quality_gate()
    first = pipeline.approve_candidate()
    assert pipeline.approve_candidate() == first
    assert first["candidate_approved"] and not first["production_promoted"]
    assert client.tags["assignment.candidate_approved"] == "true"


@pytest.mark.parametrize("mutation", ["policy", "run_id", "workflow_run_id", "remote_gate"])
def test_approval_rechecks_coherent_local_and_remote_gate(evaluated, mutation):
    pipeline, client = evaluated
    pipeline.quality_gate()
    if mutation == "remote_gate":
        client.tags["assignment.gate"] = "failed"
    else:
        gate = read_json(pipeline.run / "gate.json")
        gate[mutation] = "wrong"
        write_json(pipeline.run / "gate.json", gate)
    with pytest.raises(ValueError, match="requires"):
        pipeline.approve_candidate()
    assert "assignment.candidate_approved" not in client.tags


def test_missing_gate_does_not_approve(evaluated):
    pipeline, client = evaluated
    with pytest.raises(FileNotFoundError):
        pipeline.approve_candidate()
    assert "assignment.candidate_approved" not in client.tags


def test_unknown_stage_rejected_before_execution(pipeline):
    with pytest.raises(ValueError, match="Unknown pipeline stage"):
        pipeline.execute("deploy")
    assert not (pipeline.run / "approved.json").exists()
