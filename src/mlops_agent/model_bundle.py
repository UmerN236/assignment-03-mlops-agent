"""Validate a trusted, explicitly selected MLflow bundle before deserialization.

Hashes detect corruption; they do not make untrusted pickle safe. Only engineering
packaging may create bundles. The API accepts neither models nor artifact URIs.
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FEATURES = ("sepal_length", "sepal_width", "petal_length", "petal_width")
CLASSES = ("setosa", "versicolor", "virginica")
SHA = r"^[0-9a-f]{40}$"
HASH = r"^[0-9a-f]{64}$"


class DatasetReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    path: Literal["data/iris.csv"]
    git_revision: str = Field(pattern=SHA)
    dvc_md5: str = Field(pattern=r"^[0-9a-f]{32}$")


class ModelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    model_id: str = Field(pattern=r"^m-[0-9a-f]{32}$")
    model_sha256: str = Field(pattern=HASH)
    training_code_revision: str = Field(pattern=SHA)
    dataset: DatasetReference
    evaluation_id: str = Field(pattern=HASH)
    sklearn_version: Literal["1.7.2"] = "1.7.2"
    numpy_version: Literal["2.5.4"] = "2.5.4"
    cloudpickle_version: Literal["3.1.2"] = "3.1.2"


class BundleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    format_version: Literal[1] = 1
    selection: ModelSelection
    # Fixed filenames prevent paths in metadata from expanding filesystem access.
    files: dict[Literal["MLmodel", "model.pkl"], str]


def image_tag(revision: str, manifest: BundleManifest) -> str:
    """Bind image identity to source AND complete bundle provenance, not weights alone."""
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("A full source revision is required")
    canonical = json.dumps(manifest.model_dump(mode="json"), sort_keys=True).encode()
    identity = hashlib.sha256(canonical).hexdigest()
    return f"mlops-assignment3-inference:{revision[:12]}-{identity[:12]}"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest(directory: Path) -> BundleManifest:
    path = directory / "manifest.json"
    if path.is_symlink() or path.stat().st_size > 16384:
        raise ValueError("Invalid bundle manifest")
    return BundleManifest.model_validate(json.loads(path.read_text()))


def load_bundle(directory: Path, manifest: BundleManifest):
    """Load using MLflow's supported sklearn API only after integrity checks."""
    import cloudpickle
    import mlflow.sklearn
    import numpy as np
    import sklearn
    import yaml

    if set(manifest.files) != {"MLmodel", "model.pkl"}:
        raise ValueError("Incomplete model bundle")
    for name, expected in manifest.files.items():
        path = directory / name
        if (
            path.is_symlink()
            or not path.is_file()
            or not path.resolve().is_relative_to(directory.resolve())
            or path.stat().st_size > 10_000_000
            or file_sha256(path) != expected
        ):
            raise ValueError("Model artifact integrity check failed")
    selection = manifest.selection
    metadata = yaml.safe_load((directory / "MLmodel").read_text())
    if (
        metadata["run_id"] != selection.run_id
        or metadata["model_id"] != selection.model_id
        or metadata["flavors"]["sklearn"]["pickled_model"] != "model.pkl"
        or metadata["flavors"]["sklearn"]["code"] is not None
        or metadata["flavors"]["sklearn"]["serialization_format"] != "cloudpickle"
        or metadata["flavors"]["sklearn"]["sklearn_version"] != selection.sklearn_version
        or manifest.files["model.pkl"] != selection.model_sha256
        or sklearn.__version__ != selection.sklearn_version
        or np.__version__ != selection.numpy_version
        or cloudpickle.__version__ != selection.cloudpickle_version
    ):
        raise ValueError("Model provenance or runtime mismatch")
    model = mlflow.sklearn.load_model(str(directory))
    if model.n_features_in_ != 4 or list(model.classes_) != [0, 1, 2]:
        raise ValueError("Model schema mismatch")
    # Exercise the real prediction path before reporting readiness.
    predict(model, [[5.0, 3.5, 1.4, 0.2]])
    return model


def predict(model, rows: list[list[float]]) -> tuple[list[int], list[list[float]]]:
    import numpy as np

    values = np.asarray(rows, dtype=np.float64)
    labels = np.asarray(model.predict(values))
    probabilities = np.asarray(model.predict_proba(values))
    if (
        labels.shape != (len(rows),)
        or not np.isin(labels, [0, 1, 2]).all()
        or probabilities.shape != (len(rows), 3)
        or not np.isfinite(probabilities).all()
        or not ((probabilities >= 0) & (probabilities <= 1)).all()
        or not np.allclose(probabilities.sum(axis=1), 1)
    ):
        raise ValueError("Invalid model output")
    return labels.astype(int).tolist(), probabilities.tolist()
