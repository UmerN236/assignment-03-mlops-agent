# Demonstration and engineering defense

## Demonstration order

1. Run `make check` and `make smoke`. Explain mocked ordinary CI versus live
   integration evidence, show the GitHub PR checks, and identify the running
   source/model with the version tool rather than assuming latest Git is deployed.
2. Open [the five conversation exports](evidence/conversations/README.md). Show
   each prompt, request ID, native model turns, exact tool arguments/results and
   resolved facts. Use `make verify-submission` to validate their references offline.
3. Show the selected run in MLflow and its recorded dataset Git/DVC hash. Compare
   actual metric direction and evaluation cohort; highest F1 is only a candidate.
4. Show Airflow's successful agent-triggered run and its task statuses. Contrast
   the failed validation/quality runs and blocked candidate approval.
5. Show two Ready replicas, ClusterIP/endpoints, probes/resources and prediction
   output. Explain the readiness failure evidence and recovered state.
6. Run the mandatory prompt live if the free provider has quota, or inspect its
   complete exported transcript. It must not trigger training or deployment.

## Design choices to explain

- Supported MLflow APIs preserve typed run/model information; no UI scraping.
- DVC content hashes and Git references identify data separately from code.
- Structured tool proposals remain untrusted until host schema/permission checks.
  The model chooses tools; the host, not the model, authorizes writes and resolves facts.
- A stable host-generated training run ID prevents accidental duplicate POSTs.
  Unknown outcomes require reading that ID before retrying.
- Airflow handles dependency/retry/gate semantics; MLflow records experiments;
  Kubernetes handles serving health and replica routing. They have different jobs.
- Inference images contain an explicit trusted model and need no live MLflow
  access. Source plus complete bundle provenance determine image identity.
- Readiness controls traffic; liveness controls restart eligibility. Two replicas
  on one kind node do not establish node-level high availability.
- No drift/freshness policy is configured, so retraining necessity remains unknown.
  Candidate/deployed differences are reported as observations, not automatic actions.

## Diagnose an unexpected failure

Start with the failed request ID and timestamps. Identify which tool returned
unavailable/error; preserve other observations and avoid invented results.

For a missing dataset, inspect the committed pointer, cache/remote and recipe;
recover in an isolated checkout. For MLflow, inspect health, experiment/run ID,
recorded provenance and artifact transport. For Airflow, distinguish authentication,
paused/import-error DAGs, queued/running states, actual failed task attempts and
logs. For Kubernetes, compare desired/Ready replicas, Pod conditions/restarts,
events, Service endpoints, configured probe paths and application version.

Correct the evidenced root cause, repeat a bounded read or explicitly authorized
operation, and verify the recovery. An expired restricted token needs engineer
refresh; the agent must not fall back to administrator credentials. A provider
429 or malformed function call is a provider limitation, not service health.
Use the stored real evidence if live free quota is unavailable during evaluation.

## Reviewer handoff

The repository is public. Submit its URL and identify the reviewed submission tag;
[the submission page](../SUBMISSION.md) maps the required artifacts. Local volumes
and credentials are not shared by Git; reviewers should follow
[reproduction](reproduction.md) with their own provider key. Never submit `.env`,
kubeconfigs, service-account tokens, raw authentication responses or local notes.
