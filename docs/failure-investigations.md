# Deliberate failure investigations

## 1. Invalid training input blocks downstream work

**Injection and root cause.** The engineering DAG test used the isolated
`malformed_validation_fixture` variant, replacing `sepal_length` with
`missing_feature` in an in-memory copy. The canonical DVC bytes were preserved.
The exact feature schema therefore failed validation; this was an intended data
contract failure, not observed model degradation.

**Observed impact.** Run `engineering__20261114T132643_validation_failure` failed
at `validation` after two attempts. Preprocessing, training, evaluation, quality
gate and candidate approval became `upstream_failed` with zero attempts. No
trained model or candidate approval was produced by that run.

**Agent diagnosis.** [The real diagnostic conversation](evidence/validation-failure-agent.json)
retrieved failed tasks, attempt-2 execution/log diagnostics and the actual recovery
run. The response cites those observations and does not initiate training.
[Direct diagnostic observations](evidence/validation-failure-diagnostics.json)
and the [original run/fixture/gate export](evidence/airflow-dag-live.json) preserve
the underlying evidence. Structured logs identify the failed stage and request;
full exception details remain in the authorized Airflow UI.

**Resolution and verification.** Run `engineering__20261114T132643_recovery`
used canonical input and completed all six stages successfully. The independent
quality-gate failure in the original export additionally proves that failed
evaluation thresholds block approval even after training succeeds. Fix data or
quality before retrying; do not bypass dependencies or promote a failed candidate.

## 2. Wrong readiness path removes healthy processes from Service routing

**Scope and confirmation.** The explicit engineering command
`verify-readiness-failure.py --confirm 'inject readiness failure in mlops-agent'`
touched only the owned `mlops-agent/inference` Deployment. It saved the original
probe and rollout strategy and restored them in `finally`. It is not callable
by the LLM; agent RBAC stayed read-only throughout.

**Injection and root cause.** The probe path was changed from `/readyz` to
`/injected-readiness-failure`. A temporary Recreate strategy made the controlled
failure observable across both replicas rather than leaving old healthy backends
serving during a normal zero-unavailable rollout. The application did not expose
the injected path, so probes received HTTP 404. This was configuration failure,
not missing weights, training degradation or a liveness restart.

**Observed impact and diagnosis.** [Actual before/during/after observations](evidence/readiness-failure-live.json)
show two Ready replicas before injection, zero during failure, no Ready Service
endpoints, Pod `Unhealthy` events, and structured 404 request logs. Liveness still
returned 200. Service health returned `unavailable`; the tool did not invent a
successful response. The real LLM diagnosis cited workload probes, endpoint
readiness, Pod events and logs. Its status is `partial` because one health read
was unavailable, while its resolved diagnostic facts and recommendation are
retained. No mutation or retraining was initiated by the agent.

**Resolution and verification.** The original strategy and readiness probe were
restored. A bounded rollout wait and actual workload/health reads verified two
Ready replicas and successful Service health. [The final deployment export](evidence/kubernetes-live.json)
also verifies healthy routing and predictions after the reviewed image update.

**Reliability lesson.** Probe failure changes traffic eligibility; it does not
necessarily restart a process. Diagnose conditions, endpoints, configured paths
and logs together. A [first provider attempt](evidence/readiness-failure-attempt.json)
could not finish valid structured output; it is preserved as a failed attempt.
The subsequent diagnostic capture completed evidence referencing and truthfully
retained partial Service health rather than concealing the outage.
