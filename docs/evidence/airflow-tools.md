# Observed authenticated Airflow tools

[Sanitized tool export](airflow-tools-live.json), 14 November 2026, records all six
registered tools using the real Airflow 3.1.3 public API. These are explicit
engineer-invoked tool operations; LLM conversations remain a later milestone.

- Unauthenticated `/api/v2/dags` returned **401**. The installed `/openapi.json`
  contained every endpoint used by the adapter. Authenticated DAG listing returned
  `assignment_training`, unpaused, without import errors. Recent-run listing
  returned actual success and controlled-failure histories.
- The default read-only host rejected a trigger. A write-enabled host still
  rejected an unapproved DAG. Both returned `invalid_request` without HTTP writes.
- One explicitly authorized canonical POST returned
  **`agent__20261114T145452_c2af24b9`**, initially **queued**. Actual reads observed
  running and then **success**. All six tasks returned **success**, try number 1,
  max tries 1. Failed-task lookup returned an empty failed list for this completed
  run. Validation attempt 1 logs returned a real successful structured event.
- Fresh failed-task reads identified `quality_gate` and `validation` respectively
  in prior `engineering__20261114T132643_gate_failure` and
  `engineering__20261114T132643_validation_failure`. Both failed tasks had actual
  try number **2**. Downstream tasks were separately reported as `upstream_failed`.
  Attempt 2 log reads returned structured **error** events with the corresponding
  workflow ID. These histories were intentional tests, not production degradation.

Initial verification stopped because the API reported training task duration
**-55.828 seconds**. Its start/end fields were ordered, and its state was success.
The original unavailable response is retained in the export. The schema was
corrected to preserve finite reported durations with an explicit anomaly flag,
and a regression test was added. Verification resumed the **same run**, without
another trigger, and passed. The anomaly's cause has not been established; this
is not reliable latency evidence. Other task durations are likewise reported
values, not independently measured or recomputed task runtimes.

Logs export only known structured stage fields. Arbitrary text, rendered inputs,
DAG conf, passwords, tokens and continuation tokens are excluded. A missing log
page remains unknown while retaining independently retrieved task facts. The
API supports bounded polling and list/log truncation; no state is inferred from
an empty list or from a timeout.

Local `make check` passed Ruff lint/format and **227 pytest tests**, including
**51 Airflow adapter cases** for authorization, allowlists, credentials, schema
errors, HTTP failures, bounded retries/polling, worker timeout, identity mismatch,
selection of failed versus blocked tasks, log filtering and timing anomalies.
CI uses mocks; the JSON export above is the separate live observation evidence.

The running training image still records source revision
`4281a7a0bbdcbf5f45b9b49f751d95965e1c50c2`; this milestone changes host tools and
does not rebuild the execution image. Candidate approval does not deploy or
promote a production model. Conversational authorization, all-four-service
reasoning and final assignment acceptance remain pending.
