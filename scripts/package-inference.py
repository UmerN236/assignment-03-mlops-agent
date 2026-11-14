"""Fetch only the explicit candidate over MLflow HTTP, validate and stage a bundle.

Run as a bounded engineering subprocess (make package-inference). Never exposes
model selection, downloads, or deserialization as a public API operation.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path

import mlflow
from mlflow import MlflowClient

from mlops_agent.config import load_settings
from mlops_agent.model_bundle import BundleManifest, ModelSelection, file_sha256, load_bundle


def main():
    root = Path(__file__).resolve().parents[1]
    selection = ModelSelection.model_validate_json(
        (root / "infra/inference/model-selection.json").read_text()
    )
    settings = load_settings()
    os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] = "20"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] = "0"
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_registry_uri(settings.mlflow_tracking_uri)
    client = MlflowClient(settings.mlflow_tracking_uri)
    run = client.get_run(selection.run_id)
    expected_params = {
        "dataset_path": selection.dataset.path,
        "dataset_git_revision": selection.dataset.git_revision,
        "dataset_dvc_md5": selection.dataset.dvc_md5,
        "code_git_revision": selection.training_code_revision,
        "evaluation_id": selection.evaluation_id,
        "sklearn_version": selection.sklearn_version,
    }
    if (
        run.info.status != "FINISHED"
        or any(run.data.params.get(k) != v for k, v in expected_params.items())
        or run.data.tags.get("assignment.model_id") != selection.model_id
        or client.get_logged_model(selection.model_id).source_run_id != selection.run_id
    ):
        raise ValueError("Selected run does not match the approved provenance")
    destination = root / "artifacts/inference"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError("Bundle destination must not be a symlink")
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix="package-") as work:
        staged = Path(work) / "bundle"
        staged.mkdir()
        downloaded = Path(
            mlflow.artifacts.download_artifacts(
                artifact_uri=f"models:/{selection.model_id}", dst_path=str(Path(work) / "download")
            )
        )
        for name in ("MLmodel", "model.pkl"):
            source = downloaded / name
            if source.is_symlink() or not source.is_file():
                raise ValueError("Expected a regular model artifact")
            shutil.copyfile(source, staged / name)
        manifest = BundleManifest(
            selection=selection,
            files={name: file_sha256(staged / name) for name in ("MLmodel", "model.pkl")},
        )
        load_bundle(staged, manifest)
        (staged / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n")
        if destination.exists():
            if set(p.name for p in destination.iterdir()) != {
                "MLmodel",
                "model.pkl",
                "manifest.json",
            }:
                raise ValueError("Refusing to replace an unexpected existing bundle")
            if any((destination / p.name).read_bytes() != p.read_bytes() for p in staged.iterdir()):
                raise ValueError("Refusing to replace a different existing bundle")
        else:
            staged.rename(destination)
    print(json.dumps({"status": "packaged", "model_run_id": selection.run_id}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # External exceptions may contain connection strings or artifact paths.
        raise SystemExit(
            f"Model packaging failed ({type(exc).__name__}); no bundle promoted"
        ) from None
