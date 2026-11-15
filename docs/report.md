# Technical report: evidence-backed MLOps AI agent

## System and implementation

The repository implements one conversational operations interface over DVC,
MLflow, Airflow 3 and Kubernetes. A separate FastAPI application serves an actual
trained Iris model. Python 3.12.12 and resolved dependencies are recorded in
`pyproject.toml`/`uv.lock`; Docker runtimes have digest-pinned base images and
hash-locked dependencies. [The architecture diagram](../architecture.md) shows
the service boundaries and the evidence path.

A user request enters the CLI or loopback FastAPI `/chat` endpoint. The selected
free OpenRouter model proposes native structured function calls. The host validates
their schemas, permissions and limits before executing a registered adapter.
Results contain request ID, tool name, UTC observation time, status, evidence,
error and elapsed milliseconds. The model finishes with references to successful
observations. The host resolves those references into exact values; it does not
accept model-supplied operational values as facts. Responses distinguish facts,
uncertainties, recommendations and cross-system correlations.

## Tools and permissions

The [machine-readable catalog](tool-catalog.json) contains every input/output
schema. The read-only host exposes 24 tools; explicit training mode adds one
authorized trigger, for 25 total definitions.

| Module | Individually callable operations | Boundary |
| --- | --- | --- |
| DVC, 7 tools | List datasets; dataset version; compare versions; status; resolve recorded MLflow lineage; verify supplied reference; explain reproduction | Fixed repository/dataset and approved subprocess argv; no shell, checkout write or caller-supplied executable |
| MLflow, 7 tools | Experiments; recent runs; run details/artifacts; best run; run comparison; experiment comparison; registered versions | Supported `MlflowClient`; bounded isolated worker; no UI scraping or model promotion |
| Airflow, 6 tools | DAG list; run list; run/task status; failed tasks; task diagnostics; approved training trigger | Authenticated `/api/v2`, approved DAG, bounded reads; one explicit confirmed POST, never automatic POST retry |
| Kubernetes, 5 tools | Workloads; Services/endpoints; Pod diagnostics/events; bounded logs; application health/version | Restricted token, fixed namespace/context and assignment ownership; no write/exec/secret access |

Inputs forbid unknown fields, constrain IDs/paths and bound list sizes and
execution time. Tokens and passwords reach the Airflow worker over stdin, not
command-line arguments or exported logs. Tool logs serialize name, status,
duration and correlation ID. Unavailable services produce explicit unknowns;
arbitrary service text cannot expand permissions. Ordinary CI mocks external
systems and rejects in-process network connections.

Training needs caller-selected `trigger_training` mode and the exact confirmation
`trigger assignment_training`. Query and assessment registries omit this capability.
Kubernetes mutations are entirely unsupported, including requests claiming
confirmation. The separately authorized engineering setup/failure scripts are
restricted to the dedicated cluster/namespace and never become LLM tools.

## Reproducible data, training and serving

The deterministic 150-row Iris dataset has two genuine DVC revisions: the initial
recipe and a recorded sensor-resolution change. Git records DVC pointers; a local
remote stores content. [Historical restoration evidence](evidence/dvc-bootstrap.json)
shows changed-data detection, isolated recovery and independent regeneration.
Fresh clones reconstruct the committed recipe and verify its content hash instead
of depending on another person's local remote.

Training uses a stratified 70/30 split with seed 42. Logistic regression and random
forests share a recorded evaluation cohort. MLflow records dataset path, DVC MD5,
dataset Git revision, training-code Git revision, split indices/hash, configuration,
accuracy, macro F1, log loss, model artifacts and registered candidate metadata.
Selection honors metric direction and refuses a global ranking across incompatible
cohorts. [Recorded experiments](evidence/mlflow-live.json) provide real values.

The Airflow TaskFlow DAG is validation -> preprocessing -> training ->
evaluation/MLflow -> quality gate -> candidate approval. Tasks have one retry,
explicit dependencies and bounded execution. Shared artifacts persist by workflow
ID. The candidate gate requires F1/accuracy >=0.90, log loss <=0.35 and at least
45 held-out rows. Failed validation prevents training; failed quality prevents
approval. Candidate approval does not deploy or establish production readiness.

Inference packages an explicitly selected, trusted model with validated hashes
and complete lineage. The image identity includes source revision and full bundle
provenance, so identical weights from different run IDs cannot overwrite the same
tag. Build-time loading runs as the non-root serving user. Kubernetes has two
desired replicas, ClusterIP routing, startup/liveness/readiness probes, CPU/memory
requests and limits, and a non-sensitive ConfigMap. The verified image is loaded
into kind and rendered into a local manifest copy after ownership/identity checks.

The final [Docker export](evidence/inference-live.json) verifies all 45 holdout
predictions/probabilities, negative input validation and missing-model behavior.
The [cluster export](evidence/kubernetes-live.json) independently verifies Service
DNS, ClusterIP and both replica IPs, exact model/version linkage and ten RBAC probes.
These repeated holdout checks verify reproducibility and transport, not new
independent statistical validation.

## Tested conversations and decisions

Five complete, real LLM/tool conversations are exported with user prompts, request
IDs, model/cost observations, tool arguments/results, resolved facts and final
responses. [The conversation index](evidence/conversations/README.md) links each
scenario: dataset provenance, model selection, approved pipeline execution,
deployment diagnosis and the mandatory multi-tool request. The pipeline run
actually reached success. All recorded provider completion costs were zero.

The mandatory conversation lists experiments, selects a comparable recent model,
resolves that exact run's recorded DVC reference, checks Kubernetes workload,
Service and health/version, and inspects recent Airflow workflows. The selected
candidate and deployed model are correctly reported as different. No training or
deployment occurs. Retraining necessity is not established because no current
degradation measurement or approved freshness policy was supplied; historical
controlled failures and highest F1 are insufficient reasons to retrain.

## Failures, validation and reproduction

[Two investigations](failure-investigations.md) contain actual observations, root
cause, impact, diagnosis, correction and recovery. An isolated malformed feature
header fails validation twice and blocks every downstream stage; a separate valid
run recovers. A deliberately wrong readiness path produces HTTP 404 probe events,
zero Ready backends and an unavailable Service while the model process remains
live. Read-only agent diagnosis cites probe/endpoint/event/log observations; its
partial health status accurately reflects missing Service health. Restoring the
original strategy/probe recovers two healthy replicas. A first provider failure
attempt is preserved separately rather than represented as a successful diagnosis.

Ruff and 314 meaningful pytest cases pass, including dispatch, validation, timeouts,
service failures, unknown/malformed responses, authorization, prompt-output
boundaries, provenance mismatches, no fabricated unavailable results, secret
redaction and CI isolation. Pull-request Actions runs lock validation, frozen
installation and the same lint/test command. [CI](../.github/workflows/ci.yaml)
needs no live services or production credentials.

The [clean-checkout export](evidence/reproduction-live.json) records an independent
clone, new locked virtual environment, DVC regeneration, a completely empty
temporary MLflow tracking store, five new runs across two experiments, explicit
selection, packaging, image build and actual HTTP prediction with the new run ID.
No original tracking state or user secrets were copied. Verified local uv/Python
distribution and the Docker engine were reused; Airflow/Kubernetes were verified
separately in the dedicated live environment. [Reproduction instructions](reproduction.md)
distinguish that scope from provisioning an entirely new machine.

## Limitations and improvements

Iris and the repeated 45-row holdout are educational; use independent temporal
evaluation and monitored data/model quality before production decisions. A
single-node kind cluster cannot survive node failure despite two replicas.
Free-model availability, quota and tool-call quality vary; partial/unavailable
answers remain truthful, and no paid fallback is used. The Gemini adapter is not
implemented because OpenRouter is the configured provider. Diagnostic exports
omit arbitrary raw logs/event messages; operators can inspect full authorized
service logs when structured evidence is insufficient. Credentials expire and
must be refreshed by an engineer. These are explicit limitations, not claims of
high availability or production approval.

Future improvements are managed storage/registry, independent evaluation,
freshness/drift policies with monitored thresholds, stronger authentication for a
network-exposed agent, more precise free-model capability selection, and a
multi-node deployment. Serving intentionally remains loopback/private for this
demonstration. Use the [defense guide](defense.md) for the live evaluation.
