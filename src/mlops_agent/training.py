"""Deterministic training primitives reusable by the later Airflow DAG."""

import csv
import hashlib
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import sklearn
from pydantic import BaseModel, ConfigDict, Field
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, log_loss
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from mlops_agent.dataset import DATASET

FEATURES = ["sepal_length", "sepal_width", "petal_length", "petal_width"]
EVALUATION_POLICY = "iris-stratified-holdout-v1;f1=macro;labels=0,1,2;zero_division=0"


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    classifier: Literal["logistic", "forest"] = "logistic"
    C: float = Field(default=1.0, gt=0, le=1000, allow_inf_nan=False)
    max_depth: int = Field(default=4, ge=1, le=20)
    n_estimators: int = Field(default=100, ge=1, le=300)
    model_seed: int = Field(default=42, ge=0, le=2**31 - 1)
    split_seed: int = Field(default=42, ge=0, le=2**31 - 1)
    test_fraction: float = Field(default=0.3, ge=0.2, le=0.4, allow_inf_nan=False)


@dataclass
class PreparedData:
    features: np.ndarray
    labels: np.ndarray
    train_indices: np.ndarray
    test_indices: np.ndarray
    split_sha256: str
    evaluation_id: str


def validate_dataset(content: bytes) -> tuple[np.ndarray, np.ndarray]:
    """Fail closed on malformed schema, missing values and invalid labels/ranges."""
    try:
        reader = csv.DictReader(io.StringIO(content.decode("ascii")))
        if reader.fieldnames != [*FEATURES, "target"]:
            raise ValueError
        rows = list(reader)
        if len(rows) != 150 or any(set(r) != set(reader.fieldnames) for r in rows):
            raise ValueError
        features = np.array([[float(row[k]) for k in FEATURES] for row in rows])
        if not np.isfinite(features).all() or not ((features > 0) & (features < 20)).all():
            raise ValueError
        if any(row["target"] not in {"0", "1", "2"} for row in rows):
            raise ValueError
        labels = np.array([int(row["target"]) for row in rows])
        if set(labels) != {0, 1, 2} or min(np.bincount(labels)) < 10:
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise ValueError(
            "Dataset validation failed: expected 150 complete Iris classification rows"
        ) from None
    return features, labels


def prepare_split(content: bytes, config: TrainingConfig) -> PreparedData:
    features, labels = validate_dataset(content)
    train, test = train_test_split(
        np.arange(len(labels)),
        test_size=config.test_fraction,
        random_state=config.split_seed,
        stratify=labels,
    )
    split_sha = hashlib.sha256(
        json.dumps({"train": train.tolist(), "test": test.tolist()}, sort_keys=True).encode()
    ).hexdigest()
    evaluation_id = hashlib.sha256(
        json.dumps(
            {
                "data_sha256": hashlib.sha256(content).hexdigest(),
                "split_sha256": split_sha,
                "policy": EVALUATION_POLICY,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return PreparedData(features, labels, train, test, split_sha, evaluation_id)


def fit_classifier(data: PreparedData, config: TrainingConfig):
    if config.classifier == "logistic":
        model = make_pipeline(
            StandardScaler(),
            LogisticRegression(
                C=config.C,
                random_state=config.model_seed,
                max_iter=500,
                solver="lbfgs",
            ),
        )
    else:
        model = RandomForestClassifier(
            n_estimators=config.n_estimators,
            max_depth=config.max_depth,
            random_state=config.model_seed,
            n_jobs=1,
        )
    # Scaler learns only from training rows, inside the pipeline.
    model.fit(data.features[data.train_indices], data.labels[data.train_indices])
    return model


def evaluate_classifier(model, data: PreparedData) -> tuple[dict, dict]:
    test_x, test_y = data.features[data.test_indices], data.labels[data.test_indices]
    predicted, probabilities = model.predict(test_x), model.predict_proba(test_x)
    metrics = {
        "accuracy": float(accuracy_score(test_y, predicted)),
        "f1_macro": float(
            f1_score(test_y, predicted, labels=[0, 1, 2], average="macro", zero_division=0)
        ),
        "log_loss": float(log_loss(test_y, probabilities, labels=[0, 1, 2])),
    }
    if not all(math.isfinite(value) for value in metrics.values()):
        raise ValueError("Nonfinite evaluation metrics")
    return metrics, {
        "test_row_indices": data.test_indices.tolist(),
        "actual": test_y.tolist(),
        "predicted": predicted.tolist(),
        "probabilities": probabilities.tolist(),
        "confusion_matrix": confusion_matrix(test_y, predicted, labels=[0, 1, 2]).tolist(),
    }


def training_lineage(root: Path) -> dict:
    from mlops_agent.dvc_tools import DatasetInput, DvcTools

    dvc = DvcTools(root)
    version = dvc.get_version(DatasetInput())
    if not version["workspace_matches_revision"]:
        raise ValueError("Dataset must match the committed DVC pointer")
    # Tracked code must be committed; an actual SHA must identify executed code.
    import subprocess

    result = subprocess.run(
        [dvc.git, "status", "--porcelain", "--untracked-files=normal"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    if result.stdout.strip():
        raise ValueError("Commit code and data metadata before recording training provenance")
    return {k: version[k] for k in ("dataset_path", "dataset_git_revision", "dataset_dvc_md5")} | {
        "code_git_revision": dvc._revision("HEAD"),
        "dataset_recipe": "iris-sepal-resolution-v2",
        "sklearn_version": sklearn.__version__,
    }


def train_and_log(
    root: Path,
    tracking_uri: str,
    experiment_name: str,
    config: TrainingConfig,
) -> dict:
    """Engineering training entry point; never exposed as an automatic read tool."""
    import mlflow
    import mlflow.sklearn
    from mlflow.models import infer_signature

    if experiment_name not in {"assignment-iris-logistic", "assignment-iris-forest"}:
        raise ValueError("Experiment is outside the assignment allowlist")
    lineage = training_lineage(root)
    content = (root / DATASET).read_bytes()
    if hashlib.md5(content, usedforsecurity=False).hexdigest() != lineage["dataset_dvc_md5"]:
        raise ValueError("Dataset changed after lineage validation")
    data = prepare_split(content, config)
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_registry_uri(tracking_uri)
    mlflow.set_experiment(experiment_name)
    parameters = {
        **lineage,
        "classifier": config.classifier,
        "model_seed": config.model_seed,
        "split_seed": config.split_seed,
        "test_fraction": config.test_fraction,
        "split_sha256": data.split_sha256,
        "evaluation_id": data.evaluation_id,
        "evaluation_policy": EVALUATION_POLICY,
        "train_rows": len(data.train_indices),
        "test_rows": len(data.test_indices),
    }
    if config.classifier == "logistic":
        parameters["C"] = config.C
    else:
        parameters.update(max_depth=config.max_depth, n_estimators=config.n_estimators)
    with mlflow.start_run(tags={"assignment.training": "true"}) as run:
        mlflow.log_params(parameters)
        model = fit_classifier(data, config)
        metrics, predictions = evaluate_classifier(model, data)
        mlflow.log_metrics(metrics)
        mlflow.log_dict({**predictions, "evaluation_id": data.evaluation_id}, "evaluation.json")
        mlflow.log_dict({"parameters": parameters, "config": config.model_dump()}, "lineage.json")
        mlflow.log_dict(
            {"train": data.train_indices.tolist(), "test": data.test_indices.tolist()}, "split.json"
        )
        model_info = mlflow.sklearn.log_model(
            model,
            name="model",
            input_example=data.features[data.train_indices][:2],
            signature=infer_signature(
                data.features[data.train_indices], model.predict(data.features[data.train_indices])
            ),
            pip_requirements=[
                f"scikit-learn=={sklearn.__version__}",
                f"numpy=={np.__version__}",
                "cloudpickle==3.1.2",
            ],
        )
        mlflow.set_tag("assignment.model_id", model_info.model_id)
        return {
            "run_id": run.info.run_id,
            "experiment_id": run.info.experiment_id,
            "metrics": metrics,
            "model_id": model_info.model_id,
            "model_uri": model_info.model_uri,
            "evaluation_id": data.evaluation_id,
        }
