# Observed Airflow training and failure recovery

The [actual JSON export](airflow-dag-live.json) records authenticated Airflow 3.1.3
public API observations from 14 November 2026, plus task-attempt logs, persistent
receipts, MLflow results and before/after deployed identity. All run IDs share
prefix `engineering__20261114T132643_`. Training image source revision is
`4281a7a0bbdcbf5f45b9b49f751d95965e1c50c2`; later commits add verifier/evidence/docs.
These are explicit engineering runs, not agent conversation transcripts.

| Suffix | Observed DAG state | Tasks / retries | Approval |
| --- | --- | --- | --- |
| `smoke` | success | All six tasks success, one attempt each | Candidate approved; production_promoted=false |
| `validation_failure` | failed | Validation failed on attempts 1 and 2; all five downstream tasks upstream_failed | No evaluation or approval receipt |
| `gate_failure` | failed | First four tasks success; gate failed on attempts 1 and 2; approval upstream_failed | Candidate tag=false; no approval receipt |
| `recovery` | success | All six tasks success, one attempt each | Candidate approved; production_promoted=false |

For every executed attempt the API returned actual logs (HTTP 200). The export
retains tool/stage, status, duration and request ID only; untrusted raw log text is
omitted. Graph inspection under the installed SDK confirms every task has one
retry, all-success dependencies, five-minute execution timeout, max one active run
and the exact sequential edges. Unauthenticated DAG access returned HTTP 401;
authenticated reads, triggers, task states and logs succeeded.

## Validation investigation

Injected only `input_variant=malformed_validation_fixture`. The worker replaces
`sepal_length` with `missing_feature` in isolated in-memory validation bytes. The
normal DVC data and prepared read-only input remain unchanged. The actual validator
rejects this missing-column schema; both validation attempts logged errors. The
run failed, all downstream tasks became upstream_failed, and no model evaluation
or candidate approval was created. Diagnosis is a malformed input schema, rather
than a training or service outage. Resolution was a new canonical recovery run,
which completed all tasks successfully. The failed history remains intact.

## Quality-gate investigation

Injected a bounded valid training configuration, logistic regression `C=0.0001`.
Actual evaluation succeeded but observed accuracy **0.711111**, macro F1
**0.657079**, log loss **1.089769**, with 45 held-out rows. All three metric
thresholds failed the fixed `iris-candidate-v1` policy. The gate wrote failed
local/MLflow evidence on both attempts and failed; the approval task never ran.
The MLflow training run remains FINISHED (evaluation completed), while its gate
tag is failed and candidate_approved=false. A FINISHED MLflow run therefore cannot
be treated as approval. Resolution restored default `C=1.0` in a new canonical run.

The smoke and recovery models observed accuracy **0.911111**, macro F1
**0.910714**, log loss **0.214631** on the same deterministic 45-row cohort. These
passed the demonstration candidate thresholds. Both runs record data DVC MD5
`c53cf26bbf3cda572dfcbfeee37b4b37`, exact Git revisions, split hash, evaluation ID,
configuration and model ID. Three real newly logged models (smoke, rejected gate,
recovery) reloaded from HTTP-proxied MLflow artifacts inside the Airflow container.
This verifies container artifact access; the repeatedly used holdout does not
establish independent-test quality, drift, freshness or production readiness.

## Isolation, restoration and limits

The named Airflow volume is writable and persistent at `/opt/airflow`; prepared
input is a read-only mount. Scientific packages run separately in `/opt/training`
and the unchanged upstream Airflow dependency check passed. Image identity,
code revision, runtime version and mounts are exported. Existing auth storage and
MLflow volume were preserved. Worker environments contain no provider or cluster
credentials; no inference image was rebuilt or deployment changed.

Registry versions before and after remained `["1"]`; live Kubernetes service
health and application/model/data identity matched exactly before and after all
runs. The deployed original model remains healthy. Gate passage approves a
candidate only; neither success nor failure changes registry aliases or deploys.
The separate authorized Kubernetes readiness exercise is still pending.

Ordinary CI validation: Ruff lint/format and 176 pytest tests, with services
mocked. New cases cover malformed input without data mutation, lineage/hash
mismatch, immutable retry configuration, gate thresholds/nonfinite metrics,
missing/stale/failed gate receipts, approval without production promotion,
unauthorized stage selection, subprocess timeouts/unavailability/invalid output,
secret-free worker environments/logs, and sanitized evidence exports.
