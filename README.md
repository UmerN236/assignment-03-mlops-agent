# MLOps AI Agent

A Python agent for dataset provenance, experiment comparison, training workflow
operations, and Kubernetes application diagnosis.

## Project status

The reproducible development environment, validated configuration, initial tests,
CI, and local service bootstrap are implemented. Service observations are recorded
in [environment evidence](docs/evidence/environment.md). The first deterministic
Iris dataset has two genuine DVC revisions; see [data bootstrap](docs/data.md).
Seven DVC tools and seven MLflow tools are callable through structured registries
and command-line helpers. Five real training runs across two experiments and a
registered model candidate have been verified; see [MLflow evidence](docs/evidence/mlflow.md).
Airflow and Kubernetes adapters, the training DAG, inference service, and
conversational agent are still pending.
This repository does not yet provide a runnable operations agent.

## Development setup

On Apple Silicon macOS, with Docker Desktop running, Git, curl, and make installed:

```sh
make tools    # checksum-verified uv, kind, kubectl under .local/bin
make setup    # project-local Python 3.12.12 and frozen uv.lock
# Only create a template if there is no existing .env:
test -e .env || cp .env.example .env
make config   # allowlisted presence booleans; never prints key values
make check    # lint, format check, and pytest; no live service credentials needed
make services
make cluster
make smoke    # real, read-only service checks; fails if a dependency is unavailable
```

Use `LLM_PROVIDER=openrouter` with `OPENROUTER_API_KEY` and
`OPENROUTER_MODEL=openrouter/free` (or an explicitly configured `:free` model).
`LLM_MODEL` takes precedence over provider-specific model names. Empty template
entries use defaults. The loader rejects implicit/paid OpenRouter models and
does not fall back between providers. A Gemini integration and its model/free-tier
verification remain pending. Keep existing credentials intact; never commit `.env`.

Services bind only to loopback: MLflow at `http://127.0.0.1:5000` and Airflow at
`http://127.0.0.1:8080`. Airflow uses SimpleAuthManager, not an authentication bypass.
The bootstrap creates a random local admin password once, in ignored runtime
storage. The smoke script exchanges it for a JWT in memory and tests the public
`/api/v2/dags` endpoint without displaying either credential. Explicit
`AIRFLOW_TOKEN` or `AIRFLOW_USERNAME`/`AIRFLOW_PASSWORD` configuration can override
the bootstrap credential for subsequent clients.

The dedicated cluster/context is `mlops-assignment3` / `kind-mlops-assignment3`;
the assignment namespace is `mlops-agent`. Kubeconfig stays in `.local/kubeconfig`.
Bootstrap commands create infrastructure as an engineer; future agent tools must
still enforce read-only defaults and exact confirmations for writes.

See [development notes](docs/development.md) for version decisions, service paths,
Linux CI instructions, and current limitations.

## DVC tools

```sh
make data-bootstrap
make data-status
PYTHONPATH=src .venv/bin/python scripts/dvc-tool.py --schemas
PYTHONPATH=src .venv/bin/python scripts/dvc-tool.py dvc_get_dataset_version '{}'
PYTHONPATH=src .venv/bin/python scripts/dvc-tool.py dvc_list_datasets '{}'
PYTHONPATH=src .venv/bin/python scripts/verify-dvc.py
```

The verification script creates isolated clones under ignored local storage,
checks an earlier committed dataset out, pulls from the real local DVC remote,
detects changed data and restores cached bytes. A second clone rebuilds the data
with no pre-existing cache or remote. It exports real tool responses to
[DVC evidence](docs/evidence/dvc-bootstrap.json). It reuses the installed frozen
Python runtime. See [dataset operations](docs/data.md) for inputs, safety policy,
fresh-clone instructions and MLflow lineage integration limits.

## MLflow training and inspection

```sh
# Training requires committed code/data metadata and preserves existing runs:
make train-models
make verify-mlflow
PYTHONPATH=src .venv/bin/python scripts/mlflow-tool.py mlflow_list_experiments '{}'
PYTHONPATH=src .venv/bin/python scripts/mlflow-tool.py mlflow_compare_experiments \
  '{"experiment_ids":["1","2"],"metric":"f1_macro","direction":"maximize","limit":5}'
```

Use experiment IDs returned by your tracking service. See [MLflow operations](docs/mlflow.md)
for exact schemas, deterministic split policy, artifacts and lineage. Comparison
tools honor metric direction and refuse a global winner across incompatible
evaluation cohorts. A high held-out F1 or registry READY state does not establish
production readiness or justify retraining. Training is an explicit engineering
command; all exposed MLflow tools are read-only. The DVC run resolver now retrieves
real MLflow parameters through the same bounded client worker.

## Intended capabilities

- Inspect DVC datasets, revisions, differences, and reproducibility references.
- Compare recorded MLflow runs and retrieve metrics, artifacts, and model metadata.
- Inspect and explicitly trigger an approved Airflow 3 training DAG.
- Diagnose a FastAPI inference service running in an approved Kubernetes namespace.
- Combine tool evidence into responses that distinguish facts, unknowns, and
  recommended actions.

See [architecture.md](architecture.md) for the design and
[docs/requirements.md](docs/requirements.md) for acceptance criteria.

Interaction instructions will accompany the agent implementation. Secrets,
credentials, and local runtime data must remain outside version control.
