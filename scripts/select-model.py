"""Explicit engineering selection of a real run in the configured tracking store.

Writes ignored local metadata, never silently replaces the checked-in historical
selection. Run this only for a model trained in a trusted assignment environment.
"""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path

import cloudpickle
import mlflow
import numpy as np
from mlflow import MlflowClient

from mlops_agent.config import load_settings
from mlops_agent.model_bundle import DatasetReference, ModelSelection, file_sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, default=Path(".local/model-selection.json"))
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{32}", args.run_id):
        parser.error("Use an actual full training run ID")
    if args.output.exists():
        parser.error("Selection exists; choose a new output file to preserve it")
    settings = load_settings()
    os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] = "20"
    os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] = "0"
    mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
    mlflow.set_registry_uri(settings.mlflow_tracking_uri)
    client = MlflowClient(settings.mlflow_tracking_uri)
    run = client.get_run(args.run_id)
    model_id = run.data.tags.get("assignment.model_id", "")
    if run.info.status != "FINISHED" or not re.fullmatch(r"m-[0-9a-f]{32}", model_id):
        raise ValueError("A completed run with a recorded model is required")
    if client.get_logged_model(model_id).source_run_id != args.run_id:
        raise ValueError("Logged model source run does not match")
    params = run.data.params
    with tempfile.TemporaryDirectory() as work:
        directory = Path(
            mlflow.artifacts.download_artifacts(artifact_uri=f"models:/{model_id}", dst_path=work)
        )
        selection = ModelSelection(
            run_id=args.run_id,
            model_id=model_id,
            model_sha256=file_sha256(directory / "model.pkl"),
            training_code_revision=params["code_git_revision"],
            dataset=DatasetReference(
                path=params["dataset_path"],
                git_revision=params["dataset_git_revision"],
                dvc_md5=params["dataset_dvc_md5"],
            ),
            evaluation_id=params["evaluation_id"],
            sklearn_version=params["sklearn_version"],
            numpy_version=np.__version__,
            cloudpickle_version=cloudpickle.__version__,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(selection.model_dump_json(indent=2) + "\n")
    print(json.dumps({"selection": str(args.output), "run_id": selection.run_id}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        raise SystemExit(f"Explicit model selection failed ({type(error).__name__})") from None
