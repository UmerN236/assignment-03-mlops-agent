"""Explicit engineering batch: five real runs in two approved experiments."""

import json
import os
from pathlib import Path

from mlflow import MlflowClient

from mlops_agent.config import load_settings
from mlops_agent.mlflow_tools import ClientReader, SelectionInput
from mlops_agent.training import TrainingConfig, train_and_log

root = Path(__file__).resolve().parents[1]
settings = load_settings()
os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"] = "30"
os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] = "0"
os.environ["MLFLOW_ENABLE_ASYNC_LOGGING"] = "false"
output = root / ".local/mlflow-training.json"
if output.exists():
    raise SystemExit("Existing batch evidence preserved; inspect before running another batch")
observations = {"runs": []}
configs = [TrainingConfig(C=c) for c in (0.1, 1.0, 10.0)] + [
    TrainingConfig(classifier="forest", max_depth=depth) for depth in (2, 4)
]
for config in configs:
    run = train_and_log(
        root, settings.mlflow_tracking_uri, f"assignment-iris-{config.classifier}", config
    )
    observations["runs"].append(run)
    output.write_text(json.dumps(observations, indent=2) + "\n")
    print(json.dumps(run), flush=True)

client = MlflowClient(
    tracking_uri=settings.mlflow_tracking_uri, registry_uri=settings.mlflow_tracking_uri
)
reader = ClientReader(client)
args = SelectionInput(
    experiment_ids=sorted({r["experiment_id"] for r in observations["runs"]}),
    direction="maximize",
    limit=5,
)
selection = reader.selection(args)
assert selection["comparable"] and len(selection["runs"]) == 5
candidate = selection["selected_run"]
name = "assignment-iris"
if not client.search_registered_models(filter_string=f"name = '{name}'", max_results=1):
    client.create_registered_model(
        name, description="Assignment candidate; not a production approval"
    )
version = client.create_model_version(
    name,
    f"models:/{candidate['model_id']}",
    run_id=candidate["run_id"],
    model_id=candidate["model_id"],
    await_creation_for=30,
    description="Best F1 in the recorded five-run cohort; requires independent validation",
)
observations["registered_candidate"] = {
    "name": name,
    "version": version.version,
    "status": version.status,
    "run_id": version.run_id,
    "source": version.source,
}
output.write_text(json.dumps(observations, indent=2) + "\n")
print(json.dumps(observations["registered_candidate"]))
