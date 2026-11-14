# Reproducible development and bootstrap

## Versions and isolation

- Python **3.12.12**, uv **0.9.9**, full transitive resolution in `uv.lock`.
- Agent: DVC **3.64.0**, MLflow **3.6.0**, scikit-learn **1.7.2**, FastAPI
  **0.121.1**, Pydantic **2.12.4**, Kubernetes client **34.1.0**; all direct
  dependencies are pinned in `pyproject.toml`.
- Airflow **3.1.3**, official **Python 3.12** container, isolated from the agent's
  dependencies. Its complete upstream environment is fixed by image digest.
- kind **0.30.0**, kubectl **1.34.0**, Kubernetes node **1.34.0** with the kind
  release's published image digest. The cluster runs inference later; this is
  not an Airflow KubernetesExecutor deployment.

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
run `uv sync --frozen --python 3.12.12`, then `uv run ruff check .`,
`uv run ruff format --check .`, and `uv run pytest`. CI follows these commands and
needs neither Docker nor API keys. Dependency changes require an intentional
`uv lock` and review of the updated lockfile; normal setup uses `--frozen`.

`make services` uses a fixed Compose project and container names with the
`mlops-assignment3` prefix. It does not import `.env` into Compose. Runtime preparation
creates a random Airflow password with mode 0600 only when absent. Existing `.env`
and passwords are preserved. Use `make services` again after Docker restarts;
containers are intentionally not configured as system services.

| Host path/address | Container path/address | Purpose |
| --- | --- | --- |
| Docker volume `mlops-assignment3-mlflow-data` | `/mlflow` | SQLite tracking store and server-managed artifacts on Linux filesystem |
| `127.0.0.1:5000` | `http://mlflow:5000` from Airflow | MLflow tracking and proxied artifact access |
| Docker volume `mlops-assignment3-airflow-data` | `/opt/airflow` | Airflow database and logs on Linux filesystem |
| `.local/runtime/airflow/simple_auth_manager_passwords.json.generated` | Same filename in `/opt/airflow` | Preserved local admin password, never printed |
| `infra/airflow/dags` | `/opt/project/infra/airflow/dags` | Read-only DAG source (initially empty) |
| `src` | `/opt/project/src` | Read-only application source for later DAG packaging |
| `.local/kubeconfig` | Not mounted into services | Explicit assignment cluster access |

MLflow serves artifacts through HTTP using `--serve-artifacts`, keeping the
server's `/mlflow/artifacts` filesystem private to the tracking container. Future
training and inference code must use supported download APIs instead of assuming
that the host or Airflow can read that server path. Airflow presently has no
training dependencies, data mount, or training DAG: its image will be extended
with compatible locked dependencies and shared paths during the DAG milestone.
No inference deployment or model artifacts are supplied by this bootstrap.

`make cluster` inspects existing kind cluster names, creates only the dedicated
cluster if absent, exports only its kubeconfig locally, and applies the dedicated
namespace manifest using an explicit context. It never switches the user's global
Kubernetes context. `make smoke` reads real MLflow experiments, checks authenticated
Airflow access and scheduler components, and inspects cluster nodes/namespace. Its
JSON contains allowlisted observations only; failures expose an error type, not
HTTP bodies, credentials, or subprocess stderr. This bootstrap check is separate
from the future agent's callable operational tools.

## Provider boundary

The [OpenRouter free router documentation](https://openrouter.ai/docs/guides/routing/routers/free-router)
describes free model routing filtered for required capabilities, including tool
calling. Availability and rate limits can change. A completed bootstrap check
proves connectivity at the recorded time, not continuous availability or agent
functionality. The future provider adapter still needs schema validation, bounded
iterations, timeouts, quota handling, and a live multi-service conversation.
