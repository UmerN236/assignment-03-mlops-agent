# MLOps AI Agent

An evidence-backed Python operations agent for DVC dataset provenance, MLflow
experiment comparison, Airflow 3 training workflows and Kubernetes diagnosis.
It uses native structured tool calls through the configured free OpenRouter
model. Responses separate observed facts, unknowns and recommendations.

The four service adapters and the integrated read-only conversation are
implemented and live-verified. See [architecture](architecture.md),
[acceptance checklist](docs/requirements.md), [reliability audit](docs/reliability.md)
and [five tested conversations](docs/evidence/conversations/README.md). The
[technical report](docs/report.md), [failure investigations](docs/failure-investigations.md),
[defense guide](docs/defense.md) and [fresh-checkout procedure](docs/reproduction.md)
complete the submission documentation. Evidence records observations
at their timestamps, rather than guaranteeing current service health.

## Install and test

Run commands from the repository root. The local tool installer supports **Apple
Silicon macOS** and requires Git, curl, make and a running Docker Desktop for live
services. It installs checksum-verified binaries inside the checkout. Python
3.12.12 and uv 0.9.9 are pinned; Airflow has its own Python 3.12 container runtime.

```sh
make tools
make setup                  # project-local Python and frozen uv.lock
# Preserve any existing configuration:
test -e .env || cp .env.example .env
make config                 # presence booleans only; never prints keys
make check                  # Ruff lint + format check + pytest
make verify-submission      # offline evidence/fact-reference acceptance check
```

Tests require neither Docker nor live API credentials. All external service
transports are mocked. Shared fixtures clear application environment overrides
and reject in-process IPv4/IPv6 TCP connections, including loopback; local sklearn
training/serialization and in-process ASGI tests still run. This guard does not
sandbox child processes. Live verification scripts are separate, explicit commands.

On Linux with uv 0.9.9 installed:

```sh
uv lock --check              # fail if metadata and resolution disagree
uv sync --frozen --python 3.12.12
make check UV=uv
```

[Pull-request CI](.github/workflows/ci.yaml) runs these lock/install/check steps
on Ubuntu 24.04, using SHA-pinned Node 24 actions, a read-only repository token
and no service credentials. New pushes cancel an obsolete check for the same
ref. The same `make check` target runs locally and in Actions. Inspect actual
[Actions runs](https://github.com/UmerN236/assignment-03-mlops-agent/actions)
for the revision being reviewed; an earlier green run does not validate new code.
Dependency changes require an intentional `uv lock` and lockfile review.

## Configure and start services

Edit only needed entries in the existing ignored `.env`. Set
`LLM_PROVIDER=openrouter`, `OPENROUTER_API_KEY` and a configured free route such as
`OPENROUTER_MODEL=openrouter/free`. `LLM_MODEL` overrides provider-specific model
names. The adapter checks current account/model metadata and requires free
pricing and native tool support; no paid/provider fallback exists. Empty entries
use defaults. Missing keys leave the live conversation unavailable while tests
and independent service work can continue. The Gemini adapter is unimplemented.

For an existing assignment checkout, these commands preserve its runtime state:

```sh
make services               # dedicated MLflow + Airflow Compose services
make data-bootstrap         # verify recipe/hash, populate DVC cache/local remote
make cluster                # create/reuse only the dedicated kind cluster
make smoke                  # real read-only service/auth/cluster observations
```

| Component | Address / state | Setup and review |
| --- | --- | --- |
| DVC | `data/iris.csv.dvc`, ignored `.local/dvc-remote` | [Recipe, historical restore and remote access](docs/data.md) |
| MLflow 3.6.0 | `http://127.0.0.1:5000`; dedicated Docker volume | [Training, runs, metrics, models and lineage](docs/mlflow.md) |
| Airflow 3.1.3 | `http://127.0.0.1:8080`; dedicated metadata/log volume | [Authenticated API, DAG and diagnostics](docs/airflow.md) |
| Inference | Two replicas, ClusterIP `inference:8000` in `mlops-agent` | [Model packaging](docs/inference.md), [deployment and RBAC](docs/kubernetes.md) |
| Conversational API | `http://127.0.0.1:8090` after `make agent-api` | [API, schemas, bounds and permissions](docs/agent.md) |

Airflow uses SimpleAuthManager with authentication enabled. Bootstrap creates a
random admin password only when absent, in ignored local runtime storage. Clients
exchange it for an in-memory JWT and use `/api/v2`; smoke checks prove anonymous
access is denied. Explicit `AIRFLOW_TOKEN` or `AIRFLOW_USERNAME`/`AIRFLOW_PASSWORD`
take precedence. Never print or export password/token files.

`make cluster` uses `mlops-assignment3`, context `kind-mlops-assignment3` and
namespace `mlops-agent`, with engineer kubeconfig `.local/kubeconfig`. It does
not switch the global context. Agent tools use only `.local/kubeconfig-agent`
(or `KUBERNETES_READONLY_KUBECONFIG`), with no administrator fallback. Its token
expires; the [deployment runbook](docs/kubernetes.md) explains refresh/setup.
`make services` reuses the locally selected custom Airflow image if present.

## Populate a fresh environment

Data regeneration needs no remote download: `make data-bootstrap` verifies the
committed v2 MD5 before populating the local DVC remote. Historical recovery uses
an isolated checkout and that revision's recipe or an authorized object store.
The local remote is not uploaded to GitHub.

After services and data are ready, the following are **explicit engineering
writes**, separate from read-only agent assessment:

```sh
make train-models           # five real runs across two experiments; preserves history
make verify-mlflow          # inspect actual runs, metrics, artifacts and registry
make airflow-image         # build committed code + training runtime; recreate only Airflow
make smoke                  # wait for healthy services before workflow operations
```

Image builds require clean committed code so recorded Git SHAs identify the
executed source. The initial Airflow base service has no training DAG until
`make airflow-image`. Its stages are validation -> preprocessing -> training ->
evaluation/MLflow -> quality gate -> candidate approval, with retries and
persistent artifacts. Validation/gate failure blocks approval. No automatic
registry promotion or deployment occurs.

Default packaging preserves the historical
[`model-selection.json`](infra/inference/model-selection.json). A fresh machine
can instead explicitly select a newly trained, trusted run without editing
historical IDs or manifests. Follow [fresh-checkout reproduction](docs/reproduction.md):
`select-model.py --run-id ACTUAL_RUN_ID`, package with its ignored local selection,
build, verify, and deploy. The image tag identifies both committed source and
complete model-bundle provenance. Deployment imports the exact verified image ID and renders its tag
into a local manifest copy. New training never silently changes deployment.

Live verifiers write sanitized exports and may refuse an existing different
owned image or changed bundle. Inspect those failures; do not erase existing
runtime state to make a command pass. `make verify-airflow-dag` deliberately
creates smoke, isolated malformed-input, quality-gate-failure and recovery runs.
`make verify-airflow-tools` authorizes one canonical training run; use its
`--resume` option after an interrupted observation to avoid a duplicate trigger.
These commands are not part of ordinary CI.

## Talk to the agent

With configured services and a free provider key:

```sh
make agent                  # mandatory read-only all-four-service assessment
PYTHONPATH=src .venv/bin/python scripts/agent.py \
  'Read inference deployment health and application version' --mode query
make agent-api              # foreground, loopback port 8090; separate terminal
```

In another terminal:

```sh
curl -sS http://127.0.0.1:8090/livez
curl -sS http://127.0.0.1:8090/chat \
  -H 'Content-Type: application/json' \
  -d '{"mode":"assessment","message":"Find the best recent model, identify the dataset version used to train it, check the deployment status, and explain whether retraining is necessary."}'
```

`/docs` provides request/response schemas. `/livez` proves process liveness only.
`/chat` returns actual tool observations, request ID, correlated lineage and
known/unknown/recommendation fields. Partial/unavailable conversations return 503
and retain prior evidence; invalid requests return sanitized 422. CLI exits
nonzero for partial results. Provider quota, model availability and deadlines can
cause failure; there is no automatic paid retry. `make verify-agent` spends live
free quota. To validate an existing real conversation without a provider request:

```sh
PYTHONPATH=src .venv/bin/python scripts/verify-agent.py --from-json docs/evidence/agent-live.json
```

Query and assessment expose read tools only: DVC 7, MLflow 7, Kubernetes 5,
Airflow 5. Training requires user-supplied `--mode trigger_training` plus exact
`--confirmation 'trigger assignment_training'`; see [training example and
policy](docs/agent.md#permissions-and-retraining). A model cannot authorize itself.
Kubernetes writes are unsupported and rejected. Highest F1, historical controlled
failures or a candidate/deployed mismatch do not establish retraining necessity;
the agent reports missing freshness/degradation evidence and never retrains
from the mandatory assessment.

## Inspect services directly

Each adapter has at least three individually callable tools. Examples:

```sh
make data-status
PYTHONPATH=src .venv/bin/python scripts/dvc-tool.py --schemas
PYTHONPATH=src .venv/bin/python scripts/dvc-tool.py dvc_get_dataset_version '{}'
PYTHONPATH=src .venv/bin/python scripts/mlflow-tool.py mlflow_list_experiments '{}'
PYTHONPATH=src .venv/bin/python scripts/airflow-tool.py list_runs --arguments '{"limit":5}'
PYTHONPATH=src .venv/bin/python scripts/kubernetes-tool.py workloads
PYTHONPATH=src .venv/bin/python scripts/kubernetes-tool.py health
```

Use actual returned experiment/run/Pod IDs for follow-up reads. Complete schemas,
metric direction/cohort rules and timeout/error behavior are in the linked
service runbooks. For inference HTTP review, use the explicit loopback
port-forward in [Kubernetes setup](docs/kubernetes.md), then `/readyz`, `/version`
and the named-feature `/predict` example in [inference setup](docs/inference.md).

The repository is public. [Submission instructions](SUBMISSION.md) identify the
reviewed tag and all required deliverables. `.env`, credentials, kubeconfigs,
local notes and runtime artifacts stay ignored. Public Git access does not
provide local MLflow volumes or the DVC object store; use the documented fresh
reproduction procedure. [Development notes](docs/development.md) describe
container paths, version decisions and limitations.
