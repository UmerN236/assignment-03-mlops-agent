# Acceptance checklist

All boxes are intentionally open until implementation and verification provide
evidence. Mocked test results do not satisfy a live demonstration requirement.

## DVC data management - 15 marks

- [ ] At least three separately callable, structured DVC tools.
- [ ] List DVC-tracked datasets.
- [ ] Retrieve dataset content version and Git revision.
- [ ] Compare dataset revisions and detect workspace changes.
- [ ] Resolve the dataset reference recorded for an MLflow training run.
- [ ] Explain and demonstrate checkout of an earlier dataset revision.
- [ ] Restrict subprocess operations to an approved command and path allowlist.

## MLflow experiment intelligence - 15 marks

- [ ] At least three separately callable, structured MLflow tools.
- [ ] Use MlflowClient or supported Python APIs, not UI scraping.
- [ ] List experiments and training runs.
- [ ] Retrieve recorded metrics, parameters, and artifacts.
- [ ] Select the best eligible recent run using a requested metric and direction.
- [ ] Compare at least two experiments and the last five training runs.
- [ ] Retrieve registered model versions where available; explain absent registry data.
- [ ] Explain selection limitations and avoid equating highest F1 with readiness.

## Airflow workflow operations - 15 marks

- [ ] At least three separately callable, structured Airflow tools.
- [ ] Use authenticated Airflow 3 public API requests or a supported client.
- [ ] List DAGs and retrieve DAG run status.
- [ ] Trigger only an approved training DAG on an explicit request.
- [ ] Identify failed tasks and retrieve execution details and available diagnostics.
- [ ] Implement validation -> preprocessing -> training -> evaluation/MLflow -> quality gate.
- [ ] Configure task dependencies, retries, and logging.
- [ ] Failed validation or quality gate blocks inappropriate promotion.
- [ ] Demonstrate a real DAG run and its actual task states.

## Kubernetes application operations - 15 marks

- [ ] At least three separately callable, structured Kubernetes tools.
- [ ] List application Pods and Deployments; inspect Services.
- [ ] Retrieve Pod state, logs, relevant events, and restart counts.
- [ ] Identify unhealthy Pods and deployed application/model versions.
- [ ] Deploy a working containerized FastAPI inference service.
- [ ] Deployment has at least two desired replicas and becomes Ready.
- [ ] Include a ClusterIP Service, readiness/liveness probes, CPU/memory requests/limits.
- [ ] Include a ConfigMap for non-sensitive settings.
- [ ] Limit operations to an approved namespace.
- [ ] Require explicit confirmation for any agent operation changing cluster state.

## Integrated agent - 15 marks

- [ ] Use a supported LLM API or suitable agent framework with structured tool calling.
- [ ] Validate structured tool inputs and outputs and support multi-tool requests.
- [ ] Execute the complete mandatory prompt: best recent model, its recorded DVC
      reference, Kubernetes status/health, and recent Airflow workflow states.
- [ ] Correlate observations and distinguish known facts, uncertainties, and recommendations.
- [ ] Never initiate retraining automatically from the mandatory prompt.
- [ ] Recommend retraining only using a freshness policy, failed quality gate, or
      supplied degradation results.

## Testing, reliability, safety - 10 marks

- [ ] At least eight meaningful pytest tests; external services mocked in ordinary CI.
- [ ] Test successful tool selection and execution.
- [ ] Test timeouts, invalid requests, and service failures.
- [ ] Test that an unavailable tool cannot produce invented operational results.
- [ ] Test rejection of unauthorized Kubernetes modifications.
- [ ] Structured logs include tool name, status, duration, and request ID without secrets.
- [ ] Inject at least two failures and explain diagnosis, root cause, and resolution.

## Repository and CI - 5 marks

- [ ] Maintain source code, infrastructure, tests, and documentation in one GitHub repository.
- [ ] Provide a reproducible Python environment with pinned/resolved dependencies.
- [ ] GitHub Actions runs linting and automated tests on pull requests.
- [ ] CI does not require live external services or production credentials.
- [ ] Do not commit API keys, kubeconfig, service-account tokens, or other secrets.

## Demonstration and submission - 10 marks

- [ ] Demonstrate dataset provenance with a reproducible DVC reference.
- [ ] Demonstrate model selection with real MLflow metrics and justification.
- [ ] Demonstrate pipeline execution with a real Airflow run and task statuses.
- [ ] Demonstrate Kubernetes diagnosis with actual health data and logs.
- [ ] Demonstrate multi-tool reasoning using all four technologies.
- [ ] README covers installation, configuration, each service, tests, and interaction.
- [ ] Short technical report covers architecture and tool definitions/permissions.
- [ ] Report includes screenshots or exported evidence from all four integrations.
- [ ] Report includes five tested conversations linked to actual tool evidence.
- [ ] Report includes two failure investigations, limitations, and proposed improvements.
- [ ] Prepare architecture/tool-choice explanations and an unexpected-failure diagnosis.
