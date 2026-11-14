"""Read actual tracking/registry state, resolve lineage and verify artifact transport."""

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import mlflow
import mlflow.sklearn
from mlflow import MlflowClient

from mlops_agent.config import load_settings
from mlops_agent.dataset import DATASET
from mlops_agent.dvc_tools import DvcTools
from mlops_agent.mlflow_tools import MlflowTools
from mlops_agent.training import TrainingConfig, evaluate_classifier, prepare_split

root = Path(__file__).resolve().parents[1]
settings = load_settings()
os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] = "20"
os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] = "0"
mlflow.set_tracking_uri(settings.mlflow_tracking_uri)
mlflow.set_registry_uri(settings.mlflow_tracking_uri)
adapter = MlflowTools(settings.mlflow_tracking_uri)
client = MlflowClient(
    tracking_uri=settings.mlflow_tracking_uri, registry_uri=settings.mlflow_tracking_uri
)
observations = []


def observe(registry, name, args):
    result = registry.call(name, args)
    observations.append(result.model_dump(mode="json"))
    if result.status != "ok":
        raise RuntimeError(f"Live verification failed: {name}: {result.error}")
    return result.evidence


experiments = observe(adapter.registry, "mlflow_list_experiments", {})["experiments"]
ids = sorted(
    e["experiment_id"]
    for e in experiments
    if e["name"] in {"assignment-iris-logistic", "assignment-iris-forest"}
)
assert len(ids) == 2
arguments = {"experiment_ids": ids, "limit": 5, "direction": "maximize", "metric": "f1_macro"}
runs = observe(adapter.registry, "mlflow_list_runs", {"experiment_ids": ids})["runs"]
assert len(runs) == 5 and all(r["status"] == "FINISHED" for r in runs)
comparison = observe(adapter.registry, "mlflow_compare_runs", arguments)
assert comparison["comparable"] and len(comparison["ranking"]) == 5
experiment_comparison = observe(adapter.registry, "mlflow_compare_experiments", arguments)
assert all(e["recent_run_count"] for e in experiment_comparison["experiments"])
selected = observe(adapter.registry, "mlflow_select_best", arguments)["selected_run"]
loss = observe(
    adapter.registry,
    "mlflow_select_best",
    {**arguments, "metric": "log_loss", "direction": "minimize"},
)
assert loss["selected_run"]["metrics"]["log_loss"] == min(r["metrics"]["log_loss"] for r in runs)
details = []
for run in runs:
    detail = observe(adapter.registry, "mlflow_get_run", {"run_id": run["run_id"]})
    assert {f["path"] for f in detail["artifacts"]} >= {
        "evaluation.json",
        "lineage.json",
        "split.json",
    }
    assert detail["logged_model"]["source_run_id"] == run["run_id"]
    assert {f["path"] for f in detail["logged_model"]["artifacts"]} >= {"MLmodel", "model.pkl"}
    details.append(detail)
versions = observe(adapter.registry, "mlflow_model_versions", {})["versions"]
assert any(v["run_id"] == selected["run_id"] and v["status"] == "READY" for v in versions)
dvc = DvcTools(root, run_lookup=adapter.run_params)
lineage = observe(dvc.registry, "dvc_resolve_mlflow_run", {"run_id": selected["run_id"]})
assert lineage["reference_matches"] and lineage["run_record_verified"]
previous = "6193fbd83e994dec9607a61c46134cd7654b845f"
diff = observe(
    dvc.registry,
    "dvc_compare_versions",
    {"old_revision": previous, "new_revision": selected["parameters"]["dataset_git_revision"]},
)
assert diff["changes"].get("modified")

destination = root / ".local/artifact-verification" / selected["run_id"]
destination.mkdir(parents=True, exist_ok=True)
local_model = mlflow.artifacts.download_artifacts(
    artifact_uri=f"models:/{selected['model_id']}", dst_path=str(destination)
)
model_bytes = (Path(local_model) / "model.pkl").read_bytes()
loaded = mlflow.sklearn.load_model(local_model)
params = selected["parameters"]
data = prepare_split(
    (root / DATASET).read_bytes(),
    TrainingConfig(
        split_seed=int(params["split_seed"]), test_fraction=float(params["test_fraction"])
    ),
)
metrics, _ = evaluate_classifier(loaded, data)
assert all(abs(metrics[k] - selected["metrics"][k]) < 1e-12 for k in metrics)

# Airflow has no MLflow/sklearn dependencies yet. Verify real HTTP model-byte
# access inside that container; model execution in future images is a later check.
location = client.get_logged_model(selected["model_id"]).artifact_location
parsed = urlsplit(location)
assert parsed.scheme == "mlflow-artifacts" and not parsed.netloc
uri = (
    "http://mlflow:5000/api/2.0/mlflow-artifacts/artifacts/"
    + parsed.path.lstrip("/")
    + "/model.pkl"
)
name = "mlops-assignment3-airflow"
inspection = subprocess.run(
    ["docker", "inspect", "--format", "{{.Name}}", name],
    capture_output=True,
    text=True,
    timeout=10,
    check=True,
)
assert inspection.stdout.strip() == f"/{name}"
script = (
    "import hashlib,json,urllib.request\n"
    f"content=urllib.request.urlopen({uri!r},timeout=15).read()\n"
    "print(json.dumps({'sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}))\n"
)
result = subprocess.run(
    ["docker", "exec", "-i", name, "python", "-"],
    input=script,
    capture_output=True,
    text=True,
    timeout=25,
    check=True,
)
inside = json.loads(result.stdout)
assert inside["sha256"] == hashlib.sha256(model_bytes).hexdigest()
export = {
    "observed_at": datetime.now(UTC).isoformat(),
    "mlflow_version": mlflow.__version__,
    "training_code_sha": params["code_git_revision"],
    "dataset_git_revision": params["dataset_git_revision"],
    "dataset_dvc_md5": params["dataset_dvc_md5"],
    "evaluation_id": data.evaluation_id,
    "candidate_run_id": selected["run_id"],
    "artifact_reload_metrics": metrics,
    "artifact_http_from_airflow": inside,
    "container_limitation": (
        "Verified model bytes over HTTP; Airflow training dependencies and inference image pending"
    ),
    "observations": observations,
}
output = root / "docs/evidence/mlflow-live.json"
output.write_text(json.dumps(export, indent=2) + "\n")
print(
    json.dumps(
        {
            "checks": "passed",
            "evidence": str(output.relative_to(root)),
            "runs": len(runs),
            "experiments": len(ids),
            "candidate_run_id": selected["run_id"],
        }
    )
)
