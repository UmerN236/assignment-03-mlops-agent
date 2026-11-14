# Airflow training workflow

`assignment_training` is a manually triggered Airflow **3.1.3 / Python 3.12**
TaskFlow DAG. It has no scheduled retraining. The conversational Airflow adapter
is a separate milestone; these commands are explicit engineering operations.

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
recovery creates a new run instead of rewriting history. Agent-facing tools with
approved-DAG input validation and explicit-trigger policy will be added separately.

Official implementation references: [Airflow 3.1.3 TaskFlow](https://airflow.apache.org/docs/apache-airflow/3.1.3/tutorial/taskflow.html),
[task and artifact practices](https://airflow.apache.org/docs/apache-airflow/3.1.3/best-practices.html),
[public API](https://airflow.apache.org/docs/apache-airflow/3.1.3/stable-rest-api-ref.html),
and [dependency isolation](https://airflow.apache.org/docs/apache-airflow/3.1.3/installation/installing-from-pypi.html).
The verifier also inspects the installed API/SDK, since current stable docs may
refer to newer versions.
