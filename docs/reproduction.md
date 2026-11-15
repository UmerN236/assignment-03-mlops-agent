# Reproduce from a fresh checkout

Use Python 3.12.12, the committed uv lockfile, Docker, and the dedicated assignment
cluster. `make tools` installs the pinned local tools on Apple Silicon macOS;
Linux reviewers can install uv 0.9.9, kubectl and kind as documented upstream and
use `make check UV=uv`. Runtime calls need the user's own free OpenRouter key.
Never copy another user's kubeconfig or credentials into a submission.

## Data and tests

```sh
make tools
make setup
test -e .env || cp .env.example .env
make check
make data-bootstrap
make data-status
```

Data bootstrap regenerates the committed recipe and checks its DVC content hash
before populating the cache and local remote. A clone does not need the original
machine's data remote. Historical revisions have their own committed recipes.
The environment is resolved/frozen, while external service data is created by
the explicit engineering operations below. Existing runtime volumes are preserved.

## Fresh service state and a newly trained model

```sh
make services
make cluster
make smoke
make train-models
```

The batch prints five actual new run IDs across two experiments and records
them in ignored `.local/mlflow-training.json`. It refuses to overwrite an existing
batch record. Read its `registered_candidate.run_id`, or inspect real run metrics
through the MLflow tools. A newly generated run ID will differ from the historical
submission evidence; that is expected and must never be substituted into old evidence.

Explicitly choose a trusted run you just trained, using its returned full ID:

```sh
PYTHONPATH=src .venv/bin/python scripts/select-model.py --run-id ACTUAL_RUN_ID
PYTHONPATH=src .venv/bin/python scripts/package-inference.py \
  --selection .local/model-selection.json
PYTHONPATH=src .venv/bin/python scripts/build-inference.py
PYTHONPATH=src .venv/bin/python scripts/verify-inference.py --replace-owned
make deploy-kubernetes
make verify-kubernetes
```

Do not type the placeholder `ACTUAL_RUN_ID`. Selection verifies a completed run,
recorded model/source linkage, full dataset/code provenance and actual artifact
hash. It writes ignored local metadata without replacing the checked-in historical
selection. Packaging then validates the selected trusted artifact and runtime
before deserialization. It refuses to overwrite a different existing model bundle;
use a separate fresh checkout when reproducing a different model.

The image tag includes both source revision and model-content hash. Building
requires committed runtime source; unrelated evidence/doc edits do not change the
image inputs. Verification writes actual image ID/model observations, and setup
checks that image ID before importing into the named kind cluster. Setup renders
the verified image into a local copy of the Kubernetes template. No historical
tag, manifest edit or fabricated MLflow identifier is required on a fresh machine.

`--replace-owned` is an explicit engineering authorization to replace only the
named, labeled assignment Docker inference container. An unrelated container is
rejected. Kubernetes deployment also checks resource ownership before writes.

## Training workflow and agent

```sh
make airflow-image
make smoke
make verify-airflow-dag
make verify-airflow-tools
make agent
```

The first workflow verifier deliberately runs validation/quality-gate failures
and recovery; the second explicitly triggers a canonical run. They are separate
from ordinary mocked CI. `make agent` performs the mandatory read-only assessment
and cannot train or deploy. `make agent-api` exposes the local conversation API
on port 8090; start it in another terminal for `/docs`, `/livez` and `/chat`.

The same fixed project/namespace/ports must not be provisioned concurrently by
two checkouts. A clean-checkout audit may use a separate tracking server and
ephemeral ports for data/training/model packaging without disrupting the live demo.
The submission's reproduction evidence states exactly which parts were executed.
