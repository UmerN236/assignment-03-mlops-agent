# Versioned inference service

This FastAPI application serves an explicitly selected trained Iris classifier.
The conversational agent is a separate application responsibility. There is no
tool execution, training, model upload, or model selection route in this service.

## Build and run

Start MLflow with `make services`, then use the frozen development environment:

```sh
make inference-image
make verify-inference
```

Packaging retrieves the exact run/model in
[`model-selection.json`](../infra/inference/model-selection.json) through the
supported MLflow HTTP artifact API. It checks FINISHED state, model/run linkage,
dataset/code/evaluation lineage, the previously observed model SHA-256, and a real
prediction. It stages only `MLmodel`, `model.pkl`, and a hash manifest under ignored
`artifacts/inference/`. Different existing bundles are preserved and cause an error.
The packaging subprocess has a 120-second deadline, with 20-second HTTP requests
and no HTTP retries. Service URLs contain no embedded credentials.

Build from committed code: the image records the current full Git SHA in its
read-only application version file and OCI label. Python and the temporary uv
build-tool image use digests; uv downloads dependencies concurrently without
installing the build tool into the runtime image. The
runtime dependencies are resolved in `infra/inference/requirements.lock` and
installed with required hashes. The Docker context is denied by default and
includes only runtime source, the lock, Dockerfile, and staged model bundle.
`.env`, Git, local runtime/runner files, and training data cannot enter the image.
Buildx configuration, activity and logs use a workspace-local directory through
Docker's documented [BUILDX_CONFIG setting](https://docs.docker.com/build/building/variables/#buildx_config).

`make verify-inference` leaves a labeled, non-root, read-only Docker container
`mlops-assignment3-inference` available at its printed loopback URL. It refuses to
replace an existing unrelated container or a service using a different image.
It compares all 45 held-out predictions/probabilities against the same artifact
loaded independently on the host, checks metadata, invalid inputs and a separate
missing-model container, then removes only that temporary negative-test container.
Evidence is exported to `docs/evidence/inference-live.json` after all checks pass.
No model/MLflow volume is mounted; serving works from the packaged local artifact
without runtime access to MLflow or host artifact paths.

A fresh checkout needs access to the tracking server holding this explicit run,
or a trusted copy of its validated bundle. Regenerating the dataset does not
recreate the same MLflow run ID. Missing historical state fails packaging rather
than selecting a different model. Later Airflow runs can supply new artifacts
only through an explicit reviewed selection change and image rebuild.

## HTTP contract

| Route | Behavior |
| --- | --- |
| `GET /livez` | 200 when the process can respond, independent of model state. |
| `GET /readyz` | 200 only after verified loading and smoke prediction; otherwise 503. |
| `GET /version` | Application Git SHA, model readiness, run/model IDs, SHA-256, training code, dataset Git revision/DVC MD5, evaluation cohort, feature order and class names. Missing metadata is null. |
| `POST /predict` | 1–100 named feature rows; class ID/name and three probabilities, plus run ID and application SHA. |

Measurements are numeric centimeters, finite and strictly between 0 and 20,
matching training validation. Strings, booleans, nulls, missing/extra fields,
empty/oversized batches and malformed JSON return 422. Feature names avoid
positional-order ambiguity. Predictions preserve request order. Example:

```sh
curl -sS "$INFERENCE_URL/predict" -H 'Content-Type: application/json' -d \
  '{"instances":[{"sepal_length":5.0,"sepal_width":3.5,"petal_length":1.4,"petal_width":0.2}]}'
```

The startup loader verifies file integrity, metadata/runtime compatibility and
the four-feature/three-class schema before deserialization and readiness. Pickle
can execute code: the bundle must come from the trusted engineering packaging
step. Hashes detect corruption and are not a sandbox for untrusted artifacts.
Load failures preserve liveness and return 503 for readiness/prediction. Invalid
model outputs also remove readiness. Restore a correct image and restart to
recover; this service never silently downloads or substitutes a model.

Each HTTP response has `X-Request-ID`; structured request/load logs include name,
status, duration and correlation ID. Validation errors omit submitted values and
model errors omit exception text. Request bodies and credentials are not logged.

Startup uses FastAPI's documented [lifespan mechanism](https://fastapi.tiangolo.com/advanced/events/).
Unit tests use real local sklearn serialization without requiring external
services; Docker verification is separately observed live evidence. Local
readiness is process/model availability, not a production approval or drift check.
Kubernetes replicas, probes, resources, ConfigMap and operations tools belong to
the next milestone and remain pending.
