# Actual integrated agent assessment

The [sanitized transcript](agent-live.json) records a real OpenRouter conversation
and actual service responses observed on 14 November 2026 at approximately
15:54–15:57 UTC. Request ID: `5efd2141-4aef-487a-8672-5e1460a895e4`.
The exact mandatory prompt is included in the export. Its acceptance checks were
computed from the captured response using `scripts/verify-agent.py --from-json`;
this validates saved observations without spending more free quota.

- Actual key metadata reported a free-tier account and the current model catalog
  contained the selected `openrouter/free` route. Six actual provider completions
  reported cost **0** each. Selected model IDs are recorded per turn. No fixed
  model availability or future quota is assumed.
- MLflow returned five recent comparable assignment runs. Selection by macro F1,
  maximizing, returned `a9cd0c64cb8a414496f185a1e69b2352`, F1
  `0.9107142857142857`, accuracy `0.9111111111111111`, log loss
  `0.2146311900295925`. The finite recent window, common cohort and small-split
  limitations are present in the actual selection result.
- A separate DVC tool retrieved that run's recorded parameters through the
  supported MLflow client and verified Git revision
  `4281a7a0bbdcbf5f45b9b49f751d95965e1c50c2`, dataset `data/iris.csv`, MD5
  `c53cf26bbf3cda572dfcbfeee37b4b37` against committed metadata.
- Kubernetes returned both real inference Pods Ready, actual Service endpoints,
  liveness/readiness and application/model metadata. Deployed run
  `f1aa8c88b5d645418f17e18898805dba` differs from the selected recent candidate.
  The host records this mismatch without deployment or retraining.
- Airflow returned the most recent authenticated agent-triggered workflow as
  successful. Earlier successful recovery/smoke and deliberate validation/gate
  failures are also visible. Those controlled failures do not establish current
  production degradation or a need to retrain.
- No `airflow_trigger_training` call or Kubernetes mutation was permitted or
  executed. The response separates resolved known facts, uncertainties,
  constrained recommendations, identity correlation and retraining policy.
  Retraining necessity remains **not established** without an approved freshness
  policy or current degradation measurements.

Two `submit_answer` attempts in the successful conversation failed host reference
validation, emitted sanitized policy events, and were corrected by the model.
Some read observations were repeated during correction. The export retains these
actual events and all responses rather than editing them into a fabricated
single-pass conversation. It remains one request with one correlation ID.

The [earlier attempt summary](agent-attempts.json) records two parser rejections
and provider deadline failures in both CLI and HTTP requests. OpenRouter included an extra `index` field
on valid native calls; projecting and validating the supported fields fixed that
interoperability issue, with a regression test. The timeout attempt retained real
observations and returned partial with no fabricated final facts. After reducing
the assessment's model-visible allowlist, the separate request above completed.
These attempts used free-only routing and did not trigger training. They are operational
limitations, not controlled assignment failure exercises.

`tests/test_agent.py` and `tests/test_provider.py` exercise selection/execution,
all-four correlation, missing lineage/coverage, unavailable systems, invalid
references/inputs/outputs, unauthorized writes, single-POST authorization,
budgets, provider failures/timeouts/quota, free-only routing and HTTP responses.
Ruff lint/format and the complete pytest suite passed locally before the bundled
commit. PR CI provides the independent Linux check for the exact commit.

The conversational API's real loopback `/livez` returned 200. A live HTTP `/chat`
request retained real tool observations and returned 503 after a later provider
deadline; its sanitized summary is included with the earlier attempts. This
also exposed overly broad query instructions, now separated from assessment. Mock-transport
FastAPI tests validate `/chat` execution, 503 evidence results and sanitized 422
errors. After separating narrow-query instructions, a second live HTTP `/chat` request
returned **200**, executing exactly one real Kubernetes health read and resolving
the deployed run ID into a factual citation. Both provider turns reported zero
cost. [Actual HTTP evidence](agent-api-live.json) also records real `/livez` 200
and sanitized invalid-input 422. The mandatory all-four conversation ran through
the same `Agent` host in the CLI.

Five complete demonstration conversations, the controlled readiness failure and
recovery, report and final audit remain separate scheduled work.
