"""Airflow's isolated ML worker: immutable input, persistent per-run artifacts.

No Airflow imports, credentials, shell commands, cluster or deployment writes.
"""

import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Literal

import joblib
import numpy as np
import sklearn
from pydantic import BaseModel, ConfigDict, Field

from mlops_agent.training import (
    EVALUATION_POLICY,
    PreparedData,
    TrainingConfig,
    evaluate_classifier,
    fit_classifier,
    prepare_split,
    validate_dataset,
)

DAG_ID = "assignment_training"
STAGES = (
    "validation",
    "preprocessing",
    "training",
    "evaluation",
    "quality_gate",
    "approve_candidate",
)
POLICY = {
    "version": "iris-candidate-v1",
    "min_f1_macro": 0.90,
    "min_accuracy": 0.90,
    "max_log_loss": 0.35,
    "min_test_rows": 45,
}
LOG = logging.getLogger(__name__)


class PipelineRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    workflow_run_id: str = Field(min_length=1, max_length=250, pattern=r"^[A-Za-z0-9_.:+-]+$")
    training: TrainingConfig = Field(default_factory=TrainingConfig)
    input_variant: Literal["canonical", "malformed_validation_fixture"] = "canonical"


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, sort_keys=True, allow_nan=False))
    temporary.replace(path)


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def decide_gate(metrics: dict, test_rows: int) -> dict:
    """Policy cannot be relaxed by DAG config. Repeated holdout is a limitation."""
    import math

    required = {"accuracy", "f1_macro", "log_loss"}
    finite = required.issubset(metrics) and all(
        isinstance(metrics[k], (int, float))
        and not isinstance(metrics[k], bool)
        and math.isfinite(metrics[k])
        for k in required
    )
    passed = bool(
        finite
        and 0 <= metrics["log_loss"] <= POLICY["max_log_loss"]
        and POLICY["min_f1_macro"] <= metrics["f1_macro"] <= 1
        and POLICY["min_accuracy"] <= metrics["accuracy"] <= 1
        and test_rows >= POLICY["min_test_rows"]
    )
    return {
        "passed": passed,
        "policy": POLICY,
        "metrics": metrics,
        "test_rows": test_rows,
        "scope": "candidate-only; repeated holdout; no production approval or deployment",
    }


class Pipeline:
    def __init__(
        self,
        request: PipelineRequest,
        input_root: Path,
        shared_root: Path,
        code_revision: str,
        tracking_uri: str,
    ):
        self.request = request
        self.input_root = input_root
        self.code_revision = code_revision
        self.uri = tracking_uri
        self.key = hashlib.sha256(request.workflow_run_id.encode()).hexdigest()
        self.run = shared_root / self.key
        self.run.mkdir(parents=True, exist_ok=True)
        config = request.model_dump()
        saved = self.run / "request.json"
        if saved.exists() and read_json(saved) != config:
            raise ValueError("Workflow request changed across attempts")
        write_json(saved, config)

    def validation(self):
        # Validate schema before hash checking so the isolated malformed fixture
        # exercises the actual same validation code, without mutating DVC data.
        content = (self.input_root / "iris.csv").read_bytes()
        if self.request.input_variant == "malformed_validation_fixture":
            content = content.replace(b"sepal_length", b"missing_feature", 1)
        validate_dataset(content)
        lineage = read_json(self.input_root / "lineage.json")
        if (
            lineage["code_git_revision"] != self.code_revision
            or len(self.code_revision) != 40
            or hashlib.md5(content, usedforsecurity=False).hexdigest() != lineage["dataset_dvc_md5"]
        ):
            raise ValueError("Input/code provenance mismatch")
        snapshot = self.run / "iris.csv"
        if snapshot.exists() and snapshot.read_bytes() != content:
            raise ValueError("Workflow input snapshot changed")
        snapshot.write_bytes(content)
        write_json(self.run / "lineage.json", lineage)
        return {"validated_rows": 150, "dataset_dvc_md5": lineage["dataset_dvc_md5"]}

    def preprocessing(self):
        data = prepare_split((self.run / "iris.csv").read_bytes(), self.request.training)
        temporary = self.run / "split.tmp.npz"
        np.savez(
            temporary,
            features=data.features,
            labels=data.labels,
            train_indices=data.train_indices,
            test_indices=data.test_indices,
        )
        temporary.replace(self.run / "split.npz")
        result = {
            "split_sha256": data.split_sha256,
            "evaluation_id": data.evaluation_id,
            "train_rows": len(data.train_indices),
            "test_rows": len(data.test_indices),
        }
        write_json(self.run / "split.json", result)
        return result

    def prepared(self):
        meta = read_json(self.run / "split.json")
        with np.load(self.run / "split.npz", allow_pickle=False) as data:
            return PreparedData(
                **{k: data[k] for k in data.files},
                split_sha256=meta["split_sha256"],
                evaluation_id=meta["evaluation_id"],
            )

    def training(self):
        model = fit_classifier(self.prepared(), self.request.training)
        temporary = self.run / "model.tmp"
        joblib.dump(model, temporary)
        temporary.replace(self.run / "model.joblib")
        return {"classifier": self.request.training.classifier}

    def mlflow(self):
        import mlflow

        mlflow.set_tracking_uri(self.uri)
        mlflow.set_registry_uri(self.uri)
        return mlflow

    def evaluation(self):
        mlflow = self.mlflow()
        from mlflow import sklearn as mlflow_sklearn
        from mlflow.models import infer_signature

        # Only load this workflow's trusted local trained object, never user paths.
        model, data = joblib.load(self.run / "model.joblib"), self.prepared()
        metrics, predictions = evaluate_classifier(model, data)
        result_file = self.run / "evaluation.json"
        if result_file.exists():
            result = read_json(result_file)
            if mlflow.MlflowClient().get_run(result["run_id"]).info.status == "FINISHED":
                return result  # Retry after successful artifact commit is idempotent.
        experiment = "assignment-iris-" + self.request.training.classifier
        mlflow.set_experiment(experiment)
        run_file = self.run / "mlflow-run.json"
        if not run_file.exists():
            run = mlflow.MlflowClient().create_run(
                mlflow.get_experiment_by_name(experiment).experiment_id,
                tags={
                    "assignment.training": "true",
                    "assignment.airflow_dag": DAG_ID,
                    "assignment.airflow_run": self.request.workflow_run_id,
                    "assignment.gate": "pending",
                    "assignment.candidate_approved": "false",
                },
            )
            write_json(run_file, {"run_id": run.info.run_id})
        run_id = read_json(run_file)["run_id"]
        parameters = {
            **read_json(self.run / "lineage.json"),
            **self.request.training.model_dump(),
            **read_json(self.run / "split.json"),
            "evaluation_policy": EVALUATION_POLICY,
            "sklearn_version": sklearn.__version__,
        }
        with mlflow.start_run(run_id=run_id):
            mlflow.log_params(parameters)
            mlflow.log_metrics(metrics)
            mlflow.log_dict({**predictions, "evaluation_id": data.evaluation_id}, "evaluation.json")
            mlflow.log_dict({"parameters": parameters}, "lineage.json")
            mlflow.log_dict(
                {"train": data.train_indices.tolist(), "test": data.test_indices.tolist()},
                "split.json",
            )
            info = mlflow_sklearn.log_model(
                model,
                name="model",
                input_example=data.features[data.train_indices][:2],
                signature=infer_signature(
                    data.features[data.train_indices],
                    model.predict(data.features[data.train_indices]),
                ),
                pip_requirements=[
                    f"scikit-learn=={sklearn.__version__}",
                    f"numpy=={np.__version__}",
                    "cloudpickle==3.1.2",
                ],
            )
            mlflow.set_tag("assignment.model_id", info.model_id)
            result = {
                "run_id": run_id,
                "model_id": info.model_id,
                "model_uri": info.model_uri,
                "metrics": metrics,
                "evaluation_id": data.evaluation_id,
                "test_rows": len(data.test_indices),
                "workflow_run_id": self.request.workflow_run_id,
            }
        # Only publish a result after MLflow exits the run successfully.
        write_json(result_file, result)
        return result

    def quality_gate(self):
        result = read_json(self.run / "evaluation.json")
        gate = {
            **decide_gate(result["metrics"], result["test_rows"]),
            "run_id": result["run_id"],
            "workflow_run_id": self.request.workflow_run_id,
        }
        client = self.mlflow().MlflowClient()
        client.log_dict(result["run_id"], gate, "quality_gate.json")
        client.set_tag(
            result["run_id"], "assignment.gate", "passed" if gate["passed"] else "failed"
        )
        write_json(self.run / "gate.json", gate)
        if not gate["passed"]:
            raise ValueError("Candidate quality gate failed")
        return gate

    def approve_candidate(self):
        # All-success dependency plus defense in depth: no approval on missing,
        # failed, stale, different-run or changed policy evidence.
        result = read_json(self.run / "evaluation.json")
        gate = read_json(self.run / "gate.json")
        expected = {
            **decide_gate(result["metrics"], result["test_rows"]),
            "run_id": result["run_id"],
            "workflow_run_id": self.request.workflow_run_id,
        }
        client = self.mlflow().MlflowClient()
        observed = client.get_run(result["run_id"])
        if (
            not gate.get("passed")
            or gate != expected
            or observed.data.tags.get("assignment.gate") != "passed"
            or observed.data.tags.get("assignment.airflow_run") != self.request.workflow_run_id
            or observed.info.status != "FINISHED"
        ):
            raise ValueError("Candidate approval requires this workflow's passed gate")
        client.set_tag(result["run_id"], "assignment.candidate_approved", "true")
        approval = {
            "run_id": result["run_id"],
            "workflow_run_id": self.request.workflow_run_id,
            "policy": POLICY["version"],
            "candidate_approved": True,
            "production_promoted": False,
        }
        write_json(self.run / "approved.json", approval)
        return approval

    def execute(self, stage: str) -> dict:
        if stage not in STAGES:
            raise ValueError("Unknown pipeline stage")
        started = time.monotonic()
        status = "error"
        try:
            result = getattr(self, stage)()
            status = "ok"
            return result
        finally:
            LOG.info(
                json.dumps(
                    {
                        "tool": "airflow_" + stage,
                        "status": status,
                        "duration_ms": (time.monotonic() - started) * 1000,
                        "request_id": self.key,
                    }
                )
            )


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        request = PipelineRequest.model_validate(json.load(sys.stdin))
        pipeline = Pipeline(
            request,
            Path("/opt/project/input"),
            Path("/opt/airflow/training"),
            Path("/opt/project/revision").read_text().strip(),
            os.environ["MLFLOW_TRACKING_URI"],
        )
        result = pipeline.execute(sys.argv[1])
        print(json.dumps({"status": "ok", "evidence": result}, allow_nan=False))
    except Exception as error:
        # Neither provider secrets nor arbitrary input/remote exceptions reach task logs.
        print(json.dumps({"status": "error", "error_type": type(error).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
