# Acceptance checklist

Boxes are checked only when implementation and verification provide evidence.
Mocked test results do not satisfy a live demonstration requirement.

## DVC data management - 15 marks

- [x] At least three separately callable, structured DVC tools (seven registered).
- [x] List DVC-tracked datasets.
- [x] Retrieve dataset content version and Git revision.
- [x] Compare dataset revisions and detect workspace changes.
- [x] Resolve the dataset reference recorded for an MLflow training run.
      Live retrieved reference matches the committed pointer in [MLflow evidence](evidence/mlflow-live.json).
- [x] Explain and demonstrate checkout of an earlier dataset revision.
- [x] Restrict subprocess operations to an approved command and path allowlist.
      [Tool contract](data.md), [live historical restore/bootstrap](evidence/dvc-bootstrap.json),
      and `tests/test_dvc_tools.py`; two genuine revisions and [v2 recovery](evidence/dvc-v2.json).

## MLflow experiment intelligence - 15 marks

- [x] At least three separately callable, structured MLflow tools (seven registered).
- [x] Use MlflowClient or supported Python APIs, not UI scraping.
- [x] List experiments and training runs.
- [x] Retrieve recorded metrics, parameters, and artifacts.
- [x] Select the best eligible recent run using a requested metric and direction.
- [x] Compare at least two experiments and the last five training runs.
- [x] Retrieve registered model versions where available; explain absent registry data.
- [x] Explain selection limitations and avoid equating highest F1 with readiness.
      [Policy/tools](mlflow.md), [actual five-run evidence](evidence/mlflow.md),
      and `tests/test_mlflow_tools.py`; candidate version 1 READY, no production approval.

## Airflow workflow operations - 15 marks

- [x] At least three separately callable, structured Airflow tools.
- [x] Use authenticated Airflow 3 public API requests or a supported client.
- [x] List DAGs and retrieve DAG run status.
- [x] Trigger only an approved training DAG on an explicit request.
- [x] Identify failed tasks and retrieve execution details and available diagnostics.
- [x] Implement validation -> preprocessing -> training -> evaluation/MLflow -> quality gate.
- [x] Configure task dependencies, retries, and logging.
- [x] Failed validation or quality gate blocks inappropriate promotion.
- [x] Demonstrate a real DAG run and its actual task states.
      [Workflow policy](airflow.md), [four real runs and both failure retries](evidence/airflow-dag.md).
      Six authenticated tools and a real returned trigger/run ID are verified in
      [tool evidence](evidence/airflow-tools.md); conversational authorization remains pending.

## Kubernetes application operations - 15 marks

- [x] At least three separately callable, structured Kubernetes tools.
- [x] List application Pods and Deployments; inspect Services.
- [x] Retrieve Pod state, logs, relevant events, and restart counts.
- [x] Identify unhealthy Pods and deployed application/model versions.
- [x] Deploy a working containerized FastAPI inference service.
- [x] Deployment has at least two desired replicas and becomes Ready.
- [x] Include a ClusterIP Service, readiness/liveness probes, CPU/memory requests/limits.
- [x] Include a ConfigMap for non-sensitive settings.
- [x] Limit operations to an approved namespace.
- [x] Require explicit confirmation for any agent operation changing cluster state.

      [Tool/runbook policy](kubernetes.md), [actual deployment/RBAC export](evidence/kubernetes-live.json).
      Agent mutations are unsupported and rejected even with claimed confirmation.

### Inference prerequisite verified locally

- [x] Separate FastAPI prediction application loads the selected real MLflow artifact.
- [x] Validate named feature batches and reject invalid inputs with 422.
- [x] Independent liveness/readiness and application/model/dataset provenance routes.
- [x] Digest-pinned image and hash-locked dependencies run as a non-root user.
- [x] Built image matches all 45 holdout predictions/probabilities; missing model
      remains live but returns 503 for readiness and prediction.
      [Observed Docker evidence](evidence/inference.md); [cluster evidence](evidence/kubernetes.md).

## Integrated agent - 15 marks

- [x] Use a supported LLM API or suitable agent framework with structured tool calling.
- [x] Validate structured tool inputs and outputs and support multi-tool requests.
- [x] Execute the complete mandatory prompt: best recent model, its recorded DVC
      reference, Kubernetes status/health, and recent Airflow workflow states.
- [x] Correlate observations and distinguish known facts, uncertainties, and recommendations.
- [x] Never initiate retraining automatically from the mandatory prompt.
- [x] Recommend retraining only using a freshness policy, failed quality gate, or
      supplied degradation results.
      The current host conservatively emits no retrain recommendation; it requests
      policy/degradation evidence and reports necessity as not established.
      [Live all-four transcript](evidence/agent.md), [agent contract](agent.md).

## Testing, reliability, safety - 10 marks

- [x] At least eight meaningful pytest tests; external services mocked in ordinary CI.
      302 config/dataset/DVC/MLflow/training/inference/Kubernetes/workflow/agent tests pass; later
      failure-investigation requirements remain below.
- [x] Test successful tool selection and execution.
- [x] Test timeouts, invalid requests, and service failures across adapters/provider.
- [x] Test that an unavailable tool cannot produce invented operational results.
- [x] Test rejection of unauthorized Kubernetes modifications; read-only tool and live RBAC checks.
- [x] Structured logs include tool name, status, duration, and request ID without secrets.
      [Reliability audit and test coverage](reliability.md), including identity,
      namespace, malformed-response and redaction regressions; ordinary CI is mocked.
- [ ] Inject at least two failures and explain diagnosis, root cause, and resolution.
      Isolated validation and candidate-gate failures are observed and recovered in
      [workflow evidence](evidence/airflow-dag.md); the required Kubernetes readiness
      exercise and combined final investigations remain pending.

## Repository and CI - 5 marks

- [x] Maintain source code, infrastructure, tests, and documentation in one GitHub repository.
- [x] Provide a reproducible Python environment with pinned/resolved dependencies.
      `pyproject.toml`, `uv.lock`, `make setup`, and environment bootstrap evidence.
- [x] GitHub Actions runs linting and automated tests on pull requests.
      [Environment PR run](https://github.com/UmerN236/assignment-03-mlops-agent/actions/runs/43563756356)
      passed frozen setup, lint, format, and pytest on Linux.
- [x] CI does not require live external services or production credentials.
- [x] Do not commit API keys, kubeconfig, service-account tokens, or other secrets.
      Staged secret scan passed; `.local/` and `.env` are ignored and untracked.

## Demonstration and submission - 10 marks

- [x] Demonstrate dataset provenance with a reproducible DVC reference.
- [x] Demonstrate model selection with real MLflow metrics and justification.
      [MLflow results](evidence/mlflow.md); integrated conversations remain pending.
- [x] Demonstrate pipeline execution with a real Airflow run and task statuses.
      [Actual smoke/failure/recovery export](evidence/airflow-dag-live.json);
      conversational trigger demonstration remains pending.
- [x] Demonstrate Kubernetes diagnosis with actual health data and logs.
      [Direct tool export](evidence/kubernetes-live.json); LLM conversation remains pending.
- [x] Demonstrate multi-tool reasoning using all four technologies.
- [ ] README covers installation, configuration, each service, tests, and interaction.
- [ ] Short technical report covers architecture and tool definitions/permissions.
- [ ] Report includes screenshots or exported evidence from all four integrations.
- [ ] Report includes five tested conversations linked to actual tool evidence.
- [ ] Report includes two failure investigations, limitations, and proposed improvements.
- [ ] Prepare architecture/tool-choice explanations and an unexpected-failure diagnosis.
