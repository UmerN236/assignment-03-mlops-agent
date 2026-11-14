# Reproducible development and bootstrap

## Versions and isolation

- Python **3.12.12**, uv **0.9.9**, full transitive resolution in `uv.lock`.
- Agent: DVC **3.64.0**, MLflow **3.6.0**, scikit-learn **1.7.2**, FastAPI
  **0.121.1**, Pydantic **2.12.4**, Kubernetes client **34.1.0**; all direct
  dependencies are pinned in `pyproject.toml`.
- Airflow **3.1.3**, official **Python 3.12** container, isolated from the agent's
  dependencies. Its upstream environment is fixed by image digest; the custom
  training image adds a separate hash-locked scientific environment at `/opt/training`.
- kind **0.30.0**, kubectl **1.34.0**, Kubernetes node **1.34.0** with the kind
  release's published image digest. The cluster runs two inference replicas;
  Airflow uses its local executor in the separate Compose service.

Airflow's [version-specific prerequisites](https://airflow.apache.org/docs/apache-airflow/3.1.3/installation/prerequisites.html)
include Python 3.12. The
[3.1.3 token route implementation](https://github.com/apache/airflow/blob/3.1.3/airflow-core/src/airflow/api_fastapi/auth/managers/simple/routes/login.py)
accepts a credentialed `POST /auth/token`; the resulting bearer token authenticates
the version 3 public API. The no-credential all-admins mode is explicitly disabled.
The [kind release](https://github.com/kubernetes-sigs/kind/releases/tag/v0.30.0)
provides the selected Kubernetes image digest. Tool archive hashes were obtained
from the official release asset metadata (uv/kind) and `dl.k8s.io` (kubectl), and
are fixed in the installer rather than trusting a newly downloaded checksum.

The host agent environment deliberately excludes Airflow. The bootstrap uses
Airflow's standalone development installation with SQLite on a dedicated Docker
volume. A macOS bind mount produced a real SQLite locking-protocol failure during
bootstrap, so metadata must remain on Docker's Linux filesystem. Initialization
preserves any previous bootstrap state. This is a local demonstration, not a
production scheduler architecture.

## Files and commands

`make setup` keeps managed Python, uv cache, and tools in ignored `.local/`; only
`.venv/` sits at the workspace root. Native TLS verification stays enabled, and
copy linking avoids macOS file-cloning failures in restricted workspaces. The
installer currently targets Darwin arm64. On Linux with uv 0.9.9 already available,
run `uv lock --check`, `uv sync --frozen --python 3.12.12`, then
`make check UV=uv`. CI uses Ubuntu 24.04 and these same checks, with SHA-pinned
Node 24 [checkout](https://github.com/actions/checkout/tree/v5) and
[setup-uv](https://github.com/astral-sh/setup-uv/tree/v7) actions. It needs neither
Docker nor API keys. Shared pytest fixtures remove application settings from the
process environment and block in-process TCP connections, including localhost;
service calls use mocks while sklearn and ASGI tests execute locally. This is a
test guard, not a network sandbox for subprocesses. Dependency changes require an
intentional `uv lock` and review of the updated lockfile; normal setup uses `--frozen`.

`make services` uses a fixed Compose project and container names with the
`mlops-assignment3` prefix. It does not import `.env` into Compose. Runtime preparation
creates a random Airflow password with mode 0600 only when absent. Existing `.env`
and passwords are preserved. Use `make services` again after Docker restarts;
containers are intentionally not configured as system services. After
`make airflow-image`, the chosen versioned image is preserved locally and reused
by `make services`. See [training workflow setup](airflow.md) before triggering runs.

| Host path/address | Container path/address | Purpose |
| --- | --- | --- |
| Docker volume `mlops-assignment3-mlflow-data` | `/mlflow` | SQLite tracking store and server-managed artifacts on Linux filesystem |
| `127.0.0.1:5000` | `http://mlflow:5000` from Airflow | MLflow tracking and proxied artifact access |
| Docker volume `mlops-assignment3-airflow-data` | `/opt/airflow` | Airflow metadata/logs and persistent per-workflow training artifacts |
| `.local/runtime/airflow/simple_auth_manager_passwords.json.generated` | Same filename in `/opt/airflow` | Preserved local admin password, never printed |
| `infra/airflow/dags` | `/opt/project/dags` | Committed DAG baked into the versioned custom image |
| Selected training modules under `src/mlops_agent` | `/opt/project/src/mlops_agent` | Committed code baked into the image; exact SHA at `/opt/project/revision` |
| Prepared `artifacts/airflow-input` | `/opt/project/input` | Read-only canonical data and DVC/Git lineage, checked during validation |
| `infra/airflow/requirements.lock` | `/opt/training` | Hash-checked ML runtime isolated from Airflow packages |
| `.local/kubeconfig` | Not mounted into services | Explicit assignment cluster access |

MLflow serves artifacts through HTTP using `--serve-artifacts`, keeping the
server's `/mlflow/artifacts` filesystem private to the tracking container.
Training and inference packaging use supported MLflow APIs instead of assuming
that the host or Airflow can read that server path. Real Airflow training and
container-side model reload are verified in [workflow evidence](evidence/airflow-dag.md).
Inference images package explicitly selected validated model bytes; see
[inference setup](inference.md) and [cluster deployment](kubernetes.md). The initial
base-image bootstrap starts service metadata only; `make airflow-image` adds the
training workflow and runtime after data bootstrap and committed source are ready.

`make cluster` inspects existing kind cluster names, creates only the dedicated
cluster if absent, exports only its kubeconfig locally, and applies the dedicated
namespace manifest using an explicit context. It never switches the user's global
Kubernetes context. `make smoke` reads real MLflow experiments, checks authenticated
Airflow access and scheduler components, and inspects cluster nodes/namespace. Its
JSON contains allowlisted observations only; failures expose an error type, not
HTTP bodies, credentials, or subprocess stderr. This bootstrap check is separate
from the agent's individually callable operational tools.

## Provider boundary

The [OpenRouter free router documentation](https://openrouter.ai/docs/guides/routing/routers/free-router)
describes free model routing filtered for required capabilities, including tool
calling. Availability and rate limits can change. A completed bootstrap check
proves connectivity at the recorded time, not continuous availability.
The implemented [provider adapter](agent.md) validates native tool calls, bounds
iterations and requests, handles quota/timeouts, and enforces free-only routing.
The [integrated live conversation](evidence/agent.md) records actual all-four-service
observations. Current availability is rechecked before each live conversation.
