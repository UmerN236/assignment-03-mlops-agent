# Environment bootstrap observations

Observed **14 November 2026**, approximately **05:52 UTC**. These are bootstrap
observations, not completed operational-agent demonstration requirements.

- `make setup`: Python 3.12.12 installed locally; frozen resolution installed.
  `uv pip check`: all 162 installed packages compatible.
- `make check`: Ruff lint and format checks passed; **17 pytest cases passed**.
  Coverage here concerns configuration boundaries, secret-safe errors, missing
  credentials, model selection configuration, and execution bounds. Operational
  tool selection, failure, timeout, and authorization tests remain future work.
- uv 0.9.9, kind 0.30.0, and kubectl 1.34.0 downloaded from official release
  sources and verified against fixed SHA-256 values before installation.
- MLflow 3.6.0: health HTTP 200; supported client experiment listing returned one
  initial experiment. No training runs or model artifacts were created.
- Airflow 3.1.3 / Python 3.12: unauthenticated `GET /api/v2/dags` returned 401;
  credentialed token exchange followed by authenticated listing returned 200 with
  zero DAGs. Metadata database, scheduler, DAG processor, and triggerer reported
  healthy. Airflow-container to `http://mlflow:5000/health` returned HTTP 200.
- kind cluster `mlops-assignment3`: one Ready control-plane at Kubernetes 1.34.0.
  Namespace `mlops-agent` is Active, with no inference workloads yet.
- Free OpenRouter smoke at **05:45:50 UTC** authenticated the configured key,
  received and validated one structured `echo_nonce` tool call, submitted its
  actual result, and received the expected acknowledgment. Both requests reported
  cost **0**. The actual selected free models are in the sanitized JSON export.
  This harmless connectivity test is not an assignment operational conversation.

Machine-readable observations:
[services](environment-bootstrap.json), [provider](provider-bootstrap.json).
No credentials, headers, kubeconfig contents, or full HTTP bodies are included.
The service checks are rerunnable with `make smoke`; historical exports do not
assert continuous availability.

## Bootstrap repairs

The first uv installation encountered macOS `Resource deadlock avoided` while
cloning wheel files. Setting project-local `UV_LINK_MODE=copy` resolved the install;
the frozen environment and compatibility check then passed.

The initial Airflow HTTP health endpoint returned 200 while its scheduler was
unhealthy. Actual scheduler logs contained `sqlite3.OperationalError: locking
protocol`. Airflow metadata was on a macOS bind mount. Stopping the assignment
services, preserving bootstrap state in dedicated Docker volumes, and restarting
restored all four component health checks. The storage placement is implicated by
the observed error and successful volume-based recovery. MLflow metadata was also
moved to its dedicated Linux-backed volume. Both databases returned `ok` from
`PRAGMA quick_check`. The container health check now inspects component status,
not just the endpoint's HTTP status. These bootstrap repairs do not replace the
two required controlled failure exercises.
