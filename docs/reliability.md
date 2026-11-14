# Reliability and safety audit

Run `make check` with the frozen Python 3.12 environment. Ordinary CI uses mocks
for external services and requires no credentials. The audit adds 24 regression
and boundary cases to the existing 278 cases. Sixteen initial regression cases
failed against the previous source before their fixes were applied.
Final local validation passed Ruff lint/format and all 302 pytest cases. The
existing Starlette/AnyIO deprecation warning remains.

## Corrections

- DVC rejects response containers that do not match the requested operation.
  In particular, an empty status list cannot be reported as a clean workspace.
  Missing repository storage returns unavailable when called, without preventing
  unrelated service queries from registering or running.
- MLflow checks the requested run identity before exporting lineage or fetching
  artifacts. A logged model must match both the run's recorded model ID and its
  source run. Mismatches provide no usable evidence through the worker.
- The agent independently validates the Kubernetes read operation and namespace,
  even when an embedding host registers an overly permissive tool. Unsupported
  cluster writes remain rejected, including claimed confirmations.
- Kubernetes diagnostics tolerate absent optional container state. Log projection
  retains valid fields while replacing malformed/nonfinite numeric fields with
  null; arbitrary text and credentials remain omitted.
- Inference validation preserves known field locations and indices but replaces
  arbitrary input keys with `unknown_field`, preventing keys containing sensitive
  text from being echoed in validation responses.

## Automated coverage

| Requirement | Representative tests |
| --- | --- |
| Tool selection, execution and all-four correlation | `test_query_instructions_focus_on_requested_service`, `test_complete_assessment_uses_four_services_and_correlates` in `tests/test_agent.py` |
| Requested historical run lineage | `test_mlflow_lineage_is_resolved_against_recorded_git_hash` in `tests/test_dvc_tools.py`; mismatched run/model cases in `tests/test_mlflow_tools.py` |
| Shell/path/revision injection and unknown commands | Revision/path/extra-command cases in `tests/test_dvc_tools.py` |
| Timeouts, process failures and unavailable tools | Worker failure cases in DVC, MLflow, Airflow and Kubernetes tests; `test_provider_timeout_sanitized_and_not_retried` |
| Deadline and output bounds | `test_provider_deadline_checked_even_when_stream_keeps_responding`, `test_provider_oversized_response_rejected_before_becoming_evidence`; Airflow oversized/worker deadline cases |
| Metric direction, missing metrics, completed state, incompatible splits, registry absence | Ranking/cohort and registry cases in `tests/test_mlflow_tools.py` |
| Authentication, rejected credentials and approved DAG | Password/token/authentication and invalid-DAG cases in `tests/test_airflow_tools.py` |
| Service 5xx, limited safe retries, unknown write outcomes | `test_bounded_get_retry_and_filtered_dags`, `test_post_is_never_retried`; `test_only_one_training_post_attempt_even_if_response_unknown` |
| Real task states, failed/blocked distinction and missing logs | Status/diagnostic/identity cases in `tests/test_airflow_tools.py` |
| Malformed inputs/outputs and unavailable results cannot become facts | Wrong DVC containers; invalid output/citation and `test_unavailable_cannot_become_known_fact` in `tests/test_agent.py` |
| Unauthorized writes and namespace isolation | Registry/host/RBAC manifest boundary cases in `tests/test_kubernetes_tools.py` and `tests/test_agent.py` |
| No automatic retraining or unsupported recommendation | `test_model_cannot_authorize_training`, `test_exact_mandatory_prompt_enforces_readonly_assessment`, `test_retraining_recommendation_enum_rejects_unproven_request` |
| Redacted correlated structured logs | `test_invalid_arguments_and_unknown_names_are_absent_from_structured_logs`, Kubernetes log projection and Airflow diagnostic log filtering |
| Malformed inference input, absent model and failed predictions | Validation/readiness/output-integrity cases in `tests/test_inference.py` |
| Validation/gate failure blocks candidate approval | Malformed fixture, threshold, failed/missing gate and coherent approval cases in `tests/test_pipeline.py` |

## Actual service verification and limits

[Live adapter smoke export](evidence/reliability-live.json) records eleven
successful read responses against the working source: DVC status/list/diff,
MLflow experiments/selection/run details, recorded DVC lineage, Kubernetes
workloads/logs/health, and authenticated recent Airflow runs. The selected run's
model/source identity and Git/DVC lineage agree; at least two Pods were Ready.
The export identifies the base commit and the uncommitted source state at capture.
It is a direct adapter check, not a new LLM conversation or failure exercise.

No provider requests, training, deployment, cluster mutation or promotion were
performed during this audit. Existing container images and the running agent API
were not rebuilt/restarted; their reported application versions remain actual
historical versions. The new inference response redaction is validated against
the source application in pytest and will enter the image on its next rebuild.
The required controlled readiness investigation and final reproduction audit
remain separate work. Best F1 and historical controlled failures still do not
establish production readiness or a need for retraining.
