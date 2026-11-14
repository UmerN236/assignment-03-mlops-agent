# MLOps AI Agent

A Python agent for dataset provenance, experiment comparison, training workflow
operations, and Kubernetes application diagnosis.

## Project status

Repository initialization and requirement mapping are complete. Application code,
service configuration, automated tests, and live demonstration evidence are not
implemented yet. This repository does not currently provide a runnable agent.

## Intended capabilities

- Inspect DVC datasets, revisions, differences, and reproducibility references.
- Compare recorded MLflow runs and retrieve metrics, artifacts, and model metadata.
- Inspect and explicitly trigger an approved Airflow 3 training DAG.
- Diagnose a FastAPI inference service running in an approved Kubernetes namespace.
- Combine tool evidence into responses that distinguish facts, unknowns, and
  recommended actions.

See [architecture.md](architecture.md) for the design and
[docs/requirements.md](docs/requirements.md) for acceptance criteria.

Installation, environment configuration, service launch, test, and interaction
instructions will accompany the corresponding implementation. Secrets, credentials,
and local runtime data must remain outside version control.
