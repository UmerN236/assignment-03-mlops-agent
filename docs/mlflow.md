# Deterministic training and MLflow tools

The MLflow 3.6.0 tracking server uses a dedicated SQLite backend and native Docker
volume, with HTTP artifact serving enabled. Clients use `MlflowClient` and supported
MLflow logging/model APIs. No UI parsing is involved. All operations described
here are for this assignment's local tracking service.

## Reproduce training

After `make setup`, `make services`, and `make data-bootstrap`, commit any code or
dataset-metadata edits, then run:

```sh
make train-models
make verify-mlflow
PYTHONPATH=src .venv/bin/python scripts/verify-dvc.py --output docs/evidence/dvc-v2.json
```

The explicit engineering batch creates five real runs: standardized logistic
regression with C 0.1, 1 and 10 in `assignment-iris-logistic`, and random forests
with maximum depth 2 and 4 (100 trees) in `assignment-iris-forest`. It records
progress in ignored local storage and refuses to overwrite a previous batch's
evidence. Before intentionally repeating the batch, preserve/move that local
record. Existing MLflow runs are retained. Training is not an agent read tool.

Dataset v2 simulates coarser sepal measurements; see [data operations](data.md).
Validation requires the exact CSV schema, 150 complete finite positive rows,
features below 20, labels 0/1/2 and sufficient class counts. A stratified 70/30
split with seed 42 produces 105 training and 45 evaluation rows, 15 evaluation
examples per class. The scaler is fitted on training rows only. Both families
use model seed 42; forest fitting uses one worker. Evaluation records accuracy,
macro F1 (all three labels, zero division = 0), and multiclass log loss.

Every run stores the DVC path/hash, dataset Git revision, actual committed code
SHA, split/model seed, split indices/hash, evaluation cohort ID, classifier
parameters, library version, row counts and metric policy. It logs evaluation
predictions/probabilities/confusion matrix, lineage/config and split JSON, plus a
schema-annotated sklearn model and input example with pinned loading dependencies.
Training refuses mismatched DVC bytes and an uncommitted working tree. A
SHA-256 evaluation ID binds content bytes, split indices and metric policy.

MLflow 3 stores logged models separately from run artifacts: the run contains
`assignment.model_id`, and inspection uses `get_logged_model` and
`list_logged_model_artifacts` alongside `list_artifacts`. The selected F1
candidate is registered under `assignment-iris`, without promotion or a production
alias. Registration is engineering setup, never an automatic agent operation.

## Individually callable read tools

```sh
PYTHONPATH=src .venv/bin/python scripts/mlflow-tool.py --schemas
PYTHONPATH=src .venv/bin/python scripts/mlflow-tool.py mlflow_list_experiments '{}'
# Replace IDs with actual experiment IDs returned by the previous call:
PYTHONPATH=src .venv/bin/python scripts/mlflow-tool.py mlflow_compare_runs \
  '{"experiment_ids":["1","2"],"limit":5,"metric":"f1_macro","direction":"maximize"}'
```

| Tool | Inputs | Observation |
| --- | --- | --- |
| `mlflow_list_experiments` | bounded `limit` | Experiment IDs, names, artifact locations |
| `mlflow_list_runs` | experiment IDs, limit, recent hours | Newest assignment training runs, status, metrics, allowed provenance parameters |
| `mlflow_get_run` | run ID | Metrics, parameters, run artifact metadata, logged model metadata/files |
| `mlflow_select_best` | run-search inputs, metric, direction, optional evaluation ID | Eligible candidate, ranking, exclusions and limitations |
| `mlflow_compare_runs` | same as selection; default limit 5 | Last-N comparison with explicit evaluation caveats |
| `mlflow_compare_experiments` | at least two distinct experiment IDs plus selection inputs | Cross-experiment recent counts and comparable run ranking |
| `mlflow_model_versions` | assignment model name, limit | Actual registered versions, source, run, status and aliases; explains empty result |

Run searches include only `assignment.training=true`, newest first, within an
explicit recent window (default seven days). They expose pagination/truncation;
selection is limited to that returned window, not a claim about all history.
A global last-N window can omit an experiment. Eligible candidates must be
finished, have a logged model reference, complete evaluation lineage and a finite
requested metric. Selection honors explicit `maximize` or `minimize`. Ties prefer
the newest run, then lexical run ID. Different data/split/policy cohorts are
returned for inspection with **no global winner**; specify an evaluation ID to
narrow selection. Recorded provenance fields are checked as well as the cohort
label, preventing a mislabeled ID from authorizing a cross-split ranking.

The same small held-out split is used repeatedly for candidate selection, which
introduces selection bias. This is not an independent final test, a drift test,
latency validation, production quality gate or evidence that retraining is needed.
Highest F1 alone establishes none of those conditions. Registry READY means the
version exists, not that a deployment is healthy or approved.

Each call uses an isolated Python worker with a hard total timeout, fixed argv,
no shell, no provider credentials and zero MLflow HTTP retries. Worker stderr
and exception bodies are never returned; failures produce explicit unavailable
or error envelopes with no inferred metrics. Inputs are bounded and validated
before invocation. Logs contain tool name/status/duration/request ID. No registry
write, training trigger or arbitrary artifact-download tool is exposed to agents.

The DVC CLI now wires `MlflowTools.run_params` into `dvc_resolve_mlflow_run`.
That read retrieves real run parameters before checking the committed DVC pointer.
The live verifier checks this correlation, both metric directions, all five
runs' artifact metadata, registry state, downloaded candidate predictions and
HTTP model bytes from inside the Airflow container. Airflow dependency installation
and inference-image loading belong to later milestones; do not infer them from
successful HTTP transport.

Official references: [MlflowClient API](https://mlflow.org/docs/latest/api_reference/python_api/mlflow.client.html),
[MLflow 3 model changes](https://mlflow.org/docs/latest/ml/mlflow-3), and
[artifact proxy architecture](https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/).
The installed 3.6.0 signatures and live server are verified; current documentation
can describe newer releases. In 3.6, artifact factories also consult the fluent
tracking URI despite an explicit client URI. The isolated worker sets both;
a real failed listing exposed this and a regression test covers the repair.
See [live results](evidence/mlflow.md) and the [actual tool export](evidence/mlflow-live.json).
