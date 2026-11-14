# Airflow training workflow

`assignment_training` is a manually triggered Airflow **3.1.3 / Python 3.12**
TaskFlow DAG. It has no scheduled retraining. Six agent-facing tools are available
below; the [conversational host](agent.md) binds training capability to the explicit
user request and confirmation. The build and DAG
verification commands here are explicit engineering operations.

```sh
make data-bootstrap
# Commit coherent source changes before recording exact code provenance.
make airflow-image
# Wait for the named service to be healthy, then run authorized smoke exercises:
make verify-airflow-dag
```

`airflow-image` inspects the dedicated Compose container's project ownership,
requires clean committed source and data matching the committed DVC hash, builds
a versioned image and recreates **only** `mlops-assignment3-airflow`. Existing
Airflow metadata/logs and MLflow artifacts remain in their dedicated named volumes.
The chosen image name is stored locally and reused by subsequent `make services`.
Fresh setup can first run the upstream base image; it has no training DAG until
the custom image is built. Rebuild after code changes to update the executed SHA.
No host `.env`, Git directory, provider keys or kubeconfig is copied into the image.

## Stages and persistence

| Task | Behavior | Persistent output |
| --- | --- | --- |
| `validation` | Strict 150-row schema, finite/ranged features, valid classes; checks data MD5 and image code SHA against prepared lineage | Immutable per-run dataset snapshot and DVC/Git lineage |
| `preprocessing` | Deterministic stratified split; scaling remains inside fitted training pipeline | NumPy arrays, split hash, evaluation cohort ID |
| `training` | Fit bounded configured logistic regression or random forest | Trusted local trained model |
| `evaluation` | Holdout metrics, predictions, MLflow model/signature, parameters and provenance | MLflow run/model IDs, evaluation result |
| `quality_gate` | Fixed multi-metric candidate policy; records pass/fail then fails task on rejection | `gate.json`, MLflow `quality_gate.json` and gate tag |
| `approve_candidate` | Requires all prior tasks successful plus matching local/remote passed-gate evidence | Per-workflow approval receipt and candidate tag; no production promotion |

All dependencies use `all_success`, including the final leaf. A failed ancestor
therefore makes the DAG fail and blocks candidate approval. Every task has one
retry, five-second retry delay, five-minute execution timeout and a hard
240-second subprocess deadline. MLflow requests use a 20-second timeout and zero
HTTP retries. Logs include stage/tool, status, duration and workflow request ID;
arbitrary subprocess stderr and error bodies are excluded.

Airflow uses its upstream dependency environment; hash-locked scientific packages
run in `/opt/training`. Large objects are kept under
`/opt/airflow/training/<sha256(workflow_run_id)>`, in the persistent Airflow volume.
The prepared input mount `/opt/project/input` is read-only; code and the DAG are
baked into the image with an exact committed SHA. XCom contains small stage
references only. This layout supports the single-container local executor; a
future distributed executor needs a shared object store or shared volume at the
same paths. Do not move tasks to independent workers with private disks.

Each workflow uses a stable MLflow run ID across evaluation retries; completed
results are reused. Partial attempts can leave unselected logged-model artifacts,
but have no approval. Split indices, evaluation cohort/policy, dataset DVC MD5,
dataset Git revision, code Git revision, classifier settings and sklearn version
are recorded. The MLflow artifact proxy serves model bytes over container-network
HTTP (`http://mlflow:5000`), so worker loads do not depend on host filesystem paths.

## Candidate policy and limitations

`iris-candidate-v1` requires **all**: macro F1 >= 0.90, accuracy >= 0.90,
log loss <= 0.35, finite metrics in valid ranges, and at least 45 held-out rows.
DAG configuration cannot override thresholds. Scaling is fitted on training rows
only. This is a demonstration candidate gate on repeatedly used Iris holdout data;
it does not assess drift, freshness, fairness, latency, independent-test quality
or production readiness. It neither changes registry aliases nor deploys an image.
Engineering deployment still requires an explicitly selected packaged model.

The verifier executes canonical smoke, an isolated malformed-column validation
fixture, weak regularization (`C=0.0001`) to exercise a genuine quality rejection,
and canonical recovery. The malformed fixture changes only in-memory bytes for
that workflow, preserving the DVC dataset. It inspects actual API terminal states,
retry attempts and logs, persistent gate/approval receipts, MLflow tags/metrics,
container-side artifact reload, unchanged registry versions and live deployed
identity. Successful completion exports `docs/evidence/airflow-dag-live.json`.
A verifier assertion failure retains observations in local storage and is not
passing evidence. The engineering command intentionally creates real runs;
ordinary `make check` uses mocks and never contacts these services.

## Authentication and review

The API binds to loopback port 8080. SimpleAuthManager is enabled, with its
all-admin bypass disabled. The engineer verifier exchanges the existing local
runtime admin password for an in-memory JWT at `/auth/token` and calls `/api/v2`.
It first proves unauthenticated DAG access is rejected. Explicit `AIRFLOW_TOKEN`
or `AIRFLOW_USERNAME` / `AIRFLOW_PASSWORD` configuration takes precedence. Neither
passwords nor JWTs are printed/exported. The generated password and Airflow volume
must remain private. SimpleAuthManager and standalone/SQLite are appropriate for
this isolated demonstration, not a production multi-user deployment.

In the Airflow UI, open `assignment_training` > Runs, select an actual exported
run ID, and inspect Graph and task attempt logs. Failure attempts remain available;
recovery creates a new run instead of rewriting history. Agent-facing tools enforce
the same fixed DAG boundary and explicit-trigger policy as described below.

Official implementation references: [Airflow 3.1.3 TaskFlow](https://airflow.apache.org/docs/apache-airflow/3.1.3/tutorial/taskflow.html),
[task and artifact practices](https://airflow.apache.org/docs/apache-airflow/3.1.3/best-practices.html),
[public API](https://airflow.apache.org/docs/apache-airflow/3.1.3/stable-rest-api-ref.html),
and [dependency isolation](https://airflow.apache.org/docs/apache-airflow/3.1.3/installation/installing-from-pypi.html).
The verifier also inspects the installed API/SDK, since current stable docs may
refer to newer versions.

## Agent-facing tools

`AirflowTools(settings).registry` registers six independently callable tools, each
with strict input schemas and the standard validated `ToolResult` envelope.
Relevant API response fields are validated separately; arbitrary `conf`, rendered
fields, notes, auth payloads and raw logs are omitted from evidence.

| Tool | Inputs beyond fixed `dag_id=assignment_training` | Observations / action |
| --- | --- | --- |
| `airflow_list_dags` | `limit` 1–50 (default 10) | Approved DAG pause/import-error states; API count and truncation |
| `airflow_list_runs` | `limit` 1–50 (default 10) | Actual recent runs, ordered by `-run_after`, state/timestamps |
| `airflow_get_run` | `dag_run_id`, `wait_seconds` 0–60 (default 0) | Actual run and task states, attempts, timing, terminal/poll-expiry flags |
| `airflow_trigger_training` | unique `agent__...` run ID, exact confirmation | POST canonical `conf={}` once; returns the server-observed run ID/state |
| `airflow_get_failed_tasks` | `dag_run_id` | Separates failed, upstream-blocked and retrying tasks |
| `airflow_get_task_diagnostics` | `dag_run_id`, approved `task_id`, `try_number` 1–10 (default 1) | Current task execution fields plus selected attempt's sanitized events |

The host must create `AirflowTools(settings, allow_trigger=True)` **only for an
explicit user training request**. This capability is not a model-supplied argument.
The tool additionally requires `confirmation="trigger assignment_training"` and
rejects other DAGs, arbitrary configuration, paths, map indexes and extra fields
before HTTP. Ordinary read clients reject triggers even with that confirmation.
The conversational host binds this capability to the user-supplied training mode
and confirmation; the literal tool argument alone cannot authorize it. Assessment
requests must use a read-only instance. Tools never unpause, backfill, clear tasks,
change registry aliases, deploy, or automatically initiate retraining.

```sh
# Choose a NEW unique run ID each time a new run is explicitly intended:
PYTHONPATH=src .venv/bin/python scripts/airflow-tool.py trigger_training --allow-trigger \
  --arguments '{"dag_run_id":"agent__UNIQUE_ID","confirmation":"trigger assignment_training"}'
# Use the real returned ID for all subsequent reads:
PYTHONPATH=src .venv/bin/python scripts/airflow-tool.py get_run \
  --arguments '{"dag_run_id":"ACTUAL_RETURNED_RUN_ID","wait_seconds":20}'
PYTHONPATH=src .venv/bin/python scripts/airflow-tool.py get_failed_tasks \
  --arguments '{"dag_run_id":"ACTUAL_RETURNED_RUN_ID"}'
PYTHONPATH=src .venv/bin/python scripts/airflow-tool.py get_task_diagnostics \
  --arguments '{"dag_run_id":"ACTUAL_RETURNED_RUN_ID","task_id":"validation","try_number":1}'
```

Authentication precedence: `AIRFLOW_TOKEN`, then `AIRFLOW_USERNAME` /
`AIRFLOW_PASSWORD`, then the generated SimpleAuthManager JSON configured with
`AIRFLOW_PASSWORD_FILE`. The default file is under `.local/runtime/airflow/` and
is used only when the base URL is exactly `http://127.0.0.1:8080`; remote services
require explicit credentials. No credential file or `.env` is modified. Password
exchange uses `/auth/token`; API requests use `Authorization: Bearer ...` at
`/api/v2`. Each call exchanges a fresh JWT if using a password. A rejected explicit
token never falls back to a different credential. No auth material is exported.

Every call runs in a subprocess with the configured `TOOL_TIMEOUT_SECONDS` hard
deadline (default 30, maximum 120); worker env excludes provider/cluster secrets.
HTTP phases have at most a ten-second timeout, redirects and ambient proxies are
disabled, and each response is capped at 1 MiB. GET retries once only for HTTP
502/503/504. No POST is retried, including token exchange. Rate limits,
auth rejection, malformed responses, missing resources and connection failures
produce sanitized typed errors. If a trigger times out or returns a server error,
its outcome can be unknown: query its supplied run ID before any further trigger.
A 409 means the ID exists; inspect it rather than creating another run blindly.

Polling must fit `max(0, min(60, TOOL_TIMEOUT_SECONDS - 5))` seconds; default zero is a
single read. Poll expiry retains the actual nonterminal observation and sets
`polling_timed_out=true`; a hard worker deadline returns unavailable without
invented task states. Tasks and run status are sequential observations, not an
atomic snapshot. Lists are bounded and report truncation; no automatic unbounded
pagination occurs. Task diagnostics return task facts with `log_status=unavailable`
if the log backend fails, rather than inventing logs. Logs are one bounded page
(`full_content=false`), indicate continuation, and export at most 100 known
stage/status/duration/request-ID events matching the requested run and task.
Inspect full logs privately in Airflow UI when these selected events do not
establish a root cause.

The live 3.1.3 API reported a negative duration for one successful task despite
ordered start/end timestamps. Tools preserve this reported number and flag
`negative_duration_reported=true`; its cause is unconfirmed. Do not use flagged
values for latency conclusions or silently replace them with computed durations.
See [actual tool verification and limitations](evidence/airflow-tools.md).

`make verify-airflow-tools` explicitly authorizes one real canonical run, verifies
unauthenticated rejection, checks installed OpenAPI paths, tests policy denials,
reads prior controlled failures and attempt logs, and observes its returned run ID
to successful termination. If verification stops after a trigger, inspect local
observations and use `scripts/verify-airflow-tools.py --resume` to continue the
same observed run without another write. The final export preserves any earlier
failed observation and explains repairs; it is not an LLM conversation transcript.
